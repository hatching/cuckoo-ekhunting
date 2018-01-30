# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import os
import logging

from cuckoo.core.database import Database
from cuckoo.common.objects import File, URL

log = logging.getLogger(__name__)
db = Database()

class Target(object):

    category_helpers = {
        "file": File,
        "archive": File,
        "url": URL,
    }

    def __init__(self):
        self.db_target = None
        self.target_dict = {}
        self.original = None

    def set_target(self, db_target):
        self.db_target = db_target
        self.target_dict = db_target.to_dict()
        helper = self.category_helpers.get(db_target.category)
        self.original = helper(db_target.target)

    def _create(self, target, helper, args):
        target = db.find_target(sha256=helper.get_sha256())
        if target:
            log.info(
                "Target '%s' (%s) already exists. Using existing target",
                target, args.get("category")
            )
            self.set_target(target)
            return target.id

        args.update(dict(
            target=target,
            crc32=helper.get_crc32(),
            md5=helper.get_md5(),
            sha1=helper.get_sha1(),
            sha256=helper.get_sha256(),
            sha512=helper.get_sha512(),
            ssdeep=helper.get_ssdeep()
        ))
        target = db.add_target(**args)
        if not target:
            log.error("Error adding new target")
            return None

        self.set_target(target)
        return target.id

    def create_url(self, url):
        url_helper = URL(url)

        if not url:
            log.error("Cannot create target for URL '%s', it is empty", url)
            return None

        args = dict(category="url")
        return self._create(url, url_helper, args)

    def create_file(self, file_path):
        file_helper = File(file_path)

        if not file_helper.valid():
            log.error(
                "Cannot create target for file '%s', file does not exist or is"
                " 0 bytes", file_path
            )
            return None

        args = dict(
            category="file",
            file_type=file_helper.get_type(),
            file_size=file_helper.get_size()
        )
        return self._create(file_path, file_helper, args)

    def create_archive(self, file_path):
        file_helper = File(file_path)

        if not file_helper.valid():
            log.error(
                "Cannot create target for archive '%s', file does not exist or"
                " is 0 bytes", file_path
            )
            return None

        args = dict(
            category="archive",
            file_type=file_helper.get_type(),
            file_size=file_helper.get_size()
        )
        return self._create(file_path, file_helper, args)

    @property
    def id(self):
        self.target_dict.get("id")

    @property
    def target(self):
        self.target_dict.get("target")

    @property
    def category(self):
        self.target_dict.get("category")

    @property
    def md5(self):
        self.target_dict.get("md5")

    @property
    def crc32(self):
        self.target_dict.get("crc32")

    @property
    def sha1(self):
        self.target_dict.get("sha1")

    @property
    def sha256(self):
        self.target_dict.get("sha256")

    @property
    def sha512(self):
        self.target_dict.get("sha512")

    @property
    def ssdeep(self):
        self.target_dict.get("ssdeep")

    @property
    def last_task(self):
        self.target_dict.get("last_task")

    @property
    def file_size(self):
        self.target_dict.get("file_size")

    @property
    def file_type(self):
        self.target_dict.get("file_type")