# Copyright (C) 2010-2013 Claudio Guarnieri.
# Copyright (C) 2014-2016 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

"""Added failed statuses to tasks (from Cuckoo 1.1 to 1.2)

Revision ID: 495d5a6edef3
Revises: 18eee46c6f81
Create Date: 2015-02-28 19:08:29.284111

"""
# Spaghetti as a way of life.

# Revision identifiers, used by Alembic.
revision = "495d5a6edef3"
down_revision = "18eee46c6f81"

from datetime import datetime

from alembic import op
from dateutil.parser import parse
import sqlalchemy as sa

def upgrade():
    conn = op.get_bind()

    # Deal with Alembic shit.
    # Alembic is so ORMish that it was impossible to write code which works
    #  on different DBMS.
    if conn.engine.driver == "psycopg2":
        # Altering status ENUM.
        # This shit of raw SQL is here because alembic doesn't deal
        #  well with alter_colum of ENUM type. Commit because SQLAlchemy
        # doesn't support ALTER TYPE in a transaction.
        op.execute('COMMIT')
        conn.execute("ALTER TYPE status_type ADD VALUE 'failed_reporting'")
    else:
        # Read data.
        tasks_data = []
        old_tasks = conn.execute(
            "select id, target, category, timeout, priority, custom, machine,"
            " package, options, platform, memory, enforce_timeout, clock,"
            " added_on, started_on, completed_on, status, sample_id from tasks"
        ).fetchall()
        for item in old_tasks:
            d = {}
            d["id"] = item[0]
            d["target"] = item[1]
            d["category"] = item[2]
            d["timeout"] = item[3]
            d["priority"] = item[4]
            d["custom"] = item[5]
            d["machine"] = item[6]
            d["package"] = item[7]
            d["options"] = item[8]
            d["platform"] = item[9]
            d["memory"] = item[10]
            d["enforce_timeout"] = item[11]

            if isinstance(item[12], datetime):
                d["clock"] = item[12]
            elif item[12]:
                d["clock"] = parse(item[12])
            else:
                d["clock"] = None

            if isinstance(item[13], datetime):
                d["added_on"] = item[13]
            elif item[13]:
                d["added_on"] = parse(item[13])
            else:
                d["added_on"] = None

            if isinstance(item[14], datetime):
                d["started_on"] = item[14]
            elif item[14]:
                d["started_on"] = parse(item[14])
            else:
                d["started_on"] = None

            if isinstance(item[15], datetime):
                d["completed_on"] = item[15]
            elif item[15]:
                d["completed_on"] = parse(item[15])
            else:
                d["completed_on"] = None

            d["status"] = item[16]
            d["sample_id"] = item[17]

            tasks_data.append(d)
        if conn.engine.driver == "mysqldb":
            # Disable foreign key checking to migrate table avoiding checks.
            op.execute('SET foreign_key_checks = 0')

            # Drop old table.
            op.drop_table("tasks")

            # Drop old Enum.
            sa.Enum(name="status_type").drop(op.get_bind(), checkfirst=False)
            # Create table with 1.2 schema.
            op.create_table(
                "tasks",
                sa.Column("id", sa.Integer(), nullable=False),
                sa.Column("target", sa.String(length=255), nullable=False),
                sa.Column("category", sa.String(length=255), nullable=False),
                sa.Column(
                    "timeout", sa.Integer(), server_default="0",
                    nullable=False
                ),
                sa.Column(
                    "priority", sa.Integer(), server_default="1",
                    nullable=False
                ),
                sa.Column("custom", sa.String(length=255), nullable=True),
                sa.Column("machine", sa.String(length=255), nullable=True),
                sa.Column("package", sa.String(length=255), nullable=True),
                sa.Column("options", sa.String(length=255), nullable=True),
                sa.Column("platform", sa.String(length=255), nullable=True),
                sa.Column(
                    "memory", sa.Boolean(), nullable=False, default=False),
                sa.Column(
                    "enforce_timeout", sa.Boolean(), nullable=False,
                    default=False
                ),
                sa.Column(
                    "clock", sa.DateTime(timezone=False), default=datetime.now,
                    nullable=False
                ),
                sa.Column(
                    "added_on", sa.DateTime(timezone=False), nullable=False
                ),
                sa.Column(
                    "started_on", sa.DateTime(timezone=False), nullable=True
                ),
                sa.Column(
                    "completed_on", sa.DateTime(timezone=False), nullable=True
                ),
                sa.Column(
                    "status", sa.Enum(
                        "pending", "running", "completed", "reported",
                        "recovered", "failed_analysis", "failed_processing",
                        "failed_reporting", name="status_type"
                    ),
                    server_default="pending", nullable=False
                ),
                sa.Column(
                    "sample_id", sa.Integer, sa.ForeignKey("samples.id"),
                    nullable=True
                ),
                sa.PrimaryKeyConstraint("id")
            )
            op.execute('COMMIT')

            # Insert data.
            op.bulk_insert(Task.__table__, tasks_data)
            # Enable foreign key.
            op.execute('SET foreign_key_checks = 1')

        else:
            op.drop_table("tasks")

            # Create table with 1.2 schema.
            op.create_table(
                "tasks",
                sa.Column("id", sa.Integer(), nullable=False),
                sa.Column("target", sa.String(length=255), nullable=False),
                sa.Column("category", sa.String(length=255), nullable=False),
                sa.Column(
                    "timeout", sa.Integer(), server_default="0", nullable=False
                ),
                sa.Column(
                    "priority", sa.Integer(), server_default="1",
                    nullable=False
                ),
                sa.Column("custom", sa.String(length=255), nullable=True),
                sa.Column("machine", sa.String(length=255), nullable=True),
                sa.Column("package", sa.String(length=255), nullable=True),
                sa.Column("options", sa.String(length=255), nullable=True),
                sa.Column("platform", sa.String(length=255), nullable=True),
                sa.Column(
                    "memory", sa.Boolean(), nullable=False, default=False
                ),
                sa.Column(
                    "enforce_timeout", sa.Boolean(), nullable=False,
                    default=False
                ),
                sa.Column(
                    "clock", sa.DateTime(timezone=False), default=datetime.now,
                    nullable=False
                ),
                sa.Column(
                    "added_on", sa.DateTime(timezone=False), nullable=False
                ),
                sa.Column(
                    "started_on", sa.DateTime(timezone=False), nullable=True
                ),
                sa.Column(
                    "completed_on", sa.DateTime(timezone=False), nullable=True
                ),
                sa.Column(
                    "status", sa.Enum(
                        "pending", "running", "completed", "reported",
                        "recovered", "failed_analysis", "failed_processing",
                        "failed_reporting", name="status_type"
                    ),
                    server_default="pending", nullable=False),
                sa.Column(
                    "sample_id", sa.Integer, sa.ForeignKey("samples.id"),
                    nullable=True
                ),
                sa.PrimaryKeyConstraint("id")
            )

            # Insert data.
            op.bulk_insert(Task.__table__, tasks_data)

def downgrade():
    pass

Base = sa.ext.declarative.declarative_base()

TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_COMPLETED = "completed"
TASK_RECOVERED = "recovered"
TASK_REPORTED = "reported"
TASK_FAILED_ANALYSIS = "failed_analysis"
TASK_FAILED_PROCESSING = "failed_processing"
TASK_FAILED_REPORTING = "failed_reporting"

tasks_tags = sa.Table(
    "tasks_tags", Base.metadata,
    sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id")),
    sa.Column("tag_id", sa.Integer, sa.ForeignKey("tags.id"))
)

class Task(Base):
    """Analysis task queue."""
    __tablename__ = "tasks"

    id = sa.Column(sa.Integer(), primary_key=True)
    target = sa.Column(sa.Text(), nullable=False)
    category = sa.Column(sa.String(255), nullable=False)
    timeout = sa.Column(sa.Integer(), server_default="0", nullable=False)
    priority = sa.Column(sa.Integer(), server_default="1", nullable=False)
    custom = sa.Column(sa.String(255), nullable=True)
    owner = sa.Column(sa.String(64), nullable=True)
    machine = sa.Column(sa.String(255), nullable=True)
    package = sa.Column(sa.String(255), nullable=True)
    tags = sa.orm.relationship(
        "Tag", secondary=tasks_tags, cascade="all, delete", single_parent=True,
        backref=sa.orm.backref("task", cascade="all"), lazy="subquery"
    )
    options = sa.Column(sa.String(255), nullable=True)
    platform = sa.Column(sa.String(255), nullable=True)
    memory = sa.Column(sa.Boolean, nullable=False, default=False)
    enforce_timeout = sa.Column(sa.Boolean, nullable=False, default=False)
    clock = sa.Column(
        sa.DateTime(timezone=False),default=datetime.now, nullable=False
    )
    added_on = sa.Column(
        sa.DateTime(timezone=False), default=datetime.now, nullable=False
    )
    started_on = sa.Column(sa.DateTime(timezone=False), nullable=True)
    completed_on = sa.Column(sa.DateTime(timezone=False), nullable=True)
    status = sa.Column(
        sa.Enum(
            TASK_PENDING, TASK_RUNNING, TASK_COMPLETED, TASK_REPORTED,
            TASK_RECOVERED, TASK_FAILED_ANALYSIS, TASK_FAILED_PROCESSING,
            TASK_FAILED_REPORTING, name="status_type"
        ),
        server_default=TASK_PENDING, nullable=False
    )
    sample_id = sa.Column(
        sa.Integer, sa.ForeignKey("samples.id"), nullable=True
    )
    sample = sa.orm.relationship("Sample", backref="tasks")
    guest = sa.orm.relationship(
        "Guest", uselist=False, backref="tasks", cascade="save-update, delete"
    )
    errors = sa.orm.relationship(
        "Error", backref="tasks", cascade="save-update, delete"
    )
