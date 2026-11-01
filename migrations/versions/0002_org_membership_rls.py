"""Add organisation membership and PostgreSQL tenant row security."""
from alembic import op
import sqlalchemy as sa

revision = "0002_org_membership_rls"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    if "organisation_memberships" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "organisation_memberships",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("issuer", sa.String(length=500), nullable=False),
            sa.Column("subject", sa.String(length=500), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("role", sa.String(length=30), nullable=False, server_default="member"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
        )
    existing_indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("organisation_memberships")}
    if "ix_membership_user_id" not in existing_indexes:
        op.create_index("ix_membership_user_id", "organisation_memberships", ["user_id"])
    if "ix_membership_org_id" not in existing_indexes:
        op.create_index("ix_membership_org_id", "organisation_memberships", ["org_id"])

    if op.get_bind().dialect.name != "postgresql":
        return

    tenant_tables = [
        "data_objects", "data_records", "applications", "workflows", "audit_events"
    ]
    for table in tenant_tables:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY mosaic_tenant_isolation ON "{table}"
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '') )
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '') )'''
        )

    op.execute("ALTER TABLE organisations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organisations FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY mosaic_organisation_access ON organisations
        USING (
          id = NULLIF(current_setting('app.current_org_id', true), '')
          OR EXISTS (
            SELECT 1 FROM organisation_memberships m
            WHERE m.org_id = organisations.id
              AND m.user_id = NULLIF(current_setting('app.current_user_id', true), '')
          )
        )
        WITH CHECK (id = NULLIF(current_setting('app.current_org_id', true), ''))
    """)

    op.execute("ALTER TABLE organisation_memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organisation_memberships FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY mosaic_membership_access ON organisation_memberships
        USING (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')
          OR org_id = NULLIF(current_setting('app.current_org_id', true), '')
        )
        WITH CHECK (
          user_id = NULLIF(current_setting('app.current_user_id', true), '')
          OR org_id = NULLIF(current_setting('app.current_org_id', true), '')
        )
    """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for table in ["data_objects", "data_records", "applications", "workflows", "audit_events"]:
            op.execute(f'DROP POLICY IF EXISTS mosaic_tenant_isolation ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
        op.execute("DROP POLICY IF EXISTS mosaic_organisation_access ON organisations")
        op.execute("ALTER TABLE organisations DISABLE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS mosaic_membership_access ON organisation_memberships")
        op.execute("ALTER TABLE organisation_memberships DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_membership_org_id", table_name="organisation_memberships")
    op.drop_index("ix_membership_user_id", table_name="organisation_memberships")
    op.drop_table("organisation_memberships")
