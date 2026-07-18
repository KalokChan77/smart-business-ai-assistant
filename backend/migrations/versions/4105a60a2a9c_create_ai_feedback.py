"""create ai feedback

Revision ID: 4105a60a2a9c
Revises: db5ec0516aa8
Create Date: 2026-07-17 07:06:44.997986

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "4105a60a2a9c"
down_revision: str | Sequence[str] | None = "db5ec0516aa8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_ai_runs_id_response_message_id",
        "ai_runs",
        ["id", "response_message_id"],
    )
    op.create_table(
        "ai_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column(
            "rating",
            sa.Enum(
                "positive",
                "negative",
                name="ai_feedback_rating",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 1000",
            name=op.f("ck_ai_feedback_ai_feedback_comment_length"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_ai_feedback_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "message_id"],
            ["ai_runs.id", "ai_runs.response_message_id"],
            name="fk_ai_feedback_run_response_message_ai_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_feedback")),
        sa.UniqueConstraint("run_id", name="uq_ai_feedback_run_id"),
    )
    op.create_index(
        op.f("ix_ai_feedback_message_id"),
        "ai_feedback",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_feedback_created_rating",
        "ai_feedback",
        ["created_at", "rating"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_ai_feedback_created_rating",
        table_name="ai_feedback",
    )
    op.drop_index(op.f("ix_ai_feedback_message_id"), table_name="ai_feedback")
    op.drop_table("ai_feedback")
    op.drop_constraint(
        "uq_ai_runs_id_response_message_id",
        "ai_runs",
        type_="unique",
    )
