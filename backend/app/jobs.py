from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analytics import championship_explanations_are_current
from .db import SessionLocal
from .models import JobRecord, SnapshotRecord
from .services import run_simulation_pipeline, run_sync_pipeline, simulation_input_hash

executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="predictor-job")
submit_lock = Lock()
logger = logging.getLogger(__name__)


def serialize_job(job: JobRecord) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "message": job.message,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def update_job(job_id: str, progress: int, stage: str, message: str) -> None:
    with SessionLocal() as session:
        job = session.get(JobRecord, job_id)
        if not job:
            return
        job.status = "completed" if progress >= 100 else "running"
        job.progress = max(0, min(100, progress))
        job.stage = stage
        job.message = message
        job.updated_at = datetime.now(UTC)
        session.commit()


def _execute(job_id: str, job_type: str) -> None:
    try:
        update_job(job_id, 1, "started", "工作已開始")
        runner = run_sync_pipeline if job_type == "sync" else run_simulation_pipeline
        result = runner(
            lambda progress, stage, message: update_job(job_id, progress, stage, message)
        )
        with SessionLocal() as session:
            job = session.get(JobRecord, job_id)
            if job:
                job.status = "completed"
                job.progress = 100
                job.stage = "completed"
                job.message = json.dumps(result, ensure_ascii=False)
                job.updated_at = datetime.now(UTC)
                session.commit()
    except Exception as exc:  # background boundary: persist safe error state
        logger.exception("Background job failed: job_id=%s job_type=%s", job_id, job_type)
        with SessionLocal() as session:
            job = session.get(JobRecord, job_id)
            if job:
                failed_stage = job.stage or "unknown"
                error_context = {
                    "stage": failed_stage,
                    "match_id": getattr(exc, "match_id", None),
                    "source": getattr(exc, "source", failed_stage),
                    "error": str(exc),
                }
                job.status = "failed"
                job.stage = failed_stage
                job.message = f"工作執行失敗（{failed_stage}）"
                job.error = json.dumps(error_context, ensure_ascii=False)
                job.updated_at = datetime.now(UTC)
                session.commit()


def create_or_reuse_job(session: Session, job_type: str) -> tuple[dict[str, Any], bool]:
    with submit_lock:
        active = session.scalar(
            select(JobRecord)
            .where(JobRecord.job_type == job_type, JobRecord.status.in_(("queued", "running")))
            .order_by(JobRecord.created_at.desc())
        )
        if active:
            return serialize_job(active), True
        if job_type == "simulation":
            current_input_hash = simulation_input_hash(session)
            snapshot = session.scalar(
                select(SnapshotRecord).where(SnapshotRecord.key == "championship_odds")
            )
            snapshot_payload = dict(snapshot.payload or {}) if snapshot else {}
            explanations = snapshot_payload.get("explanations")
            explanations_are_current = championship_explanations_are_current(explanations)
            if (
                snapshot_payload.get("input_hash") == current_input_hash
                and explanations_are_current
            ):
                job = JobRecord(
                    id=str(uuid4()),
                    job_type="simulation",
                    status="completed",
                    progress=100,
                    stage="snapshot_reused",
                    message=json.dumps(
                        {
                            "input_hash": current_input_hash,
                            "snapshot_last_updated": snapshot_payload.get("last_updated"),
                            "snapshot_reused": True,
                        },
                        ensure_ascii=False,
                    ),
                )
                session.add(job)
                session.commit()
                session.refresh(job)
                return serialize_job(job), True
        job = JobRecord(
            id=str(uuid4()),
            job_type=job_type,
            status="queued",
            progress=0,
            stage="queued",
            message="已排入背景工作",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        try:
            executor.submit(_execute, job.id, job_type)
        except Exception as exc:
            logger.exception("Could not submit background job: job_id=%s", job.id)
            job.status = "failed"
            job.stage = "submit"
            job.message = "背景工作無法啟動"
            job.error = json.dumps(
                {
                    "stage": "submit",
                    "match_id": None,
                    "source": "background_worker",
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
            job.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(job)
        return serialize_job(job), False


def mark_interrupted_jobs() -> None:
    with SessionLocal() as session:
        jobs = session.scalars(
            select(JobRecord).where(JobRecord.status.in_(("queued", "running")))
        ).all()
        for job in jobs:
            job.status = "failed"
            job.stage = "interrupted"
            job.error = "Application restarted while this job was active"
            job.updated_at = datetime.now(UTC)
        session.commit()
