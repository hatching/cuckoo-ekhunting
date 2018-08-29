# Copyright (C) 2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

"""Removed guest table and added new machine and task fields

Revision ID: 15740ce250e6
Revises: 181be2111077
Create Date: 2017-11-10 19:15:45.968647

"""

# Revision identifiers, used by Alembic.
revision = "15740ce250e6"
down_revision = "cb1024e614b7"


from datetime import datetime
from alembic import op
import sqlalchemy as sa

def upgrade():
    currentdate = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    op.drop_table("guests")
    op.add_column(
        "machines", sa.Column(
            "manager", sa.String(length=255), nullable=True
        )
    )
    op.add_column(
        "tasks", sa.Column(
            "start_on", sa.DateTime(), server_default=currentdate,
            default=datetime.now, nullable=False
        )
    )

def downgrade():
    pass
