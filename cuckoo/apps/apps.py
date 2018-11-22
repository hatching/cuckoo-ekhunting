# Copyright (C) 2016-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import fnmatch
import hashlib
import io
import logging
import os
import random
import requests
import shutil
import subprocess
import sys
import tarfile
import time

from cuckoo.common.colors import bold, red, yellow
from cuckoo.common.config import emit_options, Config
from cuckoo.common.elastic import elastic
from cuckoo.common.exceptions import (
    CuckooOperationalError, CuckooDatabaseError, CuckooDependencyError
)
from cuckoo.common.mongo import mongo
from cuckoo.common.objects import File
from cuckoo.common.utils import to_unicode, json_decode
from cuckoo.core.database import (
    Database, TASK_PENDING, TASK_FAILED_PROCESSING, TASK_REPORTED
)
from cuckoo.core.init import write_cuckoo_conf
from cuckoo.core.log import task_log_start, task_log_stop, logger
from cuckoo.core.startup import init_console_logging
from cuckoo.core.task import Task
from cuckoo.core.target import Target
from cuckoo.misc import cwd, mkdir


log = logging.getLogger(__name__)
submit_task = Task()

URL = "https://github.com/cuckoosandbox/community/archive/%s.tar.gz"

def fetch_community(branch="master", force=False, filepath=None):
    if filepath:
        buf = open(filepath, "rb").read()
    else:
        log.info("Downloading.. %s", URL % branch)
        r = requests.get(URL % branch)
        if r.status_code != 200:
            raise CuckooOperationalError(
                "Error fetching the Cuckoo Community binaries "
                "(status_code: %d)!" % r.status_code
            )

        buf = r.content

    t = tarfile.TarFile.open(fileobj=io.BytesIO(buf), mode="r:gz")

    folders = {
        "modules/signatures": "signatures",
        "data/monitor": "monitor",
        "data/yara": "yara",
        "agent": "agent",
        "analyzer": "analyzer",
    }

    members = t.getmembers()

    directory = members[0].name.split("/")[0]
    for tarfolder, outfolder in folders.items():
        mkdir(cwd(outfolder))

        # E.g., "community-master/modules/signatures".
        name_start = "%s/%s" % (directory, tarfolder)
        for member in members:
            if not member.name.startswith(name_start) or \
                    name_start == member.name:
                continue

            filepath = cwd(outfolder, member.name[len(name_start)+1:])
            if member.isdir():
                mkdir(filepath)
                continue

            # TODO Ask for confirmation as we used to do.
            if os.path.exists(filepath) and not force:
                log.debug(
                    "Not overwriting file which already exists: %s",
                    member.name[len(name_start)+1:]
                )
                continue

            if member.issym():
                t.makelink(member, filepath)
                continue

            if not os.path.exists(os.path.dirname(filepath)):
                os.makedirs(os.path.dirname(filepath))

            log.debug("Extracted %s..", member.name[len(name_start)+1:])
            open(filepath, "wb").write(t.extractfile(member).read())

def enumerate_files(path, pattern):
    """Yields all filepaths from a directory."""
    if os.path.isfile(path):
        yield path
    elif os.path.isdir(path):
        for dirname, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirname, filename)

                if os.path.isfile(filepath):
                    if pattern:
                        if fnmatch.fnmatch(filename, pattern):
                            yield to_unicode(filepath)
                    else:
                        yield to_unicode(filepath)

def submit_tasks(target, options, package, custom, owner, timeout, priority,
                 machine, platform, memory, enforce_timeout, clock, tags,
                 remote, pattern, maxcount, is_unique, is_url, is_baseline,
                 is_shuffle, start_on):
    db = Database()

    data = dict(
        package=package or "",
        timeout=timeout,
        options=options,
        priority=priority,
        machine=machine,
        platform=platform,
        custom=custom,
        owner=owner,
        tags=tags,
        memory="1" if memory else "0",
        enforce_timeout="1" if enforce_timeout else "0",
        clock=clock,
        unique="1" if is_unique else "0",
        start_on=start_on
    )

    if is_baseline:
        if remote:
            log.info("Remote baseline support has not yet been implemented.")
            return

        task_id = submit_task.add_baseline(timeout, owner, machine, memory)
        yield "Baseline", machine, task_id
        return

    if is_url and is_unique:
        log.info("URL doesn't have --unique support yet.")
        return

    if is_url:
        for url in target:
            if not remote:
                data.pop("unique", None)
                task_id = submit_task.add_url(to_unicode(url), **data)
                yield "URL", url, task_id
                continue

            data["url"] = to_unicode(url)
            try:
                r = requests.post(
                    "http://%s/tasks/create/url" % remote, data=data
                )
                yield "URL", url, r.json()["task_id"]
            except Exception as e:
                log.error(
                    "%s: unable to submit URL: %s", bold(red("Error")), e
                )
    else:
        files = []
        for path in target:
            files.extend(enumerate_files(os.path.abspath(path), pattern))

        if is_shuffle:
            random.shuffle(files)

        for filepath in files:
            if not os.path.getsize(filepath):
                log.warning(
                    "%s: sample %s (skipping file)", bold(yellow("Empty")),
                    filepath
                )
                continue

            if maxcount is not None:
                if not maxcount:
                    break
                maxcount -= 1

            if not remote:
                if is_unique:
                    sha256 = File(filepath).get_sha256()
                    if db.find_target(sha256=sha256):
                        log.info(
                            "File \"%s\" has already been analyzed", filepath
                        )
                        yield "File", filepath, None
                        continue

                data.pop("unique", None)
                task_id = submit_task.add_path(file_path=filepath, **data)
                yield "File", filepath, task_id
                continue

            files = {
                "file": (os.path.basename(filepath), open(filepath, "rb")),
            }

            try:
                r = requests.post(
                    "http://%s/tasks/create/file" % remote,
                    data=data, files=files
                )
                yield "File", filepath, r.json()["task_id"]
            except Exception as e:
                log.error(
                    "%s: unable to submit file: %s", bold(red("Error")), e
                )
                continue

def process_task(task):
    db = Database()
    if not task.dir_exists():
        log.error(
            "Task #%s directory %s does not exist, cannot process it",
            task.id, task.path
        )
        db.set_status(task.id, TASK_FAILED_PROCESSING)
        return

    task_log_start(task.id)

    if task.targets:
        target = task.targets[0]
    else:
        target = Target()

    logger(
        "Starting task reporting",
        action="task.report", status="pending",
        target=target.target, category=target.category,
        package=task["package"], options=emit_options(task["options"]),
        custom=task["custom"]
    )

    success = False
    try:
        success = task.process()
    except Exception as e:
        log.error("Failed to process task #%s. Error: %s", task.id, e)
    finally:
        if success:
            log.info(
                "Task #%d: reports generation completed", task.id,
                extra={
                    "action": "task.report",
                    "status": "success",
                }
            )
            db.set_status(task.id, TASK_REPORTED)
        else:
            log.error(
                "Failed to process task #%s", task.id,
                extra={
                    "action": "task.report",
                    "status": "failed",
                }
            )
            db.set_status(task.id, TASK_FAILED_PROCESSING)
        task_log_stop(task.id)

def process_task_range(tasks):
    db, task_ids = Database(), []
    for entry in tasks.split(","):
        if entry.isdigit():
            task_ids.append(int(entry))
        elif entry.count("-") == 1:
            start, end = entry.split("-")
            if not start.isdigit() or not end.isdigit():
                log.warning("Invalid range provided: %s", entry)
                continue
            task_ids.extend(range(int(start), int(end)+1))
        elif entry:
            log.warning("Invalid range provided: %s", entry)

    for task_id in sorted(set(task_ids)):
        db_task = db.view_task(task_id)
        task = Task()
        if not db_task:
            task_json = cwd("task.json", analysis=task_id)
            if os.path.isfile(task_json):
                task_dict = json_decode(open(task_json, "rb").read())
            else:
                task_dict = {
                    "id": task_id,
                    "category": "file",
                    "target": "",
                    "options": {},
                    "package": None,
                    "custom": None,
                }

            task.load_task_dict(task_dict)
        else:
            task.set_task(db_task)

        process_task(task)

def process_check_stop(count, maxcount, endtime):
    """Check if we need to stop processing.
     Options passed by maxcount (-m) or calculated endtime (-t)
    """
    if maxcount and count >= maxcount:
        return False

    if endtime and int(time.time()) > endtime:
        return False

    return True

def process_tasks(instance, maxcount, timeout):
    count = 0
    endtime = 0
    db = Database()

    if timeout:
        endtime = int(time.time() + timeout)

    try:
        while process_check_stop(count, maxcount, endtime):
            task_id = db.processing_get_task(instance)

            # Wait a small while before trying to fetch a new task.
            if task_id is None:
                time.sleep(1)
                continue

            task = Task(db.view_task(task_id))

            log.info("Task #%d: reporting task", task.id)

            process_task(task)
            count += 1
    except Exception as e:
        log.exception("Caught unknown exception: %s", e)

def cuckoo_clean():
    """Clean up cuckoo setup.
    It deletes logs, all stored data from file system and configured
    databases (SQL and MongoDB).
    """
    # Init logging (without writing to file).
    init_console_logging()

    try:
        # Initialize the database connection.
        db = Database()
        db.connect(schema_check=False)

        # Drop all tables.
        db.drop()
    except (CuckooDependencyError, CuckooDatabaseError) as e:
        # If something is screwed due to incorrect database migrations or bad
        # database SqlAlchemy would be unable to connect and operate.
        log.warning("Error connecting to database: it is suggested to check "
                    "the connectivity, apply all migrations if needed or purge "
                    "it manually. Error description: %s", e)

    # Check if MongoDB reporting is enabled and drop the database if it is.
    if mongo.init():
        try:
            mongo.connect()
            mongo.drop()
            mongo.close()
        except Exception as e:
            log.warning("Unable to drop MongoDB database: %s", e)

    # Check if ElasticSearch reporting is enabled and drop its data if it is.
    if elastic.init():
        elastic.connect()

        # TODO This should be moved to the elastic abstract.
        # TODO We should also drop historic data, i.e., from pervious days,
        # months, and years.
        date_index = datetime.datetime.utcnow().strftime({
            "yearly": "%Y",
            "monthly": "%Y-%m",
            "daily": "%Y-%m-%d",
        }[elastic.index_time_pattern])
        dated_index = "%s-%s" % (elastic.index, date_index)

        elastic.client.indices.delete(
            index=dated_index, ignore=[400, 404]
        )

        template_name = "%s_template" % dated_index
        if elastic.client.indices.exists_template(template_name):
            elastic.client.indices.delete_template(template_name)

    # Paths to clean.
    paths = [
        cwd("cuckoo.db"),
        cwd("log"),
        cwd("storage", "analyses"),
        cwd("storage", "baseline"),
        cwd("storage", "binaries"),
    ]

    # Delete the various files and directories. In case of directories, keep
    # the parent directories, so to keep the state of the CWD in tact.
    for path in paths:
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
                os.mkdir(path)
            except (IOError, OSError) as e:
                log.warning("Error removing directory %s: %s", path, e)
        elif os.path.isfile(path):
            try:
                os.unlink(path)
            except (IOError, OSError) as e:
                log.warning("Error removing file %s: %s", path, e)

def cuckoo_machine(vmname, action, ip, platform, options, tags,
                   interface, snapshot, resultserver):
    db = Database()

    cfg = Config.from_confdir(cwd("conf"))
    machinery = cfg["cuckoo"]["cuckoo"]["machinery"]
    machines = cfg[machinery][machinery]["machines"]

    if action == "add":
        if not ip:
            sys.exit("You have to specify a legitimate IP address for --add.")

        if db.view_machine(vmname):
            sys.exit("A Virtual Machine with this name already exists!")

        if vmname in machines:
            sys.exit("A Virtual Machine with this name already exists!")

        if resultserver and resultserver.count(":") == 1:
            resultserver_ip, resultserver_port = resultserver.split(":")
            resultserver_port = int(resultserver_port)
        else:
            resultserver_ip = cfg["cuckoo"]["resultserver"]["ip"]
            resultserver_port = cfg["cuckoo"]["resultserver"]["port"]

        machines.append(vmname)
        cfg[machinery][vmname] = {
            "label": vmname,
            "platform": platform,
            "ip": ip,
            "options": options,
            "snapshot": snapshot,
            "interface": interface,
            "resultserver_ip": resultserver_ip,
            "resultserver_port": resultserver_port,
            "tags": tags,
        }

        db.add_machine(
            vmname, vmname, ip, platform, options, tags, interface, snapshot,
            resultserver_ip, int(resultserver_port), machinery
        )
        db.unlock_machine(vmname)

    if action == "delete":
        # TODO Add a db.del_machine() function for runtime modification.

        if vmname not in machines:
            sys.exit("A Virtual Machine with this name doesn't exist!")

        machines.remove(vmname)
        cfg[machinery].pop(vmname)

    write_cuckoo_conf(cfg=cfg)

def migrate_database(revision="head"):
    args = [
        "alembic", "-x", "cwd=%s" % cwd(), "upgrade", revision,
    ]
    try:
        subprocess.check_call(args, cwd=cwd("db_migration", private=True))
    except subprocess.CalledProcessError:
        return False
    return True

def migrate_cwd():
    db = Database()
    log.warning(
        "This is the first time you're running Cuckoo after updating your "
        "local version of Cuckoo. We're going to update files in your CWD "
        "that require updating. Note that we'll first ensure that no custom "
        "patches have been applied by you before applying any modifications "
        "of our own."
    )

    # Remove now-obsolete index_*.yar files.
    for filename in os.listdir(cwd("yara")):
        if filename.startswith("index_") and filename.endswith(".yar"):
            os.remove(cwd("yara", filename))

    # Create new directories if not present yet.
    mkdir(cwd("stuff"))
    mkdir(cwd("yara", "office"))

    # Create the new $CWD/whitelist/ directory.
    if not os.path.exists(cwd("whitelist")):
        shutil.copytree(
            cwd("..", "data", "whitelist", private=True), cwd("whitelist")
        )

    # Create the new $CWD/yara/dumpmem/ directory.
    if not os.path.exists(cwd("yara", "dumpmem")):
        mkdir(cwd("yara", "dumpmem"))

    hashes = {}
    for line in open(cwd("cwd", "hashes.txt", private=True), "rb"):
        if not line.strip() or line.startswith("#"):
            continue
        hash_, filename = line.split()
        hashes[filename] = hashes.get(filename, []) + [hash_]

    # We remove $CWD/monitor/latest upfront if it's a symbolic link, because
    # our migration code doesn't properly handle symbolic links.
    if os.path.islink(cwd("monitor", "latest")):
        os.remove(cwd("monitor", "latest"))

    modified, outdated, deleted = [], [], []
    for filename, hashes in hashes.items():
        if not os.path.exists(cwd(filename)):
            if hashes[-1] != "0"*40:
                outdated.append(filename)
            continue
        hash_ = hashlib.sha1(open(cwd(filename), "rb").read()).hexdigest()
        if hash_ not in hashes:
            modified.append(filename)
        elif hashes[-1] == "0"*40:
            deleted.append(filename)
        elif hash_ != hashes[-1]:
            outdated.append(filename)

    if modified:
        log.error(
            "One or more files in the CWD have been modified outside of "
            "regular Cuckoo usage. Due to these changes Cuckoo isn't able to "
            "automatically upgrade your setup."
        )

        for filename in sorted(modified):
            log.warning("Modified file: %s (=> %s)", filename, cwd(filename))

        log.error("Moving forward you have two options:")
        log.warning(
            "1) You make a backup of the affected files, remove their "
            "presence in the CWD (yes, actually 'rm -f' the file), and "
            "re-run Cuckoo to automatically restore the new version of the "
            "file. Afterwards you'll be able to re-apply any changes as you "
            "like."
        )
        log.warning(
            "2) You revert back to the version of Cuckoo you were on "
            "previously and accept that manual changes that have not been "
            "merged upstream require additional maintenance that you'll "
            "pick up at a later point in time."
        )

        sys.exit(1)

    for filename in sorted(deleted):
        log.debug("Deleted %s", filename)
        os.unlink(cwd(filename))

    for filename in sorted(outdated):
        filepath = cwd("..", "data", filename, private=True)
        if not os.path.exists(filepath):
            log.debug(
                "Failed to upgrade file not shipped with this release: %s",
                filename
            )
            continue

        log.debug("Upgraded %s", filename)
        if not os.path.exists(os.path.dirname(cwd(filename))):
            os.makedirs(os.path.dirname(cwd(filename)))
        shutil.copy(filepath, cwd(filename))

    log.info("Checking if any task directories are missing")
    for db_task in db.list_tasks(status=TASK_PENDING, details=False):
        task = Task(db_task)
        if not task.dir_exists():
            task.create_empty()
            for target in task.targets:
                if target.is_file and not os.path.exists(target.copied_binary):
                    target.copy()
        else:
            # Always call this so that missing (newly added) directories
            # are created
            task.create_dirs()

    log.info(
        "Automated migration of your CWD was successful! Continuing "
        "execution of Cuckoo as expected."
    )
