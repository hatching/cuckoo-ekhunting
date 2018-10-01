# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import gevent
import logging
import socket

from cuckoo.massurl.web import run_server
from cuckoo.massurl.scheduler import massurl_scheduler

log = logging.getLogger(__name__)

def massurl_main(host, port):
    log.debug("Starting massurl")
    gevent.spawn(massurl_scheduler)
    try:
        run_server(host, port)
    except socket.error as e:
        if e.errno == 98:
            log.error("Cannot use address:port combination: %s", e)
        else:
            log.exception("Error starting Massurl web: %s", e)
