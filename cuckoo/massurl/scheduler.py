# Copyright (C) 2018-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import logging
import time

import gevent

from cuckoo.core.database import (
    Database, Task as DbTask, Target, TASK_FAILED_ANALYSIS,
    TASK_FAILED_PROCESSING, TASK_FAILED_REPORTING, TASK_ABORTED, TASK_RUNNING,
    TASK_REPORTED
)
from cuckoo.core.task import Task
from cuckoo.massurl import cleanup
from cuckoo.massurl import db as massurldb
from cuckoo.massurl.signatures import run_signature, verify_sig
from cuckoo.massurl import web
from cuckoo.massurl.urldiary import URLDiaries
from cuckoo.massurl.db import (
    URLGroup, URLGroupTask, URLGroupURL, URLGroupProfile
)
from cuckoo.massurl.realtime import ev_client
from cuckoo.massurl.schedutil import schedule_time_next
from cuckoo.misc import cwd

log = logging.getLogger(__name__)
db = Database()
submit_task = Task()
diary_stats = {
    "count": 0
}

OWNER = "cuckoo.massurl"
DEFAULT_OPTIONS = "analysis=kernel"

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
    """Retrieve a group to create tasks for. Only returns a group if it is
     completed has a scheduled date, and has any URLs"""
    s = db.Session()
    try:
        group = s.query(URLGroup).filter(
            URLGroup.schedule_next != None,
            URLGroup.completed.is_(True),
            URLGroup.schedule_next <=
            datetime.datetime.utcnow() + datetime.timedelta(seconds=10),
            URLGroupProfile.group_id==URLGroup.id,
            URLGroupURL.url_group_id == URLGroup.id
        ).order_by(URLGroup.schedule_next).first()
        if group:
            group = group.to_dict(False)
    finally:
        s.close()
    return group

def create_parallel_tasks(targets, max_parallel, **kwargs):
    urls = []

    for t in targets:
        urls.append(t)
        if len(urls) >= max_parallel:
            yield submit_task.add_massurl(urls, **kwargs)
            urls = []
    if urls:
        yield submit_task.add_massurl(urls, **kwargs)

def create_single_task(group_id, urls, run, **kwargs):
    if not kwargs.get("options"):
        kwargs["options"] = DEFAULT_OPTIONS

    task_id = submit_task.add_massurl(urls=urls, **kwargs)
    s = db.Session()
    try:
        grouptask = URLGroupTask()
        grouptask.task_id = task_id
        grouptask.url_group_id = group_id
        grouptask.run = run
        s.add(grouptask)
        s.commit()
    finally:
        s.close()

def generate_task_args(profile, group):
    options = DEFAULT_OPTIONS
    options += ",route=%s" % profile.route

    if profile.country:
        if profile.route == "vpn":
            options += ",vpn.country=%s" % profile.country
        elif profile.route == "socks5":
            options += ",socks5.country=%s" % profile.country

    options += ",urlblocksize=%s" % group.batch_size
    options += ",blocktime=%s" % group.batch_time
    tags = ",".join([t.name for t in profile.tags])

    return {
        "options": options, "package": profile.browser, "tags": tags,
        "owner": OWNER
    }

def insert_group_tasks(group):
    log.debug("Creating group tasks for %r", group["name"])
    group = massurldb.find_group(group_id=group.id)
    urls = massurldb.find_urls_group(group.id, limit=None)
    run = group.run + 1

    groupid_task = []
    for profile in group.profiles:
        log.info(
            "Creating tasks for group %r with profile %r",
            group.name, profile.name
        )
        args = generate_task_args(profile, group)
        for task_id in create_parallel_tasks(urls, group.max_parallel, **args):
            groupid_task.append({
                "url_group_id": group.id,
                "task_id": task_id,
                "run": run
            })

    if groupid_task:
        s = db.Session()
        try:
            s.query(URLGroup).filter(URLGroup.id==group.id).update({
                "completed": False,
                "schedule_next": None,
                "status": "pending",
                "run": run
            })
            s.bulk_insert_mappings(URLGroupTask, groupid_task)
            s.commit()
        finally:
            s.close()

        log.debug(
            "Created %s new tasks for group %s", len(groupid_task), group.name
        )

def task_creator():
    """Creates tasks"""
    while True:
        group = next_group_task()
        if not group:
            break
        insert_group_tasks(group)

def task_checker():
    s = db.Session()
    try:
        tasks = s.query(URLGroupTask, URLGroup.status, DbTask.status).filter(
            URLGroupTask.url_group_id == URLGroup.id,
            URLGroupTask.task_id == DbTask.id,
            URLGroup.completed.is_(False),
            URLGroupTask.run == URLGroup.run,
            DbTask.status != "pending", DbTask.status != "completed"
        )

        if not tasks.count():
            return

        tasks = tasks.all()
        s.expunge_all()
    finally:
        s.close()

    check_groups = set()
    for grouptask, groupstatus, task_status in tasks:
        set_running = False
        if task_status == TASK_RUNNING and groupstatus == "pending":
            set_running = True

        check_groups.add((grouptask.url_group_id, set_running))

        # Verify if the failed or aborted task was already resubmitted.
        # Create a new submission if any URLs for a failed task were not
        # analyzed
        if not grouptask.resubmitted and task_status in (
                TASK_FAILED_ANALYSIS, TASK_FAILED_REPORTING,
                TASK_FAILED_PROCESSING, TASK_ABORTED
        ):

            log.error(
                "Task #%s for group %r has status: %s", grouptask.task_id,
                grouptask.url_group_id, task_status
            )

            s = db.Session()
            # Retrieve all URLs for the failed task that have not been marked
            # as analyzed and mark the grouptask relation as resubmitted, so
            # that it will not try to resubmit it again.
            task = None
            try:
                s.query(URLGroupTask).filter(
                    URLGroupTask.id==grouptask.id
                ).update({"resubmitted": True})

                urls = s.query(Target.target).filter(
                    Target.task_id == grouptask.task_id,
                    Target.analyzed.is_(False)
                )
                if urls.count():
                    urls = [u.target for u in urls.all()]
                    task = s.query(DbTask).get(grouptask.task_id)
                    s.expunge(task)

                s.commit()
            finally:
                s.close()

            # Create a new task for URLs that have not been analyzed yet.
            if task:
                log.debug(
                    "Creating new task for failed task #%s", grouptask.task_id
                )
                create_single_task(
                    group_id=grouptask.url_group_id, urls=urls,
                    run=grouptask.run, custom="%d" % grouptask.task_id,
                    options=task.options, machine=task.machine,
                    package=task.package, clock=task.clock, owner=OWNER
                )

    s = db.Session()
    alerts = []
    try:
        for group_id, set_running in check_groups:
            if set_running:
                group = s.query(URLGroup).get(group_id)
                if group.status == "pending":
                    group.status = "running"
                    s.add(group)
                    alerts.append({
                        "level": 1, "title": "Group analysis started",
                        "url_group_name": group.name,
                        "content": "The analysis of group '%s' "
                                   "has started" % group.name
                    })
                    s.commit()
                continue

            have_tasks = s.query(DbTask).filter(
                URLGroupTask.url_group_id==group_id,
                URLGroupTask.task_id == DbTask.id,
                URLGroupTask.run == URLGroup.run,
                URLGroupTask.resubmitted.is_(False),
                DbTask.status != TASK_REPORTED
            ).exists()

            if s.query(have_tasks).scalar():
                continue

            group = s.query(URLGroup).with_for_update().get(group_id)
            log.info("All tasks for group %s have completed", group.name)

            if group.schedule:
                group.schedule_next = schedule_time_next(group.schedule)
                log.debug(
                    "Group %s scheduled at %s", group_id, group.schedule_next
                )

            group.completed = True
            group.status = "completed"
            s.add(group)

            alerts.append({
                "level": 1, "title": "Group analysis completed",
                "url_group_name": group.name,
                "content": "The analysis of group '%s' has completed. %s" % (
                    group.name, ("Next run at %s" % group.schedule_next)
                    if group.schedule_next else ""
                )
            })
            s.commit()
    finally:
        s.close()

    for alert in alerts:
        web.send_alert(**alert)

def signature_runner():
    new_count = URLDiaries.count_diaries()
    if new_count == diary_stats["count"]:
        return

    diary_stats["count"] = new_count
    for signature in massurldb.list_signatures(enabled_only=True):
        content = verify_sig(signature.content)
        if not content:
            log.error("Invalid signature")
            continue

        matches = run_signature(content, signature.last_run)
        if not matches:
            continue

        log.info(
            "Custom signature match for %s. Matches %s",
            signature.name, len(matches)
        )

        for match in matches:
            diary = URLDiaries.get_diary(
                diary_id=match, return_fields=["url", "version"]
            )
            if not diary:
                continue

            web.send_alert(
                title="Custom signature match! '%s'" % signature.name,
                level=signature.level, diary_id=match,
                signature=signature.name,
                content="URL diary(version=%s)"
                        " for URL %s matched signature %s." % (
                            diary.get("version"), diary.get("url"),
                            signature.name,
                        )
            )
        massurldb.update_signature(
            signature_id=signature.id, last_run=int(time.time() * 1000)
        )

def validate_message(message, extra_keys=[]):
    keys = ["taskid", "status"]
    keys.extend(extra_keys)
    for k in keys:
        if k not in message.get("body", {}):
            return None

    try:
        message["body"]["taskid"] = int(message["body"]["taskid"])
    except ValueError:
        return None

    return message

def handle_massurldetection(message):
    message = validate_message(
        message, ["candidates", "signatures"]
    )

    log.info("Received detection event: %s", message)
    task_id = message["body"].get("taskid")

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
        for k in ("signature", "description", "ioc"):
            if k not in sig:
                return

    diary_id = message["body"].get("diary_id")
    group = massurldb.find_group_task(task_id)
    if not group:
        log.debug(
            "Received alert for task that is not for any of the existing"
            " groups"
        )
        return

    log.info("Amount of targets in machine was %s", len(candidates))
    if len(candidates) > 1:
        content = "One or more URLs of group '%s' might be infected!" \
                  " Re-analyzing all URLs one-by-one.\n " \
                  "URLs: %s.\n\n" \
                  "Signatures: %s\n\n"\
                  "IoC: %s\n"% (
                      group.name,
                      "\n ".join(candidates),
                      "\n ".join(s.get("signature") for s in signatures),
                      "\n ".join(s.get("ioc") for s in signatures)
                  )

    else:
        content = "URL %s of group '%s' shows signs of malware infection! " % (
            candidates[0], group.name
        )

    web.send_alert(
        level=3, title="Detection of malicious behavior!", notify=True,
        url_group_name=group.name, task_id=task_id, diary_id=diary_id,
        content=content
    )

    # If more than a single URL was in the VM, re-analyze them all one-by-one
    if len(candidates) > 1:
        log.info("Creating new replay task for remaining URLs in VM")
        task = db.view_task(task_id=task_id)
        create_single_task(
            group_id=group.id, urls=candidates, run=group.run, priority=999,
            owner=OWNER, machine=task.machine, package=task.package,
            custom=task_id,
            options="analysis=kernel,urlblocksize=1,replay=%s" % cwd(
                "dump.pcap", analysis=task_id
            )
        )

def handle_massurltaskfailure(message):
    message = validate_message(message, ["error"])
    if not message:
        return

    task_id = message["body"].get("taskid")
    error = message["body"].get("error")
    group = massurldb.find_group_task(task_id)
    if not group:
        log.debug(
            "Received alert for task that is not for any of the existing"
            " groups"
        )
        return

    web.send_alert(
        title="Group '%s' task #%s encountered a fatal error" %
              (group.name, task_id),
        content="Task #%s encountered a fatal error that caused the task to "
                "fail. Error: %s." % (task_id, error),
        url_group_name=group.name, level=2
    )

def massurl_scheduler():
    # TODO: increase delays
    gevent.spawn(run_with_minimum_delay, task_creator, 10.0)
    gevent.spawn(run_with_minimum_delay, task_checker, 10.0)
    gevent.spawn(run_with_minimum_delay, signature_runner, 20.0)
    gevent.spawn(run_with_minimum_delay, cleanup.clean, 3600.0)
    ev_client.subscribe(handle_massurldetection, "massurldetection")
    ev_client.subscribe(handle_massurltaskfailure, "massurltaskfailure")
