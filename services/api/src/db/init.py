"""Database + schema bootstrapping.

Runs the DuckDB DDL migration against the active connection (local or MotherDuck).
The DDL file itself creates all required schemas (platform, catalogue, transforms,
integrations, permissions, audit, bronze, silver, gold).
"""

import hashlib
import pathlib
from datetime import UTC, datetime

import structlog

from src.db.connection import get_conn

logger = structlog.get_logger(__name__)

_DDL_FILENAME = "001_core_duckdb.sql"
_MIGRATIONS = [
    "002_rename_integrations.sql",
    "003_cron_audit.sql",
    "004_auth.sql",
    "005_tenant.sql",
    "006_invite.sql",
    "007_trigger_mode.sql",
    "008_agent_memory.sql",
    "009_unique_entity_name.sql",
    "010_collections.sql",
    "011_migration_tracking.sql",
]


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _is_migration_applied(conn: object, filename: str) -> bool:
    """Return True if this migration is already recorded in schema_migration."""
    try:
        row = conn.execute(  # type: ignore[attr-defined]
            "SELECT 1 FROM platform.schema_migration WHERE filename = ?", [filename]
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _record_migration(conn: object, filename: str, checksum: str) -> None:
    try:
        conn.execute(  # type: ignore[attr-defined]
            "INSERT OR IGNORE INTO platform.schema_migration (filename, checksum) VALUES (?, ?)",
            [filename, checksum],
        )
    except Exception as exc:
        logger.warning("migration_record_failed", filename=filename, error=str(exc))

_ORDERS_JSON_TRANSFORM_SQL = """CREATE OR REPLACE TABLE silver.orders_cleaned AS
WITH parsed AS (
    SELECT
        json_extract_string(payload, '$.order_id') AS order_id,
        json_extract_string(payload, '$.customer_id') AS customer_id,
        json_extract_string(payload, '$.status') AS status,
        TRY_CAST(json_extract_string(payload, '$.created_at') AS TIMESTAMP) AS created_at,
        COALESCE(NULLIF(json_extract_string(payload, '$.shipping_country'), ''), 'UNKNOWN')
            AS shipping_country,
        TRY_CAST(json_extract(payload, '$.total') AS DOUBLE) AS total_usd
    FROM bronze.orders
)
SELECT
    order_id,
    customer_id,
    status,
    created_at,
    shipping_country,
    total_usd
FROM parsed
WHERE order_id IS NOT NULL AND total_usd IS NOT NULL"""


def _find_ddl() -> pathlib.Path:
    """Search upward from this file for db/001_core_duckdb.sql.

    Works in both layouts:
      Docker:   /app/src/db/init.py  → /app/db/
      Local dev: services/api/src/db/init.py → jonas-data-platform/db/
    """
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "db" / _DDL_FILENAME
        if candidate.exists():
            return candidate
    # Explicit fallback for Docker image layout
    return pathlib.Path("/app/db") / _DDL_FILENAME


def _migrate_legacy_orders_transform_sql() -> None:
    """Update older demo transform SQL that assumes flat bronze.orders columns.

    Older seed data stored raw JSON in bronze.orders(payload), but the transform
    used `order_id`/`total` columns directly. This migration rewrites only the
    legacy SQL signature to a payload-extraction variant.
    """
    conn = get_conn()
    now = datetime.now(UTC).isoformat()
    try:
        conn.execute(
            """
            UPDATE transforms.transform
            SET transform_sql = ?, updated_at = ?
            WHERE name = 'orders_bronze_to_silver'
              AND lower(transform_sql) LIKE ?
              AND lower(transform_sql) LIKE ?
              AND lower(transform_sql) NOT LIKE ?
            """,
            [
                _ORDERS_JSON_TRANSFORM_SQL,
                now,
                "%from bronze.orders%",
                "%where order_id is not null and total is not null%",
                "%json_extract%",
            ],
        )
    except Exception as exc:
        logger.debug("legacy_transform_migration_skipped", error=repr(exc))


def bootstrap() -> None:
    """Idempotently run DDL migrations against the active connection."""
    conn = get_conn()
    DDL_PATH = _find_ddl()

    if not DDL_PATH.exists():
        logger.warning("ddl_not_found", path=str(DDL_PATH))
        return

    ddl = DDL_PATH.read_text()
    # DuckDB executemany doesn't handle multi-statement strings well;
    # split on semicolons and execute each statement individually.
    statements = [s.strip() for s in ddl.split(";") if s.strip()]
    for stmt in statements:
        try:
            conn.execute(stmt)
        except Exception as exc:
            logger.debug("ddl_stmt_warning", error=repr(exc), stmt_preview=stmt[:60])

    _migrate_legacy_orders_transform_sql()

    # Run sequential migrations
    applied = 0
    skipped = 0
    for migration_filename in _MIGRATIONS:
        migration_path = DDL_PATH.parent / migration_filename
        if not migration_path.exists():
            logger.warning("migration_not_found", filename=migration_filename)
            continue
        migration_sql = migration_path.read_text()
        checksum = _sha256(migration_sql)

        if _is_migration_applied(conn, migration_filename):
            skipped += 1
            continue

        mig_statements = []
        for s in migration_sql.split(";"):
            # Strip leading comment lines, then check if any SQL remains
            lines = [ln for ln in s.splitlines() if not ln.strip().startswith("--")]
            sql = "\n".join(lines).strip()
            if sql:
                mig_statements.append(sql)
        ok = True
        for stmt in mig_statements:
            try:
                conn.execute(stmt)
            except Exception as exc:
                logger.warning(
                    "migration_stmt_warning",
                    filename=migration_filename,
                    error=repr(exc),
                    stmt_preview=stmt[:60],
                )
                ok = False
        if ok:
            _record_migration(conn, migration_filename, checksum)
            applied += 1

    seed_admin_password()

    # Provision tenant-scoped data lake schemas for all existing tenants
    try:
        from src.db.tenant_schemas import get_all_tenant_ids, provision_tenant_schemas

        for tid in get_all_tenant_ids(conn):
            provision_tenant_schemas(tid)
    except Exception as exc:
        logger.warning("schema_provisioning_warning", error=repr(exc))

    # Decay + prune agent memories for all tenants
    try:
        from src.agent.memory import decay_memories, prune_memories

        conn2 = get_conn()
        tenant_rows = conn2.execute("SELECT id FROM platform.tenant").fetchall()
        for (tid,) in tenant_rows:
            decay_memories(str(tid))
            prune_memories(str(tid))
    except Exception as exc:
        logger.warning("memory_decay_warning", error=repr(exc))

    logger.info(
        "bootstrap_complete",
        ddl_statements=len(statements),
        migrations_applied=applied,
        migrations_skipped=skipped,
    )


def seed_admin_password() -> None:
    """Set password hashes for all demo users if not yet set.

    Uses ADMIN_PASSWORD env var (default 'admin123' for dev).
    Runs on every bootstrap but is a no-op when already set.
    """
    import os

    from src.auth.jwt import hash_password

    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    conn = get_conn()
    try:
        demo_users = ["user-admin", "user-analyst", "user-viewer"]
        h = hash_password(password)
        for user_id in demo_users:
            row = conn.execute(
                "SELECT password_hash FROM platform.user_account WHERE id = ?",
                [user_id],
            ).fetchone()
            if row and not row[0]:
                conn.execute(
                    "UPDATE platform.user_account SET password_hash = ? WHERE id = ?",
                    [h, user_id],
                )
        logger.info("demo_passwords_seeded")
    except Exception as exc:
        logger.warning("seed_passwords_failed", error=repr(exc))
