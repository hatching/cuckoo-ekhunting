# Copyright (C) 2012-2013 Claudio Guarnieri.
# Copyright (C) 2014-2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import time
import logging
import threading
import Queue

import cuckoo

from cuckoo.common.config import Config, config
from cuckoo.common.exceptions import (
    CuckooCriticalError, CuckooMachineError, CuckooOperationalError
)
from cuckoo.core.database import (
    Database, TASK_RUNNING, TASK_PENDING, TASK_FAILED_ANALYSIS
)
from cuckoo.core.rooter import rooter
from cuckoo.core.log import logger
from cuckoo.core.task import Task
from cuckoo.misc import cwd, get_free_disk

log = logging.getLogger(__name__)

class Scheduler(object):

    machine_lock = None

    def __init__(self, maxcount=None):
        self.running = True
        self.db = Database()
        self.maxcount = maxcount
        self.total_analysis_count = 0
        self.machinery = None
        self.error_queue = None
        self.managers = []

    def initialize(self):
        machinery_name = config("cuckoo:cuckoo:machinery")
        max_vmstartup = config("cuckoo:cuckoo:max_vmstartup_count") or 1

        # Initialize a semaphore or lock to prevent to many VMs from
        # starting at the same time.
        Scheduler.machine_lock = threading.Semaphore(max_vmstartup)

        log.info("Using \"%s\" as machine manager", machinery_name, extra={
            "action": "init.machinery",
            "status": "success",
            "machinery": machinery_name,
        })

        # Create the machine manager
        self.machinery = cuckoo.machinery.plugins[machinery_name]()

        # Provide a dictionary with the configuration options to the
        # machine manager instance.
        self.machinery.set_options(Config(machinery_name))

        try:
            self.machinery.initialize(machinery_name)
        except CuckooMachineError as e:
            raise CuckooCriticalError("Error initializing machines: %s" % e)

        # At this point all the available machines should have been identified
        # and added to the list. If none were found, Cuckoo aborts the
        # execution. TODO In the future we'll probably want get rid of this.
        machines = self.machinery.machines()
        if not machines:
            raise CuckooCriticalError("No machines available.")

        log.info("Loaded %s machines", len(machines), extra={
            "action": "init.machines",
            "status": "success",
            "count": len(machines),
        })

        if len(machines) > 1 and self.db.engine.name == "sqlite":
            log.warning("As you've configured Cuckoo to execute parallel "
                        "analyses, we recommend you to switch to a MySQL or "
                        "a PostgreSQL database as SQLite might cause some "
                        "issues.")

        if len(machines) > 4 and config("cuckoo:cuckoo:process_results"):
            log.warning("When running many virtual machines it is recommended "
                        "to process the results in separate 'cuckoo process' "
                        "instances increase throughput and stability."
                        " Please read the documentation about the "
                        "`Processing Utility`.")

        self.drop_forwarding_rules()

        # Message queue with threads to transmit exceptions (used as IPC).
        self.error_queue = Queue.Queue()

        # Command-line overrides the configuration file.
        if self.maxcount is None:
            self.maxcount = config("cuckoo:cuckoo:max_analysis_count")

    def drop_forwarding_rules(self):
        """Drop all existing packet forwarding rules for each VM. Just in case
        Cuckoo was terminated for some reason and various forwarding rules
        have thus not been dropped yet."""
        for machine in self.machinery.machines():
            if not machine.interface:
                log.info("Unable to determine the network interface for VM "
                         "with name %s, Cuckoo will not be able to give it "
                         "full internet access or route it through a VPN! "
                         "Please define a default network interface for the "
                         "machinery or define a network interface for each "
                         "VM.", machine.name)
                continue

            # Drop forwarding rule to each VPN.
            if config("routing:vpn:enabled"):
                for vpn in config("routing:vpn:vpns"):
                    rooter(
                        "forward_disable", machine.interface,
                        config("routing:%s:interface" % vpn), machine.ip
                    )

            # Drop forwarding rule to the internet / dirty line.
            if config("routing:routing:internet") != "none":
                rooter(
                    "forward_disable", machine.interface,
                    config("routing:routing:internet"), machine.ip
                )

    def stop(self):
        """Stop scheduler."""
        self.running = False
        # Shutdown machine manager (used to kill machines that still alive).
        self.machinery.shutdown()

    def ready_for_new_run(self):
        """Performs checks to see if Cuckoo should start a new
        pending task or not"""
        # Wait until the machine lock is not locked. This is only the case
        # when all machines are fully running, rather that about to start
        # or still busy starting. This way we won't have race conditions
        # with finding out there are no available machines in the analysis
        # manager or having two analyses pick the same machine.
        if not Scheduler.machine_lock.acquire(False):
            logger(
                "Could not acquire machine lock",
                action="scheduler.machine_lock", status="busy"
            )
            return False

        Scheduler.machine_lock.release()

        # Verify if the minimum amount of disk space is available
        if config("cuckoo:cuckoo:freespace"):
            try:
                freespace = get_free_disk(cwd("storage", "analyses"))
                if freespace <= config("cuckoo:cuckoo:freespace"):
                    log.error(
                        "Not enough free disk space! (Only %d MB!)",
                        freespace, extra={
                            "action": "scheduler.diskspace",
                            "status": "error",
                            "available": freespace,
                        }
                    )
                    return False
            except OSError as e:
                # Ignore this check, since we cannot determine it now
                log.error("Error determining free disk space. Error: %s", e)

        max_vm = config("cuckoo:cuckoo:max_machines_count")

        if max_vm and len(self.machinery.running()) >= max_vm:
            log.debug("Maximum amount of machines is running")
            logger(
                "Already maxed out on running machines",
                action="scheduler.machines", status="maxed"
            )
            return False

        # Stops the scheduler if the max_analysis_count in the configuration
        # file has been reached.
        if self.maxcount and self.total_analysis_count >= self.maxcount:
            if len(self.managers) <= 0:
                    log.debug("Reached max analysis count, exiting.", extra={
                        "action": "scheduler.max_analysis",
                        "status": "success",
                        "limit": self.total_analysis_count,
                    })
                    self.stop()
                    return False
            else:
                log.debug("Maximum analysis hit, awaiting active to"
                          "finish off. Still active: %s", len(self.managers))
                logger(
                    "Maximum analyses hit, awaiting active to finish off",
                    action="scheduler.max_analysis", status="busy",
                    active=len(self.managers)
                )
                return False

        if not self.machinery.availables():
            logger(
                "No available machines",
                action="scheduler.machines", status="none"
            )
            return False

        return True

    def handle_pending(self):
        """Handles pending tasks. Checks if a new task can be started. Eg:
        not too many machines already running, disk space left etc. Selects a
        machine matching the task requirements and creates
        a matching analysis manager for the category of the selected pending
        task"""
        # Acquire machine lock non-blocking. This is because the scheduler
        # also handles requests made by analysis manager. A blocking lock
        # could cause a deadlock
        if not Scheduler.machine_lock.acquire(False):
            return

        # Select task that is specifically for one of the available machines
        # possibly a service machine
        machine, task, analysis = None, None, False
        for a_machine in self.db.get_available_machines():
            task = self.db.fetch(machine=a_machine.name, lock=False)
            if task:
                machine = self.machinery.acquire(machine_id=a_machine.name)
                break

            if a_machine.is_analysis():
                analysis = True

        # No task for a specific machine and at least one of the available
        # machines is not a service machine. Fetch task that is not
        # for a service machine
        if not task and not machine and analysis:

            # Search for a task, but don't lock it until we are sure a machine
            # for this task is available, since it might have tags or require
            # a specific platform. Ignore a task if we know a machine is not
            # available for it.
            exclude = []
            while not machine:
                task = self.db.fetch(service=False, lock=False,
                                     exclude=exclude)

                if task is None:
                    break

                try:
                    machine = self.machinery.acquire(machine_id=task.machine,
                                                     platform=task.platform,
                                                     tags=task.tags)
                except CuckooOperationalError:
                    log.error("Task #%s cannot be started, no machine with"
                              " matching requirements for this task exists."
                              " Requirements: %s",
                              task.id, Task.requirements_str(task))
                    # No machine with required tags, name etc exists
                    # Set analysis to failed.
                    # TODO Use another status so it might be recovered
                    # on next Cuckoo startup if the machine exists by then
                    self.db.set_status(task.id, TASK_FAILED_ANALYSIS)

                if not machine:
                    log.debug("No matching machine for task #%s. Skipping task"
                              " until machine is available. Requirements: %s",
                              task.id, Task.requirements_str(task))
                    exclude.append(task.id)

        if not task or not machine:
            Scheduler.machine_lock.release()
            return

        log.info(
            "Task #%d: acquired machine %s (label=%s)",
            task.id, machine.name, machine.label, extra={
                "action": "vm.acquire",
                "status": "success",
                "vmname": machine.name,
            }
        )

        # Task and matching machine found. Find analysis manager
        # which supports the category of this task. Lock it when found
        analysis_manager = self.get_analysis_manager(task, machine)

        if not analysis_manager:
            # If no analysis manager is found for this task category, it
            # cannot be started, therefore we release the machine again
            self.machinery.release(label=machine.label)

            # Release machine lock as the machine will not be starting
            Scheduler.machine_lock.release()
            return

        # Only lock task for running if we are sure we will try to start it
        self.db.set_status(task.id, TASK_RUNNING)

        # Increment the total of analyses
        self.total_analysis_count += 1

        analysis_manager.daemon = True
        if not analysis_manager.init(self.db):
            self.db.set_status(task.id, TASK_FAILED_ANALYSIS)
            log.error("Failed to initialize analysis manager for task #%s",
                      task.id)

            Scheduler.machine_lock.release()
        else:
            # If initialization succeeded, start the analysis manager
            # and store it so we can track it
            analysis_manager.start()
            self.managers.append(analysis_manager)

    def get_analysis_manager(self, db_task, machine):
        """Searches all available analysis managers for one
        that supports the category of the given task. Returns an
        analysis manager. Returns None if no manager supports the category"""

        managers = cuckoo.analysis.plugins
        analysis_manager = None
        for manager in managers:
            if db_task.category in manager.supports:
                core_task = Task(db_task)
                sample = None

                # Check if this task is a file
                if core_task.is_file:
                    sample = self.db.view_sample(db_task.sample_id)

                analysis_manager = manager(machine,
                                           self.error_queue,
                                           self.machinery)
                analysis_manager.set_task(core_task, sample)
                break

        return analysis_manager

    def handle_managers(self):
        """Executes actions requested by analysis managers. If an analysis
        manager is finished, executes its finalize actions. Returns a
        list of analysis managers to untrack"""
        remove = []
        for manager in self.managers:

            if manager.action_requested():
                status = manager.get_analysis_status()
                status_action = getattr(manager, "on_status_%s" % status, None)
                try:
                    if status_action:
                        log.debug("Executing requested action by task #%s for"
                                  " status \'%s\'", manager.task.id, status)
                        status_action(self.db)
                    else:
                        log.error("Analysis manager for task #%s requested"
                                  " action for status \'%s\', but no action is"
                                  " implemented", manager.task.id, status)
                finally:
                    manager.release_locks()

            if not manager.isAlive():
                manager.finalize(self.db)
                remove.append(manager)

        return remove

    def start(self):
        self.initialize()

        log.info("Waiting for analysis tasks")

        while self.running:
            time.sleep(1)

            # Handle pending tasks by finding the matching machine and
            # analysis manager. The manager is started added to tracked
            # analysis managers
            if self.db.count_tasks(status=TASK_PENDING) > 0:
                # Check if the max amount of VMs are running, if there is
                # enough disk space, etc
                if self.ready_for_new_run():

                    # Grab a pending task, find a machine that matches, find
                    # a matching analysis manager and start the analysis
                    self.handle_pending()

            # Handles actions requested by analysis managers and performs
            # finalization actions for the managers if they exit.
            for untrack_manager in self.handle_managers():
                self.managers.remove(untrack_manager)

            try:
                raise self.error_queue.get(block=False)
            except Queue.Empty:
                pass

        log.debug("End of analyses")
