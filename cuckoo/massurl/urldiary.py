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
from httpreplay.cut import http_handler, https_handler, forward_handler
from httpreplay.misc import read_tlsmaster
from httpreplay.reader import PcapReader
from httpreplay.smegma import TCPPacketStreamer

from cuckoo.common.config import config
from cuckoo.common.elastic import elasticmassurl
from cuckoo.common.exceptions import CuckooStartupError
from cuckoo.misc import cwd

log = logging.getLogger(__name__)
logging.getLogger("elasticsearch").setLevel(logging.ERROR)

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

        urldiary.stored = True
        urldiary = urldiary.dump()
        version = cls.get_latest_diary(urldiary.get("url_id"))
        if version:
            version = version.get("version", 1) + 1
        else:
            version = 1

        urldiary["version"] = version
        try:
            urldiary = json.loads(json.dumps(urldiary, encoding="latin1"))
        except ValueError as e:
            log.exception("Failed to encode URL diary: %s", e)
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
    def get_diary(cls, diary_id, return_fields=[]):
        """Find a specified URL diary"""
        try:
            res = elasticmassurl.client.search(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING, size=1,
                sort="datetime:desc", _source_include=return_fields,
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
    def get_diaries(cls, ids=[], return_fields="datetime,url,version"):
        """Retrieve the specified related requests by id"""
        ids = ids if isinstance(ids, (list, tuple, set)) else []
        try:
            res = elasticmassurl.client.search(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING,
                _source_include=return_fields, sort="datetime:desc",
                body={
                    "query": {
                        "ids": {"values": ids}
                    }
                }
            )
        except TransportError as e:
            log.exception("Error while retrieving related streams. %s", e)
            return []

        return URLDiaries.get_values(res, return_empty=[])

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
    def search_diaries(cls, needle=None, return_fields="datetime,url,version",
                       size=50, offset=0, body=None, since=None):
        """Search all URL diaries for needle and return a list objs
        containing return_fields
        @param offset: search for smaller than the provided the millisecond
        time stamp
        """
        if not body:
            body = build_search_query(needle)

        if offset:
            body["query"]["bool"]["filter"] = {
                "range": {"datetime": {"lt": offset}}
            }
        elif since:
            body["query"]["bool"]["filter"] = {
                "range": {"datetime": {"gt": since}}
            }

        try:
            res = elasticmassurl.client.search(
                timeout="60s", index=cls.DIARY_INDEX,
                _source_include=return_fields, sort="datetime:desc", size=size,
                doc_type=cls.DIARY_MAPPING,
                body=body
            )
        except TransportError as e:
            log.exception("Error while searching diaries. %s", e)
            return []

        return URLDiaries.get_values(res, return_empty=[])

    @classmethod
    def count_diaries(cls):
        try:
            res = elasticmassurl.client.count(
                index=cls.DIARY_INDEX, doc_type=cls.DIARY_MAPPING
            )
        except TransportError as e:
            log.exception("Error while counting diary entries. %s", e)
            return None

        return res["count"]

    @classmethod
    def search_requestlog(cls, body, return_fields="datetime,url,version",
                          size=50, offset=0, since=None, parent=None):

        if offset:
            body["query"]["bool"]["filter"] = {
                "range": {"datetime": {"lt": offset}}
            }
        elif since:
            body["query"]["bool"]["filter"] = {
                "range": {"datetime": {"gt": since}}
            }

        if parent:
            body["query"]["bool"]["must"].append({
                "term": {"parent": parent}
            })
        try:
            res = elasticmassurl.client.search(
                timeout="60s", index=cls.REQUEST_LOG_INDEX,
                _source_include=return_fields, sort="datetime:desc", size=size,
                doc_type=cls.REQUEST_LOG_MAPPING,
                body=body
            )
        except TransportError as e:
            log.exception("Error while request logs. %s", e)
            return []

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

_phrase_match = ["requestdata", "responsedata", "javascript"]

_nested_fields = {
    "requestdata": "log",
    "responsedata": "log",
    "signatures": "signatures",
    "requests": "requested_urls",
    "signaturename": "signatures",
    "signatureioc": "signatures"
}
_field_paths = {
    "requestdata": "log.request",
    "responsedata": "log.response",
    "javascript": "javascript",
    "signaturename": "signatures.signature",
    "signatureioc": "signatures.ioc"
}

def escape_and_filter(needle):
    escape = [
        "+", "-", "=", "&", "|", "!", "(", ")", "{", "}", "[", "]", "^", "~",
        "?", ":", "/"
    ]
    remove = ["<", ">"]

    if "\\" in needle:
        needle = needle.replace("\\", "\\\\\\")

    if "\"" in needle:
        needle = needle.replace("\"", "\\\\\"")

    for e in escape:
        needle = needle.replace(e, "\%s" % e)

    for r in remove:
        needle = needle.replace(r, "")

    return needle

def get_nested_query(path, bool):
    return {
        "nested": {
            "path": path,
            "query": {
                "bool": bool
            }
        }
    }

def querystring(needles, _or=False, _and=False, field=None):
    if not isinstance(needles, list):
        needles = [needles]

    if _or:
        _or = "OR"
    elif _and:
        _and = "AND"

    searchstr = ""
    for n in needles:
        searchstr += "%s" % n[:256]
        searchstr = escape_and_filter(searchstr)
        if n != needles[-1]:
            if _or:
                searchstr = "%s %s " % (searchstr, _or)
            elif _and:
                searchstr = "%s %s " % (searchstr, _and)

    return {
        "query_string": {
            "query": searchstr,
            "default_field": field or "*"
        }
    }

def matchphrase(field, needle):
    return {
        "match_phrase": {field: needle}
    }

def boolquery(must=[], should=[]):
    boolq = {}
    if must:
        boolq["must"] = must
    if should:
        boolq["should"] = should
        boolq["minimum_should_match"] = 1

    return boolq

def build_query(content, str_use_fields=False):
    global_must = []
    global_should = []
    for key, values in content.iteritems():
        phrase_q = False
        if key in _phrase_match:
            phrase_q = True

        strqs_anyof = []
        phraseqs_anyof = []
        strqs_contains = []
        phraseqs_contains = []
        for rule in values:
            for rulekey, needles in rule.iteritems():
                if rulekey == "must":
                    for s in needles:
                        if phrase_q and "*" not in s:
                            phraseqs_contains.append(s)
                        else:
                            strqs_contains.append(s)

                elif rulekey == "any":
                    for s in needles:
                        if phrase_q and "*" not in s:
                            phraseqs_anyof.append(s)
                        else:
                            strqs_anyof.append(s)

        must = []
        should = []
        if strqs_anyof:
            must.append(
                querystring(
                    needles=strqs_anyof, _or=True,
                    field=_field_paths.get(key) if str_use_fields else None
                )
            )
        if strqs_contains:
            must.append(
                querystring(
                    needles=strqs_contains, _and=True,
                    field=_field_paths.get(key) if str_use_fields else None
                )
            )

        for phrase in phraseqs_contains:
            must.append(matchphrase(_field_paths.get(key), phrase))

        for phrase in phraseqs_anyof:
            should.append(matchphrase(_field_paths.get(key), phrase))

        nested = _nested_fields.get(key)
        if nested:
            global_must.append(
                get_nested_query(
                    nested, boolquery(must=must, should=should)
                )
            )
        else:
            global_must.extend(must)
            global_should.extend(should)

    return {
        "query": {
            "bool": boolquery(must=global_must, should=global_should)
        }
    }

def build_search_query(item):
    allowed = [
        "requests", "url", "javascript", "signatures", "signaturename",
        "signatureioc"
    ]
    rules = {}
    searches = [s.strip() for s in item.split("AND")]
    for fields in searches:
        fields = filter(None, fields.split(":", 1))
        if len(fields) != 2:
            continue

        op, search = fields
        if search and op in allowed:
            if op not in rules:
                rules[op] = [{"must": []}]
            rules[op][0]["must"].append(search)

    if not rules:
        return {
            "query": {
                "bool": {
                    "must": {
                        "query_string": {
                            "query": "%s" % escape_and_filter(item[:256])
                        }
                    }
                }
            }
        }

    return build_query(rules, str_use_fields=True)


class URLDiary(object):
    def __init__(self, url, url_id, machine, browser):
        self._diary = {
            "url": url,
            "url_id": url_id,
            "machine": machine,
            "browser": browser,
            "version": 0,
            "datetime": "",
            "javascript": [],
            "requested_urls": [],
            "signatures": []
        }
        self.logs = []
        self.urls = []
        self.stored = False

    def add_javascript(self, javascript):
        if javascript not in self._diary["javascript"]:
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

    MAX_REQUEST_SIZE = 4096

    def __init__(self, task_id):
        self.task_id = task_id
        self.offset = 0
        self.pcapheader = None
        self.handlers = {}
        self.MAX_REQUEST_SIZE = config("massurl:elasticsearch:request_store")

    def process(self, flowmapping, ports=None):
        """Reads a PCAP and adds the reqeusts that match the flow mapping
        to a dictionary of reports it will return. Reports will contain
        all found requests made for a url
        @param flowmapping: a dictionary of netflow:url values"""
        tlspath = cwd("tlsmaster.txt", analysis=self.task_id)
        tlsmaster = {}
        if os.path.exists(tlspath):
            tlsmaster = read_tlsmaster(tlspath)

        if tlsmaster or not self.handlers:
            self._create_handlers(tlsmaster, ports=ports)

        pcap_fp = open(cwd("dump.pcap", analysis=self.task_id))
        reader = PcapReader(pcap_fp)
        if self.offset and self.offset > 0:
            pcap_fp.seek(self.offset)

        reader.set_tcp_handler(TCPPacketStreamer(reader, self.handlers))
        reports = {}

        try:
            for flow, timestamp, protocol, sent, recv in reader.process():
                tracked_url = flowmapping.get(flow)
                if not tracked_url:
                    continue

                if not sent and not recv:
                    continue

                if isinstance(sent, dpkt.http.Request):
                    url = "%s://%s%s" % (
                        protocol,
                        sent.headers.get("host", "%s:%s" % (flow[2], flow[3])),
                        sent.uri
                    )
                else:
                    url = "%s://%s:%s" % (
                        protocol, flow[2], flow[3]
                    )

                report = reports.setdefault(tracked_url, {})
                requested = report.setdefault("requested", [])
                logs = report.setdefault("log", {})

                if url not in requested:
                    requested.append(url)

                if not isinstance(recv, (dpkt.http.Response, basestring)):
                    recv = recv.raw

                requestlog = logs.setdefault(url, [])
                requestlog.append({
                    "time": timestamp,
                    "request": bytes(sent)[:self.MAX_REQUEST_SIZE],
                    "response": bytes(recv)[:self.MAX_REQUEST_SIZE]
                })

            return reports
        except Exception as e:
            log.exception("Failure while extracting requests from PCAP")
            return reports

        finally:
            self.offset = pcap_fp.tell()
            pcap_fp.close()

    def _create_handlers(self, tlsmaster={}, ports=[]):
        tls_ports = [443, 4443, 8443]
        http_ports = [80, 8000, 8080]
        for port in ports:
            if port not in tls_ports:
                http_ports.append(port)

        self.handlers = {
            "generic": forward_handler
        }
        for httpport in http_ports:
            self.handlers.update({
                httpport: http_handler
            })
        if tlsmaster:
            for tlsport in tls_ports:
                self.handlers.update({
                    tlsport: lambda: https_handler(tlsmaster)
                })
