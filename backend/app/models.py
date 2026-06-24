from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class SourceFields:
    source: Mapped[str] = mapped_column(String(80), default="local_seed")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[str] = mapped_column(String(40), default="4.0.0")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class MatchRecord(SourceFields, Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class PredictionRecord(SourceFields, Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    input_version: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class MarketOddsRecord(SourceFields, Base):
    __tablename__ = "market_odds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True, default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(80), default="queued")
    message: Mapped[str] = mapped_column(Text, default="等待執行")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(String(80), index=True)
    model_version: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MatchReview(SourceFields, Base):
    __tablename__ = "match_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    failure_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)


class MetricRecord(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[float] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SnapshotRecord(SourceFields, Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class RawSnapshotRecord(Base):
    __tablename__ = "raw_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(80), index=True)
    match_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    external_match_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    prediction_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    payload_json: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(40), default="4.0.0", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
