# Copyright (C) 2010-2013 Claudio Guarnieri.
# Copyright (C) 2014-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

from lib.common.abstracts import Package

class Firefox(Package):
    """Firefox analysis package."""
    PATHS = [
        ("ProgramFiles", "Mozilla Firefox", "firefox.exe"),
    ]

    def start(self, target):
        firefox = self.get_path("Firefox")
        if not isinstance(target, (list, tuple)):
            target = [target]

        pids = []
        for url in target:
            pid = self.execute(
                firefox, args=["-new-window", url], maximize=True
            )
            if pid:
                pids.append(pid)

        return pids
