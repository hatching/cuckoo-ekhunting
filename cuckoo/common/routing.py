# Copyright (C) 2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import threading

from cuckoo.common.config import config
from cuckoo.common.exceptions import CuckooOperationalError
from cuckoo.core.database import Database
from cuckoo.core.rooter import rooter

log = logging.getLogger(__name__)
db = Database()

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
        elif self.route == "socks5":
            if not config("auxiliary:redsocks:enabled"):
                log.error(
                    "Socks5 network routing was specified, but the Redsocks "
                    "auxiliary module is disabled. This module is required to "
                    "use socks5 routing",  extra={
                        "action": "network.route",
                        "status": "error",
                        "route": self.route,
                    }
                )
                self.route = "none"
                self.task.options["route"] = "none"
                self.interface = None
                self.rt_table = None

            elif not self.task.options.get("socks5.localport"):
                log.warning(
                    "No redsocks instance was configured and started to"
                    " redirect traffic to a socks5 proxy. Setting route"
                    " to 'none'", extra={
                        "action": "network.route",
                        "status": "error",
                        "route": self.route,
                    }
                )
                self.route = "none"
                self.task.options["route"] = "none"
                self.interface = None
                self.rt_table = None

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
        elif self.route == "vpn":
            country = self.task.options.get("vpn.country")
            name = self.task.options.get("vpn.name")
            vpn = VPNManager.acquire(country=country, name=name)
            self.interface = vpn.get("interface")
            self.rt_table = vpn.get("rt_table")
            self.task.options["route"] = name

        elif self.route in config("routing:vpn:vpns"):
            vpn = VPNManager.acquire(name=self.route)
            self.interface = vpn.get("interface")
            self.rt_table = vpn.get("rt_table")
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
                str(config("cuckoo:resultserver:port")),
                config("routing:inetsim:ports") or ""
            )

        if self.route == "tor":
            rooter(
                "proxy_enable", self.machine.ip,
                str(config("cuckoo:resultserver:ip")),
                str(config("routing:tor:dnsport")),
                str(config("routing:tor:proxyport"))
            )

        if self.route == "socks5":
            rooter(
                "proxy_enable", self.machine.ip,
                str(config("cuckoo:resultserver:ip")),
                str(config("routing:socks5:dnsport")),
                str(self.task.options["socks5.localport"])
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

        if self.route == "drop" or self.route == "internet":
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
                str(config("cuckoo:resultserver:port")),
                config("routing:inetsim:ports") or ""
            )

        if self.route == "tor":
            rooter(
                "proxy_disable", self.machine.ip,
                str(config("cuckoo:resultserver:ip")),
                str(config("routing:tor:dnsport")),
                str(config("routing:tor:proxyport"))
            )

        if self.route == "socks5":
            rooter(
                "proxy_disable", self.machine.ip,
                str(config("cuckoo:resultserver:ip")),
                str(config("routing:socks5:dnsport")),
                str(self.task.options["socks5.localport"])
            )


class VPNManager(object):

    lock = threading.Lock()
    vpns = None

    @classmethod
    def init(cls):
        """Initialize the order VPN list. Used to round-robin VPN for Cuckoo
        tasks"""
        if cls.vpns is not None:
            raise CuckooOperationalError(
                "VPNManager initialization called after it has already been"
                " initialized."
            )

        cls.vpns = []

        used_vpns = set([
            task.route for task in
            db.list_tasks(
            filter_by="route", operators="!=", values="none", details=False,
            order_by="started_on", limit=len(config("routing:vpn:vpns"))
        )])

        vpns = []
        # Insert the vpn names in order, so that the last used vpns end up
        # at the end of the vpn list.
        for vpn in config("routing:vpn:vpns"):
            if vpn not in used_vpns:
                vpns.append(vpn)

        for used in used_vpns:
            if used in config("routing:vpn:vpns"):
                vpns.append(used)

        for vpn in vpns:
            cls.vpns.append({
                "name": config("routing:%s:name" % vpn),
                "country": config("routing:%s:country" % vpn),
                "description": config("routing:%s:description" % vpn),
                "interface": config("routing:%s:interface" % vpn),
                "rt_table": config("routing:%s:rt_table" % vpn)
            })

    @classmethod
    def acquire(cls, country=None, name=None):
        """Return a dictionary containing VPN info of the VPN that has not
        been used for the longest time."""
        cls.lock.acquire()
        use_vpn = None
        try:
            for vpn in cls.vpns:
                if country:
                    if vpn.get("country").lower() == country.lower():
                        use_vpn = vpn
                        break
                elif name:
                    if vpn.get("name") == name:
                        use_vpn = vpn
                        break
                else:
                    use_vpn = vpn
                    break

            # Move the entry back to the list.
            cls.vpns.remove(vpn)
            cls.vpns.append(vpn)
        finally:
            cls.lock.release()

        return use_vpn
