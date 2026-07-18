"""create customer service

Revision ID: 2b67c8e7c1ea
Revises: 4105a60a2a9c
Create Date: 2026-07-17 08:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "2b67c8e7c1ea"
down_revision: str | Sequence[str] | None = "4105a60a2a9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_users_id_tenant_id",
        "users",
        ["id", "tenant_id"],
    )
    op.create_table(
        "customer_tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("requester_user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_user_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "in_progress",
                "resolved",
                "closed",
                name="customer_ticket_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum(
                "refund_after_sales",
                "account_security",
                "product_service",
                "knowledge_document",
                "technical_support",
                "other",
                name="customer_ticket_category",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=True,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "low",
                "normal",
                "high",
                "urgent",
                name="customer_ticket_priority",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="normal",
            nullable=False,
        ),
        sa.Column("classification_confidence", sa.Integer(), nullable=True),
        sa.Column("classification_reason", sa.String(length=500), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "classification_confidence IS NULL OR "
            "classification_confidence BETWEEN 0 AND 100",
            name=op.f(
                "ck_customer_tickets_customer_ticket_classification_confidence_range"
            ),
        ),
        sa.CheckConstraint(
            "char_length(description) BETWEEN 1 AND 10000",
            name=op.f("ck_customer_tickets_customer_ticket_description_length"),
        ),
        sa.CheckConstraint(
            "char_length(subject) BETWEEN 1 AND 200",
            name=op.f("ck_customer_tickets_customer_ticket_subject_length"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_customer_tickets_assigned_tenant_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_customer_tickets_requester_tenant_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_tickets")),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_customer_tickets_id_tenant_id",
        ),
    )
    op.create_index(
        op.f("ix_customer_tickets_assigned_user_id"),
        "customer_tickets",
        ["assigned_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_tickets_requester_user_id"),
        "customer_tickets",
        ["requester_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_tickets_tenant_id"),
        "customer_tickets",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_tickets_requester_created",
        "customer_tickets",
        ["requester_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_customer_tickets_tenant_category_created",
        "customer_tickets",
        ["tenant_id", "category", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_customer_tickets_tenant_status_created",
        "customer_tickets",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "reply_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "refund_after_sales",
                "account_security",
                "product_service",
                "knowledge_document",
                "technical_support",
                "other",
                name="reply_suggestion_category",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "confirmed",
                name="reply_suggestion_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("suggested_reply", sa.Text(), nullable=False),
        sa.Column("final_reply", sa.Text(), nullable=True),
        sa.Column(
            "knowledge_outcome",
            sa.Enum(
                "answered",
                "no_match",
                "refused",
                name="customer_service_knowledge_outcome",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column(
            "quality_status",
            sa.Enum(
                "passed",
                "needs_review",
                name="reply_quality_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("quality_notes", sa.JSON(), nullable=False),
        sa.Column(
            "workflow_version",
            sa.String(length=64),
            server_default="customer-service-v1",
            nullable=False,
        ),
        sa.Column("generated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            "(status = 'draft' AND final_reply IS NULL "
            "AND confirmed_by_user_id IS NULL AND confirmed_at IS NULL) "
            "OR (status = 'confirmed' AND final_reply IS NOT NULL "
            "AND confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name=op.f(
                "ck_reply_suggestions_reply_suggestion_confirmation_consistency"
            ),
        ),
        sa.CheckConstraint(
            "final_reply IS NULL OR char_length(final_reply) BETWEEN 1 AND 5000",
            name=op.f("ck_reply_suggestions_reply_suggestion_final_reply_length"),
        ),
        sa.CheckConstraint(
            "char_length(suggested_reply) BETWEEN 1 AND 5000",
            name=op.f("ck_reply_suggestions_reply_suggestion_suggested_reply_length"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_reply_suggestions_confirmed_tenant_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generated_by_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_reply_suggestions_generated_tenant_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id", "tenant_id"],
            ["customer_tickets.id", "customer_tickets.tenant_id"],
            name="fk_reply_suggestions_ticket_tenant_customer_tickets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reply_suggestions")),
        sa.UniqueConstraint("ticket_id", name="uq_reply_suggestions_ticket_id"),
    )
    op.create_index(
        op.f("ix_reply_suggestions_confirmed_by_user_id"),
        "reply_suggestions",
        ["confirmed_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reply_suggestions_generated_by_user_id"),
        "reply_suggestions",
        ["generated_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reply_suggestions_tenant_id"),
        "reply_suggestions",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_reply_suggestions_tenant_status_updated",
        "reply_suggestions",
        ["tenant_id", "status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_reply_suggestions_tenant_status_updated",
        table_name="reply_suggestions",
    )
    op.drop_index(
        op.f("ix_reply_suggestions_tenant_id"),
        table_name="reply_suggestions",
    )
    op.drop_index(
        op.f("ix_reply_suggestions_generated_by_user_id"),
        table_name="reply_suggestions",
    )
    op.drop_index(
        op.f("ix_reply_suggestions_confirmed_by_user_id"),
        table_name="reply_suggestions",
    )
    op.drop_table("reply_suggestions")

    op.drop_index(
        "ix_customer_tickets_tenant_status_created",
        table_name="customer_tickets",
    )
    op.drop_index(
        "ix_customer_tickets_tenant_category_created",
        table_name="customer_tickets",
    )
    op.drop_index(
        "ix_customer_tickets_requester_created",
        table_name="customer_tickets",
    )
    op.drop_index(
        op.f("ix_customer_tickets_tenant_id"),
        table_name="customer_tickets",
    )
    op.drop_index(
        op.f("ix_customer_tickets_requester_user_id"),
        table_name="customer_tickets",
    )
    op.drop_index(
        op.f("ix_customer_tickets_assigned_user_id"),
        table_name="customer_tickets",
    )
    op.drop_table("customer_tickets")
    op.drop_constraint(
        "uq_users_id_tenant_id",
        "users",
        type_="unique",
    )
