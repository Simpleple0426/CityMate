"""Ensure Chinese text support even when the database default is latin1."""

from alembic import op

revision = "0002_mysql_unicode"
down_revision = "0001_citymate"
branch_labels = None
depends_on = None
TABLES = (
    "cm_users",
    "cm_shops",
    "cm_vouchers",
    "cm_orders",
    "cm_notes",
    "cm_likes",
    "cm_follows",
    "cm_checkins",
    "cm_appointments",
    "cm_slots",
    "cm_outbox",
)


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "mysql":
        return
    previous = connection.exec_driver_sql("SELECT @@FOREIGN_KEY_CHECKS").scalar()
    connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
    try:
        for table in TABLES:
            connection.exec_driver_sql(
                f"ALTER TABLE {table} CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        connection.exec_driver_sql(f"SET FOREIGN_KEY_CHECKS={int(previous)}")


def downgrade():
    # Reverting to latin1 could destroy user text; leave the compatible charset in place.
    pass
