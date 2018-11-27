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
import uuid

from flask import Flask, request, jsonify, render_template
from gevent.lock import BoundedSemaphore
from gevent.pywsgi import WSGIServer
from gevent.queue import Queue
from geventwebsocket import WebSocketError
from geventwebsocket.handler import WebSocketHandler

from cuckoo.massurl import db
from cuckoo.common.utils import parse_bool

alert_queue = Queue()
app = Flask(__name__)
lock = BoundedSemaphore(1)
log = logging.getLogger(__name__)
sockets = set()

def json_error(status_code, message, *args):
    r = jsonify(success=False, message=message % args if args else message)
    r.status_code = status_code
    return r

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
            g.to_dict() for g in db.list_groups(limit=50)
        ]
    )

@app.route("/url-groups/manage")
def url_groups_manage():
    return render_template(
        "url-group-content.html", groups=[
            g.to_dict() for g in db.list_groups(limit=50)
        ]
    )

@app.route("/url-groups/view")
def url_groups_view():
    return render_template(
        "url-group-view.html", groups=[
            g.to_dict() for g in db.list_groups(limit=50)
        ]
    )

@app.route("/diary/<uuid>")
def diary_view(uuid):
    return render_template(
        "url-diary.html",
        uuid=uuid,
        diaries=[]
    )

#
# API routes
#
@app.route("/api/alerts/list")
def list_alerts():
    target_group = request.args.get("target_group")

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
        level=intargs["level"], target_group=target_group,
        limit=intargs["limit"], offset=intargs["offset"]
    )

    return jsonify([a.to_dict() for a in alerts])

@app.route("/api/group/add", methods=["POST"])
def add_group():
    name = request.form.get("name", "")
    description = request.form.get("description", "")
    schedule = request.form.get("schedule") or "1d"

    if not name:
        return json_error(400, "Missing 'name' parameter")
    if not description:
        return json_error(400, "Missing 'description' parameter")

    try:
        group_id = db.add_group(name, description, schedule)
    except ValueError as e:
        return json_error(400, str(e))
    except KeyError:
        return json_error(409, "Specified group name already exists")
    if not group_id:
        return json_error(500, "Error while creating a new group")

    return jsonify(group_id=group_id)

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

    group = db.find_group(name=name, group_id=group_id)
    if not group:
        return json_error(404, "Group not found")

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

    urls = db.find_urls_group(group.id, limit=limit, offset=offset)

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
    if not urls:
        return json_error(400, "No URLs specified")

    if db.delete_url_from_group(urls, group.id):
        return jsonify(message="success")

    return json_error(500, "Error removing URLs from group")

@app.route("/api/groups/list")
def list_groups():
    intargs = {
        "limit": request.args.get("limit", 50),
        "offset": request.args.get("offset", 0)
    }

    for key, value in intargs.iteritems():
        if value:
            try:
                intargs[key] = int(value)
            except ValueError:
                return json_error(400, "%s should be an integer" % key)

    return jsonify(
        [
            g.to_dict() for g in db.list_groups(
                limit=intargs["limit"], offset=intargs["offset"]
            )
        ]
    )

@app.route("/api/diary/url/<int:url_id>")
def get_diaries_url(url_id):
    limit = int(request.args.get("limit", 50))
    offset = request.args.get("offset", 0)
    return jsonify([
        {
            "version": random.randint(1, 150),
            "datetime": str(random_date(
                datetime.datetime.strptime(
                    "1-11-2018 21:55:22", "%d-%m-%Y %H:%M:%S"
                ),
                datetime.datetime.strptime(
                    "23-11-2018 23:17:18", "%d-%m-%Y %H:%M:%S"
                )
            )),
            "id": str(uuid.uuid4())
        }
        for x in range(limit)
    ])

@app.route("/api/diary/search/<item>")
def search_diaries(item):
    limit = int(request.args.get("limit", 50))
    offset = request.args.get("offset", 0)
    return jsonify([
        {
            "version": random.randint(1, 150),
            "datetime": str(random_date(
                datetime.datetime.strptime(
                    "1-11-2018 21:55:22", "%d-%m-%Y %H:%M:%S"
                ),
                datetime.datetime.strptime(
                    "23-11-2018 23:17:18", "%d-%m-%Y %H:%M:%S"
                )
            )),
            "id": str(uuid.uuid4()),
            "url": "http://%s" % random_string(10, 60),
            "match": ["%s%s" % (item, random_string(5, 200)) for x in range(random.randint(0, 10))]
        }
        for x in range(limit)
    ])

@app.route("/api/diary/<uuid>")
def get_diary(uuid):
    return jsonify({
        "url": "http://%s" % random_string(10, 60),
        "datetime": str(random_date(
                datetime.datetime.strptime(
                    "1-11-2018 21:55:22", "%d-%m-%Y %H:%M:%S"
                ),
                datetime.datetime.strptime(
                    "23-11-2018 23:17:18", "%d-%m-%Y %H:%M:%S"
                )
            )),
        "signatures": rand_sig(),
        "javascript": [random_string(22, 6000) for x in range(
            random.randint(0, 40)
        )],
        "requested_urls": [
            {"url": "http://%s" % random_string(10, 60), "len": 55} for x in range(random.randint(0, 100))
            ],
        "version": random.randint(1, 150),
        "id": uuid
    })

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
    return [random.choice(s) for x in range(c or random.randint(0, 18))]

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
        db.add_alert(**alert)
        alert["notify"] = notify
        alert["timestamp"] = alert["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
        alert_queue.put(json.dumps(alert))
        gevent.sleep(0.2)

    return jsonify(message="OK")

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

ws_routes = {
    "/alerts": ws_connect
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
