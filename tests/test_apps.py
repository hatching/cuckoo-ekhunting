# Copyright (C) 2016-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import hashlib
import json
import logging
import mock
import os
import pytest
import shutil
import sys
import tempfile

import cuckoo

from cuckoo.apps.apps import (
    process_task, cuckoo_clean, process_task_range, cuckoo_machine,
    migrate_cwd
)
from cuckoo.common.config import config
from cuckoo.common.exceptions import CuckooConfigurationError
from cuckoo.common.files import Files
from cuckoo.core.database import Database
from cuckoo.core.log import logger
from cuckoo.core.task import Task
from cuckoo.core.startup import (
    init_logfile, init_console_logging, init_yara, init_logging
)
from cuckoo.main import main, cuckoo_create, cuckoo_init
from cuckoo.misc import set_cwd, decide_cwd, cwd, mkdir, is_linux
from tests.utils import chdir

db = Database()
submit_task = Task()

@mock.patch("cuckoo.main.load_signatures")
def test_init(p):
    set_cwd(tempfile.mkdtemp())
    with pytest.raises(SystemExit):
        main.main(
            ("--cwd", cwd(), "--nolog", "init"),
            standalone_mode=False
        )
    p.assert_not_called()

class TestAppsWithCWD(object):
    def setup(self):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()

    @mock.patch("cuckoo.main.load_signatures")
    @mock.patch("cuckoo.main.cuckoo_main")
    def test_main(self, p, q):
        p.side_effect = SystemExit(0)

        # Ensure that the "latest" binary value makes sense so that the
        # "run community command" exception is not thrown.
        mkdir(cwd("monitor", open(cwd("monitor", "latest")).read().strip()))
        main.main(("--cwd", cwd(), "-d", "--nolog"), standalone_mode=False)
        q.assert_called_once()

    @mock.patch("cuckoo.main.load_signatures")
    @mock.patch("cuckoo.main.log")
    def test_main_exception(self, p, q):
        q.side_effect = Exception("this is a test")
        with pytest.raises(SystemExit):
            main.main(
                ("--cwd", cwd(), "-d", "--nolog"), standalone_mode=False
            )
        p.exception.assert_called_once()

    def test_api(self):
        with mock.patch("cuckoo.main.cuckoo_api") as p:
            p.return_value = None
            main.main(("--cwd", cwd(), "api"), standalone_mode=False)
            p.assert_called_once_with("localhost", 8090, False)

    if is_linux():
        @mock.patch("cuckoo.main.cuckoo_rooter")
        def test_rooter_abort(self, p, capsys):
            p.side_effect = KeyboardInterrupt
            main.main(("--cwd", cwd(), "rooter"), standalone_mode=False)
            out, _ = capsys.readouterr()
            assert "Aborting the Cuckoo Rooter" in out

    def test_community(self):
        with mock.patch("cuckoo.main.fetch_community") as p:
            p.return_value = None
            main.main(("--cwd", cwd(), "community"), standalone_mode=False)
            p.assert_called_once_with(
                force=False, branch="master", filepath=None
            )

    @mock.patch("cuckoo.main.fetch_community")
    def test_community_abort(self, p, capsys):
        p.side_effect = KeyboardInterrupt
        main.main(("--cwd", cwd(), "community"), standalone_mode=False)
        out, _ = capsys.readouterr()
        assert "Aborting fetching of" in out

    def test_clean(self):
        with mock.patch("cuckoo.main.cuckoo_clean") as p:
            p.return_value = None
            main.main(("--cwd", cwd(), "clean"), standalone_mode=False)
            p.assert_called_once_with()

    @mock.patch("cuckoo.main.cuckoo_clean")
    def test_clean_abort(self, p, capsys):
        p.side_effect = KeyboardInterrupt
        main.main(("--cwd", cwd(), "clean"), standalone_mode=False)
        out, _ = capsys.readouterr()
        assert "Aborting cleaning up of" in out

    def test_submit(self):
        with mock.patch("cuckoo.main.submit_tasks") as p:
            p.return_value = []
            main.main((
                "--cwd", cwd(), "submit", Files.create(cwd(), "a.txt", "hello")
            ), standalone_mode=False)

    @mock.patch("cuckoo.main.submit_tasks")
    def test_submit_abort(self, p, capsys):
        p.side_effect = KeyboardInterrupt
        main.main((
            "--cwd", cwd(), "submit", Files.create(cwd(), "a.txt", "hello")
        ), standalone_mode=False)
        out, _ = capsys.readouterr()
        assert "Aborting submission of" in out

    def test_dnsserve(self):
        with mock.patch("cuckoo.main.cuckoo_dnsserve") as p:
            p.return_value = None
            main.main(("--cwd", cwd(), "dnsserve"), standalone_mode=False)
            p.assert_called_once_with("0.0.0.0", 53, None, None)

    @mock.patch("cuckoo.main.cuckoo_dnsserve")
    def test_dnsserve_abort(self, p, capsys):
        p.side_effect = KeyboardInterrupt
        main.main(("--cwd", cwd(), "dnsserve"), standalone_mode=False)
        out, _ = capsys.readouterr()
        assert "Aborting Cuckoo DNS Serve" in out

    @mock.patch("django.core.management.execute_from_command_line")
    def test_web_noargs(self, p):
        curdir = os.getcwd()

        main.main(("--cwd", cwd(), "web"), standalone_mode=False)
        p.assert_called_once_with(
            ("cuckoo", "runserver", "localhost:8000")
        )

        os.chdir(curdir)

    @mock.patch("django.core.management.execute_from_command_line")
    def test_web_args(self, p):
        curdir = os.getcwd()

        main.main(
            ("--cwd", cwd(), "web", "foo", "bar"),
            standalone_mode=False
        )
        p.assert_called_once_with(("cuckoo", "foo", "bar"))

        os.chdir(curdir)

    def test_machine(self):
        with mock.patch("cuckoo.main.cuckoo_machine") as p:
            p.return_value = None
            main.main((
                "--cwd", cwd(), "machine", "cuckoo2", "1.2.3.4", "--add"
            ), standalone_mode=False)

            p.assert_called_once_with(
                "cuckoo2", "add", "1.2.3.4", "windows",
                None, None, None, None, None
            )

    def test_machine_add(self):
        cuckoo_machine(
            "cuckoo2", "add", "1.2.3.4", "windows",
            None, None, None, None, None
        )
        assert config("virtualbox:virtualbox:machines") == [
            "cuckoo1", "cuckoo2",
        ]
        assert config("virtualbox:cuckoo2:ip") == "1.2.3.4"
        assert config("virtualbox:cuckoo2:platform") == "windows"

    def test_machine_delete(self):
        cuckoo_machine(
            "cuckoo1", "delete", None, None, None, None, None, None, None
        )
        assert config("virtualbox:virtualbox:machines") == []

        # TODO This might require a little tweak.
        with pytest.raises(CuckooConfigurationError) as e:
            config("virtualbox:cuckoo1:label", strict=True)
        e.match("No such configuration value exists")

    @mock.patch("click.confirm")
    @mock.patch("cuckoo.main.import_cuckoo")
    def test_import_confirm(self, p, q, capsys):
        p.return_value = None
        q.return_value = True
        dirpath = tempfile.mkdtemp()
        main.main(
            ("--cwd", cwd(), "import", dirpath),
            standalone_mode=False
        )
        p.assert_called_once_with(None, "copy", dirpath)
        out, err = capsys.readouterr()
        assert "understand that, depending on the mode" in out

    @mock.patch("click.confirm")
    def test_import_noconfirm(self, p, capsys):
        p.return_value = False
        with pytest.raises(SystemExit) as e:
            main.main(
                ("--cwd", cwd(), "import", tempfile.mkdtemp()),
                standalone_mode=False
            )
        e.match("Aborting operation")

    @mock.patch("click.confirm")
    @mock.patch("cuckoo.main.import_cuckoo")
    def test_import_abort(self, p, q, capsys):
        p.side_effect = KeyboardInterrupt
        q.return_value = True
        main.main(
            ("--cwd", cwd(), "import", tempfile.mkdtemp()),
            standalone_mode=False
        )
        out, _ = capsys.readouterr()
        assert "Aborting import of Cuckoo instance" in out

    def test_dist_server(self):
        with mock.patch("cuckoo.main.cuckoo_distributed") as p:
            p.return_value = None
            main.main(
                ("--cwd", cwd(), "distributed", "server"),
                standalone_mode=False
            )
            p.assert_called_once_with("localhost", 9003, False)

    def test_dist_instance(self):
        with mock.patch("cuckoo.main.cuckoo_distributed_instance") as p:
            p.return_value = None
            main.main(
                ("--cwd", cwd(), "distributed", "instance", "name"),
                standalone_mode=False
            )
            p.assert_called_once_with("name")

    def test_dist_migrate(self):
        with mock.patch("cuckoo.main.subprocess.check_call") as p:
            p.return_value = None
            main.main(
                ("--cwd", cwd(), "distributed", "migrate"),
                standalone_mode=False
            )
            p.assert_called_once_with(
                ["alembic", "-x", "cwd=%s" % cwd(), "upgrade", "head"],
                cwd=cwd("distributed", "migration", private=True)
            )

class TestProcessingTasks(object):
    def setup(self):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        Database().connect()

    def teartown(self):
        cwd_path = cwd()
        if os.path.isdir(cwd_path):
            shutil.rmtree(cwd())

    @mock.patch("cuckoo.main.load_signatures")
    @mock.patch("cuckoo.main.process_task_range")
    def test_process_once(self, p, q):
        main.main(
            ("--cwd", cwd(), "process", "-r", "1234"),
            standalone_mode=False
        )
        p.assert_called_once_with("1234")
        q.assert_called_once()

    @mock.patch("cuckoo.main.load_signatures")
    @mock.patch("cuckoo.main.process_task_range")
    def test_process_abort(self, p, q, capsys):
        p.side_effect = KeyboardInterrupt
        main.main(
            ("--cwd", cwd(), "process", "-r", "1234"),
            standalone_mode=False
        )
        out, _ = capsys.readouterr()
        assert "Aborting (re-)processing of your analyses" in out

    @mock.patch("cuckoo.apps.apps.process_task")
    @mock.patch("cuckoo.apps.apps.Task")
    def test_process_once_deeper(self, t, p):
        mkdir(cwd(analysis=1234))
        process_task_range("1234")
        p.assert_called_once()
        t.set_task.assert_not_called()
        t.assert_has_calls([
            mock.call().load_task_dict({
                "id": 1234,
                "category": "file",
                "target": "",
                "options": {},
                "package": None,
                "custom": None,
            })
        ])

    @mock.patch("cuckoo.apps.apps.process_task")
    @mock.patch("cuckoo.apps.apps.Task")
    def test_process_task_range_single_db(self, mt, mp):
        task = Task()
        id = task.add_path(__file__)
        process_task_range(str(id))
        mt.assert_has_calls([
            mock.call().set_task(mock.ANY)
        ])
        mp.assert_called_once()

    @mock.patch("cuckoo.apps.apps.process_task")
    @mock.patch("cuckoo.apps.apps.Task")
    def test_process_task_range_multi(self, mt, mp):
        mkdir(cwd(analysis=1234))
        mkdir(cwd(analysis=2345))
        process_task_range("1234,2345")
        assert mp.call_count == 2
        mt.assert_has_calls([
            mock.call(),
            mock.call().load_task_dict({
                "id": 1234,
                "category": "file",
                "target": "",
                "options": {},
                "package": None,
                "custom": None,
            }), mock.call(),
            mock.call().load_task_dict({
                "id": 2345,
                "category": "file",
                "target": "",
                "options": {},
                "package": None,
                "custom": None,
            })
        ])

    @mock.patch("cuckoo.apps.apps.process_task")
    @mock.patch("cuckoo.apps.apps.Task")
    def test_process_task_range_multi_db(self, mt, mp):
        task1, task2 = Task(), Task()
        id1, id2 = task1.add_path(__file__), task2.add_path(__file__)
        process_task_range("%s,%s" % (id1, id2))
        assert mp.call_count == 2
        mt.assert_has_calls([
            mock.call(), mock.call().set_task(mock.ANY), mock.call(),
            mock.call().set_task(mock.ANY)
        ])

    @mock.patch("cuckoo.apps.apps.Database.set_status")
    @mock.patch("cuckoo.apps.apps.task_log_start")
    def test_process_task(self, mt, mdb):
        tasks = []
        for x in range(1, 10):
            task = mock.MagicMock()
            task.id = x
            tasks.append(task)

        taskx = mock.MagicMock()
        taskx.dir_exists.return_value = False
        tasks.append(taskx)

        for task in tasks:
            process_task(task)
            task.dir_exists.assert_called_once()
            if task is taskx:
                # The task dir for this task does not exist. It should
                # not be processed
                task.process.assert_not_called()
                mdb.assert_any_call(task.id, "failed_processing")
            else:
                task.process.assert_called_once()
                mdb.assert_any_call(task.id, "reported")

    @mock.patch("cuckoo.apps.apps.process_task")
    @mock.patch("cuckoo.apps.apps.Task")
    def test_process_task_range_range(self, mt, p):
        mkdir(cwd(analysis=3))
        for x in xrange(10, 101):
            mkdir(cwd(analysis=x))
        process_task_range("3,10-100")
        assert p.call_count == 92
        assert mt.call_count == 92

    @mock.patch("cuckoo.apps.apps.Database")
    def test_process_task_range_duplicate(self, p):
        process_task_range("3,3,42")
        assert p.return_value.view_task.call_count == 2
        p.return_value.view_task.assert_any_call(3)
        p.return_value.view_task.assert_any_call(42)

    @mock.patch("cuckoo.main.load_signatures")
    @mock.patch("cuckoo.main.process_tasks")
    def test_process_many(self, p, q):
        main.main(
            ("--cwd", cwd(), "process", "instance"),
            standalone_mode=False
        )
        p.assert_called_once_with("instance", 0)
        q.assert_called_once()

    @mock.patch("cuckoo.apps.apps.Database")
    @mock.patch("cuckoo.apps.apps.logger")
    def test_logger(self, p, q):
        task = Task()
        task.process = mock.MagicMock()
        task.add_path(__file__, options={"a": "b"}, custom="foobar",
                      package="baz")
        process_task(task)

        p.assert_called_once()
        assert p.call_args[1] == {
            "action": "task.report",
            "status": "pending",
            "target": __file__,
            "category": "file",
            "package": "baz",
            "options": "a=b",
            "custom": "foobar",
        }

    @mock.patch("cuckoo.main.process_task_range")
    @mock.patch("cuckoo.main.init_modules")
    def test_process_init_modules(self, p, q):
        main.main(
            ("--cwd", cwd(), "process", "-r", "1"),
            standalone_mode=False
        )
        p.assert_called_once()

    def test_empty_reprocess(self):
        db.connect()
        mkdir(cwd(analysis=1))
        init_logging(logging.INFO)
        init_console_logging(logging.INFO)
        process_task_range("1")
        assert os.path.exists(cwd("reports", "report.json", analysis=1))
        obj = json.load(open(cwd("reports", "report.json", analysis=1), "rb"))
        assert "contact back" in obj["debug"]["errors"][0]

    def test_reprocess_taskjson(self):
        db.connect()
        mkdir(cwd(analysis=1))
        init_logging(logging.INFO)
        init_console_logging(logging.INFO)
        shutil.copyfile(
            os.path.join("tests", "files", "task_dump.json"),
            cwd("task.json", analysis=1)
        )
        process_task_range("1")
        assert os.path.exists(cwd("task.json", analysis=1))
        assert os.path.exists(cwd("reports", "report.json", analysis=1))
        obj = json.load(open(cwd("reports", "report.json", analysis=1), "rb"))
        assert obj["info"]["added"] == 1494439200.0

def test_process_log_taskid():
    set_cwd(tempfile.mkdtemp())
    cuckoo_create()
    db.connect()

    init_console_logging(logging.DEBUG)
    init_logfile("process-p0.json")

    task = Task()
    task.add_url("http://google.com/", package="ie")
    task.process = mock.MagicMock()
    process_task(task)

    for line in open(cwd("log", "process-p0.json"), "rb"):
        obj = json.loads(line)
        if obj["action"] == "task.report":
            assert obj["task_id"] == task.id
            break
    else:
        raise

@mock.patch("cuckoo.apps.apps.Database")
def test_clean_dropdb(p):
    set_cwd(tempfile.mkdtemp())
    cuckoo_create()

    cuckoo_clean()
    p.return_value.connect.assert_called_once()
    p.return_value.drop.assert_called_once_with()

@mock.patch("cuckoo.apps.apps.Database")
@mock.patch("cuckoo.apps.apps.mongo")
def test_clean_dropmongo(p, q):
    set_cwd(tempfile.mkdtemp())
    cuckoo_create(cfg={
        "reporting": {
            "mongodb": {
                "enabled": True,
                "host": "host",
                "port": 13337,
            },
        },
    })

    cuckoo_clean()
    p.init.assert_called_once_with()
    p.connect.assert_called_once_with()
    p.drop.assert_called_once_with()
    p.close.assert_called_once_with()

@mock.patch("cuckoo.apps.apps.Database")
def test_clean_keepdirs(p):
    set_cwd(tempfile.mkdtemp())
    cuckoo_create()

    with open(cwd("log", "cuckoo.log"), "wb") as f:
        f.write("this is a log file")

    os.mkdir(cwd(analysis=1))
    with open(cwd("analysis.log", analysis=1), "wb") as f:
        f.write("this is also a log file")

    with open(cwd("storage", "binaries", "a"*40), "wb") as f:
        f.write("this is a binary file")

    assert os.path.isdir(cwd("log"))
    assert os.path.exists(cwd("log", "cuckoo.log"))
    assert os.path.exists(cwd("storage", "analyses"))
    assert os.path.exists(cwd("storage", "analyses", "1"))
    assert os.path.exists(cwd("storage", "analyses", "1", "analysis.log"))
    assert os.path.exists(cwd("storage", "baseline"))
    assert os.path.exists(cwd("storage", "binaries"))
    assert os.path.exists(cwd("storage", "binaries", "a"*40))

    cuckoo_clean()

    assert os.path.isdir(cwd("log"))
    assert not os.path.exists(cwd("log", "cuckoo.log"))
    assert os.path.exists(cwd("storage", "analyses"))
    assert not os.path.exists(cwd("storage", "analyses", "1"))
    assert not os.path.exists(cwd("storage", "analyses", "1", "analysis.log"))
    assert os.path.exists(cwd("storage", "baseline"))
    assert os.path.exists(cwd("storage", "binaries"))
    assert not os.path.exists(cwd("storage", "binaries", "a"*40))

@mock.patch("cuckoo.main.Database")
@mock.patch("cuckoo.main.submit_tasks")
def test_submit_unique_with_duplicates(p, q, capsys):
    set_cwd(tempfile.mkdtemp())
    cuckoo_create()

    p.return_value = [
        ("category", "target", 1),
        ("category", "target", None),
    ]

    main.main(
        ("--cwd", cwd(), "submit", "--unique", "a", "b"),
        standalone_mode=False
    )
    out, err = capsys.readouterr()
    assert "added as task with" in out
    assert "Skipped" in out

def test_config_load_once():
    set_cwd(tempfile.mkdtemp())
    cuckoo_create()

    db.connect()
    t0 = submit_task.add_path(__file__)
    t1 = submit_task.add_path(__file__)
    shutil.rmtree(cwd(analysis=t0))
    shutil.rmtree(cwd(analysis=t1))
    shutil.copytree("tests/files/sample_analysis_storage", cwd(analysis=t0))
    shutil.copytree("tests/files/sample_analysis_storage", cwd(analysis=t1))

    with mock.patch("cuckoo.common.config.ConfigParser.ConfigParser") as p:
        process_task_range("%d,%d" % (t0, t1))
        assert p.return_value.read.call_count == 2
        p.return_value.read.assert_any_call(cwd("conf", "processing.conf"))
        p.return_value.read.assert_any_call(cwd("conf", "reporting.conf"))

class TestMigrateCWD(object):
    @mock.patch("shutil.copy")
    def test_up_to_date(self, p):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        migrate_cwd()
        p.assert_not_called()

    @mock.patch("cuckoo.apps.apps.log")
    @mock.patch("shutil.copy")
    def test_modified_file(self, p, q):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        open(cwd("agent", "agent.py"), "wb").write("newer agent")
        with pytest.raises(SystemExit):
            migrate_cwd()
        assert q.error.call_count == 2
        assert "One or more files" in q.error.call_args_list[0][0][0]
        assert q.warning.call_args_list[1][0][1] == "agent/agent.py"
        p.assert_not_called()

    @mock.patch("shutil.copy")
    def test_missing_file(self, p):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()

        # We're going to restore a file that has been removed by the user for
        # one reason or the other, namely, web/local_settings.py.
        os.unlink(cwd("web", "local_settings.py"))

        migrate_cwd()
        p.assert_called_once_with(
            cwd("..", "data", "web/local_settings.py", private=True),
            cwd("web/local_settings.py")
        )

    @mock.patch("cuckoo.apps.apps.hashlib")
    @mock.patch("shutil.copy")
    def test_outdated_file(self, p, q):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()

        # We're going to pretend like web/local_settings.py is outdated by
        # replacing its sha1 by that of its initial version.
        our_buf = open(cwd("web", "local_settings.py"), "rb").read()

        def our_sha1(buf):
            class obj(object):
                def hexdigest(self):
                    return "d90bb80df2ed51d393823438f1975c1075523ec8"
            return obj() if buf == our_buf else hashlib.sha1(buf)

        q.sha1.side_effect = our_sha1
        migrate_cwd()
        p.assert_called_once_with(
            cwd("..", "data", "web/local_settings.py", private=True),
            cwd("web/local_settings.py")
        )

    @mock.patch("cuckoo.apps.apps.hashlib")
    def test_deleted_file(self, p):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()

        def our_sha1(buf):
            class obj(object):
                def hexdigest(self):
                    return "4989ba7ce0dc38709dd125d6c4fac5852914f0c7"
            return obj() if buf == "yes!" else hashlib.sha1(buf)

        p.sha1.side_effect = our_sha1

        open(cwd("analyzer/windows/lib/common/errors.py"), "wb").write("yes!")
        assert os.path.exists(cwd("analyzer/windows/lib/common/errors.py"))
        migrate_cwd()
        assert not os.path.exists(cwd("analyzer/windows/lib/common/errors.py"))

    def test_new_directory(self):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        shutil.rmtree(cwd("yara", "scripts"))
        shutil.rmtree(cwd("yara", "shellcode"))
        shutil.rmtree(cwd("stuff"))
        shutil.rmtree(cwd("whitelist"))
        open(cwd("yara", "index_binaries.yar"), "wb").write("hello")
        migrate_cwd()
        # TODO Move this to its own 2.0.2 -> 2.0.3 migration handler.
        assert os.path.exists(cwd("yara", "scripts", ".gitignore"))
        assert os.path.exists(cwd("yara", "shellcode", ".gitignore"))
        # TODO Move this to its own 2.0.3 -> 2.0.4 migration handler.
        assert os.path.exists(cwd("stuff"))
        assert os.path.exists(cwd("whitelist"))
        assert open(cwd("whitelist", "domain.txt"), "rb").read().strip() == (
            "# You can add whitelisted domains here."
        )
        assert os.path.exists(cwd("yara", "dumpmem"))
        assert not os.path.exists(cwd("yara", "index_binaries.yar"))

    def test_create_missing_dirs(self):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        t1 = submit_task.add_path(__file__)
        t2 = submit_task.add_path(__file__)
        task_dirs = ["shots", "logs", "files", "extracted", "buffer", "memory"]

        shutil.rmtree(cwd(analysis=t1))
        os.rmdir(cwd("logs", analysis=t2))
        assert not os.path.exists(cwd(analysis=t1))
        assert not os.path.exists(cwd("logs", analysis=t2))
        migrate_cwd()
        assert os.path.exists(cwd(analysis=t1))
        assert os.path.exists(cwd(analysis=t2))
        for task in [t1, t2]:
            for dir in task_dirs:
                assert os.path.exists(cwd(dir, analysis=task))

    def test_using_community(self):
        def h(filepath):
            return hashlib.sha1(open(filepath, "rb").read()).hexdigest()

        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        filepath = cwd("signatures", "__init__.py")
        # Old Community version.
        shutil.copy("tests/files/sig-init-old.py", filepath)
        assert h(filepath) == "033e19e4fea1989680f4af19b904448347dd9589"
        migrate_cwd()
        assert h(filepath) == "eaffef3b08fd1069ba2d3c977015b598fa150941"

    def test_current_community(self):
        set_cwd(tempfile.mktemp())
        shutil.copytree(os.path.expanduser("~/.cuckoo"), cwd())
        open(cwd(".cwd"), "wb").write("somethingelse")
        migrate_cwd()

    @pytest.mark.skipif("sys.platform == 'win32'")
    def test_monitor_latest_symlink(self):
        set_cwd(tempfile.mktemp())
        cuckoo_create()
        monitor = open(cwd("monitor", "latest"), "rb").read().strip()
        os.unlink(cwd("monitor", "latest"))
        os.symlink(cwd("monitor", monitor), cwd("monitor", "latest"))
        migrate_cwd()

class TestCommunitySuggestion(object):
    @property
    def ctx(self):
        class context(object):
            log = False
        return context

    @mock.patch("cuckoo.main.green")
    def test_default_cwd(self, p):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        with chdir(cwd()):
            decide_cwd(".")
            cuckoo_init(logging.INFO, self.ctx)
            p.assert_called_once_with("cuckoo community")

    @mock.patch("cuckoo.main.green")
    def test_hardcoded_cwd(self, p):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        decide_cwd(cwd())
        cuckoo_init(logging.INFO, self.ctx)
        p.assert_called_once_with("cuckoo --cwd %s community" % cwd())

    @mock.patch("cuckoo.main.green")
    def test_hardcoded_cwd_with_space(self, p):
        set_cwd(tempfile.mkdtemp("foo bar"))
        cuckoo_create()
        decide_cwd(cwd())
        cuckoo_init(logging.INFO, self.ctx)
        p.assert_called_once_with('cuckoo --cwd "%s" community' % cwd())

    @mock.patch("cuckoo.main.green")
    def test_hardcoded_cwd_with_quote(self, p):
        set_cwd(tempfile.mkdtemp("foo ' bar"))
        cuckoo_create()
        decide_cwd(cwd())
        cuckoo_init(logging.INFO, self.ctx)
        p.assert_called_once_with('cuckoo --cwd "%s" community' % cwd())

    @mock.patch("cuckoo.main.green")
    def test_has_signatures(self, p):
        set_cwd(tempfile.mkdtemp())
        sys.modules.pop("signatures", None)
        sys.modules.pop("signatures.android", None)
        sys.modules.pop("signatures.cross", None)
        sys.modules.pop("signatures.darwin", None)
        sys.modules.pop("signatures.extractor", None)
        sys.modules.pop("signatures.linux", None)
        sys.modules.pop("signatures.network", None)
        sys.modules.pop("signatures.windows", None)
        cuckoo_create()
        shutil.copy(
            "tests/files/enumplugins/sig1.py",
            cwd("signatures", "windows", "foobar.py")
        )
        cuckoo.signatures = []
        cuckoo_init(logging.INFO, self.ctx)
        p.assert_not_called()
