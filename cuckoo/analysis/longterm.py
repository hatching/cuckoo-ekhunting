# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import os

from cuckoo.analysis.regular import Regular
from cuckoo.common.config import config
from cuckoo.common.exceptions import (
    CuckooMachineSnapshotError, CuckooMachineError, CuckooGuestCriticalTimeout
)
from cuckoo.common.objects import Analysis
from cuckoo.core.database import TASK_FAILED_ANALYSIS, TASK_PENDING
from cuckoo.core.log import task_log_start, task_log_stop, logger
from cuckoo.core.resultserver import ResultServer

log = logging.getLogger(__name__)

class Longterm(Regular):

    supports = ["longterm"]
    
    def init(self, db):
        success = super(Longterm, self).init(db)
        if not success:
            return False

        self.longterm = db.view_longterm(self.task.longterm_id)
        if not self.longterm:
            log.warning(
                "No longterm analysis found matching id '%s'",
                self.task.longterm_id
            )
            return False

        # The last_completed is updated at the end of a LTA task. If it is
        # not set, no tasks were completed yet.
        self.options["lta.first"] = self.longterm.last_completed is None

        # Machine was not given on LTA creation, set the current machine as
        # the analysis machine that should be used for all tasks that are part
        # of this LTA
        if self.longterm.machine is None:
            db.set_longterm_machine(self.machine.label, self.longterm.id)
            self.longterm.machine = self.machine.label
            db.machine_reserve(self.machine.label, self.task.id)

        return True

    def run(self):
        task_log_start(self.task.id)
        analysis_success = False

        try:
            analysis_success = self.prepare_and_start()
            log.info("At %s: ANALYSIS SUCCESS: %s", analysis_success, "prepare and start")
        except Exception as e:
            log.exception(
                "Failure during the starting of task #%s. Error: %s",
                self.task.id, e,
            )

        log.info("At %s: ANALYSIS SUCCESS: %s", analysis_success, "after start analysis")

        # The guest manager could have changed the status to failed if
        # something went wrong with starting the machine.
        if self.analysis.status == Analysis.STARTING:
            self.set_analysis_status(Analysis.RUNNING)
        else:
            analysis_success = False
            log.info("BLAAAAAAAAAAAAAAAAAAt")
            log.info("STATUS IS: %s", self.analysis.status)

        log.info("At %s: ANALYSIS SUCCESS: %s", analysis_success, "after setting status to running")

        # If the status is not running, the wait will return immediately
        try:
            self.guest_manager.wait_for_completion()
        except Exception as e:
            log.exception(
                "Guest manager failure while waiting for analysis to"
                " complete. Error: %s", e
            )
            analysis_success = False

        try:
            self.stop_and_wait()
        except Exception as e:
            log.exception(
                "Failure during the stopping of task #%s. Error: %s",
                self.task.id, e
            )
        log.info("At %s: ANALYSIS SUCCESS: %s", analysis_success, "After stop")

        if not analysis_success:
            self.set_analysis_status(Analysis.FAILED, wait=True)
        else:
            self.set_analysis_status(Analysis.STOPPED, wait=True)

    def prepare_and_start(self):
        self.set_analysis_status(self.analysis.STARTING)

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

        # Tell the resultserver it should expect incoming results
        # for this task
        ResultServer().add_task(self.task.db_task, self.machine)

        # Start auxiliary modules
        self.aux.start()

        log.info(
            "Starting VM: '%s'", self.machine.label, extra={
                "action": "vm.start",
                "status": "pending",
                "vmname": self.machine.name
            }
        )

        if not self.options["lta.first"]:
            log.debug(
                "Not first task of longterm analysis, starting machine without"
                " restoring to snapshot."
            )

        try:
            self.machinery.start(
                self.machine.label, self.task.db_task,
                revert=self.options["lta.first"]
            )
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

        log.debug("Machine started")

        # Enable network routing
        self.route.route_network()

        # By the time start returns it will have fully started the Virtual
        # Machine. We can now safely release the machine lock.
        self.release_machine_lock()

        # Request scheduler action for status 'starting'
        self.request_scheduler_action(Analysis.STARTING)

        # Start guest manager and wait for machine to start.
        try:
            self.guest_manager.start_analysis(
                self.options, self.options.get("monitor", "latest")
            )
        except CuckooGuestCriticalTimeout as e:
            log.error("Error starting guest manager: %s", e)
            return False

        # The guest manager could have changed the status to failed if
        # something went wrong with starting the machine.
        if self.analysis.status != Analysis.STARTING:
            log.error(
                "Analysis status was changed to unexpected status '%s'. "
                "This likely means something went wrong while starting the "
                "guest.", self.analysis.status
            )
            return False

        return True

    def stop_and_wait(self):
        self.set_analysis_status(Analysis.STOPPING)

        # Stop all Auxiliary modules
        self.aux.stop()

        # If enabled, make a full memory dump of the machine
        # before it shuts down
        if config("cuckoo:cuckoo:memory_dump") or self.task.memory:
            try:
                dump_path = os.path.join(self.task.path, "memory.dmp")
                self.machinery.dump_memory(self.machine.label, dump_path)

            except NotImplementedError:
                log.error(
                    "The memory dump functionality is not available for "
                    "the current machine manager."
                )
            except CuckooMachineError as e:
                log.error("Machinery error: %s", e)

        logger(
            "Stopping VM",
            action="vm.stop", status="pending",
            vmname=self.machine.name
        )

        # Stop the analysis machine.
        try:
            self.machinery.stop_safe(self.machine.label)
        except CuckooMachineError as e:
            log.warning(
                "Unable to stop machine %s: %s", self.machine.label, e,
            )

        # After all this, we can make the ResultServer forget about the
        # internal state for this analysis task.
        ResultServer().del_task(self.task.db_task, self.machine)

        # Drop the network routing rules if any.
        self.route.unroute_network()

    def finalize(self, db):
        self.task.set_latest()
        self.release_machine_lock()

        if self.analysis.status != Analysis.STOPPED:
            log.error(
                "Analysis status is '%s' after exit. Setting task #%s status"
                " to %s", self.analysis.status, self.task.id,
                TASK_FAILED_ANALYSIS
            )
            self.task.write_task_json(status=TASK_FAILED_ANALYSIS)
            self.task.set_status(TASK_FAILED_ANALYSIS)

        db.set_latest_longterm(self.task.id, self.task.longterm_id)

        # Release the machine reservation if there are no pending tasks left
        # for this longterm analysis. If there are, reserve the machine for
        # the next task of this longterm analysis.
        pending_lta = db.list_tasks(
            longterm_id=self.task.longterm_id, status=TASK_PENDING,
            order_by="id"
        )
        if not pending_lta:
            log.debug(
                "Last task of longterm analysis completed. Clearing"
                " reservation of machine %s", self.longterm.machine
            )
            db.clear_reservation(self.longterm.machine)
        else:
            log.debug(
                "Changing machine %s reservation to next task #%s",
                self.longterm.machine, pending_lta[0].id
            )
            db.machine_reserve(self.longterm.machine, pending_lta[0].id)

        task_log_stop(self.task.id)
