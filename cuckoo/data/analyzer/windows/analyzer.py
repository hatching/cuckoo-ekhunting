# Copyright (C) 2011-2013 Claudio Guarnieri.
# Copyright (C) 2014-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import importlib
import logging
import os
import pkgutil
import struct
import sys
import threading
import time
import traceback
import urllib
import urllib2
import zipfile

from lib.api.process import Process
from lib.common.abstracts import Auxiliary
from lib.common.decide import dump_memory
from lib.common.exceptions import (
    CuckooDisableModule, CuckooError, CuckooPackageError
)
from lib.common.rand import random_string
from lib.common.results import upload_to_host, Files
from lib.core.command import MessageClient
from lib.core.config import Config
from lib.core.ioctl import zer0m0n
from lib.core.packages import choose_package, get_package_class
from lib.core.pipe import (
    get_pipe_path, disconnect_pipes, PipeServer, PipeForwarder, PipeDispatcher,
)
from lib.core.privileges import grant_privilege
from lib.core.startup import init_logging, set_clock, disconnect_logger
from modules import auxiliary

log = logging.getLogger("analyzer")

class ProcessList(object):
    def __init__(self):
        self.pids = []
        self.pids_notrack = []

    def add_pid(self, pid, track=True):
        """Add a process identifier to the process list.

        Track determines whether the analyzer should be monitoring this
        process, i.e., whether Cuckoo should wait for this process to finish.
        """
        if int(pid) not in self.pids and int(pid) not in self.pids_notrack:
            if track:
                self.pids.append(int(pid))
            else:
                self.pids_notrack.append(int(pid))

    def add_pids(self, pids):
        """Add one or more process identifiers to the process list."""
        if isinstance(pids, (tuple, list)):
            for pid in pids:
                self.add_pid(pid)
        else:
            self.add_pid(pids)

    def has_pid(self, pid, notrack=True):
        """Is this process identifier being tracked?"""
        if int(pid) in self.pids:
            return True

        if notrack and int(pid) in self.pids_notrack:
            return True

        return False

    def remove_pid(self, pid):
        """Remove a process identifier from being tracked."""
        if pid in self.pids:
            self.pids.remove(pid)

        if pid in self.pids_notrack:
            self.pids_notrack.remove(pid)

    def untrack_terminated(self):
        """Search for terminated processes in the tracked pid list and
        remove them from the pid and pid_notrack list"""
        terminated = []
        for pid in self.pids:
            if not Process(pid=pid).is_alive():
                terminated.append(pid)
                log.info("Process with PID %s has terminated", pid)

        for pid in terminated:
            self.remove_pid(pid)

    def terminate_tracked(self):
        log.info("Terminating all remaining processes")
        for pid in self.pids:
            p = Process(pid=pid)
            if p.is_alive():
                try:
                    p.terminate()
                except Exception:
                    continue

class CommandPipeHandler(object):
    """Pipe Handler.

    This class handles the notifications received through the Pipe Server and
    decides what to do with them.
    """
    ignore_list = dict(pid=[])

    def __init__(self, analyzer):
        self.analyzer = analyzer
        self.tracked = {}

    def _handle_debug(self, data):
        """Debug message from the monitor."""
        log.debug(data)

    def _handle_info(self, data):
        """Regular message from the monitor."""
        log.info(data)

    def _handle_warning(self, data):
        """Warning message from the monitor."""
        log.warning(data)

    def _handle_critical(self, data):
        """Critical message from the monitor."""
        log.critical(data)

    def _handle_loaded(self, data):
        """The monitor has loaded into a particular process."""
        if not data or data.count(",") != 1:
            log.warning("Received loaded command with incorrect parameters, "
                        "skipping it.")
            return

        pid, track = data.split(",")
        if not pid.isdigit() or not track.isdigit():
            log.warning("Received loaded command with incorrect parameters, "
                        "skipping it.")
            return

        self.analyzer.plock.acquire()
        self.analyzer.plist.add_pid(int(pid), track=int(track))
        self.analyzer.plock.release()

        log.debug("Loaded monitor into process with pid %s", pid)

    def _handle_getpids(self, data):
        """Return the process identifiers of the agent and its parent
        process."""
        return struct.pack("II", self.analyzer.pid, self.analyzer.ppid)

    def _inject_process(self, process_id, thread_id, mode):
        """Helper function for injecting the monitor into a process."""
        # We acquire the process lock in order to prevent the analyzer to
        # terminate the analysis while we are operating on the new process.
        self.analyzer.plock.acquire()

        # Set the current DLL to the default one provided at submission.
        dll = self.analyzer.default_dll

        if process_id in (self.analyzer.pid, self.analyzer.ppid):
            if process_id not in self.ignore_list["pid"]:
                log.warning("Received request to inject Cuckoo processes, "
                            "skipping it.")
                self.ignore_list["pid"].append(process_id)
            self.analyzer.plock.release()
            return

        # We inject the process only if it's not being monitored already,
        # otherwise we would generated polluted logs (if it wouldn't crash
        # horribly to start with).
        if self.analyzer.plist.has_pid(process_id):
            # This pid is already on the notrack list, move it to the
            # list of tracked pids.
            if not self.analyzer.plist.has_pid(process_id, notrack=False):
                log.debug("Received request to inject pid=%d. It was already "
                          "on our notrack list, moving it to the track list.")

                self.analyzer.plist.remove_pid(process_id)
                self.analyzer.plist.add_pid(process_id)
                self.ignore_list["pid"].append(process_id)
            # Spit out an error once and just ignore it further on.
            elif process_id not in self.ignore_list["pid"]:
                self.ignore_list["pid"].append(process_id)

            # We're done operating on the processes list, release the lock.
            self.analyzer.plock.release()
            return

        # Open the process and inject the DLL. Hope it enjoys it.
        proc = Process(pid=process_id, tid=thread_id)

        filename = os.path.basename(proc.get_filepath())

        if not self.analyzer.files.is_protected_filename(filename):
            # Add the new process ID to the list of monitored processes.
            self.analyzer.plist.add_pid(process_id)

            # We're done operating on the processes list,
            # release the lock. Let the injection do its thing.
            self.analyzer.plock.release()

            # If we have both pid and tid, then we can use APC to inject.
            if process_id and thread_id:
                proc.inject(dll, apc=True, mode="%s" % mode)
            else:
                proc.inject(dll, apc=False, mode="%s" % mode)

            log.info("Injected into process with pid %s and name %r",
                     proc.pid, filename)

    def _handle_process(self, data):
        """Request for injection into a process."""
        # Parse the process identifier.
        if not data or not data.isdigit():
            log.warning("Received PROCESS command from monitor with an "
                        "incorrect argument.")
            return

        return self._inject_process(int(data), None, 0)

    def _handle_process2(self, data):
        """Request for injection into a process using APC."""
        # Parse the process and thread identifier.
        if not data or data.count(",") != 2:
            log.warning("Received PROCESS2 command from monitor with an "
                        "incorrect argument.")
            return

        pid, tid, mode = data.split(",")
        if not pid.isdigit() or not tid.isdigit() or not mode.isdigit():
            log.warning("Received PROCESS2 command from monitor with an "
                        "incorrect argument.")
            return

        return self._inject_process(int(pid), int(tid), int(mode))

    def _handle_file_new(self, data):
        """Notification of a new dropped file."""
        self.analyzer.files.add_file(data.decode("utf8"), self.pid)

    def _handle_file_del(self, data):
        """Notification of a file being removed (if it exists) - we have to
        dump it before it's being removed."""
        filepath = data.decode("utf8")
        if os.path.exists(filepath):
            self.analyzer.files.delete_file(filepath, self.pid)

    def _handle_file_move(self, data):
        """A file is being moved - track these changes."""
        if "::" not in data:
            log.warning("Received FILE_MOVE command from monitor with an "
                        "incorrect argument.")
            return

        old_filepath, new_filepath = data.split("::", 1)
        self.analyzer.files.move_file(
            old_filepath.decode("utf8"), new_filepath.decode("utf8"), self.pid
        )

    def _handle_kill(self, data):
        """A process is being killed."""
        if not data.isdigit():
            log.warning("Received KILL command with an incorrect argument.")
            return

        if self.analyzer.config.options.get("procmemdump"):
            dump_memory(int(data))

    def _handle_dumpmem(self, data):
        """Dump the memory of a process as it is right now."""
        if not data.isdigit():
            log.warning("Received DUMPMEM command with an incorrect argument.")
            return

        dump_memory(int(data))

    def _handle_dumpreqs(self, data):
        if not data.isdigit():
            log.warning(
                "Received DUMPREQS command with an incorrect argument %r.", data
            )
            return

        pid = int(data)

        if pid not in self.tracked:
            log.warning("Received DUMPREQS command but there are no reqs for pid %d.", pid)
            return

        dumpreqs = self.tracked[pid].get("dumpreq", [])
        for addr, length in dumpreqs:
            log.debug("tracked dump req (%r, %r, %r)", pid, addr, length)

            if not addr or not length:
                continue

            Process(pid=pid).dump_memory_block(int(addr), int(length))

    def _handle_track(self, data):
        if not data.count(":") == 2:
            log.warning("Received TRACK command with an incorrect argument %r.", data)
            return

        pid, scope, params = data.split(":", 2)
        pid = int(pid)

        paramtuple = params.split(",")
        if pid not in self.tracked:
            self.tracked[pid] = {}
        if scope not in self.tracked[pid]:
            self.tracked[pid][scope] = []
        self.tracked[pid][scope].append(paramtuple)

    def dispatch(self, data):
        response = "NOPE"

        if not data or ":" not in data:
            log.critical("Unknown command received from the monitor: %r",
                         data.strip())
        else:
            # Backwards compatibility (old syntax is, e.g., "FILE_NEW:" vs the
            # new syntax, e.g., "1234:FILE_NEW:").
            if data[0].isupper():
                command, arguments = data.strip().split(":", 1)
                self.pid = None
            else:
                self.pid, command, arguments = data.strip().split(":", 2)

            fn = getattr(self, "_handle_%s" % command.lower(), None)
            if not fn:
                log.critical("Unknown command received from the monitor: %r",
                             data.strip())
            else:
                try:
                    response = fn(arguments)
                except:
                    log.exception(
                        "Pipe command handler exception occurred (command "
                        "%s args %r).", command, arguments
                    )

        return response

class Analyzer(object):

    def __init__(self):
        self.config = Config(cfg="analysis.conf")
        self.default_dll = self.config.options.get("dll")
        self.is_running = True
        self.cleanup_files = []
        self.pkg_counter = 0
        self.runtime = 0
        self.reboot = []
        self.packages = {}
        self.aux_enabled = {}
        self.aux_available = {}

        self.pid = os.getpid()
        self.ppid = Process(pid=self.pid).get_parent_pid()
        self.path = os.getcwd()
        self.plock = threading.Lock()
        self.files = Files()
        self.plist = ProcessList()

    def initialize(self):
        Process.set_config(self.config)
        self.config.logpipe = get_pipe_path(random_string(16, 32))
        self.config.pipe = self.config.options.get(
            "pipe", get_pipe_path(random_string(16, 32))
        )
        self.msgclient = MessageClient(
            self.config.ip, self.config.port, self
        )

    def prepare(self):
        # Get SeDebugPrivilege for the Python process. It will be needed in
        # order to perform the injections.
        for privilege in ("SeDebugPrivilege", "SeLoadDriverPrivilege"):
            if not grant_privilege(privilege):
                log.error("Failed to grant '%s' privilege")

        # Set the system's date and time to given values
        set_clock(datetime.datetime.strptime(
            self.config.clock, "%Y%m%dT%H:%M:%S"
        ))

        # Initialize and start the Command Handler pipe server. This is going
        # to be used for communicating with the monitored processes.
        self.command_pipe = PipeServer(
            PipeDispatcher, self.config.pipe, message=True,
            dispatcher=CommandPipeHandler(self)
        )
        self.command_pipe.start()

        # Initialize and start the Log Pipe Server - the log pipe server will
        # open up a pipe that monitored processes will use to send logs to
        # before they head off to the host machine.
        self.log_pipe = PipeServer(
            PipeForwarder, self.config.logpipe,
            destination=(self.config.ip, self.config.port)
        )
        self.log_pipe.start()

        self.msgclient.connect()
        if not self.msgclient.connected:
            return False
        self.msgclient.start()

        return True

    def start_package(self, config):
        """Start an analysis package.

        @param config: a dictionary containing at least a target category,
        options dictionary, and target string or list of targets

        returns a package id
        """
        pkg = config.get("package")
        if not pkg:
            log.info(
                "No analysis package provided, trying to automatically find a "
                "matching package"
            )
            pkg = choose_package(config)
        else:
            pkg = get_package_class(pkg)

        if not pkg:
            category = config.get("category")
            raise CuckooPackageError(
                "No valid analysis package available for target category '%s'."
                "%s" % (category, category if category == "file" else "")
            )

        log.info("Using analysis package '%s'", pkg.__name__)
        options = config.get("options", {}) or {}
        pkg_instance = pkg(options=options, analyzer=self)

        category = config.get("category")
        if category == "file":
            target = os.path.join(os.environ["TEMP"], config.get("file_name"))
            pkg_instance.move_curdir(target)

        elif category == "archive":
            zippath = os.path.join(os.environ["TEMP"], config.get("file_name"))
            zipfile.ZipFile(zippath).extractall(os.environ["TEMP"])
            if not options.get("filename"):
                raise CuckooPackageError(
                    "No filename specified to open after unpacking archive"
                )

            target = os.path.join(os.environ["TEMP"], options.get("filename"))
        elif category == "url":
            target = config.get("target")
        else:
            raise CuckooPackageError(
                "Unknown category '%s' specified" % category
            )

        pids = pkg_instance.start(target)
        if pids:
            self.plist.add_pids(pids)

        self.pkg_counter += 1
        pkg_id = str(config.get("pkg_id") or self.pkg_counter)
        self.packages[pkg_id] = pkg_instance
        return {"pkg_id": pkg_id}

    def stop_package(self, pkg_id, procmemdump=False):
        """Stop the package matching the given package id. Process memory
        dumps are created if

        @param pkg_id: a string identifier to specify a running analysis
        package
        """
        pkg_id = str(pkg_id)
        pkg = self.packages.get(pkg_id)
        if not pkg:
            raise CuckooPackageError(
                "Cannot stop package. Package with id '%r' does not "
                "exist" % pkg_id
            )

        if procmemdump or pkg.options.get("procmemdump"):
            try:
                pkg.dump_procmem()
            except Exception as e:
                log.exception(
                    "Error while creating process memory dumps for "
                    "package '%s'. %s", pkg.__class__.__name__, e
                )

        try:
            pkg.finish()
        except Exception as e:
            log.exception(
                "Error during analysis package '%s' finishing. %s",
                pkg.__class__.__name__, e
            )

        try:
            # Upload files the package created to package_files in the
            # results folder.
            for path, name in pkg.package_files() or []:
                upload_to_host(path, os.path.join("package_files", name))
        except Exception as e:
            log.warning(
                "The package '%s' package_files function raised an "
                "exception: %s", pkg.__class__.__name__, e
            )

        pkg.stop()
        self.packages.pop(pkg_id)
        return {"pkg_id": pkg_id}

    def list_packages(self):
        """Return a dict of package identifiers and the package name
        that is running"""
        return {
            pkg_id: pkg.__class__.__name__
            for pkg_id, pkg in self.packages.iteritems()
        }

    def dump_memory(self, pid):
        """Dump the memory of the specified PID"""
        dump_memory(pid)

    def list_tracked_pids(self):
        """Return a list of all tracked pids"""
        return self.plist.pids

    def prepare_zer0m0n(self):
        """Communicate settings to zer0m0n and request actions"""
        # Inform zer0m0n of the ResultServer address.
        zer0m0n.resultserver(self.config.ip, self.config.port)

        # Inform zer0m0n of the command and logpipe names
        zer0m0n.cmdpipe(self.config.pipe)
        zer0m0n.channel(self.config.logpipe)

        # Hide the analyzer and agent pids
        zer0m0n.hidepid(self.pid)
        zer0m0n.hidepid(self.ppid)

        # Initialize zer0m0n with our compiled Yara rules.
        zer0m0n.yarald("bin/rules.yarac")

        # Propagate the requested dump interval, if set.
        zer0m0n.dumpint(int(self.config.options.get("dumpint", "0")))

    def start_auxiliaries(self):
        Auxiliary()
        iter_aux_modules = pkgutil.iter_modules(
            auxiliary.__path__, "%s." % auxiliary.__name__
        )
        for loader, name, ispkg in iter_aux_modules:
            if ispkg:
                continue

            try:
                importlib.import_module(name)
            except ImportError as e:
                log.exception(
                    "Failed to import Auxiliary module: '%s'. %s", name, e
                )

        for aux_module in Auxiliary.__subclasses__():
            try:
                aux = aux_module(options=self.config.options, analyzer=self)
                self.aux_available[aux_module.__name__.lower()] = aux
                if not aux.enabled():
                    log.debug(
                        "Auxiliary module '%s' disabled", aux_module.__name__
                    )
                    raise CuckooDisableModule

                aux.init()
                aux.start()
            except (NotImplementedError, AttributeError) as e:
                log.exception(
                    "Auxiliary module '%s' could not be started. Missing "
                    "attributes or functions. %s", aux_module.__name__, e
                )
            except CuckooDisableModule:
                continue
            except Exception as e:
                log.exception(
                    "Error while starting auxiliary module '%s'. %s",
                    aux_module.__name__, e
                )
            else:
                self.aux_enabled[aux_module.__name__.lower()] = aux
                log.debug("Started auxiliary module %s", aux_module.__name__)

    def stop(self):
        """Stop the analyzer and all running modules."""
        log.info("Stopping analysis")
        for pkg_id, package in self.packages.iteritems():

            if package.options.get("procmemdump"):
                try:
                    package.dump_procmem()
                except Exception as e:
                    log.exception(
                        "Error during the creation of a memory dump for"
                        " package '%s'. %s", package.__class__.__name__, e
                    )

            try:
                # Perform final operations for all analysis packages
                package.finish()
            except Exception as e:
                log.exception(
                    "The analysis package '%s' raised an exception in its "
                    "finish method. %s", package.__class__.__name__, e
                )

            try:
                # Upload files the package created to package_files in the
                # results folder.
                for path, name in package.package_files() or []:
                    upload_to_host(path, os.path.join("package_files", name))
            except Exception as e:
                log.exception(
                    "The package '%s' package_files function raised an "
                    "exception: %s", package.__class__.__name__, e
                )

        for aux_name, aux in self.aux_enabled.iteritems():
            try:
                aux.stop()
            except (NotImplementedError, AttributeError):
                continue
            except Exception as e:
                log.exception(
                    "Failed to terminate auxiliary module: %s. %s",
                    aux_name, e
                )

        if self.config.terminate_processes:
            self.plist.terminate_tracked()

        for aux_name, aux in self.aux_enabled.iteritems():
            try:
                aux.finish()
            except (NotImplementedError, AttributeError):
                continue
            except Exception as e:
                log.exception(
                    "Failed to terminate auxiliary module: %s. %s", aux_name, e
                )

        # Stop the pipe for commands to be sent to the analyzer.
        self.command_pipe.stop()

        # Upload all pending files before ending the analysis
        self.files.dump_files()
        return True

    def request_stop(self):
        """Can be called outside of the analyzer to cause it to go through
        the proper stopping routine"""
        self.is_running = False

    def do_run(self):
        if not self.is_running:
            log.info(
                "Analyzer was requested to stop running, terminating analysis"
            )
            return False

        if self.runtime >= int(self.config.timeout):
            log.info("Analysis timeout hit, terminating analysis")
            self.is_running = False
            return False

        if not self.plist.pids and not self.config.enforce_timeout:
            log.info(
                "Process list is empty and timeout enforcing is disabled, "
                "terminating analysis."
            )
            self.is_running = False
            return False

        return True

    def finalize(self):
        """Close connections, close pipes etc. Steps that are performed
        just before posting the result to the agent. Nothing can be logged
        here"""
        self.log_pipe.stop()
        self.msgclient.stop()
        disconnect_pipes()
        disconnect_logger()

    def start(self):
        """Start the analyzer"""
        log.debug(
            "Starting analyzer from: '%s'. Command pipe: '%s'. Log pipe: '%s'",
            self.path, self.config.pipe, self.config.logpipe
        )

        self.start_auxiliaries()
        self.prepare_zer0m0n()
        self.start_package(self.config)

        while self.do_run():
            self.runtime += 1

            if self.plock.locked():
                time.sleep(1)
                continue

            self.plock.acquire()
            try:
                self.plist.add_pids(zer0m0n.getpids())

                for pkg_cnt, pkg in self.packages.iteritems():
                    pkg.set_pids(self.plist.pids)

                try:
                    pkg.check()
                except Exception as e:
                    log.exception(
                        "The analysis package '%s' raised an exception. "
                        "Error: %s. %s", pkg.__class__.__name__, e
                    )

            finally:
                self.plock.release()
                time.sleep(1)

        return True

if __name__ == "__main__":
    init_logging()
    analyzer = Analyzer()
    data = {
        "status": "",
        "description": ""
    }

    try:
        analyzer.initialize()

        # Prepare for analysis, if it fails, stop the analysis
        if not analyzer.prepare():
            raise CuckooError("Analyzer preparation failed")

        start = analyzer.start()
        stop = analyzer.stop()

        log.info("Analysis complete")
        data["status"] = "complete"
        data["description"] = start and stop
    except KeyboardInterrupt:
        log.warning("CTRL+C detected!")
        data["status"] = "exception"
        data["description"] = "Analyzer stopped by keyboard interrupt"
    except Exception as e:
        excp = traceback.format_exc()

        if len(log.handlers):
            log.exception("Analyzer exception: %s", e)
        else:
            sys.stderr.write("%s\n" % excp)

        data["status"] = "exception"
        data["description"] = excp
    finally:
        try:
            analyzer.finalize()
        finally:
            urllib2.urlopen(
                "http://127.0.0.1:8000/status", urllib.urlencode(data)
            )
