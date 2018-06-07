# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import os
import time
from threading import Thread, ThreadError

from cuckoo.analysis.regular import Regular
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

log = logging.getLogger(__name__)

class Longterm(Regular):

    supports = ["longterm"]
    
    def init(self, db):
        success = super(Longterm, self).init(db)
        if not success:
            return False

        self.longterm = db.view_lta(self.task.longterm_id)
        if not self.longterm:
            log.warning(
                "No longterm analysis found matching id '%s'",
                self.task.longterm_id
            )
            return False

        self.options["lta.first"] = self.longterm.last_completed is None
        return True

    def run(self):
        task_log_start(self.task.id)
        startup_success = False
        try:
            startup_success = self.prepare_and_start()
        except Exception as e:
            log.exception(
                "Failure during the starting of task #%s. Error: %s",
                self.task.id, e,
            )

        # Start guest manager and wait for machine to start.
        try:
            self.guest_manager.start_analysis(
                self.options, self.options.get("monitor", "latest")
            )
        except CuckooGuestCriticalTimeout as e:
            startup_success = False
            log.error("Error starting guest manager: %s", e)

        # The guest manager could have changed the status to failed if
        # something went wrong with starting the machine.
        if self.analysis.status == Analysis.STARTING:
            self.set_analysis_status(Analysis.RUNNING)
        else:
            startup_success = False

        # If analysis manager processing is enabled, the guest manager wait
        # is started/moved to another thread so we can process results while
        # the analysis runs.
        wait_th = None
        if not config("cuckoo:cuckoo:process_results"):
            try:
                self.guest_manager.wait_for_completion()
            except Exception as e:
                log.exception(
                    "Guest manager failure while waiting for analysis to"
                    " complete. Error: %s", e
                )

        else:
            try:
                wait_th = Thread(target=self.guest_manager.wait_for_completion)
                wait_th.start()
            except ThreadError as e:
                log.exception(
                    "Failed to start guest manager wait in a new thread. "
                    "Error: %s", e
                )

        # Seperate guest manager wait thread is used, start processing
        # while analysis runs and guest manager thread is alive
        if wait_th:
            self.interval_process(wait_th)

        # TODO Processing in the analysis manager should keep happening while
        # the machine is stopping/was stopped to make sure the latest behavior,
        # including memdumps are processed.
        try:
            self.stop_and_wait()
        except Exception as e:
            log.exception(
                "Failure during the stopping of task #%s. Error: %s",
                self.task.id, e
            )

        if not startup_success:
            self.set_analysis_status(Analysis.FAILED, wait=True)
        else:
            self.set_analysis_status(Analysis.STOPPED, wait=True)

    def interval_process(self, th):
        do = True
        while do:
            # TODO Get time from from config

            # Only sleep if thread is running. If thread is not running, it
            # means that it either ended or failed to start. One round of
            # processing results should always happen.
            if th.isAlive():
                time.sleep(60)

            # TODO Only process if new data is available
            # TODO Summarize behavioral data
            self.task.process()
            if self.analysis.STATUS != Analysis.RUNNING or not th.isAlive():
                do = False

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
            self.machinery.safe_stop(self.machine.label)
        except CuckooMachineError as e:
            log.warning(
                "Unable to stop machine %s: %s", self.machine.label, e,
            )

        # After all this, we can make the ResultServer forget about the
        # internal state for this analysis task.
        ResultServer().del_task(self.task.db_task, self.machine)

        # Drop the network routing rules if any.
        self.route.unroute_network()
