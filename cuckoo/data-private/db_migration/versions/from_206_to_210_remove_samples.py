# Copyright (C) 2018 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

"""Introduced targets table and changed references to targets.
- Creates the new target, tasks_targets and experiments tables
- Uses existing sample_id and url info to fill the targets table
- Removes columns sample_id, target, and category
- Removes the samples table

Revision ID: e126de888ebd
Revises: 15740ce250e6
Create Date: 2018-03-29 14:13:33.714691

"""

# Revision identifiers, used by Alembic.
revision = "e126de888ebd"
down_revision = "15740ce250e6"

import datetime
import dateutil
import sqlalchemy as sa

from alembic import op
from sqlalchemy import dialects
from sqlalchemy.sql import table, column

from cuckoo.common.objects import URL

Base = sa.ext.declarative.declarative_base()

def upgrade():
    conn = op.get_bind()
    dbdriver = conn.engine.driver

    # Drop new tables if they already exist. Could happen for some db engines
    # if Cuckoo is started before the migration
    metadata = sa.schema.MetaData()
    metadata.reflect(bind=conn)
    drop_on_exist = ["tasks_targets", "targets", "experiments"]
    for t in reversed(metadata.sorted_tables):
        if t.name in drop_on_exist:
            op.drop_table(t.name)

    # For MySQL, the table must be specified or it might throw an error
    op.drop_index("hash_index", "samples")

    # Create tables the new tables and add the new columns
    op.create_table(
        "targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("file_type", sa.Text(), nullable=True),
        sa.Column("md5", sa.String(length=32), nullable=False),
        sa.Column("crc32", sa.String(length=8), nullable=False),
        sa.Column("sha1", sa.String(length=40), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("sha512", sa.String(length=128), nullable=False),
        sa.Column("ssdeep", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("last_task", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id")
    )
    op.create_index(
        "target_index", "targets", [
            "md5", "crc32", "sha1", "sha256", "sha512"
        ],
        unique=True
    )

    op.create_table(
        "experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("added_on", sa.DateTime(), nullable=False),
        sa.Column("machine", sa.String(length=255), nullable=True),
        sa.Column("runs", sa.Integer(), server_default="1", nullable=False),
        sa.Column("ran", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_completed", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id")
    )

    op.create_table(
        "tasks_targets",
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], )
    )

    op.add_column(
        "machines", sa.Column("reserved_by", sa.Integer(), nullable=True)
    )
    op.add_column(
        "tasks", sa.Column("experiment_id", sa.Integer(), nullable=True)
    )

    # Postgres requires enums to exist when creating a column with them
    if dbdriver == "psycopg2":
        task_type = dialects.postgresql.ENUM(
            "regular", "baseline", "service", "experiment", name="task_type"
        )
        task_type.create(conn)

    op.add_column(
        "tasks",
        sa.Column(
            "type", sa.Enum(
                "regular", "baseline", "service", "experiment",
                name="task_type"
            ), server_default="regular", nullable=False
        )
    )

    if dbdriver != "pysqlite":
        op.create_foreign_key(
            None, "tasks", "experiments", ["experiment_id"], ["id"]
        )

    # Change existing tasks to the correct task type
    expr_tasks = table(
        "tasks", column("category", sa.String), column("type", sa.Enum)
    )

    op.execute(
        expr_tasks.update().where(
            expr_tasks.c.category=="baseline"
        ).values(type="baseline")
    )
    op.execute(
        expr_tasks.update().where(
            expr_tasks.c.category=="service"
        ).values(type="service")
    )

    # Create target rows from information out of existing task targets and
    # and sample rows. Create dict mapping between targets and their hashes
    # to be used when inserting the tasks_targets rows.
    last_id = 0
    migrated_targets = {}
    ignore = []
    while True:
        tasks = conn.execute(
            "SELECT id, category, target, sample_id FROM tasks WHERE id > %s "
            "ORDER BY id ASC LIMIT 1000" % last_id
        ).fetchall()
        if len(tasks) < 1:
            break

        target_data = []
        for task in tasks:
            last_id = task[0]
            sample = None
            url = None

            if task[3]:
                sample = conn.execute(
                    "SELECT id, file_size, file_type, md5, crc32, "
                    "sha1, sha256, sha512, ssdeep FROM samples "
                    "WHERE id=%s" % task[3]
                ).fetchone()
            elif task[1] == "url":
                url = URL(task[2])

            if not sample and not url:
                continue

            if not migrated_targets.get(task[2]):
                new_target = target_from_sample(
                    task[2], task[1], sample, url
                )
                migrated_targets[task[2]] = new_target["md5"]
                if new_target["md5"] not in ignore:
                    target_data.append(new_target)
                    ignore.append(new_target["md5"])

        op.bulk_insert(Target.__table__, target_data)

    # Fill the relational table that contains all targets for a task
    last_id = 0
    while True:
        tasks = conn.execute(
            "SELECT id, target, sample_id FROM tasks WHERE id > %s "
            "ORDER BY id ASC LIMIT 1000" % last_id
        ).fetchall()

        if len(tasks) < 1:
            break

        task_target_data = []
        for task in tasks:
            last_id = task[0]
            md5 = migrated_targets.get(task[1])
            if not md5:
                continue

            target_id = conn.execute(
                "SELECT id FROM targets WHERE md5='%s'" % md5
            ).fetchone()
            if not target_id:
                continue

            target_id = target_id[0]
            task_target_data.append({
                "task_id": task[0],
                "target_id": target_id
            })

        op.bulk_insert(tasks_targets, task_target_data)

    # PostgreSQL and MySQL have different names for the foreign key of
    # Task.sample_id -> Sample.id; for SQLite we do not drop/recreate the
    # foreign key.
    fkey_name = {
        "mysqldb": "tasks_ibfk_1",
        "psycopg2": "tasks_sample_id_fkey",
    }
    fkey = fkey_name.get(dbdriver)
    if fkey:
        op.drop_constraint(fkey, "tasks", type_="foreignkey")

    op.drop_table("samples")

    if dbdriver != "pysqlite":
        op.drop_column("tasks", "category")
        op.drop_column("tasks", "target")
        op.drop_column("tasks", "sample_id")
    else:
        # Drop table and create a new one for sqlite, since it cannot
        # handle deleting columns etc
        old_tasks = conn.execute(
            "SELECT %s FROM tasks" % ",".join(task_columns)
        ).fetchall()

        op.rename_table("tasks", "old_tasks")
        op.drop_table("old_tasks")

        op.create_table(
            "tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "type", sa.Enum(
                    "regular", "baseline", "service", "experiment",
                    name="task_type"
                ), server_default="regular", nullable=False
            ),
            sa.Column("timeout", sa.Integer(), server_default="0",
                      nullable=False),
            sa.Column("priority", sa.Integer(), server_default="1",
                      nullable=False),
            sa.Column("custom", sa.Text(), nullable=True),
            sa.Column("owner", sa.String(64), nullable=True),
            sa.Column("machine", sa.String(255), nullable=True),
            sa.Column("package", sa.String(255), nullable=True),
            sa.Column("options", sa.Text(), nullable=True),
            sa.Column("platform", sa.String(255), nullable=True),
            sa.Column("memory", sa.Boolean, nullable=False, default=False),
            sa.Column("enforce_timeout", sa.Boolean, nullable=False,
                      default=False),
            sa.Column(
                "clock", sa.DateTime(timezone=False),
                default=datetime.datetime.now,
                nullable=False
            ),
            sa.Column(
                "added_on", sa.DateTime(timezone=False),
                default=datetime.datetime.now,
                nullable=False
            ),
            sa.Column(
                "start_on", sa.DateTime(timezone=False),
                default=datetime.datetime.now,
                nullable=False
            ),
            sa.Column("started_on", sa.DateTime(timezone=False),
                      nullable=True),
            sa.Column("completed_on", sa.DateTime(timezone=False),
                      nullable=True),
            sa.Column(
                "status", sa.Enum(
                    "pending", "running", "completed", "reported", "recovered",
                    "failed_analysis", "failed_processing", "failed_reporting",
                    name="status_type"
                ), server_default="pending", nullable=False
            ),
            sa.Column("processing", sa.String(16), nullable=True),
            sa.Column("route", sa.String(16), nullable=True),
            sa.Column(
                "submit_id", sa.Integer(), sa.ForeignKey("submit.id"),
                nullable=True,
                index=True
            ),
            sa.Column(
                "experiment_id", sa.Integer(), sa.ForeignKey("experiments.id"),
                nullable=True
            )
        )

        # Reinsert all tasks in the new tasks table. Parse dates if they are
        # not a datetime obj, as Sqlite does not handle it otherwise
        new_tasks = []
        datefields = [
                "clock", "added_on", "start_on", "started_on", "completed_on"
        ]
        for old_task in old_tasks:
            new_task = dict(zip(task_columns, old_task))

            for datefield in datefields:
                datevalue = new_task.get(datefield)
                if not datevalue or isinstance(datevalue, datetime.datetime):
                    continue
                new_task[datefield] = dateutil.parser.parse(datevalue)

            new_tasks.append(new_task)

        op.bulk_insert(tasks_table, new_tasks)

def target_from_sample(target, category, sample=None, url=None):
    t = {}
    if sample:
        t = {
            "file_size": sample[1],
            "file_type": sample[2],
            "md5": sample[3],
            "crc32": sample[4],
            "sha1": sample[5],
            "sha256": sample[6],
            "sha512": sample[7],
            "ssdeep": sample[8],
            "category": "file",
            "target": target,
            "last_task": None
        }
    elif url and category == "url":
        t = {
            "file_size": None,
            "file_type": None,
            "md5": url.get_md5(),
            "crc32": url.get_crc32(),
            "sha1": url.get_sha1(),
            "sha256": url.get_sha256(),
            "sha512": url.get_sha512(),
            "ssdeep": url.get_ssdeep(),
            "category": "url",
            "target": target,
            "last_task": None
        }

    return t

def downgrade():
    pass

tasks_targets = sa.Table(
    "tasks_targets", Base.metadata,
    sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id")),
    sa.Column("target_id", sa.Integer(), sa.ForeignKey("targets.id"))
)

task_columns = (
    "id", "type", "timeout", "priority", "custom", "owner", "machine",
    "package", "options", "platform", "memory", "enforce_timeout", "clock",
    "added_on", "start_on", "started_on", "completed_on", "status",
    "processing", "route", "submit_id", "experiment_id"
)

tasks_table = sa.Table(
    "tasks", Base.metadata,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column(
        "type", sa.Enum(
            "regular", "baseline", "service", "experiment", name="task_type"
        ), server_default="regular", nullable=False
    ),
    sa.Column("timeout", sa.Integer(), server_default="0", nullable=False),
    sa.Column("priority", sa.Integer(), server_default="1", nullable=False),
    sa.Column("custom", sa.Text(), nullable=True),
    sa.Column("owner", sa.String(64), nullable=True),
    sa.Column("machine", sa.String(255), nullable=True),
    sa.Column("package", sa.String(255), nullable=True),
    sa.Column("options", sa.Text(), nullable=True),
    sa.Column("platform", sa.String(255), nullable=True),
    sa.Column("memory", sa.Boolean, nullable=False, default=False),
    sa.Column("enforce_timeout", sa.Boolean, nullable=False, default=False),
    sa.Column(
        "clock", sa.DateTime(timezone=False), default=datetime.datetime.now,
        nullable=False
    ),
    sa.Column(
        "added_on", sa.DateTime(timezone=False), default=datetime.datetime.now,
        nullable=False
    ),
    sa.Column(
        "start_on", sa.DateTime(timezone=False), default=datetime.datetime.now,
        nullable=False
    ),
    sa.Column("started_on", sa.DateTime(timezone=False), nullable=True),
    sa.Column("completed_on", sa.DateTime(timezone=False), nullable=True),
    sa.Column(
        "status", sa.Enum(
            "pending", "running", "completed", "reported", "recovered",
            "failed_analysis", "failed_processing", "failed_reporting",
            name="status_type"
        ), server_default="pending", nullable=False
    ),
    sa.Column("processing", sa.String(16), nullable=True),
    sa.Column("route", sa.String(16), nullable=True),
    sa.Column(
        "submit_id", sa.Integer(), sa.ForeignKey("submit.id"), nullable=True,
        index=True
    ),
    sa.Column(
        "experiment_id", sa.Integer(), sa.ForeignKey("experiments.id"),
        nullable=True
    )
)

class Target(Base):
    """Submitted target details"""
    __tablename__ = "targets"

    id = sa.Column(sa.Integer(), primary_key=True)
    file_size = sa.Column(sa.Integer(), nullable=True)
    file_type = sa.Column(sa.Text(), nullable=True)
    md5 = sa.Column(sa.String(32), nullable=False)
    crc32 = sa.Column(sa.String(8), nullable=False)
    sha1 = sa.Column(sa.String(40), nullable=False)
    sha256 = sa.Column(sa.String(64), nullable=False)
    sha512 = sa.Column(sa.String(128), nullable=False)
    ssdeep = sa.Column(sa.String(255), nullable=True)
    category = sa.Column(sa.String(255), nullable=False)
    target = sa.Column(sa.Text(), nullable=False)
    last_task = sa.Column(sa.Integer(), nullable=True)
