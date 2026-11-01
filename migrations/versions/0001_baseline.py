"""MOSAIC baseline schema.

This bootstrap is intentionally idempotent so an existing preview database
created by SQLAlchemy create_all can be adopted without dropping its tables.
All subsequent schema changes must be explicit Alembic operations.
"""
from alembic import op
from mosaic.db import Base
import mosaic.models  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
