# Copyright (C) 2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import os
import time

from cuckoo.common.abstracts import AnalysisManager
from cuckoo.common.config import config
from cuckoo.common.constants import faq
from cuckoo.common.exceptions import (
    CuckooMachineSnapshotError, CuckooMachineError, CuckooGuestError,
    CuckooGuestCriticalTimeout
)
from cuckoo.common.objects import Analysis
from cuckoo.core.database import (
    TASK_COMPLETED, TASK_REPORTED, TASK_FAILED_ANALYSIS, TASK_FAILED_PROCESSING
)
from cuckoo.core.guest import GuestManager
from cuckoo.core.log import task_log_start, task_log_stop, logger
from cuckoo.core.plugins import RunAuxiliary
from cuckoo.core.resultserver import ResultServer
from cuckoo.core.target import Target

import gevent
import json

log = logging.getLogger(__name__)

def ping_test(rt):
    def result(msg):
        log.debug("got response: %r", msg)

    for _ in range(3):
        rt.send_command(result, {"cmd":"ping"})
        gevent.sleep(3)

class RealTimeHandler:
    def __init__(self, task_id, am):
        self.task_id = task_id
        self.am = am
        self.msg_id = 1
        self.commands = {}

        self.sendq = gevent.queue.Queue()

    def stop(self):
        self.sendq.put(None)
        # TODO: probably need to close the socket here as well

    def start(self, sock):
        """RealTime connection has been established"""
        log.debug("RealTimeHandler start")
        if self.sock:
            raise NotImplementedError("RealTime connection reopened")
        self.sock = sock
        gevent.spawn(self.send_thread)

    def send_thread(self):
        while True:
            msg = self.sendq.get()
            if msg is None:
                break
            # TODO: gracefully deal with socket errors
            # TODO: think about write timeout
            self.sock.sendall(msg)

    def on_message(self, msg):
        response_id = msg.get("rid")
        if response_id is not None:
            # This is a response to a previous message
            func = self.commands.pop(response_id)
            if func:
                log.debug("Calling response handler %s -> %r", response_id, func)
                func(msg)
        else:
            # TODO future work: request coming *from* guest
            pass

    def send_command(self, callback, msg):
        # TODO with lock {{{
        id = self.msg_id
        self.msg_id += 1
        # }}}
        msg["id"] = id
        if callback:
            self.commands[id] = callback
        self.sock.write(json.dumps(msg))

class Regular(AnalysisManager):

    supports = ["regular", "baseline", "service"]

    def init(self, db):
        """Executed by the scheduler. Prepares the analysis for starting."""
        # Used at the processing and final stage to determine is processing
        # was run and successful
        self.processing_success = False

        # If for some reason the task dir does not exist, stop the analysis
        # because it should have been created upon submission
        if not self.task.dir_exists():
            log.error(
                "Task directory for task #%s does not exist", self.task.id
            )
            return False

        self.guest_manager = GuestManager(
            self.machine.name, self.machine.ip, self.machine.platform,
            self.task, self, self.analysis, self.target
        )

        self.aux = RunAuxiliary(
            self.task.task_dict, self.machine, self.guest_manager
        )

        # Check if the current task has remotecontrol
        # enabled before starting the machine.
        self.control_enabled = (
            config("cuckoo:remotecontrol:enabled") and
            "remotecontrol" in self.task.options
        )

        # Write task to disk in json file
        self.task.write_task_json()

        if not self.target.target:
            self.build_options()
            return True

        options = {
            "category": self.target.category,
            "target": self.target.target
        }

        if self.target.is_file:
            if not self.target.copy_exists():
                log.error(
                    "The file to submit '%s' does not exist",
                    self.target.copied_binary
                )
                return False

            if not self.target.helper.is_readable():
                log.error(
                    "Unable to read target file %s, please check if it is"
                    " readable for the user executing Cuckoo Sandbox",
                    self.target.copied_binary
                )
                return False

            task_options = {}
            package, activity = self.target.helper.get_apk_entry()
            if package and activity:
                task_options["apk_entry"] = "%s:%s" % (package, activity)

            options.update({
                "file_name": os.path.basename(self.target.target),
                "file_type": self.target.helper.get_type(),
                "pe_exports": ",".join(
                    self.target.helper.get_exported_functions()
                ),
                "options": task_options
            })

        self.build_options(options=options)

        return True

    def run(self):
        """Starts the analysis manager thread."""
        task_log_start(self.task.id)
        analysis_success = False

        try:
            analysis_success = self.start_and_wait()

            # See if the analysis did not fail in the analysis manager
            # and see if the status was not set to failed by
            # the guest manager
            if analysis_success:
                if self.analysis.status == Analysis.FAILED:
                    analysis_success = False
        except Exception as e:
            log.exception(
                "Failure during the starting of task #%s. Error: %s",
                self.task.id, e, extra={
                    "action": "task.start",
                    "status": "error"
                }
            )
        finally:
            try:
                self.stop_and_wait()
            except Exception as e:
                log.exception(
                    "Failure during the stopping of task #%s. Error: %s",
                    self.task.id, e, extra={
                        "action": "task.stop",
                        "status": "error"
                    }
                )

        if analysis_success:
            self.set_analysis_status(Analysis.STOPPED, wait=True)
        else:
            self.set_analysis_status(Analysis.FAILED, wait=True)

        if not config("cuckoo:cuckoo:process_results"):
            log.debug(
                "Cuckoo process_results is set to 'no',"
                " not processing results"
            )
            return

        log.info(
            "Processing and reporting results for task #%s", self.task.id,
            extra={
                "action": "task.report",
                "status": "pending"
            }
        )
        try:
            self.processing_success = self.task.process()
        except Exception as e:
            log.exception(
                "Error during processing of task #%s. Error: %s",
                self.task.id, e, extra={
                    "action": "task.report",
                    "status": "failed"
                }
            )
            return

        log.info(
            "Task #%d: analysis procedure completed", self.task.id,
            extra={
                "action": "task.report",
                "status": "finished",
            }
        )

    def start_and_wait(self):
        """Start the analysis by running the auxiliary modules,
        adding the task to the resultserver, starting the machine
        and running a guest manager."""
        # Set guest status to starting and start analysis machine
        self.set_analysis_status(Analysis.STARTING)

        target = self.target.target
        if self.target.target and self.target.is_file:
            target = os.path.basename(target)

        log.info(
            "Starting analysis (task #%s, options: '%s') type '%s'."
            " Target: %s '%s'", self.task.id, self.options["options"],
            self.task.type, self.target.category, target,
            extra={
                "action": "task.init",
                "status": "starting",
                "task_id": self.task.id,
                "target": target,
                "category": self.target.category,
                "package": self.task.package,
                "options": self.options["options"],
                "custom": self.task.custom,
                "type": self.task.type
            }
        )

        self.rt = RealTimeHandler(self.task.db_task.id, self)
        ResultServer().add_task(self.task.db_task, self.machine, self.rt)

        # TODO: test realtime handler
        gevent.spawn(ping_test, self.rt)

        # Start auxiliary modules
        self.aux.start()

        if self.control_enabled:
            try:
                self.machinery.enable_remote_control(self.machine.label)
            except NotImplementedError:
                self.control_enabled = False
                log.exception(
                    "Remote control support has not been implemented "
                    "for machinery %s.", self.machine.manager
                )

        # Json log for performance measurement purposes
        logger(
            "Starting VM",
            action="vm.start", status="pending",
            vmname=self.machine.name
        )

        try:
            self.machinery.start(self.machine.label, self.task.db_task)
        except CuckooMachineSnapshotError as e:
            log.error(
                "Unable to restore to the snapshot for this Virtual Machine! "
                "Does your VM have a proper Snapshot and can you revert to it "
                "manually? VM: %s, error: %s",
                self.machine.name, e, extra={
                    "action": "vm.resume",
                    "status": "error",
                    "vmname": self.machine.name,
                }
            )
            return False
        except CuckooMachineError as e:
            log.error(
                "Error starting Virtual Machine! VM: %s, error: %s",
                self.machine.name, e, extra={
                    "action": "vm.start",
                    "status": "error",
                    "vmname": self.machine.name,
                }
            )
            return False

        logger(
            "Started VM",
            action="vm.start", status="success",
            vmname=self.machine.name
        )

        # retrieve the port used for remote control
        if self.control_enabled:
            try:
                params = self.machinery.get_remote_control_params(
                    self.machine.label
                )
                self.db.set_machine_rcparams(self.machine.label, params)
            except NotImplementedError:
                log.exception(
                    "Remote control support has not been implemented "
                    "for machinery %s.", self.machine.manager
                )

        # Enable network routing
        self.route.route_network()

        # By the time start returns it will have fully started the Virtual
        # Machine. We can now safely release the machine lock.
        self.release_machine_lock()

        # Request scheduler action for status 'starting'
        self.request_scheduler_action(Analysis.STARTING)

        # Choose the correct way of waiting or managing the agent and
        # execute it
        try:
            self.manage()
        except CuckooGuestCriticalTimeout as e:
            log.error(
                "Error from machine '%s': it appears that this Virtual "
                "Machine hasn't been configured properly as the Cuckoo Host "
                "wasn't able to connect to the Guest. There could be a few "
                "reasons for this, please refer to our documentation on the "
                "matter: %s", self.machine.name,
                faq("troubleshooting-vm-network-configuration"),
                extra={
                    "error_action": "vmrouting",
                    "action": "guest.handle",
                    "status": "error",
                    "task_id": self.task.id,
                }
            )

        except CuckooGuestError as e:
            log.error(
                "Error from the Cuckoo Guest: %s", e, extra={
                    "action": "guest.handle",
                    "status": "error",
                    "task_id": self.task.id,
            })

        return True

    def stop_and_wait(self):
        """Stop the analysis by stopping the aux modules, optionally
        dumping VM memory, stopping the VM and deleting the task from
        the resultserver."""
        self.set_analysis_status(Analysis.STOPPING)

        # Stop all Auxiliary modules
        self.aux.stop()

        # If enabled, make a full memory dump of the machine
        # before it shuts down
        if config("cuckoo:cuckoo:memory_dump") or self.task.memory:
            logger(
                "Taking full memory dump",
                action="vm.memdump", status="pending",
                vmname=self.machine.name
            )
            try:
                dump_path = os.path.join(self.task.path, "memory.dmp")
                self.machinery.dump_memory(self.machine.label, dump_path)

                logger(
                    "Taken full memory dump",
                    action="vm.memdump", status="success",
                    vmname=self.machine.name
                )

            except NotImplementedError:
                log.error(
                    "The memory dump functionality is not available for "
                    "the current machine manager.", extra={
                        "action": "vm.memdump",
                        "status": "error",
                        "vmname": self.machine.name,
                    }
                )
            except CuckooMachineError as e:
                log.error(
                    "Machinery error: %s", e, extra={
                        "action": "vm.memdump",
                        "status": "error",
                })

        logger(
            "Stopping VM",
            action="vm.stop", status="pending",
            vmname=self.machine.name
        )

        # Stop the analysis machine.
        try:
            self.machinery.stop(self.machine.label)
        except CuckooMachineError as e:
            log.warning(
                "Unable to stop machine %s: %s", self.machine.label, e,
                extra={
                    "action": "vm.stop",
                    "status": "error",
                    "vmname": self.machine.name,
                }
            )

        logger(
            "Stopped VM",
            action="vm.stop", status="success",
            vmname=self.machine.name
        )

        # Disable remote control after stopping the machine
        # if it was enabled for the task.
        if self.control_enabled:
            try:
                self.machinery.disable_remote_control(self.machine.label)
            except NotImplementedError:
                log.exception(
                    "Remote control support has not been implemented "
                    "for machinery %s.", self.machine.manager
                )

        # After all this, we can make the ResultServer forget about the
        # internal state for this analysis task.
        ResultServer().del_task(self.task.db_task, self.machine)
        self.rt.stop()

        # Drop the network routing rules if any.
        self.route.unroute_network()

    def manage(self):
        """Choose and use to method of waiting or managing the further steps
        to be taken of an analysis."""
        if "noagent" in self.machine.options:
            log.debug("Usage handler for the 'noagent' option")
            self.set_analysis_status(Analysis.RUNNING)
            self.wait_finish()
        elif self.task.type == "baseline":
            log.debug("Sleeping until timeout for baseline")
            self.set_analysis_status(Analysis.RUNNING)
            time.sleep(self.options["timeout"])
        else:
            log.debug("Using guest manager")
            monitor = self.task.options.get("monitor", "latest")
            self.guest_manager.start_analysis(self.options, monitor)

            if self.analysis.status == Analysis.STARTING:
                self.set_analysis_status(Analysis.RUNNING)
                self.guest_manager.wait_for_completion()

    def set_target(self, targets):
        if targets:
            self.target = targets[0]
        else:
            self.target = Target()

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

    def on_status_stopped(self, db):
        """Is executed by the scheduler on analysis status stopped
        Sets the task to completed, writes task json to analysis folder
        and releases machine if it is locked."""
        log.debug(
            "Setting task #%s status to %s", self.task.id, TASK_COMPLETED
        )
        self.task.set_status(TASK_COMPLETED)

        # Update task obj and write json to disk
        self.task.write_task_json()

        if self.machine.locked:
            log.debug("Releasing machine lock on %s", self.machine.label)
            self.machine = self.machinery.release(self.machine.label)

    def on_status_failed(self, db):
        """Is executed by the scheduler on analysis status failed.
        Releases the locked machine if it is locked and updates task status
        to analysis failed."""
        log.error("Analysis for task #%s failed", self.task.id)
        if self.machine.locked:
            log.debug("Releasing machine lock on %s", self.machine.label)
            self.machine = self.machinery.release(self.machine.label)

    def finalize(self, db):
        """Executed by the scheduler when the analysis manager thread exists.
        Updates the task status to the correct one and updates the
        task.json."""
        self.task.set_latest()
        self.release_machine_lock()
        # If, at this point, the analysis is not stopped, it cannot
        # succeeded, since the manager thread already exited. Updated status
        # to failed if the results were not processed.
        if self.analysis.status != Analysis.STOPPED:
            log.warning(
                "Analysis status is '%s' after exit.", self.analysis.status
            )
            if not config("cuckoo:cuckoo:process_results"):
                log.debug(
                    "Setting task #%s status to %s", TASK_FAILED_ANALYSIS
                )
                self.task.write_task_json(status=TASK_FAILED_ANALYSIS)
                self.task.set_status(TASK_FAILED_ANALYSIS)

        if config("cuckoo:cuckoo:process_results"):
            if self.processing_success:
                log.debug(
                    "Setting task #%s status to %s", self.task.id,
                    TASK_REPORTED
                )
                self.task.write_task_json(status=TASK_REPORTED)
                self.task.set_status(TASK_REPORTED)
            else:
                log.debug(
                    "Setting task #%s status to %s", self.task.id,
                    TASK_FAILED_PROCESSING
                )
                self.task.write_task_json(status=TASK_FAILED_PROCESSING)
                self.task.set_status(TASK_FAILED_PROCESSING)

        task_log_stop(self.task.id)
