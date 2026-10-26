"""Add fixed application terms and independent randomized responses.

Revision ID: b6d208a134f0
Revises: a83c6f2d901e
"""
from alembic import op
import sqlalchemy as sa

revision = "b6d208a134f0"
down_revision = "a83c6f2d901e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("participant_sessions", sa.Column("terms_snapshot", sa.JSON(), nullable=True))
    op.create_table("rrt_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("participant_id", sa.Integer(), sa.ForeignKey("participant_sessions.id"), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("protocol_version", sa.String(32), nullable=False),
        sa.Column("redeemed", sa.Boolean(), nullable=False))
    op.create_table("rrt_responses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("protocol_version", sa.String(32), nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("batch_day", sa.Date(), nullable=False),
        sa.Column("choice", sa.String(8), nullable=False),
        sa.CheckConstraint("choice IN ('yes', 'no', 'skipped')", name="ck_rrt_choice"))
    op.create_index("ix_rrt_responses_protocol_version", "rrt_responses", ["protocol_version"])
    op.create_index("ix_rrt_responses_is_test", "rrt_responses", ["is_test"])


def downgrade():
    op.drop_table("rrt_responses")
    op.drop_table("rrt_invitations")
    with op.batch_alter_table("participant_sessions") as batch:
        batch.drop_column("terms_snapshot")
