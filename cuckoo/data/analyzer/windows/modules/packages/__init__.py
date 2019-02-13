# Copyright (C) 2010-2013 Claudio Guarnieri.
# Copyright (C) 2014-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

pkgs = []

import inspect
import pkgutil

from lib.common.abstracts import Package

for loader, fname, is_pkg in pkgutil.walk_packages(__path__):
    module = loader.find_module(fname).load_module(fname)

    for name, value in inspect.getmembers(module):
        if name.startswith('__') or name == Package.__name__:
            continue

        if not inspect.isclass(value) or not issubclass(value, Package):
            continue

        pkgs.append((fname, name, value))
