# Copyright (C) 2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import mock
import os
import shutil
import tempfile

from cuckoo.analysis.regular import Regular
from cuckoo.common.objects import File
from cuckoo.core.database import Database
from cuckoo.core.guest import GuestManager
from cuckoo.core.plugins import RunAuxiliary
from cuckoo.core.task import Task
from cuckoo.core.target import Target
from cuckoo.main import cuckoo_create
from cuckoo.misc import set_cwd, cwd

class FakeMachine(object):
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

class TestRegular(object):

    createcwd = True

    def setup_class(self):
        self.remove_paths = []
        self.db = Database()

    def create_cwd(self, cfg=None):
        if not TestRegular.createcwd and cfg is None:
            return

        TestRegular.createcwd = False
        newcwd = tempfile.mkdtemp()
        set_cwd(newcwd)
        cuckoo_create(cfg=cfg)
        self.remove_paths.append(newcwd)
        self.db.connect()

    def teardown_class(self):
        for path in self.remove_paths:
            if os.path.isdir(path):
                shutil.rmtree(path)

    def get_manager(self, task=None):
        if task is None:
            task = Task()
            fd, fpath = tempfile.mkstemp()
            os.write(fd, b"\x00"*32)
            os.close(fd)
            newname = os.path.join(os.path.dirname(fpath), "testanalysis.exe")
            os.rename(fpath, newname)
            task.add_path(newname)

        manager = Regular(
            FakeMachine(), mock.MagicMock(), mock.MagicMock()
        )
        manager.set_task(task)
        manager.set_target(task.targets)
        return manager

    def test_set_task(self):
        self.create_cwd()
        task = Task()
        task.add_path(__file__)
        manager = self.get_manager()
        manager.set_task(task)

        assert manager.task == task
        assert manager.analysis is not None
        assert manager.name == "task_%s_Regular" % task.id

    def test_set_target(self):
        self.create_cwd()
        task = Task()
        task.add_path(__file__)
        manager = self.get_manager()
        manager.set_target(task.targets)
        assert manager.target == task.targets[0]

    def test_set_target_empty(self):
        self.create_cwd()
        task = Task()
        task.add_path(__file__)
        task.task_dict["targets"] = []
        manager = self.get_manager()
        manager.set_target(task.targets)
        assert isinstance(manager.target, Target)

    @mock.patch("cuckoo.common.abstracts.AnalysisManager.build_options")
    def test_init(self, mb):
        self.create_cwd()
        manager = self.get_manager()
        result = manager.init(self.db)
        mb.assert_called_once_with(options={
            "category": "file",
            "target": manager.target.target,
            "file_type": "data",
            "file_name": "testanalysis.exe",
            "pe_exports": "",
            "options": {}
        })

        assert result
        assert isinstance(manager.guest_manager, GuestManager)
        assert isinstance(manager.aux, RunAuxiliary)
        assert os.path.isfile(os.path.join(manager.task.path, "task.json"))

    @mock.patch("cuckoo.common.abstracts.AnalysisManager.build_options")
    @mock.patch("cuckoo.core.target.File.get_apk_entry")
    def test_init_apk_options(self, mae, mb):
        self.create_cwd()
        manager = self.get_manager()
        mae.return_value = ("package", "activity")
        result = manager.init(self.db)

        mb.assert_called_once_with(options={
            "category": "file",
            "target": manager.target.target,
            "file_type": "data",
            "file_name": "testanalysis.exe",
            "pe_exports": "",
            "options": {"apk_entry": "package:activity"}
        })

        assert result
        assert isinstance(manager.guest_manager, GuestManager)
        assert isinstance(manager.aux, RunAuxiliary)
        assert os.path.isfile(os.path.join(manager.task.path, "task.json"))

    @mock.patch("cuckoo.common.abstracts.AnalysisManager.build_options")
    def test_init_non_file(self, mb):
        self.create_cwd()
        task = Task()
        task.add_url("http://example.com/42")
        manager = self.get_manager(task)

        result = manager.init(self.db)
        mb.assert_called_once()
        assert result
        assert isinstance(manager.guest_manager, GuestManager)
        assert isinstance(manager.aux, RunAuxiliary)
        assert os.path.isfile(os.path.join(task.path, "task.json"))

    def test_init_remov_original(self):
        self.create_cwd()
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

        result = manager.init(self.db)
        assert result
        assert manager.options["target"] == tmpfile
        assert manager.options["file_name"] == tmpfile_obj.get_name()
        assert isinstance(manager.guest_manager, GuestManager)
        assert isinstance(manager.aux, RunAuxiliary)
        assert os.path.isfile(os.path.join(task.path, "task.json"))

    def test_init_fail(self):
        self.create_cwd()
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

    def test_init_copied_bin_none(self):
        self.create_cwd()
        manager = self.get_manager()
        manager.target.copied_binary = None
        result = manager.init(self.db)

        assert not result

    @mock.patch("cuckoo.analysis.regular.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager."
                "request_scheduler_action")
    def test_start_and_wait(self, mrsa, msas, mrs):
        self.create_cwd()
        manager = self.get_manager()
        # Mock resultserver obj so we can check if add_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj

        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.route = mock.MagicMock()
        manager.aux = mock.MagicMock()
        manager.guest_manager = mock.MagicMock()
        # Set status manually, because the method used is mocked
        manager.analysis.status = "starting"

        result = manager.start_and_wait()

        # Check if all required methods were called successfully
        msas.assert_has_calls([
            mock.call("starting"), mock.call("running")
        ])
        resulserver_obj.add_task.assert_called_once_with(manager.task.db_task,
                                             manager.machine)
        manager.aux.start.assert_called_once()
        manager.machinery.start.assert_called_once_with("machine1",
                                                        manager.task.db_task)
        manager.route.route_network.assert_called_once()
        manager.machine_lock.release.assert_called_once()
        mrsa.assert_called_once_with("starting")
        manager.guest_manager.start_analysis.assert_called_once()
        manager.guest_manager.wait_for_completion.assert_called_once()
        assert result

    @mock.patch("cuckoo.analysis.regular.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager."
                "request_scheduler_action")
    def test_start_and_wait_url(self, mrsa, msas, mrs):
        self.create_cwd()
        task = Task()
        task.add_url("http://example.com/42")

        # Mock resultserver obj so we can check if add_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj

        manager = self.get_manager(task)
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.route = mock.MagicMock()
        manager.aux = mock.MagicMock()
        manager.guest_manager = mock.MagicMock()
        # Set status manually, because the method used is mocked
        manager.analysis.status = "starting"

        result = manager.start_and_wait()

        # Check if all required methods were called successfully
        msas.assert_has_calls([
            mock.call("starting"), mock.call("running")
        ])
        resulserver_obj.add_task.assert_called_once_with(task.db_task,
                                             manager.machine)
        manager.aux.start.assert_called_once()
        manager.machinery.start.assert_called_once_with("machine1",
                                                        task.db_task)
        manager.route.route_network.assert_called_once()
        manager.machine_lock.release.assert_called_once()
        mrsa.assert_called_once_with("starting")
        manager.guest_manager.start_analysis.assert_called_once()
        manager.guest_manager.wait_for_completion.assert_called_once()
        assert result

    @mock.patch("cuckoo.analysis.regular.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager."
                "request_scheduler_action")
    @mock.patch("time.sleep")
    def test_start_and_wait_baseline(self, mts, mrsa, msas, mrs):
        self.create_cwd()
        task = Task()
        task.add_baseline()

        # Mock resultserver obj so we can check if add_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj
        manager = self.get_manager(task)
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.route = mock.MagicMock()
        manager.aux = mock.MagicMock()

        result = manager.start_and_wait()

        # Check if all required methods were called successfully
        msas.assert_has_calls([
            mock.call("starting"), mock.call("running")
        ])
        resulserver_obj.add_task.assert_called_once_with(task.db_task,
                                             manager.machine)
        manager.aux.start.assert_called_once()
        manager.machinery.start.assert_called_once_with("machine1",
                                                        task.db_task)
        manager.route.route_network.assert_called_once()
        manager.machine_lock.release.assert_called_once()
        mrsa.assert_called_once_with("starting")
        mts.assert_called_once_with(manager.options["timeout"])
        assert result

    @mock.patch("cuckoo.analysis.regular.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager."
                "request_scheduler_action")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.wait_finish")
    def test_start_and_wait_noagent(self, mwf, mrsa, msas, mrs):
        self.create_cwd()
        task = Task()
        task.add_service(owner="1", tags="service,mitm", timeout=120)

        # Mock resultserver obj so we can check if add_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj
        manager = self.get_manager(task)
        manager.machine.options = "noagent"
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.route = mock.MagicMock()
        manager.aux = mock.MagicMock()

        result = manager.start_and_wait()

        # Check if all required methods were called successfully
        msas.assert_has_calls([
            mock.call("starting"), mock.call("running")
        ])
        resulserver_obj.add_task.assert_called_once_with(task.db_task,
                                             manager.machine)
        manager.aux.start.assert_called_once()
        manager.machinery.start.assert_called_once_with("machine1",
                                                        task.db_task)
        manager.route.route_network.assert_called_once()
        manager.machine_lock.release.assert_called_once()
        mrsa.assert_called_once_with("starting")
        mwf.assert_called_once()
        assert result

    @mock.patch("cuckoo.analysis.regular.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    def test_stop_and_wait(self, msas, mrs):
        self.create_cwd()
        # Mock resultserver obj so we can check if del_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj
        manager = self.get_manager()
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.route = mock.MagicMock()
        manager.aux = mock.MagicMock()

        manager.stop_and_wait()

        # Check if all required methods were called successfully
        msas.assert_called_once_with("stopping")
        manager.aux.stop.assert_called_once()
        manager.machinery.stop.assert_called_once_with("machine1")

        resulserver_obj.del_task.assert_called_once_with(manager.task.db_task,
                                             manager.machine)
        manager.route.unroute_network.assert_called_once()

    @mock.patch("cuckoo.analysis.regular.ResultServer")
    @mock.patch("cuckoo.common.abstracts.AnalysisManager.set_analysis_status")
    def test_stop_and_wait_dump_mem(self, msas, mrs):
        self.create_cwd()
        task = Task()
        task.add_path(__file__, memory=True)

        # Mock resultserver obj so we can check if del_task was called
        resulserver_obj = mock.MagicMock()
        mrs.return_value = resulserver_obj
        manager = self.get_manager(task)
        manager.init(self.db)
        manager.machinery = mock.MagicMock()
        manager.route = mock.MagicMock()
        manager.aux = mock.MagicMock()

        manager.stop_and_wait()

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
        manager.route.unroute_network.assert_called_once()

    def test_run(self):
        self.create_cwd()

        manager = self.get_manager()
        manager.init(self.db)

        manager.start_and_wait = mock.MagicMock(return_value=True)
        manager.stop_and_wait = mock.MagicMock()
        manager.task.process = mock.MagicMock(return_value=True)
        manager.set_analysis_status = mock.MagicMock()
        manager.release_machine_lock = mock.MagicMock()

        manager.run()

        manager.start_and_wait.assert_called_once()
        manager.stop_and_wait.assert_called_once()
        manager.set_analysis_status.assert_called_once_with(
            "stopped", wait=True
        )
        manager.task.process.assert_called_once()

    def test_run_fail(self):
        self.create_cwd()
        manager = self.get_manager()
        manager.init(self.db)

        manager.start_and_wait = mock.MagicMock(return_value=False)
        manager.stop_and_wait = mock.MagicMock()
        manager.task.process = mock.MagicMock(return_value=True)
        manager.set_analysis_status = mock.MagicMock()
        manager.release_machine_lock = mock.MagicMock()

        manager.run()

        manager.start_and_wait.assert_called_once()
        manager.stop_and_wait.assert_called_once()
        manager.set_analysis_status.assert_called_once_with(
            "failed", wait=True
        )
        manager.task.process.assert_called_once()

    def test_on_status_starting(self):
        manager = self.get_manager()
        manager.init(self.db)
        manager.route.route = "none"

        manager.on_status_starting(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert db_task.machine == "machine1"
        assert db_task.route == "none"

    def test_on_status_stopped(self):
        manager = self.get_manager()
        task_json_path = cwd("task.json", analysis=manager.task.id)
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
        manager.machinery.release.assert_called_once_with("machine1")

    def test_finalize(self):
        manager = self.get_manager()
        task_json_path = cwd("task.json", analysis=manager.task.id)
        manager.init(self.db)
        manager.processing_success = True
        manager.release_machine_lock = mock.MagicMock()
        # Remove because init creates it. We need to check if it was created
        # on status stopped
        os.remove(task_json_path)

        manager.finalize(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert manager.task.db_task is not db_task
        assert db_task.status == "reported"
        assert os.path.isfile(task_json_path)
        manager.release_machine_lock.assert_called_once()

    def test_finalize_analysis_failed(self):
        self.create_cwd(cfg={
            "cuckoo": {
                "cuckoo": {
                    "process_results": False
                }
            }
        })
        manager = self.get_manager()
        task_json_path = cwd("task.json", analysis=manager.task.id)
        manager.init(self.db)
        manager.analysis.status = "running"
        manager.release_machine_lock = mock.MagicMock()
        # Remove because init creates it. We need to check if it was created
        # on status stopped
        os.remove(task_json_path)

        manager.finalize(self.db)

        db_task = self.db.view_task(manager.task.id)
        assert manager.task.db_task is not db_task
        assert db_task.status == "failed_analysis"
        assert os.path.isfile(task_json_path)
        manager.release_machine_lock.assert_called_once()

    def test_finalize_process_failed(self):
        TestRegular.createcwd = True
        self.create_cwd()
        manager = self.get_manager()
        task_json_path = cwd("task.json", analysis=manager.task.id)

        manager.init(self.db)
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
        self.create_cwd(cfg={
            "cuckoo": {
                "cuckoo": {
                    "process_results": False
                }
            }
        })
        manager = self.get_manager()
        task_json_path = cwd("task.json", analysis=manager.task.id)
        manager.init(self.db)
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

    def test_support_list(self):
        for tasktype in ("regular", "baseline", "server"):
            assert tasktype in Regular.supports
