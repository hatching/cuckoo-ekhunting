# Copyright (C) 2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

from cuckoo.core.plugins import enumerate_plugins
from cuckoo.common.abstracts import AnalysisManager

plugins = enumerate_plugins(
    __file__, "cuckoo.analysis", globals(), AnalysisManager
)
