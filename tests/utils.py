# Copyright (C) 2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import os
import sys

from cuckoo.misc import mkdir, cwd, load_signatures
from cuckoo.core.database import Database, Task as DbTask, Target as DbTarget
from cuckoo.common.objects import File, URL

db = Database()

class chdir(object):
    """Temporarily change the current directory."""

    def __init__(self, dirpath):
        self.dirpath = dirpath

    def __enter__(self):
        self.origpath = os.getcwd()
        os.chdir(self.dirpath)

    def __exit__(self, type_, value, traceback):
        os.chdir(self.origpath)

def init_analysis(task_id, package, *filename):
    """Initializes an analysis with an "encrypted" binary from tests/files/."""
    mkdir(cwd(analysis=task_id))
    content = open(os.path.join("tests", "files", *filename), "rb").read()
    open(cwd("binary", analysis=task_id), "wb").write(content[::-1])

def reload_signatures():
    sys.modules.pop("signatures", None)
    sys.modules.pop("signatures.android", None)
    sys.modules.pop("signatures.cross", None)
    sys.modules.pop("signatures.darwin", None)
    sys.modules.pop("signatures.extractor", None)
    sys.modules.pop("signatures.linux", None)
    sys.modules.pop("signatures.network", None)
    sys.modules.pop("signatures.windows", None)
    load_signatures()

def add_task(target=None, category="file",timeout=0, package="", options="",
            priority=1, custom="", owner="", machine="", platform="",
            tags=[], memory=False, enforce_timeout=False, clock=None,
            task_type="regular", submit_id=None, start_on=None,
            longterm_id=None, status=None):
    db_target = None

    if category == "file":
        db_target = create_target_file(target)
    elif category == "url":
        db_target = create_target_url(target)

    newtask = DbTask()
    newtask.type = task_type
    newtask.timeout = timeout
    newtask.priority = priority
    newtask.custom = custom
    newtask.owner = owner
    newtask.machine = machine
    newtask.package = package
    newtask.options = options
    newtask.platform = platform
    newtask.memory = memory
    newtask.enforce_timeout = enforce_timeout
    newtask.clock = clock
    newtask.submit_id = submit_id
    newtask.start_on = start_on
    newtask.longterm_id = longterm_id
    newtask.status = status

    ses = db.Session()
    try:
        for tag in tags:
            newtask.tags.append(db.get_or_create(ses, name=tag))
        ses.add(newtask)
        ses.commit()
        task_id = newtask.id
        if target:
            db_target.task_id = task_id
            ses.add(db_target)
            ses.commit()
    finally:
        ses.close()

    return task_id

def add_target(target, category="file", task_id=None):
    if category == "url":
        db_target = create_target_url(target)
    elif category == "file":
        db_target = create_target_file(target)

    if not task_id:
        task_id = add_task()

    db_target.task_id = task_id
    ses = db.Session()
    target_id = None
    try:
        ses.add(db_target)
        ses.commit()
        target_id = db_target.id
    finally:
        ses.close()

    return target_id

def create_target_file(target=__file__):
    fileobj = File(target or __file__)
    return DbTarget(
        target=target, crc32=fileobj.get_crc32(),
        md5=fileobj.get_md5(), sha1=fileobj.get_sha1(),
        sha256=fileobj.get_sha256(),
        sha512=fileobj.get_sha512(),
        ssdeep=fileobj.get_ssdeep(), category="file",
        file_size=fileobj.get_size(), file_type=fileobj.get_type()
    )

def create_target_url(url):
    urlobj = URL(url)
    return DbTarget(
        target=url, crc32=urlobj.get_crc32(),
        md5=urlobj.get_md5(), sha1=urlobj.get_sha1(),
        sha256=urlobj.get_sha256(),
        sha512=urlobj.get_sha512(),
        ssdeep=urlobj.get_ssdeep(), category="url"
    )
