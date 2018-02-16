# Copyright (C) 2010-2013 Claudio Guarnieri.
# Copyright (C) 2014-2016 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import os
import logging

from cuckoo.common.abstracts import Processing
from cuckoo.common.config import emit_options
from cuckoo.common.objects import File
from cuckoo.misc import cwd, version

log = logging.getLogger(__name__)

class AnalysisInfo(Processing):
    """General information about analysis session."""

    def run(self):
        """Run information gathering.
        @return: information dict.
        """
        self.key = "info"

        # Get git head.
        if os.path.exists(cwd(".cwd")):
            git_head = git_fetch_head = open(cwd(".cwd"), "rb").read()
        else:
            log.warning(
                "No .cwd file was found in the Cuckoo Working Directory. Did "
                "you correctly setup the CWD?"
            )
            git_head = git_fetch_head = None

        # Monitor.
        monitor = cwd("monitor", self.task["options"].get("monitor", "latest"))
        if os.path.islink(monitor):
            monitor = os.readlink(monitor)
        elif os.path.isfile(monitor):
            monitor = open(monitor, "rb").read().strip()
        elif os.path.isdir(monitor):
            monitor = os.path.basename(monitor)
        else:
            monitor = None

        return dict(
            version=version,
            git={
                "head": git_head,
                "fetch_head": git_fetch_head,
            },
            monitor=monitor,
            added=self.task.get("added_on"),
            started=self.task["started_on"],
            ended=self.task.get("completed_on", "none"),
            duration=self.task.get("duration", -1),
            id=int(self.task["id"]),
            category=self.task["category"],
            custom=self.task["custom"],
            owner=self.task["owner"],
            package=self.task["package"],
            platform=self.task["platform"],
            options=emit_options(self.task["options"]),
            route=self.task["route"],
        )

class MetaInfo(Processing):
    """General information about the task and output files (memory dumps, etc)."""

    def run(self):
        """Run information gathering.
        @return: information dict.
        """
        self.key = "metadata"

        def reformat(x):
            # kinda ugly absolute -> relative
            relpath = x[len(self.analysis_path):].lstrip("/")

            dirname = os.path.dirname(relpath)
            basename = os.path.basename(relpath)
            return dict(dirname=dirname or "",
                        basename=basename,
                        sha256=File(x).get_sha256())

        meta = {
            "output": {},
        }

        if os.path.exists(self.pcap_path):
            meta["output"]["pcap"] = reformat(self.pcap_path)

        infos = [
            (self.pmemory_path, "memdumps"),
            (self.buffer_path, "buffers"),
            (self.dropped_path, "dropped"),
        ]

        for path, key in infos:
            if os.path.exists(path):
                contents = os.listdir(path)
                if contents:
                    meta["output"][key] = [reformat(os.path.join(path, i)) for i in contents]

        return meta
