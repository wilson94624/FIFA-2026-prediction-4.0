from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, get_db, init_db
from .jobs import create_or_reuse_job, mark_interrupted_jobs, serialize_job
from .models import JobRecord, MatchRecord
from .schemas import HealthResponse, JobResponse
from .services import (
    backtest_payload,
    championship_payload,
    latest_backtest,
    list_predictions,
    metrics_payload,
    prediction_for_match,
    raw_snapshot_summary_payload,
    review_for_match,
    seed_database,
    tournament_payload,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as session:
        seed_database(session)
        list_predictions(session)
        backtest_payload(session)
    mark_interrupted_jobs()
    yield


app = FastAPI(
    title="FIFA 2026 Predictor API",
    version=settings.model_version,
    description="Predictor 4.0 single-source model, market evidence and analytics API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.model_version)


@app.get("/api/predictions")
def predictions(include_finished: bool = Query(False), session: Session = Depends(get_db)) -> dict:
    return {
        "predictions": list_predictions(session, include_finished=include_finished),
        "version": settings.model_version,
    }


@app.get("/api/predictions/{match_id}")
def prediction(match_id: str, session: Session = Depends(get_db)) -> dict:
    match = session.scalar(select(MatchRecord).where(MatchRecord.match_id == match_id))
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    try:
        return prediction_for_match(session, dict(match.payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/tournament")
def tournament(session: Session = Depends(get_db)) -> dict:
    return tournament_payload(session)


@app.get("/api/championship-odds")
def championship_odds(session: Session = Depends(get_db)) -> dict:
    return championship_payload(session)


@app.post("/api/sync", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_sync(response: Response, session: Session = Depends(get_db)) -> JobResponse:
    payload, reused = create_or_reuse_job(session, "sync")
    if reused:
        response.headers["X-Job-Reused"] = "true"
    return JobResponse(**payload, reused=reused)


@app.post("/api/simulations", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_simulation(response: Response, session: Session = Depends(get_db)) -> JobResponse:
    payload, reused = create_or_reuse_job(session, "simulation")
    if reused:
        response.headers["X-Job-Reused"] = "true"
    return JobResponse(**payload, reused=reused)


@app.get("/api/sync-status", response_model=JobResponse)
def sync_status(job_id: str, session: Session = Depends(get_db)) -> JobResponse:
    job = session.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(**serialize_job(job), reused=False)


@app.get("/api/backtests/summary")
def backtest_summary(session: Session = Depends(get_db)) -> dict:
    return latest_backtest(session)


@app.get("/api/reviews/{match_id}")
def review(match_id: str, session: Session = Depends(get_db)) -> dict:
    payload = review_for_match(session, match_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Review not found")
    return payload


@app.get("/api/metrics")
def metrics(session: Session = Depends(get_db)) -> dict:
    return metrics_payload(session)


@app.get("/api/admin/snapshots/summary")
def snapshot_summary(session: Session = Depends(get_db)) -> dict:
    return raw_snapshot_summary_payload(session)
