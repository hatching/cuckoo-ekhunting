# Copyright (C) 2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import subprocess
import time

from _winreg import HKEY_LOCAL_MACHINE
from lib.common.abstracts import Package

log = logging.getLogger(__name__)

class Edge(Package):
    """Windows 10 Edge analysis package."""
    PATHS = [
        ("System32", "cmd.exe")
    ]

    REGKEYS = [
       [
            HKEY_LOCAL_MACHINE,
            "Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System",
            {
                # Disable Security Settings Check.
                "FilterAdministratorToken": 1,
            },
       ]
    ]

    def get_edge_pids(self):
        wmic = "C:\\Windows\\System32\\wbem\\WMIC.exe"
        pipe = subprocess.Popen(
            [
                wmic, "process", "where", "name like 'MicrosoftEdge%%'",
                "get", "processId"
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        pids = []
        while True:
            line = pipe.stdout.readline()
            if not line:
                break
            data = line.strip()
            if data and data.isdigit():
                pids.append(int(data))

        return pids

    def start(self, urls):
        if not isinstance(urls, list):
            urls = [urls]

        cmd_path = self.get_path("cmd.exe")
        all_pids = set()

        for url in urls:
            edge = "shell:AppsFolder\Microsoft.MicrosoftEdge_" \
                   "8wekyb3d8bbwe!MicrosoftEdge"
            args = ["/c", "start", edge, "-private", url]
            self.execute(cmd_path, args=args)
            time.sleep(0.5)
            edge_pids = self.get_edge_pids()
            this_url = set(edge_pids) - all_pids

            for pid in this_url:
                all_pids.add(pid)
                self.pids_targets[pid] = url

        all_pids = list(all_pids)
        self.initial_pids = all_pids

        return all_pids
