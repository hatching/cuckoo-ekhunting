# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import os
import socket
import subprocess

from socks5man.manager import Manager

from cuckoo.common.abstracts import Auxiliary
from cuckoo.common.config import config
from cuckoo.common.exceptions import (
    CuckooDisableModule, CuckooOperationalError
)
from cuckoo.common.files import Files
from cuckoo.misc import cwd, is_linux

log = logging.getLogger(__name__)
socks5_manager = Manager()

class Redsocks(Auxiliary):
    """
    Retrieves an operational SOCKS5 proxy according to the choices stored in
    the options of a task. The SOCKS5 proxy is retrieved using socks5man.

    The Redsocks process is started by the module and is provided with a config
    of the chosen proxy server. The host and port of the proxy are stored
    back in the task options so that they can be used for routing in the
    analysis manager.

    The analysis manager can then use this to redirect all network traffic for
    a single analysis through the chosen proxy.
    """

    def start(self):
        """Retrieve an operational socks5 proxy and start redsocks
        with a config for this proxy."""
        self.process = None
        self.conf_path = None

        if self.task.options.get("route", "") != "socks5":
            return False

        if not is_linux():
            log.warning(
                "The Redsocks module is currently only supported on Linux"
            )
            raise CuckooDisableModule

        country = self.task.options.get("socks5.country")
        socks5 = socks5_manager.acquire(country=country)
        if not socks5:
            if country:
                log.error(
                    "Cannot start forwarding traffic over socks5. "
                    "No operational socks5 server available for country: %s",
                    country
                )
            else:
                log.error(
                    "Cannot start forwarding traffic over socks5. No "
                    "operational socks5 server available"
                )
            raise CuckooDisableModule

        log.debug("Using socks5 proxy in country: %s", socks5.country)

        local_ip = config("cuckoo:resultserver:ip")
        local_port = self.get_tcp_port(local_ip)
        logfile = cwd("redsocks.log", analysis=self.task.id)

        self.conf_path = self.gen_config(
            logfile, local_ip, local_port, socks5.host, socks5.port,
            socks5.username, socks5.password
        )

        try:
            self.process = subprocess.Popen(
                [self.options.redsocks, "-c", self.conf_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True
            )
        except (OSError, ValueError) as e:
            log.exception(
                "Failed to start redsocks (config=%s). Error: %s",
                self.conf_path, e
            )
            raise

        self.task.options["socks5.host"] = socks5.host
        self.task.options["socks5.port"] = socks5.port
        self.task.options["socks5.localport"] = local_port

        log.info(
            "Started redsocks with PID: %s (local_port=%s, config=%s)",
            self.process.pid, local_port, self.conf_path
        )

    def stop(self):
        """Stop the redsocks process"""
        if not self.process:
            return False

        if self.process.poll():
            stdout, stderr = self.process.communicate()
            raise CuckooOperationalError(
                "The redsocks process has exited unexpectedly. This can mean"
                " the network traffic was not forwarded during the analysis."
                "Stdout = '%s', stderr = '%s'" % (stdout, stderr)
            )

        try:
            self.process.terminate()
        except OSError as e:
            log.error("Error terminating redsocks process: %s", e)
            try:
                self.process.kill()
            except Exception as e:
                log.exception(
                    "Unable to stop redsocks process with PID: %s."
                    " Error: %s", self.process.pid, e
                )
        finally:
            if config("auxiliary:redsocks:delete_config"):
                os.remove(self.conf_path)

    def gen_config(self, logfile, local_ip, local_port, socks5_host,
                   socks5_port, username=None, password=None):
        """Generate and writea redsocks config file to be used for
         one analysis"""

        conf_base = {
            "log_debug": "on",
            "log_info": "on",
            "log": "\"file:%s\"" % logfile,
            "daemon": "off",
            "redirector": "iptables"
        }

        conf_redsocks = {
            "local_ip": local_ip,
            "local_port": str(local_port),
            "ip": socks5_host,
            "port": str(socks5_port),
            "type": "socks5"
        }

        conf_sections = {
            "base": conf_base,
            "redsocks": conf_redsocks
        }

        if username:
            conf_redsocks["login"] = username
            conf_redsocks["password"] = password

        conf = ""
        for name, section in conf_sections.iteritems():
            conf += "%s {\n" % name
            for field, value in section.iteritems():
                conf += "%s = %s;\n" % (field, value)
            conf += "}\n"

        return Files.temp_named_put(conf, "redsocks-task-%s" % self.task.id)

    def get_tcp_port(self, bind_ip):
        """Bind to the resultserver IP to retrieve an available TCP port"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((bind_ip, 0))
        tcp_port = s.getsockname()[1]
        s.close()

        return tcp_port
