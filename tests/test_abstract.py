# Copyright (C) 2016-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import mock
import os
import pytest
import shutil
import tempfile

from cuckoo.common import abstracts
from cuckoo.common import config
from cuckoo.common.objects import Analysis
from cuckoo.core.database import Database
from cuckoo.core.init import write_cuckoo_conf
from cuckoo.core.task import Task
from cuckoo.main import cuckoo_create
from cuckoo.misc import set_cwd

class TestProcessing(object):
    def setup(self):
        self.p = abstracts.Processing()

    def test_not_implemented_run(self):
        with pytest.raises(NotImplementedError):
            self.p.run()

class TestReport(object):
    def setup(self):
        self.r = abstracts.Report()

    def test_set_path(self):
        dir = tempfile.mkdtemp()
        rep_dir = os.path.join(dir, "reports")
        self.r.set_path(dir)
        assert os.path.exists(rep_dir)
        os.rmdir(rep_dir)

    def test_options_none(self):
        assert self.r.options is None

    def test_set_options_assignment(self):
        foo = {1: 2}
        self.r.set_options(foo)
        assert foo == self.r.options

    def test_not_implemented_run(self):
        with pytest.raises(NotImplementedError):
            self.r.run({})

class TestConfiguration(object):
    def test_simple(self):
        c = abstracts.Configuration()

        c.add({
            "family": "a", "url": "b", "type": "c",
        })
        assert c.results() == [{
            "family": "a", "url": ["b"], "type": "c",
        }]

        c.add({
            "family": "a", "url": ["d", None],
        })
        assert c.results() == [{
            "family": "a", "type": "c", "url": ["b", "d"],
        }]

        c.add({
            "family": "a", "version": 42,
        })
        assert c.results() == [{
            "family": "a", "type": "c", "version": 42, "url": ["b", "d"],
        }]

        c.add({
            "family": "b", "type": "c",
        })
        assert c.results() == [{
            "family": "a", "type": "c", "version": 42, "url": ["b", "d"],
        }, {
            "family": "b", "type": "c",
        }]

        c = abstracts.Configuration()
        c.add({
            "family": "a", "randomkey": "hello", "rc4key": "x",
        })
        assert c.results() == [{
            "family": "a",
            "key": {
                "rc4key": ["x"],
            },
            "extra": {
                "randomkey": ["hello"],
            }
        }]

        c.add({
            "family": "a", "rc4key": "x", "key": "y", "randomkey": "hello",
            "cnc": ["1", "2", ""],
        })
        assert c.results() == [{
            "family": "a",
            "key": {
                "rc4key": ["x"],
            },
            "cnc": ["1", "2"],
            "extra": {
                "randomkey": ["hello"],
                "key": ["y"],
            },
        }]

class FakeMachine(object):
    def __init__(self):
        self.name = "machine1"
        self.label = "machine1"
        self.ip = "192.168.56.10"
        self.platform = "windows"
        self.options = ""
        self.interface = "tap0"
        self.snapshot = ""
        self.resultserver_ip = "192.168.56.1"
        self.resultserver_port = 4242
        self.manager = "virtualbox"
        self.locked = True

class TestAnalysisManager(object):
    def setup_class(self):
        self.cwd = tempfile.mkdtemp()
        set_cwd(self.cwd)
        cuckoo_create()
        self.db = Database()
        self.db.connect()

    def teardown_class(self):
        if os.path.isdir(self.cwd):
            shutil.rmtree(self.cwd)

    def test_set_task(self):
        task = Task()
        task.add_path(__file__)
        sample = self.db.view_sample(task.sample_id)
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )

        a.set_task(task, sample)

        assert a.task == task
        assert a.sample == sample
        assert isinstance(a.analysis, Analysis)
        assert a.name == "task_#%s_AnalysisManager" % task.id

    def test_build_options(self):
        task = Task()
        task.add_path(__file__, options={"free": "yes"})
        sample = self.db.view_sample(task.sample_id)
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        a.set_task(task, sample)

        expected = {
            "category": "file",
            "clock": task.clock,
            "enforce_timeout": False,
            "id": task.id,
            "package": "",
            "target": __file__,
            "terminate_processes": False,
            "ip": "192.168.56.1",
            "port": 4242,
            "timeout": 120,
            "options": "free=yes"
        }

        assert a.options == {}
        a.build_options()
        assert a.options == expected
        a.build_options({
            "file_name": "doge.py",
            "options": {"doges": "many"}
        })
        assert a.options["options"] == "doges=many,free=yes"
        assert a.options["file_name"] == "doge.py"
        assert a.options["category"] == "file"

    @mock.patch("time.sleep")
    def test_wait_finish(self, mts):
        task = Task()
        task.add_url("http://example.com/42")
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        a.set_task(task)
        a.analysis.status = "stoppped"
        a.wait_finish()
        mts.assert_not_called()

    def test_request_scheduler_action(self):
        task = Task()
        task.add_url("http://example.com/42")
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        a.set_task(task)
        a.action_lock = mock.MagicMock()
        a.action_lock.locked = mock.MagicMock(return_value=False)

        a.request_scheduler_action()

        a.action_lock.locked.assert_called_once()
        a.action_lock.acquire.assert_has_calls([
            mock.call(False),
            mock.call(True)
        ])
        a.action_lock.release.assert_called_once()
        assert a.override_status is None

    def test_set_analysis_status(self):
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        a.analysis = mock.MagicMock()
        a.request_scheduler_action = mock.MagicMock()
        a.set_analysis_status("starting")

        a.analysis.set_status.assert_called_once_with("starting")
        a.request_scheduler_action.assert_not_called()

    def test_set_analysis_status_request(self):
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        a.analysis = mock.MagicMock()
        a.request_scheduler_action = mock.MagicMock()

        a.set_analysis_status("starting", wait=True)

        a.analysis.status_lock.acquire.assert_called_once()
        a.analysis.set_status.assert_called_once_with(
            "starting", use_lock=False
        )
        a.request_scheduler_action.assert_called_once()

    def test_release_locks(self):
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        a.analysis = mock.MagicMock()
        a.analysis.status_lock.locked = mock.MagicMock(return_value=True)
        a.action_lock = mock.MagicMock()

        a.release_locks()

        a.analysis.status_lock.locked.assert_called_once()
        a.analysis.status_lock.release.assert_called_once()
        a.action_lock.release.assert_called_once()

    def test_action_requested(self):
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        a.analysis = mock.MagicMock()
        a.action_lock = mock.MagicMock()
        a.action_lock.locked = mock.MagicMock(return_value=True)
        a.analysis.changed = True

        assert a.action_requested()

    def test_get_analysis_status(self):
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        a.analysis = mock.MagicMock()
        a.analysis.get_status = mock.MagicMock(return_value="starting")

        assert a.get_analysis_status() == "starting"

    def test_get_analysis_status_overriden(self):
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        a.analysis = mock.MagicMock()
        a.override_status = "stopping"
        a.analysis.get_status = mock.MagicMock(return_value="starting")

        assert a.get_analysis_status() == "stopping"

    def test_init(self):
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )

        assert a.init(self.db)

    def test_run(self):
        a = abstracts.AnalysisManager(
            FakeMachine(), mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        )
        with pytest.raises(NotImplementedError):
            a.run()
