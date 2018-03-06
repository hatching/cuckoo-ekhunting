# Copyright (C) 2017-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import io
import json
import mock
import os
import pytest
import shutil
import tempfile
import zipfile

from cuckoo.common.objects import File
from cuckoo.core.database import Database, Task as DbTask, Target as DbTarget
from cuckoo.core.task import Task
from cuckoo.core.target import Target
from cuckoo.main import cuckoo_create
from cuckoo.misc import set_cwd, cwd

submit_task = Task()

class TestTask(object):
    def setup(self):
        self.cwd = tempfile.mkdtemp()
        set_cwd(self.cwd)
        cuckoo_create()
        self.db = Database()
        self.db.connect()
        self.tmpfile = None
        self.files = []

    def teardown(self):
        shutil.rmtree(self.cwd)
        for path in self.files:
            try:
                os.remove(path)
            except OSError:
                pass

    def get_file(self):
        fd, target = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        self.files.append(target)
        return target

    def add_task(self, category="file", url=None, **kwargs):
        target = Target()
        if category == "file":
            target.create_file(self.get_file())
        elif category == "url":
            target.create_url(url)

        kwargs["targets"] = [target.db_target]

        return [self.db.add(**kwargs), target.target]

    def test_defined_task_dirs(self):
        assert Task.dirs == [
            "shots", "logs", "files", "extracted", "buffer", "memory"
        ]

    def test_load_from_db(self):
        id = self.add_task()[0]
        task = Task()
        assert task.load_from_db(id)

        assert task.id == id
        assert task.category == "file"
        assert task.path == cwd(analysis=id)

    def test_set_task_constructor(self):
        id = self.add_task()[0]
        db_task = self.db.view_task(id)
        task = Task(db_task)

        assert task.id == id
        assert task.category == "file"
        assert task.path == cwd(analysis=id)
        assert task.db_task == db_task

    def test_set_task(self):
        id, sample = self.add_task()
        db_task = self.db.view_task(id)
        task = Task()
        task.set_task(db_task)

        assert task.id == id
        assert task.category == "file"
        assert task.path == cwd(analysis=id)
        assert task.db_task == db_task
        assert task.target == sample
        assert len(task.targets) == 1
        assert isinstance(task.targets[0], Target)

    def test_load_task_from_dict(self):
        task_dict = {
            "id": 42,
            "category": "file",
            "target": "/tmp/stuff/doge42.exe",
        }

        task = Task()
        task.load_task_dict(task_dict)

        assert task.id == 42
        assert task.category == "file"
        assert task.target == "/tmp/stuff/doge42.exe"
        assert task.path == cwd(analysis=42)

    def test_create_dirs(self):
        id, sample = self.add_task()
        print id
        task = Task()
        task.load_from_db(id)

        dirs = ["shots", "logs", "files", "extracted", "buffer", "memory"]
        task_path = cwd(analysis=id)

        dir_paths = [cwd(task_path, dir) for dir in dirs]

        for path in dir_paths:
            assert not os.path.exists(path)

        assert task.create_dirs()
        assert os.path.exists(task_path)
        for path in dir_paths:
            assert os.path.exists(path)

    def test_dir_exists(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)

        assert not task.dir_exists()
        os.mkdir(cwd(analysis=id))
        assert task.dir_exists()

    def test_is_reported(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)
        task.create_dirs()

        assert not task.is_reported()
        reports = os.path.join(task.path, "reports")
        os.mkdir(reports)
        with open(os.path.join(reports, "report.json"),
                  "wb") as fw:
            fw.write(os.urandom(64))
        assert task.is_reported()

    @mock.patch("cuckoo.core.task.RunReporting.run")
    @mock.patch("cuckoo.core.task.RunSignatures.run")
    @mock.patch("cuckoo.core.task.RunProcessing.run")
    def test_process(self, mp, ms, mr):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)

        mp.return_value = {"x":"x"}

        task.process()
        mp.assert_called_once()
        ms.assert_called_once()
        mr.assert_called_once()

    @mock.patch("cuckoo.core.task.RunReporting")
    @mock.patch("cuckoo.core.task.RunSignatures")
    @mock.patch("cuckoo.core.task.RunProcessing")
    def test_process_nodelete(self, mp, ms, mr):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create(cfg={
            "cuckoo": {
                "cuckoo": {
                    "delete_original": False,
                    "delete_bin_copy": False,
                },
            },
        })

        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)
        task.create_dirs()
        copied_binary = cwd("storage", "binaries", File(sample).get_sha256())

        task.process()
        assert os.path.exists(copied_binary)
        assert os.path.exists(sample)

    @mock.patch("cuckoo.core.task.RunReporting")
    @mock.patch("cuckoo.core.task.RunSignatures")
    @mock.patch("cuckoo.core.task.RunProcessing")
    def test_process_dodelete(self, mp, ms, mr):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create(cfg={
            "cuckoo": {
                "cuckoo": {
                    "delete_original": True,
                    "delete_bin_copy": True,
                },
            },
        })

        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)
        task.create_dirs()

        assert os.path.exists(task.target)
        assert os.path.exists(task.targets[0].copied_binary)
        task.process()
        assert not os.path.exists(sample)
        assert not os.path.exists(task.targets[0].copied_binary)

    def test_get_tags_list(self):
        task = Task()
        tags = " doge,stuff,things"
        tags2 = ("doge", "things ")
        tags3 = "foo,,bar"
        tags4 = ["tag1", 1, "", "tag2"]

        assert task.get_tags_list(tags) == ["doge", "stuff", "things"]
        assert task.get_tags_list(tags2) == ["doge", "things"]
        assert task.get_tags_list(tags3) == ["foo", "bar"]
        assert task.get_tags_list(tags4) == ["tag1", "tag2"]
        assert task.get_tags_list("") == []
        assert task.get_tags_list([]) == []
        assert task.get_tags_list(()) == []
        assert task.get_tags_list(1) == []

    def test_set_latest(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)
        task.create_dirs()

        sym_latest = cwd("storage", "analyses", "latest")
        task.set_latest()

        assert os.path.realpath(sym_latest) == task.path

    def test_set_status(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)
        task.set_status("reported")

        assert task.status == "reported"
        assert task["status"] == "reported"

    def test_refresh(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)
        self.db.set_machine(id, "machine1")

        assert task.machine == ""
        assert task["machine"] == ""
        task.refresh()
        assert task.machine == "machine1"
        assert task["machine"] == "machine1"

    def test_write_task_json(self):
        session = self.db.Session()
        target = Target()
        tid = target.create_file("tests/files/pdf0.pdf")
        db_target = session.query(DbTarget).filter_by(id=tid).first()
        db_target.target = "/tmp/doge.exe"
        session.commit()
        session.refresh(db_target)
        id, sample = self.add_task()
        db_task = session.query(DbTask).filter_by(id=id).first()
        db_task.status = "reported"
        db_task.machine = "DogeOS1"
        db_task.targets = [db_target]
        db_task.start_on = datetime.datetime(2017, 5, 10, 18, 0)
        db_task.added_on = datetime.datetime(2017, 5, 10, 18, 0)
        db_task.clock = datetime.datetime(2017, 5, 10, 18, 0)
        session.commit()
        session.refresh(db_task)

        task = Task()
        task.load_from_db(id)
        task.create_dirs()
        task.write_task_json()

        correct = open("tests/files/task_dump.json", "rb")
        correct_json = json.load(correct)
        generated = open(os.path.join(task.path, "task.json"), "rb")
        generated_json = json.load(generated)

        assert generated_json == correct_json

    def test_get_item(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)

        assert task["id"] == id
        assert task["category"] == "file"
        assert task["target"] == sample
        assert task["machine"] == ""

    def test_get_attribute(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)
        path = cwd(analysis=id)

        assert task.id == id
        assert task.path == path
        assert task.category == "file"
        assert task.target == sample

    def test_requirement_str(self):
        id, sample = self.add_task(
            tags=["doge"], platform="DogeOS", machine="Doge1"
        )
        task = Task()
        task.load_from_db(id)

        req_str = task.requirements_str(task.db_task)
        assert req_str == "machine=Doge1 platform=DogeOS tags=doge, "

    def test_reschedule_file(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)

        newid = task.reschedule(priority=3)

        oldtask = self.db.view_task(id)
        newtask = self.db.view_task(newid)
        assert newid is not None
        assert oldtask.status == "recovered"
        assert newtask.targets[0].category == "file"
        assert newtask.targets[0].target == sample
        assert newtask.priority == 3

    def test_reschedule_url(self):
        id, sample = self.add_task(
            url="http://example.com/42", category="url"
        )
        task = Task()
        task.load_from_db(id)

        newid = task.reschedule(priority=2)

        oldtask = self.db.view_task(id)
        newtask = self.db.view_task(newid)
        assert newid is not None
        assert oldtask.status == "recovered"
        assert newtask.targets[0].category == "url"
        assert newtask.priority == 2
        assert newtask.targets[0].target == "http://example.com/42"

    def test_reschedule_id(self):
        id, sample = self.add_task()
        task = Task()
        newid = task.reschedule(task_id=id)

        oldtask = self.db.view_task(id)
        newtask = self.db.view_task(newid)
        assert newid is not None
        assert oldtask.status == "recovered"
        assert newtask.targets[0].category == "file"

    def test_reschedule_fail(self):
        newid = submit_task.reschedule()
        assert newid is None

    def test_reschedule_nonexistant(self):
        newid = submit_task.reschedule(task_id=42)
        assert newid is None

    def test_add_service(self):
        task = Task()
        id = task.add_service(timeout=60, tags=["officepc"], owner="Doge")
        task_path = cwd(analysis=id)
        db_task = self.db.view_task(id)

        assert id is not None
        assert os.path.exists(task_path)
        assert db_task.type == "service"
        assert db_task.owner == "Doge"
        assert db_task.timeout == 60
        assert db_task.priority == 999
        assert db_task.tags[0].name == "officepc"
        assert db_task.targets == []

    def test_add_baseline(self):
        task = Task()
        id = task.add_baseline(timeout=60, owner="Doge", machine="machine1")
        task_path = cwd(analysis=id)
        db_task = self.db.view_task(id)

        assert id is not None
        assert os.path.exists(task_path)
        assert db_task.type == "baseline"
        assert db_task.owner == "Doge"
        assert db_task.timeout == 60
        assert db_task.priority == 999
        assert db_task.machine == "machine1"
        assert db_task.memory == False
        assert db_task.targets == []

    def test_add_reboot(self):
        id, sample = self.add_task(owner="MrDoge")
        sid = self.db.add_submit(None, None, None)
        task = Task()
        task.load_from_db(id)
        task.create_empty()
        newid = task.add_reboot(id, owner="Doge", submit_id=sid)
        task_path = cwd(analysis=newid)
        db_task = self.db.view_task(newid)

        assert newid is not None
        assert os.path.exists(task_path)
        assert db_task.targets[0].category == "file"
        assert db_task.package == "reboot"
        assert db_task.owner == "Doge"
        assert db_task.priority == 1
        assert db_task.custom == "%s" % id
        assert db_task.memory == False
        assert db_task.targets[0].target == sample
        assert db_task.submit_id == sid
        assert len(task.targets) == 1
        assert isinstance(task.targets[0], Target)

    def test_add_reboot_nonexistant(self):
        newid = submit_task.add_reboot(42)
        assert newid is None

    def test_add_reboot_binary_removed(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)
        task.create_empty()
        os.remove(task.targets[0].copied_binary)
        newid = task.add_reboot(id)
        assert newid is None

    def test_add_url(self):
        id = submit_task.add_url("http://example.com/42")
        db_task = self.db.view_task(id)
        task_path = cwd(analysis=id)

        assert id is not None
        assert os.path.exists(task_path)
        assert db_task.targets[0].category == "url"
        assert db_task.targets[0].target == "http://example.com/42"
        assert submit_task.targets[0].target == "http://example.com/42"
        assert len(submit_task.targets) == 1
        assert isinstance(submit_task.targets[0], Target)

    def test_add_archive(self):
        fakezip = self.get_file()
        id = submit_task.add_archive(fakezip, "file1.exe", "exe")
        task_path = cwd(analysis=id)
        db_task = self.db.view_task(id)

        assert id is not None
        assert os.path.exists(task_path)
        assert db_task.targets[0].category == "archive"
        assert db_task.options == {"filename": "file1.exe"}
        assert db_task.targets[0].target == fakezip
        assert db_task.package == "exe"
        assert submit_task.targets[0].target == fakezip
        assert len(submit_task.targets) == 1
        assert isinstance(submit_task.targets[0], Target)

    def test_add_archive_nonexistant(self):
        id = submit_task.add_archive("/tmp/BfUbuYByg.zip", "file1.exe", "exe")
        assert id is None

    def test_add_path(self):
        sample = self.get_file()
        id = submit_task.add_path(sample)
        task_path = cwd(analysis=id)
        db_task = self.db.view_task(id)

        assert id is not None
        assert os.path.exists(task_path)
        assert db_task.targets[0].category == "file"
        assert db_task.targets[0].target == sample
        assert submit_task.targets[0].target == sample
        assert len(submit_task.targets) == 1
        assert isinstance(submit_task.targets[0], Target)

    def test_add_path_nonexistant(self):
        id = submit_task.add_path("/tmp/YtcukGBYTTBYU.exe")
        assert id is None

    def test_add_path_invalid_starton(self):
        tmpfile = self.get_file()
        id = submit_task.add_path(tmpfile, start_on="13-11-2013")
        assert id is None

    def test_add_file(self):
        task = Task()
        sample = self.get_file()
        target = Target()
        target.create_file(sample)
        starton = datetime.datetime.now()
        id = task.add(
            [target.db_target], clock="5-17-2017 13:37:13",
            package="exe", owner="Doge", custom="stuff", machine="machine1",
            platform="DogeOS", tags="tag1", memory=True, enforce_timeout=True,
            submit_id=1500, start_on=starton
        )
        task_path = cwd(analysis=id)
        db_task = self.db.view_task(id)

        assert id is not None
        assert os.path.exists(task_path)
        assert db_task.targets[0].category == "file"
        assert db_task.targets[0].target == sample
        assert db_task.clock == datetime.datetime(
            year=2017, month=5, day=17, hour=13,minute=37,second=13
        )
        assert db_task.timeout == 0
        assert db_task.package == "exe"
        assert db_task.options == {}
        assert db_task.priority == 1
        assert db_task.custom == "stuff"
        assert db_task.owner == "Doge"
        assert db_task.machine == "machine1"
        assert db_task.platform == "DogeOS"
        assert len(db_task.tags) == 1
        assert db_task.tags[0].name == "tag1"
        assert db_task.memory
        assert db_task.enforce_timeout
        assert db_task.submit_id == 1500
        assert db_task.start_on == starton
        assert task.id == id
        assert task.target == sample
        assert task.category == "file"
        assert task.type == "regular"

    def test_add_url(self):
        task = Task()
        target = Target()
        target.create_url("http://example.com/42")
        id = task.add([target.db_target])
        task_path = cwd(analysis=id)
        db_task = self.db.view_task(id)

        assert id is not None
        assert os.path.exists(task_path)
        assert db_task.targets[0].category == "url"
        assert db_task.targets[0].target == "http://example.com/42"
        assert db_task.clock is not None
        assert task.id == id
        assert task.target == "http://example.com/42"
        assert task.category == "url"

    def test_estimate_export_size(self):
        fake_task = cwd(analysis=1)
        shutil.copytree("tests/files/sample_analysis_storage", fake_task)

        est_size = Task.estimate_export_size(1, ["logs"], ["dump.pcap"])
        assert int(est_size) == 7861

    def test_get_files(self):
        fake_task = cwd(analysis=1)
        shutil.copytree("tests/files/sample_analysis_storage", fake_task)
        dirs, files = Task.get_files(1)

        assert len(dirs) == 6
        assert len(files) == 10
        assert "dump.pcap" in files
        assert ("logs", 1) in dirs

    def test_create_zip(self):
        fake_task = cwd(analysis=1)
        shutil.copytree("tests/files/sample_analysis_storage", fake_task)
        zfileio = Task.create_zip(
            1, ["logs", "report"], ["cuckoo.log", "files.json"]
        )

        assert isinstance(zfileio, io.BytesIO)

        zfile = zipfile.ZipFile(zfileio)
        assert len(zfile.read("files.json")) == 1856
        assert len(zfileio.getvalue()) == 13938

    def test_all_properties(self):
        id, sample = self.add_task()
        task = Task()
        task.load_from_db(id)
        task_properties = [
            "id", "target", "category", "timeout", "priority", "custom",
            "owner", "machine", "package", "tags", "options", "platform",
            "memory", "enforce_timeout", "clock", "added_on", "start_on",
            "started_on", "completed_on", "status", "sample_id", "submit_id",
            "processing", "route", "targets"
        ]

        try:
            for field in task_properties:
                getattr(task, field)
        except Exception as e:
            pytest.fail(
                "One or more properties of Task raised an error: %s" % e
            )
