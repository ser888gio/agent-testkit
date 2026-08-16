"""Alembic environment. Raw SQL migrations only — no ORM models, no target_metadata."""

from __future__ import annotations

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config


def run_migrations_offline() -> None:
    raise RuntimeError(
        "offline SQL generation is not supported: AgentAudit migrations inspect and "
        "rebuild existing SQLite tables"
    )


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "sqlite":
            # Table-rebuild migrations need to replace referenced parent tables. Store
            # connections re-enable enforcement before serving application queries.
            connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
            connection.commit()
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
