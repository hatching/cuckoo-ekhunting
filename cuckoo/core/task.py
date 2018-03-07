# Copyright (C) 2017-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import io
import json
import logging
import os
import threading
import zipfile

from cuckoo.common.config import config
from cuckoo.common.exceptions import CuckooOperationalError
from cuckoo.common.files import Folders, Files
from cuckoo.common.objects import Dictionary
from cuckoo.common.utils import get_directory_size, json_default, json_encode
from cuckoo.core.database import Database, TASK_RECOVERED, Task as DbTask
from cuckoo.core.plugins import RunProcessing, RunSignatures, RunReporting
from cuckoo.core.target import Target
from cuckoo.misc import cwd

log = logging.getLogger(__name__)
db = Database()

class Task(object):

    dirs = ["shots", "logs", "files", "extracted", "buffer", "memory"]
    latest_symlink_lock = threading.Lock()

    def __init__(self, db_task=None):
        self.db_task = None
        self.task_dict = {}

        if db_task:
            self.set_task(db_task)

    def set_task(self, db_task):
        """Update Task wrapper with new task db object
        @param db_task: Task Db object"""
        self.db_task = db_task
        self.path = cwd(analysis=db_task.id)
        self.task_dict = db_task.to_dict()
        self.task_dict["targets"] = [
            Target(db_target) for db_target in self.db_task.targets
        ]
        # For backwards compatibility, load these two attributes
        # TODO Remove when processing and reporting changes
        if self.task_dict["targets"]:
            self.task_dict["target"] = self.task_dict["targets"][0].target
            self.task_dict["category"] = self.task_dict["targets"][0].category
        else:
            self.task_dict["target"] = "none"
            self.task_dict["category"] = None

    def load_task_dict(self, task_dict):
        """Load all dict key values as attributes to the object.
        Try to change target dictionaries to target objects"""
        # Cast to Cuckoo dictionary, so keys can be accessed as attributes
        newtask = DbTask()
        newtask = newtask.to_dict()
        targets = []
        for dict_target in task_dict.get("targets", []):
            target = Target()
            target.target_dict = dict_target

        task_dict["targets"] = targets
        newtask.update(task_dict)
        self.task_dict = Dictionary(newtask)
        self.path = cwd(analysis=task_dict["id"])

    def load_from_db(self, task_id):
        """Load task from id. Returns True of success, False otherwise"""
        db_task = db.view_task(task_id)
        if not db_task:
            return False

        self.set_task(db_task)
        return True

    def create_empty(self):
        """Create task directory and copy files to binary folder"""
        log.debug("Creating directories for task #%s", self.id)
        self.create_dirs()
        if self.targets:
            self.targets[0].symlink_to_task(self.id)

    def create_dirs(self):
        """Create the folders for this analysis. Returns True if
        all folders were created. False if not"""
        for task_dir in self.dirs:
            create_dir = cwd(task_dir, analysis=self.id)
            try:
                if not os.path.exists(create_dir):
                    Folders.create(create_dir)
            except CuckooOperationalError as e:
                log.error(
                    "Unable to create folder '%s' for task #%s Error: %s",
                    create_dir, self.id, e
                )
                return False

        return True

    def set_latest(self):
        """Create a symlink called 'latest' pointing to this analysis
        in the analysis folder"""
        latest = cwd("storage", "analyses", "latest")
        try:
            self.latest_symlink_lock.acquire()

            if os.path.lexists(latest):
                os.remove(latest)

            Files.symlink(self.path, latest)
        except OSError as e:
            log.error(
                "Error pointing to latest analysis symlink. Error: %s", e
            )
        finally:
            self.latest_symlink_lock.release()

    def delete_binary_symlink(self):
        # If the copied binary was deleted, also delete the symlink to it
        symlink = cwd("binary", analysis=self.id)
        if os.path.islink(symlink):
            try:
                os.remove(symlink)
            except OSError as e:
                log.error(
                    "Failed to delete symlink to removed binary '%s'. Error:"
                    " %s", symlink, e
                )

    def dir_exists(self):
        """Checks if the analysis folder for this task id exists"""
        return os.path.exists(self.path)

    def is_reported(self):
        """Checks if a JSON report exists for this task"""
        return os.path.exists(
            os.path.join(self.path, "reports", "report.json")
        )

    def write_task_json(self, **kwargs):
        """Change task to JSON and write it to disk"""
        path = os.path.join(self.path, "task.json")
        dump = self.db_task.to_dict()

        # For backwards compatibility, add these to task json.
        # TODO: Remove when processing and reporting change
        dump.update({
            "category": self.category,
            "target": self.target
        })

        if kwargs:
            dump.update(kwargs)

        with open(path, "wb") as fw:
            fw.write(json_encode(dump))

    def process(self):
        """Process, run signatures and reports the results for this task"""
        results = RunProcessing(task=self.task_dict).run()
        RunSignatures(results=results).run()
        RunReporting(task=self.task_dict, results=results).run()

        if config("cuckoo:cuckoo:delete_original"):
            for target in self.targets:
                target.delete_original()

        if config("cuckoo:cuckoo:delete_bin_copy"):
            for target in self.targets:
                target.delete_copy()

        return True

    def get_tags_list(self, tags):
        """Check tags and change into usable format"""
        ret = []
        if isinstance(tags, basestring):
            for tag in tags.split(","):
                if tag.strip():
                    ret.append(tag.strip())

        elif isinstance(tags, (tuple, list)):
            for tag in tags:
                if isinstance(tag, basestring) and tag.strip():
                    ret.append(tag.strip())

        return ret

    def add(self, targets=[], timeout=0, package="", options="", priority=1,
            custom="", owner="", machine="", platform="", tags=None,
            memory=False, enforce_timeout=False, clock=None, task_type=None,
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
        @param task_type: The type of task: regular, experiment, other type
        @return: task id or None.
        """
        # Convert empty strings and None values to a valid int
        if not timeout:
            timeout = 0
        if not priority:
            priority = 1

        if isinstance(start_on, basestring):
            try:
                start_on = datetime.datetime.strptime(
                    start_on, "%Y-%m-%d %H:%M"
                )
            except ValueError:
                log.error("'start on' format should be: 'YYYY-M-D H:M'")
                return None

        if clock:
            if isinstance(clock, basestring):
                dfmt = "%m-%d-%Y %H:%M:%S"
                try:
                    clock = datetime.datetime.strptime(clock, dfmt)
                except ValueError:
                    log.warning(
                        "Datetime %s not in format %s. Using current "
                        "timestamp", clock, dfmt
                    )
                    clock = datetime.datetime.now()

        task = db.add(
            targets, timeout=timeout, package=package, options=options,
            priority=priority, custom=custom, owner=owner, machine=machine,
            platform=platform, tags=self.get_tags_list(tags), memory=memory,
            enforce_timeout=enforce_timeout, clock=clock, task_type=task_type,
            submit_id=submit_id,  start_on=start_on
        )

        if not task:
            log.error("Failed to create new task")
            return None

        # Use the returned task id to initialize this core task object
        self.set_task(db.view_task(task))
        self.create_empty()

        return self.id

    def add_path(self, file_path, timeout=0, package="", options="",
                 priority=1, custom="", owner="", machine="", platform="",
                 tags=None, memory=False, enforce_timeout=False, clock=None,
                 submit_id=None, start_on=None, task_type="regular"):
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
        @param task_type: The type of task: regular, experiment, other type
        @return: task id or None
        """
        if not file_path:
            log.error("No file path given to analyze, cannot create task")
            return None

        target = Target()
        if not target.create_file(file_path):
            log.error("New task creation failed, could not create target")
            return None

        return self.add(
            targets=[target.db_target], timeout=timeout, package=package,
            options=options, priority=priority, custom=custom, owner=owner,
            machine=machine, platform=platform, tags=tags, memory=memory,
            enforce_timeout=enforce_timeout, clock=clock, task_type=task_type,
            submit_id=submit_id, start_on=start_on
        )

    def add_archive(self, file_path, filename, package, timeout=0,
                    options=None, priority=1, custom="", owner="", machine="",
                    platform="", tags=None, memory=False,
                    enforce_timeout=False, clock=None, submit_id=None,
                    start_on=None, task_type="regular"):
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
        if not file_path:
            log.error("No file path given to analyze, cannot create task")
            return None

        options = options or {}
        options["filename"] = filename

        target = Target()
        if not target.create_archive(file_path):
            log.error("New task creation failed, could not create target")
            return None

        return self.add(
            targets=[target.db_target], timeout=timeout, package=package,
            options=options, priority=priority, custom=custom, owner=owner,
            machine=machine, platform=platform, tags=tags, memory=memory,
            enforce_timeout=enforce_timeout, clock=clock, task_type=task_type,
            submit_id=submit_id, start_on=start_on
        )

    def add_url(self, url, timeout=0, package="", options="", priority=1,
                custom="", owner="", machine="", platform="", tags=None,
                memory=False, enforce_timeout=False, clock=None,
                submit_id=None, start_on=None, task_type="regular"):
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
        if not url:
            log.error("No URL given, cannot create task")
            return None

        target = Target()
        if not target.create_url(url):
            log.error("New task creation failed, could not create target")

        return self.add(
            targets=[target.db_target], timeout=timeout, package=package,
            options=options, priority=priority, custom=custom, owner=owner,
            machine=machine, platform=platform, tags=tags, memory=memory,
            enforce_timeout=enforce_timeout, clock=clock, task_type=task_type,
            submit_id=submit_id, start_on=start_on
        )

    def add_reboot(self, task_id, timeout=0, options="", priority=1,
                   owner="", machine="", platform="", tags=None, memory=False,
                   enforce_timeout=False, clock=None, submit_id=None,
                   task_type="regular"):
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

        if not self.load_from_db(task_id):
            log.error(
                "Unable to add reboot analysis as the original task or its "
                "sample has already been deleted."
            )
            return None

        custom = "%s" % task_id

        if not self.targets:
            log.error(
                "No target to reboot available to reboot task #%s", self.id
            )
            return None

        target = self.targets[0]
        if target.is_file and not target.copy_exists():
            log.error(
                "Target file no longer exists, cannot reboot task #%s", self.id
            )
            return None

        return self.add(
            targets=[target.db_target], timeout=timeout, package="reboot",
            options=options, priority=priority, custom=custom, owner=owner,
            machine=machine, platform=platform, tags=tags, memory=memory,
            enforce_timeout=enforce_timeout, clock=clock, task_type=task_type,
            submit_id=submit_id
        )

    def add_baseline(self, timeout=0, owner="", machine="", memory=False):
        """Add a baseline task to database.
        @param timeout: selected timeout.
        @param owner: task owner.
        @param machine: selected machine.
        @param memory: toggle full memory dump.
        @return: task id or None.
        """
        return self.add(
            timeout=timeout, priority=999, owner=owner, machine=machine,
            memory=memory, task_type="baseline"
        )

    def add_service(self, timeout, owner, tags):
        """Add a service task to database.
        @param timeout: selected timeout.
        @param owner: task owner.
        @param tags: task tags.
        @return: task id or None.
        """
        return self.add(
            timeout=timeout, priority=999, owner=owner, tags=tags,
            task_type="service"
        )

    def reschedule(self, task_id=None, priority=None):
        """Reschedule this task or the given task
        @param task_id: task_id to reschedule
        @param priority: overwrites the priority the task already has"""
        if not self.db_task and not task_id:
            log.error(
                "Task is None and no task_id provided, cannot reschedule"
            )
            return None
        elif task_id:
            if not self.load_from_db(task_id):
                log.error("Failed to load task from id: %s", task_id)
                return None

        priority = priority or self.priority

        # Change status to recovered
        db.set_status(self.id, TASK_RECOVERED)

        return self.add(
            targets=[target.db_target for target in self.targets],
            timeout=self.timeout, package=self.package,
            options=self.options, priority=priority, custom=self.custom,
            owner=self.owner, machine=self.machine, platform=self.platform,
            tags=self.tags, memory=self.memory,
            enforce_timeout=self.enforce_timeout, clock=self.clock,
            task_type=self.type,
        )

    @staticmethod
    def requirements_str(db_task):
        """Returns the task machine requirements in a printable string
        @param db_task: Database Task object"""
        requirements = ""

        req_fields = {
            "platform": db_task.platform,
            "machine": db_task.machine,
            "tags": db_task.tags
        }

        for reqname, value in req_fields.iteritems():
            if value:
                requirements += "%s=" % reqname
                if reqname == "tags":
                    for tag in db_task.tags:
                        requirements += "%s," % tag.name
                else:
                    requirements += "%s" % value
                requirements += " "

        return requirements

    @staticmethod
    def estimate_export_size(task_id, taken_dirs, taken_files):
        """Estimate the size of the export zip if given dirs and files
        are included"""
        path = cwd(analysis=task_id)
        if not os.path.exists(path):
            log.error("Path %s does not exist", path)
            return 0

        size_total = 0

        for directory in taken_dirs:
            destination = "%s/%s" % (path, os.path.basename(directory))
            if os.path.isdir(destination):
                size_total += get_directory_size(destination)

        for filename in taken_files:
            destination = "%s/%s" % (path, os.path.basename(filename))
            if os.path.isfile(destination):
                size_total += os.path.getsize(destination)

        # estimate file size after zipping; 60% compression rate typically
        size_estimated = size_total / 6.5

        return size_estimated

    @staticmethod
    def get_files(task_id):
        """Locate all directories/results available for this task
        returns a tuple of all dirs and files"""
        analysis_path = cwd(analysis=task_id)
        if not os.path.exists(analysis_path):
            log.error("Path %s does not exist", analysis_path)
            return [], []

        dirs, files = [], []
        for filename in os.listdir(analysis_path):
            path = os.path.join(analysis_path, filename)
            if os.path.isdir(path):
                dirs.append((filename, len(os.listdir(path))))
            else:
                files.append(filename)

        return dirs, files

    @staticmethod
    def create_zip(task_id, taken_dirs, taken_files, export=True):
        """Returns a zip file as a file like object.
        @param task_id: task id of an existing task
        @param taken_dirs: list of directories (limiting to extension possible
        if a dir is given in a tuple with a list of extensions
        ['dir1', ('dir2', ['.bson'])]
        @param taken_files: files from root dir to include
        @param export: Is this a full task export
        (should extra info be included?)"""

        if not taken_dirs and not taken_files:
            log.warning("No directories or files to zip were provided")
            return None

        # Test if the task_id is an actual integer, to prevent it being
        # a path.
        try:
            int(task_id)
        except ValueError:
            log.error("Task id was not integer! Actual value: %s", task_id)
            return None

        task_path = cwd(analysis=task_id)
        if not os.path.exists(task_path):
            log.error("Path %s does not exist", task_path)
            return None

        # Fill dictionary with extensions per directory to include.
        # If no extensions exist for a directory, it will include all when
        # making the zip
        include_exts = {}

        taken_dirs_tmp = []
        for taken_dir in taken_dirs:

            # If it is a tuple, it contains extensions to include
            if isinstance(taken_dir, tuple):
                taken_dirs_tmp.append(taken_dir[0])
                if taken_dir[0] not in include_exts:
                    include_exts[taken_dir[0]] = []

                if isinstance(taken_dir[1], list):
                    include_exts[taken_dir[0]].extend(taken_dir[1])
                else:
                    include_exts[taken_dir[0]].append(taken_dir[1])
            else:
                taken_dirs_tmp.append(taken_dir)

        taken_dirs = taken_dirs_tmp
        f = io.BytesIO()
        z = zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED, allowZip64=True)

        # If exporting a complete analysis, create an analysis.json file with
        # additional information about this analysis. This information serves
        # as metadata when importing a task.
        if export:
            report_path = cwd("reports", "report.json", analysis=task_id)

            if not os.path.isfile(report_path):
                log.warning(
                    "Cannot export task %s, report.json does not exist",
                    task_id
                )
                z.close()
                return None

            report = json.loads(open(report_path, "rb").read())
            obj = {
                "action": report.get("debug", {}).get("action", []),
                "errors": report.get("debug", {}).get("errors", []),
            }
            z.writestr(
                "analysis.json", json.dumps(
                    obj, indent=4, default=json_default
                )
            )

        for dirpath, dirnames, filenames in os.walk(task_path):
            if dirpath == task_path:
                for filename in filenames:
                    if filename in taken_files:
                        z.write(os.path.join(dirpath, filename), filename)

            basedir = os.path.basename(dirpath)
            if basedir in taken_dirs:

                for filename in filenames:

                    # Check if this directory has a set of extensions that
                    # should only be included
                    include = True
                    if basedir in include_exts and include_exts[basedir]:
                        include = False
                        for ext in include_exts[basedir]:
                            if filename.endswith(ext):
                                include = True
                                break

                    if not include:
                        continue

                    z.write(
                        os.path.join(dirpath, filename),
                        os.path.join(os.path.basename(dirpath), filename)
                    )

        z.close()
        f.seek(0)

        return f

    def refresh(self):
        """Reload the task object from the database to have the latest
        changes"""
        db_task = db.view_task(self.db_task.id)
        self.set_task(db_task)

    def set_status(self, status):
        """Set the task to given status in the database and update the
        dbtask object to have the new status"""
        db.set_status(self.db_task.id, status)
        self.refresh()

    def __getitem__(self, item):
        """Make Task.db_task readable as dictionary"""
        return self.task_dict[item]

    def __setitem__(self, key, value):
        """Make value assignment to Task.db_task possible"""
        self.task_dict[key] = value

    @property
    def id(self):
        return self.task_dict.get("id")

    @property
    def type(self):
        return self.task_dict.get("type")

    @property
    def target(self):
        return self.task_dict.get("target")

    @property
    def category(self):
        return self.task_dict.get("category")

    @property
    def targets(self):
        return self.task_dict.get("targets")

    @property
    def timeout(self):
        return self.task_dict.get("timeout")

    @property
    def priority(self):
        return self.task_dict.get("priority")

    @property
    def custom(self):
        return self.task_dict.get("custom")

    @property
    def owner(self):
        return self.task_dict.get("owner")

    @property
    def machine(self):
        return self.task_dict.get("machine")

    @property
    def package(self):
        return self.task_dict.get("package")

    @property
    def tags(self):
        return self.task_dict.get("tags")

    @property
    def options(self):
        return self.task_dict.get("options")

    @property
    def platform(self):
        return self.task_dict.get("platform")

    @property
    def memory(self):
        return self.task_dict.get("memory")

    @property
    def enforce_timeout(self):
        return self.task_dict.get("enforce_timeout")

    @property
    def clock(self):
        return self.task_dict.get("clock")

    @property
    def added_on(self):
        return self.task_dict.get("added_on")

    @property
    def start_on(self):
        return self.task_dict.get("start_on")

    @property
    def started_on(self):
        return self.task_dict.get("started_on")

    @property
    def completed_on(self):
        return self.task_dict.get("completed_on")

    @property
    def status(self):
        return self.task_dict.get("status")

    @property
    def sample_id(self):
        return self.task_dict.get("sample_id")

    @property
    def submit_id(self):
        return self.task_dict.get("submit_id")

    @property
    def processing(self):
        return self.task_dict.get("processing")

    @property
    def route(self):
        return self.task_dict.get("route")
