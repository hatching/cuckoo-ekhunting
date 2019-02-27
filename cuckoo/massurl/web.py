# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import gevent.monkey
gevent.monkey.patch_all()

import datetime
import gevent
import json
import logging
import random
import string
import os
import time
import uuid

from socks5man.manager import Manager

from flask import Flask, request, jsonify, render_template, send_file
from gevent.lock import BoundedSemaphore
from gevent.pywsgi import WSGIServer
from gevent.queue import Queue
from geventwebsocket import WebSocketError
from geventwebsocket.handler import WebSocketHandler

from cuckoo.common.utils import parse_bool
from cuckoo.massurl import db
from cuckoo.massurl.urldiary import URLDiaries
from cuckoo.massurl import schedutil
from cuckoo.misc import cwd
from cuckoo.common.config import config


log = logging.getLogger(__name__)

alert_queue = Queue()
app = Flask(__name__)
lock = BoundedSemaphore(1)
sockets = set()
BROWSERS = {
    "Internet Explorer": "ie",
    "Firefox": "ff",
    "Edge": "edge"
}

def json_error(status_code, message, *args):
    r = jsonify(success=False, message=message % args if args else message)
    r.status_code = status_code
    return r

def get_available_routes():
    routes = []
    if config("routing:routing:internet") is not None or "none":
        routes.append("internet")
    if config("routing:vpn:enabled") and config("routing:vpn:vpns"):
        routes.append("vpn")
    if config("auxiliary:redsocks:enabled"):
        if Manager().list_socks5(operational=True):
            routes.append("socks5")

    return routes

def get_route_countries():
    countries = {
        "socks5": [],
        "vpn": []
    }
    if config("routing:vpn:enabled"):
        vpn_counties = set()
        for vpn in config("routing:vpn:vpns"):
            country = config("routing:%s:country" % vpn)
            if country:
                vpn_counties.add(country.lower())

        countries["vpn"] = list(vpn_counties)

    if config("auxiliary:redsocks:enabled"):
        countries["socks5"] = list(set(
            s.country.lower() for s in Manager().list_socks5(operational=True)
        ))

    return countries
#
# WEB VIEW ROUTES
#
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/url-groups")
def url_groups():
    return render_template(
        "url-groups.html", groups=[
            g.to_dict(additional=["urlcount", "unread", "highalert"])
            for g in db.list_groups(limit=50, details=True)
        ]
    )

@app.route("/url-groups/manage")
def url_groups_manage():
    return render_template(
        "url-group-content.html", groups=[
            g.to_dict(additional=["urlcount", "unread", "highalert"])
            for g in db.list_groups(limit=50, details=True)
        ]
    )

@app.route("/url-groups/view")
def url_groups_view():
    return render_template(
        "url-group-view.html", groups=[
            g.to_dict(additional=["urlcount", "unread", "highalert"])
            for g in db.list_groups(limit=50, details=True)
        ]
    )

@app.route("/diary")
def diaries_search():
    return render_template("search.html")

@app.route("/diary/<uuid>")
def diary_view(uuid):
    return render_template("url-diary.html", uuid=uuid)

@app.route("/settings")
def settings_view():
    return render_template("settings.html")

@app.route("/settings/profiles")
def profiles_view():
    return render_template(
        "profiles.html", browsers=[{k:v} for k, v in BROWSERS.iteritems()],
        tags=[t.to_dict() for t in db.db.list_tags()],
        routes=get_available_routes(), route_countries=get_route_countries()
    )

#
# API routes
#
@app.route("/api/alerts/list")
def list_alerts():
    url_group_name = request.args.get("group_name")
    order = request.args.get("order", "desc")
    if order not in ("asc", "desc"):
        return json_error(400, "Order can be asc or desc")

    orderby = request.args.get("orderby", "timestamp")
    if orderby not in ("timestamp", "level"):
        return json_error(400, "Orderby can be timestamp or level")

    intargs = {
        "limit": request.args.get("limit", 20),
        "offset": request.args.get("offset", 0),
        "level": request.args.get("level")
    }

    for key, value in intargs.iteritems():
        if value:
            try:
                intargs[key] = int(value)
            except ValueError:
                return json_error(400, "%s should be an integer" % key)

    alerts = db.list_alerts(
        level=intargs["level"], url_group_name=url_group_name,
        limit=intargs["limit"], offset=intargs["offset"], order=order,
        orderby=orderby
    )

    return jsonify([a.to_dict() for a in alerts])

@app.route("/api/alerts/read", methods=["POST"])
def mark_alert_read():
    alert = request.form.get("alert", 0)
    groupname = request.form.get("url_group_name")
    markall = request.form.get("markall", False)

    try:
        alert = int(alert)
    except ValueError:
        return json_error(400, "'alert' should be an integer")

    db.mark_alert_read(
        alert_id=alert, group_name=groupname, markall=markall
    )
    return jsonify(message="OK")

@app.route("/api/alerts/delete", methods=["POST"])
def delete_alert():
    alert = request.form.get("alert", 0)
    level = request.form.get("level", 0)
    groupname = request.form.get("group_name")
    clearall = request.form.get("clearall", False)

    intargs = {
        "alert": request.args.get("alert", 0),
        "level": request.args.get("level", 0)
    }

    for key, value in intargs.iteritems():
        if value:
            try:
                intargs[key] = int(value)
            except ValueError:
                return json_error(400, "%s should be an integer" % key)

    db.delete_alert(
        alert_id=alert, group_name=groupname, level=level, clear=clearall
    )
    return jsonify(message="OK")

@app.route("/api/group/add", methods=["POST"])
def add_group():
    name = request.form.get("name", "")
    description = request.form.get("description", "")

    if not name:
        return json_error(400, "Missing 'name' parameter")
    if not description:
        return json_error(400, "Missing 'description' parameter")

    try:
        group_id = db.add_group(name, description)
    except ValueError as e:
        return json_error(400, str(e))
    except KeyError:
        return json_error(409, "Specified group name already exists")
    if not group_id:
        return json_error(500, "Error while creating a new group")

    return jsonify(group_id=group_id)

@app.route("/api/group/schedule/<int:group_id>", methods=["POST"])
def schedule_group(group_id):
    schedule = request.form.get("schedule")

    group = db.find_group(group_id=group_id)
    if not group:
        return json_error(404, message="Group does not exist")

    if not group.profiles:
        return json_error(400, "Group has not profiles. Cannot be scheduled")

    if not schedule:
        db.remove_schedule(group_id)
        return jsonify(message="OK")

    if not db.find_urls_group(group_id=group.id, limit=1):
        return json_error(400, "Group has no URLs")

    if schedule == "now":
        if not group.completed:
            return json_error(400, "Group is already pending or running")

        schedule_next = datetime.datetime.utcnow() + \
                        datetime.timedelta(seconds=10)
        db.set_schedule_next(group_id, schedule_next)
        return jsonify(message="Scheduled at %s" % schedule_next)

    try:
        schedutil.schedule_time_next(schedule)
    except ValueError as e:
        return json_error(500, message=str(e))

    db.add_schedule(group_id, schedule)
    return jsonify(message="OK")


@app.route("/api/group/add/url", methods=["POST"])
def group_add_url():
    urls = request.form.get("urls", "")
    name = request.form.get("group_name", "")
    group_id = request.form.get("group_id")
    seperator = request.form.get("seperator", "\n")

    if not group_id and not name:
        return json_error(400, "No valid group name or id specified")

    if group_id:
        if not group_id.isdigit():
            return json_error(400, "group_id must be an integer")

        group_id = int(group_id)

    urls = filter(None, [url.strip() for url in urls.split(seperator)])
    if not urls:
        return json_error(400, "No URLs specified")

    group_id = db.mass_group_add(urls, name, group_id)
    if group_id:
        return jsonify(
            message="success",
            info="Added new URLs to group %s" % group_id
        )
    return json_error(404, "Specified group does not exist")

@app.route("/api/group/view/<int:group_id>")
@app.route("/api/group/view/<name>")
def view_group(group_id=None, name=None):
    if not group_id and not name:
        return json_error(400, "No group_id or name specified to view")

    try:
        details = int(request.args.get("details", 0))
    except ValueError:
        return json_error(400, "Invalid value for 'details'. Can be 0 or 1")

    group = db.find_group(name=name, group_id=group_id, details=True)
    if not group:
        return json_error(404, "Group not found")

    if details:
        return jsonify(group.to_dict(
            additional=["urlcount", "unread", "highalert"]
        ))
    else:
        return jsonify(group.to_dict())

@app.route("/api/group/view/<int:group_id>/urls")
@app.route("/api/group/view/<name>/urls")
def view_group_urls(group_id=None, name=None):
    if not group_id and not name:
        return json_error(400, "No group_id or name specified to view")

    limit = request.args.get("limit", "1000")
    if not limit.isdigit():
        return json_error(400, "Invalid limit")
    limit = int(limit)

    offset = request.args.get("offset", "0")
    if not offset.isdigit():
        return json_error(400, "Invalid offset")
    offset = int(offset)

    group = db.find_group(name=name, group_id=group_id)
    if not group:
        return json_error(404, "Specified group does not exist")

    urls = db.find_urls_group(
        group.id, limit=limit, offset=offset, include_id=True
    )

    return jsonify(name=group.name, group_id=group.id, urls=urls)

@app.route("/api/group/delete", methods=["POST"])
def delete_group():
    name = request.form.get("group_name", "")
    group_id = request.form.get("group_id")

    if not group_id and not name:
        return json_error(400, "No valid group name or id specified")

    if group_id:
        if not group_id.isdigit():
            return json_error(400, "group_id must be an integer")

        group_id = int(group_id)

    if db.delete_group(group_id=group_id, name=name):
        return jsonify(message="success")
    return json_error(404, "Specified group does not exist")

@app.route("/api/group/delete/url", methods=["POST"])
def group_delete_url():
    urls = request.form.get("urls", "")
    name = request.form.get("group_name", "")
    group_id = request.form.get("group_id")
    delall = request.form.get("delall", False)
    seperator = request.form.get("seperator", "\n")

    if not group_id and not name:
        return json_error(400, "No valid group name or id specified")

    if group_id:
        if not group_id.isdigit():
            return json_error(400, "group_id must be an integer")

        group_id = int(group_id)

    group = db.find_group(name=name, group_id=group_id)
    if not group:
        return json_error(404, "Specified group does not exist")

    urls = filter(None, [url.strip() for url in urls.split(seperator)])
    if not urls and not delall:
        return json_error(400, "No URLs specified")

    if db.delete_url_from_group(urls, group.id, clearall=delall):
        return jsonify(message="success")

    return json_error(500, "Error removing URLs from group")

@app.route("/api/groups/list")
def list_groups():
    intargs = {
        "limit": request.args.get("limit", 50),
        "offset": request.args.get("offset", 0),
        "details": request.args.get("details", 0)
    }

    for key, value in intargs.iteritems():
        if value:
            try:
                intargs[key] = int(value)
            except ValueError:
                return json_error(400, "%s should be an integer" % key)

    if not intargs.get("details"):
        return jsonify(
            [
                g.to_dict() for g in db.list_groups(
                    limit=intargs["limit"], offset=intargs["offset"]
                )
            ]
        )
    else:
        return jsonify([
            g.to_dict(additional=["urlcount", "unread", "highalert"])
            for g in db.list_groups(
                limit=intargs["limit"], offset=intargs["offset"], details=True
            )
        ])

@app.route("/api/diary/url/<url_id>")
def get_diaries_url(url_id):
    intargs = {
        "limit": request.args.get("limit", 20),
        "offset": request.args.get("offset", 0)
    }

    for key, value in intargs.iteritems():
        if value:
            try:
                intargs[key] = int(value)
            except ValueError:
                return json_error(400, "%s should be an integer" % key)

    diary_list = URLDiaries.list_diary_url_id(
        url_id, size=intargs.get("limit"), return_fields="version,datetime",
        offset=intargs.get("offset")
    )
    if diary_list is None:
        return json_error(500, "Error retrieving URL diaries")

    return jsonify(diary_list)

@app.route("/api/diary/search/<item>")
def search_diaries(item):
    intargs = {
        "limit": request.args.get("limit", 20),
        "offset": request.args.get("offset", 0)
    }

    for key, value in intargs.iteritems():
        if value:
            try:
                intargs[key] = int(value)
            except ValueError:
                return json_error(400, "%s should be an integer" % key)

    diary_list = URLDiaries.search_diaries(
        item, return_fields="datetime,url,version", size=intargs.get("limit"),
        offset=intargs.get("offset")
    )

    if diary_list is None:
        return json_error(500, "Error retrieving URL diaries")

    return jsonify(diary_list)

@app.route("/api/requestlog/<log_id>")
def get_request_log(log_id):
    request_log = URLDiaries.get_request_log(log_id)
    if not request_log:
        return json_error(404, "The specified request log does not exist")

    return jsonify(request_log)

@app.route("/api/diary/<diary_id>")
def get_diary(diary_id):
    diary = URLDiaries.get_diary(diary_id)
    if not diary:
        return json_error(404, "The specified URL diary does not exist")

    return jsonify(diary)

@app.route("/api/pcap/<int:task_id>")
def get_pcap(task_id):
    pcap_path = cwd("dump.pcap", analysis=task_id)
    if not os.path.isfile(pcap_path):
        return json_error(404, message="PCAP for given task does not exist")

    return send_file(
        pcap_path, attachment_filename="task%s-dump.pcap" % task_id
    )

@app.route("/api/profile/add", methods=["POST"])
def add_profile():
    name = request.form.get("name")
    browser = request.form.get("browser", "").lower()
    route = request.form.get("route", "").lower()
    country = request.form.get("country", "").lower()
    tags = request.form.getlist("tags")

    if not name:
        return json_error(400, "No name provided")

    if browser not in BROWSERS.values():
        return json_error(400, "%r is not a valid browser choice" % browser)

    available_routes = get_available_routes()
    if route.lower() not in available_routes:
        return json_error(
            400, "Invalid route %r. Available routes: %s" %
                 (route, available_routes)
        )

    if country and route != "internet":
        if country not in get_route_countries()[route]:
            return json_error(
                400, "Route through country %r does not exist for route %r" %
                     (country, route)
            )

    if not isinstance(tags, list):
        return json_error(400, "tags must be a list of tag ids")

    try:
        tags = [int(t) for t in tags]
    except ValueError:
        return json_error(400, "tags must be a list of integer tag ids")

    try:
        profile_id = db.add_profile(
            name=name, browser=browser, route=route, country=country, tags=tags
        )
    except KeyError:
        return json_error(409, "Profile with name %r already exists" % name)

    return jsonify({"profile_id": profile_id})

@app.route("/api/profile/list")
def list_profiles():
    intargs = {
        "limit": request.args.get("limit", 20),
        "offset": request.args.get("offset", 0)
    }

    for key, value in intargs.iteritems():
        if value:
            try:
                intargs[key] = int(value)
            except ValueError:
                return json_error(400, "%s should be an integer" % key)

    return jsonify([p.to_dict() for p in db.list_profiles(
        limit=intargs.get("limit"), offset=intargs.get("offset")
    )])

@app.route("/api/profile/<name>")
@app.route("/api/profile/<int:profile_id>")
def find_profile(name=None, profile_id=None):
    profile = db.find_profile(profile_id=profile_id, profile_name=name)

    if not profile:
        return json_error(404, "Profile not found")
    return jsonify(profile.to_dict())

@app.route("/api/profile/update/<int:profile_id>", methods=["POST"])
def update_profile(profile_id):
    browser = request.form.get("browser", "").lower()
    route = request.form.get("route", "").lower()
    country = request.form.get("country", "").lower()
    tags = request.form.getlist("tags")

    if browser not in BROWSERS.values():
        return json_error(400, "%r is not a valid browser choice" % browser)

    available_routes = get_available_routes()
    if route.lower() not in available_routes:
        return json_error(
            400, "Invalid route %r. Available routes: %s" %
                 (route, available_routes)
        )

    if country and route != "internet":
        if country not in get_route_countries()[route]:
            return json_error(
                400, "Route through country %r does not exist for route %r" %
                     (country, route)
            )

    if not isinstance(tags, list):
        return json_error(400, "tags must be a list of tag ids")

    try:
        tags = [int(t) for t in tags]
    except ValueError:
        return json_error(400, "tags must be a list of integer tag ids")

    try:
        db.update_profile(
            profile_id=profile_id, browser=browser, route=route, country=country,
            tags=tags
        )
    except KeyError:
        return json_error(404, "Profile %r does not exist" % profile_id)

    return jsonify(message="success")

@app.route("/api/profile/delete/<int:profile_id>", methods=["POST"])
def delete_profiles(profile_id):
    db.delete_profile(profile_id)
    return jsonify(message="success")

@app.route("/api/group/<int:group_id>/profiles", methods=["POST"])
def update_profile_group(group_id):
    profile_ids = request.form.getlist("profile_ids")

    if not isinstance(profile_ids, list):
        return json_error(400, "profile_ids must be a list of integer ids")

    try:
        profile_ids = [int(p) for p in profile_ids]
    except ValueError:
        return json_error(400, "profile_ids must be a list of integer ids")

    db.update_profile_group(profile_ids=profile_ids, group_id=group_id)
    return jsonify(message="success")

def random_string(minimum, maximum=None):
    if maximum is None:
        maximum = minimum

    count = random.randint(minimum, maximum)
    return "".join(random.choice(string.ascii_letters) for x in xrange(count))

def random_date(start, end):
    delta = end - start
    int_delta = (delta.days * 24 * 60 * 60) + delta.seconds
    random_second = random.randrange(int_delta)
    return start + datetime.timedelta(seconds=random_second)

def rand_sig(c=None):
    s = ["JS eval()", "Suspicious JS", "JS iframe", "Flash file loaded",
         "New URL detected", "Suspicious URL domain name", "JS in PDF",
         "TOR url", "TOR gateway URL", "IE11 Exploit", "Edge Exploit",
         "Firefox exploit", "Suspicious process created", "Browser exploited",
         "Suspicious Java applet"]
    s.extend([random_string(8, 17) for x in range(random.randint(4, 20))])
    random.shuffle(s)
    return [
        {"signature": random.choice(s),
         "description": random_string(10, 100),
         "ioc": random_string(10, 100)
         } for x in range(c or random.randint(0, 18))
    ]

@app.route("/api/genalert")
def gen_alerts():
    notify = request.args.get("notify", False)
    int_args = {
        "targetgroup_id": request.args.get("targetgroup_id"),
        "level": request.args.get("level", 2),
        "count": request.args.get("count", 1)
    }

    for key, value in int_args.iteritems():
        if value:
            try:
                int_args[key] = int(value)
            except ValueError:
                return json_error(400, "%s should be an integer!" % key)

    if notify:
        notify = parse_bool(notify)

    group_name = None
    if int_args["targetgroup_id"]:
        targetgroup = db.find_group(group_id=int_args["targetgroup_id"])
        if not targetgroup:
            return json_error(404, "Target group does not exist")

        group_name = targetgroup.name

    for x in range(int_args["count"]):
        alert = {
            "level": int_args["level"],
            "title": random_string(5, 30),
            "content": random_string(80, 400),
            "task_id": random.randint(1, 1000),
            "url_group_name": group_name,
            "timestamp": datetime.datetime.now(),
            "target": random.choice(["http://example.com/somepage", None])
        }
        send_alert(notify=notify, **alert)

        gevent.sleep(0.2)

    return jsonify(message="OK")

@app.route("/api/gendiaries/<group_id>")
def gen_diaries(group_id):
    urls = db.find_urls_group(group_id=group_id, include_id=True)
    if not urls:
        return json_error(404, "Group with specified ID does not exist")

    def gen_diary(url, url_id):
        gen_urls = []
        for x in range(random.randint(0, 100)):
            u = "http://%s" % random_string(10, 60)
            gen_urls.append({"url": u, "len": len(u)})

        latest = URLDiaries.get_latest_diary(
            url_id=url_id, return_fields="version"
        ) or {}
        return {
            "url": url,
            "url_id": url_id,
            "datetime": int(time.time() * 1000),
            "signatures": rand_sig(),
            "javascript": [random_string(22, 6000) for x in range(
                random.randint(0, 40)
            )],
            "requested_urls": gen_urls,
            "related_documents": [],
            "version": (latest.get("version") or 0) + 1
        }

    ids = []
    for url in urls:
        uid = uuid.uuid1()
        URLDiaries.store_diary(
            gen_diary(url.get("url"), url.get("id")), uid
        )
        ids.append(uid)

    return jsonify(ids=ids)

def ws_connect(ws):
    """Websocket connections for alerts are handled here. When a connection
    is closed. It is removed from the tracked websockets automatically"""
    log.debug("New websocket connection")

    try:
        lock.acquire()
        sockets.add(ws)
    finally:
        lock.release()

    try:
        while ws.receive():
            if ws.closed:
                break
    finally:
        try:
            lock.acquire()
            sockets.discard(ws)
        finally:
            lock.release()

    return []

def handle_alerts():
    """Retrieve alerts from a queue (will be replace with a socket later, so
     that other Cuckoo processes can send info to it)"""
    for alert in alert_queue:
        try:
            lock.acquire()
            for ws in sockets:
                try:
                    ws.send(alert)
                except WebSocketError:
                    continue
        finally:
            lock.release()

def send_alert(level=1, title="", content="", task_id=None, url_group_name="",
               timestamp=None, target=None, diary_id=None, notify=False):
    alert = {
        "level": level,
        "title": title,
        "content": content,
        "task_id": task_id,
        "url_group_name": url_group_name,
        "timestamp": timestamp or datetime.datetime.now(),
        "target": target,
        "diary_id": diary_id
    }
    db.add_alert(**alert)
    alert["notify"] = notify
    alert["timestamp"] = alert["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
    alert_queue.put(json.dumps(alert))

ws_routes = {
    "/ws/alerts": ws_connect
}

def run_server(host, port):
    """Run the server. This handles websocket and HTTP requests"""
    log.info("Starting server for %r on %s:%s", app, host, port)

    gevent.spawn(handle_alerts)

    # Determines what handler should be u
    def xapp(environ, start_response):
        uri = environ["PATH_INFO"]
        ws_handler = ws_routes.get(uri)

        if ws_handler and "wsgi.websocket" in environ:
            return ws_handler(environ["wsgi.websocket"])
        return app(environ, start_response)

    server = WSGIServer(
        (host, int(port)), application=xapp, handler_class=WebSocketHandler
    )
    logging.getLogger("geventwebsocket.handler").setLevel(logging.DEBUG)
    server.serve_forever()
