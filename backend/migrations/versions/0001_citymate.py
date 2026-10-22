"""Initial CityMate schema, separate from legacy education tables."""

from alembic import op
from citymate.models import Base

revision = "0001_citymate"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    Base.metadata.drop_all(op.get_bind())
