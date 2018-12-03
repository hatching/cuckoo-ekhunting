# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import logging
import uuid

from elasticsearch import helpers
from elasticsearch.exceptions import TransportError

from cuckoo.common.elastic import elastic

log = logging.getLogger(__name__)

class URLDiaries(object):

    DIARY_INDEX = "urldiary"
    DIARY_MAPPING = "urldiary"
    RELATED_INDEX = "related"
    RELATED_MAPPING = "related"

    @classmethod
    def init(cls):
        elastic.init()
        elastic.connect()

    @classmethod
    def store_diary(cls, diary, diary_id):
        """Store the specified URL diary under the specified id"""
        try:
            elastic.client.create(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING, id=diary_id,
                body=diary
            )
        except TransportError as e:
            log.exception("Error during diary creation. %s", e)
            return None

    @classmethod
    def get_diary(cls, diary_id):
        """Find a specified URL diary"""
        try:
            res = elastic.client.search(
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
    def list_diary_url_id(cls, url_id, size=50, return_fields=""):
        """Find all URL diaries for a url id"""
        # TODO implement offsets
        try:
            res = elastic.client.search(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING, size=size,
                sort="datetime:desc", _source_include=return_fields,
                body={
                    "query": {
                        "match": {"url_id": url_id}
                    }
                }
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
            ready_related.append({
                "_id": related_id,
                "_index": cls.RELATED_INDEX,
                "_mapping": cls.RELATED_MAPPING,
                "_source": r
            })
        try:
            helpers.bulk(elastic.client, ready_related)
        except TransportError as e:
            log.exception("Error while bulk storing related data to")
            return None

        return related_ids

    @classmethod
    def get_related(cls, parent_uuid, max_size=100):
        """Find all related streams for a URL given diary uuid"""
        # TODO implement offsets
        try:
            res = elastic.client.search(
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
            res = elastic.client.search(
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
                       size=50):
        """Search all URL diaries for needle and return a list objs
        containing return_fields"""
        # TODO implement offsets
        try:
            res = elastic.client.search(
                timeout="60s", index=cls.DIARY_INDEX,
                _source_include=return_fields, sort="datetime:desc", size=size,
                doc_type=cls.DIARY_MAPPING, body={
                    "query": {
                        "query_string": {"query": "%s" % needle[:128]}
                    }
                }
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

        if hits.get("total", 0) == 1 and listed:
            return hits.get("hits", [{}])[0].get("_source", {})

        if addid:
            ret = []
            for h in hits.get("hits", []):
                h["_source"]["id"] = h["_id"]
                ret.append(h["_source"])
            return ret

        return [r.get("_source") for r in hits.get("hits", [])]
