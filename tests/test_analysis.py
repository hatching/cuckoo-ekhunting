# Copyright (C) 2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import mock
import os
import pytest
import shutil
import tempfile

from cuckoo.analysis.taskanalysis import TaskAnalysis
from cuckoo.common.objects import File
from cuckoo.core.database import Database
from cuckoo.core.guest import GuestManager
from cuckoo.core.plugins import RunAuxiliary
from cuckoo.core.task import Task
from cuckoo.main import cuckoo_create
from cuckoo.misc import set_cwd, cwd

class Machine(object):
    def __init__(self):
        self.name = "machine1"
        self.label = "machine1"
        self.ip = "192.168.56.10"
        self.platform = "windows"
        self.options = ""
        self.interface = "vboxnet0"
        self.snapshot = ""
        self.resultserver_ip = "192.168.56.1"
        self.resultserver_port = 4242
        self.manager = "virtualbox"
        self.locked = True

class TestTaskAnalysis:
    def setup_class(self):
        self.cwd = tempfile.mkdtemp()
        set_cwd(self.cwd)
        cuckoo_create()

    def teardown_class(self):
        if os.path.isdir(self.cwd):
            shutil.rmtree(self.cwd)

    def setup(self):
        self.db = Database()
        self.db.connect()

    def get_manager(self, task=None):
        sample = None
        if task is None:
            task = Task()
            task.add_path(__file__)
        if task.category == "file" or task.category == "archive":
            sample = self.db.view_sample(task.sample_id)

        manager = TaskAnalysis(Machine(), mock.MagicMock(), mock.MagicMock())
        manager.set_task(task, sample)
        return manager

    def test_set_task(self):
        task = Task()
        task.add_path(__file__)
        manager = self.get_manager()
        manager.set_task(task)

        assert manager.task == task
        assert manager.analysis is not None
        assert manager.name == "Task_#%s_TaskAnalysis_Thread" % task.id


    @mock.patch("cuckoo.common.abstracts.AnalysisManager.file_usable")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.build_options")
    def test_init(self, mb, mf):
        manager = self.get_manager()
        result = manager.init(self.db)

        mb.assert_called_once_with(update_with={
            "file_type": "Python script, ASCII text executable,"
                         " with CRLF line terminators",
            "file_name": "test_analysis.py",
            "target": "/home/ricardo/scheduler/cuckoo-internal"
                      "/tests/test_analysis.py",
            "pe_exports": "",
            "options": {}
        })

        mf.assert_called_once()
        assert result
        assert manager.file is not None
        assert isinstance(manager.guest_manager, GuestManager)
        assert isinstance(manager.aux, RunAuxiliary)
        assert os.path.isfile(os.path.join(manager.task.path, "task.json"))

    @mock.patch("cuckoo.common.abstracts.AnalysisManager.file_usable")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.build_options")
    @mock.patch("cuckoo.analysis.taskanalysis.File.get_apk_entry")
    def test_init_apk_options(self, mae, mb, mf):
        manager = self.get_manager()
        mae.return_value= ("package", "activity")
        result = manager.init(self.db)

        mb.assert_called_once_with(update_with={
            "file_type": "Python script, ASCII text executable,"
                         " with CRLF line terminators",
            "file_name": "test_analysis.py",
            "target": "/home/ricardo/scheduler/cuckoo-internal"
                      "/tests/test_analysis.py",
            "pe_exports": "",
            "options": {"apk_entry": "package:activity"}
        })

        mf.assert_called_once()
        assert result
        assert manager.file is not None
        assert isinstance(manager.guest_manager, GuestManager)
        assert isinstance(manager.aux, RunAuxiliary)
        assert os.path.isfile(os.path.join(manager.task.path, "task.json"))

    @mock.patch("cuckoo.common.abstracts.AnalysisManager.file_usable")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.build_options")
    def test_init_non_file(self, mb, mf):
        task = Task()
        task.add_url("http://example.com/42")
        manager = self.get_manager(task)

        result = manager.init(self.db)
        mb.assert_called_once()
        mf.assert_not_called()
        assert result
        assert manager.file is None
        assert isinstance(manager.guest_manager, GuestManager)
        assert isinstance(manager.aux, RunAuxiliary)
        assert os.path.isfile(os.path.join(task.path, "task.json"))

    def test_init_use_bin_copy(self):
        task = Task()
        fd, tmpfile = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        task.add_path(tmpfile)
        tmpfile_obj = File(tmpfile)
        tmpfile_obj.calc_hashes()
        manager = self.get_manager(task)

        # Remove so init fails to find the original target
        os.remove(tmpfile)
        copy_path = cwd("storage", "binaries", tmpfile_obj.get_sha256())

        result = manager.init(self.db)
        assert result
        assert manager.file is not None
        assert manager.options["target"] == copy_path
        assert manager.options["file_name"] == tmpfile_obj.get_name()
        assert isinstance(manager.guest_manager, GuestManager)
        assert isinstance(manager.aux, RunAuxiliary)
        assert os.path.isfile(os.path.join(task.path, "task.json"))

    def test_init_fail(self):
        task = Task()
        fd, tmpfile = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        task.add_path(tmpfile)
        manager = self.get_manager(task)
        copy_path = cwd("storage", "binaries", File(tmpfile).get_sha256())

        # Remove both binaries to make init fail
        os.remove(copy_path)
        os.remove(tmpfile)
        result = manager.init(self.db)

        assert not result
        assert os.path.isfile(os.path.join(task.path, "task.json"))

    @mock.patch("cuckoo.analysis.taskanalysis.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.route_network")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager."
                "request_scheduler_action")
    @mock.patch("cuckoo.core.scheduler.Scheduler.machine_lock")
    def test_start_analysis(self, mml, mrsa, msas, mrn, mrs):
        manager = self.get_manager()
        # Mock resultserver obj so we can check if add_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj

        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.aux = mock.MagicMock()
        manager.guest_manager = mock.MagicMock()
        # Set status manually, because the method used is mocked
        manager.analysis.status = "starting"

        result = manager.start_analysis()

        # Check if all required methods were called successfully
        msas.assert_has_calls([
            mock.call("starting"), mock.call("running")
        ])
        resulserver_obj.add_task.assert_called_once_with(manager.task.db_task,
                                             manager.machine)
        manager.aux.start.assert_called_once()
        manager.machinery.start.assert_called_once_with("machine1",
                                                        manager.task.db_task)
        mrn.assert_called_once()
        mml.release.assert_called_once()
        mrsa.assert_called_once_with(for_status="starting")
        manager.guest_manager.start_analysis.assert_called_once()
        manager.guest_manager.wait_for_completion.assert_called_once()
        assert result

    @mock.patch("cuckoo.analysis.taskanalysis.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.route_network")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager."
                "request_scheduler_action")
    @mock.patch("cuckoo.core.scheduler.Scheduler.machine_lock")
    def test_start_analysis_url(self, mml, mrsa, msas, mrn, mrs):
        task = Task()
        task.add_url("http://example.com/42")

        # Mock resultserver obj so we can check if add_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj

        manager = self.get_manager(task)
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.aux = mock.MagicMock()
        manager.guest_manager = mock.MagicMock()
        # Set status manually, because the method used is mocked
        manager.analysis.status = "starting"

        result = manager.start_analysis()

        # Check if all required methods were called successfully
        msas.assert_has_calls([
            mock.call("starting"), mock.call("running")
        ])
        resulserver_obj.add_task.assert_called_once_with(task.db_task,
                                             manager.machine)
        manager.aux.start.assert_called_once()
        manager.machinery.start.assert_called_once_with("machine1",
                                                        task.db_task)
        mrn.assert_called_once()
        mml.release.assert_called_once()
        mrsa.assert_called_once_with(for_status="starting")
        manager.guest_manager.start_analysis.assert_called_once()
        manager.guest_manager.wait_for_completion.assert_called_once()
        assert result

    @mock.patch("cuckoo.analysis.taskanalysis.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.route_network")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager."
                "request_scheduler_action")
    @mock.patch("cuckoo.core.scheduler.Scheduler.machine_lock")
    @mock.patch("time.sleep")
    def test_start_analysis_baseline(self, mts, mml, mrsa, msas, mrn, mrs):
        task = Task()
        task.add_baseline()

        # Mock resultserver obj so we can check if add_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj
        manager = self.get_manager(task)
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.aux = mock.MagicMock()

        result = manager.start_analysis()

        # Check if all required methods were called successfully
        msas.assert_has_calls([
            mock.call("starting"), mock.call("running")
        ])
        resulserver_obj.add_task.assert_called_once_with(task.db_task,
                                             manager.machine)
        manager.aux.start.assert_called_once()
        manager.machinery.start.assert_called_once_with("machine1",
                                                        task.db_task)
        mrn.assert_called_once()
        mml.release.assert_called_once()
        mrsa.assert_called_once_with(for_status="starting")
        mts.assert_called_once_with(manager.options["timeout"])
        assert result

    @mock.patch("cuckoo.analysis.taskanalysis.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.route_network")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager."
                "request_scheduler_action")
    @mock.patch("cuckoo.core.scheduler.Scheduler.machine_lock")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.wait_finish")
    def test_start_analysis_noagent(self, mwf, mml, mrsa, msas, mrn, mrs):
        task = Task()
        task.add_service(owner="1", tags="service,mitm", timeout=120)

        # Mock resultserver obj so we can check if add_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj
        manager = self.get_manager(task)
        manager.machine.options = "noagent"
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.aux = mock.MagicMock()

        result = manager.start_analysis()

        # Check if all required methods were called successfully
        msas.assert_has_calls([
            mock.call("starting"), mock.call("running")
        ])
        resulserver_obj.add_task.assert_called_once_with(task.db_task,
                                             manager.machine)
        manager.aux.start.assert_called_once()
        manager.machinery.start.assert_called_once_with("machine1",
                                                        task.db_task)
        mrn.assert_called_once()
        mml.release.assert_called_once()
        mrsa.assert_called_once_with(for_status="starting")
        mwf.assert_called_once()
        assert result

    @mock.patch("cuckoo.analysis.taskanalysis.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.unroute_network")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    def test_stop_analysis(self, msas, murn, mrs):
        # Mock resultserver obj so we can check if del_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj
        manager = self.get_manager()
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.aux = mock.MagicMock()

        manager.stop_analysis()

        # Check if all required methods were called successfully
        msas.assert_called_once_with("stopping")
        manager.aux.stop.assert_called_once()
        manager.machinery.stop.assert_called_once_with("machine1")

        resulserver_obj.del_task.assert_called_once_with(manager.task.db_task,
                                             manager.machine)
        murn.assert_called_once()

    @mock.patch("cuckoo.analysis.taskanalysis.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.unroute_network")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    def test_stop_analysis_dump_mem(self, msas, murn, mrs):
        task = Task()
        task.add_path(__file__, memory=True)

        # Mock resultserver obj so we can check if del_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj
        manager = self.get_manager(task)
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.aux = mock.MagicMock()

        manager.stop_analysis()

        # Check if all required methods were called successfully
        msas.assert_called_once_with("stopping")
        manager.aux.stop.assert_called_once()
        manager.machinery.dump_memory.assert_called_once_with(
            "machine1",
            cwd("storage", "analyses", str(task.id), "memory.dmp")
        )
        manager.machinery.stop.assert_called_once_with("machine1")

        resulserver_obj.del_task.assert_called_once_with(task.db_task,
                                             manager.machine)
        murn.assert_called_once()

    def test_run(self):
        manager = self.get_manager()
        manager.init(self.db)

        manager.start_analysis = mock.MagicMock(return_value=True)
        manager.stop_analysis = mock.MagicMock()
        manager.task.process = mock.MagicMock(return_value=True)
        manager.set_analysis_status = mock.MagicMock()
        manager.release_scheduler_lock = mock.MagicMock()
        manager.cfg.cuckoo.process_results = True

        manager.run()

        manager.start_analysis.assert_called_once()
        manager.stop_analysis.assert_called_once()
        manager.set_analysis_status.assert_called_once_with(
            "stopped", request_scheduler_action=True
        )
        manager.task.process.assert_called_once()
        manager.release_scheduler_lock.assert_called_once()

    def test_run_fail(self):
        manager = self.get_manager()
        manager.init(self.db)

        manager.start_analysis = mock.MagicMock(return_value=False)
        manager.stop_analysis = mock.MagicMock()
        manager.task.process = mock.MagicMock(return_value=True)
        manager.set_analysis_status = mock.MagicMock()
        manager.release_scheduler_lock = mock.MagicMock()
        manager.cfg.cuckoo.process_results = True

        manager.run()

        manager.start_analysis.assert_called_once()
        manager.stop_analysis.assert_called_once()
        manager.set_analysis_status.assert_called_once_with(
            "failed", request_scheduler_action=True
        )
        manager.task.process.assert_not_called()
        manager.release_scheduler_lock.assert_called_once()

    def test_on_status_starting(self):
        manager = self.get_manager()
        manager.init(self.db)
        manager.route = "none"

        manager.on_status_starting(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert db_task.machine == "machine1"
        assert db_task.route == "none"

    def test_on_status_stopped(self):
        manager = self.get_manager()
        task_json_path = cwd("storage", "analyses", str(manager.task.id), "task.json")
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        # Remove because init creates it. We need to check if it was created
        # on status stopped
        os.remove(task_json_path)

        manager.on_status_stopped(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert manager.task.db_task is not db_task
        assert db_task.status == "completed"
        assert os.path.isfile(task_json_path)
        manager.machinery.release.assert_called_once_with("machine1")

    def test_on_status_failed(self):
        manager = self.get_manager()
        manager.init(self.db)

        manager.on_status_failed(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert db_task.status == "failed_analysis"
        manager.machinery.release.assert_called_once_with("machine1")

    def test_finalize(self):
        manager = self.get_manager()
        task_json_path = cwd("storage", "analyses", str(manager.task.id),
                             "task.json")
        manager.init(self.db)
        manager.cfg.cuckoo.process_results = True
        manager.processing_success = True
        # Remove because init creates it. We need to check if it was created
        # on status stopped
        os.remove(task_json_path)

        manager.finalize(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert manager.task.db_task is not db_task
        assert db_task.status == "reported"
        assert os.path.isfile(task_json_path)

    def test_finalize_analysis_failed(self):
        manager = self.get_manager()
        task_json_path = cwd("storage", "analyses", str(manager.task.id),
                             "task.json")
        manager.init(self.db)
        manager.cfg.cuckoo.process_results = False
        manager.analysis.status = "running"
        # Remove because init creates it. We need to check if it was created
        # on status stopped
        os.remove(task_json_path)

        manager.finalize(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert manager.task.db_task is not db_task
        assert db_task.status == "failed_analysis"
        assert os.path.isfile(task_json_path)

    def test_finalize_process_failed(self):
        manager = self.get_manager()
        task_json_path = cwd("storage", "analyses", str(manager.task.id),
                             "task.json")
        manager.init(self.db)
        manager.cfg.cuckoo.process_results = True
        manager.processing_success = False
        # Remove because init creates it. We need to check if it was created
        # on status stopped
        os.remove(task_json_path)

        manager.finalize(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert manager.task.db_task is not db_task
        assert db_task.status == "failed_processing"
        assert os.path.isfile(task_json_path)

    def test_finalize_process_disabled(self):
        manager = self.get_manager()
        task_json_path = cwd("storage", "analyses", str(manager.task.id),
                             "task.json")
        manager.init(self.db)
        manager.cfg.cuckoo.process_results = False
        manager.processing_success = None
        # Remove because init creates it. We need to check if it was created
        # on status stopped
        os.remove(task_json_path)

        manager.finalize(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert manager.task.db_task is not db_task
        assert db_task.status != "reported"
        assert db_task.status != "failed_processing"
        assert os.path.isfile(task_json_path)

    @mock.patch("cuckoo.core.scheduler.Scheduler.machine_lock")
    def test_release_scheduler_lock(self, mml):
        manager = self.get_manager()
        manager.init(self.db)

        manager.release_scheduler_lock()

        mml.release.assert_called_once()
        assert manager.scheduler_lock_released
