# Copyright (C) 2016-2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import logging
import os
import threading

from cuckoo.common.config import Config
from cuckoo.common.exceptions import CuckooOperationalError
from cuckoo.common.files import Folders, Files
from cuckoo.common.objects import Dictionary, File, URL
from cuckoo.core.database import Database, TASK_RECOVERED
from cuckoo.core.plugins import RunProcessing, RunSignatures, RunReporting
from cuckoo.misc import cwd

log = logging.getLogger(__name__)

class Task(object):

    files = ["file", "archive"]
    dirs = ["shots", "logs", "files", "extracted", "buffer", "memory"]
    latest_symlink_lock = threading.Lock()

    def __init__(self, db_task=None):
        self.cfg = Config()
        self.db = Database()
        self.db_task = None
        self.copied_binary = None
        self.task_dict = None

        if db_task:
            self.set_task(db_task)

    def set_task(self, db_task):
        """Update Task wrapper with new task db object
        @param db_task: Task Db object"""
        self.db_task = db_task
        self.path = cwd("storage", "analyses", str(db_task.id))
        self.file = db_task.category in Task.files
        self._read_copied_binary()

    def load_task_dict(self, task_dict):
        """Load all dict key values as attributes to the object"""
        # Cast to Cuckoo dictionary, so keys can be accessed as attributes
        self.task_dict = Dictionary(task_dict)
        self.id = task_dict["id"]
        self.category = task_dict.get("category")
        self.target = task_dict.get("target")

        self.path = cwd("storage", "analyses", str(task_dict["id"]))
        self.file = self.category in Task.files
        self._read_copied_binary()

        # Map all remaining values in the dict as attributes
        for key, value in task_dict.iteritems():
                setattr(self, key, value)

    def load_from_id(self, task_id):
        """Load task from id. Returns True of success, False otherwise"""
        db_task = self.db.view_task(task_id)
        if not db_task:
            return False

        self.set_task(db_task)
        return True

    def create_empty(self):
        """Create task directory and copy files to binary folder"""
        log.debug("Creating directories for task #%s", self.id)
        self.create_dirs()
        self.bin_copy_and_symlink()

    def create_dirs(self):
        """Create the folders for this analysis. Returns True if
        all folders were created. False if not"""
        missing = self.dirs_missing()
        if not self.dir_exists():
            missing.append(self.path)
        elif len(missing) < 1:
            return True

        created = 0
        for dir in missing:
            try:
                Folders.create(dir)
                created += 1
            except CuckooOperationalError as e:
                log.error("Unable to create folder \'%s\' for task #%s. "
                          "Error: %s", dir, self.id, e)

        return created == len(missing)

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

        # Update copied binary path attribute
        self._read_copied_binary()

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
        if not self.target:
            return

        if not os.path.isfile(self.target):
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

    def dirs_missing(self):
        """Returns a list of directories that are missing in the task
        directory. logs, shots etc. Full path is returned"""
        missing = []
        for dir in Task.dirs:
            path = os.path.join(self.path, dir)
            if not os.path.exists(path):
                missing.append(path)

        return missing

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
        if self.db_task:
            dict_task = self.db_task.to_dict()
        else:
            dict_task = self.task_dict

        results = RunProcessing(task=dict_task).run()

        if not results:
            return False

        RunSignatures(results=results).run()
        RunReporting(task=dict_task, results=results).run()

        if self.cfg.cuckoo.delete_original:
            self.delete_original_sample()

        if self.cfg.cuckoo.delete_bin_copy:
            self.delete_copied_sample()

        return True

    @staticmethod
    def get_tags_list(tags):
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
            submit_id=None, start_on=None):
        """Create new task
        @param obj: object to add (File or URL).
        @param timeout: selected timeout.
        @param package: the analysis package to use
        @param options: analysis options.
        @param priority: analysis priority.
        @param custom: custom options.
        @param owner: task owner.
        @param machine: selected machine.
        @param platform: platform.
        @param tags: optional tags that must be set for machine selection
        @param memory: toggle full memory dump.
        @param enforce_timeout: toggle full timeout execution.
        @param clock: virtual machine clock time
        @return: task id or None.
        """
        # Convert empty strings and None values to a valid int
        if not timeout:
            timeout = 0
        if not priority:
            priority = 1

        sample_id = None
        if category in self.files and isinstance(obj, File):
            sample_id = self.db.add_sample(obj)
            if not sample_id:
                log.error("Failed to add sample to database")
                return None

            target = obj.file_path

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
            platform=platform, tags=self.get_tags_list(tags), memory=memory,
            enforce_timeout=enforce_timeout, clock=clock, category=category,
            submit_id=submit_id, sample_id=sample_id, start_on=start_on
        )

        if not task:
            log.error("Failed to create new task")
            return None

        # Use the returned task id to initialize this core task object
        self.set_task(self.db.view_task(task))
        self.create_empty()

        return self.id

    def add_path(self, file_path, timeout=0, package="", options="",
                 priority=1, custom="", owner="", machine="", platform="",
                 tags=None, memory=False, enforce_timeout=False, clock=None,
                 submit_id=None, start_on=None):
        """Add a task to database from file path.
        @param file_path: sample path.
        @param timeout: selected timeout.
        @param options: analysis options.
        @param priority: analysis priority.
        @param custom: custom options.
        @param owner: task owner.
        @param machine: selected machine.
        @param platform: platform.
        @param tags: Tags required in machine selection
        @param memory: toggle full memory dump.
        @param enforce_timeout: toggle full timeout execution.
        @param clock: virtual machine clock time
        @return: task id or None
        """
        if not file_path or not os.path.exists(file_path):
            log.error("File does not exist: %s.", file_path)
            return None

        return self.add(File(file_path), timeout, package, options, priority,
                        custom, owner, machine, platform, tags, memory,
                        enforce_timeout, clock, "file", submit_id, start_on)

    def add_archive(self, file_path, filename, package, timeout=0,
                    options=None, priority=1, custom="", owner="", machine="",
                    platform="", tags=None, memory=False,
                    enforce_timeout=False, clock=None, submit_id=None,
                    start_on=None):
        """Add a task to the database that's packaged in an archive file.
        @param file_path: path to archive
        @param filename: name of file in archive
        @param timeout: selected timeout.
        @param options: analysis options.
        @param priority: analysis priority.
        @param custom: custom options.
        @param owner: task owner.
        @param machine: selected machine.
        @param platform: platform.
        @param tags: tags for machine selection
        @param memory: toggle full memory dump.
        @param enforce_timeout: toggle full timeout execution.
        @param clock: virtual machine clock time
        @return: task id or None.
        """
        if not file_path or not os.path.exists(file_path):
            log.error("File does not exist: %s.", file_path)
            return None

        options = options or {}
        options["filename"] = filename

        return self.add(File(file_path), timeout, package, options, priority,
                        custom, owner, machine, platform, tags, memory,
                        enforce_timeout, clock, "archive", submit_id, start_on)

    def add_url(self, url, timeout=0, package="", options="", priority=1,
                custom="", owner="", machine="", platform="", tags=None,
                memory=False, enforce_timeout=False, clock=None,
                submit_id=None, start_on=None):
        """Add a task to database from url.
        @param url: url.
        @param timeout: selected timeout.
        @param package: the analysis package to use
        @param options: analysis options.
        @param priority: analysis priority.
        @param custom: custom options.
        @param owner: task owner.
        @param machine: selected machine.
        @param platform: platform.
        @param tags: tags for machine selection
        @param memory: toggle full memory dump.
        @param enforce_timeout: toggle full timeout execution.
        @param clock: virtual machine clock time
        @return: task id or None.
        """
        return self.add(URL(url), timeout, package, options, priority,
                        custom, owner, machine, platform, tags, memory,
                        enforce_timeout, clock, "url", submit_id, start_on)

    def add_reboot(self, task_id, timeout=0, options="", priority=1,
                   owner="", machine="", platform="", tags=None, memory=False,
                   enforce_timeout=False, clock=None, submit_id=None):
        """Add a reboot task to database from an existing analysis.
        @param task_id: task id of existing analysis.
        @param timeout: selected timeout.
        @param package: the analysis package to use
        @param options: analysis options.
        @param priority: analysis priority.
        @param owner: task owner.
        @param machine: selected machine.
        @param platform: platform.
        @param tags: tags for machine selection
        @param memory: toggle full memory dump.
        @param enforce_timeout: toggle full timeout execution.
        @param clock: virtual machine clock time
        @return: task id or None.
        """

        if not self.load_from_id(task_id) or not os.path.exists(self.target):
            log.error(
                "Unable to add reboot analysis as the original task or its "
                "sample has already been deleted."
            )
            return None

        custom = "%s" % task_id

        return self.add(File(self.target), timeout, "reboot", options,
                        priority, custom, owner, machine, platform, tags,
                        memory, enforce_timeout, clock, "file", submit_id)

    def add_baseline(self, timeout=0, owner="", machine="", memory=False):
        """Add a baseline task to database.
        @param timeout: selected timeout.
        @param owner: task owner.
        @param machine: selected machine.
        @param memory: toggle full memory dump.
        @return: task id or None.
        """
        return self.add(None, timeout=timeout, priority=999, owner=owner,
                        machine=machine, memory=memory, category="baseline")

    def add_service(self, timeout, owner, tags):
        """Add a service task to database.
        @param timeout: selected timeout.
        @param owner: task owner.
        @param tags: task tags.
        @return: task id or None.
        """
        return self.add(None, timeout=timeout, priority=999, owner=owner,
                        tags=tags, category="service")

    def reschedule(self, task_id=None, priority=None):
        """Reschedule this task"""
        if not self.db_task and not task_id:
            log.error("Task is None and no task_id provided."
                      " Cannot reschedule.")
            return None
        elif task_id:
            if not self.load_from_id(task_id):
                log.error("Failed to load task from id: %s", task_id)
                return None

        handlers = {
            "file": self.add_path,
            "url": self.add_url
        }

        add = handlers.get(self.category, None)
        if not add:
            log.error("Rescheduling task category %s not supported",
                      self.category)
            return None

        priority = priority or self.priority

        # Change status to recovered
        self.db.set_status(self.id, TASK_RECOVERED)

        return add(self.target, self.timeout, self.package, self.options, priority,
                   self.custom, self.owner, self.machine, self.platform,
                   self.get_tags_list(self.tags), self.memory,
                   self.enforce_timeout, self.clock)

    @staticmethod
    def requirements_str(db_task):
        """Returns the task machine requirements in a printable string
        @param db_task: Database Task object"""
        requirements = ""

        req_fields = {
            "Platform": db_task.platform,
            "Machine name": db_task.machine,
            "Tags": db_task.tags
        }

        for reqname, value in req_fields.iteritems():
            if value:
                requirements += "%s: " % reqname
                if reqname == "Tags":
                    for tag in db_task.tags:
                        requirements += "%s " % tag.name
                else:
                    requirements += "%s " % value

        return requirements

    def __getattr__(self, item):
        """Map attributes back to the db task object"""
        # Try to retrieve attribute from db_object
        return getattr(self.db_task, item)

    def __getitem__(self, item):
        """Make Task readable as dictionary"""
        attr = getattr(self, item, None)
        if attr is None:
            return self.__getattr__(item)
        else:
            return attr

    def __repr__(self):
        return "<core.Task('{0}','{1}')>".format(self.id, self.target)
