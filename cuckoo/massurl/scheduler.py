# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import gevent
import logging
import time

from cuckoo.core.database import Database, Task
from cuckoo.massurl.db import URLGroup, URLGroupTask
from cuckoo.massurl.schedutil import schedule_time_next

log = logging.getLogger(__name__)
db = Database()

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
    group = s.query(URLGroup).filter_by(completed=True) \
        .order_by(URLGroup.schedule_next).first()
    if group:
        group = group.to_dict(False)
    s.close()
    return group

def create_url_task(targets):
    assert len(targets) == 1, "Only one URL per task is supported"
    target = targets[0]
    t = Task(target)
    t.category = "url"
    # TODO: probably based on len(targets)
    t.timeout = 10
    t.package = ""
    t.options = ""
    t.priority = 1
    t.custom = ""
    t.owner = OWNER
    t.machine = ""
    t.platform = ""
    t.memory = False
    t.enforce_timeout = False
    return t

def create_parallel_tasks(urls, max_parallel):
    task = []
    for u in urls:
        task.append(u.target)
        if len(task) >= max_parallel:
            yield create_url_task(task)
            task = []
    if task:
        yield create_url_task(task)

def insert_group_tasks(group):
    log.debug("Creating group tasks for %r", group["name"])
    s = db.Session()
    try:
        group = s.query(URLGroup).with_for_update().get(group.id)
        group.completed = False
        s.add(group)

        max_parallel = group.max_parallel if False else 1

        # TODO: .yield_per(500).enable_eagerloads(False)
        # TODO: make sure iteration works well with very large groups. if it's
        # too slow (on sqlite), it may block/crash Cuckoo
        # TODO: don't use the ORM for large number of inserts
        for task in create_parallel_tasks(group.urls, max_parallel):
            s.add(task)
            group.tasks.append(task)
            #s.flush()
            #URLGroupTask(task_id=
            #f

        s.commit()

    finally:
        s.close()
    log.debug("Tasks created")

def task_creator():
    """Creates tasks"""
    group = next_group_task()
    if not group:
        # Nothing to schedule; ideally we also wait on scheduling_change as
        # well
        return

    log.debug("Have next task. Scheduled @ %r", group.schedule_next)
    while True:
        now = datetime.datetime.utcnow()
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
        tasks = s.query(URLGroupTask, Task.status) \
            .filter(URLGroupTask.task_id == Task.id,
                    Task.status != "pending",
                    Task.status != "running",
                    Task.status != "completed")
        if not tasks.count():
            return
        check_groups = set()
        for track, task_status in tasks.all():
            if task_status == "reported":
                # This is where you would put the task ID into a queue so
                # that the report can be added to the URL diary

                log.debug("Task #%s for group %s has finished",
                          track.task_id, track.url_group_id)
                # TODO: if malicious and this task has multiple targets,
                # create a new single-target task for every URL
            else:
                log.error("Task #%s for group %s has failed: %s",
                          track.task_id, track.url_group_id,
                          task_status)
            check_groups.add(track.url_group_id)
            s.delete(track)
        for group in check_groups:
            have_tasks = s.query(URLGroupTask).filter_by(url_group_id=group).exists()
            if s.query(have_tasks).scalar():
                continue
            log.info("All tasks for group %s have completed", group)
            g = s.query(URLGroup).with_for_update().get(group)
            g.schedule_next = schedule_time_next(g.schedule)
            log.debug("Group %s scheduled at %s", group, g.schedule_next)
            g.completed = True
            s.add(g)
        s.commit()
    finally:
        s.close()

def massurl_scheduler():
    # TODO: increase delays
    gevent.spawn(run_with_minimum_delay, task_creator, 10.0)
    gevent.spawn(run_with_minimum_delay, task_checker, 10.0)
