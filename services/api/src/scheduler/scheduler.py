"""APScheduler cron integration — runs api_pull connectors on schedule.

Loads all active api_pull connectors with a cron_schedule from the DB on startup
and reschedules when connectors are updated. Jobs are re-loaded from DB on every
app restart (no persistent job store needed for the demo).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


def start(app: Any) -> None:  # noqa: ARG001
    """Load active cron connectors and start the scheduler. Called from lifespan."""
    _reload_jobs()
    scheduler.start()
    logger.info("[scheduler] started")


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[scheduler] stopped")


def reload_connector(
    connector_id: str, cron_schedule: str | None, tenant_id: str
) -> None:
    """Add or remove a single connector job after a PATCH update."""
    job_id = f"connector_{connector_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if cron_schedule:
        try:
            trigger = CronTrigger.from_crontab(cron_schedule, timezone="UTC")
            scheduler.add_job(
                _run_connector_pull,
                trigger,
                id=job_id,
                kwargs={"connector_id": connector_id, "tenant_id": tenant_id},
                replace_existing=True,
            )
            logger.info(
                "[scheduler] scheduled connector %s @ %s", connector_id, cron_schedule
            )
        except Exception as exc:
            logger.warning("[scheduler] invalid cron for %s: %r", connector_id, exc)


def _reload_jobs() -> None:
    """Read all api_pull connectors with a cron_schedule and register jobs."""
    try:
        from src.db.connection import get_conn

        conn = get_conn()
        rows = conn.execute(
            """
            SELECT id, tenant_id, cron_schedule
            FROM integrations.connector
            WHERE connector_type = 'api_pull'
              AND status = 'active'
              AND cron_schedule IS NOT NULL
            """
        ).fetchall()
        for connector_id, tenant_id, cron_schedule in rows:
            reload_connector(str(connector_id), str(cron_schedule), str(tenant_id))
        logger.info("[scheduler] loaded %d cron connector(s)", len(rows))
    except Exception as exc:
        logger.warning("[scheduler] could not load cron connectors: %r", exc)


def _run_connector_pull(connector_id: str, tenant_id: str) -> None:
    """Execute an api_pull for a connector and record the run."""
    try:
        from src.db.connection import get_conn
        from src.integrations import ingest, service

        integration = service.get_integration(connector_id, tenant_id)
        if not integration:
            logger.warning(
                "[scheduler] connector %s not found — skipping", connector_id
            )
            return

        raw_config = integration.get("config") or {}
        config: dict[str, Any] = (
            json.loads(raw_config) if isinstance(raw_config, str) else raw_config
        )
        url: str = config.get("url", "").strip()
        if not url:
            logger.warning(
                "[scheduler] connector %s has no url — skipping", connector_id
            )
            return

        headers: dict[str, str] = config.get("headers", {})
        entity_id = integration.get("target_entity_id")
        if entity_id:
            from src.catalogue.service import get_entity

            entity = get_entity(str(entity_id), tenant_id)
            source = str(entity["name"]) if entity else str(integration["name"])
        else:
            source = str(integration["name"])

        result = ingest.land_api_pull(url, headers, source, tenant_id, connector_id)
        logger.info(
            "[scheduler] connector %s pull done — %d/%d rows",
            connector_id,
            result.get("rows_landed", 0),
            result.get("rows_received", 0),
        )
        from src.audit.log import write_audit

        write_audit(
            tenant_id=tenant_id,
            user_id="scheduler",
            action="scheduled_trigger",
            resource_type="connector",
            resource_id=connector_id,
            detail={"rows_landed": result.get("rows_landed"), "source": source},
        )
    except Exception as exc:
        logger.error("[scheduler] connector %s pull failed: %r", connector_id, exc)

    # Ensure the connection stays alive after the background job
    try:
        get_conn()
    except Exception:
        pass
