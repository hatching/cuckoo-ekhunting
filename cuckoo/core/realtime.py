# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import json
import logging
import threading
import time

from cuckoo.common.exceptions import (
    RealtimeCommandFailed, RealtimeBlockingExpired
)

log = logging.getLogger(__name__)


class RealTimeHandler(object):
    def __init__(self):
        self.cmd_id = 1
        self.command_cb = {}
        self.response_wait = {}
        self.subscribed = {}
        self.sock = None
        self.sendlock = threading.Lock()

    def start(self, sock):
        """RealTime connection has been established"""
        log.debug("Started Realtime handler")
        if self.sock:
            raise NotImplementedError("RealTime connection reopened")

        self.sock = sock

    def on_message(self, msg):
        """Is called by the resultserver when a realtime message arrives.
        Causes any callbacks, subscribed methods or response waiters to
        be called or receive their response."""
        response_id = msg.get("rid")
        if response_id is not None:
            # This is a response to a previous message
            callback = self.command_cb.get(response_id)
            if callback:
                log.debug(
                    "Calling response handler %s -> %r", response_id, callback
                )

                callback(msg)
                self.command_cb.pop(response_id)
            elif response_id in self.response_wait:
                self.response_wait[response_id] = msg

        else:
            # Search for subscribed methods for the message type.
            msg_type = msg.get("type")
            if not msg_type:
                return

            for func in self.subscribed.get(msg_type, set()):
                log.debug(
                    "Calling subscribed method '%s' for message of type '%s'",
                    func, msg_type
                )
                try:
                    func(msg)
                except Exception as e:
                    log.exception(
                        "Exception during calling of subscribed callback "
                        "function '%s'. %s", func, e
                    )

    def subscribe_callback(self, msg_type, func):
        """A method can be registered to this realtime handler. It will
        be called when a message that is not a reply is received and matches
        the subscribed callback

        @param msg_type: A string category that a guest->host message can
        contain
        @param func: A function obj that should be called that accepts a
        dictionary 'message'.
        """
        if msg_type not in self.subscribed:
            self.subscribed[msg_type] = set()

        log.debug(
            "Subscribed '%s' for incoming messages of type '%s'",
            msg_type, func
        )
        self.subscribed[msg_type].add(func)

    def send_command(self, command, callback=None):
        """Send a command to the guest over the realtime protocol. Blocks
        until it can acquire a sending lock.

        If a callback function is
        specified, it is called when receiving a response from the guest

        @param command: A dictionary containing a command category, method,
        args dict and response bool
        @param callback: A function obj that accepts a msg dict sent by the
        guest
        """
        self.sendlock.acquire()
        self.cmd_id += 1
        cmd_id = self.cmd_id
        try:
            command.update({"command_id": cmd_id})
            if callback:
                self.command_cb[cmd_id] = callback

            self.sock.write(json.dumps(command) + "\n")
        finally:
            self.sendlock.release()

        return cmd_id

    def send_command_blocking(self, command, maxwait=10):
        """Send a realtime command and block until a response comes in.
        Blocks until the response arrives or maxwait is reached.

        Raises RealtimeCommandFailed if the guest did not successfully execute
        the command.

        @param command: A command message dictionary
        @param maxwait: A max wait time in seconds
        """
        cmd_id = self.send_command(command)
        waited = 0
        self.response_wait[cmd_id] = None
        while waited < maxwait:
            if not self.response_wait.get(cmd_id):
                waited += 0.2
                time.sleep(0.2)
                continue

            response = self.response_wait.pop(cmd_id)
            if not response.get("success"):
                raise RealtimeCommandFailed(
                    "Guest raised exception during command execution. "
                    "Command: '%s'" % command
                )

            return response.get("return_data")

        raise RealtimeBlockingExpired(
            "Specified max blocking seconds: %s. Blocked for "
            "%s" % (maxwait, waited)
        )

class RealTimeMessages(object):
    """Generates the messages to send for a specific action"""

    @staticmethod
    def command(category, method, args={}, respond=True):
        return {
            "category": category,
            "method": method,
            "args": args or {},
            "respond": respond,
        }

    @staticmethod
    def stop_package(pkg_id, respond=True):
        """Stops the analysis package with the specified id"""
        return RealTimeMessages.command(
            category="analyzer", method="stop_package", respond=respond,
            args={"pkg_id": pkg_id}
        )

    @staticmethod
    def start_package(category, target, package=None, options={},
                      pkg_id=None, file_name=None, file_type=None,
                      respond=True):
        """Start an analysis package"""
        return RealTimeMessages.command(
            category="analyzer", method="start_package", respond=respond,
            args={
                "config": {
                    "category": category,
                    "target": target,
                    "package": package,
                    "file_name": file_name,
                    "file_type": file_type,
                    "pkg_id": pkg_id,
                    "options": options or {}
                }
            }
        )

    @staticmethod
    def list_packages():
        """Request the analyzer for a list of all pkg_ids and the types
        of analysis packages they refer to"""
        return RealTimeMessages.command(
            category="analyzer", method="list_packages", respond=True
        )

    @staticmethod
    def stop_analyzer():
        """Stop the analyzer, causing the finish routine"""
        return RealTimeMessages.command(
            category="analyzer", method="stop", respond=True
        )

    @staticmethod
    def dump_memory(pid):
        """Ask the analyzer to create a process memory dump for the
        specified pid"""
        return RealTimeMessages.command(
            category="analyzer", method="dump_memory", respond=True,
            args={
                "pid": pid
            }
        )

    @staticmethod
    def list_tracked_pids():
        """Ask the analyzer to return a list of tracked PIDs"""
        return RealTimeMessages.command(
            category="analyzer", method="list_tracked_pids", respond=True
        )
