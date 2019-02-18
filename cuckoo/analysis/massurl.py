# Copyright (C) 2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import Queue
import logging
import threading
import time

from cuckoo.common.abstracts import AnalysisManager
from cuckoo.common.exceptions import (
    CuckooMachineSnapshotError, CuckooMachineError, CuckooGuestError,
    CuckooGuestCriticalTimeout, RealtimeBlockingExpired, RealtimeError
)
from cuckoo.common.objects import Analysis
from cuckoo.core.database import (
    TASK_REPORTED, TASK_FAILED_ANALYSIS, TASK_ABORTED
)
from cuckoo.core.guest import GuestManager
from cuckoo.core.log import task_log_start, task_log_stop
from cuckoo.core.plugins import RunAuxiliary
from cuckoo.core.realtime import EventClient, RealTimeHandler, RealTimeMessages
from cuckoo.core.resultserver import ResultServer
from cuckoo.massurl.urldiary import URLDiary, URLDiaries

log = logging.getLogger(__name__)

class MassURL(AnalysisManager):

    supports = ["massurl"]
    URL_BLOCKSIZE = 5
    SECS_PER_BLOCK = 20

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
        self.URL_BLOCKSIZE = self.task.options.get(
            "urlblocksize", self.URL_BLOCKSIZE
        )
        self.SECS_PER_BLOCK = self.task.options.get(
            "blocktime", self.SECS_PER_BLOCK
        )
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
            self.curr_block.get(self.curr_block.keys().pop(0)).get("target_obj")
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
        self.detection_events = Queue.Queue()

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
        self.route.route_network()

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

            self.request_scheduler_action(for_status="newurlblock")

            # Start with handling incoming onemon events, as the first block
            # of URLs has been submitted with the task options
            handled_events = self.handle_detection_events()

            # TODO extract HTTP requests from PCAP and add them to the
            # URL diary as requested URLs and related streams.

            if handled_events:
                self.request_scheduler_action(for_status="aborted")
                return

            # Store URL diaries
            for url, info in self.curr_block.iteritems():
                URLDiaries.store_diary(info.get("diary").dump())

            # Acquire the next block of URLs according to the defined URL
            # blocksize
            self.curr_block = self.new_target_block()
            if not self.curr_block:
                continue

            try:
                self.rt.send_command_blocking(
                    RealTimeMessages.start_package(
                        target=self.curr_block.keys(), category="url",
                        package=self.task.package,
                        options=self.task.options,
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

    def onemon_callback(self, message):
        log.info("INCOMING ONEMON EVENT")
        task_id = message["body"].get("taskid")
        if not task_id or task_id != self.task.id:
            return

        for k in ("description", "ioc", "signature"):
            if k not in message["body"]:
                return

        self.detection_events.put(message)

    def handle_detection_events(self):
        # New queue for a new batch, to be sure it is empty
        self.detection_events = Queue.Queue()
        # Inform event subscribers a new batch is being opened in the VM
        self.ev_client.send_event(
            "massurltask", body={
                "taskid": self.task.id,
                "status": self.analysis.status,
                "action": "newbatch"
            }
        )

        time.sleep(self.SECS_PER_BLOCK)
        # If some event occured, increase wait time a to gather some more info
        if not self.detection_events.empty():
            time.sleep(self.SECS_PER_BLOCK)

        # Request the analyzer to stop all running analysis packages
        try:
            self.rt.send_command(RealTimeMessages.stop_all_packages())
        except RealtimeError as e:
            log.error("Error sending real-time package stop command. %s", e)

        # Tell onemon to stop processing this batch
        self.ev_client.send_event(
            "massurltask", body={
                "taskid": self.task.id,
                "status": self.analysis.status,
                "action": "batchclosed"
            }
        )

        num_events = self.detection_events.qsize()
        # If no events were sent by onemon, no signatures were triggered.
        # Continue analysis.
        if not num_events:
            return False

        log.info("Detected %d events in task #%d", num_events, self.task.id)
        # Collect all triggered signatures from the queue
        sigs = []
        for e in range(num_events):
            ev = self.detection_events.get(block=False)["body"]
            sigs.append({
                "signature": ev.get("signature"),
                "description": ev.get("description"),
                "ioc": ev.get("ioc")
            })

        # TODO: store sigs in a URL diary when it is known to which URL
        # they belong or mark a URL as 'potentially triggered sig X' until
        # it is known what URL did really trigger a sig?
        if len(self.curr_block) == 1:
            info = self.curr_block.get(self.curr_block.keys().pop(0))
            info.get("diary").add_signature(sigs)
            diary_id = URLDiaries.store_diary(info.get("diary").dump())
            # Send events to massurl scheduler if there are any
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
            # Send events to massurl scheduler if there are any
            self.ev_client.send_event(
                "massurldetection", body={
                    "taskid": self.task.id,
                    "status": "aborted",
                    "candidates": self.curr_block.keys(),
                    "signatures": sigs
                }
            )

        return True

    def run(self):
        task_log_start(self.task.id)
        if not self.ev_client.start(maxtries=2):
            log.error(
                "Could not connect to Cuckoo event messaging client. Aborting"
            )
            self.set_analysis_status(Analysis.FAILED)
            return

        # Hand the event client to the analysis status object, so each
        # status change will be sent as an event.
        self.analysis.event_client = self.ev_client

        # Tell the client to ask the event server to send all events of
        # type 'signature'. These events will be sent by onemon.
        self.ev_client.subscribe(self.onemon_callback, "signature")
        try:
            if self.start_run():
                self.set_analysis_status(Analysis.RUNNING)
                self.gm_wait_th.start()
                self.run_analysis()

        except Exception as e:
            log.exception(
                "Failure during analysis run of task #%s. %s", self.task.id, e
            )
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

    def on_status_newurlblock(self, db):
        """When a new block of URLs has been sent to the VM, update their rows
        in the database. This way we can keep track of which were and were not
        analyzed in case of an abort/crash/detection and a re-submit
         is required."""
        log.debug("Uploaded new block of %d URLs", len(self.curr_block))
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
