# Copyright (C) 2016-2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import Queue
import mock
import os
import pytest
import shutil
import tempfile
import threading

from cuckoo.analysis.regular import Regular
from cuckoo.common import config
from cuckoo.common.exceptions import CuckooCriticalError
from cuckoo.core.database import Database
from cuckoo.core.init import write_cuckoo_conf
from cuckoo.core.scheduler import Scheduler
from cuckoo.core.task import Task
from cuckoo.machinery.virtualbox import VirtualBox
from cuckoo.main import cuckoo_create
from cuckoo.misc import set_cwd

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

class FakeTask(object):
    def __init__(self, id):
        self.id = id
        self.category = "file"
        self.sample_id = 2
        self.status = "pending"
        self.platform = "windows"
        self.tags = ""
        self.machine = ""

class TestScheduler:

    def setup_class(self):
        self.cwd = tempfile.mkdtemp()
        set_cwd(self.cwd)
        cuckoo_create()
        self.db = Database()
        self.db.connect()

    def teardown_class(self):
        if os.path.isdir(self.cwd):
            shutil.rmtree(self.cwd)

    @mock.patch("cuckoo.common.abstracts.Machinery.initialize")
    @mock.patch("cuckoo.common.abstracts.Machinery.machines")
    def test_initialize(self, mm, mi):
        mm.return_value = ["m1"]
        s = Scheduler(10)
        s.drop_forwarding_rules = mock.MagicMock()

        s.initialize()

        mi.assert_called_once()
        mm.assert_called_once()
        assert isinstance(s.machine_lock, type(threading.Semaphore()))
        assert isinstance(s.machinery, VirtualBox)
        s.drop_forwarding_rules.assert_called_once()
        assert isinstance(s.error_queue, Queue.Queue)


    @mock.patch("cuckoo.common.abstracts.Machinery.initialize")
    def test_initialize_no_machines(self, mi):
        s = Scheduler(10)

        with pytest.raises(CuckooCriticalError):
            s.initialize()

    def test_stop(self):
        s = Scheduler()
        s.machinery = mock.MagicMock()
        s.stop()

        assert not s.running
        s.machinery.shutdown.assert_called_once()

    @mock.patch("cuckoo.core.scheduler.rooter")
    def test_drop_forwarding_rules(self, mr):
        write_cuckoo_conf(cfg={
            "routing": {
                "routing": {
                    "internet": "eth0"
                },
                "vpn": {
                    "enabled": "yes"
                }
            }
        })
        # Clear config cache so it will load new values
        config._cache = {}
        s = Scheduler()
        s.machinery = mock.MagicMock()
        s.machinery.machines.return_value = [Machine()]
        s.drop_forwarding_rules()

        mr.assert_has_calls([
            mock.call("forward_disable", "tap0", "tun0", "192.168.56.10"),
            mock.call("forward_disable", "tap0", "eth0", "192.168.56.10")
        ])

    @mock.patch("cuckoo.core.scheduler.get_free_disk")
    def test_ready_for_new_run(self, mfd):
        mfd.return_value = 10000
        s = Scheduler()
        Scheduler.machine_lock = mock.MagicMock()
        s.machinery = mock.MagicMock()
        s.machinery.availables.return_value = [Machine()]

        result = s.ready_for_new_run()

        assert result
        s.machine_lock.acquire.assert_called_once_with(False)
        s.machine_lock.release.assert_called_once()
        mfd.assert_called_once()
        s.machinery.availables.assert_called_once()

    @mock.patch("cuckoo.core.scheduler.get_free_disk")
    def test_ready_for_new_run_no_space(self, mfd):
        mfd.return_value = 1
        s = Scheduler()
        Scheduler.machine_lock = mock.MagicMock()
        s.machinery = mock.MagicMock()
        s.machinery.availables.return_value = [Machine()]

        result = s.ready_for_new_run()

        assert not result
        s.machine_lock.acquire.assert_called_once_with(False)
        s.machine_lock.release.assert_called_once()
        mfd.assert_called_once()

    @mock.patch("cuckoo.core.scheduler.get_free_disk")
    def test_ready_for_new_run_maxcount(self, mfd):
        mfd.return_value = 10000
        s = Scheduler(10)
        s.stop = mock.MagicMock()
        s.total_analysis_count = 10
        Scheduler.machine_lock = mock.MagicMock()
        s.machinery = mock.MagicMock()
        s.machinery.availables.return_value = [Machine()]

        result = s.ready_for_new_run()

        assert not result
        s.machine_lock.acquire.assert_called_once_with(False)
        s.machine_lock.release.assert_called_once()
        mfd.assert_called_once()
        s.stop.assert_called_once()

    @mock.patch("cuckoo.core.scheduler.get_free_disk")
    def test_ready_for_new_run_maxcount2(self, mfd):
        mfd.return_value = 10000
        s = Scheduler(10)
        # Scheduler should not stop if max is reached and there are still
        # running analyses
        s.managers.append(mock.MagicMock())
        s.stop = mock.MagicMock()
        s.total_analysis_count = 10
        Scheduler.machine_lock = mock.MagicMock()
        s.machinery = mock.MagicMock()
        s.machinery.availables.return_value = [Machine()]

        result = s.ready_for_new_run()

        assert not result
        s.machine_lock.acquire.assert_called_once_with(False)
        s.machine_lock.release.assert_called_once()
        mfd.assert_called_once()
        s.stop.assert_not_called()

    @mock.patch("cuckoo.core.scheduler.get_free_disk")
    def test_ready_for_new_run_max_running(self, mfd):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create(cfg={
            "cuckoo": {
                "cuckoo": {
                    "max_machines_count": 1
                }
            }
        })
        Database().connect()
        mfd.return_value = 10000
        s = Scheduler()
        Scheduler.machine_lock = mock.MagicMock()
        s.machinery = mock.MagicMock()
        s.machinery.running.return_value = [Machine(), Machine()]

        result = s.ready_for_new_run()

        assert not result
        s.machine_lock.acquire.assert_called_once_with(False)
        s.machine_lock.release.assert_called_once()
        mfd.assert_called_once()
        s.machinery.availables.assert_not_called()

    @mock.patch("cuckoo.core.scheduler.get_free_disk")
    def test_ready_for_new_run_noavailbles(self, mfd):
        mfd.return_value = 10000
        s = Scheduler()
        Scheduler.machine_lock = mock.MagicMock()
        s.machinery = mock.MagicMock()
        s.machinery.availables.return_value = []

        result = s.ready_for_new_run()

        assert not result
        s.machine_lock.acquire.assert_called_once_with(False)
        s.machine_lock.release.assert_called_once()
        mfd.assert_called_once()
        s.machinery.availables.assert_called_once()

    def test_handle_pending_service(self):
        # Test starting a task with service VM
        s = Scheduler()
        s.db = mock.MagicMock()
        s.db.get_available_machines.return_value = [Machine()]
        s.machinery = mock.MagicMock()
        task = FakeTask(1)
        s.db.fetch.return_value = task
        machine_mock2 = mock.MagicMock()
        s.machinery.acquire.return_value = machine_mock2
        Scheduler.machine_lock = mock.MagicMock()
        analyis_manager = mock.MagicMock()
        s.get_analysis_manager = mock.MagicMock(return_value=analyis_manager)

        s.handle_pending()

        s.machine_lock.acquire.assert_called_once_with(False)
        s.get_analysis_manager.assert_called_once_with(task, machine_mock2)
        s.db.set_status.assert_called_once_with(1, "running")
        assert s.total_analysis_count == 1
        analyis_manager.init.assert_called_once()
        analyis_manager.start.assert_called_once()

    def test_handle_pending_task(self):
        # Test finding and starting a task with machine
        s = Scheduler()
        s.db = mock.MagicMock()
        mock_machine1 = mock.MagicMock()
        s.db.get_available_machines.return_value = [mock_machine1]
        s.machinery = mock.MagicMock()
        task = FakeTask(1)
        s.db.fetch.side_effect = [None, task]
        machine_mock2 = mock.MagicMock()
        s.machinery.acquire.return_value = machine_mock2
        Scheduler.machine_lock = mock.MagicMock()
        analyis_manager = mock.MagicMock()
        s.get_analysis_manager = mock.MagicMock(return_value=analyis_manager)

        s.handle_pending()

        s.machine_lock.acquire.assert_called_once_with(False)
        mock_machine1.is_analysis.assert_called_once()
        s.db.fetch.assert_has_calls([
            mock.call(machine=mock.ANY, lock=False),
            mock.call(service=False, lock=False, exclude=[])
        ])
        s.get_analysis_manager.assert_called_once_with(task, machine_mock2)
        s.db.set_status.assert_called_once_with(1, "running")
        assert s.total_analysis_count == 1
        analyis_manager.init.assert_called_once()
        analyis_manager.start.assert_called_once()

    def test_handle_pending_task_exclude(self):
        # Test starting task with machine after first excluding 1 task
        # because not machine for it is available
        s = Scheduler()
        s.db = mock.MagicMock()
        mock_machine1 = mock.MagicMock()
        s.db.get_available_machines.return_value = [mock_machine1]
        s.machinery = mock.MagicMock()
        task2 = FakeTask(2)
        s.db.fetch.side_effect = [None, FakeTask(1), task2]
        machine_mock2 = mock.MagicMock()
        s.machinery.acquire.side_effect = [None, machine_mock2]
        Scheduler.machine_lock = mock.MagicMock()
        analyis_manager = mock.MagicMock()
        s.get_analysis_manager = mock.MagicMock(return_value=analyis_manager)

        s.handle_pending()

        s.machine_lock.acquire.assert_called_once_with(False)
        mock_machine1.is_analysis.assert_called_once()
        s.db.fetch.assert_has_calls([
            mock.call(machine=mock.ANY, lock=False),
            mock.call(service=False, lock=False, exclude=mock.ANY),
            mock.call(service=False, lock=False, exclude=[1])
        ])
        s.get_analysis_manager.assert_called_once_with(task2, machine_mock2)
        s.db.set_status.assert_called_once_with(2, "running")
        assert s.total_analysis_count == 1
        analyis_manager.init.assert_called_once()
        analyis_manager.start.assert_called_once()

    def test_handle_pending_no_tasks(self):
        # No tasks, release lock
        s = Scheduler()
        s.db = mock.MagicMock()
        mock_machine1 = mock.MagicMock()
        s.db.get_available_machines.return_value = [mock_machine1]
        s.machinery = mock.MagicMock()
        task2 = FakeTask(2)
        s.db.fetch.side_effect = [None, None]
        Scheduler.machine_lock = mock.MagicMock()
        analyis_manager = mock.MagicMock()
        s.get_analysis_manager = mock.MagicMock(return_value=analyis_manager)

        s.handle_pending()

        s.machine_lock.acquire.assert_called_once_with(False)
        mock_machine1.is_analysis.assert_called_once()
        s.db.fetch.assert_has_calls([
            mock.call(machine=mock.ANY, lock=False),
            mock.call(service=False, lock=False, exclude=mock.ANY)
        ])
        assert s.total_analysis_count == 0
        s.machine_lock.release.assert_called_once()

    def test_get_analysis_manager(self):
        s = Scheduler()
        task = Task()
        task.add_path(__file__)
        manager = s.get_analysis_manager(task.db_task, Machine())

        assert isinstance(manager, Regular)

    def test_get_analysis_manager_unsupportedcategory(self):
        s = Scheduler()
        id = self.db.add("http://example.com/42", category="DOGE")
        db_task = self.db.view_task(id)
        manager = s.get_analysis_manager(db_task, Machine())

        assert manager is None

    def test_handle_managers(self):
        s = Scheduler()
        manager = mock.MagicMock()
        manager.get_analysis_status.return_value = "stopped"
        manager.on_status_stopped = mock.MagicMock()
        manager.isAlive.return_value = False
        s.managers.append(manager)

        result = s.handle_managers()

        assert result == [manager]
        manager.action_requested.assert_called_once()
        manager.get_analysis_status.assert_called_once()
        manager.on_status_stopped.assert_called_once_with(s.db)
        manager.release_locks.assert_called_once()
        manager.isAlive.assert_called_once()
        manager.finalize.assert_called_once_with(s.db)

    def test_handle_managers_stillalive(self):
        s = Scheduler()
        manager = mock.MagicMock()
        manager.get_analysis_status.return_value = "stopped"
        manager.on_status_stopped = mock.MagicMock()
        s.managers.append(manager)

        result = s.handle_managers()

        assert result == []
        manager.action_requested.assert_called_once()
        manager.get_analysis_status.assert_called_once()
        manager.on_status_stopped.assert_called_once_with(s.db)
        manager.release_locks.assert_called_once()
        manager.isAlive.assert_called_once()
        manager.finalize.assert_not_called()

    def test_handle_managers_incorrect_status(self):
        s = Scheduler()
        manager = mock.MagicMock()
        # The method is not mocked return
        manager.get_analysis_status.return_value = "doge"
        manager.on_status_doge = None
        s.managers.append(manager)

        result = s.handle_managers()

        assert result == []
        manager.action_requested.assert_called_once()
        manager.get_analysis_status.assert_called_once()
        manager.release_locks.assert_called_once()
        manager.isAlive.assert_called_once()
        manager.finalize.assert_not_called()

    @mock.patch("time.sleep")
    def test_start(self, mts):
        s = Scheduler()
        s.initialize = mock.MagicMock()
        s.db = mock.MagicMock()
        s.db.count_tasks.return_value = 1
        s.ready_for_new_run = mock.MagicMock()
        s.handle_pending = mock.MagicMock()
        s.handle_managers = mock.MagicMock()
        s.error_queue = Queue.Queue()
        s.error_queue.put(OSError)

        # Catch this error to escape the scheduler loop
        try:
            s.start()
        except OSError:
            pass

        mts.assert_called_once()
        s.db.count_tasks.assert_called_once_with(status="pending")
        s.ready_for_new_run.assert_called_once()
        s.handle_pending.assert_called_once()
        s.handle_managers.assert_called_once()
