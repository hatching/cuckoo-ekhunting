# Copyright (C) 2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import os
import time
import threading

from cuckoo.common.abstracts import AnalysisManager
from cuckoo.common.config import config
from cuckoo.common.constants import faq
from cuckoo.common.objects import File, Analysis
from cuckoo.common.exceptions import (
    CuckooMachineSnapshotError, CuckooMachineError, CuckooGuestError,
    CuckooGuestCriticalTimeout
)
from cuckoo.core.database import (
    TASK_COMPLETED, TASK_REPORTED, TASK_FAILED_ANALYSIS, TASK_FAILED_PROCESSING
)
from cuckoo.core.guest import GuestManager
from cuckoo.core.log import task_log_start, task_log_stop, logger
from cuckoo.core.plugins import RunAuxiliary
from cuckoo.core.resultserver import ResultServer
from cuckoo.core.scheduler import Scheduler

log = logging.getLogger(__name__)

class TaskAnalysis(AnalysisManager):

    supports = ["file", "url", "archive", "baseline", "service"]

    def init(self, db):
        """Excuted by the scheduler. Prepares the analysis for starting"""
        init_success = True

        # Used to keep track about the Scheduler machine_lock
        self.lock_released = False

        # Used at the processing and final stage to determine is processing
        # was run and successful
        self.processing_success = None

        # Keep track if the machine lock has been released
        self.scheduler_lock_released = False

        # If dir creation failed on submission, create them now
        if len(self.task.dirs_missing()) > 0:
            if not self.task.create_dirs():
                log.error("Unable to create missing directories."
                          " Task #%s failed", self.task.id)

                return False
            else:
                log.debug("Created missing task directories for task #%s",
                          self.task.id)

        if self.task.file:
            self.file = File(self.task.target)

            # Get filename here so we can use it to name the copy
            # in case the original is not available
            file_name = self.file.get_name()
            use_copy = False
            if not os.path.exists(self.task.target):
                log.warning("Original binary %s does not exist anymore."
                            " Using copy", self.task.target)
                use_copy = True
                self.file = File(self.task.copied_binary)

            # Verify if the file is readable and has not changed
            if not self.file_usable():
                init_success = False

            else:
                options = {}
                package, activity = self.file.get_apk_entry()
                if package and activity:
                    options["apk_entry"] = "%s:%s" % (package, activity)

                self.build_options(update_with={
                    "target": self.task.copied_binary if use_copy
                    else self.task.target,
                    "file_name": file_name,
                    "file_type": self.file.get_type(),
                    "pe_exports": ",".join(self.file.get_exported_functions()),
                    "options": options
                })

        else:
            self.build_options()

        self.guest_manager = GuestManager(self.machine.name, self.machine.ip,
                                          self.machine.platform, self.task.id,
                                          self, self.analysis)

        self.aux = RunAuxiliary(self.task.db_task.to_dict(), self.machine,
                                self.guest_manager)

        # Write task to disk in json file
        self.task.write_to_disk()

        return init_success

    def run(self):
        """Starts the analysis manager thread"""
        try:
            task_log_start(self.task.id)
            analysis_success = False

            try:
                analysis_success = self.start_analysis()

                # See if the analysis did not fail in the analysis manager
                # and see if the status was not set to failed by
                # the guest manager
                if analysis_success:
                    if self.analysis.status == Analysis.FAILED:
                        analysis_success = False
            except Exception as e:
                log.error("Error in start_analysis: %s", e)
            finally:
                self.stop_analysis()

            # Only process and report if the analysis was successful
            if analysis_success:
                self.set_analysis_status(Analysis.STOPPED,
                                         request_scheduler_action=True)

                if self.cfg.cuckoo.process_results:
                    logger(
                        "Starting task reporting",
                        action="task.report", status="pending"
                    )
                    log.info("Processing and reporting results for task #%s",
                             self.task.id)

                    self.processing_success = self.task.process()

                    logger(
                        "Task reporting finished",
                        action="task.report", status="finished"
                    )
                else:
                    log.debug("Cuckoo process_results is set to 'no',"
                              " not processing results")

                log.info(
                    "Task #%d: analysis procedure completed",
                    self.task.id, extra={
                        "action": "task.stop",
                        "status": "success",
                    }
                )
            else:
                self.set_analysis_status(Analysis.FAILED,
                                         request_scheduler_action=True)
        except Exception as e:
            log.exception("Failure in analysis manager.run for task #%s. "
                          "Error: %s", self.task.id, e, extra={
                "action": "task.stop",
                "status": "error",
            })

        finally:
            # Set this task as the latest symlink
            self.task.set_latest()
            task_log_stop(self.task.id)
            self.release_scheduler_lock()

    def start_analysis(self):
        """Start the analysis by running the auxiliary modules,
        adding the task to the resultserver, starting the machine
        and running a guest manager"""
        # Set guest status to starting and start analysis machine
        self.set_analysis_status(Analysis.STARTING)

        target = self.task.target
        if self.task.file:
            target = self.file.get_name()

        log.info("Starting analysis of %s \"%s\" (task #%d, options: \"%s\")",
                 self.task.category.upper(), target, self.task.id,
                 self.options["options"], extra={
                "action": "task.init",
                "status": "starting",
                "task_id": self.task.id,
                "target": target,
                "category": self.task.category,
                "package": self.task.package,
                "options": self.options["options"],
                "custom": self.task.custom,
        })

        try:
            ResultServer().add_task(self.task.db_task, self.machine)
        except Exception as e:
            self.error_queue.put(e)
            return False

        # Start auxiliary modules
        self.aux.start()

        # Check if the current task has remotecontrol
        # enabled before starting the machine.
        self.control_enabled = (
            config("cuckoo:remotecontrol:enabled") and
            "remotecontrol" in self.task.options
        )
        if self.control_enabled:
            try:
                self.machinery.enable_remote_control(self.machine.label)
            except NotImplementedError:
                raise CuckooMachineError(
                    "Remote control support has not been implemented "
                    "for this machinery."
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

        # Json log for performance measurement purposes
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
                raise CuckooMachineError(
                    "Remote control support has not been implemented "
                    "for this machinery."
                )

        # Enable network routing
        self.route_network()

        # By the time start returns it will have fully started the Virtual
        # Machine. We can now safely release the machine lock.
        self.release_scheduler_lock()

        # Request scheduler action for status 'starting'
        self.request_scheduler_action(for_status=Analysis.STARTING)

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
                "matter: %s",
                self.machine.name,
                faq("troubleshooting-vm-network-configuration"),
                extra={
                    "error_action": "vmrouting",
                    "action": "guest.handle",
                    "status": "error",
                    "task_id": self.task.id,
                }
            )

        except CuckooGuestError as e:
            log.error("Error from the Cuckoo Guest: %s", e, extra={
                "action": "guest.handle",
                "status": "error",
                "task_id": self.task.id,
            })

        return True

    def stop_analysis(self):
        """Stop the analysis by stopping the aux modules, optionally
        dumping VM memory, stopping the VM and deleting the task from
        the resultserver"""
        self.set_analysis_status(Analysis.STOPPING)

        # Stop all Auxiliary modules
        self.aux.stop()

        # If enabled, make a full memory dump of the machine
        # before it shuts down
        if self.cfg.cuckoo.memory_dump or self.task.memory:

            # Json log for performance measurement purposes
            logger(
                "Taking full memory dump",
                action="vm.memdump", status="pending",
                vmname=self.machine.name
            )

            try:
                dump_path = os.path.join(self.task.path, "memory.dmp")
                self.machinery.dump_memory(self.machine.label, dump_path)

                # Json log for performance measurement purposes
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
                log.error("Machinery error: %s", e, extra={
                    "action": "vm.memdump",
                    "status": "error",
                })

        # Json log for performance measurement purposes
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
                "Unable to stop machine %s: %s",
                self.machine.label, e, extra={
                    "action": "vm.stop",
                    "status": "error",
                    "vmname": self.machine.name,
                }
            )

        # Json log for performance measurement purposes
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
                raise CuckooMachineError(
                    "Remote control support has not been implemented "
                    "for this machinery."
                )

        # After all this, we can make the ResultServer forget about the
        # internal state for this analysis task.
        ResultServer().del_task(self.task.db_task, self.machine)

        # Drop the network routing rules if any.
        self.unroute_network()

    def manage(self):
        """Choose and use to method of waiting or managing the further steps
        to be taken of an analysis."""

        if "noagent" in self.machine.options:
            log.debug("Usage handler for the \'noagent\' option")
            self.set_analysis_status(Analysis.RUNNING)
            self.wait_finish()

        elif self.task.category == "baseline":
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

    def on_status_starting(self, db):
        """Is executed by the scheduler on analysis status starting
        Stores the chosen route in the db"""
        log.info("Using route \'%s\' for task #%s", self.route,
                     self.task.id)
        # Propagate the taken route to the database.
        db.set_route(self.task.id, self.route)

        # Store used machine in the task
        db.set_machine(self.task.id, self.machine.name)

    def on_status_stopped(self, db):
        """Is executed by the scheduler on analysis status stopped
        Sets the task to completed, writes task json to analysis folder
        and releases machine if it is locked"""
        log.debug("Setting task #%s status to %s", self.task.id,
                  TASK_COMPLETED)
        db.set_status(self.task.id, TASK_COMPLETED)

        # Update task obj and write json to disk
        db_task = db.view_task(self.task.id)
        self.task.set_task(db_task)
        self.task.write_to_disk()

        if self.machine.locked:
            log.debug("Releasing machine lock on %s", self.machine.label)
            self.machine = self.machinery.release(self.machine.label)

    def on_status_failed(self, db):
        """Is executed by the scheduler on analysis status failed.
        Releases the locked machine if it is locked and updates task status
        to analysis failed"""
        db.set_status(self.task.id, TASK_FAILED_ANALYSIS)

        if self.machine.locked:
            log.debug("Releasing machine lock on %s", self.machine.label)
            self.machine = self.machinery.release(self.machine.label)

    def finalize(self, db):
        """Executed by the scheduler when the analysis manager thread exists.
        Updates the task status to the correct one and updates the
        task.json"""
        # Update task obj and write json to disk
        db_task = db.view_task(self.task.id)
        self.task.set_task(db_task)
        self.task.write_to_disk()

        if self.cfg.cuckoo.process_results and \
                        self.processing_success is not None:
            if self.processing_success:
                log.debug("Setting task #%s status to %s", self.task.id,
                          TASK_REPORTED)
                db.set_status(self.task.id, TASK_REPORTED)
            else:
                log.debug("Setting task #%s status to %s", self.task.id,
                          TASK_FAILED_PROCESSING)
                db.set_status(self.task.id, TASK_FAILED_PROCESSING)

    def release_scheduler_lock(self):
        """Release the scheduler machine_lock. Do this when the VM has
        started"""
        if not self.scheduler_lock_released:
            try:
                Scheduler.machine_lock.release()
                self.scheduler_lock_released = True
            except threading.ThreadError:
                pass
