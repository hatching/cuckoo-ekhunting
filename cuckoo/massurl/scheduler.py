# Copyright (C) 2018-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import logging
import time

import gevent

from cuckoo.core.database import (
    Database, Task as DbTask, Target, TASK_FAILED_ANALYSIS,
    TASK_FAILED_PROCESSING, TASK_FAILED_REPORTING
)
from cuckoo.core.task import Task
from cuckoo.massurl import web
from cuckoo.massurl.db import URLGroup, URLGroupTask
from cuckoo.massurl import db as massurldb
from cuckoo.massurl.realtime import ev_client
from cuckoo.massurl.schedutil import schedule_time_next

log = logging.getLogger(__name__)
db = Database()
submit_task = Task()

OWNER = "cuckoo.massurl"

# TODO: call .set()/.clear() when the schedule changes (group add, delete,
# schedule modify)
scheduling_change = gevent.event.Event()

def run_with_minimum_delay(task, delay):
    while True:
        start = time.time()
        try:
            task()
        except:
            log.exception("Task %s error:", task)
        duration = time.time() - start
        if duration < delay:
            gevent.sleep(delay - duration)

def next_group_task():
    s = db.Session()
    group = s.query(URLGroup).filter(
        URLGroup.schedule_next != None,
        URLGroup.completed.is_(True),
    ).order_by(URLGroup.schedule_next).first()
    if group:
        group = group.to_dict(False)
    s.close()
    return group

def create_parallel_tasks(targets, max_parallel):
    urls = []
    options = "free=yes"
    for t in targets:
        urls.append(t)
        if len(urls) >= max_parallel:
            yield submit_task.add_massurl(urls, options=options)
            urls = []
    if urls:
        yield submit_task.add_massurl(urls, options=options)

def create_single_task(urls, group_id):
    for task_id in create_parallel_tasks(urls, len(urls)):
        s = db.Session()
        try:
            grouptask = URLGroupTask()
            grouptask.task_id = task_id
            grouptask.url_group_id = group_id
            s.add(grouptask)
            s.commit()
        finally:
            s.close()

def insert_group_tasks(group):
    # TEMP solution
    log.debug("Creating group tasks for %r", group["name"])
    group = massurldb.find_group(group_id=group.id)
    urls = massurldb.find_urls_group(group.id, limit=1000000000)

    # TEMP very ugly solution
    groupid_task = []
    for task_id in create_parallel_tasks(urls, group.max_parallel):
        groupid_task.append({
            "url_group_id": group.id,
            "task_id": task_id
        })

    if groupid_task:
        s = db.Session()
        try:
            s.query(URLGroup).filter(URLGroup.id==group.id).update({
                "completed": False,
                "schedule_next": None
            })
            s.bulk_insert_mappings(URLGroupTask, groupid_task)
            s.commit()
        finally:
            s.close()
    log.debug("Tasks created: %s", groupid_task)

# def insert_group_tasks(group):
#     log.debug("Creating group tasks for %r", group["name"])
#     s = db.Session()
#     try:
#         group = s.query(URLGroup).with_for_update().get(group.id)
#         group.completed = False
#         s.add(group)
#
#         max_parallel = group.max_parallel if False else 1
#
#         # TODO: .yield_per(500).enable_eagerloads(False)
#         # TODO: make sure iteration works well with very large groups. if it's
#         # too slow (on sqlite), it may block/crash Cuckoo
#         # TODO: don't use the ORM for large number of inserts
#         groupid_task = []
#         for task_id in create_parallel_tasks(group.urls, max_parallel):
#             groupid_task.append({
#                 "url_group_id": group.id,
#                 "task_id": task_id
#             })
#
#         if groupid_task:
#             s.bulk_insert_mappings(URLGroupTask, groupid_task)
#         s.commit()
#
#     finally:
#         s.close()
#     log.debug("Tasks created")

def task_creator():
    """Creates tasks"""
    group = next_group_task()
    if not group:
        # Nothing to schedule; ideally we also wait on scheduling_change as
        # well
        return

    log.debug("Have next task. Scheduled @ %s", group.schedule_next)
    while True:
        now = datetime.datetime.utcnow()
        log.info("Now: %s. Next: %s", now, group.schedule_next)
        if now >= group.schedule_next:
            break
        # Make sure long sleeps don't break anything
        delay = min((group.schedule_next - now).total_seconds() + 1, 3600)
        if scheduling_change.wait(timeout=delay):
            # If the schedule changed, we want to recheck which group to
            # execute
            return

    insert_group_tasks(group)

def task_checker():
    """Check if tasks have finalized"""

    # TODO: event based instead of polling
    s = db.Session()
    try:
        # All failed or reported tasks
        tasks = s.query(URLGroupTask, DbTask.status) \
            .filter(URLGroupTask.task_id == DbTask.id,
                    DbTask.status != "pending",
                    DbTask.status != "running",
                    DbTask.status != "completed")
        if not tasks.count():
            return

        check_groups = set()
        for track, task_status in tasks.all():
            if task_status == "aborted":
                # Re-submit all URLs for task id that are not 'analyzed'
                # Look up for what group this task was, so we can match
                # the new task id and group id in URLGroupTask
                urls = s.query(Target.target).filter(
                    Target.task_id == track.task_id,
                    Target.analyzed.is_(False)
                ).all()
                create_single_task(
                    [u.target for u in urls], track.url_group_id
                )

                log.debug("Task #%s for group %s has finished",
                          track.task_id, track.url_group_id)
                # TODO: if malicious and this task has multiple targets,
                # create a new single-target task for every URL
            elif task_status in (
                    TASK_FAILED_ANALYSIS, TASK_FAILED_REPORTING,
                    TASK_FAILED_PROCESSING
            ):
                log.error(
                    "Task #%s for group %s has failed: %s", track.task_id,
                    track.url_group_id, task_status
                )

            check_groups.add(track.url_group_id)
            s.delete(track)
        for group in check_groups:
            have_tasks = s.query(URLGroupTask).filter_by(url_group_id=group).exists()
            if s.query(have_tasks).scalar():
                continue
            log.info("All tasks for group %s have completed", group)
            g = s.query(URLGroup).with_for_update().get(group)
            if g.schedule:
                g.schedule_next = schedule_time_next(g.schedule)
                log.debug("Group %s scheduled at %s", group, g.schedule_next)
            g.completed = True
            s.add(g)
        s.commit()
    finally:
        s.close()

def handle_massurldetection(message):
    for k in ("taskid", "status", "candidates", "signatures"):
        if k not in message["body"]:
            return

    try:
        task_id = int(message["body"].get("taskid"))
    except ValueError:
        return

    status = message["body"].get("status")
    if status != "aborted":
        return

    candidates = message["body"].get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return

    signatures = message["body"].get("signatures")
    if not isinstance(signatures, list) or not signatures:
        return

    for sig in signatures:
        if not isinstance(sig, dict):
            return
        for k in ("signature", "description", "io"):
            if k not in sig:
                return

    diary_id = message["body"].get("diary_id")

    s = db.Session()
    try:
        group = s.query(URLGroup).filter(
            URLGroupTask.task_id==task_id
        ).first()
        if not group:
            return
        s.expunge(group)
    finally:
        s.close()

    if len(candidates) > 1:
        content = "One or more URLs of group '%s' might be infected!" \
                  " Re-analyzing all URLs one-by-one.\n" \
                  "URLs: %s.\n\n" \
                  "Signatures: %s\n" % (
                      group.name,
                      "\n ".join(candidates),
                      "\n ".join(s.get("signature") for s in signatures)
                  )

    else:
        content = "URL %s of group %s shows signs of malware infection!" % (
            candidates[0], group.name
        )

    web.send_alert(
        level=3, title="Detection of malicious behavior!", notify=True,
        url_group_name=group.name, task_id=task_id, diary_id=diary_id,
        content=content
    )

    # If more than a single URL was in the VM, re-analyze them all one-by-one
    if len(candidates) > 1:
        task_id = submit_task.add_massurl(
            urls=candidates, options="free=yes,urlblocksize=1", priority=999
        )
        s = db.Session()
        try:
            grouptask = URLGroupTask()
            grouptask.task_id = task_id
            grouptask.url_group_id = group.id
            s.add(grouptask)
            s.commit()
        finally:
            s.close()

def handle_massurltask(message):
    for k in ("taskid", "action", "status"):
        if k not in message["body"]:
            return

    action = message["body"].get("action")
    if action != "statuschange":
        return

    try:
        taskid = int(message["body"].get("taskid"))
    except ValueError:
        return

    newstatus = message["body"].get("status")
    log.info("Doing query")
    s = db.Session()
    try:
        groupname = s.query(URLGroup.name).filter(
            URLGroupTask.task_id == taskid
        ).first()
    finally:
        s.close()

    if groupname:
        groupname = groupname[0]

    level = 1
    if newstatus in ("failed", "aborted"):
        level = 2

    web.send_alert(
        level=level, title="Task changed status", url_group_name=groupname,
        task_id=taskid,
        content="Task #%s for group '%s' changed status to %s" % (
            taskid, groupname, newstatus
        )
    )

def massurl_scheduler():
    # TODO: increase delays
    gevent.spawn(run_with_minimum_delay, task_creator, 5.0)
    gevent.spawn(run_with_minimum_delay, task_checker, 5.0)
    ev_client.subscribe(handle_massurltask, "massurltask")
    ev_client.subscribe(handle_massurldetection, "massurldetection")
