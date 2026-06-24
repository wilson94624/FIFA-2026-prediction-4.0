from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import RawSnapshotRecord

logger = logging.getLogger(__name__)


def canonical_payload(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_payload(payload).encode("utf-8")).hexdigest()


def append_snapshot(
    session: Session,
    *,
    source: str,
    snapshot_type: str,
    payload: Any,
    match_id: str | None = None,
    external_match_id: str | None = None,
    fetched_at: datetime | None = None,
    prediction_timestamp: datetime | None = None,
    model_version: str | None = None,
    notes: str | None = None,
) -> RawSnapshotRecord | None:
    digest = payload_hash(payload)
    existing = session.scalar(
        select(RawSnapshotRecord)
        .where(RawSnapshotRecord.source == source)
        .where(RawSnapshotRecord.snapshot_type == snapshot_type)
        .where(RawSnapshotRecord.match_id == match_id)
        .where(RawSnapshotRecord.payload_hash == digest)
    )
    if existing:
        return None

    record = RawSnapshotRecord(
        source=source,
        snapshot_type=snapshot_type,
        match_id=str(match_id) if match_id is not None else None,
        external_match_id=str(external_match_id) if external_match_id is not None else None,
        fetched_at=fetched_at or datetime.now(UTC),
        prediction_timestamp=prediction_timestamp,
        payload_json=payload,
        payload_hash=digest,
        model_version=model_version or settings.model_version,
        notes=notes,
    )
    session.add(record)
    return record


def safe_append_snapshot(session: Session, **kwargs: Any) -> RawSnapshotRecord | None:
    try:
        return append_snapshot(session, **kwargs)
    except Exception:
        logger.warning(
            "Snapshot archive write failed: source=%s type=%s match_id=%s",
            kwargs.get("source"),
            kwargs.get("snapshot_type"),
            kwargs.get("match_id"),
            exc_info=True,
        )
        return None


def snapshot_summary(session: Session) -> dict[str, Any]:
    records = session.scalars(select(RawSnapshotRecord)).all()
    by_source = Counter(record.source for record in records)
    by_type = Counter(record.snapshot_type for record in records)
    latest = max((record.fetched_at for record in records), default=None)
    injury_matches = {
        record.match_id
        for record in records
        if record.snapshot_type == "injury_unavailable_players" and record.match_id
    }
    return {
        "total_snapshots": len(records),
        "by_source": dict(sorted(by_source.items())),
        "by_snapshot_type": dict(sorted(by_type.items())),
        "latest_fetched_at": latest.isoformat() if latest else None,
        "matches_with_injury_snapshots": len(injury_matches),
    }
