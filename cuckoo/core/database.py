# Copyright (C) 2012-2013 Claudio Guarnieri.
# Copyright (C) 2014-2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import datetime
import json
import logging
import os
import sys
import threading

from cuckoo.common.colors import green
from cuckoo.common.config import config, parse_options, emit_options
from cuckoo.common.exceptions import CuckooDatabaseError
from cuckoo.common.exceptions import CuckooOperationalError
from cuckoo.common.exceptions import CuckooDependencyError
from cuckoo.common.objects import File, URL, Dictionary
from cuckoo.common.utils import Singleton, classlock, json_encode
from cuckoo.misc import cwd, format_command
from cuckoo.core.task import Task as CoreTask

from sqlalchemy import create_engine, Column, not_, func
from sqlalchemy import Integer, String, Boolean, DateTime, Enum
from sqlalchemy import ForeignKey, Text, Index, Table, TypeDecorator
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import sessionmaker, relationship, joinedload

Base = declarative_base()

log = logging.getLogger(__name__)

SCHEMA_VERSION = "15740ce250e6"
TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_COMPLETED = "completed"
TASK_RECOVERED = "recovered"
TASK_REPORTED = "reported"
TASK_FAILED_ANALYSIS = "failed_analysis"
TASK_FAILED_PROCESSING = "failed_processing"
TASK_FAILED_REPORTING = "failed_reporting"

status_type = Enum(
    TASK_PENDING, TASK_RUNNING, TASK_COMPLETED, TASK_REPORTED, TASK_RECOVERED,
    TASK_FAILED_ANALYSIS, TASK_FAILED_PROCESSING, TASK_FAILED_REPORTING,
    name="status_type"
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
    tags = relationship("Tag", secondary=machines_tags, single_parent=True,
                        backref="machine")
    options = Column(JsonTypeList255(), nullable=True)
    interface = Column(String(255), nullable=True)
    snapshot = Column(String(255), nullable=True)
    locked = Column(Boolean(), nullable=False, default=False)
    locked_changed_on = Column(DateTime(timezone=False), nullable=True)
    status = Column(String(255), nullable=True)
    status_changed_on = Column(DateTime(timezone=False), nullable=True)
    resultserver_ip = Column(String(255), nullable=False)
    resultserver_port = Column(Integer(), nullable=False)
    _rcparams = Column("rcparams", Text(), nullable=True)
    manager = Column(String(255), nullable=True)

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
                 snapshot, resultserver_ip, resultserver_port, manager):
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

class Sample(Base):
    """Submitted files details."""
    __tablename__ = "samples"

    id = Column(Integer(), primary_key=True)
    file_size = Column(Integer(), nullable=False)
    file_type = Column(Text(), nullable=False)
    md5 = Column(String(32), nullable=False)
    crc32 = Column(String(8), nullable=False)
    sha1 = Column(String(40), nullable=False)
    sha256 = Column(String(64), nullable=False)
    sha512 = Column(String(128), nullable=False)
    ssdeep = Column(String(255), nullable=True)
    __table_args__ = Index("hash_index", "md5", "crc32", "sha1",
                           "sha256", "sha512", unique=True),

    def __repr__(self):
        return "<Sample('{0}','{1}')>".format(self.id, self.sha256)

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

    def __init__(self, md5, crc32, sha1, sha256, sha512,
                 file_size, file_type, ssdeep):
        self.md5 = md5
        self.sha1 = sha1
        self.crc32 = crc32
        self.sha256 = sha256
        self.sha512 = sha512
        self.file_size = file_size
        self.file_type = file_type
        self.ssdeep = ssdeep

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
        return "<Error('{0}','{1}','{2}')>".format(self.id, self.message, self.task_id)

class Task(Base):
    """Analysis task queue."""
    __tablename__ = "tasks"

    id = Column(Integer(), primary_key=True)
    target = Column(Text(), nullable=False)
    category = Column(String(255), nullable=False)
    timeout = Column(Integer(), server_default="0", nullable=False)
    priority = Column(Integer(), server_default="1", nullable=False)
    custom = Column(Text(), nullable=True)
    owner = Column(String(64), nullable=True)
    machine = Column(String(255), nullable=True)
    package = Column(String(255), nullable=True)
    tags = relationship("Tag", secondary=tasks_tags, single_parent=True,
                        backref="task", lazy="subquery")
    _options = Column("options", Text(), nullable=True)
    platform = Column(String(255), nullable=True)
    memory = Column(Boolean, nullable=False, default=False)
    enforce_timeout = Column(Boolean, nullable=False, default=False)
    clock = Column(DateTime(timezone=False),
                   default=datetime.datetime.now,
                   nullable=False)
    added_on = Column(DateTime(timezone=False),
                      default=datetime.datetime.now,
                      nullable=False)
    start_on = Column(DateTime(timezone=False), default=datetime.datetime.now,
                      nullable=False)
    started_on = Column(DateTime(timezone=False), nullable=True)
    completed_on = Column(DateTime(timezone=False), nullable=True)
    status = Column(status_type, server_default=TASK_PENDING, nullable=False)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=True)
    submit_id = Column(
        Integer, ForeignKey("submit.id"), nullable=True, index=True
    )
    processing = Column(String(16), nullable=True)
    route = Column(String(16), nullable=True)
    sample = relationship("Sample", backref="tasks")
    submit = relationship("Submit", backref="tasks")
    errors = relationship(
        "Error", backref="tasks", cascade="save-update, delete"
    )

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
        d["duration"] = self.duration()

        return d

    def to_json(self):
        """Converts object to JSON.
        @return: JSON data
        """
        return json_encode(self.to_dict())

    def __init__(self, target=None, id=None, category=None):
        self.target = target
        self.id = id
        self.category = category

    def __repr__(self):
        return "<Task('{0}','{1}')>".format(self.id, self.target)

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
                    connection_string, connect_args={"sslmode": "disable"})
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

    def _get_or_create(self, session, model, **kwargs):
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
            log.debug("Database error cleaning machines: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def add_machine(self, name, label, ip, platform, options, tags, interface,
                    snapshot, resultserver_ip, resultserver_port, manager):
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
        machine = Machine(name=name,
                          label=label,
                          ip=ip,
                          platform=platform,
                          options=options,
                          interface=interface,
                          snapshot=snapshot,
                          resultserver_ip=resultserver_ip,
                          resultserver_port=resultserver_port,
                          manager=manager)

        # Deal with tags format (i.e., foo,bar,baz)
        if tags:
            for tag in tags.split(","):
                if tag.strip():
                    tag = self._get_or_create(session, Tag, name=tag.strip())
                    machine.tags.append(tag)
        session.add(machine)

        try:
            session.commit()
        except SQLAlchemyError as e:
            log.debug("Database error adding machine: %s", e)
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
        try:
            row = session.query(Task).get(task_id)
            if not row:
                return

            row.status = status

            if status == TASK_RUNNING:
                row.started_on = datetime.datetime.now()
            elif status == TASK_COMPLETED:
                row.completed_on = datetime.datetime.now()

            session.commit()
        except SQLAlchemyError as e:
            log.debug("Database error setting status: %s", e)
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
            row = session.query(Task).get(task_id)
            if not row:
                return

            row.machine = machine

            session.commit()
        except SQLAlchemyError as e:
            log.debug("Database error setting status: %s", e)
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
            row = session.query(Task).get(task_id)
            if not row:
                return

            row.route = route
            session.commit()
        except SQLAlchemyError as e:
            log.debug("Database error setting route: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def fetch(self, machine=None, service=True, exclude=[], use_start_on=True):
        """Fetches a task waiting to be processed and locks it for running.
        @param machine: Fetch task for specific machine
        @param service: Fetch service machine tasks
        @param lock: Lock task when fetching it
        @param exclude: List of task ids to exclude while fetching a task
        @param use_start_on: Only fetch tasks that have reached the time at
        which they should start
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

            if exclude:
                q = q.filter(~Task.id.in_(exclude))

            row = q.order_by(Task.priority.desc(), Task.added_on).first()

            return row
        except SQLAlchemyError as e:
            log.debug("Database error fetching task: %s", e)
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
            log.debug("Database error listing machines: %s", e)
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
            log.debug("Database error locking machine: %s", e)
            session.close()
            return None

        if machine:
            machine.locked = True
            machine.locked_changed_on = datetime.datetime.now()
            try:
                session.commit()
                session.refresh(machine)
            except SQLAlchemyError as e:
                log.debug("Database error updating machine: %s to locked", e)
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
            log.debug("Database error unlocking machine: %s", e)
            session.close()
            return None

        if machine:
            machine.locked = False
            machine.locked_changed_on = datetime.datetime.now()
            try:
                session.commit()
                session.refresh(machine)
            except SQLAlchemyError as e:
                log.debug("Database error locking machine: %s", e)
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
            log.debug("Database error counting machines: %s", e)
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
            log.debug("Database error getting available machines: %s", e)
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
        try:
            machine = session.query(Machine).filter_by(label=label).first()
        except SQLAlchemyError as e:
            log.debug("Database error setting machine status: %s", e)
            session.close()
            return

        if machine:
            machine.status = status
            machine.status_changed_on = datetime.datetime.now()
            try:
                session.commit()
                session.refresh(machine)
            except SQLAlchemyError as e:
                log.debug("Database error setting machine status: %s", e)
                session.rollback()
            finally:
                session.close()
        else:
            session.close()

    @classlock
    def set_machine_rcparams(self, label, rcparams):
        """Set remote control connection params for a virtual machine.
        @param label: virtual machine label
        @param rcparams: dict with keys: protocol, host, port
        """
        session = self.Session()
        try:
            machine = session.query(Machine).filter_by(label=label).first()
        except SQLAlchemyError as e:
            log.debug("Database error setting machine rcparams: %s", e)
            session.close()
            return

        if machine:
            machine.rcparams = rcparams
            try:
                session.commit()
                session.refresh(machine)
            except SQLAlchemyError as e:
                log.debug("Database error setting machine rcparams: %s", e)
                session.rollback()
            finally:
                session.close()
        else:
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
            log.debug("Database error adding error log: %s", e)
            session.rollback()
        finally:
            session.close()

    @classlock
    def add_sample(self, file_obj):
        """Add a new sample to the database.
        @param file_obj: cuckoo.common.objects.File object of the sample
        """
        if not isinstance(file_obj, File):
            log.error("Cannot store sample. %s is not a file object", file_obj)
            return None

        sample = Sample(
            md5=file_obj.get_md5(),
            crc32=file_obj.get_crc32(),
            sha1=file_obj.get_sha1(),
            sha256=file_obj.get_sha256(),
            sha512=file_obj.get_sha512(),
            file_size=file_obj.get_size(),
            file_type=file_obj.get_type(),
            ssdeep=file_obj.get_ssdeep()
        )

        session = self.Session()
        try:
            session.add(sample)
            session.commit()
            sample_id = sample.id
        except SQLAlchemyError as e:
            session.rollback()
            log.debug("Database error storing new sample: %s", e)
            return None
        finally:
            session.close()

        return sample_id

    # The following functions are mostly used by external utils.
    @classlock
    def add(self, target, timeout=0, package="", options="", priority=1,
            custom="", owner="", machine="", platform="", tags=None,
            memory=False, enforce_timeout=False, clock=None, category=None,
            submit_id=None, sample_id=None, start_on=None):
        """Add a task to database.
        @param target: target of this task(file path or url)
        @param timeout: selected timeout.
        @param package: the analysis package to use
        @param options: analysis options.
        @param priority: analysis priority.
        @param custom: custom options.
        @param owner: task owner.
        @param machine: selected machine.
        @param platform: platform.
        @param tags: optional tags that must be set for machine selection
        @param memory: toggle full memory dump.
        @param enforce_timeout: toggle full timeout execution.
        @param clock: virtual machine clock time
        @return: cursor or None.
        """
        session = self.Session()

        task = Task(target=target, category=category)
        task.timeout = timeout
        task.priority = priority
        task.custom = custom
        task.owner = owner
        task.machine = machine
        task.package = package
        task.options = options
        task.platform = platform
        task.memory = memory
        task.enforce_timeout = enforce_timeout
        task.clock = clock
        task.submit_id = submit_id
        task.sample_id = sample_id
        task.start_on = start_on

        if tags:
            for tag in tags:
                task.tags.append(self._get_or_create(session, Tag, name=tag))

        session.add(task)

        try:
            session.commit()
            task_id = task.id
        except SQLAlchemyError as e:
            log.debug("Database error adding task: %s", e)
            session.rollback()
            return None
        finally:
            session.close()

        return task_id

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
            log.debug("Database error adding submit entry: %s", e)
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
            log.debug("Database error viewing submit: %s", e)
            return
        finally:
            session.close()
        return submit

    def list_tasks(self, limit=None, details=True, category=None, owner=None,
                   offset=None, status=None, sample_id=None, not_status=None,
                   completed_after=None, order_by=None):
        """Retrieve list of task.
        @param limit: specify a limit of entries.
        @param details: if details about must be included
        @param category: filter by category
        @param owner: task owner
        @param offset: list offset
        @param status: filter by task status
        @param sample_id: filter tasks for a sample
        @param not_status: exclude this task status from filter
        @param completed_after: only list tasks completed after this timestamp
        @param order_by: definition which field to sort by
        @return: list of tasks.
        """
        session = self.Session()
        try:
            search = session.query(Task)

            if status:
                search = search.filter_by(status=status)
            if not_status:
                search = search.filter(Task.status != not_status)
            if category:
                search = search.filter_by(category=category)
            if owner:
                search = search.filter_by(owner=owner)
            if details:
                search = search.options(
                    joinedload("errors"), joinedload("tags")
                )
            if sample_id is not None:
                search = search.filter_by(sample_id=sample_id)
            if completed_after:
                search = search.filter(Task.completed_on > completed_after)

            if order_by is not None:
                search = search.order_by(order_by)
            else:
                search = search.order_by(Task.added_on.desc())

            tasks = search.limit(limit).offset(offset).all()
            return tasks
        except SQLAlchemyError as e:
            log.debug("Database error listing tasks: %s", e)
            return []
        finally:
            session.close()

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
            log.debug("Database error counting tasks: %s", e)
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
            log.debug("Database error counting tasks: %s", e)
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
                    joinedload("errors"), joinedload("tags")
                ).get(task_id)
            else:
                task = session.query(Task).get(task_id)
        except SQLAlchemyError as e:
            log.debug("Database error viewing task: %s", e)
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
                joinedload("errors"), joinedload("tags")
            ).filter(Task.id.in_(task_ids)).order_by(Task.id).all()
        except SQLAlchemyError as e:
            log.debug("Database error viewing tasks: %s", e)
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
            log.debug("Database error deleting task: %s", e)
            session.rollback()
            return False
        finally:
            session.close()
        return True

    @classlock
    def view_sample(self, sample_id):
        """Retrieve information on a sample given a sample id.
        @param sample_id: ID of the sample to query.
        @return: details on the sample used in sample: sample_id.
        """
        session = self.Session()
        try:
            sample = session.query(Sample).get(sample_id)
        except AttributeError:
            return None
        except SQLAlchemyError as e:
            log.debug("Database error viewing task: %s", e)
            return None
        else:
            if sample:
                session.expunge(sample)
        finally:
            session.close()

        return sample

    @classlock
    def find_sample(self, md5=None, sha256=None):
        """Search samples by MD5.
        @param md5: md5 string
        @return: matches list
        """
        session = self.Session()
        try:
            if md5:
                sample = session.query(Sample).filter_by(md5=md5).first()
            elif sha256:
                sample = session.query(Sample).filter_by(sha256=sha256).first()
        except SQLAlchemyError as e:
            log.debug("Database error searching sample: %s", e)
            return None
        else:
            if sample:
                session.expunge(sample)
        finally:
            session.close()
        return sample

    @classlock
    def count_samples(self):
        """Counts the amount of samples in the database."""
        session = self.Session()
        try:
            sample_count = session.query(Sample).count()
        except SQLAlchemyError as e:
            log.debug("Database error counting samples: %s", e)
            return 0
        finally:
            session.close()
        return sample_count

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
            log.debug("Database error viewing machine: %s", e)
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
            log.debug("Database error viewing machine by label: %s", e)
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
            log.debug("Database error viewing errors: %s", e)
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
            log.debug("Database error getting new processing tasks: %s", e)
        finally:
            session.close()
