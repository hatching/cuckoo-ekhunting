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

class Machine(object):
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

class TestAnalysisManager:
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
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())

        a.set_task(task, sample)

        assert a.task == task
        assert a.sample == sample
        assert isinstance(a.analysis, Analysis)
        assert a.name == "Task_#%s_AnalysisManager_Thread" % task.id

    def test_file_usable(self):
        task = Task()
        fd, fpath = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        task.add_path(fpath)
        sample = self.db.view_sample(task.sample_id)
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task, sample)

        normal = a.file_usable()
        a.file = None
        # Change file to trigger error
        os.write(fd, os.urandom(32))
        modified = a.file_usable()
        # Make unreadable to trigger error
        os.chmod(fpath, 0000)
        unreadable = a.file_usable()
        assert normal
        assert not modified
        assert not unreadable

    def test_build_options(self):
        task = Task()
        task.add_path(__file__, options={"free": "yes"})
        sample = self.db.view_sample(task.sample_id)
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
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

    @mock.patch("cuckoo.core.rooter.rooter")
    def test_route_network_none(self, mr):
        task = Task()
        task.add_url("http://example.com/42", options={"route": "none"})
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route_network()

        assert a.route == "none"
        assert a.interface is None
        assert a.rt_table is None
        mr.assert_not_called()

    @mock.patch("cuckoo.common.abstracts.rooter")
    def test_route_network_inetsim(self, mr):
        task = Task()
        task.add_url("http://example.com/42", options={"route": "inetsim"})
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route_network()

        assert a.route == "inetsim"
        assert a.interface is None
        assert a.rt_table is None
        mr.assert_called_once_with(
            "inetsim_enable", "192.168.56.10", "192.168.56.1",
            "vboxnet0", "2042"
        )

    @mock.patch("cuckoo.common.abstracts.rooter")
    def test_route_network_internet(self, mr):
        write_cuckoo_conf(cfg={
            "routing": {
                "routing": {
                    "internet": "eth0"
                }
            }
        })
        # Clear config cache so it will load new values
        config._cache = {}

        mr.return_value = True
        task = Task()
        task.add_url("http://example.com/42", options={"route": "internet"})
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route_network()

        assert a.route == "internet"
        assert a.interface == "eth0"
        assert a.rt_table == "main"
        mr.assert_has_calls([
            mock.call("nic_available", "eth0"),
            mock.call("drop_enable", "192.168.56.10", "192.168.56.1", "2042"),
            mock.call("forward_enable", "tap0", "eth0", "192.168.56.10"),
            mock.call("srcroute_enable", "main", "192.168.56.10")
        ])

    @mock.patch("cuckoo.common.abstracts.rooter")
    def test_route_network_tor(self, mr):
        task = Task()
        task.add_url("http://example.com/42", options={"route": "tor"})
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route_network()

        assert a.route == "tor"
        assert a.interface is None
        assert a.rt_table is None
        mr.assert_called_once_with(
            "tor_enable", "192.168.56.10", "192.168.56.1", "5353", "9040"
        )

    @mock.patch("cuckoo.common.abstracts.rooter")
    def test_route_network_drop(self, mr):
        task = Task()
        task.add_url("http://example.com/42", options={"route": "drop"})
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route_network()

        assert a.route == "drop"
        assert a.interface is None
        assert a.rt_table is None
        mr.assert_called_once_with(
            "drop_enable", "192.168.56.10", "192.168.56.1", "2042"
        )

    @mock.patch("cuckoo.common.abstracts.rooter")
    def test_route_network_vpn(self, mr):
        mr.return_value = True
        task = Task()
        task.add_url("http://example.com/42", options={"route": "vpn0"})
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route_network()

        assert a.route == "vpn0"
        assert a.interface == "tun0"
        assert a.rt_table == "tun0"
        mr.assert_has_calls([
            mock.call("nic_available", "tun0"),
            mock.call("forward_enable", "tap0", "tun0", "192.168.56.10"),
            mock.call("srcroute_enable", "tun0", "192.168.56.10")
        ])

    @mock.patch("cuckoo.common.abstracts.rooter")
    def test_unroute_network_none(self, mr):
        task = Task()
        task.add_url("http://example.com/42")
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route = "none"
        a.unroute_network()

        mr.assert_not_called()

    @mock.patch("cuckoo.common.abstracts.rooter")
    def test_unroute_network_vpn(self, mr):
        task = Task()
        task.add_url("http://example.com/42")
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route = "vpn0"
        a.rt_table = "tun0"
        a.interface = "tun0"
        a.unroute_network()

        mr.assert_has_calls([
            mock.call("forward_disable", "tap0", "tun0", "192.168.56.10"),
            mock.call("srcroute_disable", "tun0", "192.168.56.10"),
            mock.call("drop_disable", "192.168.56.10", "192.168.56.1", "2042")
        ])

    @mock.patch("cuckoo.common.abstracts.rooter")
    def test_unroute_network_inetsim(self, mr):
        task = Task()
        task.add_url("http://example.com/42")
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route = "inetsim"
        a.unroute_network()

        mr.assert_has_calls([
            mock.call("drop_disable", "192.168.56.10", "192.168.56.1", "2042"),
            mock.call(
                "inetsim_disable", "192.168.56.10", "192.168.56.1", "vboxnet0",
                 "2042"
            )
        ])

    @mock.patch("cuckoo.common.abstracts.rooter")
    def test_unroute_network_tor(self, mr):
        task = Task()
        task.add_url("http://example.com/42")
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.route = "tor"
        a.unroute_network()

        mr.assert_has_calls([
            mock.call("drop_disable", "192.168.56.10", "192.168.56.1", "2042"),
            mock.call(
                "tor_disable", "192.168.56.10", "192.168.56.1", "5353", "9040"
            )
        ])

    @mock.patch("time.sleep")
    def test_wait_finish(self, mts):
        task = Task()
        task.add_url("http://example.com/42")
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.set_task(task)
        a.analysis.status = "stoppped"
        a.wait_finish()
        mts.assert_not_called()

    def test_request_scheduler_action(self):
        task = Task()
        task.add_url("http://example.com/42")
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
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
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.analysis = mock.MagicMock()
        a.request_scheduler_action = mock.MagicMock()
        a.set_analysis_status("starting")

        a.analysis.set_status.assert_called_once_with("starting")
        a.request_scheduler_action.assert_not_called()

    def test_set_analysis_status_request(self):
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.analysis = mock.MagicMock()
        a.request_scheduler_action = mock.MagicMock()

        a.set_analysis_status("starting", request_scheduler_action=True)

        a.analysis.status_lock.acquire.assert_called_once()
        a.analysis.set_status.assert_called_once_with(
            "starting", use_lock=False
        )
        a.request_scheduler_action.assert_called_once()

    def test_release_locks(self):
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.analysis = mock.MagicMock()
        a.analysis.status_lock.locked = mock.MagicMock(return_value=True)
        a.action_lock = mock.MagicMock()

        a.release_locks()

        a.analysis.status_lock.locked.assert_called_once()
        a.analysis.status_lock.release.assert_called_once()
        a.action_lock.release.assert_called_once()

    def test_action_requested(self):
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.analysis = mock.MagicMock()
        a.action_lock = mock.MagicMock()
        a.action_lock.locked = mock.MagicMock(return_value=True)
        a.analysis.changed = True

        assert a.action_requested()

    def test_get_analysis_status(self):
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.analysis = mock.MagicMock()
        a.analysis.get_status = mock.MagicMock(return_value="starting")

        assert a.get_analysis_status() == "starting"

    def test_get_analysis_status_overriden(self):
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        a.analysis = mock.MagicMock()
        a.override_status = "stopping"
        a.analysis.get_status = mock.MagicMock(return_value="starting")

        assert a.get_analysis_status() == "stopping"

    def test_init(self):
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())

        assert a.init(self.db)

    def test_run(self):
        a = abstracts.AnalysisManager(Machine(), mock.MagicMock(),
                                      mock.MagicMock())
        with pytest.raises(NotImplementedError):
            a.run()
