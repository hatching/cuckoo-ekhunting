# Copyright (C) 2018-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import json
import logging
import os
import time
import uuid

import dpkt

from elasticsearch import helpers
from elasticsearch.exceptions import TransportError, ConnectionError
from httpreplay.cut import http_handler, https_handler
from httpreplay.misc import read_tlsmaster
from httpreplay.reader import PcapReader
from httpreplay.smegma import TCPPacketStreamer

from cuckoo.common.config import config
from cuckoo.common.elastic import elasticmassurl
from cuckoo.common.exceptions import CuckooStartupError
from cuckoo.misc import cwd

log = logging.getLogger(__name__)

class URLDiaries(object):

    init_done = False
    DIARY_INDEX = "urldiary"
    DIARY_MAPPING = "urldiary"
    REQUEST_LOG_INDEX = "requestlog"
    REQUEST_LOG_MAPPING = "requestlog"

    @classmethod
    def init(cls):
        elasticmassurl.init()
        elasticmassurl.connect()
        cls.DIARY_INDEX = config("massurl:elasticsearch:diary_index")
        cls.REQUEST_LOG_INDEX = config("massurl:elasticsearch:related_index")
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
                "file": "massurl-diary.json",
                "name": cls.DIARY_MAPPING
            },
            cls.REQUEST_LOG_INDEX: {
                "file": "massurl-requestlog.json",
                "name": cls.REQUEST_LOG_MAPPING
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
    def store_diary(cls, urldiary, diary_id=None):
        """Store the specified URL diary under a generated or the
        specified id"""
        diary_id = diary_id or str(uuid.uuid1())

        request_log_ids = {
            url: str(uuid.uuid1()) for url in urldiary.urls
        }

        # Store all per-url request logs in a separate index first with the
        # specified IDs. Store these IDs in the URL diary.
        if cls.store_request_logs(urldiary.logs, diary_id, request_log_ids):
            urldiary.set_requestlog_ids(request_log_ids)

        urldiary = urldiary.dump()
        version = cls.get_latest_diary(urldiary.get("url_id"))
        if version:
            version = version.get("version", 1) + 1
        else:
            version = 1

        urldiary["version"] = version
        try:
            elasticmassurl.client.create(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING, id=diary_id,
                body=urldiary
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
    def store_request_logs(cls, request_logs, parent_uuid, request_log_ids):
        """Store a list of related request objects. Objects must be related
        to the specified URL diary parent
        @param request_log_ids: a dict of url:identifier"""
        ready_logs = []
        for r in request_logs:
            r["parent"] = parent_uuid
            r["datetime"] = int(time.time() * 1000)
            ready_logs.append(json.dumps({
                "_id": request_log_ids.get(r.get("url")),
                "_index": cls.REQUEST_LOG_INDEX,
                "_type": cls.REQUEST_LOG_MAPPING,
                "_source": r
            }, encoding="latin1"))
        try:
            helpers.bulk(
                elasticmassurl.client,
                [json.loads(requestlog) for requestlog in ready_logs]
            )
        except TransportError as e:
            log.exception("Error while bulk storing request logs data")
            return False
        return True

    @classmethod
    def get_request_log(cls, requestlog_id):
        """Find request log with given ID"""
        try:
            res = elasticmassurl.client.search(
                index=cls.REQUEST_LOG_INDEX,doc_type=cls.REQUEST_LOG_MAPPING,
                size=1, sort="datetime:desc",
                body={
                    "query": {
                        "match": {"_id": requestlog_id}
                    }
                }
            )
        except TransportError as e:
            log.exception("Error during request log lookup. %s", e)
            return None

        return URLDiaries.get_values(res, return_empty=None, listed=False)

    @classmethod
    def get_related_ids(cls, ids=[]):
        """Retrieve the specified related requests by id"""
        ids = ids if isinstance(ids, (list, tuple, set)) else []
        try:
            res = elasticmassurl.client.search(
                index=cls.REQUEST_LOG_INDEX, doc_type=cls.REQUEST_LOG_MAPPING,
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
        try:
            res = elasticmassurl.client.search(
                timeout="60s", index=cls.DIARY_INDEX,
                _source_include=return_fields, sort="datetime:desc", size=size,
                doc_type=cls.DIARY_MAPPING,
                body=build_search_query(needle, offset)
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

def _get_nested_query(path, needle):
    return {
        "nested": {
            "path": path,
            "query": {
                "bool": {
                    "must": [
                        {"query_string": {"query": "%s" % needle[:256]}}
                    ]
                }
            }
        }
    }

def build_search_query(item, offset):
    must = []

    nested_ops = {
        "requests": "requested_urls",
        "signatures": "signatures"
    }

    normal_ops = ["url", "javascript"]

    searches = [s.strip() for s in item.split("AND")]
    for fields in searches:
        fields = fields.split(":",1)
        if len(fields) != 2:
            continue

        op, search = fields
        log.info("OP is: %s. search is %s", op, search)

        if search and op in nested_ops:
            must.append(_get_nested_query(nested_ops.get(op), search))
        elif search and op in normal_ops:
            must.append({
                "query_string": {
                    "default_field": op,
                    "query": "%s" % search[:256]
                }
            })

    if not must:
        must = {"query_string": {"query": "%s" % item[:256]}}

    query = {
        "query": {
            "bool": {
                "must": must
            }
        }
    }
    if offset:
        query["query"]["bool"]["filter"] = {
                "range": {"datetime": {"lt": offset}}
    }
    return query

class URLDiary(object):
    def __init__(self, url, url_id):
        self._diary = {
            "url": url,
            "url_id": url_id,
            "version": 0,
            "datetime": "",
            "javascript": [],
            "requested_urls": [],
            "signatures": []
        }
        self.logs = []
        self.urls = []

    def add_javascript(self, javascript):
        self._diary["javascript"].append(javascript)

    def add_signature(self, signature):
        if isinstance(signature, list):
            self._diary["signatures"].extend(signature)
        else:
            self._diary["signatures"].append(signature)

    def set_request_report(self, report):
        requested_urls = report.get("requested", [])
        if not requested_urls:
            return
        self.urls = requested_urls

        requestlogs = report.get("log", {})
        if not requestlogs:
            return

        for url in requested_urls:
            requestlog = requestlogs.get(url)
            if requestlog:
                self.logs.append({
                    "url": url,
                    "log": requestlog
                })

    def set_requestlog_ids(self, request_log_ids):
        for url in self.urls:
            self._diary["requested_urls"].append({
                "url": url,
                "len": len(url),
                "request_log": request_log_ids.get(url)
            })

    def dump(self):
        if not self._diary["requested_urls"]:
            for url in self.urls:
                self._diary["requested_urls"].append({
                    "url": url,
                    "len": len(url),
                    "request_log": ""
                })

        self._diary["datetime"] = int(time.time() * 1000)
        return self._diary

class RequestFinder(object):

    MAX_REQUEST_SIZE = 2048

    def __init__(self, task_id):
        self.task_id = task_id
        self.offset = 0
        self.pcapheader = None
        self.handlers = {}

    def process(self, flowmapping):
        """Reads a PCAP and adds the reqeusts that match the flow mapping
        to a dictionary of reports it will return. Reports will contain
        all found requests made for a url

        @param flowmapping: a dictionary of netflow:url values"""
        tlspath = cwd("tlsmaster.txt", analysis=self.task_id)
        tlsmaster = {}
        if os.path.exists(tlspath):
            tlsmaster = read_tlsmaster(tlspath)

        if tlsmaster or not self.handlers:
            self._create_handlers(tlsmaster)

        pcap_fp = open(cwd("dump.pcap", analysis=self.task_id))
        reader = PcapReader(pcap_fp)
        if self.offset and self.offset > 0:
            pcap_fp.seek(self.offset)

        reader.set_tcp_handler(TCPPacketStreamer(reader, self.handlers))
        reports = {}

        try:
            for flow, timestamp, protocol, sent, recv in reader.process():
                if not isinstance(sent, dpkt.http.Request):
                    continue

                tracked_url = flowmapping.get(flow)
                if not tracked_url:
                    continue

                report = reports.setdefault(tracked_url, {})
                requested = report.setdefault("requested", [])
                logs = report.setdefault("log", {})

                url = "%s://%s%s" % (
                    protocol,
                    sent.headers.get("host", "%s:%s" % (flow[2], flow[3])),
                    sent.uri
                )
                if url not in requested:
                    requested.append(url)

                requestlog = logs.setdefault(url, [])
                requestlog.append({
                    "time": timestamp,
                    "request": bytes(sent.raw)[:self.MAX_REQUEST_SIZE],
                    "response": bytes(recv.raw)[:self.MAX_REQUEST_SIZE]
                })

            return reports
        except Exception as e:
            log.exception("Failure while extracting requests from PCAP")
            return reports

        finally:
            self.offset = pcap_fp.tell()
            pcap_fp.close()

    def _create_handlers(self, tlsmaster={}):
        self.handlers = {
            80: http_handler,
            8000: http_handler,
            8080: http_handler
        }
        if tlsmaster:
            self.handlers.update({
                443: lambda: https_handler(tlsmaster),
                4443: lambda: https_handler(tlsmaster),
                8443: lambda: https_handler(tlsmaster)
            })
