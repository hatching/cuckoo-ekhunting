# Copyright (C) 2016-2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import os
import logging
import threading

from cuckoo.common.config import Config
from cuckoo.common.objects import File, URL
from cuckoo.common.files import Folders, Files
from cuckoo.core.database import Database
from cuckoo.misc import cwd
from cuckoo.common.exceptions import (
    CuckooOperationalError, CuckooDatabaseError
)
from cuckoo.core.plugins import RunProcessing, RunSignatures, RunReporting

log = logging.getLogger(__name__)

class Task(object):

    files = ["file", "archive"]
    latest_symlink_lock = threading.Lock()

    def __init__(self, db_task):
        self.cfg = Config()
        self.db = Database()
        self.set_task(db_task)

    def set_task(self, db_task):
        """Update Task wrapper with new task db object"""
        self.db_task = db_task
        self.path = cwd("storage", "analyses", str(db_task.id))
        self.file = db_task.category in Task.files
        self.copied_binary = None
        self._read_copied_binary()

    def create_empty(self):
        """Create task directory and copy files to binary folder"""
        log.debug("Creating empty task directory for task #%s", self.id)
        self.create_dirs()
        self.bin_copy_and_symlink()

    def create_dirs(self):
        """Create the folder for this analysis"""
        if self.dir_exists():
            return

        try:
            Folders.create(self.path)
        except CuckooOperationalError as e:
            log.error("Unable to create analysis folder for task #%s. "
                      "Error: %s", self.id, e)

    def bin_copy_and_symlink(self, copyto=None):
        """Create a copy of the submitted sample to the binaries directory
        and create a symlink to it in the task folder

        @param copyto: overwrite the default copy location. Default is
        the binaries folder in the cwd. File name will be the sha256 hash of
        the file
        """
        symlink = os.path.join(self.path, "binary")
        if not self.file or os.path.exists(symlink):
            return

        copy_to = cwd("storage", "binaries", File(self.target).get_sha256())

        if copyto:
            copy_to = copyto

        if not os.path.exists(copy_to):
            Files.copy(self.target, copy_to)
            self.copied_binary = copy_to

        try:
            Files.symlink(copy_to, symlink, copy_on_fail=True)
        except OSError as e:
            log.error("Failed to create symlink in task folder #%s to "
                      "file %s. Error: %s", self.id, copy_to, e)

    def set_latest(self):
        """Create a symlink called 'latest' pointing to this analysis
        in the analysis folder"""
        latest = cwd("storage", "analyses", "latest")
        try:
            Task.latest_symlink_lock.acquire()

            if os.path.lexists(latest):
                os.remove(latest)

            Files.symlink(self.path, latest)
        except OSError as e:
            log.error("Error pointing to latest analysis symlink. Error: %s",
                      e)
        finally:
            Task.latest_symlink_lock.release()

    def _read_copied_binary(self):
        """Use the 'binary' symlink in the task folder to read the
        path of the copy of the sample"""
        symlink = os.path.join(self.path, "binary")
        if not os.path.exists(symlink):
            return

        self.copied_binary = os.path.realpath(symlink)

    def delete_original_sample(self):
        """Delete the original sample file for this task. This is the location
        of where the file was submitted from"""
        if not os.path.exists(self.target):
            log.warning("Cannot delete original file \'%s\'. It does not "
                        "exist anymore", self.target)
        else:
            try:
                os.remove(self.target)
            except OSError as e:
                log.error("Failed to delete original file at path \'%s\'"
                          " Error: %s", self.target, e)

    def delete_copied_sample(self):
        """Delete the copy of the sample, which is stored in the working
        directory binaries folder. Also removes the symlink to this file"""
        success = False
        if not os.path.exists(self.copied_binary):
            log.warning("Cannot delete copied file \'%s\'. It does not "
                        "exist anymore", self.copied_binary)
        else:
            try:
                os.remove(self.copied_binary)
                success = True
            except OSError as e:
                log.error("Failed to delete copied file at path \'%s\'"
                          " Error: %s", self.copied_binary, e)

        if not success:
            return
        # If the copied binary was deleted, also delete the symlink to it

        symlink = os.path.join(self.path, "binary")
        if os.path.islink(symlink):
            try:
                os.remove(symlink)
            except OSError as e:
                log.error("Failed to delete symlink to removed binary \'%s\'."
                          " Error: %s", symlink, e)

    def dir_exists(self):
        """Checks if the analysis folder for this task id exists"""
        return os.path.exists(self.path)

    def is_reported(self):
        """Checks if a JSON report exists for this task"""
        return os.path.exists(os.path.join(self.path, "reports",
                                           "report.json"))

    def write_to_disk(self, path=None):
        """Change task to JSON and write it to disk"""
        if not path:
            path = os.path.join(self.path, "task.json")

        if not self.dir_exists():
            self.create_dirs()

        with open(path, "wb") as fw:
            fw.write(self.db_task.to_json())

    def process(self):
        """Process, run signatures and reports the results for this task"""
        task_json = self.db_task.to_dict()
        results = RunProcessing(task=self.db_task.to_dict()).run()

        if not results:
            return False

        RunSignatures(results=results).run()
        RunReporting(task=task_json, results=results).run()

        if self.file and self.cfg.cuckoo.delete_original:
            self.delete_original_sample()

        if self.file and self.cfg.cuckoo.delete_bin_copy:
            self.delete_original_sample()

        return True

    def __getattr__(self, item):
        """Map attributes back to the db task object"""
        if not hasattr(self.db_task, item):
            raise AttributeError("Task object does not have attribute \'%s\'"
                                 % item)

        return getattr(self.db_task, item, None)

    def _get_tags_list(self, tags):
        """Check tags and into usable format"""
        _tags = []
        if isinstance(tags, basestring):
            for tag in tags.split(","):
                if tag.strip():
                    _tags.append(tag.strip())

        elif isinstance(tags, (tuple, list)):
            for tag in tags:
                if isinstance(tag, basestring) and tag.strip():
                    _tags.append(tag.strip())
        else:
            _tags = None

        return _tags

    def add(self, obj, timeout=0, package="", options="", priority=1,
            custom="", owner="", machine="", platform="", tags=None,
            memory=False, enforce_timeout=False, clock=None, category=None,
            submit_id=None):

        # Convert empty strings and None values to a valid int
        if not timeout:
            timeout = 0
        if not priority:
            priority = 1

        sample_id = None
        if category in self.files and isinstance(obj, File):
            sample = self.db.add_sample(obj)
            if not sample:
                raise CuckooDatabaseError("Failed to add sample"
                                             " to the database")

            target = obj.file_path
            sample_id = sample.id

        elif isinstance(obj, URL):
            target = obj.url
        else:
            target = "none"

        if clock:
            if isinstance(clock, basestring):
                dfmt = "%m-%d-%Y %H:%M:%S"
                try:
                    clock = datetime.datetime.strptime(clock, dfmt)
                except ValueError:
                    log.warning("Datetime %s not in format %s. Using current "
                                "timestamp", clock, dfmt)
                    clock = datetime.datetime.now()

        task = self.db.add(
            target, timeout=timeout, package=package, options=options,
            priority=priority, custom=custom, owner=owner, machine=machine,
            platform=platform, tags=self._get_tags_list(tags), memory=memory,
            enforce_timeout=enforce_timeout, clock=clock, category=category,
            submit_id=submit_id, sample_id=sample_id
        )

        if not task:
            return None

        # Use the returned task to initalize this core task object
        self.set_task(task)
        self.create_empty()


    def add_path(self, file_path, timeout=0, package="", options="",
                 priority=1, custom="", owner="", machine="", platform="",
                 tags=None, memory=False, enforce_timeout=False, clock=None,
                 submit_id=None):

        if not file_path or not os.path.exists(file_path):
            log.warning("File does not exist: %s.", file_path)
            return None

        return self.add(File(file_path), timeout, package, options, priority,
                        custom, owner, machine, platform, tags, memory,
                        enforce_timeout, clock, "file", submit_id)