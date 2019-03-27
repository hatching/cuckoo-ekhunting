# Copyright (C) 2018-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import logging
import os
import shutil

from cuckoo.common.config import config
from cuckoo.core.database import Task as DbTask
from cuckoo.massurl import db
from cuckoo.massurl.db import URLGroupTask
from cuckoo.massurl.urldiary import URLDiaries
from cuckoo.misc import cwd

log = logging.getLogger(__name__)

def clean_tasks(dt):
    ses = db.db.Session()
    tasks = []
    try:
        tasks = ses.query(DbTask.id).filter(
            DbTask.owner == "cuckoo.massurl",
            DbTask.started_on <= dt
        ).all()
        if not tasks:
            return

        log.debug("Deleting %s tasks", len(tasks))
        tasks = set(task.id for task in tasks)
        db.db.engine.execute(
            URLGroupTask.__table__.delete().where(
                URLGroupTask.task_id.in_(tasks)
            )
        )
        ses.commit()
    finally:
        ses.close()

    # Move PCAPS if enabled
    if config("massurl:retention:keep_pcap"):
        pcaps = cwd("storage", "files", "pcaps")
        if not os.path.exists(pcaps):
            os.makedirs(pcaps)

        for task_id in tasks:
            dump_path = cwd("dump.pcap", analysis=task_id)
            if not os.path.isfile(dump_path):
                continue
            new_path = os.path.join(pcaps, "%s.pcap" % task_id)
            if os.path.isfile(new_path):
                continue

            shutil.move(dump_path, new_path)

    for task_id in tasks:
        task_path = cwd(analysis=task_id)
        if os.path.exists(task_path):
            shutil.rmtree(task_path)

    # delete tasks
    ses = db.db.Session()
    try:
        db.db.engine.execute(
            DbTask.__table__.delete().where(
                DbTask.id.in_(tasks)
            )
        )
        ses.commit()
    finally:
        ses.close()

def to_millis(dt):
    return (dt - datetime.datetime.utcfromtimestamp(0)).total_seconds() * 1000

def clean():
    if not config("massurl:retention:enabled"):
        return

    alert_days = config("massurl:retention:alerts")
    if alert_days:
        before = datetime.datetime.utcnow() - datetime.timedelta(
            days=alert_days
        )
        log.debug("Removing alerts older than %s", before)
        db.delete_alert(before=before)

    task_days = config("massurl:retention:tasks")
    if task_days:
        before = datetime.datetime.utcnow() - datetime.timedelta(
            days=task_days
        )
        log.debug("Removing tasks older than %s", before)
        clean_tasks(before)

    diary_days = config("massurl:retention:urldiaries")
    if diary_days:
        before = datetime.datetime.utcnow() - datetime.timedelta(
            days=diary_days
        )
        before_millis = int(to_millis(before))
        log.debug("Removing URL diaries older than %s", before)
        deldiaries = URLDiaries.delete_urldiary(before=before_millis)
        delrequestlogs = URLDiaries.delete_requestlog(before=before_millis)
        log.debug("Deleted %s URL diaries", deldiaries)
        log.debug("Deleted %s request logs", delrequestlogs)

    log.debug("Cleanup finished")
