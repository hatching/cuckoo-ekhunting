# Copyright (C) 2016-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import mock
import os
import pytest
import tempfile

from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy import MetaData

from cuckoo.common.files import Files
from cuckoo.common.objects import File, URL
from cuckoo.core.database import (
    Database, Task, Tag, AlembicVersion, SCHEMA_VERSION
)
from cuckoo.common.exceptions import CuckooOperationalError
from cuckoo.core.startup import init_yara
from cuckoo.distributed.app import create_app
from cuckoo.main import main, cuckoo_create
from cuckoo.misc import set_cwd, cwd, mkdir

class DatabaseEngine(object):
    """Tests database stuff."""
    URI = None

    def setup_class(self):
        set_cwd(tempfile.mkdtemp())

    def setup(self):
        self.d = Database()
        self.d.connect(dsn=self.URI)

    def teardown(self):
        # Clear all tables without dropping them
        # This is done after each test to ensure a test doesn't fail because
        # of data of a previous test
        meta = MetaData()
        meta.reflect(self.d.engine)
        ses = self.d.Session()
        try:
            for t in reversed(meta.sorted_tables):
                ses.execute(t.delete())
            ses.commit()
        finally:
            ses.close()

    def add_url(self, url, priority=1, status="pending"):
        url = URL(url)
        target_id = self.d.add_target(
            url.url, "url", url.get_crc32(), url.get_md5(),
            url.get_sha1(), url.get_sha256(), url.get_sha512()
        )
        db_target = self.d.find_target(id=target_id)
        task_id = self.d.add(targets=[db_target], priority=priority)
        self.d.set_status(task_id, status)
        return task_id

    def add_file(self, file_path, priority=1, status="pending"):
        fileobj = File(file_path)
        target_id = self.d.add_target(
            file_path, "file", fileobj.get_crc32(), fileobj.get_md5(),
            fileobj.get_sha1(), fileobj.get_sha256(), fileobj.get_sha512(),
            file_type=fileobj.get_type(), file_size=fileobj.get_size()
        )
        db_target = self.d.find_target(id=target_id)
        task_id = self.d.add(targets=[db_target], priority=priority)
        self.d.set_status(task_id, status)
        return task_id

    def add_test_target(self, fileobj=None, path=None, return_id=False,
                        url=None):
        if not fileobj and path:
            fileobj = File(path)
        elif url:
            url = URL(url)

        if fileobj:
            id = self.d.add_target(
                fileobj.file_path, "file", fileobj.get_crc32(), fileobj.get_md5(),
                fileobj.get_sha1(), fileobj.get_sha256(), fileobj.get_sha512(),
                file_type=fileobj.get_type(), file_size=fileobj.get_size()
            )
        elif url:
            id = self.d.add_target(
                url.url, "url", url.get_crc32(), url.get_md5(),
                url.get_sha1(), url.get_sha256(), url.get_sha512()
            )
        if return_id:
            return id
        else:
            return self.d.find_target(id=id)

    def test_add_task(self):
        fd, sample_path = tempfile.mkstemp()
        os.write(fd, "hehe")
        os.close(fd)

        # Add task.
        count = self.d.Session().query(Task).count()
        self.add_file(sample_path)
        assert self.d.Session().query(Task).count() == count + 1

    def test_processing_get_task(self):
        # First reset all existing rows so that earlier exceptions don't affect
        # this unit test run.
        null, session = None, self.d.Session()

        session.query(Task).filter(
            Task.status == "completed", Task.processing == null
        ).update({
            "processing": "something",
        })
        session.commit()

        t1 = self.add_url("http://google.com/1", priority=1, status="completed")
        t2 = self.add_url("http://google.com/2", priority=2, status="completed")
        t3 = self.add_url("http://google.com/3", priority=1, status="completed")
        t4 = self.add_url("http://google.com/4", priority=1, status="completed")
        t5 = self.add_url("http://google.com/5", priority=3, status="completed")
        t6 = self.add_url("http://google.com/6", priority=1, status="completed")
        t7 = self.add_url("http://google.com/7", priority=1, status="completed")

        assert self.d.processing_get_task("foo") == t5
        assert self.d.processing_get_task("foo") == t2
        assert self.d.processing_get_task("foo") == t1
        assert self.d.processing_get_task("foo") == t3
        assert self.d.processing_get_task("foo") == t4
        assert self.d.processing_get_task("foo") == t6
        assert self.d.processing_get_task("foo") == t7
        assert self.d.processing_get_task("foo") is None

    def test_error_exists(self):
        task_id = self.add_url("http://google.com/")
        self.d.add_error("A"*1024, task_id)
        assert len(self.d.view_errors(task_id)) == 1
        self.d.add_error("A"*1024, task_id)
        assert len(self.d.view_errors(task_id)) == 2

    def test_long_error(self):
        self.add_url("http://google.com/")
        self.d.add_error("A"*1024, 1)
        err = self.d.view_errors(1)
        assert err and len(err[0].message) == 1024

    def test_submit(self):
        dirpath = tempfile.mkdtemp()
        submit_id = self.d.add_submit(dirpath, "files", {
            "foo": "bar",
        })
        submit = self.d.view_submit(submit_id)
        assert submit.id == submit_id
        assert submit.tmp_path == dirpath
        assert submit.submit_type == "files"
        assert submit.data == {
            "foo": "bar",
        }

    def test_connect_no_create(self):
        AlembicVersion.__table__.drop(self.d.engine)
        self.d.connect(dsn=self.URI, create=False)
        assert "alembic_version" not in self.d.engine.table_names()
        self.d.connect(dsn=self.URI)
        assert "alembic_version" in self.d.engine.table_names()

    def test_view_submit_tasks(self):
        submit_id = self.d.add_submit(None, None, None)
        target_id = self.add_test_target(path=__file__, return_id=True)
        db_target = self.d.find_target(id=target_id)
        t1 = self.d.add([db_target], custom="1", submit_id=submit_id)
        t2 = self.d.add([db_target], custom="2", submit_id=submit_id)

        submit = self.d.view_submit(submit_id)
        assert submit.id == submit_id
        with pytest.raises(DetachedInstanceError):
            print submit.tasks

        submit = self.d.view_submit(submit_id, tasks=True)
        assert len(submit.tasks) == 2
        tasks = sorted((task.id, task) for task in submit.tasks)
        assert tasks[0][1].id == t1
        assert tasks[0][1].custom == "1"
        assert tasks[1][1].id == t2
        assert tasks[1][1].custom == "2"

    def test_task_set_options(self):
        db_target = self.add_test_target(path=__file__)
        t0 = self.d.add([db_target], options={"foo": "bar"})
        t1 = self.d.add([db_target], options="foo=bar")

        assert self.d.view_task(t0).options == {"foo": "bar"}
        assert self.d.view_task(t1).options == {"foo": "bar"}

    def test_error_action(self):
        task_id = self.d.add([self.add_test_target(path=__file__)])
        self.d.add_error("message1", task_id)
        self.d.add_error("message2", task_id, "actionhere")
        e1, e2 = self.d.view_errors(task_id)
        assert e1.message == "message1"
        assert e1.action is None
        assert e2.message == "message2"
        assert e2.action == "actionhere"

    def test_view_tasks(self):
        t1 = self.d.add([self.add_test_target(path=__file__)])
        t2 = self.d.add([self.add_test_target(url="http://example.com")])
        tasks = self.d.view_tasks([t1, t2])
        assert tasks[0].to_dict() == self.d.view_task(t1).to_dict()
        assert tasks[1].to_dict() == self.d.view_task(t2).to_dict()

    def test_add_machine(self):
        self.d.add_machine(
            "name1", "label", "1.2.3.4", "windows", None,
            "tag1 tag2", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.add_machine(
            "name2", "label", "1.2.3.4", "windows", "",
            "tag1 tag2", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.add_machine(
            "name3", "label", "1.2.3.4", "windows", "opt1 opt2",
            "tag1 tag2", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.add_machine(
            "name4", "label", "1.2.3.4", "windows", ["opt3", "opt4"],
            "tag1 tag2", "int0", "snap0", "5.6.7.8", 2043, "virtualbox",
            reserved_by=1600
        )
        m1 = self.d.view_machine("name1")
        m2 = self.d.view_machine("name2")
        m3 = self.d.view_machine("name3")
        m4 = self.d.view_machine("name4")
        assert m1.options == []
        assert m2.options == []
        assert m3.options == ["opt1", "opt2"]
        assert m4.options == ["opt3", "opt4"]
        assert m1.manager == "virtualbox"
        assert m4.reserved_by == 1600

    def test_add(self):
        now = datetime.datetime.now()
        id = self.d.add(
            [self.add_test_target(path=__file__)], 0, "py", "free=yes", 3,
            "custom", "owner", "machine1", "DogeOS", ["tag1"], False,
            False, now, "regular", None, now
        )

        task = self.d.view_task(id)
        assert id is not None
        assert task.timeout == 0
        assert task.package == "py"
        assert task.options == {"free": "yes"}
        assert task.priority == 3
        assert task.custom == "custom"
        assert task.owner == "owner"
        assert task.machine == "machine1"
        assert task.platform == "DogeOS"
        assert len(task.tags) == 1
        assert task.tags[0].name == "tag1"
        assert task.memory == False
        assert task.enforce_timeout == False
        assert task.clock == now
        assert task.submit_id is None
        assert task.start_on == now
        assert len(task.targets) == 1
        assert task.targets[0].category == "file"
        assert task.targets[0].target == __file__

    def test_set_machine_rcparams(self):
        self.d.add_machine(
            "name5", "label5", "1.2.3.4", "windows", None,
            "tag1 tag2", "int0", "snap0", "5.6.7.8", 2043
        )

        self.d.set_machine_rcparams("label5", {
            "protocol": "rdp",
            "host": "127.0.0.1",
            "port": 3389,
        })

        m = self.d.view_machine("name5")
        assert m.rcparams == {
            "protocol": "rdp",
            "host": "127.0.0.1",
            "port": "3389",
        }

    def test_add_target_file(self):
        fd, sample_path = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        target = File(sample_path)

        id = self.d.add_target(
            sample_path, "file", target.get_crc32(), target.get_md5(),
            target.get_sha1(), target.get_sha256(), target.get_sha512(),
            file_type=target.get_type(), file_size=target.get_size()
        )
        db_target = self.d.find_target(id=id)

        assert id is not None
        assert db_target.file_size == 64
        assert db_target.file_type == target.get_type()
        assert db_target.md5 == target.get_md5()
        assert db_target.crc32 == target.get_crc32()
        assert db_target.sha1 == target.get_sha1()
        assert db_target.sha256 == target.get_sha256()
        assert db_target.sha512 == target.get_sha512()
        assert db_target.ssdeep == target.get_ssdeep()
        assert db_target.category == "file"

    def test_add_target_url(self):
        target = URL("http://example.com/")

        id = self.d.add_target(
            target.url, "url", target.get_crc32(), target.get_md5(),
            target.get_sha1(), target.get_sha256(), target.get_sha512()
        )
        db_target = self.d.find_target(id=id)

        assert id is not None
        assert db_target.md5 == target.get_md5()
        assert db_target.crc32 == target.get_crc32()
        assert db_target.sha1 == target.get_sha1()
        assert db_target.sha256 == target.get_sha256()
        assert db_target.sha512 == target.get_sha512()
        assert db_target.ssdeep == target.get_ssdeep()
        assert db_target.category == "url"

    def test_find_target(self):
        fd, sample_path = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        target = File(sample_path)
        id = self.add_test_target(target, return_id=True)

        assert self.d.find_target(id=id).id == id
        assert self.d.find_target(crc32=target.get_crc32()).id == id
        assert self.d.find_target(md5=target.get_md5()).id == id
        assert self.d.find_target(sha1=target.get_sha1()).id == id
        assert self.d.find_target(sha256=target.get_sha256()).id == id
        assert self.d.find_target(sha512=target.get_sha512()).id == id

    def test_find_target_multifilter(self):
        ids = []
        paths = []
        target = None
        for x in range(2):
            fd, sample_path = tempfile.mkstemp()
            randbytes = os.urandom(64)
            paths.append(sample_path)
            os.write(fd, randbytes)
            os.close(fd)
            target = File(sample_path)
            ids.append(self.add_test_target(target, return_id=True))

        db_target = self.d.find_target(
            sha256=target.get_sha256(), target=paths[1]
        )
        assert self.d.find_target(id=ids[0], md5=target.get_md5()) is None
        assert db_target.id == ids[1]

    def test_fetch_with_machine(self):
        future = datetime.datetime(2200, 5, 12, 12, 12)
        db_target = self.add_test_target(path=__file__)
        self.d.add([db_target], tags=["service"])
        t2 = self.d.add([db_target], machine="machine1")
        self.d.add([db_target], start_on=future)
        self.d.add([db_target])

        t = self.d.fetch(machine="machine1", service=False)

        assert t.id == t2
        assert t.status == "pending"

    def test_fetch_service_false(self):
        db_target = self.add_test_target(path=__file__)
        self.d.add([db_target], tags=["service"])
        t2 = self.d.add([db_target])

        t = self.d.fetch(service=False)
        assert t.id == t2
        assert t.status == "pending"

    def test_fetch_service_true(self):
        db_target = self.add_test_target(path=__file__)
        t1 = self.d.add([db_target], tags=["service"])
        self.d.add([db_target], machine="machine1")
        self.d.add([db_target])
        self.d.add([db_target])

        task = self.d.fetch()
        assert task.id == t1
        assert task.status == "pending"

    def test_fetch_use_start_on_true(self):
        future = datetime.datetime(2200, 5, 12, 12, 12)
        db_target = self.add_test_target(path=__file__)
        self.d.add([db_target], start_on=future, priority=999)
        t2 = self.d.add([db_target])
        t = self.d.fetch(service=False)

        assert t.id == t2
        assert t.status == "pending"

    def test_fetch_use_start_on_false(self):
        future = datetime.datetime(2200, 5, 12, 12, 12)
        db_target = self.add_test_target(path=__file__)
        t1 = self.d.add([db_target], start_on=future, priority=999)
        self.d.add([db_target])

        t = self.d.fetch(use_start_on=False, service=False)
        assert t.id == t1
        assert t.status == "pending"

    def test_fetch_use_exclude(self):
        db_target = self.add_test_target(path=__file__)
        t1 = self.d.add([db_target], priority=999)
        t2 = self.d.add([db_target], priority=999)
        t3 = self.d.add([db_target], priority=999)
        t4 = self.d.add([db_target], priority=998)

        t = self.d.fetch(service=False, exclude=[t1,t2,t3])
        assert t.id == t4
        assert t.status == "pending"

    def test_fetch_specific_task(self):
        db_target = self.add_test_target(path=__file__)
        t1 = self.d.add([db_target], priority=999)
        t2 = self.d.add([db_target], priority=999)
        t = self.d.fetch(task_id=t1)
        assert t.id == t1
        assert t.status == "pending"

    def test_lock_machine(self):
        db_target = self.add_test_target(path=__file__)
        t1 = self.d.add([db_target], tags=["app1", "office7"])
        t2 = self.d.add([db_target], tags=["office15"])

        self.d.add_machine(
            "name1", "name1", "1.2.3.4", "windows", "",
            "app1,office7", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.add_machine(
            "name2", "name2", "1.2.3.4", "DogeOS", "opt1 opt2",
            "office13", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.add_machine(
            "name3", "name3", "1.2.3.4", "CoffeeOS", ["opt3", "opt4"],
            "cofOS,office7", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )

        task1 = self.d.view_task(t1)
        task2 = self.d.view_task(t2)

        m1 = self.d.lock_machine(tags=task1.tags)
        assert m1.locked
        assert m1.name == "name1"
        with pytest.raises(CuckooOperationalError):
            self.d.lock_machine(platform="DogeOS", tags=task2.tags)
        m2 = self.d.lock_machine(platform="DogeOS")
        assert m2.name == "name2"
        m3 = self.d.lock_machine(label="name3")
        assert m3.locked
        assert m3.name == "name3"

    def test_list_tasks(self):
        db_target = self.add_test_target(path=__file__)
        t1 = self.d.add(
            [db_target],  owner="doge", options={"route": "vpn511"}
        )
        t2 = self.d.add([db_target])
        self.d.add([db_target])
        self.d.set_status(t2, "reported")
        self.d.set_status(t1, "reported")

        tasks = self.d.list_tasks(owner="doge", status="reported")
        tasks2 = self.d.list_tasks()
        tasks3 = self.d.list_tasks(status="reported")

        assert tasks[0].id == t1
        assert len(tasks2) == 3
        assert len(tasks3) == 2

    def test_list_tasks_between(self):
        db_target = self.add_test_target(path=__file__)
        for x in range(5):
             self.d.add([db_target])

        tasks = self.d.list_tasks(
            filter_by="id", operators="between", values=(1, 3)
        )
        assert len(tasks) == 3

    def test_list_tasks_multiple_filter(self):
        ids = []
        future = None
        db_target = self.add_test_target(path=__file__)
        for x in range(10):
            id = self.d.add([db_target])
            ids.append(id)
            future = datetime.datetime.now() + datetime.timedelta(days=id)
            ses = self.d.Session()
            task = ses.query(Task).get(id)
            task.completed_on = future
            ses.commit()
            ses.close()

        tasks = self.d.list_tasks(
            filter_by=["id", "completed_on"], operators=[">", "<"],
            values=[4, future], order_by="id", limit=1
        )
        assert len(tasks) == 1
        assert tasks[0].id == 5

    def test_list_tasks_offset_limit(self):
        db_target = self.add_test_target(path=__file__)
        for x in range(10):
            self.d.add([db_target])

        tasks = self.d.list_tasks(offset=5, limit=10, order_by="id")
        assert len(tasks) == 5
        assert tasks[4].id == 10

    def test_list_tasks_notvalue(self):
        db_target = self.add_test_target(path=__file__)
        for x in range(10):
            id = self.d.add([db_target])
            if id % 2 == 0:
                self.d.set_status(id, "running")

        tasks = self.d.list_tasks(
            filter_by="status", operators="!=", values="running",
            order_by="id"
        )
        assert len(tasks) == 5
        assert tasks[4].id == 9

    def test_list_tasks_noresults(self):
        db_target = self.add_test_target(path=__file__)
        for x in range(5):
            self.d.add([db_target])
        tasks = self.d.list_tasks(status="reported")
        assert tasks == []

    def test_get_available_machines(self):
        self.d.add_machine(
            "name1", "name1", "1.2.3.4", "windows", "",
            "app1,office7", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.add_machine(
            "name2", "name2", "1.2.3.4", "DogeOS", "opt1 opt2",
            "office13", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.add_machine(
            "name3", "name3", "1.2.3.4", "CoffeeOS", ["opt3", "opt4"],
            "cofOS,office7", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.machine_reserve(name="name2", task_id=1337)
        self.d.lock_machine(label="name3")
        available = self.d.get_available_machines()
        names = [m["name"] for m in [db_m.to_dict() for db_m in available]]

        assert len(available) == 2
        assert "name2" in names
        assert "name1" in names

    def test_unlock_machine(self):
        self.d.add_machine(
            "name1", "name1", "1.2.3.4", "windows", "",
            "app1,office7", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.lock_machine(label="name1")

        assert self.d.view_machine(name="name1").locked
        self.d.unlock_machine(label="name1")
        assert not self.d.view_machine(name="name1").locked

    def test_list_machines(self):
        self.d.add_machine(
            "name1", "name1", "1.2.3.4", "windows", "",
            "app1,office7", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.add_machine(
            "name2", "name2", "1.2.3.4", "DogeOS", "opt1 opt2",
            "office13", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        allmachines = self.d.list_machines()
        names = [m["name"] for m in [db_m.to_dict() for db_m in allmachines]]

        assert len(allmachines) == 2
        assert "name2" in names
        assert "name1" in names

    def test_machine_reserve(self):
        self.d.add_machine(
            "name1", "name1", "1.2.3.4", "windows", "",
            "app1,office7", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        assert self.d.view_machine(name="name1").reserved_by is None
        self.d.machine_reserve(name="name1", task_id=42)
        assert self.d.view_machine(name="name1").reserved_by == 42

    def test_clear_reservation(self):
        self.d.add_machine(
            "name1", "name1", "1.2.3.4", "windows", "",
            "app1,office7", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
        )
        self.d.machine_reserve(name="name1", task_id=42)
        assert self.d.view_machine(name="name1").reserved_by == 42
        self.d.clear_reservation(name="name1")
        assert self.d.view_machine(name="name1").reserved_by is None

    def test_clean_machines(self):
        for x in range(6):
            name = "name%s" % x
            self.d.add_machine(
                name, name, "1.2.3.4", "windows", "",
                "app1,office7", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
            )

        assert len(self.d.list_machines()) == 6
        self.d.clean_machines()
        assert len(self.d.list_machines()) == 0

    def test_target_to_dict(self):
        fd, sample_path = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        target = File(sample_path)
        id = self.add_test_target(fileobj=target, return_id=True)
        db_target = self.d.find_target(id=id)
        db_target = db_target.to_dict()

        assert db_target["id"] == id
        assert db_target["file_size"] == 64
        assert db_target["file_type"] == target.get_type()
        assert db_target["md5"] == target.get_md5()
        assert db_target["crc32"] == target.get_crc32()
        assert db_target["sha1"] == target.get_sha1()
        assert db_target["sha256"] == target.get_sha256()
        assert db_target["sha512"] == target.get_sha512()
        assert db_target["ssdeep"] == target.get_ssdeep()
        assert db_target["category"] == "file"
        assert db_target["target"] == sample_path

    def test_task_multiple_targets(self):
        db_targets = []
        for x in range(10):
            fd, sample_path = tempfile.mkstemp()
            os.write(fd, os.urandom(64))
            os.close(fd)
            db_targets.append(self.add_test_target(path=sample_path))
        taskid = self.d.add(db_targets)
        task = self.d.view_task(taskid)
        assert task.id == taskid
        assert len(task.targets) == 10

class TestConnectOnce(object):
    def setup(self):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        init_yara()

    @mock.patch("cuckoo.main.Database")
    @mock.patch("cuckoo.apps.apps.Database")
    @mock.patch("cuckoo.apps.apps.process")
    def test_process_task(self, q, p1, p2):
        mkdir(cwd(analysis=1))
        p1.return_value.view_task.return_value = {}
        main.main(
            ("--cwd", cwd(), "process", "-r", "1"),
            standalone_mode=False
        )

        q.assert_called_once()
        p2.return_value.connect.assert_called_once()
        p1.return_value.connect.assert_not_called()

    @mock.patch("cuckoo.main.Database")
    @mock.patch("cuckoo.apps.apps.Database")
    @mock.patch("cuckoo.apps.apps.process")
    def test_process_tasks(self, q, p1, p2):
        p1.return_value.processing_get_task.side_effect = 1, 2
        p1.return_value.view_task.side_effect = [
            Task(id=1, type="regular"),
            Task(id=2, type="regular"),
        ]

        main.main(
            ("--cwd", cwd(), "process", "p0"),
            standalone_mode=False
        )

        assert q.call_count == 2
        p2.return_value.connect.assert_called_once()
        p1.return_value.connect.assert_not_called()

class TestSqlite3Memory(DatabaseEngine):
    URI = "sqlite:///:memory:"

class TestSqlite3File(DatabaseEngine):
    URI = "sqlite:///%s" % tempfile.mktemp()

@pytest.mark.skipif("sys.platform == 'darwin'")
class TestPostgreSQL(DatabaseEngine):
    URI = "postgresql://cuckoo:cuckoo@localhost/cuckootest"

@pytest.mark.skipif("sys.platform == 'darwin'")
class TestMySQL(DatabaseEngine):
    URI = "mysql://cuckoo:cuckoo@localhost/cuckootest"

@pytest.mark.skipif("sys.platform != 'linux2'")
class DatabaseMigrationEngine(object):
    """Tests database migration(s)."""
    URI = None
    SRC = None

    def add_test_url(self, url):
        url = URL(url)
        id = self.d.add_target(
            url.url, "url", url.get_crc32(), url.get_md5(),
            url.get_sha1(), url.get_sha256(), url.get_sha512()
        )
        return self.d.find_target(id=id)

    def setup_class(cls):
        set_cwd(tempfile.mkdtemp())

        cls.d = Database()
        cls.d.connect(dsn=cls.URI, create=False)

        cuckoo_create(cfg={
            "cuckoo": {
                "database": {
                    "connection": cls.URI,
                },
            },
        })

        cls.s = cls.d.Session()
        cls.execute_script(cls, open(cls.SRC, "rb").read())
        cls.migrate(cls)

    def test_alembic_version(self):
        version = self.s.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        assert version and len(version) == 1
        assert version[0][0] == SCHEMA_VERSION

    def test_long_error(self):
        db_target = self.add_test_url("http://example1.com")
        print "TARGET IS: %s" % db_target

        task_id = self.d.add([db_target])
        self.d.add_error("A"*1024, task_id)
        err = self.d.view_errors(task_id)
        assert err and len(err[0].message) == 1024

    def test_long_options_custom(self):
        task_id = self.d.add(
            [self.add_test_url("http://example2.com")],
            options="A"*1024, custom="B"*1024,
        )
        task = self.d.view_task(task_id)
        assert task._options == "A"*1024
        assert task.custom == "B"*1024

    def test_empty_submit_id(self):
        task_id = self.d.add([self.add_test_url("http://example3.com")])
        task = self.d.view_task(task_id)
        assert task.submit_id is None

class DatabaseMigration060(DatabaseMigrationEngine):
    def test_machine_resultserver_port_is_int(self):
        machines = self.s.execute(
            "SELECT resultserver_ip, resultserver_port FROM machines"
        ).fetchall()
        assert machines and len(machines) == 2
        assert machines[0][0] == "192.168.56.1"
        assert machines[0][1] == 2042
        assert machines[1][0] == "192.168.56.1"
        assert machines[1][1] == 2042

@pytest.mark.skipif("sys.platform == 'darwin'")
class TestDatabaseMigration060PostgreSQL(DatabaseMigration060):
    URI = "postgresql://cuckoo:cuckoo@localhost/cuckootest060"
    SRC = "tests/files/sql/060pg.sql"

    @staticmethod
    def execute_script(cls, script):
        cls.s.execute(script)
        cls.s.commit()

    @staticmethod
    def migrate(cls):
        tasks = cls.d.engine.execute(
            "SELECT status FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "failure"
        assert tasks[1][0] == "success"
        assert tasks[2][0] == "processing"

        main.main(
            ("--cwd", cwd(), "migrate", "--revision", "263a45963c72"),
            standalone_mode=False
        )

        tasks = cls.d.engine.execute(
            "SELECT status FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "failed_analysis"
        assert tasks[1][0] == "completed"
        assert tasks[2][0] == "running"

        main.main(
            ("--cwd", cwd(), "migrate"),
            standalone_mode=False
        )

        tasks = cls.d.engine.execute(
            "SELECT status, owner FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "failed_analysis"
        assert tasks[0][1] is None
        assert tasks[1][0] == "completed"
        assert tasks[2][0] == "running"

class TestDatabaseMigration060SQLite3(DatabaseMigration060):
    URI = "sqlite:///%s.sqlite3" % tempfile.mktemp()
    SRC = "tests/files/sql/060sq.sql"

    @staticmethod
    def execute_script(cls, script):
        cls.s.connection().connection.cursor().executescript(script)

    @staticmethod
    def migrate(cls):
        tasks = cls.d.engine.execute(
            "SELECT status FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "failure"
        assert tasks[1][0] == "processing"
        assert tasks[2][0] == "success"
        assert tasks[3][0] == "pending"

        main.main(
            ("--cwd", cwd(), "migrate", "--revision", "263a45963c72"),
            standalone_mode=False
        )

        tasks = cls.d.engine.execute(
            "SELECT status FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "failed_analysis"
        assert tasks[1][0] == "running"
        assert tasks[2][0] == "completed"
        assert tasks[3][0] == "pending"

        main.main(
            ("--cwd", cwd(), "migrate"),
            standalone_mode=False
        )

        tasks = cls.d.engine.execute(
            "SELECT status, owner FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "failed_analysis"
        assert tasks[0][1] is None
        assert tasks[1][0] == "running"
        assert tasks[2][0] == "completed"
        assert tasks[3][0] == "pending"

@pytest.mark.skipif("sys.platform == 'darwin'")
class TestDatabaseMigration060MySQL(DatabaseMigration060):
    URI = "mysql://cuckoo:cuckoo@localhost/cuckootest060"
    SRC = "tests/files/sql/060my.sql"

    @staticmethod
    def execute_script(cls, script):
        cls.s.execute(script)

    @staticmethod
    def migrate(cls):
        tasks = cls.d.engine.execute(
            "SELECT status FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "success"
        assert tasks[1][0] == "processing"
        assert tasks[2][0] == "pending"

        main.main(
            ("--cwd", cwd(), "migrate", "--revision", "263a45963c72"),
            standalone_mode=False
        )

        tasks = cls.d.engine.execute(
            "SELECT status FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "completed"
        assert tasks[1][0] == "running"
        assert tasks[2][0] == "pending"

        main.main(
            ("--cwd", cwd(), "migrate"),
            standalone_mode=False
        )

        tasks = cls.d.engine.execute(
            "SELECT status, owner FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "completed"
        assert tasks[0][1] is None
        assert tasks[1][0] == "running"
        assert tasks[2][0] == "pending"

class DatabaseMigration11(DatabaseMigrationEngine):
    @staticmethod
    def migrate(cls):
        main.main(("--cwd", cwd(), "migrate"), standalone_mode=False)

    def test_task_statuses(cls):
        tasks = cls.d.engine.execute(
            "SELECT status, owner FROM tasks ORDER BY id"
        ).fetchall()
        assert tasks[0][0] == "reported"
        assert tasks[1][0] == "pending"

    def test_task_options_custom(cls):
        tasks = cls.d.engine.execute(
            "SELECT options, custom FROM tasks WHERE id = 1"
        ).fetchall()
        assert tasks[0][0] == "human=1"
        assert tasks[0][1] == "custom1"

@pytest.mark.skipif("sys.platform == 'darwin'")
class TestDatabaseMigration11PostgreSQL(DatabaseMigration11):
    URI = "postgresql://cuckoo:cuckoo@localhost/cuckootest11"
    SRC = "tests/files/sql/11pg.sql"

    @staticmethod
    def execute_script(cls, script):
        cls.s.execute(script)
        cls.s.commit()

class TestDatabaseMigration11SQLite3(DatabaseMigration11):
    URI = "sqlite:///%s.sqlite3" % tempfile.mktemp()
    SRC = "tests/files/sql/11sq.sql"

    @staticmethod
    def execute_script(cls, script):
        cls.s.connection().connection.cursor().executescript(script)

@pytest.mark.skipif("sys.platform == 'darwin'")
class TestDatabaseMigration11MySQL(DatabaseMigration11):
    URI = "mysql://cuckoo:cuckoo@localhost/cuckootest11"
    SRC = "tests/files/sql/11my.sql"

    @staticmethod
    def execute_script(cls, script):
        cls.s.execute(script)

@mock.patch("cuckoo.core.database.create_engine")
@mock.patch("cuckoo.core.database.sessionmaker")
def test_connect_default(p, q):
    set_cwd(tempfile.mkdtemp())
    cuckoo_create()

    db = Database()
    db.connect(create=False)
    q.assert_called_once_with(
        "sqlite:///%s" % cwd("cuckoo.db"),
        connect_args={"check_same_thread": False}
    )
    assert db.engine.pool_timeout == 60

@mock.patch("cuckoo.core.database.create_engine")
@mock.patch("cuckoo.core.database.sessionmaker")
def test_connect_pg(p, q):
    set_cwd(tempfile.mkdtemp())
    cuckoo_create(cfg={
        "cuckoo": {
            "database": {
                "connection": "postgresql://foo:bar@localhost/foobar",
                "timeout": 120,
            }
        }
    })

    db = Database()
    db.connect(create=False)
    q.assert_called_once_with(
        "postgresql://foo:bar@localhost/foobar",
        connect_args={"sslmode": "disable"}
    )
    assert db.engine.pool_timeout == 120

@pytest.mark.skipif("sys.platform != 'linux2'")
class DistributedDatabaseEngine(object):
    URI = None

    @classmethod
    def setup_class(cls):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()

        # Don't judge me!
        with open(cwd("distributed", "settings.py"), "a+b") as f:
            f.write("\nSQLALCHEMY_DATABASE_URI = %r\n" % cls.URI)

        cls.app = create_app()

    def test_dummy(self):
        pass

class TestDistributedSqlite3Memory(DistributedDatabaseEngine):
    URI = "sqlite:///:memory:"

class TestDistributedSqlite3File(DistributedDatabaseEngine):
    URI = "sqlite:///%s" % tempfile.mktemp()

@pytest.mark.skipif("sys.platform == 'darwin'")
class TestDistributedPostgreSQL(DistributedDatabaseEngine):
    URI = "postgresql://cuckoo:cuckoo@localhost/distcuckootest"

@pytest.mark.skipif("sys.platform == 'darwin'")
class TestDistributedMySQL(DistributedDatabaseEngine):
    URI = "mysql://cuckoo:cuckoo@localhost/distcuckootest"
