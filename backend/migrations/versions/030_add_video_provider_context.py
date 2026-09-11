"""Persist the protocol used by pending transition video tasks."""
from alembic import op
import sqlalchemy as sa

revision = '030'
down_revision = '029'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('movie_shot_transitions', sa.Column('provider_context_json', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('movie_shot_transitions', 'provider_context_json')
