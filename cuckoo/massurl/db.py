# Copyright (C) 2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - https://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import time

from sqlalchemy import Column, ForeignKey, desc, asc, and_, func
from sqlalchemy import Integer, String, Boolean, DateTime, Text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship

from cuckoo.common.objects import Dictionary, URL as URLHashes
from cuckoo.common.utils import json_encode
from cuckoo.core.database import Database, Base, Tag
from cuckoo.massurl.schedutil import schedule_time_next

db = Database()

class ToDict(object):
    """Mixin to turn simple objects into a dict or JSON (no relation
    support)"""
    def to_dict(self, dt=True, additional=[]):
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

        for field in additional:
            d[field] = getattr(self, field)

        return d

    def to_json(self):
        """Converts object to JSON.
        @return: JSON data
        """
        return json_encode(self.to_dict())

class Signature(Base, ToDict):
    """User created URL diary signatures"""
    __tablename__ = "massurl_signatures"

    id = Column(Integer(), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    content = Column(Text(), nullable=False)
    level = Column(Integer(), nullable=False, default=1)
    enabled = Column(Boolean(), nullable=False, default=True)
    last_run = Column(Integer, nullable=False)

class Alert(Base, ToDict):
    """Dashboard alert history"""
    __tablename__ = "massurl_alerts"

    id = Column(Integer(), primary_key=True)
    timestamp = Column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
    level = Column(Integer(), nullable=False, default=1)
    title = Column(String(255), nullable=False)
    content = Column(Text(), nullable=False)
    target = Column(Text(), nullable=True)
    url_group_name = Column(String(255), nullable=True)
    task_id = Column(Integer(), nullable=True)
    diary_id = Column(String(36), nullable=True)
    signature = Column(String(255), nullable=True)
    read = Column(Boolean(), default=False, nullable=False)

class URL(Base, ToDict):
    __tablename__ = "massurl_urls"
    id = Column(String(64), primary_key=True)
    target = Column(String(2048), nullable=False, unique=True)

class URLGroupURL(Base):
    """Associates URLs with URL groups"""
    __tablename__ = "massurl_url_group_urls"

    url_id = Column(
        String(64), ForeignKey("massurl_urls.id", ondelete="CASCADE"),
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
    run = Column(Integer(), nullable=False)
    resubmitted = Column(Boolean(), default=False, nullable=False)
    url_group_id = Column(
        Integer(), ForeignKey("massurl_url_groups.id"), nullable=False
    )
    task_id = Column(Integer(), ForeignKey("tasks.id"), nullable=False)

class ProfileTag(Base, ToDict):
    __tablename__ = "massurl_profile_tags"

    profile_id = Column(
        Integer(), ForeignKey("massurl_profiles.id", ondelete="CASCADE"),
        nullable=False, primary_key=True
    )
    tag_id = Column(
        Integer(), ForeignKey("tags.id"), nullable=False, primary_key=True
    )

class Profile(Base, ToDict):
    __tablename__ = "massurl_profiles"
    id = Column(Integer(), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    browser = Column(String(255), nullable=False)
    route = Column(String(255), nullable=False)
    country = Column(String(255), nullable=True)
    tags = relationship("Tag", secondary=ProfileTag.__table__, lazy="subquery")

    def to_dict(self, dt=True):
        dictionary = super(Profile, self).to_dict(dt)
        dictionary["tags"] = [{"id": t.id,"name":t.name} for t in self.tags]
        return dictionary

class URLGroupProfile(Base, ToDict):
    __tablename__ = "massurl_url_group_profiles"

    profile_id = Column(
        Integer(), ForeignKey("massurl_profiles.id"), primary_key=True,
        nullable=False
    )
    group_id = Column(
        Integer(), ForeignKey("massurl_url_groups.id"), primary_key=True,
        nullable=False
    )

class URLGroup(Base, ToDict):
    """A group of URLs with a schedule"""
    __tablename__ = "massurl_url_groups"

    id = Column(Integer(), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text(), nullable=False)

    max_parallel = Column(Integer(), default=50, nullable=False)
    batch_size = Column(Integer(), default=5, nullable=False)
    batch_time = Column(Integer(), default=25, nullable=False)

    schedule = Column(Text(), nullable=True)
    schedule_next = Column(DateTime, nullable=True)
    completed = Column(Boolean(), default=True, nullable=False)
    run = Column(Integer(), nullable=False, default=0)
    status = Column(String(24), nullable=True)
    progress = Column(Integer(), nullable=True)

    urls = relationship("URL", secondary=URLGroupURL.__table__, lazy="dynamic")
    tasks = relationship(
        "Task", secondary=URLGroupTask.__table__, lazy="dynamic"
    )
    profiles = relationship(
        "Profile", secondary=URLGroupProfile.__table__, lazy="subquery"
    )

    def to_dict(self, dt=True, additional=[]):
        dictionary = super(URLGroup, self).to_dict(dt, additional)
        dictionary["profiles"] = [
            {"id": p.id, "name": p.name} for p in self.profiles
        ]
        return dictionary

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
        if not group:
            return None

        session.expunge(group)

        if details:
            group.urlcount = session.query(
                func.count(URLGroupURL.url_group_id)
            ).filter_by(url_group_id=group.id).first()[0]

            group.unread = session.query(func.count(Alert.id)).filter(
                Alert.url_group_name==group.name, Alert.read.is_(False)
            ).first()[0]

            group.highalert = session.query(func.count(Alert.id)).filter(
                Alert.url_group_name==group.name, Alert.read.is_(False),
                Alert.level >= 3
            ).first()[0]

    finally:
        session.close()

    return group


def get_chunks(it, max):
    for c in range(0, len(it), max):
        yield it[c:c+max]

def mass_group_add(urls, group_name=None, group_id=None):
    """Bulk add a list of url strings to a provided group.
    If no target exists for a provided urls, it will be created.
    @param urls: A list of URLs, may be of existing targets.
    @param group_name: A group name to add the targets to.
    @param group_id: A group identifier to add the targets to."""
    urls = [(url, URLHashes(url).get_sha256()) for url in set(urls)]

    session = db.Session()
    try:
        if not group_id:
            group_id = session.query(
                URLGroup.id
            ).filter_by(name=group_name).first()

        if not group_id:
            return False

        existing_sha256 = []
        # Find URLs from the given list that already exist.
        for chunk in get_chunks(urls, 5000):
            existing = [
                url.id for url in session.query(URL.id).filter(
                    URL.id.in_([sha256 for url, sha256 in chunk])
                ).all()
            ]
            existing_sha256.extend(existing)

        existing_sha256 = set(existing_sha256)
        # Create new entries for URLs that do not exist
        new_urls = [
            dict(id=sha256, target=url)
            for url, sha256 in urls if sha256 not in existing_sha256
        ]

        if new_urls:
            for chunk in get_chunks(new_urls, 5000):
                db.engine.execute(URL.__table__.insert(), chunk)

        # See if any of the existing URLs already belong to the specified
        # URL group
        url_in_group = []
        for chunk in get_chunks(list(existing_sha256), 5000):
            in_group = [
                group.url_id for group in session.query(
                    URLGroupURL.url_id).filter(
                        URLGroupURL.url_group_id == group_id,
                        URLGroupURL.url_id.in_(chunk)
                    ).all()
            ]
            url_in_group.extend(in_group)

        url_in_group = set(url_in_group)
        # Add URLs to the specified group of the do not belong to it yet.
        group_add = [
            dict(url_id=sha256, url_group_id=group_id)
            for url, sha256 in urls if not sha256 in url_in_group
        ]

        if group_add:
            for chunk in get_chunks(group_add, 5000):
                db.engine.execute(URLGroupURL.__table__.insert(), chunk)

        return group_id

    finally:
        session.close()

def delete_url_from_group(targets, group_id, clearall=False):
    """Removes the given list of urls from the given group
    @param targets: A list of urls
    @param group_id: The group id to remove the urls from"""
    targets = set(targets)
    session = db.Session()
    try:
        if clearall:
            db.engine.execute(
                URLGroupURL.__table__.delete(synchronize_session=False).where(
                    URLGroupURL.url_group_id==group_id
                )
            )

        else:
            urls = set(URLHashes(url).get_sha256() for url in targets)
            db.engine.execute(
                URLGroupURL.__table__.delete(
                    synchronize_session=False).where(
                    and_(
                        URLGroupURL.url_group_id==group_id,
                        URLGroupURL.url_id.in_(urls)
                    )
                )
            )

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

def list_alerts(level=None, url_group_name=None, limit=100, offset=0,
                orderby="timestamp", order="desc"):
    session = db.Session()
    alerts = []
    try:
        search = session.query(Alert)
        if level:
            search = search.filter_by(level=level)
        if url_group_name:
            search = search.filter_by(url_group_name=url_group_name)

        col = Alert.timestamp if orderby == "timestamp" else Alert.level
        sort = desc(col) if order == "desc" else asc(col)

        if orderby != "timestamp":
            search = search.order_by(
                sort, desc(Alert.timestamp) if order == "desc"
                else asc(Alert.timestamp)
            )
        else:
            search = search.order_by(sort)

        alerts = search.limit(limit).offset(offset).all()
    finally:
        session.close()

    return alerts

def add_group(name, description, schedule=None):
    schedule_next = None
    if schedule:
        schedule_next = schedule_time_next(schedule)

    exists = False
    session = db.Session()
    try:
        g = URLGroup(
            name=name, description=description, schedule=schedule,
            schedule_next=schedule_next
        )
        session.add(g)
        session.commit()
        group_id = g.id
    except IntegrityError:
        exists = True
    session.close()
    if exists:
        raise KeyError("Group with name %r exists" % name)
    return group_id

def list_groups(limit=50, offset=0, details=False):
    """Retrieve a list of target groups"""
    groups = []
    session = db.Session()
    try:
        search = session.query(URLGroup).order_by(URLGroup.id.desc())
        groups = search.limit(limit).offset(offset).all()

        if not groups:
            return []

        for group in groups:
            session.expunge(group)

        if not details:
            return groups

        for group in groups:
            group.urlcount = session.query(
                func.count(URLGroupURL.url_group_id)
            ).filter_by(url_group_id=group.id).first()[0]

            group.unread = session.query(func.count(Alert.id)).filter(
                Alert.url_group_name==group.name, Alert.read.is_(False)
            ).first()[0]
            group.highalert = session.query(func.count(Alert.id)).filter(
                Alert.url_group_name==group.name, Alert.read.is_(False),
                Alert.level >= 3
            ).first()[0]

        return groups
    finally:
        session.close()

def add_schedule(group_id, schedule):
    session = db.Session()
    try:
        session.query(URLGroup).filter(URLGroup.id == group_id).update({
            "schedule": schedule,
            "schedule_next": schedule_time_next(schedule)
        })
        session.commit()
    finally:
        session.close()

def remove_schedule(group_id):
    session = db.Session()
    try:
        session.query(URLGroup).filter(URLGroup.id == group_id).update({
            "schedule": None,
            "schedule_next": None
        })
        session.commit()
    finally:
        session.close()

def set_schedule_next(group_id, next_datetime):
    session = db.Session()
    try:
        session.query(URLGroup).filter(URLGroup.id == group_id).update({
            "schedule_next": next_datetime
        })
        session.commit()
    finally:
        session.close()

def find_group_task(task_id):
    session = db.Session()
    group = None
    try:
        group = session.query(URLGroup).filter(
            URLGroupTask.url_group_id==URLGroup.id,
            URLGroupTask.task_id==task_id
        ).first()

        if group:
            session.expunge(group)
    finally:
        session.close()
    return group

def mark_alert_read(alert_id=None, group_name=None, markall=False):
    session = db.Session()
    q = None
    try:
        if group_name:
            q = session.query(Alert).filter_by(url_group_name=group_name)
        elif markall:
            q = session.query(Alert)
        elif alert_id:
            q = session.query(Alert).filter_by(id=alert_id)
        if q:
            q.update({"read": True})
            session.commit()
    finally:
        session.close()

def delete_alert(alert_id=None, group_name=None, level=None, clear=False):
    session = db.Session()
    q = None
    try:
        if group_name:
            q = session.query(Alert).filter_by(url_group_name=group_name)
            if level:
                q = q.filter_by(level=level)
        elif clear:
            q = session.query(Alert)
        elif alert_id:
            q = session.query(Alert).filter_by(id=alert_id)
        elif level:
            q = session.query(Alert).filter_by(level=level)
        if q:
            q.delete()
            session.commit()
    finally:
        session.close()

def add_profile(name, browser, route, country=None, tags=[]):
    ses = db.Session()

    profile = Profile(name=name, browser=browser, route=route, country=country)
    try:
        dbtags = ses.query(Tag).filter(Tag.id.in_(set(tags))).all()
        profile.tags.extend(dbtags)
        ses.add(profile)
        ses.commit()
        profile_id = profile.id
        return profile_id
    except IntegrityError:
        raise KeyError("Profile with name '%s' exists" % name)
    finally:
        ses.close()

def update_profile(profile_id, browser, route, country=None, tags=[]):
    ses = db.Session()
    try:
        profile = ses.query(Profile).get(profile_id)
        if not profile:
            raise KeyError("Profile does not exist")

        dbtags = ses.query(Tag).filter(Tag.id.in_(set(tags))).all()
        profile.browser = browser
        profile.route = route
        profile.country = country
        profile.tags = dbtags
        ses.add(profile)
        ses.commit()
    finally:
        ses.close()

def list_profiles(limit=1000, offset=0):
    ses = db.Session()
    profiles = []
    try:
        profiles = ses.query(Profile).limit(limit).offset(offset).all()
        ses.expunge_all()
    finally:
        ses.close()
    return profiles

def find_profile(profile_id=None, profile_name=None):
    ses = db.Session()
    profile = None
    try:
        q = ses.query(Profile)
        if profile_id:
            q = q.filter_by(id=profile_id)
        elif profile_name:
            q = q.filter_by(name=profile_name)

        profile = q.first()
        if profile:
            ses.expunge(profile)
    finally:
        ses.close()
    return profile

def delete_profile(profile_id):
    ses = db.Session()
    try:
        profile = ses.query(Profile).get(profile_id)
        if not profile:
            return
        ses.delete(profile)
        ses.commit()
    finally:
        ses.close()

def update_profile_group(profile_ids, group_id):
    ses = db.Session()
    try:
        group = ses.query(URLGroup).get(group_id)
        if not group:
            return

        profiles = ses.query(Profile).filter(
            Profile.id.in_(set(profile_ids))
        ).all()

        group.profiles = profiles
        ses.add(group)
        ses.commit()
    finally:
        ses.close()

def update_settings_group(group_id, threshold, batch_size, batch_time):
    ses = db.Session()
    try:
        group = ses.query(URLGroup).get(group_id)
        if not group:
            return

        if threshold and threshold < 10:
            threshold = 10

        if batch_size and batch_size < 1:
            batch_size = 1

        if batch_time and batch_time < 5:
            batch_time = 5

        group.max_parallel = threshold or group.max_parallel
        group.batch_size = batch_size or group.batch_size
        group.batch_time = batch_time or group.batch_time
        ses.add(group)
        ses.commit()
    finally:
        ses.close()


def add_signature(name, content, level=1, enabled=False):
    ses = db.Session()

    sig = Signature(
        name=name, content=content, level=level, enabled=enabled,
        last_run=int(time.time()*1000)
    )
    try:
        ses.add(sig)
        ses.commit()
        sig_id = sig.id
        return sig_id
    except IntegrityError:
        raise KeyError("Signature with name '%s' already exists" % name)
    finally:
        ses.close()

def update_signature(signature_id, content=None, level=None, enabled=None,
                     last_run=None):
    ses = db.Session()
    try:
        signature = ses.query(Signature).get(signature_id)
        if not signature:
            raise KeyError("Signature does not exist")

        signature.content = content or signature.content
        signature.level = level or signature.level
        signature.enabled = enabled if enabled is\
                                       not None else signature.enabled
        signature.last_run = last_run or signature.last_run

        ses.add(signature)
        ses.commit()
    finally:
        ses.close()

def list_signatures(enabled_only=False):
    ses = db.Session()
    try:
        q = ses.query(Signature)
        if enabled_only:
            q = q.filter_by(enabled=True)

        sigs = q.all()
        if sigs:
            ses.expunge_all()
        return sigs
    finally:
        ses.close()

def find_signature(signature_id):
    ses = db.Session()
    signature = None
    try:
        signature = ses.query(Signature).get(signature_id)

        if signature:
            ses.expunge(signature)
    finally:
        ses.close()
    return signature

def delete_signature(signature_id):
    ses = db.Session()
    try:
        signature = ses.query(Signature).get(signature_id)
        if not signature:
            raise KeyError("Signature does not exist")

        ses.delete(signature)
        ses.commit()
    finally:
        ses.close()
