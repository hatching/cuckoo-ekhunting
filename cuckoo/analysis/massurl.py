# Copyright (C) 2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import Queue
import logging
import threading
import time
import traceback

from cuckoo.common.abstracts import AnalysisManager
from cuckoo.common.exceptions import (
    CuckooMachineSnapshotError, CuckooMachineError, CuckooGuestError,
    CuckooGuestCriticalTimeout, RealtimeError
)
from cuckoo.common.objects import Analysis
from cuckoo.common.config import config
from cuckoo.core.database import (
    TASK_REPORTED, TASK_FAILED_ANALYSIS, TASK_ABORTED
)
from cuckoo.core.guest import GuestManager
from cuckoo.core.log import task_log_start, task_log_stop
from cuckoo.core.plugins import RunAuxiliary
from cuckoo.core.realtime import EventClient, RealTimeHandler, RealTimeMessages
from cuckoo.core.resultserver import ResultServer
from cuckoo.massurl.urldiary import URLDiary, URLDiaries, RequestFinder
from cuckoo.processing.behavior import BehaviorAnalysis
from cuckoo.processing.dumptls import TLSMasterSecrets
from cuckoo.processing.network import NetworkAnalysis

log = logging.getLogger(__name__)

class MassURL(AnalysisManager):

    supports = ["massurl"]
    URL_BLOCKSIZE = 5
    SECS_PER_BLOCK = 25

    def init(self, db):
        # If for some reason the task dir does not exist, stop the analysis
        # because it should have been created upon submission
        if not self.task.dir_exists():
            log.error(
                "Task directory for task #%s does not exist", self.task.id
            )
            return False

        if not URLDiaries.init_done:
            URLDiaries.init()

        self.curr_block = self.new_target_block()
        if not self.curr_block:
            log.error("Empty target list, cannot proceed.")
            return False

        self.rt = RealTimeHandler()
        self.ev_client = EventClient()
        self.URL_BLOCKSIZE = int(self.task.options.get(
            "urlblocksize", self.URL_BLOCKSIZE
        ))
        self.SECS_PER_BLOCK = int(self.task.options.get(
            "blocktime", self.SECS_PER_BLOCK
        ))
        self.aborted = False
        self.completed = False

        # Write task to disk in json file
        self.task.write_task_json()
        self.build_options(options={
            "category": "url",
            "target": ",".join(self.curr_block.keys()),
            "enforce_timeout": True,
            "timeout": len(self.task.targets) * self.SECS_PER_BLOCK * 3
        })

        self.guest_manager = GuestManager(
            self.machine.name, self.machine.ip, self.machine.platform,
            self.task, self, self.analysis,
            self.curr_block.get(
                self.curr_block.keys().pop(0)
            ).get("target_obj")
        )

        self.aux = RunAuxiliary(
            self.task.task_dict, self.machine, self.guest_manager
        )

        # The wait/agent status checking etc is run in a separate thread. This
        # allows the analysis manager to perform other actions while the
        # analysis is running
        self.gm_wait_th = threading.Thread(
            target=self.guest_manager.wait_for_completion
        )
        self.gm_wait_th.daemon = True
        self.detection_events = Queue.Queue()
        self.netflow_events = Queue.Queue()
        self.realtime_finished = False
        self.requestfinder = RequestFinder(self.task.id)

        return True

    def set_target(self, targets):
        blocksize = int(self.task.options.get(
            "urlblocksize", self.URL_BLOCKSIZE
        ))
        self.targets = []
        for i in range(0, len(targets), blocksize):
            self.targets.append(targets[i:i + blocksize])

    def new_target_block(self):
        block = {}
        if self.targets:
            for t in self.targets.pop(0):
                diary = URLDiary(t.target, t.sha256)
                block[t.target] = {
                    "diary": diary,
                    "target_obj": t
                }
            return block
        return {}

    def start_run(self):
        self.set_analysis_status(Analysis.STARTING)
        log.info(
            "Starting analysis (task #%s, options: '%s') type '%s'. %d URLs",
            self.task.id, self.options["options"], self.task.type,
            len(self.task.targets)
        )

        ResultServer().add_task(self.task.db_task, self.machine, self.rt)
        self.aux.start()

        try:
            self.machinery.start(self.machine.label, self.task.db_task)
        except CuckooMachineSnapshotError as e:
            log.error(
                "Unable to restore to the snapshot for this Virtual Machine! "
                "Does your VM have a proper Snapshot and can you revert to it "
                "manually? VM: %s, error: %s",
                self.machine.name, e
            )
            return False
        except CuckooMachineError as e:
            log.error(
                "Error starting Virtual Machine! VM: %s, error: %s",
                self.machine.name, e
            )
            return False

        # Enable network routing
        if not self.route.route_network():
            log.error("Failed to use chosen route for the analysis")
            self.ev_client.send_event(
                "massurltaskfailure", {
                    "taskid": self.task.id,
                    "error": "Failed to use chosen route '%s'. "
                             "Inspect the log" % self.route.route,
                    "status": self.analysis.status
                }
            )
            return False

        # By the time start returns it will have fully started the Virtual
        # Machine. We can now safely release the machine lock.
        self.release_machine_lock()

        # Request scheduler action for status 'starting'
        self.request_scheduler_action(Analysis.STARTING)

        try:
            self.guest_manager.start_analysis(
                self.options, self.task.options.get("monitor", "latest")
            )
        except CuckooGuestCriticalTimeout as e:
            log.error(
                "Critical timeout reached while starting virtual"
                " machine. %s", e
            )
            return False
        except CuckooGuestError as e:
            log.error("Failed to prepare guest for analysis: %s", e)
            return False

        return self.analysis.status == Analysis.STARTING

    def stop_and_wait(self):
        if self.rt.sock:
            try:
                # Use the realtime protocol to request the analyzer to stop. So
                # that the analysis, logs etc can be closed gracefully.
                self.rt.send_command_blocking(
                    RealTimeMessages.stop_analyzer(), maxwait=3
                )
            except RealtimeError:
                log.warning("No response from analyzer to stopping request")

        self.set_analysis_status(Analysis.STOPPING)

        # Stop all Auxiliary modules
        self.aux.stop()

        # Wait for the guest manager wait to stop before stopping the machine.
        # We want any exception messages to be retrieved from the agent.
        if self.gm_wait_th.is_alive():
            self.gm_wait_th.join(timeout=6)

        # Stop the analysis machine.
        try:
            self.machinery.stop(self.machine.label)
        except CuckooMachineError as e:
            log.warning(
                "Unable to stop machine %s: %s", self.machine.label, e,
            )

        # After all this, we can make the ResultServer forget about the
        # internal state for this analysis task.
        ResultServer().del_task(self.task.db_task, self.machine)

        # Drop the network routing rules if any.
        self.route.unroute_network()

    def run_analysis(self):
        while self.curr_block:
            if not self.gm_wait_th.is_alive():
                return

            log.debug("Uploaded new block of %d URLs", len(self.curr_block))

            pkg_info = {}
            tries = len(self.curr_block) * 10
            while not pkg_info:
                try:
                    pkg_info = self.rt.send_command_blocking(
                        RealTimeMessages.list_packages(),
                        maxwait=len(self.curr_block) * 2
                    )
                except RealtimeError as e:
                    log.error(
                        "No response from guest or it failed to send analysis "
                        "package information. %s", e
                    )
                    return

                tries -= 1
                if not pkg_info and tries <= 0:
                    log.error(
                        "Analyzer is not returning target PIDs. It might have "
                        "failed to start the targets."
                    )
                    return
                time.sleep(1)

            pids_targets = {
                int(pid): target for p in pkg_info
                for pid, target in p.get("pids").items()
            }

            # Give the URLs some time to load and remain opened
            time.sleep(self.SECS_PER_BLOCK)

            # Request the analyzer to stop all running analysis packages
            try:
                self.rt.send_command(RealTimeMessages.stop_all_packages())
            except RealtimeError as e:
                log.error(
                    "Error sending real-time package stop command. %s", e
                )

            # Ask realtime to process the generated onemon protobuf file.
            signature_events = self.handle_events(pids_targets)

            # The end of the URL block is reached, have the scheduler
            # do the database operations
            self.request_scheduler_action(for_status="stopurlblock")

            # Store URL diaries
            if len(self.curr_block) > 1:
                for url, info in self.curr_block.iteritems():
                    URLDiaries.store_diary(info.get("diary"))

            if signature_events:
                self.request_scheduler_action(for_status="aborted")
                return

            # Acquire the next block of URLs according to the defined URL
            # blocksize
            self.curr_block = self.new_target_block()
            if not self.curr_block:
                continue

            try:
                self.rt.send_command_blocking(
                    RealTimeMessages.start_package(
                        target=self.curr_block.keys(), category="url",
                        package=self.task.package, options=self.task.options,
                        respond=True
                    ), maxwait=len(self.curr_block) * 10
                )
            except RealtimeError as e:
                log.error(
                    "No response from guest or it failed to open new URLs. "
                    "Error: %s", e
                )
                return

        # The loop was broken because there are no targets left. This means
        # the analysis was completed.
        self.completed = True

    def extract_requests(self, pid_target):
        flow_target = {}
        flows = {}
        ppid_pid = {}
        for x in range(self.netflow_events.qsize()):
            flow, pid, ppid = self.netflow_events.get(block=False)

            if pid not in flows:
                flows[pid] = []
            flows[pid].append(flow)

            if ppid not in ppid_pid:
                ppid_pid[ppid] = set()
            ppid_pid[ppid].add(pid)

        def walk_childprocs(pid, t):
            for flow in flows.get(pid, []):
                flow_target[flow] = t

            for child in ppid_pid.get(pid, []):
                walk_childprocs(child, t)
                
        for pid, target in pid_target.iteritems():
            walk_childprocs(pid, target)

        reports = self.requestfinder.process(flow_target)
        for target_url, report in reports.iteritems():
            log.debug("Traffic extracted for %s", target_url)
            target_helpers = self.curr_block.get(target_url)
            diary = target_helpers.get("diary")
            diary.set_request_report(report)

    def handle_events(self, pid_target):
        # New queue for a new batch, to be sure it is empty
        self.detection_events = Queue.Queue()
        self.netflow_events = Queue.Queue()
        self.realtime_finished = False
        self.realtime_finished = False

        # Tell onemon to process results.
        self.ev_client.send_event(
            "massurltask", body={
                "taskid": self.task.id
            }
        )

        # If IE was used, TLS master secrets van be extracted.
        # If not package is supplied, the analyzer will use IE.
        if not self.task.package or self.task.package.lower() == "ie":
            if config("massurl:massurl:extract_tls"):
                log.debug(
                    "Running TLS key extraction for task #%s", self.task.id
                )
                self.task.process(
                    reporting=False, signatures=False, processing_modules=[
                        BehaviorAnalysis, NetworkAnalysis, TLSMasterSecrets
                    ]
                )

        waited = 0
        while not self.realtime_finished:
            if waited >= 60:
                log.error(
                    "Timeout for realtime onemon processor reached. No results"
                    " received. Stopping analysis of URL current block: %r",
                    self.curr_block.keys()
                )
                break
            waited += 0.5
            time.sleep(0.5)

        if self.netflow_events.qsize():
            log.debug("Running request extraction for task: #%s", self.task.id)
            self.extract_requests(pid_target)

        # If no events were sent by Onemon, no signatures were triggered.
        # Continue analysis.
        if self.detection_events.qsize():
            self.handle_signature_events()
            return True

        return False

    def handle_signature_events(self):
        num_events = self.detection_events.qsize()

        log.info(
            "%d realtime signature triggered for task #%d", num_events,
            self.task.id
        )
        # Collect all triggered signatures from the queue
        sigs = []
        for x in range(num_events):
            ev = self.detection_events.get(block=False)
            sigs.append({
                "signature": ev.get("signature"),
                "description": ev.get("description"),
                "ioc": ev.get("ioc")
            })

        # A signature was triggered while only a single URL was opened. Update
        # and store the URL diary, and send a detection event.
        if len(self.curr_block) == 1:
            diary = self.curr_block.itervalues().next().get("diary")
            diary.add_signature(sigs)
            diary_id = URLDiaries.store_diary(diary)

            self.ev_client.send_event(
                "massurldetection", body={
                    "taskid": self.task.id,
                    "status": "aborted",
                    "candidates": self.curr_block.keys(),
                    "signatures": sigs,
                    "diary_id": diary_id
                }
            )

        else:
            # Multiple URLs were opened while signatures were triggered. Send
            # a detection event with all URLs that were opened. The massurl
            # scheduler will create a new task with only these URLs.
            self.ev_client.send_event(
                "massurldetection", body={
                    "taskid": self.task.id,
                    "status": "aborted",
                    "candidates": self.curr_block.keys(),
                    "signatures": sigs
                }
            )

    def run(self):
        task_log_start(self.task.id)
        if not self.ev_client.start(maxtries=2):
            log.error(
                "Could not connect to Cuckoo event messaging client. Aborting"
            )
            self.set_analysis_status(Analysis.FAILED)
            return

        # Tell the client to ask the event server to send all events of
        # type 'signature' and 'netflow'. These events will be sent by onemon.
        self.ev_client.subscribe(self.realtime_sig_cb, "signature")
        self.ev_client.subscribe(self.realtime_netflow_cb, "netflow")
        self.ev_client.subscribe(self.realtime_finished_cb, "finished")

        try:
            if self.start_run():
                self.set_analysis_status(Analysis.RUNNING)
                self.gm_wait_th.start()
                self.run_analysis()

        except Exception as e:
            log.exception(
                "Failure during analysis run of task #%s. %s", self.task.id, e
            )
            try:
                self.ev_client.send_event(
                    "massurltaskfailure", {
                        "taskid": self.task.id,
                        "error": "%s" % traceback.format_exc(2),
                        "status": self.analysis.status
                    }
                )
            except Exception as e:
                log.exception("Failed to send failure notification event")

        finally:
            try:
                self.stop_and_wait()
            except Exception as e:
                log.exception(
                    "Failure while stopping analysis run of task #%s: %s",
                    self.task.id, e
                )

        if self.completed or self.aborted:
            self.set_analysis_status(Analysis.STOPPED, wait=True)
        else:
            self.set_analysis_status(Analysis.FAILED, wait=True)

    def realtime_sig_cb(self, message):
        """Handle incoming signature events from the realtime processor"""
        log.info("INCOMING ONEMON EVENT")
        task_id = message["body"].get("taskid")
        if not task_id or task_id != self.task.id:
            return

        for k in ("description", "ioc", "signature"):
            if k not in message["body"]:
                return

        self.detection_events.put(message["body"])

    def realtime_netflow_cb(self, message):
        """Handle incoming netflow events from the realtime processor"""
        task_id = message["body"].get("taskid")
        if not task_id or task_id != self.task.id:
            return

        for k in ("srcip", "srcport", "dstip", "dstport", "pid", "ppid"):
            if k not in message["body"]:
                return

        flow = message["body"]
        self.netflow_events.put(
            (
                (
                    flow.get("srcip"), flow.get("srcport"), flow.get("dstip"),
                    flow.get("dstport")
                ),  flow.get("pid"), flow.get("ppid")
            )
        )

    def realtime_finished_cb(self, message):
        """Handle incoming finish events from the realtime processor"""
        task_id = message["body"].get("taskid")
        if not task_id or task_id != self.task.id:
            return

        self.realtime_finished = True

    def on_status_failed(self, db):
        """The mass url analysis failed"""
        # What should we do it failed? How can be prevent redundant work and
        # Be sure the mass url scheduler knows this task failed?
        if self.machine.locked:
            log.debug("Releasing machine lock on %s", self.machine.label)
            self.machine = self.machinery.release(self.machine.label)

    def on_status_starting(self, db):
        """Is executed by the scheduler on analysis status starting
        Stores the chosen route in the db."""
        log.info(
            "Using route '%s' for task #%s", self.route.route, self.task.id
        )
        # Propagate the taken route to the database.
        db.set_route(self.task.id, self.route.route)

        # Store used machine in the task
        db.set_machine(self.task.id, self.machine.name)

    def on_status_stopurlblock(self, db):
        """When a new block of URLs has finished, update their rows
        in the database. This way we can keep track of which were and were not
        analyzed in case of an abort/crash/detection and a re-submit
         is required."""
        updated = []
        for t in self.curr_block:
            target_obj = self.curr_block[t].get("target_obj")
            target_obj["analyzed"] = True
            updated.append(target_obj.target_dict)
        db.update_targets(updated)

    def on_status_aborted(self, db):
        """This status is reached when a potentially malicious action is
        detected and the remaining URLs should be analyzed in a new task"""
        log.info("Task #%s aborted", self.task.id)
        self.aborted = True
        self.task.set_status(TASK_ABORTED)
        self.task.write_task_json()

    def on_status_stopped(self, db):
        """Executed by the scheduler when the analysis reaches the stopped
        status."""
        if self.machine.locked:
            log.debug("Releasing machine lock on %s", self.machine.label)
            self.machine = self.machinery.release(self.machine.label)

    def finalize(self, db):
        self.ev_client.stop()
        self.task.set_latest()
        self.release_machine_lock()
        if self.analysis.status != Analysis.STOPPED:
            log.warning(
                "Analysis status is '%s' after exit.", self.analysis.status
            )
            self.task.write_task_json(status=TASK_FAILED_ANALYSIS)
            self.task.set_status(TASK_FAILED_ANALYSIS)

        if self.completed:
            log.info("Setting task #%d to reported", self.task.id)
            self.task.write_task_json(status=TASK_REPORTED)
            self.task.set_status(TASK_REPORTED)

        task_log_stop(self.task.id)
