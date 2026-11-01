"""Add persisted workflow execution runs."""
from alembic import op
import sqlalchemy as sa

revision = "0004_workflow_runs"
down_revision = "0003_org_invitations"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "workflow_runs" not in tables:
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="running"),
            sa.Column("input", sa.JSON(), nullable=False),
            sa.Column("step_results", sa.JSON(), nullable=False),
            sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("idempotency_key", sa.String(128), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("org_id", "idempotency_key", name="uq_workflow_run_idempotency"),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("workflow_runs")}
    for name, column in [
        ("ix_workflow_runs_org_id", "org_id"),
        ("ix_workflow_runs_workflow_id", "workflow_id"),
        ("ix_workflow_runs_status", "status"),
    ]:
        if name not in indexes:
            op.create_index(name, "workflow_runs", [column])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE workflow_runs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE workflow_runs FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY mosaic_workflow_run_tenant_isolation ON workflow_runs
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), ''))
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), ''))
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS mosaic_workflow_run_tenant_isolation ON workflow_runs")
        op.execute("ALTER TABLE workflow_runs DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_org_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
