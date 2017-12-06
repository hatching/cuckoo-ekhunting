# Copyright (C) 2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging

from cuckoo.common.config import config
from cuckoo.core.rooter import rooter

log = logging.getLogger(__name__)

class Route(object):

    def __init__(self, task, machine):
        self.task = task
        self.machine = machine
        self.interface = None
        self.rt_table = None
        self.route = None

    def route_network(self):
        """Enable network routing if desired."""
        # Determine the desired routing strategy (none, internet, VPN).
        self.route = self.task.options.get(
            "route", config("routing:routing:route")
        )

        if self.route == "none" or self.route == "drop":
            self.interface = None
            self.rt_table = None
        elif self.route == "inetsim":
            pass
        elif self.route == "tor":
            pass
        elif self.route == "internet":
            if config("routing:routing:internet") == "none":
                log.warning(
                    "Internet network routing has been specified, but not "
                    "configured, ignoring routing for this analysis", extra={
                        "action": "network.route",
                        "status": "error",
                        "route": self.route,
                    }
                )
                self.route = "none"
                self.task.options["route"] = "none"
                self.interface = None
                self.rt_table = None
            else:
                self.interface = config("routing:routing:internet")
                self.rt_table = config("routing:routing:rt_table")
        elif self.route in config("routing:vpn:vpns"):
            self.interface = config("routing:%s:interface" % self.route)
            self.rt_table = config("routing:%s:rt_table" % self.route)
        else:
            log.warning(
                "Unknown network routing destination specified, ignoring "
                "routing for this analysis: %r", self.route, extra={
                    "action": "network.route",
                    "status": "error",
                    "route": self.route,
                }
            )
            self.route = "none"
            self.task.options["route"] = "none"
            self.interface = None
            self.rt_table = None

        # Check if the network interface is still available. If a VPN dies for
        # some reason, its tunX interface will no longer be available.
        if self.interface and not rooter("nic_available", self.interface):
            log.error(
                "The network interface '%s' configured for this analysis is "
                "not available at the moment, switching to route=none mode.",
                self.interface, extra={
                    "action": "network.route",
                    "status": "error",
                    "route": self.route,
                }
            )
            self.route = "none"
            self.task.options["route"] = "none"
            self.interface = None
            self.rt_table = None

        # For now this doesn't work yet in combination with tor routing.
        if self.route == "drop" or self.route == "internet":
            rooter(
                "drop_enable", self.machine.ip,
                config("cuckoo:resultserver:ip"),
                str(config("cuckoo:resultserver:port"))
            )

        if self.route == "inetsim":
            machinery = config("cuckoo:cuckoo:machinery")
            rooter(
                "inetsim_enable", self.machine.ip,
                config("routing:inetsim:server"),
                config("%s:%s:interface" % (machinery, machinery)),
                str(config("cuckoo:resultserver:port"))
            )

        if self.route == "tor":
            rooter(
                "tor_enable", self.machine.ip,
                str(config("cuckoo:resultserver:ip")),
                str(config("routing:tor:dnsport")),
                str(config("routing:tor:proxyport"))
            )

        if self.interface:
            rooter(
                "forward_enable", self.machine.interface,
                self.interface, self.machine.ip
            )

        if self.rt_table:
            rooter(
                "srcroute_enable", self.rt_table, self.machine.ip
            )

    def unroute_network(self):
        """Disable any enabled network routing."""
        if self.interface:
            rooter(
                "forward_disable", self.machine.interface,
                self.interface, self.machine.ip
            )

        if self.rt_table:
            rooter(
                "srcroute_disable", self.rt_table, self.machine.ip
            )

        if self.route != "none":
            rooter(
                "drop_disable", self.machine.ip,
                config("cuckoo:resultserver:ip"),
                str(config("cuckoo:resultserver:port"))
            )

        if self.route == "inetsim":
            machinery = config("cuckoo:cuckoo:machinery")
            rooter(
                "inetsim_disable", self.machine.ip,
                config("routing:inetsim:server"),
                config("%s:%s:interface" % (machinery, machinery)),
                str(config("cuckoo:resultserver:port"))
            )

        if self.route == "tor":
            rooter(
                "tor_disable", self.machine.ip,
                str(config("cuckoo:resultserver:ip")),
                str(config("routing:tor:dnsport")),
                str(config("routing:tor:proxyport"))
            )

    def __repr__(self):
        return self.route