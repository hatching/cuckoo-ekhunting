# Copyright (C) 2016-2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import mock
import os
import pytest
import subprocess
import socket
import tempfile

from cuckoo.auxiliary.sniffer import Sniffer
from cuckoo.auxiliary.redsocks import Redsocks
from cuckoo.common.abstracts import Auxiliary
from cuckoo.common.exceptions import (
    CuckooOperationalError, CuckooDisableModule
)
from cuckoo.misc import set_cwd, cwd, getuser, is_windows

def test_init():
    a = Auxiliary()
    a.set_options({
        "aux": "iliary",
    })
    assert a.options["aux"] == "iliary"
    assert a.options.aux == "iliary"

class BasePopen(object):
    pid = 0x4141

    def poll(self):
        return False

    def terminate(self):
        pass

    def communicate(self):
        return "", (
            "1 packet captured\n"
            "X packets captured\n"
            "1 packet dropped by kernel\n"
            "Y packets dropped by kernel\n"
            "1 packet received by filter\n"
            "Z packets received by filter\n"
        )

class PopenStdout(BasePopen):
    def communicate(self):
        return "stdout", "tcpdump: listening on foobar\nX packets captured\n"

class PopenStderr(BasePopen):
    def communicate(self):
        return "", "not a standard error message"

class PopenPermissionDenied(BasePopen):
    def poll(self):
        return True

class task(object):
    id = 42
    options = {}

    def __init__(self, options={}):
        self.options = options

class machine(object):
    interface = "interface"
    options = {}
    ip = "1.2.3.4"
    resultserver_ip = "1.1.1.1"
    resultserver_port = 1234

class fake_socks5(object):
    def __init__(self, host, port, username=None, password=None,
                 country="Dogeland"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.country = country

def test_sniffer():
    set_cwd(tempfile.mkdtemp())

    s = Sniffer()
    s.set_task(task)
    s.set_machine(machine)
    s.set_options({
        "tcpdump": __file__,
        "bpf": None,
    })

    with mock.patch("subprocess.Popen") as p:
        p.return_value = BasePopen()
        assert s.start() is True

    user = getuser()
    if user:
        user = "-Z %s " % user

    # Test regular setup.
    command = (
        "%s -U -q -s 0 -n -i interface %s-w %s "
        "host 1.2.3.4 and "
        "not ( dst host 1.2.3.4 and dst port 8000 ) and "
        "not ( src host 1.2.3.4 and src port 8000 ) and "
        "not ( dst host 1.1.1.1 and dst port 1234 ) and "
        "not ( src host 1.1.1.1 and src port 1234 )" % (
            __file__, user or "",
            cwd("storage", "analyses", "42", "dump.pcap")
        )
    )

    if is_windows():
        p.assert_called_once_with(
            command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    else:
        p.assert_called_once_with(
            command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True
        )

    assert s.stop() is None

    # Test a bpf rule.
    s.options["bpf"] = "not arp"
    with mock.patch("subprocess.Popen") as p:
        p.return_value = BasePopen()
        assert s.start() is True

    if is_windows():
        p.assert_called_once_with(
            command.split() + ["and", "(", "not arp", ")"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    else:
        p.assert_called_once_with(
            command.split() + ["and", "(", "not arp", ")"],
            close_fds=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

    assert s.stop() is None

    # Test an invalid executable path.
    with mock.patch("os.path.exists") as p:
        p.return_value = False
        assert s.start() is False

    # Test permission denied on tcpdump.
    with mock.patch("subprocess.Popen") as p:
        p.return_value = PopenPermissionDenied()
        assert s.start() is True

    with pytest.raises(CuckooOperationalError) as e:
        assert s.stop()
    e.match("the network traffic during the")
    e.match("denied-for-tcpdump")

    # Test stdout output from tcpdump.
    with mock.patch("subprocess.Popen") as p:
        p.return_value = PopenStdout()
        assert s.start() is True

    with pytest.raises(CuckooOperationalError) as e:
        assert s.stop()
    e.match("did not expect standard output")

    # Test unknown stderr output from tcpdump.
    with mock.patch("subprocess.Popen") as p:
        p.return_value = PopenStderr()
        assert s.start() is True

    with pytest.raises(CuckooOperationalError) as e:
        assert s.stop()
    e.match("following standard error output")

    # Test OSError and/or ValueError exceptions.
    with mock.patch("subprocess.Popen") as p:
        p.side_effect = OSError("this is awkward")
        assert s.start() is False

    with mock.patch("subprocess.Popen") as p:
        p.side_effect = ValueError("this is awkward")
        assert s.start() is False


class TestRedSocks(object):

    def setup(self):
        self.r = Redsocks()

    def test_none_route(self):
        self.r.set_task(task({"route": "none"}))
        self.r.set_options({})
        assert not self.r.start()

    def test_no_route(self):
        self.r.set_task(task())
        self.r.set_options({})
        assert not self.r.start()

    @mock.patch("cuckoo.auxiliary.redsocks.is_linux")
    def test_unsupported_platform(self, mi):
        mi.return_value = False
        self.r.set_task(task({"route": "socks5"}))
        self.r.set_options({})

        with pytest.raises(CuckooDisableModule):
            self.r.start()

    @mock.patch("cuckoo.auxiliary.redsocks.socks5_manager")
    @mock.patch("cuckoo.auxiliary.redsocks.is_linux")
    def test_no_socks_country(self, mi, ms):
        ms.acquire.return_value = None
        self.r.set_task(task({
            "route": "socks5",
            "socks5.country": "germany"
        }))
        self.r.set_options({})

        with pytest.raises(CuckooDisableModule):
            self.r.start()
        ms.acquire.assert_called_once_with(country="germany")

    @mock.patch("cuckoo.auxiliary.redsocks.socks5_manager")
    @mock.patch("cuckoo.auxiliary.redsocks.is_linux")
    def test_no_socks(self, mi, ms):
        ms.acquire.return_value = None
        self.r.set_task(task({
            "route": "socks5"
        }))
        self.r.set_options({})

        with pytest.raises(CuckooDisableModule):
            self.r.start()
        ms.acquire.assert_called_once_with(country=None)

    @mock.patch("cuckoo.auxiliary.redsocks.subprocess.Popen")
    @mock.patch("cuckoo.auxiliary.redsocks.cwd")
    @mock.patch("cuckoo.auxiliary.redsocks.config")
    @mock.patch("cuckoo.auxiliary.redsocks.socks5_manager")
    @mock.patch("cuckoo.auxiliary.redsocks.is_linux")
    def test_start(self, mi, ms, mc, mw, mp):
        ms.acquire.return_value = fake_socks5("example.com", 4242)
        mc.return_value = "192.168.56.1"
        mw.return_value = "/tmp/redsocks.log"
        process = mock.MagicMock()
        process.pid = 1337
        mp.return_value = process
        self.r.gen_config = mock.MagicMock(return_value="/tmp/config.conf")
        self.r.get_tcp_port = mock.MagicMock(return_value=45000)
        self.r.set_task(task({
            "route": "socks5"
        }))
        self.r.set_options({"redsocks":"/usr/sbin/redsocks"})

        self.r.start()

        self.r.gen_config.assert_called_once_with(
            "/tmp/redsocks.log", "192.168.56.1", 45000, "example.com",
            4242, None, None
        )
        mp.assert_called_once_with(
            ["/usr/sbin/redsocks", "-c", "/tmp/config.conf"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True
        )
        assert self.r.process is process
        assert self.r.task.options["socks5.host"] == "example.com"
        assert self.r.task.options["socks5.port"] == 4242
        assert self.r.task.options["socks5.localport"] == 45000

    @mock.patch("cuckoo.auxiliary.redsocks.subprocess.Popen")
    @mock.patch("cuckoo.auxiliary.redsocks.cwd")
    @mock.patch("cuckoo.auxiliary.redsocks.config")
    @mock.patch("cuckoo.auxiliary.redsocks.socks5_manager")
    @mock.patch("cuckoo.auxiliary.redsocks.is_linux")
    def test_start_fail(self, mi, ms, mc, mw, mp):
        ms.acquire.return_value = fake_socks5("example.com", 4242)
        mc.return_value = "192.168.56.1"
        mw.return_value = "/tmp/redsocks.log"
        process = mock.MagicMock()
        process.pid = 1337
        mp.return_value = process
        mp.side_effect = OSError
        self.r.gen_config = mock.MagicMock(return_value="/tmp/config.conf")
        self.r.get_tcp_port = mock.MagicMock(return_value=45000)
        self.r.set_task(task({
            "route": "socks5"
        }))
        self.r.set_options({"redsocks":"/usr/sbin/redsocks"})

        with pytest.raises(OSError):
            self.r.start()
        assert self.r.task.options.get("socks5.localport") is None

    def test_stop_process_none(self):
        self.r.process = None
        assert not self.r.stop()

    def test_stop_crashed(self):
        self.r.process = mock.MagicMock()
        self.r.process.poll.return_value = 1234
        self.r.process.communicate.return_value = ("", "SuperError")

        with pytest.raises(CuckooOperationalError):
            self.r.stop()

    @mock.patch("os.remove")
    def test_stop_error(self, mr):
        self.r.process = mock.MagicMock()
        self.r.process.poll.return_value = False
        self.r.process.terminate.side_effect = OSError

        self.r.stop()
        self.r.process.kill.assert_called_once()

    @mock.patch("cuckoo.auxiliary.redsocks.config")
    @mock.patch("os.remove")
    def test_stop(self, mo, mc):
        self.r.process = mock.MagicMock()
        self.r.process.poll.return_value = False
        mc.return_value = True
        self.r.conf_path = "/tmp/aaaa/someconfig.conf"

        self.r.stop()
        mo.assert_called_once_with("/tmp/aaaa/someconfig.conf")

    def test_gen_config(self):
        self.r.set_task(task())
        path = self.r.gen_config(
            "/tmp/redsocks.log", "192.168.56.1", 4242, "example.com", 1337
        )

        correct = open(
            os.path.join("tests", "files", "redsocks.conf"), "r"
        ).read()
        generated = open(path, "r").read()

        assert correct == generated

    def test_get_tcp_port(self):
        port = self.r.get_tcp_port("127.0.0.1")
        assert port > 0
        assert port < 65535

        # Try to bind on the returned port to see if it is actually free
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", port))
            s.close()
        except Exception as e:
            pytest.fail(
                "get_tcp_port returned unsable port. See exception: %s" % e
            )
