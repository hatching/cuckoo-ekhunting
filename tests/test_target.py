# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import os
import pytest
import shutil
import tempfile

from cuckoo.common.objects import File, URL
from cuckoo.core.database import Database
from cuckoo.core.target import Target
from cuckoo.main import cuckoo_create
from cuckoo.misc import set_cwd, cwd

class TestTask(object):

    def setup(self):
        set_cwd(tempfile.mkdtemp())
        cuckoo_create()
        self.db = Database()
        self.db.connect()
        self.t = Target()

    def teardown(self):
        cwd_path = cwd()
        if os.path.isdir(cwd_path):
            shutil.rmtree(cwd_path)

    def create_target_file(self, target=None):
        fileobj = File(target or __file__)
        return self.db.add_target(
            fileobj.file_path, "file", fileobj.get_crc32(), fileobj.get_md5(),
            fileobj.get_sha1(), fileobj.get_sha256(), fileobj.get_sha512(),
            file_type=fileobj.get_type(), file_size=fileobj.get_size()
        )

    def create_target_url(self, target=None):
        urlobj = URL(target or "http://example.com/")
        return self.db.add_target(
            urlobj.url, "url", urlobj.get_crc32(), urlobj.get_md5(),
            urlobj.get_sha1(), urlobj.get_sha256(), urlobj.get_sha512()
        )

    def test_set_target_file(self):
        id = self.create_target_file()
        db_target = self.db.find_target(id=id)
        f = File(__file__)
        self.t.set_target(db_target)
        assert self.t.id == id
        assert self.t.target == __file__
        assert self.t.category == "file"
        assert self.t.copied_binary == cwd(
            "storage", "binaries", f.get_sha256()
        )
        assert isinstance(self.t.helper, File)

    def test_set_target_url(self):
        id = self.create_target_url()
        db_target = self.db.find_target(id=id)
        self.t.set_target(db_target)
        assert self.t.id == id
        assert self.t.target == "http://example.com/"
        assert self.t.category == "url"
        assert self.t.copied_binary is None
        assert isinstance(self.t.helper, URL)
        assert self.t.is_file

    def test_target_init(self):
        id = self.create_target_file()
        db_target = self.db.find_target(id=id)
        t = Target(db_target)
        assert t.id == id
        assert t.target == __file__
        assert t.category == "file"

    def test_create_url(self):
        url = "http://example.com/42"
        id = self.t.create_url(url)
        urlobj = URL(url)

        assert id == 1
        assert self.t.target == url
        assert self.t.id == 1
        assert self.t.category == "url"
        assert self.t.crc32 == urlobj.get_crc32()
        assert self.t.md5 == urlobj.get_md5()
        assert self.t.sha1 == urlobj.get_sha1()
        assert self.t.sha256 == urlobj.get_sha256()
        assert self.t.sha512 == urlobj.get_sha512()
        assert self.t.ssdeep == urlobj.get_ssdeep()
        assert not self.t.is_file

    def test_create_url_duplicate(self):
        id1 = self.t.create_url("http://example.com/42")
        id2 = self.t.create_url("http://example.com/42")
        id3 = self.t.create_url("http://example.com/43")
        assert id1 is not None
        assert id1 == id2
        assert id3 != id1

    def test_invalid_url(self):
        t1 = self.t.create_url("")
        assert t1 is None

    def test_create_file(self):
        id = self.t.create_file(__file__)
        fileobj = File(__file__)

        assert id == 1
        assert self.t.target == __file__
        assert self.t.id == 1
        assert self.t.category == "file"
        assert self.t.crc32 == fileobj.get_crc32()
        assert self.t.md5 == fileobj.get_md5()
        assert self.t.sha1 == fileobj.get_sha1()
        assert self.t.sha256 == fileobj.get_sha256()
        assert self.t.sha512 == fileobj.get_sha512()
        assert self.t.ssdeep == fileobj.get_ssdeep()
        assert self.t.file_type == fileobj.get_type()
        assert self.t.file_size == fileobj.get_size()
        assert os.path.exists(cwd("storage", "binaries", fileobj.get_sha256()))
        assert self.t.is_file

    def test_create_file_duplicate(self):
        fd, path = tempfile.mkstemp()
        os.write(fd, os.urandom(8))
        os.close(fd)
        id1 = self.t.create_file(__file__)
        id2 = self.t.create_file(__file__)
        id3 = self.t.create_file(path)
        assert id1 is not None
        assert id1 == id2
        assert id3 != id1

    def test_create_file_invalid(self):
        # Non-existing path
        t1 = self.t.create_file("/tmp/doge/doge/doge/doge/42/doge")
        # Empty file
        fd, path = tempfile.mkstemp()
        t2 = self.t.create_file(path)
        # Dir, instead of file
        tmp_dir = tempfile.mkdtemp()
        t3 = self.t.create_file(tmp_dir)

        assert t1 is None
        assert t2 is None
        assert t3 is None

    def test_create_archive(self):
        archive = "tests/files/pdf0.zip"
        id = self.t.create_archive(archive)
        fileobj = File(archive)

        assert id == 1
        assert self.t.target == archive
        assert self.t.id == 1
        assert self.t.category == "archive"
        assert self.t.crc32 == fileobj.get_crc32()
        assert self.t.md5 == fileobj.get_md5()
        assert self.t.sha1 == fileobj.get_sha1()
        assert self.t.sha256 == fileobj.get_sha256()
        assert self.t.sha512 == fileobj.get_sha512()
        assert self.t.ssdeep == fileobj.get_ssdeep()
        assert self.t.file_type == fileobj.get_type()
        assert self.t.file_size == fileobj.get_size()
        assert os.path.exists(cwd("storage", "binaries", fileobj.get_sha256()))
        assert self.t.is_file

    def test_create_archive_duplicate(self):
        archive = "tests/files/pdf0.zip"
        id1 = self.t.create_archive(archive)
        id2 = self.t.create_archive(archive)
        id3 = self.t.create_archive(__file__)
        assert id1 is not None
        assert id1 == id2
        assert id3 != id1

    def test_create_archive_invalid(self):
        # Non-existing path
        t1 = self.t.create_archive("/tmp/doge/doge/doge/doge/42/doge")
        # Empty file
        fd, path = tempfile.mkstemp()
        t2 = self.t.create_archive(path)
        # Dir, instead of file
        tmp_dir = tempfile.mkdtemp()
        t3 = self.t.create_archive(tmp_dir)

        assert t1 is None
        assert t2 is None
        assert t3 is None

    def test_copy(self):
        fileobj = File(__file__)
        self.t.is_file = True
        self.t.target_dict = {
            "target": __file__,
            "sha256": fileobj.get_sha256()
        }
        copy_path = cwd("storage", "binaries", fileobj.get_sha256())
        assert not os.path.exists(copy_path)
        self.t.copy()
        assert os.path.isfile(copy_path)
        assert File(copy_path).get_sha256() == fileobj.get_sha256()

    @pytest.mark.skipif("sys.platform != 'linux2'")
    def test_symlink_to_task(self):
        fileobj = File(__file__)
        os.mkdir(cwd(analysis=1))
        copy_path = cwd("storage", "binaries", fileobj.get_sha256())
        symlink = cwd("binary", analysis=1)
        shutil.copyfile(__file__, copy_path)
        self.t.is_file = True
        self.t.target_dict = {
            "target": __file__,
            "sha256": fileobj.get_sha256()
        }
        assert not os.path.exists(symlink)
        self.t.symlink_to_task(1)
        assert os.path.isfile(symlink)
        assert os.path.realpath(symlink) == copy_path

    def test_copy_exists(self):
        fd, path = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        fileobj = File(path)
        self.t.create_file(path)
        copy_path = cwd("storage", "binaries", fileobj.get_sha256())
        assert os.path.isfile(copy_path)
        assert self.t.copy_exists()
        os.remove(copy_path)
        assert not self.t.copy_exists()

    def test_delete_original(self):
        fd, path = tempfile.mkstemp()
        os.write(fd, os.urandom(64))
        os.close(fd)
        self.t.create_file(path)
        assert os.path.exists(path)
        self.t.delete_original()
        assert not os.path.exists(path)

    def test_delete_copy(self):
        fd, path = tempfile.mkstemp()
        fileobj = File(path)
        os.write(fd, os.urandom(64))
        os.close(fd)
        self.t.create_file(path)
        copy_path = cwd("storage", "binaries", fileobj.get_sha256())
        assert os.path.exists(copy_path)
        self.t.delete_copy()
        assert not os.path.exists(copy_path)

    def test_getitem(self):
        t1 = self.t.create_file(__file__)
        fileobj = File(__file__)
        assert self.t["id"] == t1
        assert self.t["target"] == __file__
        assert self.t["category"] == "file"
        assert self.t["crc32"] == fileobj.get_crc32()
        assert self.t["md5"] == fileobj.get_md5()
        assert self.t["sha1"] == fileobj.get_sha1()
        assert self.t["sha256"] == fileobj.get_sha256()
        assert self.t["sha512"] == fileobj.get_sha512()
        assert self.t["ssdeep"] == fileobj.get_ssdeep()
        assert self.t["file_size"] == fileobj.get_size()
        assert self.t["file_type"] == fileobj.get_type()
        assert self.t["last_task"] is None

        with pytest.raises(KeyError):
            self.t["n0N3xisting"]

    def test_setitem(self):
        t1 = self.t.create_file(__file__)
        fileobj = File(__file__)
        self.t["id"] = 4500
        self.t["ssdeep"] = "WeepWoopDoges"
        self.t["target"] = "/tmp/such/target/very/wow"

        assert self.t.target_dict["id"] == 4500
        assert self.t.target_dict["ssdeep"] == "WeepWoopDoges"
        assert self.t.target_dict["target"] == "/tmp/such/target/very/wow"

    def test_properties(self):
        fileobj = File(__file__)
        self.t.target_dict = {
            "id": 42,
            "target": __file__,
            "category": "file",
            "crc32": fileobj.get_crc32(),
            "md5": fileobj.get_md5(),
            "sha1": fileobj.get_sha1(),
            "sha256": fileobj.get_sha256(),
            "sha512": fileobj.get_sha512(),
            "ssdeep": fileobj.get_ssdeep(),
            "file_size": fileobj.get_size(),
            "file_type": fileobj.get_type(),
            "last_task": 1337
        }

        assert self.t.id == 42
        assert self.t.target == __file__
        assert self.t.category == "file"
        assert self.t.crc32 == fileobj.get_crc32()
        assert self.t.md5 == fileobj.get_md5()
        assert self.t.sha1 == fileobj.get_sha1()
        assert self.t.sha256 == fileobj.get_sha256()
        assert self.t.sha512 == fileobj.get_sha512()
        assert self.t.ssdeep == fileobj.get_ssdeep()
        assert self.t.file_size == fileobj.get_size()
        assert self.t.file_type == fileobj.get_type()
        assert self.t.last_task == 1337

        with pytest.raises(AttributeError):
            self.t.nonexistingattribute42doges

    def test_file_categories(self):
        assert self.t.files == ["file", "archive"]

    def test_category_helpers(self):
        assert self.t.category_helpers["file"] == File
        assert self.t.category_helpers["archive"] == File
        assert self.t.category_helpers["url"] == URL