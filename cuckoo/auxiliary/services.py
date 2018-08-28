# Copyright (C) 2010-2013 Claudio Guarnieri.
# Copyright (C) 2014-2016 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import time

from cuckoo.common.abstracts import Auxiliary
from cuckoo.common.config import Config, config
from cuckoo.core.database import Database, TASK_PENDING
from cuckoo.core.task import Task

log = logging.getLogger(__name__)
db = Database()
submit_task = Task()

class Services(Auxiliary):
    """Allows one or more additional VMs to be run next to an analysis. Either
    as global services (which are generally never rebooted) or on a
    per-analysis basis."""

    def start_service(self, service):
        """Start a VM containing one or more services."""
        # We give all services a total of 5 minutes to boot up before
        # starting the actual analysis.
        timeout = self.task.timeout or config("cuckoo:timeouts:default")
        timeout += 300
        tags = "service,%s" % service

        return submit_task.add_service(timeout, self.task.id, tags)

    def start(self):
        self.tasks = []

        if self.task.type == "service":
            return

        # Have to explicitly enable services.
        if not self.task.options.get("services"):
            return

        for service in self.options.get("services", "").split(","):
            service = service.strip()
            if not service:
                continue

            task_id = self.start_service(service)
            if not task_id:
                log.error(
                    "Failed to add service task for service '%s' and task #%s",
                    service, self.task.id
                )
                continue

            self.tasks.append((task_id, service))

            log.info(
                "Started service %s #%d for task #%d", service, task_id,
                self.task.id
            )

        # Wait until each service task not pending anymore
        for task_id, service in self.tasks:
            while db.view_task(task_id, details=False).status == TASK_PENDING:
                time.sleep(1)

        # Wait an additional timeout before starting the actual analysis.
        timeout = self.options.get("timeout")
        if isinstance(timeout, int):
            time.sleep(timeout)

    def stop(self):
        # TODO Edit Regular analysis manager to het status
        # of other tasks by asking scheduler. This to let the service tasks
        # know when their parent task has stopped, without polling the db.
        return
