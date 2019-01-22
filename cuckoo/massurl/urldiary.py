# Copyright (C) 2018-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import json
import logging
import os
import time
import uuid

from elasticsearch import helpers
from elasticsearch.exceptions import TransportError, ConnectionError

from cuckoo.common.config import config
from cuckoo.common.elastic import elasticmassurl
from cuckoo.common.exceptions import CuckooStartupError
from cuckoo.misc import cwd

log = logging.getLogger(__name__)

class URLDiaries(object):

    init_done = False
    DIARY_INDEX = "urldiary"
    DIARY_MAPPING = "urldiary"
    RELATED_INDEX = "related"
    RELATED_MAPPING = "related"

    @classmethod
    def init(cls):
        elasticmassurl.init()
        elasticmassurl.connect()
        cls.DIARY_INDEX = config("massurl:elasticsearch:diary_index")
        cls.RELATED_INDEX = config("massurl:elasticsearch:related_index")
        try:
            cls.create_mappings()
        except ConnectionError as e:
            log.error("Could not connect to Elasticsearch: %s", e)
            return False

        cls.init_done = True
        return True

    @classmethod
    def create_mappings(cls):
        mappings = {
            cls.DIARY_INDEX: {
                "file": "diary-mapping.json",
                "name": cls.DIARY_MAPPING
            },
            cls.RELATED_INDEX: {
                "file": "related-request-mapping.json",
                "name": cls.RELATED_MAPPING
            }
        }
        for indexname, info in mappings.iteritems():
            mapping_path = cwd("elasticsearch", info.get("file"))

            if elasticmassurl.client.indices.exists_type(
                    index=indexname, doc_type=info.get("name")
            ):
                continue

            if not os.path.exists(mapping_path):
                raise CuckooStartupError(
                    "Missing required Elasticsearch mapping file: '%s'" %
                    mapping_path
                )

            try:
                with open(mapping_path, "rb") as fp:
                    mapping = json.loads(fp.read())
            except ValueError as e:
                raise CuckooStartupError(
                    "Failed to load Elasticsearch mapping '%s'."
                    " Invalid JSON. %s" % (mapping_path, e)
                )

            log.info("Creating index and mapping for '%s'", indexname)
            elasticmassurl.client.indices.create(indexname, body=mapping)

    @classmethod
    def store_diary(cls, diary, diary_id=None):
        """Store the specified URL diary under the specified id"""
        diary_id = diary_id or uuid.uuid1()
        try:
            elasticmassurl.client.create(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING, id=diary_id,
                body=diary
            )
        except TransportError as e:
            log.exception("Error during diary creation. %s", e)
            return None
        return diary_id

    @classmethod
    def get_diary(cls, diary_id):
        """Find a specified URL diary"""
        try:
            res = elasticmassurl.client.search(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING, size=1,
                sort="datetime:desc",
                body={
                    "query": {
                        "match": {"_id": diary_id}
                    }
                }
            )
        except TransportError as e:
            log.exception("Error during diary lookup. %s", e)
            return None

        return URLDiaries.get_values(res, return_empty=None, listed=False)

    @classmethod
    def get_latest_diary(cls, url_id, return_fields="version"):
        try:
            res = elasticmassurl.client.search(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING, size=1,
                sort="datetime:desc", _source_include=return_fields or None,
                body={
                    "query": {
                        "match": {"url_id": url_id}
                    }
                }
            )
        except TransportError as e:
            log.exception("Error during diary lookup. %s", e)
            return None

        return URLDiaries.get_values(res, return_empty=None, listed=False)

    @classmethod
    def list_diary_url_id(cls, url_id, size=50, return_fields="", offset=0):
        """Find all URL diaries for a url id
        @param offset: search for smaller than the provided the millisecond
        time stamp"""
        query = {
            "query": {
                "bool": {
                    "must": {
                        "match": {"url_id": url_id}
                    }
                }
            }
        }
        if offset:
            query["query"]["bool"]["filter"] = {
                "range": {
                    "datetime": {"lt": offset}
                }
            }
        try:
            res = elasticmassurl.client.search(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING, size=size,
                sort="datetime:desc", _source_include=return_fields,
                body=query
            )
        except TransportError as e:
            log.exception("Error during diary lookup. %s", e)
            return None

        return URLDiaries.get_values(res, return_empty=[])

    @classmethod
    def store_related(cls, parent_uuid, related):
        """Store a list of related request objects. Objects must be related
        to the specified URL diary parent"""
        related_ids = []
        ready_related = []
        for r in related:
            r["parent"] = parent_uuid
            related_id = str(uuid.uuid1())
            related_ids.append(related_id)
            ready_related.append({
                "_id": related_id,
                "_index": cls.RELATED_INDEX,
                "_mapping": cls.RELATED_MAPPING,
                "_source": r
            })
        try:
            helpers.bulk(elasticmassurl.client, ready_related)
        except TransportError as e:
            log.exception("Error while bulk storing related data to")
            return None

        return related_ids

    @classmethod
    def get_related(cls, parent_uuid, max_size=100):
        """Find all related streams for a URL given diary uuid"""
        # TODO implement offsets
        try:
            res = elasticmassurl.client.search(
                index=cls.RELATED_INDEX, doc_type=cls.RELATED_MAPPING,
                size=max_size, body={
                    "query": {
                        "match": {"parent": parent_uuid}
                    }
                }
            )
        except TransportError as e:
            log.exception(
                "Error while retrieving related streams to parent: '%s'. %s",
                parent_uuid, e
            )
            return None

        return URLDiaries.get_values(res, return_empty=[])

    @classmethod
    def get_related_ids(cls, ids=[]):
        """Retrieve the specified related requests by id"""
        ids = ids if isinstance(ids, (list, tuple, set)) else []
        try:
            res = elasticmassurl.client.search(
                index=cls.RELATED_INDEX, doc_type=cls.RELATED_MAPPING,
                body={
                    "query": {
                        "ids": {"values": ids}
                    }
                }
            )
        except TransportError as e:
            log.exception("Error while retrieving related streams. %s", e)
            return None

        return URLDiaries.get_values(res, return_empty=[])

    @classmethod
    def search_diaries(cls, needle, return_fields="datetime,url,version",
                       size=50, offset=0):
        """Search all URL diaries for needle and return a list objs
        containing return_fields
        @param offset: search for smaller than the provided the millisecond
        time stamp
        """
        query = {
            "query": {
                "bool": {
                    "must": {
                        "query_string": {"query": "%s" % needle[:128]}
                    }
                }
            }
        }
        if offset:
            query["query"]["bool"]["filter"] = {
                "range": {"datetime": {"lt": offset}}
        }
        try:
            res = elasticmassurl.client.search(
                timeout="60s", index=cls.DIARY_INDEX,
                _source_include=return_fields, sort="datetime:desc", size=size,
                doc_type=cls.DIARY_MAPPING, body=query
            )
        except TransportError as e:
            log.exception("Error while searching diaries. %s", e)
            return None

        return URLDiaries.get_values(res, return_empty=[])

    @staticmethod
    def get_values(res, return_empty=[], addid=True, listed=True):
        """Return a list of objs without ES metadata"""
        hits = res.get("hits", {})
        if hits.get("total", 0) < 1:
            return return_empty

        if len(hits.get("hits", [])) == 1 and not listed:
            return hits.get("hits", [{}])[0].get("_source", {})

        if addid:
            ret = []
            for h in hits.get("hits", []):
                h["_source"]["id"] = h["_id"]
                ret.append(h["_source"])
            return ret

        return [r.get("_source") for r in hits.get("hits", [])]

class URLDiary(object):
    def __init__(self, url):
        self._diary = {
            "url": url,
            # TODO get URL id from massurl in the analysis manager without an
            # extra query to the db.
            "url_id": 0,
            # TODO Set version properly. We need the url_id for that
            "version": 0,
            "datetime": "",
            "javascript": [],
            "related_documents": [],
            "requested_urls": [],
            "signatures": []
        }

    def add_javascript(self, javascript):
        self._diary["javascript"].append(javascript)

    def add_related_docs(self, doc_keys):
        self._diary["related_documents"].extend(doc_keys)

    def add_signature(self, signature):
        if isinstance(signature, list):
            self._diary["signatures"].extend(signature)
        else:
            self._diary["signatures"].append(signature)

    def add_request_url(self, url):
        self._diary["requested_urls"].append({
            "len": len(url),
            "url": url
        })

    def dump(self):
        self._diary["datetime"] = int(time.time() * 1000)
        return self._diary
