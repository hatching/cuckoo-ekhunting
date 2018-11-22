# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import errno
import json
import logging
import select
import socket
import threading
import time

from lib.common.exceptions import CuckooError

log = logging.getLogger(__name__)

class CommandMessage(object):

    used_ids = []
    minimum_fields = {
        "command_id": int,
        "category": basestring,
        "method": basestring
    }

    def __init__(self, _unparsed_message):
        self._unparsed_message = _unparsed_message
        self.json_message = {}

    def validate(self):
        try:
            self.json_message = json.loads(self._unparsed_message)
            self._unparsed_message = ""
        except ValueError:
            log.exception("Invalid JSON sent by host")
            return False

        for key, value in self.minimum_fields.iteritems():
            val = self.json_message.get(key)
            if not val or not isinstance(val, value):
                log.error(
                    "Missing field '%s' or invalid value. Type should be: %s. "
                    "Data: '%r'", key, value, val
                )
                return False

        command_id = self.json_message.get("command_id")
        if command_id in CommandMessage.used_ids:
            return False

        CommandMessage.used_ids.append(command_id)

        return True

    @property
    def command_id(self):
        return self.json_message.get("command_id")

    @property
    def category(self):
        return self.json_message.get("category")

    @property
    def module(self):
        return self.json_message.get("module")

    @property
    def method(self):
        return self.json_message.get("method")

    @property
    def args(self):
        args = self.json_message.get("args", {})
        if not isinstance(args, dict):
            return {}
        return args

    @property
    def respond(self):
        return self.json_message.get("respond", False)

class MessageReader(object):

    # 50 MB JSON blob
    MAX_INFO_BUF = 1024 * 51200

    def __init__(self, sock):
        self.socket = sock
        self.rcvbuf = ""

    def readline(self):
        while True:
            offset = self.rcvbuf.find("\n")
            if offset >= 0:
                l, self.rcvbuf = self.rcvbuf[:offset], self.rcvbuf[offset + 1:]
                return l

            if len(self.rcvbuf) >= self.MAX_INFO_BUF:
                raise ValueError(
                    "Received message exceeds %s bytes" % self.MAX_INFO_BUF
                )
            buf = self._read()
            if not buf:
                raise EOFError("Last byte is: '%r'" % self.rcvbuf[:1])

            self.rcvbuf += buf

    def _read(self, amount=4096):
        return self.socket.recv(amount)

    def clear_buf(self):
        self.rcvbuf = ""

    def buffered_message(self):
        return len(self.rcvbuf) > 0

    def get_json_message(self):
        message = ""
        try:
            message = self.readline()
        except EOFError as e:
            log.exception("Unexpected end of message. %s", e)
            self.clear_buf()
        except ValueError as e:
            log.exception(e)
            self.clear_buf()

        if not message:
            return None

        message = CommandMessage(message)
        if not message.validate():
            return None

        return message

class CommandHandler(object):
    """Finds the correct method in the correct module or class, executes it,
    and makes the result accessible."""

    def __init__(self, analyzer):
        self.analyzer = analyzer
        self.last_return = None
        self.handlers = {
            "analyzer": self.handle_analyzer,
            "auxiliary": self.handle_aux
        }

    def _run_command(self, module, method, message):
        return_data = None
        try:
            run_command = getattr(module, method)
            return_data = run_command(**message.args)
        except Exception as e:
            log.exception("Failed to run command: '%s'", e)
            return False, None
        return True, return_data

    def handle_command(self, message):
        self.last_return = None
        handler = self.handlers.get(message.category)
        if not handler:
            log.error(
                "No available handler for category: %r", message.category
            )
            return False

        module = handler(message)
        if module:
            success, data = self._run_command(
                module, message.method, message
            )
            if success:
                log.debug(
                    "Successfully executed method '%r' on '%r'",
                    message.method, module
                )
            else:
                log.error(
                    "Failed to execute method '%r' on '%r'",
                    message.method, module
                )
            self.last_return = data
            return success

    def handle_aux(self, message):
        if not message.module:
            log.error("No module specified in auxiliary command")
            return False

        aux = self.analyzer.auxiliaries.get(message.module)
        if not aux:
            log.error("Module '%r' is not currently running", message.module)
            return False

        return aux

    def handle_analyzer(self, message):
        return self.analyzer

class MessageClient(threading.Thread):

    def __init__(self, resultserver_ip, command_port, analyzer):
        super(MessageClient, self).__init__()
        self.server_ip = resultserver_ip
        self.port = command_port
        self.socket = None
        self.do_run = True
        self.sendqueue = []
        self.mesreader = None
        self.analyzer = analyzer
        self.connected = False
        self.cmdhandler = CommandHandler(self.analyzer)

    def connect(self):
        tries = 0
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Set keep alive so that the connection is not closed when idle
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.socket.settimeout(10)
        while True:
            log.info("Setting up connection for realtime communication")
            try:
                self.socket.connect((self.server_ip, self.port))
                self.connected = True
                self.socket.sendall("REALTIME\n")
                break
            except socket.error as e:
                tries += 1
                log.exception("Error connecting back to resultserver: %s", e)

                if tries >= 3:
                    raise CuckooError("Error when connecting to host: %s" % e)

                # Wait a few seconds before trying to connect again
                time.sleep(tries * 5)

        self.mesreader = MessageReader(self.socket)

    def stop(self):
        self.do_run = False
        try:
            self.socket.close()
        except socket.error as e:
            log.exception("Error while closing command socket. %s", e)

    def queue_message(self, type="message", data={}, command_id=None):
        data.update({
            "type": type,
            "rid": command_id
        })
        self.sendqueue.append(data)

    def handle_messages(self):
        while True:
            command_message = self.mesreader.get_json_message()
            if not command_message:
                continue

            success = self.cmdhandler.handle_command(command_message)
            if command_message.respond:

                # Verify if the return data is json serializable.
                try:
                    json.dumps(self.cmdhandler.last_return)
                except TypeError:
                    self.cmdhandler.last_return = None

                self.queue_message(
                    type="response", command_id=command_message.command_id,
                    data={
                        "success": success,
                        "executed": "%s - %s" % (
                            command_message.category, command_message.method
                        ),
                        "return_data": self.cmdhandler.last_return
                    }
                )

            if not self.mesreader.buffered_message():
                break

    def send_messages(self):
        for c in range(len(self.sendqueue)):
            message = self.sendqueue.pop(0)
            try:
                message = json.dumps(message)
            except ValueError:
                log.exception("Failed to dump message to json")
                continue

            message += "\n"

            self.socket.sendall(message)

    def run(self):
        """"Run the command handler. Reads and sends messages, and calls
        the appropriate handlers for incoming messages"""
        while self.do_run:
            # If the realtime connection is not connected and the analyzer
            # is still running, try to reconnect.
            if not self.connected:
                if self.analyzer.runtime < int(self.analyzer.config.timeout):
                    if self.analyzer.is_running:
                        self.connect()

            try:
                infds, outfds, errfds = select.select(
                    [self.socket], [self.socket], [], 5
                )
                if len(infds) != 0:
                    self.handle_messages()

                if len(outfds) != 0:
                    self.send_messages()

            except socket.error as e:
                log.exception("Error reading or sending message: %s", e)
                if e.errno in (errno.ECONNRESET, errno.ECONNABORTED):
                    self.connected = False

            except Exception as e:
                log.exception("Exception in command handler: %s", e)
                raise e
