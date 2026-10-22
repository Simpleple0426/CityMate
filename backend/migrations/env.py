from alembic import context
from citymate.config import Settings
from citymate.models import Base, database

engine, _ = database(Settings().database_url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
