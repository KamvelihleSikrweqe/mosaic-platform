"""Add single-use organisation invitations."""
from alembic import op
import sqlalchemy as sa

revision = "0003_org_invitations"
down_revision = "0002_org_membership_rls"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "organisation_invitations" not in tables:
        op.create_table(
            "organisation_invitations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("role", sa.String(30), nullable=False, server_default="member"),
            sa.Column("invited_by", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("organisation_invitations")}
    if "ix_organisation_invitations_org_id" not in indexes:
        op.create_index("ix_organisation_invitations_org_id", "organisation_invitations", ["org_id"])
    if "ix_organisation_invitations_email" not in indexes:
        op.create_index("ix_organisation_invitations_email", "organisation_invitations", ["email"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE organisation_invitations ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organisation_invitations FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY mosaic_invitation_tenant_isolation ON organisation_invitations
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), ''))
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), ''))
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS mosaic_invitation_tenant_isolation ON organisation_invitations")
        op.execute("ALTER TABLE organisation_invitations DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_organisation_invitations_email", table_name="organisation_invitations")
    op.drop_index("ix_organisation_invitations_org_id", table_name="organisation_invitations")
    op.drop_table("organisation_invitations")
