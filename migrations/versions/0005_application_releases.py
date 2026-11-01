"""Add immutable application release snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0005_application_releases"
down_revision = "0004_workflow_runs"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "application_releases" not in inspector.get_table_names():
        op.create_table(
            "application_releases",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("environment", sa.String(30), nullable=False, server_default="development"),
            sa.Column("status", sa.String(30), nullable=False, server_default="ready"),
            sa.Column("manifest", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("app_id", "version", "environment", name="uq_app_release_version_environment"),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("application_releases")}
    for name, column in [
        ("ix_application_releases_org_id", "org_id"),
        ("ix_application_releases_app_id", "app_id"),
    ]:
        if name not in indexes:
            op.create_index(name, "application_releases", [column])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE application_releases ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE application_releases FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY mosaic_application_release_tenant_isolation ON application_releases
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), ''))
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), ''))
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS mosaic_application_release_tenant_isolation ON application_releases")
        op.execute("ALTER TABLE application_releases DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_application_releases_app_id", table_name="application_releases")
    op.drop_index("ix_application_releases_org_id", table_name="application_releases")
    op.drop_table("application_releases")
