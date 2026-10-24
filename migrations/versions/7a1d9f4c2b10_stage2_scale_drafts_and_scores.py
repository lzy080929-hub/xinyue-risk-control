"""stage two scale drafts and submission scoring snapshot

Revision ID: 7a1d9f4c2b10
Revises: f864ba4e0a76
Create Date: 2026-10-22 22:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7a1d9f4c2b10"
down_revision = "f864ba4e0a76"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("form_drafts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("scale_payload", sa.JSON(), nullable=True))

    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("scale_version", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("scoring_version", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(sa.Column("scale_scores", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.drop_column("scale_scores")
        batch_op.drop_column("scoring_version")
        batch_op.drop_column("scale_version")

    with op.batch_alter_table("form_drafts", schema=None) as batch_op:
        batch_op.drop_column("scale_payload")
