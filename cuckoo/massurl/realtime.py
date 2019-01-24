# Copyright (C) 2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

from cuckoo.common.config import config
from cuckoo.core.realtime import EventClient

ev_client = EventClient(
    config("massurl:eventserver:ip"), config("massurl:eventserver:port")
)
