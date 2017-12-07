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
from cuckoo.common.objects import File
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
        task_id = self.d.add(url, priority=priority, category="url")
        self.d.set_status(task_id, status)
        return task_id

    def test_add_task(self):
        fd, sample_path = tempfile.mkstemp()
        os.write(fd, "hehe")
        os.close(fd)

        # Add task.
        count = self.d.Session().query(Task).count()
        self.d.add(sample_path, category="file")
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
        t1 = self.d.add(__file__, custom="1", submit_id=submit_id,
                        category="file")
        t2 = self.d.add(__file__, custom="2", submit_id=submit_id,
                        category="file")

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
        t0 = self.d.add(__file__, options={"foo": "bar"}, category="file")
        t1 = self.d.add(__file__, options="foo=bar", category="file")
        assert self.d.view_task(t0).options == {"foo": "bar"}
        assert self.d.view_task(t1).options == {"foo": "bar"}

    def test_error_action(self):
        task_id = self.d.add(__file__, category="file")
        self.d.add_error("message1", task_id)
        self.d.add_error("message2", task_id, "actionhere")
        e1, e2 = self.d.view_errors(task_id)
        assert e1.message == "message1"
        assert e1.action is None
        assert e2.message == "message2"
        assert e2.action == "actionhere"

    def test_view_tasks(self):
        t1 = self.d.add(__file__, category="file")
        t2 = self.d.add("http://google.com/", category="url")
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
            "tag1 tag2", "int0", "snap0", "5.6.7.8", 2043, "virtualbox"
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

    def test_add(self):
        now = datetime.datetime.now()
        id = self.d.add(__file__, 0, "py", "free=yes", 3, "custom", "owner",
                        "machine1", "DogeOS", ["tag1"], False,
                        False, now, "file", None, 1, now)

        task = self.d.view_task(id)
        assert id is not None
        assert task.target == __file__
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
        assert task.category == "file"
        assert task.submit_id is None
        assert task.sample_id == 1
        assert task.start_on == now

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

    @mock.patch("sflock.magic")
    def test_add_sample(self, p):
        p.from_file.return_value = ""
        assert self.d.add_path(Files.temp_put(os.urandom(16))) is not None

    def test_add_sample(self):
        fd, sample_path = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        sample = File(sample_path)

        id = self.d.add_sample(sample)

        db_sample = self.d.view_sample(id)

        assert id is not None
        assert db_sample.file_size == sample.get_size()
        assert db_sample.file_type == sample.get_type()
        assert db_sample.md5 == sample.get_md5()
        assert db_sample.crc32 == sample.get_crc32()
        assert db_sample.sha1 == sample.get_sha1()
        assert db_sample.sha256 == sample.get_sha256()
        assert db_sample.sha512 == sample.get_sha512()
        assert db_sample.ssdeep == sample.get_ssdeep()

    def test_add_sample_existing(self):
        fd, sample_path = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        sample_file = File(sample_path)
        id = self.d.add_sample(sample_file)
        id2 = self.d.add_sample(sample_file)

        assert id2 == id

    def test_add_sample_incorrect(self):
        id = self.d.add_sample("A"*20)
        assert id is None

    def test_fetch_with_machine(self):
        future = datetime.datetime(2200, 5, 12, 12, 12)
        self.d.add(__file__, category="file", tags=["service"])
        t2 = self.d.add(__file__, category="file", machine="machine1")
        self.d.add(__file__, category="file", start_on=future)
        self.d.add(__file__, category="file")

        assert self.d.fetch(machine="machine1", service=False).id == t2

    def test_fetch_service_false(self):
        self.d.add(__file__, category="file", tags=["service"])
        t2 = self.d.add(__file__, category="file")

        assert self.d.fetch(service=False).id == t2

    def test_fetch_service_true(self):
        t1 = self.d.add(__file__, category="file", tags=["service"])
        self.d.add(__file__, category="file", machine="machine1")
        self.d.add(__file__, category="file")
        self.d.add(__file__, category="file",)

        task = self.d.fetch()
        assert task.id == t1
        assert task.status == "running"

    def test_fetch_no_lock(self):
        self.d.add(__file__, category="file", tags=["service"])
        self.d.add(__file__, category="file", machine="machine1")
        self.d.add(__file__, category="file")
        self.d.add(__file__, category="file")

        assert self.d.fetch(lock=False, service=False).status == "pending"

    def test_fetch_use_start_on_true(self):
        future = datetime.datetime(2200, 5, 12, 12, 12)
        self.d.add(__file__, category="file", start_on=future, priority=999)
        t2 = self.d.add(__file__, category="file")

        assert self.d.fetch(service=False).id == t2

    def test_fetch_use_start_on_false(self):
        future = datetime.datetime(2200, 5, 12, 12, 12)
        t1 = self.d.add(__file__, category="file", start_on=future,
                        priority=999)
        self.d.add(__file__, category="file")

        assert self.d.fetch(use_start_on=False, service=False).id == t1

    def test_fetch_use_exclude(self):
        t1 = self.d.add(__file__, category="file", priority=999)
        t2 = self.d.add(__file__, category="file", priority=999)
        t3 = self.d.add(__file__, category="file", priority=999)
        t4 = self.d.add(__file__, category="file", priority=998)

        assert self.d.fetch(service=False, exclude=[t1,t2,t3]).id == t4

    def test_lock_machine(self):
        t1 = self.d.add(__file__, category="file", tags=["app1", "office7"])
        t2 = self.d.add(__file__, category="file", tags=["office15"])

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
            Task(id=1, category="url", target="http://google.com/"),
            Task(id=2, category="url", target="http://google.nl/"),
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
        task_id = self.d.add("http://google.com/", category="url")
        self.d.add_error("A"*1024, task_id)
        err = self.d.view_errors(task_id)
        assert err and len(err[0].message) == 1024

    def test_long_options_custom(self):
        task_id = self.d.add(
            "http://google.com/", options="A"*1024, custom="B"*1024,
            category="url"
        )
        task = self.d.view_task(task_id)
        assert task._options == "A"*1024
        assert task.custom == "B"*1024

    def test_empty_submit_id(self):
        task_id = self.d.add("http://google.com/", category="url")
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
