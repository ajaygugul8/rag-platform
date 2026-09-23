"""
Alembic environment. Two things make this project-specific rather than
boilerplate:

1. sqlalchemy.url comes from app.config.settings (DATABASE_URL in .env),
   not from alembic.ini - so there's still exactly one place the database
   connection string lives, matching this project's existing config
   discipline (see app/config.py's docstring).
2. target_metadata is this project's actual Base.metadata (app/db/base.py
   + app/db/models.py), which is what makes `alembic revision
   --autogenerate` able to diff "what the models say" against "what the
   live database has" and generate real migration scripts instead of
   empty ones.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make app.* importable - alembic.ini's prepend_sys_path=. handles this
# when run from backend/, but being explicit here avoids surprises if
# alembic is ever invoked from a different working directory.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402,F401 - import registers all models on Base.metadata

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL scripts without a live DB connection (rarely used
    here, but standard Alembic capability - kept for completeness)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """The normal path: connect to the real database and apply/compare
    migrations against it."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()