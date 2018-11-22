# Copyright (C) 2013 Claudio Guarnieri.
# Copyright (C) 2014-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import hashlib
import json
import logging
import os
import socket
import sys
import time

from lib.common.hashing import hash_file
from lib.core.config import Config

log = logging.getLogger(__name__)

BUFSIZE = 1024*1024

def upload_to_host(file_path, dump_path, pids=[]):
    nc = infd = None
    try:
        nc = NetlogFile()
        nc.init(dump_path, file_path, pids)

        infd = open(file_path, "rb")
        buf = infd.read(BUFSIZE)
        while buf:
            nc.send(buf, retry=False)
            buf = infd.read(BUFSIZE)
    except Exception as e:
        log.error("Exception uploading file %r to host: %s", file_path, e)
    finally:
        if infd:
            infd.close()
        if nc:
            nc.close()

class NetlogConnection(object):
    def __init__(self, proto=""):
        config = Config(cfg="analysis.conf")
        self.hostip, self.hostport = config.ip, config.port
        self.sock = None
        self.proto = proto

    def connect(self):
        # Try to connect as quickly as possible. Just sort of force it to
        # connect with a short timeout.
        while not self.sock:
            try:
                s = socket.create_connection((self.hostip, self.hostport), 0.1)
            except socket.error:
                time.sleep(0.1)
                continue

            s.settimeout(None)
            s.sendall(self.proto)

            self.sock = s

    def send(self, data, retry=True):
        if not self.sock:
            self.connect()

        try:
            self.sock.sendall(data)
        except socket.error as e:
            if retry:
                self.connect()
                self.send(data, retry=False)
            else:
                print >>sys.stderr, "Unhandled exception in NetlogConnection:", str(e)
        except Exception as e:
            print >>sys.stderr, "Unhandled exception in NetlogConnection:", str(e)
            # We really have nowhere to log this, if the netlog connection
            # does not work, we can assume that any logging won't work either.
            # So we just fail silently.
            self.close()

    def close(self):
        try:
            self.sock.close()
            self.sock = None
        except Exception:
            pass

class NetlogFile(NetlogConnection):
    def init(self, dump_path, filepath=None, pids=[]):
        header = {"store_as": dump_path.encode("utf8")}
        if filepath:
            header["path"] = filepath.encode("utf8")
        if pids:
            header["pids"] = [int(p) for p in pids]
        self.proto = "FILE %s\n" % json.dumps(header)

        self.connect()

class NetlogHandler(logging.Handler, NetlogConnection):
    def __init__(self):
        logging.Handler.__init__(self)
        NetlogConnection.__init__(self, proto="LOG\n")
        self.connect()

    def emit(self, record):
        msg = self.format(record)
        self.send("{0}\n".format(msg))

class Files(object):
    PROTECTED_NAMES = ()

    def __init__(self):
        self.files = {}
        self.files_orig = {}
        self.dumped = []

    def is_protected_filename(self, file_name):
        """Do we want to inject into a process with this name?"""
        return file_name.lower() in self.PROTECTED_NAMES

    def add_pid(self, filepath, pid, verbose=True):
        """Tracks a process identifier for this file."""
        if not pid or filepath.lower() not in self.files:
            return

        if pid not in self.files[filepath.lower()]:
            self.files[filepath.lower()].append(pid)
            verbose and log.info("Added pid %s for %r", pid, filepath)

    def add_file(self, filepath, pid=None):
        """Add filepath to the list of files and track the pid."""
        if filepath.lower() not in self.files:
            log.info(
                "Added new file to list with pid %s and path %s",
                pid, filepath.encode("utf8")
            )
            self.files[filepath.lower()] = []
            self.files_orig[filepath.lower()] = filepath

        self.add_pid(filepath, pid, verbose=False)

    def dump_file(self, filepath):
        """Dump a file to the host."""
        if not os.path.isfile(filepath):
            log.warning("File at path %r does not exist, skip.", filepath)
            return False

        # Check whether we've already dumped this file - in that case skip it.
        try:
            sha256 = hash_file(hashlib.sha256, filepath)
            if sha256 in self.dumped:
                return
        except IOError as e:
            log.info("Error dumping file from path \"%s\": %s", filepath, e)
            return

        filename = "%s_%s" % (sha256[:16], os.path.basename(filepath))
        upload_path = os.path.join("files", filename)

        try:
            upload_to_host(
                # If available use the original filepath, the one that is
                # not lowercased.
                self.files_orig.get(filepath.lower(), filepath),
                upload_path, self.files.get(filepath.lower(), [])
            )
            self.dumped.append(sha256)
        except (IOError, socket.error) as e:
            log.error(
                "Unable to upload dropped file at path \"%s\": %s",
                filepath, e
            )

    def delete_file(self, filepath, pid=None):
        """A file is about to removed and thus should be dumped right away."""
        self.add_pid(filepath, pid)
        self.dump_file(filepath)

        # Remove the filepath from the files list.
        self.files.pop(filepath.lower(), None)
        self.files_orig.pop(filepath.lower(), None)

    def move_file(self, oldfilepath, newfilepath, pid=None):
        """A file will be moved - track this change."""
        self.add_pid(oldfilepath, pid)
        if oldfilepath.lower() in self.files:
            # Replace the entry with the new filepath.
            self.files[newfilepath.lower()] = \
                self.files.pop(oldfilepath.lower(), [])

    def dump_files(self):
        """Dump all pending files."""
        while self.files:
            self.delete_file(self.files.keys()[0])
