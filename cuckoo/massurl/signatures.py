# Copyright (C) 2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import json
import logging

from cuckoo.massurl.urldiary import (
    URLDiaries, build_query
)

log = logging.getLogger(__name__)

_diary_fields = ["requests", "javascript"]
_requestlog_fields = ["requestdata", "responsedata"]

_rules = {
    "must": list,
    "any": list
}

def verify_sig(content):
    if not isinstance(content, dict):
        try:
            content = json.loads(content)
        except ValueError as e:
            log.debug("Invalid JSON for signature. %s", e)
            return False

    for key, values in content.iteritems():
        if key not in _diary_fields and key not in _requestlog_fields:
            log.debug("Invalid search key %r", key)
            return False

        if not isinstance(values, list):
            log.debug("Values for search key %r must be a list", key)
            return False

        for rule in values:
            for rulekey, needles in rule.iteritems():
                if rulekey not in _rules.keys():
                    log.debug("Invalid rule %r", rulekey)
                    return False

                if not isinstance(needles, _rules.get(rulekey)):
                    log.debug(
                        "%s.%s is of inccorrect type. Must be %s",
                        key, rulekey, _rules.get(rulekey)
                    )
                    return False

                for needle in needles:
                    if not isinstance(needle, basestring):
                        log.debug(
                            "Incorrect search item %r, %s.%s search items must"
                            " be string. ", needle, key, rulekey
                        )
                        return False

    return content

def run_signature(signature, newsince=None):
    diary_rules = {}
    for key in _diary_fields:
        if key in signature:
            diary_rules[key] = signature.get(key)

    diaries = {}
    if diary_rules:
        q = build_query(diary_rules)
        diaries = match_diaries(
           q, newsince=newsince
        )
        if not diaries:
            return {}

    if "requestdata" not in signature and "responsedata" not in signature:
        return diaries

    requestrules = {}
    if "requestdata" in signature:
        requestrules["requestdata"] = signature.get("requestdata")
    if "responsedata" in signature:
        requestrules["responsedata"] = signature.get("responsedata")

    requestlog_query = build_query(requestrules)

    ignore_diaries = []
    if diaries:
        for diary_id in diaries:
            logs = URLDiaries.search_requestlog(
                requestlog_query, return_fields="parent", size=1,
                parent=diary_id
            )
            if not logs:
                ignore_diaries.append(diary_id)

        for ignore in ignore_diaries:
            diaries.remove(ignore)
    else:
        diaries = URLDiaries.search_requestlog(
            requestlog_query, return_fields="parent", size=100,
            since=newsince
        )
        diaries = [match.get("parent") for match in diaries]

    return diaries

def match_diaries(diary_query, newsince=None):
    diaries = URLDiaries.search_diaries(
        body=diary_query, since=newsince, size=100,
        return_fields="url"
    )

    return [match.get("id") for match in diaries]
