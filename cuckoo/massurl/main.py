# Copyright (C) 2018-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import socket
import sys

import gevent

from cuckoo.common.config import config
from cuckoo.massurl.realtime import ev_client
from cuckoo.massurl.scheduler import massurl_scheduler
from cuckoo.massurl.urldiary import URLDiaries
from cuckoo.massurl.web import run_server

log = logging.getLogger(__name__)

def massurl_main(host, port):
    if not config("massurl:massurl:enabled"):
        log.error(
            "MassURL is not enabled. The mass url dashboard requires "
            "Elasticsearch to operate. Please enable it and configure"
            " Elasticsearch in your massurl.conf"
        )
        sys.exit(1)

    ev_client.do_run = True
    if not ev_client.connect(maxtries=2):
        log.error(
            "Could not connect to Cuckoo event messaging server at: %s:%s",
            ev_client.ip, ev_client.port
        )
        sys.exit(1)

    gevent.spawn(ev_client.start_nonblocking)

    # Initiate Elasticsearch client
    if not URLDiaries.init():
        log.error("Failed to start massurl server")
        sys.exit(1)

    if not ev_client.connected:
        log.error(
            "Cuckoo event messaging server disconnected the event client"
        )
        sys.exit(1)

    log.debug("Starting massurl")

    gevent.spawn(massurl_scheduler)
    try:
        run_server(host, port)
    except socket.error as e:
        if e.errno == 98:
            log.error("Cannot use address:port combination: %s", e)
        else:
            log.exception("Error starting Massurl web: %s", e)
    finally:
        ev_client.stop()
