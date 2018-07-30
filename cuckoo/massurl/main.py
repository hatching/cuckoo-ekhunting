# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import gevent

from cuckoo.massurl.web import run_server
from cuckoo.massurl.scheduler import massurl_scheduler

log = logging.getLogger(__name__)

def massurl_main():
    log.debug("Starting massurl")
    gevent.spawn(massurl_scheduler)
    run_server(9911, "::")
