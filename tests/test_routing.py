# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import mock
import os
import pytest
import shutil
import tempfile

from cuckoo.common import abstracts
from cuckoo.common import config
from cuckoo.core.database import Database
from cuckoo.core.init import write_cuckoo_conf
from cuckoo.main import cuckoo_create
from cuckoo.misc import set_cwd
from cuckoo.common.routing import Route

class FakeTask(object):
    def __init__(self, options={}):
        self.id = 1
        self.options = {} or options

class FakeMachine(object):
    def __init__(self):
        self.name = "machine1"
        self.label = "machine1"
        self.ip = "192.168.56.10"
        self.platform = "windows"
        self.options = ""
        self.interface = "tap0"
        self.snapshot = ""
        self.resultserver_ip = "192.168.56.1"
        self.resultserver_port = 4242
        self.manager = "virtualbox"
        self.locked = True

class TestRoute(object):
    def setup_class(self):
        self.cwd = tempfile.mkdtemp()
        set_cwd(self.cwd)
        cuckoo_create()
        self.db = Database()
        self.db.connect()

    def teardown_class(self):
        if os.path.isdir(self.cwd):
            shutil.rmtree(self.cwd)

    @mock.patch("cuckoo.common.routing.rooter")
    def test_route_network_none(self, mr):
        route = Route(FakeTask(), FakeMachine())
        route.route_network()

        assert route.route == "none"
        assert route.interface is None
        assert route.rt_table is None
        mr.assert_not_called()

    @mock.patch("cuckoo.common.routing.rooter")
    def test_route_network_inetsim(self, mr):
        route = Route(FakeTask(options={"route": "inetsim"}), FakeMachine())
        route.route_network()

        assert route.route == "inetsim"
        assert route.interface is None
        assert route.rt_table is None
        mr.assert_called_once_with(
            "inetsim_enable", "192.168.56.10", "192.168.56.1",
            "vboxnet0", "2042", ""
        )

    @mock.patch("cuckoo.common.routing.rooter")
    def test_route_network_internet(self, mr):
        write_cuckoo_conf(cfg={
            "routing": {
                "routing": {
                    "internet": "eth0"
                }
            }
        })
        # Clear config cache so it will load new values
        config._cache = {}
        mr.return_value = True
        route = Route(FakeTask(options={"route": "internet"}), FakeMachine())
        route.route_network()

        assert route.route == "internet"
        assert route.interface == "eth0"
        assert route.rt_table == "main"
        mr.assert_has_calls([
            mock.call("nic_available", "eth0"),
            mock.call("drop_enable", "192.168.56.10", "192.168.56.1", "2042"),
            mock.call("forward_enable", "tap0", "eth0", "192.168.56.10"),
            mock.call("srcroute_enable", "main", "192.168.56.10")
        ])

    @mock.patch("cuckoo.common.routing.rooter")
    def test_route_network_tor(self, mr):
        route = Route(FakeTask(options={"route": "tor"}), FakeMachine())
        route.route_network()

        assert route.route == "tor"
        assert route.interface is None
        assert route.rt_table is None
        mr.assert_called_once_with(
            "tor_enable", "192.168.56.10", "192.168.56.1", "5353", "9040"
        )

    @mock.patch("cuckoo.common.routing.rooter")
    def test_route_network_drop(self, mr):
        route = Route(FakeTask(options={"route": "drop"}), FakeMachine())
        route.route_network()

        assert route.route == "drop"
        assert route.interface is None
        assert route.rt_table is None
        mr.assert_called_once_with(
            "drop_enable", "192.168.56.10", "192.168.56.1", "2042"
        )

    @mock.patch("cuckoo.common.routing.rooter")
    def test_route_network_vpn(self, mr):
        mr.return_value = True
        route = Route(FakeTask(options={"route": "vpn0"}), FakeMachine())
        route.route_network()

        assert route.route == "vpn0"
        assert route.interface == "tun0"
        assert route.rt_table == "tun0"
        mr.assert_has_calls([
            mock.call("nic_available", "tun0"),
            mock.call("forward_enable", "tap0", "tun0", "192.168.56.10"),
            mock.call("srcroute_enable", "tun0", "192.168.56.10")
        ])

    @mock.patch("cuckoo.common.routing.rooter")
    def test_unroute_network_none(self, mr):
        route = Route(FakeTask(), FakeMachine())
        route.route = "none"
        route.unroute_network()

        mr.assert_not_called()

    @mock.patch("cuckoo.common.routing.rooter")
    def test_unroute_network_vpn(self, mr):
        route = Route(FakeTask(), FakeMachine())
        route.route = "vpn0"
        route.unroute_network()
        route.rt_table = "tun0"
        route.interface = "tun0"
        route.unroute_network()

        mr.assert_has_calls([
            mock.call("forward_disable", "tap0", "tun0", "192.168.56.10"),
            mock.call("srcroute_disable", "tun0", "192.168.56.10"),
        ])

    @mock.patch("cuckoo.common.routing.rooter")
    def test_unroute_network_inetsim(self, mr):
        route = Route(FakeTask(), FakeMachine())
        route.route = "inetsim"
        route.unroute_network()

        mr.assert_has_calls([
            mock.call(
                "inetsim_disable", "192.168.56.10", "192.168.56.1", "vboxnet0",
                "2042", ""
            )
        ])

    @mock.patch("cuckoo.common.routing.rooter")
    def test_unroute_network_tor(self, mr):
        route = Route(FakeTask(), FakeMachine())
        route.route = "tor"
        route.unroute_network()

        mr.assert_has_calls([
            mock.call(
                "tor_disable", "192.168.56.10", "192.168.56.1", "5353", "9040"
            )
        ])