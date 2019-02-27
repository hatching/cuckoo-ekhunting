# Copyright (C) 2012-2013 Claudio Guarnieri.
# Copyright (C) 2014-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import json
import logging
import sys
import threading
import operator

from cuckoo.common.colors import green
from cuckoo.common.config import config, parse_options, emit_options
from cuckoo.common.exceptions import CuckooDatabaseError
from cuckoo.common.exceptions import CuckooOperationalError
from cuckoo.common.exceptions import CuckooDependencyError
from cuckoo.common.objects import Dictionary
from cuckoo.common.utils import Singleton, classlock, json_encode
from cuckoo.misc import cwd, format_command

from sqlalchemy import create_engine, Column, not_, func
from sqlalchemy import Integer, String, Boolean, DateTime, Enum
from sqlalchemy import ForeignKey, Text, Index, Table, TypeDecorator
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import sessionmaker, relationship, joinedload

Base = declarative_base()

log = logging.getLogger(__name__)

SCHEMA_VERSION = "e126de888ebd"
TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_COMPLETED = "completed"
TASK_RECOVERED = "recovered"
TASK_ABORTED = "aborted"
TASK_REPORTED = "reported"
TASK_FAILED_ANALYSIS = "failed_analysis"
TASK_FAILED_PROCESSING = "failed_processing"
TASK_FAILED_REPORTING = "failed_reporting"

# Task types
TYPE_REGULAR = "regular"
TYPE_LTA = "longterm"
TYPE_MASSURL = "massurl"
TYPE_BASELINE = "baseline"
TYPE_SERVICE = "service"

status_type = Enum(
    TASK_PENDING, TASK_RUNNING, TASK_COMPLETED, TASK_ABORTED, TASK_REPORTED,
    TASK_RECOVERED, TASK_FAILED_ANALYSIS, TASK_FAILED_PROCESSING,
    TASK_FAILED_REPORTING, name="status_type"
)

task_type = Enum(
    TYPE_REGULAR, TYPE_BASELINE, TYPE_SERVICE, TYPE_LTA, TYPE_MASSURL,
    name="task_type"
)

# Secondary table used in association Machine - Tag.
machines_tags = Table(
    "machines_tags", Base.metadata,
    Column("machine_id", Integer, ForeignKey("machines.id")),
    Column("tag_id", Integer, ForeignKey("tags.id"))
)

# Secondary table used in association Task - Tag.
tasks_tags = Table(
    "tasks_tags", Base.metadata,
    Column("task_id", Integer, ForeignKey("tasks.id")),
    Column("tag_id", Integer, ForeignKey("tags.id"))
)

class JsonType(TypeDecorator):
    """Custom JSON type."""
    impl = Text

    def process_bind_param(self, value, dialect):
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        return json.loads(value)

class JsonTypeList255(TypeDecorator):
    """Custom JSON type."""
    impl = String(255)

    def process_bind_param(self, value, dialect):
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        return json.loads(value) if value else []

class Machine(Base):
    """Configured virtual machines to be used as guests."""
    __tablename__ = "machines"

    id = Column(Integer(), primary_key=True)
    name = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)
    ip = Column(String(255), nullable=False)
    platform = Column(String(255), nullable=False)
    options = Column(JsonTypeList255(), nullable=True)
    interface = Column(String(255), nullable=True)
    snapshot = Column(String(255), nullable=True)
    locked = Column(Boolean(), nullable=False, default=False)
    reserved_by = Column(Integer(), nullable=True)
    locked_changed_on = Column(DateTime(timezone=False), nullable=True)
    status = Column(String(255), nullable=True)
    status_changed_on = Column(DateTime(timezone=False), nullable=True)
    resultserver_ip = Column(String(255), nullable=False)
    resultserver_port = Column(Integer(), nullable=False)
    _rcparams = Column("rcparams", Text(), nullable=True)
    manager = Column(String(255), nullable=True)
    tags = relationship(
        "Tag", secondary=machines_tags, single_parent=True, backref="machine"
    )

    def __repr__(self):
        return "<Machine('{0}','{1}')>".format(self.id, self.name)

    @hybrid_property
    def rcparams(self):
        if not self._rcparams:
            return {}
        return parse_options(self._rcparams)

    @rcparams.setter
    def rcparams(self, value):
        if isinstance(value, dict):
            self._rcparams = emit_options(value)
        else:
            self._rcparams = value

    def to_dict(self):
        """Converts object to dict.
        @return: dict
        """
        d = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, datetime.datetime):
                d[column.name] = value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                d[column.name] = value

        # Tags are a relation so no column to iterate.
        d["tags"] = [tag.name for tag in self.tags]
        return d

    def to_json(self):
        """Converts object to JSON.
        @return: JSON data
        """
        return json.dumps(self.to_dict())

    def is_analysis(self):
        """Is this an analysis machine? Generally speaking all machines are
        analysis machines, however, this is not the case for service VMs.
        Please refer to the services auxiliary module."""
        for tag in self.tags:
            if tag.name == "service":
                return
        return True

    def __init__(self, name, label, ip, platform, options, interface,
                 snapshot, resultserver_ip, resultserver_port, manager,
                 reserved_by=None):
        self.name = name
        self.label = label
        self.ip = ip
        self.platform = platform
        self.options = options
        self.interface = interface
        self.snapshot = snapshot
        self.resultserver_ip = resultserver_ip
        self.resultserver_port = resultserver_port
        self.manager = manager
        self.reserved_by = reserved_by

class Tag(Base):
    """Tag describing anything you want."""
    __tablename__ = "tags"

    id = Column(Integer(), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)

    def __repr__(self):
        return "<Tag('{0}','{1}')>".format(self.id, self.name)

    def __init__(self, name):
        self.name = name

class Submit(Base):
    """Submitted files details."""
    __tablename__ = "submit"

    id = Column(Integer(), primary_key=True)
    tmp_path = Column(Text(), nullable=True)
    added = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    submit_type = Column(String(16), nullable=True)
    data = Column(JsonType, nullable=True)

    def __init__(self, tmp_path, submit_type, data):
        self.tmp_path = tmp_path
        self.submit_type = submit_type
        self.data = data

class Longterm(Base):
    """Longterm analysis details"""
    __tablename__ = "longterms"

    id = Column(Integer(), primary_key=True)
    added_on = Column(DateTime, nullable=False, default=datetime.datetime.now)
    machine = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    last_completed = Column(Integer(), nullable=True)
    tasks = relationship("Task", backref="longterms", lazy="subquery")

    def __init__(self, name=None, machine=None):
        self.name = name
        self.machine = machine

    def to_dict(self):
        """Converts object to dict.
        @return: dict
        """
        d = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, datetime.datetime):
                d[column.name] = value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                d[column.name] = value

        # Tags are a relation so no column to iterate.
        d["tasks"] = [task.to_dict() for task in self.tasks]
        return d

    def to_json(self):
        """Converts object to JSON.
        @return: JSON data
        """
        return json.dumps(self.to_dict())

class Target(Base):
    """Submitted target details"""
    __tablename__ = "targets"

    id = Column(Integer(), primary_key=True)
    file_size = Column(Integer(), nullable=True)
    file_type = Column(Text(), nullable=True)
    md5 = Column(String(32), nullable=False)
    crc32 = Column(String(8), nullable=False)
    sha1 = Column(String(40), nullable=False)
    sha256 = Column(String(64), nullable=False)
    sha512 = Column(String(128), nullable=False)
    ssdeep = Column(String(255), nullable=True)
    category = Column(String(255), nullable=False)
    target = Column(Text(), nullable=False)
    task_id = Column(
        Integer(), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False
    )
    analyzed = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index(
            "ix_target_hash", "id", "sha256",
        ),
    )

    def __repr__(self):
        return "<Target('id=%s','category=%s','sha256=%s', 'task_id=%s')>" % (
            self.id, self.category, self.sha256, self.task_id
        )

    def to_dict(self):
        """Converts object to dict.
        @return: dict
        """
        d = {}
        for column in self.__table__.columns:
            d[column.name] = getattr(self, column.name)
        return d

    def to_json(self):
        """Converts object to JSON.
        @return: JSON data
        """
        return json.dumps(self.to_dict())

    def __init__(self, target, category, crc32, md5, sha1, sha256,
                 sha512, ssdeep=None, file_size=None, file_type=None,
                 task_id=None, analyzed=False):
        self.target = target
        self.category = category
        self.md5 = md5
        self.crc32 = crc32
        self.sha1 = sha1
        self.sha256 = sha256
        self.sha512 = sha512
        self.ssdeep = ssdeep
        self.file_size = file_size
        self.file_type = file_type
        self.task_id = task_id
        self.analyzed = analyzed

class Error(Base):
    """Analysis errors."""
    __tablename__ = "errors"

    id = Column(Integer(), primary_key=True)
    action = Column(String(64), nullable=True)
    message = Column(Text(), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)

    def to_dict(self):
        """Converts object to dict.
        @return: dict
        """
        d = {}
        for column in self.__table__.columns:
            d[column.name] = getattr(self, column.name)
        return d

    def to_json(self):
        """Converts object to JSON.
        @return: JSON data
        """
        return json.dumps(self.to_dict())

    def __init__(self, message, task_id, action=None):
        self.action = action
        self.message = message
        self.task_id = task_id

    def __repr__(self):
        return "<Error('{0}','{1}','{2}')>".format(
            self.id, self.message, self.task_id
        )

class Task(Base):
    """Analysis task queue."""
    __tablename__ = "tasks"

    id = Column(Integer(), primary_key=True)
    type = Column(task_type, server_default=TYPE_REGULAR, nullable=False)
    timeout = Column(Integer(), server_default="0", nullable=False)
    priority = Column(Integer(), server_default="1", nullable=False)
    custom = Column(Text(), nullable=True)
    owner = Column(String(64), nullable=True)
    machine = Column(String(255), nullable=True)
    package = Column(String(255), nullable=True)
    _options = Column("options", Text(), nullable=True)
    platform = Column(String(255), nullable=True)
    memory = Column(Boolean, nullable=False, default=False)
    enforce_timeout = Column(Boolean, nullable=False, default=False)
    clock = Column(
        DateTime(timezone=False), default=datetime.datetime.now, nullable=False
    )
    added_on = Column(
        DateTime(timezone=False), default=datetime.datetime.now, nullable=False
    )
    start_on = Column(
        DateTime(timezone=False), default=datetime.datetime.now, nullable=False
    )
    started_on = Column(DateTime(timezone=False), nullable=True)
    completed_on = Column(DateTime(timezone=False), nullable=True)
    status = Column(status_type, server_default=TASK_PENDING, nullable=False)
    processing = Column(String(16), nullable=True)
    route = Column(String(16), nullable=True)
    submit_id = Column(
        Integer(), ForeignKey("submit.id"), nullable=True, index=True
    )
    longterm_id = Column(
        Integer(), ForeignKey("longterms.id"), nullable=True
    )
    tags = relationship(
        "Tag", secondary=tasks_tags, single_parent=True, backref="task",
        lazy="subquery"
    )
    targets = relationship(
        "Target", lazy="subquery", cascade="all, delete-orphan"
    )
    errors = relationship(
        "Error", backref="tasks", cascade="save-update, delete"
    )
    submit = relationship("Submit", backref="tasks")

    def duration(self):
        if self.started_on and self.completed_on:
            return (self.completed_on - self.started_on).seconds
        return -1

    @hybrid_property
    def options(self):
        if not self._options:
            return {}
        return parse_options(self._options)

    @options.setter
    def options(self, value):
        if isinstance(value, dict):
            self._options = emit_options(value)
        else:
            self._options = value

    def to_dict(self, dt=False):
        """Converts object to dict.
        @param dt: encode datetime objects
        @return: dict
        """
        d = Dictionary()
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if dt and isinstance(value, datetime.datetime):
                d[column.name] = value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                d[column.name] = value

        # Tags are a relation so no column to iterate.
        d["tags"] = [tag.name for tag in self.tags]
        d["targets"] = [target.to_dict() for target in self.targets]
        d["duration"] = self.duration()

        return d

    def to_json(self):
        """Converts object to JSON.
        @return: JSON data
        """
        return json_encode(self.to_dict())

    def __init__(self, task_type=TYPE_REGULAR, id=None):
        self.id = id
        self.type = TYPE_REGULAR

    def __repr__(self):
        return "<Task('%s','%s','%s')>" % (self.id, self.type, self.status)

class AlembicVersion(Base):
    """Table used to pinpoint actual database schema release."""
    __tablename__ = "alembic_version"

    version_num = Column(String(32), nullable=False, primary_key=True)

class Database(object):
    """Analysis queue database.

    This class handles the creation of the database user for internal queue
    management. It also provides some functions for interacting with it.
    """
    __metaclass__ = Singleton

    task_columns = {
        "id": Task.id,
        "type": Task.type,
        "timeout": Task.timeout,
        "priority": Task.priority,
        "custom": Task.custom,
        "owner": Task.owner,
        "machine": Task.machine,
        "package": Task.package,
        "tags": Task.tags,
        "options": Task._options,
        "platform": Task.platform,
        "memory": Task.memory,
        "enforce_timeout": Task.enforce_timeout,
        "clock": Task.clock,
        "added_on": Task.added_on,
        "start_on": Task.start_on,
        "started_on": Task.started_on,
        "completed_on": Task.completed_on,
        "status": Task.status,
        "submit_id": Task.submit_id,
        "processing": Task.processing,
        "route": Task.route,
        "longterm_id": Task.longterm_id
    }

    def __init__(self, schema_check=True, echo=False):
        """
        @param dsn: database connection string.
        @param schema_check: disable or enable the db schema version check.
        @param echo: echo sql queries.
        """
        self._lock = None
        self.schema_check = schema_check
        self.echo = echo

    def connect(self, schema_check=None, dsn=None, create=True):
        """Connect to the database backend."""
        if schema_check is not None:
            self.schema_check = schema_check

        if not dsn:
            dsn = config("cuckoo:database:connection")
        if not dsn:
            dsn = "sqlite:///%s" % cwd("cuckoo.db")

        database_flavor = dsn.split(":", 1)[0].lower()
        if database_flavor == "sqlite":
            log.debug("Using database-wide lock for sqlite")
            self._lock = threading.RLock()

        self._connect_database(dsn)

        # Disable SQL logging. Turn it on for debugging.
        self.engine.echo = self.echo

        # Connection timeout.
        self.engine.pool_timeout = config("cuckoo:database:timeout")

        # Get db session.
        self.Session = sessionmaker(bind=self.engine)

        if create:
            self._create_tables()

    def _create_tables(self):
        """Creates all the database tables etc."""
        try:
            Base.metadata.create_all(self.engine)
        except SQLAlchemyError as e:
            raise CuckooDatabaseError(
                "Unable to create or connect to database: %s" % e
            )

        # Deal with schema versioning.
        # TODO: it's a little bit dirty, needs refactoring.
        tmp_session = self.Session()
        if not tmp_session.query(AlembicVersion).count():
            # Set database schema version.
            tmp_session.add(AlembicVersion(version_num=SCHEMA_VERSION))
            try:
                tmp_session.commit()
            except SQLAlchemyError as e:
                raise CuckooDatabaseError(
                    "Unable to set schema version: %s" % e
                )
                tmp_session.rollback()
            finally:
                tmp_session.close()
        else:
            # Check if db version is the expected one.
            last = tmp_session.query(AlembicVersion).first()
            tmp_session.close()
            if last.version_num != SCHEMA_VERSION and self.schema_check:
                log.warning(
                    "Database schema version mismatch: found %s, expected %s.",
                    last.version_num, SCHEMA_VERSION
                )
                log.error(
                    "Optionally make a backup and then apply the latest "
                    "database migration(s) by running:"
                )
                log.info("$ %s", green(format_command("migrate")))
                sys.exit(1)

    def __del__(self):
        """Disconnects pool."""
        self.engine.dispose()

    def _connect_database(self, connection_string):
        """Connect to a Database.
        @param connection_string: Connection string specifying the database
        """
        try:
            # TODO: this is quite ugly, should improve.
            if connection_string.startswith("sqlite"):
                # Using "check_same_thread" to disable sqlite
                # safety check on multiple threads.
                self.engine = create_engine(
                    connection_string,
                    connect_args={"check_same_thread": False}
                )
            elif connection_string.startswith("postgres"):
                # Disabling SSL mode to avoid some errors using sqlalchemy
                # and multiprocesing.
                # See: http://www.postgresql.org
                # /docs/9.0/static/libpq-ssl.html#LIBPQ-SSL-SSLMODE-STATEMENTS
                # TODO Check if this is still relevant. Especially provided the
                # fact that we're no longer using multiprocessing.
                self.engine = create_engine(
                    connection_string, connect_args={"sslmode": "disable"},
                    echo=True
                )
            else:
                self.engine = create_engine(connection_string)
        except ImportError as e:
            lib = e.message.split()[-1]

            if lib == "MySQLdb":
                raise CuckooDependencyError(
                    "Missing MySQL database driver (install with "
                    "`pip install mysql-python` on Linux or `pip install "
                    "mysqlclient` on Windows)"
                )

            if lib == "psycopg2":
                raise CuckooDependencyError(
                    "Missing PostgreSQL database driver (install with "
                    "`pip install psycopg2`)"
                )

            raise CuckooDependencyError(
                "Missing unknown database driver, unable to import %s" % lib
            )

    def get_or_create(self, session, model=Tag, **kwargs):
        """Get an ORM instance or create it if not exist.
        @param session: SQLAlchemy session object
        @param model: model to query
        @return: row instance
        """
        instance = session.query(model).filter_by(**kwargs).first()
        return instance or model(**kwargs)

    @classlock
    def drop(self):
        """Drop all tables."""
        try:
            Base.metadata.drop_all(self.engine)
        except SQLAlchemyError as e:
            raise CuckooDatabaseError(
                "Unable to drop all tables of the database: %s" % e
            )

    @classlock
    def clean_machines(self):
        """Clean old stored machines and related tables."""
        # Secondary table.
        # TODO: this is better done via cascade delete.
        self.engine.execute(machines_tags.delete())

        session = self.Session()
        try:
            session.query(Machine).delete()
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error cleaning machines: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def add_machine(self, name, label, ip, platform, options, tags, interface,
                    snapshot, resultserver_ip, resultserver_port, manager,
                    reserved_by=None):
        """Add a guest machine.
        @param name: machine id
        @param label: machine label
        @param ip: machine IP address
        @param platform: machine supported platform
        @param tags: list of comma separated tags
        @param interface: sniffing interface for this machine
        @param snapshot: snapshot name to use instead of the current one,
        if configured
        @param resultserver_ip: IP address of the Result Server
        @param resultserver_port: port of the Result Server
        @param manager The machine manager used
        """
        if options is None:
            options = []
        if not isinstance(options, (tuple, list)):
            options = options.split()

        session = self.Session()
        machine = Machine(
            name=name,
            label=label,
            ip=ip,
            platform=platform,
            options=options,
            interface=interface,
            snapshot=snapshot,
            resultserver_ip=resultserver_ip,
            resultserver_port=resultserver_port,
            manager=manager,
            reserved_by=reserved_by
        )

        # Deal with tags format (i.e., foo,bar,baz)
        if tags:
            for tag in tags.split(","):
                if tag.strip():
                    tag = self.get_or_create(session, Tag, name=tag.strip())
                    machine.tags.append(tag)
        session.add(machine)

        try:
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error adding machine: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def set_status(self, task_id, status):
        """Set task status.
        @param task_id: task identifier
        @param status: status string
        @return: operation status
        """
        session = self.Session()
        columns = {
            "status": status
        }
        if status == TASK_RUNNING:
            columns["started_on"] = datetime.datetime.now()
        elif status == TASK_COMPLETED:
            columns["completed_on"] = datetime.datetime.now()

        try:
            session.query(Task).filter_by(id=task_id).update(columns)
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error setting status: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def set_machine(self, task_id, machine):
        """Set given machine name in given task
        @param task_id task identifier
        @param machine: machine name
        """
        session = self.Session()
        try:
            session.query(Task).filter_by(id=task_id).update({
                "machine": machine
            })
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error setting status: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def machine_reserve(self, label, task_id):
        """Set a machine as reserved for a specific task id
        @param label: label of the machine to reserve
        @param task_id: id of the task to reserve the machine for"""
        session = self.Session()
        try:
            machine = session.query(Machine).filter_by(name=label).first()
            if not machine:
                raise CuckooDatabaseError(
                    "Tried to reserve non-existent machine %s" % label
                )

            machine.reserved_by = task_id
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error reserving machine for task: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def clear_reservation(self, label):
        """Clear reservation of a machine
        @param label: label of the machine to reserve"""
        session = self.Session()
        try:
            machine = session.query(Machine).filter_by(label=label).first()
            if not machine:
                raise CuckooDatabaseError(
                    "Tried to remove reservation from non-existent"
                    " machine %s" % label
                )

            machine.reserved_by = None
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error removing reservation of machine: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def set_route(self, task_id, route):
        """Set the taken route of this task.
        @param task_id: task identifier
        @param route: route string
        @return: operation status
        """
        session = self.Session()
        try:
            session.query(Task).filter_by(id=task_id).update({
                "route": route
            })
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error setting route: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def fetch(self, machine=None, service=True, exclude=[], use_start_on=True,
              task_id=None):
        """Fetches a task waiting to be processed and locks it for running.
        @param machine: Fetch task for specific machine
        @param service: Fetch service machine tasks
        @param exclude: List of task ids to exclude while fetching a task
        @param use_start_on: Only fetch tasks that have reached the time at
        which they should start
        @param task_id: Retrieve given task if it is ready to start
        @return: None or task
        """
        session = self.Session()
        try:
            q = session.query(Task).filter_by(status=TASK_PENDING)

            if use_start_on:
                q = q.filter(datetime.datetime.now() >= Task.start_on)

            if machine:
                q = q.filter_by(machine=machine)

            if not service:
                q = q.filter(not_(Task.tags.any(name="service")))

            if task_id:
                q = q.filter_by(id=task_id)

            if exclude:
                q = q.filter(~Task.id.in_(exclude))

            row = q.order_by(Task.priority.desc(), Task.added_on).first()

            return row
        except SQLAlchemyError as e:
            log.exception("Database error fetching task: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def list_machines(self, locked=False):
        """Lists virtual machines.
        @return: list of virtual machines
        """
        session = self.Session()
        try:
            if locked:
                machines = session.query(Machine).options(
                    joinedload("tags")
                ).filter_by(locked=True).all()
            else:
                machines = session.query(Machine).options(
                    joinedload("tags")).all()
            return machines
        except SQLAlchemyError as e:
            log.exception("Database error listing machines: %s", e)
            return []
        finally:
            session.close()

    @classlock
    def lock_machine(self, label=None, platform=None, tags=None):
        """Places a lock on a free virtual machine.
        @param label: optional virtual machine label
        @param platform: optional virtual machine platform
        @param tags: optional tags required (list)
        @return: locked machine
        """
        session = self.Session()

        # Preventive checks.
        if label and platform:
            # Wrong usage.
            log.error("You can select machine only by label or by platform.")
            return None
        elif label and tags:
            # Also wrong usage.
            log.error("You can select machine only by label or by tags.")
            return None

        try:
            machines = session.query(Machine)
            if label:
                machines = machines.filter_by(label=label)
            if platform:
                machines = machines.filter_by(platform=platform)
            if tags:
                for tag in tags:
                    machines = machines.filter(Machine.tags.any(name=tag.name))

            # Check if there are any machines that satisfy the
            # selection requirements.
            if not machines.count():
                raise CuckooOperationalError(
                    "No machines match selection criteria."
                )

            # Get the first free machine.
            machine = machines.filter_by(locked=False).first()
        except SQLAlchemyError as e:
            log.exception("Database error locking machine: %s", e)
            session.close()
            return None

        if machine:
            machine.locked = True
            machine.locked_changed_on = datetime.datetime.now()
            try:
                session.commit()
                session.refresh(machine)
            except SQLAlchemyError as e:
                log.exception("Database error updating machine: %s to locked", e)
                session.rollback()
                return None
            finally:
                session.close()
        else:
            session.close()

        return machine

    @classlock
    def unlock_machine(self, label):
        """Remove lock form a virtual machine.
        @param label: virtual machine label
        @return: unlocked machine
        """
        session = self.Session()
        try:
            machine = session.query(Machine).filter_by(label=label).first()
        except SQLAlchemyError as e:
            log.exception("Database error unlocking machine: %s", e)
            session.close()
            return None

        if machine:
            machine.locked = False
            machine.locked_changed_on = datetime.datetime.now()
            try:
                session.commit()
                session.refresh(machine)
            except SQLAlchemyError as e:
                log.exception("Database error locking machine: %s", e)
                session.rollback()
                return None
            finally:
                session.close()

        return machine

    @classlock
    def count_machines_available(self):
        """How many virtual machines are ready for analysis.
        @return: free virtual machines count
        """
        session = self.Session()
        try:
            machines_count = session.query(Machine).filter_by(
                locked=False
            ).count()
            return machines_count
        except SQLAlchemyError as e:
            log.exception("Database error counting machines: %s", e)
            return 0
        finally:
            session.close()

    @classlock
    def get_available_machines(self):
        """  Which machines are available
        @return: free virtual machines
        """
        session = self.Session()
        try:
            machines = session.query(Machine).options(
                joinedload("tags")
            ).filter_by(locked=False).all()
            return machines
        except SQLAlchemyError as e:
            log.exception("Database error getting available machines: %s", e)
            return []
        finally:
            session.close()

    @classlock
    def set_machine_status(self, label, status):
        """Set status for a virtual machine.
        @param label: virtual machine label
        @param status: new virtual machine status
        """
        session = self.Session()
        columns = {
            "status": status,
            "status_changed_on": datetime.datetime.now()
        }
        try:
            session.query(Machine).filter_by(label=label).update(columns)
        except SQLAlchemyError as e:
            log.exception("Database error updating machine status: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def set_machine_rcparams(self, label, rcparams):
        """Set remote control connection params for a virtual machine.
        @param label: virtual machine label
        @param rcparams: dict with keys: protocol, host, port
        """
        session = self.Session()
        if isinstance(rcparams, dict):
            rcparams = emit_options(rcparams)

        try:
            session.query(Machine).filter_by(label=label).update({
                "_rcparams": rcparams
            })
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error setting machine rcparams: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def add_error(self, message, task_id, action=None):
        """Add an error related to a task.
        @param message: error message
        @param task_id: ID of the related task
        """
        session = self.Session()
        error = Error(message=message, task_id=task_id, action=action)
        session.add(error)
        try:
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error adding error log: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def add_submit(self, tmp_path, submit_type, data):
        session = self.Session()

        submit = Submit(
            tmp_path=tmp_path, submit_type=submit_type, data=data or {}
        )
        session.add(submit)
        try:
            session.commit()
            session.refresh(submit)
            submit_id = submit.id
        except SQLAlchemyError as e:
            log.exception("Database error adding submit entry: %s", e)
            session.rollback()
        finally:
            session.close()
        return submit_id

    @classlock
    def view_submit(self, submit_id, tasks=False):
        session = self.Session()
        try:
            q = session.query(Submit)
            if tasks:
                q = q.options(joinedload("tasks"))
            submit = q.get(submit_id)
        except SQLAlchemyError as e:
            log.exception("Database error viewing submit: %s", e)
            return
        finally:
            session.close()
        return submit

    def list_tasks(self, filter_by=[], operators=[], values=[], details=True,
                   category=None, offset=None, limit=None, order_by=None,
                   **kwargs):
        """Retrieve a list of tasks. Any query possible.
        @param filter_by: contains the columns you want to filter on
        @param operators: contains the operator(s) you want to use when
        filtering
        @param values: contains the values to use when filtering with
        filter_by and operators
        @param offset: offset of task list
        @param limit: max amount of tasks to query
        @param details: include relationship table data
        @param order_by: the task table field to order the list by

        Example: list_tasks(filter_by="id", operators=">", values=500)
        would return all tasks with id larger than 500
        Example: list_tasks(filter_by="id", operators="between", values=(1, 5))
        would return all tasks with id between 1 and 5
        """
        tasklist = []
        filter_by = filter_by if isinstance(filter_by, list) else [filter_by]
        values = values if isinstance(values, list) else [values]
        operators = operators if isinstance(operators, list) else [operators]

        op_lookup = {
            ">": operator.gt,
            "<": operator.lt,
            ">=": operator.ge,
            "<=": operator.le,
            "!=": operator.ne
        }

        session = self.Session()
        try:
            search = session.query(Task)
            for arg, value in kwargs.iteritems():
                if value is not None:
                    search = search.filter_by(**{arg: value})

            for field in filter_by:
                operation = operators.pop(0)
                value = values.pop(0)
                if value is None:
                    continue

                op = op_lookup.get(operation)
                if op:
                    search = search.filter(op(
                        self.task_columns[field], value)
                    )
                elif operation == "between":
                    search = search.filter(
                        self.task_columns[field].between(*value)
                    )

            if category:
                search = search.join(Task.targets).filter_by(category=category)

            if details:
                search = search.options(
                    joinedload("errors"), joinedload("tags"),
                    joinedload("targets")
                )

            if order_by:
                search = search.order_by(self.task_columns[order_by])
            else:
                search = search.order_by(self.task_columns["added_on"].desc())

            tasklist = search.limit(limit).offset(offset).all()
        except SQLAlchemyError as e:
            log.exception("Database error retrieving a list of tasks: %s", e)
        finally:
            session.close()
        return tasklist

    def minmax_tasks(self):
        """Find tasks minimum and maximum
        @return: unix timestamps of minimum and maximum
        """
        session = self.Session()
        try:
            _min = session.query(func.min(Task.started_on).label(
                "min"
            )).first()
            _max = session.query(func.max(Task.completed_on).label(
                "max"
            )).first()

            if not isinstance(_min, DateTime) or \
                    not isinstance(_max, DateTime):
                return

            return int(_min[0].strftime("%s")), int(_max[0].strftime("%s"))
        except SQLAlchemyError as e:
            log.exception("Database error counting tasks: %s", e)
            return
        finally:
            session.close()

    @classlock
    def count_tasks(self, status=None):
        """Count tasks in the database
        @param status: apply a filter according to the task status
        @return: number of tasks found
        """
        session = self.Session()
        try:
            if status:
                tasks_count = session.query(Task).filter_by(
                    status=status
                ).count()
            else:
                tasks_count = session.query(Task).count()
            return tasks_count
        except SQLAlchemyError as e:
            log.exception("Database error counting tasks: %s", e)
            return 0
        finally:
            session.close()

    @classlock
    def view_task(self, task_id, details=True):
        """Retrieve information on a task.
        @param task_id: ID of the task to query.
        @return: details on the task.
        """
        session = self.Session()
        try:
            if details:
                task = session.query(Task).options(
                    joinedload("errors"), joinedload("tags"),
                    joinedload("targets")
                ).get(task_id)
            else:
                task = session.query(Task).get(task_id)
        except SQLAlchemyError as e:
            log.exception("Database error viewing task: %s", e)
            return None
        else:
            if task:
                session.expunge(task)
            return task
        finally:
            session.close()

    @classlock
    def view_tasks(self, task_ids):
        """Retrieve information on a task.
        @param task_id: ID of the task to query.
        @return: details on the task.
        """
        session = self.Session()
        try:
            tasks = session.query(Task).options(
                joinedload("errors"), joinedload("tags"), joinedload("targets")
            ).filter(Task.id.in_(task_ids)).order_by(Task.id).all()
        except SQLAlchemyError as e:
            log.exception("Database error viewing tasks: %s", e)
            return []
        else:
            for task in tasks:
                session.expunge(task)
            return tasks
        finally:
            session.close()

    @classlock
    def delete_task(self, task_id):
        """Delete information on a task.
        @param task_id: ID of the task to query.
        @return: operation status.
        """
        session = self.Session()
        try:
            task = session.query(Task).get(task_id)
            session.delete(task)
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Database error deleting task: %s", e)
            session.rollback()
            return False
        finally:
            session.close()
        return True

    @classlock
    def find_target(self, **kwargs):
        """Search target by any target field. Returns single target. None if
        no matching target"""
        session = self.Session()
        try:
            search = session.query(Target)
            for arg, value in kwargs.iteritems():
                search = search.filter_by(**{arg: value})

            target = search.first()
            if target:
                session.expunge(target)

        except SQLAlchemyError as e:
            log.exception("Database error searching for target: %s", e)
            return None
        finally:
            session.close()
        return target

    @classlock
    def count_targets(self, category=None):
        """Counts the amount of targets in the database"""
        session = self.Session()
        try:
            query = session.query(Target)
            if category:
                query.filter_by(category=category)

            count = query.count()
        except SQLAlchemyError as e:
            log.exception("Database error counting targets: %s", e)
            return None
        finally:
            session.close()
        return count

    @classlock
    def view_machine(self, name):
        """Show virtual machine.
        @params name: virtual machine name
        @return: virtual machine's details
        """
        session = self.Session()
        try:
            machine = session.query(Machine).options(
                joinedload("tags")
            ).filter_by(name=name).first()
        except SQLAlchemyError as e:
            log.exception("Database error viewing machine: %s", e)
            return None
        else:
            if machine:
                session.expunge(machine)
        finally:
            session.close()
        return machine

    @classlock
    def view_machine_by_label(self, label):
        """Show virtual machine.
        @params label: virtual machine label
        @return: virtual machine's details
        """
        session = self.Session()
        try:
            machine = session.query(Machine).options(
                joinedload("tags")
            ).filter_by(label=label).first()
        except SQLAlchemyError as e:
            log.exception("Database error viewing machine by label: %s", e)
            return None
        else:
            if machine:
                session.expunge(machine)
        finally:
            session.close()
        return machine

    @classlock
    def view_errors(self, task_id):
        """Get all errors related to a task.
        @param task_id: ID of task associated to the errors
        @return: list of errors.
        """
        session = self.Session()
        try:
            q = session.query(Error).filter_by(task_id=task_id)
            errors = q.order_by(Error.id).all()
        except SQLAlchemyError as e:
            log.exception("Database error viewing errors: %s", e)
            return []
        finally:
            session.close()
        return errors

    def processing_get_task(self, instance):
        """Get an available task for processing."""
        session = self.Session()

        # TODO We can get rid of the `processing` column once again by
        # introducing a "reporting" status, but this requires annoying
        # database migrations, so leaving that for another day.

        try:
            # Fetch a task that has yet to be processed and make sure no other
            # threads are allowed to access it through "for update".
            q = session.query(Task).filter_by(status=TASK_COMPLETED)
            q = q.filter_by(processing=None)
            q = q.order_by(Task.priority.desc(), Task.id)
            task = q.with_for_update().first()

            # There's nothing to process in the first place.
            if not task:
                return

            # Update the task so that it is processed by this instance.
            session.query(Task).filter_by(id=task.id).update({
                "processing": instance,
            })

            session.commit()
            session.refresh(task)

            # Only return the task if it was really assigned to this node. It
            # could be, e.g., in sqlite3, that the locking is misbehaving.
            if task.processing == instance:
                return task.id
        except SQLAlchemyError as e:
            log.exception("Database error getting new processing tasks: %s", e)
        finally:
            session.close()

    def view_longterm(self, longterm_id):
        """Retrieve longterm analysis info by id"""

        session = self.Session()
        try:
            lta = session.query(Longterm).get(longterm_id)

            if lta:
                session.expunge(lta)
            return lta
        except SQLAlchemyError as e:
            log.exception("Error retrieving longterm analysis: %s", e)
        finally:
            session.close()

        return None

    def add_longterm(self, name=None, machine=None):
        """Creata a new longterm analysis. It consists of multiple tasks
        that should be attached the the longterm_id returned by this
        method"""

        session = self.Session()
        lta = Longterm(name=name, machine=machine)
        try:
            session.add(lta)
            session.commit()
            longterm_id = lta.id
        except SQLAlchemyError as e:
            log.exception("Error creating new longterm analysis")
            session.rollback()
            return None
        finally:
            session.close()

        return longterm_id

    def set_latest_longterm(self, task_id, longterm_id):
        """Updates the last completed task field for a longterm analysis
        @param task_id: id of a task that is part of the given longterm
        analysis
        @param longterm_id: id of a longterm analysis"""
        session = self.Session()

        try:
            session.query(Longterm).filter_by(id=longterm_id).update({
                "last_completed": task_id
            })
            session.commit()
        except SQLAlchemyError as e:
            log.exception(
                "Error while updating latest task for longterm: %s", e
            )
        finally:
            session.close()

    def set_longterm_machine(self, label, longterm_id):
        """Set machine for given longterm analysis
        @param label: machine label
        @param longterm_id: id of a longterm analysis"""
        session = self.Session()

        try:
            session.query(Longterm).filter_by(id=longterm_id).update({
                "machine": label
            })
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Error while updating machine for longterm: %s", e)
        finally:
            session.close()

    def update_targets(self, target_dicts):
        """Update the target rows with the changes values in the list of target
        dicts.
        @param target_dicts: Al list of Target dictionaries containing all
        columns
        """
        session = self.Session()
        try:
            session.bulk_update_mappings(Target, target_dicts)
            session.commit()
        except SQLAlchemyError as e:
            log.exception("Error while updating target to analyzed. %s", e)
        finally:
            session.close()

    def list_tags(self, limit=1000, offset=0):
        """Return a list of all available tags"""
        session = self.Session()
        try:
            return session.query(Tag).limit(limit).offset(offset).all()
        finally:
            session.close()
