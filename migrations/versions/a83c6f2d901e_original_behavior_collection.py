"""Restore the original study and persist behavior coverage without changing old answers."""
from alembic import op
import sqlalchemy as sa

revision = "a83c6f2d901e"
down_revision = "7a1d9f4c2b10"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("participant_sessions") as batch:
        batch.add_column(sa.Column("client_context", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("source", sa.String(64), nullable=True))
        batch.create_index("ix_participant_sessions_source", ["source"], unique=False)
    with op.batch_alter_table("behavior_summaries") as batch:
        batch.add_column(sa.Column("metrics", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("expected_batches", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("expected_events", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("dropped_events", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("behavior_summaries") as batch:
        for column in ("dropped_events", "expected_events", "expected_batches", "metrics"):
            batch.drop_column(column)
    with op.batch_alter_table("participant_sessions") as batch:
        batch.drop_index("ix_participant_sessions_source")
        batch.drop_column("source")
        batch.drop_column("client_context")
