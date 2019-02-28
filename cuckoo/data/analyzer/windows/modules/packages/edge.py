# Copyright (C) 2010-2013 Claudio Guarnieri.
# Copyright (C) 2014-2016 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import os
from _winreg import HKEY_LOCAL_MACHINE
from lib.common.abstracts import Package
import time
import subprocess
log = logging.getLogger(__name__)

class Edge(Package):
    """Javascript analysis package."""
    PATHS = [
        #("ProgramFiles", "Internet Explorer", "iexplore.exe"),
        #("Windows", "explorer.exe"),
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
       ],
       [
            HKEY_LOCAL_MACHINE,
            "Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\UIPI",
            {
                "": "1"
            }
       ]
    ]

    def get_edge_pids(self):
        command = 'wmic process where "name like \'MicrosoftEdge%%\'" get processid'
	pipe = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

	pid = []
	while True:
	    line = pipe.stdout.readline()
	    if line:
	        data = line.strip()
		if data.isdigit():
		    pid.append(data)
		else:
		    break
	return pid

    def start(self, urls):
        if not isinstance(urls, list):
            urls = [urls]

        #for path in self.enum_paths():
        #    log.critical(path)

        cmd_path = self.get_path("cmd.exe")

        for url in urls:
            args = ["/c", "start", "shell:AppsFolder\Microsoft.MicrosoftEdge_8wekyb3d8bbwe!MicrosoftEdge -private {}".format(url)]
            self.execute(cmd_path, args=args)
            time.sleep(2)
            pids = self.get_edge_pids()
            this_url = set(pids) - set(self.pids) 

            for pid in this_url:
                self.pids_targets[pid] = url

`           self.pids = self.initial_pids = pids

        log.critical("pids %s", str(self.pids))
        return self.pids[0]

