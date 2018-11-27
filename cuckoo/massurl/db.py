# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime

from sqlalchemy import Column, ForeignKey
from sqlalchemy import Integer, String, Boolean, DateTime, Text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship

from cuckoo.core.database import Database, Base
from cuckoo.common.objects import Dictionary
from cuckoo.common.utils import json_encode
from cuckoo.massurl.schedutil import schedule_time_next

db = Database()

class ToDict(object):
    """Mixin to turn simple objects into a dict or JSON (no relation
    support)"""
    def to_dict(self, dt=True):
        """Converts object to dict.
        @return: dict
        """
        d = Dictionary()
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if dt and isinstance(value, datetime.datetime):
                d[column.name] = value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                d[column.name] = value
        return d

    def to_json(self):
        """Converts object to JSON.
        @return: JSON data
        """
        return json_encode(self.to_dict())

class Alert(Base, ToDict):
    """Dashboard alert history"""
    __tablename__ = "massurl_alerts"

    id = Column(Integer(), primary_key=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    level = Column(Integer(), nullable=False, default=1)
    title = Column(String(255), nullable=False)
    content = Column(Text(), nullable=False)
    target = Column(Text(), nullable=True)
    url_group_name = Column(String(255), nullable=True)
    task_id = Column(Integer(), nullable=True)

class URL(Base, ToDict):
    __tablename__ = "massurl_urls"
    id = Column(Integer(), primary_key=True)
    target = Column(String(2048), nullable=False, unique=True)

    # TODO: useful attributes per URL for searching

class URLGroupURL(Base):
    """Associates URLs with URL groups"""
    __tablename__ = "massurl_url_group_urls"

    url_id = Column(
        Integer(), ForeignKey("massurl_urls.id", ondelete="CASCADE"),
        nullable=False, primary_key=True,
    )
    url_group_id = Column(
        Integer(), ForeignKey("massurl_url_groups.id", ondelete="CASCADE"),
        nullable=False, primary_key=True
    )

class URLGroupTask(Base, ToDict):
    """Stores progress information on tasks"""
    __tablename__ = "massurl_url_group_tasks"
    id = Column(Integer(), primary_key=True)

    url_group_id = Column(Integer(), ForeignKey("massurl_url_groups.id"), nullable=False)
    #url_id = Column(Integer(), ForeignKey("massurl_urls.id"), nullable=False)
    task_id = Column(Integer(), ForeignKey("tasks.id"), nullable=False)

class URLGroup(Base, ToDict):
    """A group of URLs with a schedule"""
    __tablename__ = "massurl_url_groups"

    id = Column(Integer(), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text(), nullable=False)

    max_parallel = Column(Integer(), default=1, nullable=False)

    schedule = Column(Text(), server_default="", nullable=False)
    schedule_next = Column(DateTime, nullable=True)
    completed = Column(Boolean(), default=True, nullable=False)

    urls = relationship(
        "URL", secondary=URLGroupURL.__table__, lazy="dynamic"
    )
    tasks = relationship(
        "Task", secondary=URLGroupTask.__table__, lazy="dynamic"
    )

#
# Helper functions
#

def find_group(name=None, group_id=None, details=False):
    """Find a group by name
    @param name: Name of the group to find
    @param details: Loads all targets that are members of this group"""
    session = db.Session()
    try:
        group = session.query(URLGroup)
        if name:
            group = group.filter_by(name=name)
        if group_id:
            group = group.filter_by(id=group_id)

        group = group.first()
        if group:
            session.expunge(group)

    finally:
        session.close()

    return group

def mass_group_add(urls, group_name=None, group_id=None):
    """Bulk add a list of url strings to a provided group.
    If no target exists for a provided urls, it will be created.
    @param urls: A list of URLs, may be of existing targets.
    @param group_id: A group identifier to add the targets to."""
    urls = set(urls)

    session = db.Session()
    try:
        if group_id is None:
            group = session.query(URLGroup).filter_by(name=group_name).first()
        else:
            group = session.query(URLGroup).get(group_id)
        if not group:
            return
        group_id = group.id
        # TODO: optimize
        for url in urls:
            u = session.query(URL.id).filter_by(target=url).first()
            if not u:
                u = URL(target=url)
                session.add(u)
                session.flush()
            session.merge(URLGroupURL(url_id=u.id, url_group_id=group_id))
        session.commit()
        return group_id
    finally:
        session.close()

def delete_url_from_group(targets, group_id):
    """Removes the given list of urls from the given group
    @param targets: A list of urls
    @param group_id: The group id to remove the urls from"""
    session = db.Session()

    try:
        for url in targets:
            u = session.query(URL.id).filter_by(target=url).first()
            if not u:
                continue
            session.query(URLGroupURL) \
                .filter_by(url_id=u.id, url_group_id=group_id) \
                .delete(synchronize_session=False)
        session.commit()
        return True
    finally:
        session.close()

def find_urls_group(group_id, limit=1000, offset=0, include_id=False):
    """Retrieve a list of all urls in the specified group
    @param group_id: The id of the group to retrieve urls for
    @param limit: The limit on urls to return
    @param offset: The offset to use when retrieving urls"""
    session = db.Session()

    try:
        group = session.query(URLGroup).get(group_id)
        if not group:
            return False
        targets = group.urls.limit(limit).offset(offset).all()
        if include_id:
            return [{"id": t.id, "url": t.target} for t in targets]
        else:
            return [t.target for t in targets]
    finally:
        session.close()

def delete_group(group_id=None, name=None):
    """Remove target group
    @param group_id: Id of a target group
    @param name: Name of a target group"""
    if not group_id and not name:
        return False

    session = db.Session()
    try:
        group = session.query(URLGroup)
        if name:
            group = group.filter_by(name=name)
        if group_id:
            group = group.filter_by(id=group_id)

        group = group.first()
        if not group:
            return False

        session.delete(group)
        session.commit()
        return True
    finally:
        session.close()

def add_alert(level, title, content, **kwargs):
    alert = Alert(level=level, title=title, content=content, **kwargs)
    session = db.Session()
    try:
        session.add(alert)
        session.commit()
    finally:
        session.close()

def list_alerts(level=None, target_group=None, limit=100, offset=0):
    session = db.Session()
    alerts = []
    try:
        search = session.query(Alert)
        if level:
            search = search.filter_by(level=level)
        if target_group:
            search = search.filter_by(target_group=target_group)
        alerts = search.limit(limit).offset(offset).all()
    finally:
        session.close()

    return alerts

def add_group(name, description, schedule):
    schedule_next = schedule_time_next(schedule)
    exists = False
    session = db.Session()
    try:
        g = URLGroup(name=name, description=description, schedule=schedule,
                     schedule_next=schedule_next)
        session.add(g)
        session.commit()
        group_id = g.id
    except IntegrityError:
        exists = True
    session.close()
    if exists:
        raise KeyError("Group with name %r exists" % name)
    return group_id

def list_groups(limit=50, offset=0):
    """Retrieve a list of target groups"""
    groups = []
    session = db.Session()
    try:
        search = session.query(URLGroup).order_by(URLGroup.id.desc())
        groups = search.limit(limit).offset(offset).all()

        if groups:
            for group in groups:
                session.expunge(group)
    finally:
        session.close()
    return groups
