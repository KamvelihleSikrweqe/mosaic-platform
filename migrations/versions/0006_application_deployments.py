"""Add tenant-scoped application deployment intent records."""
from alembic import op
import sqlalchemy as sa

revision = "0006_application_deployments"
down_revision = "0005_application_releases"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "application_deployments" not in inspector.get_table_names():
        op.create_table(
            "application_deployments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
            sa.Column("release_id", sa.String(36), sa.ForeignKey("application_releases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("environment", sa.String(30), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("target", sa.String(120), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="planned"),
            sa.Column("health_status", sa.String(30), nullable=False, server_default="unknown"),
            sa.Column("artifact_digest", sa.String(80), nullable=False),
            sa.Column("deployment_url", sa.String(2048), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("application_deployments")}
    for name, column in [
        ("ix_application_deployments_org_id", "org_id"),
        ("ix_application_deployments_app_id", "app_id"),
        ("ix_application_deployments_release_id", "release_id"),
    ]:
        if name not in indexes:
            op.create_index(name, "application_deployments", [column])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE application_deployments ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE application_deployments FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY mosaic_application_deployment_tenant_isolation ON application_deployments
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), ''))
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), ''))
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS mosaic_application_deployment_tenant_isolation ON application_deployments")
        op.execute("ALTER TABLE application_deployments DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_application_deployments_release_id", table_name="application_deployments")
    op.drop_index("ix_application_deployments_app_id", table_name="application_deployments")
    op.drop_index("ix_application_deployments_org_id", table_name="application_deployments")
    op.drop_table("application_deployments")
