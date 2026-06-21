"""Bring legacy anonymous deployments to the emotion-social MVP schema."""

from alembic import op
import sqlalchemy as sa

from app.database import Base
from app import models  # noqa: F401

revision = "0001_emotion_social_mvp"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    additions = {
        "anonymous_users": [("account_id", sa.String(36))],
        "match_tickets": [("mode", sa.String(24), "'similar'")],
        "participants": [("joined_at", sa.DateTime()), ("hidden_at", sa.DateTime())],
    }
    for table, columns in additions.items():
        if table not in tables:
            continue
        existing = {item["name"] for item in inspector.get_columns(table)}
        for spec in columns:
            name, column_type, *default = spec
            if name not in existing:
                op.add_column(table, sa.Column(name, column_type, server_default=default[0] if default else None, nullable=True))
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Account/history data is intentionally preserved on rollback.
    pass
