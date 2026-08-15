"""phase 1 persistence integrity

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-19
"""

from __future__ import annotations

import json
import re

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_CREDENTIAL_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|(?:Bearer|Basic)\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "credentials",
    "literals",
    "password",
    "proxy_authorization",
    "secret",
    "token",
    "x_api_key",
}


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        ("_api_key", "_password", "_secret", "_token")
    )


def _is_env_reference(value: object, *, authorization: bool = False) -> bool:
    if isinstance(value, list):
        return bool(value) and all(
            _is_env_reference(item, authorization=authorization) for item in value
        )
    if not isinstance(value, str):
        return False
    if authorization:
        return bool(
            re.fullmatch(
                r"\s*(?:(?:Bearer|Basic)\s+)?\$\{[A-Za-z_][A-Za-z0-9_]*\}\s*",
                value,
                re.IGNORECASE,
            )
        )
    return bool(re.fullmatch(r"\s*\$\{[A-Za-z_][A-Za-z0-9_]*\}\s*", value))


def _check_sensitive_key(key_text: str, item: object, path: tuple[str, ...]) -> None:
    if key_text == "secret_ref":
        raise RuntimeError("secret_ref must be stored in targets.secret_ref")
    if _is_sensitive_key(key_text) and not _is_env_reference(
        item, authorization="authorization" in key_text.lower()
    ):
        location = ".".join((*path, key_text))
        raise RuntimeError(f"literal credential in existing target config at {location}")


def _assert_secret_safe_config(value: object, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            _check_sensitive_key(key_text, item, path)
            _assert_secret_safe_config(item, (*path, key_text))
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_secret_safe_config(item, (*path, str(index)))
        return
    if isinstance(value, str):
        if _CREDENTIAL_PATTERN.search(value):
            location = ".".join(path) or "<root>"
            raise RuntimeError(f"literal credential in existing target config at {location}")


def _validate_existing_target_configs() -> None:
    rows = op.get_bind().exec_driver_sql("SELECT id, org_id, config_json FROM targets")
    for target_id, org_id, config_json in rows:
        try:
            config = json.loads(config_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"cannot migrate 0004: target {org_id}/{target_id} has invalid config_json"
            ) from exc
        if not isinstance(config, dict) or config.get("id") != target_id:
            raise RuntimeError(
                f"cannot migrate 0004: target {org_id}/{target_id} does not match config id"
            )
        _assert_secret_safe_config(config)


def _validated_pack_test_rows() -> list[tuple[int, str, str, str, str]]:
    rows = op.get_bind().exec_driver_sql(
        "SELECT id, org_id, pack_id, test_json FROM pack_tests ORDER BY id"
    )
    validated: list[tuple[int, str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row_id, org_id, pack_id, test_json in rows:
        try:
            test_id = json.loads(test_json)["id"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError(
                f"cannot migrate 0004: pack_tests row {row_id} has invalid test_json"
            ) from exc
        if not isinstance(test_id, str) or not test_id:
            raise RuntimeError(
                f"cannot migrate 0004: pack_tests row {row_id} has no valid test id"
            )
        identity = (org_id, pack_id, test_id)
        if identity in seen:
            raise RuntimeError(
                f"cannot migrate 0004: duplicate test id {test_id!r} in pack {pack_id!r}"
            )
        seen.add(identity)
        validated.append((row_id, org_id, pack_id, test_id, test_json))
    return validated


def _rebuild_pack_tests_with_identity() -> None:
    rows = _validated_pack_test_rows()
    op.execute("DROP INDEX IF EXISTS idx_pack_tests_pack")
    op.execute("ALTER TABLE pack_tests RENAME TO pack_tests_legacy")
    op.execute(
        """
        CREATE TABLE pack_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id TEXT NOT NULL,
            pack_id TEXT NOT NULL,
            test_id TEXT NOT NULL,
            test_json TEXT NOT NULL,
            UNIQUE (org_id, pack_id, test_id),
            FOREIGN KEY (org_id, pack_id) REFERENCES packs(org_id, id) ON DELETE CASCADE
        )
        """
    )
    bind = op.get_bind()
    for row in rows:
        bind.exec_driver_sql(
            "INSERT INTO pack_tests (id, org_id, pack_id, test_id, test_json) "
            "VALUES (?, ?, ?, ?, ?)",
            row,
        )
    op.execute("DROP TABLE pack_tests_legacy")
    op.execute("CREATE INDEX idx_pack_tests_pack ON pack_tests(org_id, pack_id)")


def upgrade() -> None:
    if "secret_ref" not in _columns("targets"):
        op.execute("ALTER TABLE targets ADD COLUMN secret_ref TEXT")
    _validate_existing_target_configs()
    if "test_id" not in _columns("pack_tests"):
        _rebuild_pack_tests_with_identity()
    violations = op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            f"cannot migrate 0004: {len(violations)} foreign key violations remain"
        )


def _rebuild_pack_tests_without_identity() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pack_tests_pack")
    op.execute("ALTER TABLE pack_tests RENAME TO pack_tests_integrity")
    op.execute(
        """
        CREATE TABLE pack_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id TEXT NOT NULL,
            pack_id TEXT NOT NULL,
            test_json TEXT NOT NULL,
            FOREIGN KEY (org_id, pack_id) REFERENCES packs(org_id, id)
        )
        """
    )
    op.execute(
        "INSERT INTO pack_tests (id, org_id, pack_id, test_json) "
        "SELECT id, org_id, pack_id, test_json FROM pack_tests_integrity"
    )
    op.execute("DROP TABLE pack_tests_integrity")
    op.execute("CREATE INDEX idx_pack_tests_pack ON pack_tests(org_id, pack_id)")


def _rebuild_targets_without_secret_ref() -> None:
    op.execute("DROP INDEX IF EXISTS idx_targets_org")
    op.execute("ALTER TABLE targets RENAME TO targets_integrity")
    op.execute(
        """
        CREATE TABLE targets (
            id TEXT NOT NULL,
            org_id TEXT NOT NULL,
            name TEXT NOT NULL,
            config_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (org_id, id),
            FOREIGN KEY (org_id) REFERENCES orgs(id)
        )
        """
    )
    op.execute(
        "INSERT INTO targets (id, org_id, name, config_json, created_at) "
        "SELECT id, org_id, name, config_json, created_at FROM targets_integrity"
    )
    op.execute("DROP TABLE targets_integrity")
    op.execute("CREATE INDEX idx_targets_org ON targets(org_id)")


def downgrade() -> None:
    if "test_id" in _columns("pack_tests"):
        _rebuild_pack_tests_without_identity()
    if "secret_ref" in _columns("targets"):
        _rebuild_targets_without_secret_ref()
