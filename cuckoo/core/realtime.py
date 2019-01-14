# Copyright (C) 2018-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import json
import logging
import threading
import time
import socket
import select
import errno

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

class EventMessageServer(object):
    """A server that is responsible for receiving and relaying events sends
    by part of Cuckoo over a network. It can be used to receive events about
    actions Cuckoo is performing.

    All communication is in the form of JSON messages.
    """

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.do_run = True
        self.insocks = [self.sock]
        self.outsocks = []
        self.mes_handlers = {}
        self.mesqueue = []
        self.subscriptions = {}
        self.whitelist = []
        self.protaction_handlers = {
            "subscribe": self._handle_subscribe,
            "unsubscribe": self._handle_unsubscribe
        }

    @property
    def all_meshandlers(self):
        return [
            sockinfo.get("handler")
            for sock, sockinfo in self.mes_handlers.iteritems()
        ]

    def start(self):
        # TODO get IP + port from config
        self.sock.bind(('', 1337))
        self.sock.listen(5)

    def stop(self):
        """Stop the server loop"""
        self.do_run = False

    def finalize(self):
        """Stop the handling of clients and messages, sent out a shutdown
        event, try to close all connections and stops the listen socket"""
        shutdown_message = EventClient.event_message(
            "control", {"action": "shutdown"}
        )
        self.queue_message(shutdown_message, "", broadcast=True)
        self.relay_messages(outsocks=self.outsocks)
        for mes_handler in self.all_meshandlers:
            mes_handler.close()

        try:
            self.sock.close()
        except socket.error as e:
            log.exception("Error while closing event server socket. %s", e)

    def queue_message(self, mes_body, address, broadcast=False):
        """Queue a message to be sent to hosts subscribed to that event or
        broadcast it to all connected hosts."""
        self.mesqueue.append((mes_body, address, broadcast))

    def handle_incoming(self, message, mes_handler):
        mes_type = message.get("type")

        if not mes_type:
            log.error("Received message without a type, ignoring")
            return

        mes_body = message.get("body")
        if not mes_body or not isinstance(mes_body, dict):
            log.error("Received message without or an invalid body, ignoring")
            return

        if mes_type == "protocol":
            protaction = message.get("action")
            if not protaction or not isinstance(protaction, basestring):
                log.error(
                    "Received protocol message without or invalid action,"
                    " ignoring"
                )
                return

            handler = self.protaction_handlers.get(protaction)
            if not handler:
                log.debug("Unknown protocol action specified")
                return

            handler(mes_body, mes_handler)

        elif mes_type == "event":
            if not isinstance(mes_body, dict):
                log.debug("Received message body for event must be a dict")
                return

            self.queue_message(mes_body, mes_handler.address)
        else:
            log.debug("Received unknown message type '%r', ignoring", mes_type)

    def _handle_subscribe(self, mes_body, mes_handler):
        """Subscribes the specified client socket to the events specified in
        the message body"""
        event_types = mes_body.get("events")
        if not event_types:
            log.debug("Received subscribe request without event types")
            return

        event_types = set(event_types)

        for ev_type in event_types:
            if not isinstance(ev_type, basestring):
                continue

            if ev_type not in self.subscriptions:
                self.subscriptions[ev_type] = set()

            self.mes_handlers[mes_handler.sock]["subscribed"].add(ev_type)
            self.subscriptions[ev_type].add(mes_handler)

    def _handle_unsubscribe(self, mes_body, mes_handler):
        """Unsubscribes a client socket from the events specified in the
         message body"""
        event_types = mes_body.get("events")
        if not event_types:
            log.debug("Received unsubscribe request without event types")
            return

        event_types = set(event_types)

        for ev_type in event_types:
            if not isinstance(ev_type, basestring):
                continue

            if mes_handler not in self.subscriptions.get(ev_type, []):
                continue

            self.subscriptions[ev_type].remove(mes_handler)
            self.mes_handlers[mes_handler.sock]["subscribed"].remove(ev_type)

    def cleanup_client(self, insock):
        """Cleanup references and settings for a specific client socket"""
        # Close the client socket and cleanup after that
        mes_handler = self.mes_handlers[insock].get("handler")
        mes_handler.close()

        for ev_type in self.mes_handlers[insock].get("subscribed"):
            self.subscriptions[ev_type].remove(mes_handler)

            # If no subscribers are left for an event type, remove it
            if not self.subscriptions[ev_type]:
                del self.subscriptions[ev_type]

        del self.mes_handlers[insock]
        self.insocks.remove(insock)
        self.outsocks.remove(insock)

    def handle_new_client(self, insock, ip):
        """Create a new entry in a client socket info helpers"""
        self.insocks.append(insock)
        self.outsocks.append(insock)
        self.mes_handlers[insock] = {
            "handler": MessageHandler(insock, ip),
            "subscribed": set()
        }

    def relay_messages(self, outsocks):
        """Send out all queued messages to their subscribers. Only send the
        message if its socket exists in outsocks

        @param outsocks: A list of sockets that are ready to receive
        """
        for c in range(len(self.mesqueue)):
            message, sender, broadcast = self.mesqueue.pop(0)

            receivers = set()
            # Send a message to all client sockets on broadcast
            if broadcast:
                receivers = self.all_meshandlers
            else:
                receivers = self.subscriptions.get(message.get("event"))

            if not receivers:
                return

            for mes_handler in receivers:
                if mes_handler.sock in outsocks:
                    try:
                        mes_handler.send_json_message(message)
                    except socket.error as e:
                        log.error(
                            "Failed to send message to: %r. Error: %s",
                            mes_handler.address, e
                        )

    def handle(self):
        """Handles incoming and outgoing messages"""
        try:
            while self.do_run:
                insocks, outsocks, err = select.select(
                    self.insocks, self.outsocks, [], 3
                )
                for sock in insocks:
                    if sock is self.sock:
                        # Accept new connection from client
                        insock, ip = sock.accept()
                        # TODO Verify if IP is on the whitelist
                        self.handle_new_client(insock, ip)

                    else:
                        mes_handler = self.mes_handlers[sock].get("handler")
                        data = mes_handler.get_json_message()

                        # Read incoming data until next newline
                        if data:
                            while True:
                                self.handle_incoming(data, mes_handler)
                                if not mes_handler.buffered_message():
                                    break

                                data = mes_handler.get_json_message()
                        else:
                            # No  data, but a disconnect. Handle removing
                            # subscriptions and deleting references
                            self.cleanup_client(sock)

                if self.mesqueue:
                    self.relay_messages(outsocks)

        finally:
            try:
                self.finalize()
            except socket.error:
                pass

class MessageHandler(object):
    # 5 MB JSON blob
    MAX_INFO_BUF = 5 * 1024 * 1024

    def __init__(self, clientsock, address=""):
        self.sock = clientsock
        self.address = address
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
                raise EOFError("Last byte is: %r" % self.rcvbuf[:1])

            self.rcvbuf += buf

    def _read(self, amount=4096):
        return self.sock.recv(amount)

    def clear_buf(self):
        self.rcvbuf = ""

    def buffered_message(self):
        return len(self.rcvbuf) > 0

    def get_json_message(self):
        message = ""
        try:
            message = self.readline()
        except EOFError as e:
            log.debug("Unexpected end of message. %s", e)
            self.clear_buf()
        except ValueError as e:
            log.warning(e)
            self.clear_buf()

        if not message:
            return None

        try:
            message = json.loads(message)
        except ValueError:
            log.debug("Invalid JSON message, ignoring")
            return None

        return message

    def send_json_message(self, mes_dict):
        self.send_message(json.dumps(mes_dict) + "\n")

    def send_message(self, message):
        # Try to send a message over the socket. Handle socket errors.
        # or handle them were send method is used?
        self.sock.sendall(message)

    def close(self):
        try:
            self.sock.close()
        except socket.error:
            pass

class EventClient(object):
    """Client that connects to a Cuckoo event messaging server and allows for
    the sending of events. The client can subscribe to and unsubscribe from
    events. When subscribing to an event, a callback method must be given.
    This callback will be called for each received event of the
    subscribed types."""

    def __init__(self, eventserver_ip="127.0.0.1", eventserver_port=4237):
        self.ip = eventserver_ip
        self.port = eventserver_port
        self.sock = None
        self.subscribed = {}
        self.connected = False
        self.do_run = False
        self.mesqueue = []
        self.mes_handler = None
        self.sublock = threading.Lock()
        self.queuelock = threading.Lock()

    def connect(self):
        """Connect to the given Cuckoo event server until successful"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.sock.settimeout(30)
        self.connected = False

        log.debug("Connecting to event message server")
        while self.do_run and True:
            try:
                self.sock.connect((self.ip, self.port))
                self.connected = True
                self.mes_handler = MessageHandler(self.sock)
                break
            except socket.error as e:
                log.error("Failed to connect to event message server. %s", e)
                time.sleep(3)

    def queue_message(self, message):
        """Queues the given message
        @param message: A dictionary containing a message type and a body field
        containing another dictionary.
        """
        try:
            self.queuelock.acquire(True)
            self.mesqueue.append(message)
        finally:
            self.queuelock.release()

    def subscribe(self, callback_method, event_types):
        """Subscribe the given callback method to the specified event type(s).
        For each received of the given type, this method will be called with
        the event message as its only parameter."""
        if not isinstance(event_types, (list, tuple, set)):
            event_types = set([event_types])

        subto = []
        try:
            self.sublock.acquire(True)
            for event_type in event_types:
                if event_type not in self.subscribed:
                    self.subscribed[event_type] = set()
                    subto.append(event_type)

                self.subscribed[event_type].add(callback_method)
        finally:
            self.sublock.release()

        self.queue_message(EventClient.protmes_subscribe(subto))

    def unsubscribe(self, callback_method, event_types):
        """Unsubscribe the given callback method from the given event
        type(s)."""
        if not isinstance(event_types, (list, tuple, set)):
            event_types = set([event_types])

        unsubfrom = []
        try:
            self.sublock.acquire(True)
            for event_type in event_types:
                if event_type not in self.subscribed:
                    continue

                self.subscribed[event_type].remove(callback_method)

                if not self.subscribed[event_type]:
                    del self.subscribed[event_type]
                    unsubfrom.append(event_type)
        finally:
            self.sublock.release()

        self.queue_message(EventClient.protmes_unsubscribe(unsubfrom))

    def send_event(self, event_type, body={}):
        """Queues an event in the correct event sending format"""
        self.queue_message(self.event_message(event_type, body))

    def handle_incoming(self):
        """Read incoming event messages and call the callbacks that
        are subscribed to this event type."""
        while True:
            event = self.mes_handler.get_json_message()
            if not event:
                break

            event_type = event.get("event")
            if not event_type:
                break

            try:
                self.sublock.acquire(True)
                for subscribe_callback in self.subscribed.get(event_type, []):
                    try:
                        subscribe_callback(event)
                    except Exception as e:
                        log.exception(
                            "Error in event subscription callback for"
                            " event %r. %s", event_type, e
                        )
            finally:
                self.sublock.release()

            if not self.mes_handler.buffered_message():
                break

    def handle_outgoing(self):
        """Send out all queued messages"""
        try:
            self.queuelock.acquire(True)
            for c in range(len(self.mesqueue)):
                message = self.mesqueue.pop(0)
                try:
                    self.mes_handler.send_json_message(message)
                except ValueError:
                    pass
        finally:
            self.queuelock.release()

    def finalize(self):
        try:
            self.sock.close()
        except socket.error:
            pass

    def _run(self):
        """Handle incoming messages and send out queued messages"""
        try:
            while self.do_run:
                if not self.connected:
                    self.connect()

                try:
                    insock, outsock, err = select.select(
                        [self.sock], [self.sock], [], 5
                    )

                    if insock:
                        self.handle_incoming()
                    if outsock and self.mesqueue:
                        self.handle_outgoing()

                except socket.error as e:
                    log.error("Failed to read or send a message: %s", e)
                    if e.errno in (errno.ECONNRESET, errno.ECONNABORTED, errno.EC):
                        self.connected = False
                        self.mes_handler.close()

        finally:
            self.finalize()

    def start(self):
        """Start the messaging client. It is automatically started in a new
        thread. It can be stopped using the 'stop' method."""
        if self.do_run:
            return

        self.do_run = True
        self.connect()
        threading.Thread(target=self._run).start()

    def stop(self):
        self.do_run = False

    @staticmethod
    def _protmes(action, body={}):
        return {
            "type": "protocol",
            "action": action,
            "body": body
        }

    @staticmethod
    def event_message(event_type, body={}):
         return {
            "type": "event",
            "body": {
                "event": event_type,
                "body": body
            }
        }

    @staticmethod
    def protmes_subscribe(event_types):
        if not isinstance(event_types, (list, tuple)):
            event_types = [event_types]

        return EventClient._protmes("subscribe", {"events": event_types})

    @staticmethod
    def protmes_unsubscribe(event_types):
        if not isinstance(event_types, (list, tuple)):
            event_types = [event_types]

        return EventClient._protmes("subscribe", {"events": event_types})
