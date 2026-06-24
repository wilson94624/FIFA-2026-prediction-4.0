from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .analytics import (
    CHAMPIONSHIP_EXPLANATIONS_VERSION,
    calculate_backtest,
    championship_explanations,
    deterministic_review,
    validate_championship_explanations,
)
from .archive import safe_append_snapshot, snapshot_summary
from .bracket import resolve_tournament_matches
from .config import FRONTEND_DATA_DIR, settings
from .db import SessionLocal
from .engine import (
    GAMMA,
    MAX_GOALS,
    RHO,
    active_pqs,
    dynamic_elos_before,
    fatigue_before,
    parse_match_date,
    predict_match,
)
from .fotmob import PRIMARY_STATS, fetch_match_stats, has_complete_primary_stats, with_fotmob_status
from .market import fetch_market_evidence
from .models import (
    BacktestRun,
    MarketOddsRecord,
    MatchRecord,
    MatchReview,
    MetricRecord,
    PredictionRecord,
    SnapshotRecord,
)

TEAMS_PATH = FRONTEND_DATA_DIR / "teams_db.json"
MATCHES_PATH = FRONTEND_DATA_DIR / "real_games_results.json"
ANALYSES_PATH = FRONTEND_DATA_DIR / "match_analyses.json"
CHAMPIONSHIP_PATH = FRONTEND_DATA_DIR / "simulation_probabilities.json"
ARCHIVE_DIR = FRONTEND_DATA_DIR.parents[1] / "backend" / "archive"
CHAMPIONSHIP_SIMULATION_RUNS = 10_000
_cache = {"hits": 0, "misses": 0}
logger = logging.getLogger(__name__)
TOURNAMENT_TIMEZONE = timezone(timedelta(hours=-4))
MATCH_TIMING_FIELDS = ("kickoff_utc", "kickoff_source", "kickoff_status")
RETRYABLE_ERRORS = (
    ConnectionResetError,
    TimeoutError,
    httpx.ReadError,
    httpx.ConnectError,
    httpx.TimeoutException,
)
SIMULATION_MATCH_FIELDS = (
    "id",
    "match_id",
    "type",
    "stage",
    "group",
    "local_date",
    "kickoff",
    "kickoff_time",
    "date",
    "home_team_name_en",
    "away_team_name_en",
    "home_team_label",
    "away_team_label",
    "finished",
    "home_score",
    "away_score",
    "home_scorers",
    "away_scorers",
)


def _get_with_retry(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    for attempt in range(3):
        try:
            return client.get(url, **kwargs)
        except RETRYABLE_ERRORS:
            if attempt == 2:
                raise
            logger.warning("World Cup API request failed; retrying (%s/3)", attempt + 1)
            time.sleep(0.25 * (2**attempt))
    raise RuntimeError("unreachable")


def _archive_callback(session: Session) -> Callable[..., None]:
    def archive(**kwargs: Any) -> None:
        safe_append_snapshot(session, model_version=settings.model_version, **kwargs)

    return archive


def _fetch_match_stats_with_archive(
    game: dict[str, Any], archive: Callable[..., None]
) -> dict[str, Any] | None:
    try:
        return fetch_match_stats(game, archive)
    except TypeError as exc:
        if "positional" not in str(exc) and "argument" not in str(exc):
            raise
        return fetch_match_stats(game)


def _fetch_market_evidence_with_archive(
    games: list[dict[str, Any]], archive: Callable[..., None]
) -> dict[str, Any]:
    try:
        return fetch_market_evidence(games, archive) or {}
    except TypeError as exc:
        if "positional" not in str(exc) and "argument" not in str(exc):
            raise
        return fetch_market_evidence(games) or {}


def now() -> datetime:
    return datetime.now(UTC)


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def data_version() -> str:
    digest = hashlib.sha256()
    for path in (TEAMS_PATH, MATCHES_PATH):
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def metadata(
    source: str, confidence: float = 1.0, fetched_at: datetime | None = None
) -> dict[str, Any]:
    return {
        "source": source,
        "fetched_at": (fetched_at or now()).isoformat(),
        "version": settings.model_version,
        "confidence": confidence,
    }


def seed_database(session: Session) -> None:
    games = load_json(MATCHES_PATH, [])
    for game in games:
        match_id = str(game.get("id"))
        record = session.scalar(select(MatchRecord).where(MatchRecord.match_id == match_id))
        if record:
            continue
        session.add(
            MatchRecord(
                match_id=match_id,
                payload=game,
                source="worldcup26_seed",
                fetched_at=now(),
                version=settings.model_version,
                confidence=0.85,
            )
        )

    championship = load_json(CHAMPIONSHIP_PATH, {})
    if championship and not session.scalar(
        select(SnapshotRecord).where(SnapshotRecord.key == "championship_odds")
    ):
        session.add(
            SnapshotRecord(
                key="championship_odds",
                payload=championship,
                source="legacy_monte_carlo_seed",
                fetched_at=now(),
                version=settings.model_version,
                confidence=0.8,
            )
        )
    session.commit()


def teams_payload() -> dict[str, dict[str, Any]]:
    teams = load_json(TEAMS_PATH, {})
    stamp = metadata("fc26_player_database", 0.85)
    return {name: {**team, "metadata": stamp} for name, team in teams.items()}


def raw_teams() -> dict[str, dict[str, Any]]:
    return load_json(TEAMS_PATH, {})


def all_matches(session: Session) -> list[dict[str, Any]]:
    records = session.scalars(select(MatchRecord)).all()
    matches = [
        {
            **record.payload,
            **{key: record.payload.get(key) for key in MATCH_TIMING_FIELDS},
            "metadata": metadata(
                record.source,
                record.confidence,
                record.fetched_at.replace(tzinfo=UTC)
                if record.fetched_at.tzinfo is None
                else record.fetched_at,
            ),
        }
        for record in records
    ]
    return sorted(matches, key=lambda match: parse_match_date(match.get("local_date")))


def _merge_match_timing(payload: dict[str, Any], match: dict[str, Any]) -> bool:
    changed = False
    for key in MATCH_TIMING_FIELDS:
        if key in match and payload.get(key) != match.get(key):
            payload[key] = match.get(key)
            changed = True
        elif key not in payload:
            payload[key] = None
            changed = True
    return changed


def raw_matches(session: Session) -> list[dict[str, Any]]:
    records = session.scalars(select(MatchRecord)).all()
    return sorted(
        [dict(record.payload) for record in records],
        key=lambda match: parse_match_date(match.get("local_date")),
    )


def _simulation_match_input(match: dict[str, Any]) -> dict[str, Any]:
    canonical = {key: match.get(key) for key in SIMULATION_MATCH_FIELDS if key in match}
    canonical["match_id"] = str(match.get("match_id") or match.get("id") or "")
    for key, value in match.items():
        normalized_key = key.casefold()
        compact_key = normalized_key.replace("_", "").replace("-", "")
        if (
            "penalt" in compact_key
            or "extratime" in compact_key
            or normalized_key.startswith("winner")
        ):
            canonical[key] = value
    stats = match.get("stats")
    if isinstance(stats, dict) and "unavailable_players" in stats:
        canonical["unavailable_players"] = stats["unavailable_players"]
    return canonical


def _prediction_input_snapshot_payload(
    match: dict[str, Any],
    teams: dict[str, dict[str, Any]],
    games: list[dict[str, Any]],
    market: dict[str, Any] | None,
    prediction: dict[str, Any],
    seed: int,
    prediction_timestamp: datetime,
) -> dict[str, Any]:
    home, away = match.get("home_team_name_en"), match.get("away_team_name_en")
    stats = match.get("stats") or {}
    unavailable = stats.get("unavailable_players") or {"home": [], "away": []}
    home_fatigue = fatigue_before(str(home), match, games, teams[str(home)])
    away_fatigue = fatigue_before(str(away), match, games, teams[str(away)])
    elos = dynamic_elos_before(match, teams, games)
    home_active_pqs = active_pqs(teams[str(home)], list(unavailable.get("home") or []), home_fatigue)
    away_active_pqs = active_pqs(teams[str(away)], list(unavailable.get("away") or []), away_fatigue)
    model = prediction.get("model") or {}
    return {
        "match_id": str(match.get("id")),
        "home_team": home,
        "away_team": away,
        "prediction_timestamp": prediction_timestamp.isoformat(),
        "model_version": settings.model_version,
        "elo_before": {
            "home": elos.get(str(home)),
            "away": elos.get(str(away)),
            "difference": model.get("inputs", {}).get("elo_difference"),
        },
        "fatigue_before": {"home": home_fatigue, "away": away_fatigue},
        "active_pqs": {
            "home": {
                "attack": home_active_pqs[0],
                "defense": home_active_pqs[1],
                "bench": home_active_pqs[2],
            },
            "away": {
                "attack": away_active_pqs[0],
                "defense": away_active_pqs[1],
                "bench": away_active_pqs[2],
            },
        },
        "injuries_used": unavailable,
        "market_evidence": market or {"available": False, "reason": "No fresh market data"},
        "xg": model.get("expected_goals"),
        "score_matrix": model.get("score_matrix"),
        "final_probabilities": model.get("probabilities"),
        "parameters_used": {
            "max_goals": MAX_GOALS,
            "gamma": GAMMA,
            "rho": RHO,
            "seed": seed,
            "model_blend": {"normal": 0.7, "domination": 0.3},
            "elo_weight": 0.75,
            "pqs_weight": 0.20,
            "elo_scale": 450,
            "pqs_scale": 0.3,
        },
        "match_payload": match,
    }


def simulation_input_hash_for_data(
    games: list[dict[str, Any]],
    teams: dict[str, dict[str, Any]],
    simulator_version: str | None = None,
) -> str:
    if simulator_version is None:
        from backend.player_level_simulator import SIMULATOR_INPUT_VERSION

        simulator_version = SIMULATOR_INPUT_VERSION
    canonical = {
        "model_version": settings.model_version,
        "simulation_runs": CHAMPIONSHIP_SIMULATION_RUNS,
        "simulator_version": simulator_version,
        "matches": [_simulation_match_input(game) for game in games],
        "teams": teams,
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_simulation_hash_inputs(
    session: Session,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str]:
    from backend import player_level_simulator as legacy

    games = raw_matches(session)
    teams = legacy.load_teams()
    input_hash = simulation_input_hash_for_data(
        games, teams, legacy.SIMULATOR_INPUT_VERSION
    )
    return games, teams, input_hash


def simulation_input_hash(session: Session) -> str:
    return get_simulation_hash_inputs(session)[2]


def _market_for_match(session: Session, match: dict[str, Any]) -> dict[str, Any] | None:
    match_id = str(match.get("id") or "")
    record = session.scalar(select(MarketOddsRecord).where(MarketOddsRecord.match_id == match_id))
    if not record:
        return None
    payload = dict(record.payload or {})
    kickoff = _kickoff_utc(match)
    if kickoff is None or kickoff > now():
        return payload
    if _snapshot_captured_before_kickoff(record, payload, kickoff):
        payload.update(
            {
                "available": True,
                "snapshot_status": "locked",
                "locked": True,
                "locked_at": kickoff.isoformat(),
                "reason": None,
            }
        )
    else:
        payload.update(
            {
                "available": False,
                "snapshot_status": "missing",
                "locked": False,
                "locked_at": None,
                "reason": "No pre-match odds snapshot",
            }
        )
    return payload


def _kickoff_utc(match: dict[str, Any]) -> datetime | None:
    if match.get("kickoff_utc"):
        parsed = _parse_utc_datetime(match.get("kickoff_utc"))
        if parsed:
            return parsed
    kickoff = parse_match_date(match.get("local_date"))
    if kickoff == datetime.max:
        return None
    return kickoff.replace(tzinfo=TOURNAMENT_TIMEZONE).astimezone(UTC)


def _parse_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _snapshot_captured_before_kickoff(
    record: MarketOddsRecord, payload: dict[str, Any], kickoff: datetime
) -> bool:
    captured_at = _parse_utc_datetime(payload.get("snapshot_at") or payload.get("fetched_at"))
    if captured_at is None:
        captured_at = _parse_utc_datetime(record.fetched_at)
    consensus = payload.get("consensus") or {}
    complete = all(consensus.get(key) is not None for key in ("home", "draw", "away"))
    return bool(complete and captured_at and captured_at < kickoff)


def _lock_started_market_snapshots(
    session: Session, games: list[dict[str, Any]], current_time: datetime
) -> int:
    records = {
        record.match_id: record for record in session.scalars(select(MarketOddsRecord)).all()
    }
    changed = 0
    for game in games:
        match_id = str(game.get("id") or "")
        kickoff = _kickoff_utc(game)
        record = records.get(match_id)
        if not match_id or kickoff is None or kickoff > current_time or not record:
            continue
        payload = dict(record.payload or {})
        if payload.get("snapshot_status") == "locked" and payload.get("locked") is True:
            continue
        if _snapshot_captured_before_kickoff(record, payload, kickoff):
            payload.update(
                {
                    "available": True,
                    "snapshot_status": "locked",
                    "locked": True,
                    "locked_at": kickoff.isoformat(),
                    "reason": None,
                }
            )
        else:
            payload.update(
                {
                    "available": False,
                    "snapshot_status": "missing",
                    "locked": False,
                    "locked_at": None,
                    "reason": "No pre-match odds snapshot",
                }
            )
        record.payload = payload
        changed += 1
    if changed:
        session.commit()
    return changed


def prediction_for_match(
    session: Session, match: dict[str, Any], *, force: bool = False
) -> dict[str, Any]:
    match_id = str(match.get("id"))
    version = data_version()
    market = _market_for_match(session, match)
    if market:
        market_version = ":".join(
            str(market.get(key))
            for key in ("last_update", "snapshot_status", "locked_at", "available")
        )
        version = f"{version}:{market_version}"
    existing = session.scalar(select(PredictionRecord).where(PredictionRecord.match_id == match_id))
    if existing and existing.input_version == version and not force:
        _cache["hits"] += 1
        payload = dict(existing.payload)
        if _merge_match_timing(payload, match):
            existing.payload = payload
            session.commit()
        return payload
    _cache["misses"] += 1

    teams = raw_teams()
    games = raw_matches(session)
    seed = settings.default_seed + int(match_id) if match_id.isdigit() else settings.default_seed
    prediction = predict_match(
        match,
        teams,
        games,
        market,
        seed,
    )
    prediction_timestamp = now()
    try:
        prediction_input = _prediction_input_snapshot_payload(
            match,
            teams,
            games,
            market,
            prediction,
            seed,
            prediction_timestamp,
        )
        safe_append_snapshot(
            session,
            source="predictor_input",
            snapshot_type="prediction_input",
            match_id=match_id,
            prediction_timestamp=prediction_timestamp,
            payload=prediction_input,
            model_version=settings.model_version,
        )
    except Exception:
        logger.warning("Could not build prediction input snapshot: match_id=%s", match_id, exc_info=True)
    existing_analysis = dict(existing.payload).get("risk_analysis") if existing else None
    if existing_analysis and existing_analysis.get("generated_by") == "gemini_pre_match":
        prediction["risk_analysis"] = existing_analysis
    else:
        analyses = load_json(ANALYSES_PATH, {})
        prediction["risk_analysis"] = {
            "summary": analyses.get(match_id, {}).get("llm_analysis")
            or "模型依據勝平負、預期進球、傷停、疲勞與 ELO 差距產生風險說明。",
            "generated_by": "gemini" if analyses.get(match_id, {}).get("llm_analysis") else "rules",
            "factors": prediction["model"]["upset_risk"]["factors"],
        }
    _merge_match_timing(prediction, match)
    prediction["metadata"] = metadata("predictor_engine", 0.9)
    if existing:
        existing.input_version = version
        existing.payload = prediction
        existing.source = "predictor_engine"
        existing.fetched_at = now()
        existing.version = settings.model_version
        existing.confidence = 0.9
    else:
        session.add(
            PredictionRecord(
                match_id=match_id,
                input_version=version,
                payload=prediction,
                source="predictor_engine",
                fetched_at=now(),
                version=settings.model_version,
                confidence=0.9,
            )
        )
    session.commit()
    return prediction


def list_predictions(session: Session, include_finished: bool = False) -> list[dict[str, Any]]:
    predictions = []
    for match in raw_matches(session):
        if not include_finished and match.get("finished") in {"TRUE", True}:
            continue
        home, away = match.get("home_team_name_en"), match.get("away_team_name_en")
        if not home or not away or home not in raw_teams() or away not in raw_teams():
            continue
        predictions.append(prediction_for_match(session, match))
    return predictions


def tournament_payload(session: Session) -> dict[str, Any]:
    teams = teams_payload()
    matches, bracket_resolution = resolve_tournament_matches(teams, all_matches(session))
    return {
        "teams": teams,
        "matches": matches,
        "bracket_resolution": bracket_resolution,
        "metadata": metadata("worldcup26_and_fc26", 0.85),
    }


def championship_payload(session: Session) -> dict[str, Any]:
    record = session.scalar(select(SnapshotRecord).where(SnapshotRecord.key == "championship_odds"))
    if not record:
        return {
            "last_updated": None,
            "probabilities": [],
            "explanations_version": CHAMPIONSHIP_EXPLANATIONS_VERSION,
            "metadata": metadata("missing", 0),
        }
    return {
        **record.payload,
        "explanations_version": CHAMPIONSHIP_EXPLANATIONS_VERSION,
        "metadata": metadata(
            record.source,
            record.confidence,
            record.fetched_at.replace(tzinfo=UTC)
            if record.fetched_at.tzinfo is None
            else record.fetched_at,
        ),
    }


def record_metric(
    session: Session, name: str, value: float, details: dict[str, Any] | None = None
) -> None:
    session.add(MetricRecord(name=name, value=value, details=details or {}))
    session.commit()


def metrics_payload(session: Session) -> dict[str, Any]:
    response: dict[str, Any] = {}
    for name in ("worldcup_api_time", "fotmob_time", "simulation_time"):
        latest = session.scalar(
            select(MetricRecord).where(MetricRecord.name == name).order_by(MetricRecord.id.desc())
        )
        average = session.scalar(
            select(func.avg(MetricRecord.value)).where(MetricRecord.name == name)
        )
        response[name] = {
            "latest_seconds": round(latest.value, 3) if latest else None,
            "average_seconds": round(float(average), 3) if average is not None else None,
        }
    total = _cache["hits"] + _cache["misses"]
    response["cache_hit_rate"] = round(_cache["hits"] / total * 100, 2) if total else 0.0
    response["metadata"] = metadata("application_metrics", 1.0)
    return response


def raw_snapshot_summary_payload(session: Session) -> dict[str, Any]:
    return snapshot_summary(session)


def refresh_market_odds(session: Session, games: list[dict[str, Any]]) -> int:
    current_time = now()
    _lock_started_market_snapshots(session, games, current_time)
    upcoming_games = [
        game
        for game in games
        if (kickoff := _kickoff_utc(game)) is not None and kickoff > current_time
    ]
    try:
        evidence = _fetch_market_evidence_with_archive(upcoming_games, _archive_callback(session))
    except (ConnectionResetError, TimeoutError, httpx.HTTPError, TypeError, ValueError):
        logger.warning("Market sync failed; retaining cached market data", exc_info=True)
        return 0
    games_by_id = {str(game.get("id")): game for game in upcoming_games}
    updated = 0
    for match_id, payload in evidence.items():
        if not isinstance(payload, dict):
            logger.warning("Skipping invalid market payload: match_id=%s", match_id)
            continue
        game = games_by_id.get(str(match_id))
        kickoff = _kickoff_utc(game or {})
        snapshot_time = now()
        if kickoff is None or snapshot_time >= kickoff:
            logger.warning("Skipping odds received after kickoff: match_id=%s", match_id)
            continue
        payload = {
            **payload,
            "available": bool(payload.get("consensus")),
            "snapshot_status": "open",
            "snapshot_at": snapshot_time.isoformat(),
            "locked": False,
            "locked_at": None,
            "reason": None if payload.get("consensus") else "No pre-match odds snapshot",
        }
        safe_append_snapshot(
            session,
            source="odds_api",
            snapshot_type="market_odds",
            match_id=match_id,
            payload=payload,
            model_version=settings.model_version,
        )
        record = session.scalar(
            select(MarketOddsRecord).where(MarketOddsRecord.match_id == match_id)
        )
        if record:
            record.payload = payload
            record.fetched_at = now()
            record.confidence = float(payload.get("confidence", 0.5))
        else:
            session.add(
                MarketOddsRecord(
                    match_id=match_id,
                    payload=payload,
                    source="the_odds_api",
                    fetched_at=now(),
                    version=settings.model_version,
                    confidence=float(payload.get("confidence", 0.5)),
                )
            )
        updated += 1
    session.commit()
    return updated


def refresh_fotmob_stats(session: Session, progress: Callable[[int, str, str], None]) -> int:
    started = time.perf_counter()
    records = session.scalars(select(MatchRecord)).all()
    candidates = []
    today = datetime.now()
    for record in records:
        game = record.payload or {}
        if not isinstance(game, dict):
            logger.warning("Skipping invalid match payload: match_id=%s", record.match_id)
            continue
        stats = game.get("stats") or {}
        is_finished = game.get("finished") in {"TRUE", True}
        match_date = parse_match_date(game.get("local_date"))
        is_near = match_date != datetime.max and abs((match_date - today).days) <= 3
        needs_finished_stats = is_finished and (
            not stats.get("fotmob_complete")
            or not has_complete_primary_stats(stats)
            or stats.get("fotmob_status") in {"partial", "pending"}
        )
        needs_nearby_data = is_near and not stats.get("fotmob_complete")
        needs_confirmed_kickoff = (
            not game.get("kickoff_utc")
            and str(stats.get("fotmob_match_id") or "").strip()
            and (
                is_near
                or is_finished
                or stats.get("fotmob_complete")
            )
        )
        if needs_finished_stats or needs_nearby_data or needs_confirmed_kickoff:
            candidates.append(record)

    updated = 0
    archive = _archive_callback(session)
    for index, record in enumerate(candidates):
        try:
            fetched = _fetch_match_stats_with_archive(record.payload or {}, archive)
        except (ConnectionResetError, TimeoutError, httpx.HTTPError):
            logger.warning(
                "FotMob match sync failed; continuing: match_id=%s source=fotmob",
                record.match_id,
                exc_info=True,
            )
            fetched = None
        except (AttributeError, TypeError, ValueError):
            logger.warning(
                "Invalid FotMob payload; continuing: match_id=%s source=fotmob",
                record.match_id,
                exc_info=True,
            )
            fetched = None
        if isinstance(fetched, dict) and fetched:
            match_id = str((record.payload or {}).get("id") or record.match_id)
            safe_append_snapshot(
                session,
                source="fotmob",
                snapshot_type="fotmob_parsed_stats",
                match_id=match_id,
                external_match_id=fetched.get("fotmob_match_id"),
                payload=fetched,
                model_version=settings.model_version,
            )
            if "unavailable_players" in fetched:
                safe_append_snapshot(
                    session,
                    source="fotmob",
                    snapshot_type="injury_unavailable_players",
                    match_id=match_id,
                    external_match_id=fetched.get("fotmob_match_id"),
                    fetched_at=now(),
                    payload={
                        "match_id": match_id,
                        "external_match_id": fetched.get("fotmob_match_id"),
                        "fetched_at": fetched.get("fotmob_fetched_at"),
                        "unavailable_players": fetched.get("unavailable_players"),
                    },
                    model_version=settings.model_version,
                )
            payload = dict(record.payload or {})
            previous_stats = payload.get("stats") or {}
            timing = {
                key: value for key in MATCH_TIMING_FIELDS if (value := fetched.get(key))
            }
            stats_payload = {
                key: value for key, value in fetched.items() if key not in MATCH_TIMING_FIELDS
            }
            merged_stats = {**previous_stats, **stats_payload}
            # Partial retries may fill different fields over time; retain previously known
            # primary values, while allowing missing cards to remain unknown instead of zero.
            for key in PRIMARY_STATS:
                if fetched.get(key) is None and previous_stats.get(key) is not None:
                    merged_stats[key] = previous_stats[key]
            payload["stats"] = with_fotmob_status(merged_stats)
            payload.update(timing)
            record.payload = payload
            record.source = "worldcup26_api+fotmob"
            record.fetched_at = now()
            record.confidence = 0.95
            updated += 1
        progress(
            35 + int(15 * (index + 1) / max(len(candidates), 1)),
            "fotmob",
            f"FotMob 高階資料 {index + 1}/{len(candidates)}",
        )
    session.commit()
    record_metric(session, "fotmob_time", time.perf_counter() - started)
    return updated


def _normalize_remote_game(game: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "United States": "USA",
        "Czech Republic": "Czechia",
        "Cape Verde": "Cabo Verde",
        "Democratic Republic of the Congo": "Congo DR",
        "Curaçao": "Curacao",
    }
    game = game or {}
    normalized = dict(game)
    normalized["home_team_name_en"] = aliases.get(
        game.get("home_team_name_en"), game.get("home_team_name_en")
    )
    normalized["away_team_name_en"] = aliases.get(
        game.get("away_team_name_en"), game.get("away_team_name_en")
    )
    normalized["finished"] = "TRUE" if game.get("finished") in {"TRUE", True} else "FALSE"
    if normalized.get("local_date") and not any(
        normalized.get(key) for key in ("kickoff", "kickoff_time", "date", "kickoff_utc")
    ):
        normalized["kickoff_status"] = "local_time_timezone_missing"
    return normalized


def sync_remote_matches(session: Session, progress: Callable[[int, str, str], None]) -> int:
    started = time.perf_counter()
    progress(8, "worldcup", "下載世界盃賽程與賽果")
    try:
        with httpx.Client(timeout=20) as client:
            response = _get_with_retry(client, settings.world_cup_api_url)
            response.raise_for_status()
            payload = response.json() or {}
            safe_append_snapshot(
                session,
                source="worldcup_api",
                snapshot_type="worldcup_games",
                payload=payload,
                model_version=settings.model_version,
            )
            remote_games = payload.get("games") or [] if isinstance(payload, dict) else []
    except (ConnectionResetError, TimeoutError, httpx.HTTPError, TypeError, ValueError):
        logger.warning("World Cup API sync failed; retaining cached match data", exc_info=True)
        progress(35, "worldcup", "世界盃 API 暫時無法連線，沿用快取資料")
        record_metric(session, "worldcup_api_time", time.perf_counter() - started)
        return 0
    if not isinstance(remote_games, list):
        logger.warning("World Cup API returned invalid games payload; retaining cached data")
        remote_games = []
    record_metric(session, "worldcup_api_time", time.perf_counter() - started)

    existing = {record.match_id: record for record in session.scalars(select(MatchRecord)).all()}
    for index, raw_game in enumerate(remote_games):
        if not isinstance(raw_game, dict):
            logger.warning("Skipping invalid World Cup match payload at index=%s", index)
            continue
        game = _normalize_remote_game(raw_game)
        match_id = str(game.get("id"))
        if not game.get("id"):
            logger.warning("Skipping World Cup match without id at index=%s", index)
            continue
        previous = existing.get(match_id)
        previous_payload = previous.payload or {} if previous else {}
        if previous and previous_payload.get("stats") and not game.get("stats"):
            game["stats"] = previous_payload["stats"]
        if previous and previous_payload.get("kickoff_utc") and not game.get("kickoff_utc"):
            for key in MATCH_TIMING_FIELDS:
                if previous_payload.get(key):
                    game[key] = previous_payload[key]
        if previous:
            previous.payload = game
            previous.source = "worldcup26_api"
            previous.fetched_at = now()
            previous.confidence = 0.9
        else:
            session.add(
                MatchRecord(
                    match_id=match_id,
                    payload=game,
                    source="worldcup26_api",
                    fetched_at=now(),
                    version=settings.model_version,
                    confidence=0.9,
                )
            )
        if index % 10 == 0:
            progress(
                10 + int(25 * (index + 1) / max(len(remote_games), 1)), "worldcup", "更新賽事資料"
            )
    session.commit()
    return len(remote_games)


def refresh_predictions(session: Session, progress: Callable[[int, str, str], None]) -> int:
    games = raw_matches(session)
    candidates = [
        game
        for game in games
        if game.get("home_team_name_en") in raw_teams()
        and game.get("away_team_name_en") in raw_teams()
    ]
    for index, game in enumerate(candidates):
        prediction_for_match(session, game, force=True)
        if index % 8 == 0:
            progress(
                60 + int(15 * (index + 1) / max(len(candidates), 1)), "predictions", "重新計算預測"
            )
    return len(candidates)


def _probability_snapshot(prediction: dict[str, Any]) -> dict[str, float]:
    probabilities = (prediction.get("model") or {}).get("probabilities") or {}
    return {
        key: float(probabilities[key])
        for key in ("home", "draw", "away")
        if probabilities.get(key) is not None
    }


def _market_snapshot(prediction: dict[str, Any]) -> dict[str, float]:
    market = prediction.get("market_evidence") or {}
    consensus = market.get("consensus") or {}
    if not market.get("available"):
        return {}
    return {
        key: float(consensus[key])
        for key in ("home", "draw", "away")
        if consensus.get(key) is not None
    }


def _probabilities_changed(current: dict[str, float], baseline: dict[str, float]) -> bool:
    return bool(current and baseline) and any(
        abs(current.get(key, 0) - baseline.get(key, 0)) > 5
        for key in ("home", "draw", "away")
    )


def _analysis_updated_at(analysis: dict[str, Any]) -> datetime | None:
    value = analysis.get("updated_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def select_prematch_analysis_candidates(
    session: Session, *, limit: int = 10, current_time: datetime | None = None
) -> list[tuple[MatchRecord, PredictionRecord]]:
    current_time = current_time or now()
    current_utc = (
        current_time.replace(tzinfo=UTC)
        if current_time.tzinfo is None
        else current_time.astimezone(UTC)
    )
    # The current World Cup feed and frontend interpret local_date as UTC-04:00.
    tournament_timezone = timezone(timedelta(hours=-4))
    current_local = current_utc.astimezone(tournament_timezone).replace(tzinfo=None)
    predictions = {
        record.match_id: record for record in session.scalars(select(PredictionRecord)).all()
    }
    candidates = []
    for match_record in session.scalars(select(MatchRecord)).all():
        match = dict(match_record.payload or {})
        if match.get("finished") in {"TRUE", True}:
            continue
        prediction_record = predictions.get(match_record.match_id)
        if not prediction_record:
            continue
        kickoff = parse_match_date(match.get("local_date"))
        if kickoff == datetime.max or kickoff <= current_local:
            continue

        prediction = dict(prediction_record.payload or {})
        analysis = prediction.get("risk_analysis") or {}
        missing = analysis.get("generated_by") != "gemini_pre_match"
        updated_at = _analysis_updated_at(analysis)
        stale = updated_at is None or current_utc - updated_at > timedelta(hours=24)
        model_changed = _probabilities_changed(
            _probability_snapshot(prediction), analysis.get("model_probabilities") or {}
        )
        market_changed = _probabilities_changed(
            _market_snapshot(prediction), analysis.get("market_consensus") or {}
        )
        until_kickoff = kickoff - current_local
        within_48_hours = until_kickoff <= timedelta(hours=48)
        within_5_days = until_kickoff <= timedelta(days=5)
        changed = model_changed or market_changed
        if not (missing or (within_5_days and stale) or changed):
            continue
        priority = (
            0 if missing else 1,
            0 if within_48_hours else 1,
            0 if changed else 1,
            0 if within_5_days else 1,
            kickoff,
        )
        candidates.append((priority, match_record, prediction_record))
    candidates.sort(key=lambda item: item[0])
    return [(match, prediction) for _, match, prediction in candidates[:limit]]


def _gemini_prematch_analysis(
    prediction: dict[str, Any], match: dict[str, Any]
) -> str | None:
    if not settings.gemini_api_key:
        return None
    model = prediction.get("model") or {}
    prompt = {
        "instruction": (
            "以繁體中文撰寫 180 字內的賽前風險解釋。只能解釋所提供的既有資料；"
            "不得提出或修改勝率、比分、Elo、市場賠率、模型結果，也不得輸出 JSON。"
        ),
        "match": {
            "home": prediction.get("home") or match.get("home_team_name_en"),
            "away": prediction.get("away") or match.get("away_team_name_en"),
            "kickoff": match.get("local_date"),
            "stage": match.get("type"),
        },
        "model": {
            "probabilities": model.get("probabilities"),
            "expected_goals": model.get("expected_goals"),
            "predicted_score": model.get("predicted_score"),
            "confidence": model.get("confidence"),
            "upset_risk": model.get("upset_risk"),
        },
        "market_consensus": _market_snapshot(prediction),
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={settings.gemini_api_key}"
    )
    with httpx.Client(timeout=60) as client:
        response = client.post(
            url,
            json={"contents": [{"parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}]},
        )
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def refresh_prematch_ai_analyses(
    session: Session, progress: Callable[[int, str, str], None]
) -> int:
    candidates = select_prematch_analysis_candidates(session, limit=10)
    if not settings.gemini_api_key:
        logger.warning("Skipping pre-match AI cache refresh: GEMINI_API_KEY is not configured")
        return 0

    updated = 0
    for index, (match_record, prediction_record) in enumerate(candidates):
        match = dict(match_record.payload or {})
        prediction = dict(prediction_record.payload or {})
        try:
            summary = _gemini_prematch_analysis(prediction, match)
            if not summary:
                raise ValueError("Gemini returned an empty analysis")
            prediction["risk_analysis"] = {
                "summary": summary,
                "generated_by": "gemini_pre_match",
                "factors": (prediction.get("model") or {}).get("upset_risk", {}).get("factors", []),
                "updated_at": now().isoformat(),
                "model_probabilities": _probability_snapshot(prediction),
                "market_consensus": _market_snapshot(prediction),
            }
            prediction_record.payload = prediction
            prediction_record.source = "predictor_engine+gemini"
            updated += 1
            session.commit()
        except Exception:  # Per-match external API boundary: retain cache and continue sync.
            logger.warning(
                "Pre-match Gemini analysis failed; keeping cached analysis: match_id=%s",
                match_record.match_id,
                exc_info=True,
            )
        progress(
            76 + int(6 * (index + 1) / max(len(candidates), 1)),
            "ai_analysis",
            f"更新賽前 AI 分析 {index + 1}/{len(candidates)}",
        )
    return updated


def backtest_payload(session: Session, persist: bool = True) -> dict[str, Any]:
    games = [
        game
        for game in raw_matches(session)
        if game.get("finished") in {"TRUE", True}
        and game.get("home_team_name_en") in raw_teams()
        and game.get("away_team_name_en") in raw_teams()
    ]
    rows = [(prediction_for_match(session, game), game) for game in games]
    summary = {
        "dataset": "2026 retrospective walk-forward",
        "status": "retrospective",
        "development_sets": development_set_summary(),
        **calculate_backtest(rows),
        "metadata": metadata("prediction_snapshots_and_results", 0.8),
    }
    if persist:
        session.add(
            BacktestRun(
                dataset=summary["dataset"],
                model_version=settings.model_version,
                payload=summary,
            )
        )
        session.commit()
    return summary


def development_set_summary() -> dict[str, Any]:
    files = {
        "Euro 2024": ARCHIVE_DIR / "Euro_2024_Matches.csv",
        "Copa 2024": ARCHIVE_DIR / "Copa_2024_Matches.csv",
        "AFCON 2025-26": ARCHIVE_DIR / "afcon_2025_2026_dataset.csv",
    }
    counts: dict[str, int] = {}
    for name, path in files.items():
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                counts[name] = max(0, sum(1 for _ in csv.reader(handle)) - 1)
        except OSError:
            counts[name] = 0
    return {
        "role": "parameter development only; 127 matches remain after team-data validation",
        "matches": counts,
        "raw_total": sum(counts.values()),
        "total": 127,
    }


def latest_backtest(session: Session) -> dict[str, Any]:
    record = session.scalar(select(BacktestRun).order_by(BacktestRun.id.desc()))
    return dict(record.payload) if record else backtest_payload(session)


def _gemini_review(
    base_review: dict[str, Any], prediction: dict[str, Any], match: dict[str, Any]
) -> str | None:
    if not settings.gemini_api_key:
        return None
    prompt = {
        "instruction": (
            "以繁體中文撰寫 120 字內賽後模型檢討。只解釋既有分類與資料，"
            "不得修改勝率、預測或 failure_type。"
        ),
        "classification": base_review,
        "prediction": prediction["model"],
        "actual": {
            "score": [match.get("home_score"), match.get("away_score")],
            "stats": match.get("stats"),
        },
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={settings.gemini_api_key}"
    )
    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(
                url,
                json={"contents": [{"parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}]},
            )
            response.raise_for_status()
            return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (httpx.HTTPError, KeyError, IndexError, TypeError):
        return None


def create_new_reviews(session: Session) -> int:
    count = 0
    for match in raw_matches(session):
        if match.get("finished") not in {"TRUE", True}:
            continue
        match_id = str(match.get("id"))
        if session.scalar(select(MatchReview).where(MatchReview.match_id == match_id)):
            continue
        try:
            prediction = prediction_for_match(session, match)
        except ValueError:
            continue
        review = deterministic_review(prediction, match)
        llm_text = _gemini_review(review, prediction, match)
        if llm_text:
            review["review"] = llm_text
            review["generated_by"] = "gemini_with_rules"
        session.add(
            MatchReview(
                match_id=match_id,
                failure_type=review["failure_type"],
                payload=review,
                source=review["generated_by"],
                fetched_at=now(),
                version=settings.model_version,
                confidence=0.85 if llm_text else 0.7,
            )
        )
        count += 1
    session.commit()
    return count


def review_for_match(session: Session, match_id: str) -> dict[str, Any] | None:
    record = session.scalar(select(MatchReview).where(MatchReview.match_id == match_id))
    if not record:
        return None
    return {
        **record.payload,
        "metadata": metadata(
            record.source,
            record.confidence,
            record.fetched_at.replace(tzinfo=UTC)
            if record.fetched_at.tzinfo is None
            else record.fetched_at,
        ),
    }


def run_sync_pipeline(progress: Callable[[int, str, str], None]) -> dict[str, Any]:
    with SessionLocal() as session:
        synced = sync_remote_matches(session, progress)
        progress(35, "fotmob", "同步 xG、射門、牌、傷停與換人")
        fotmob_count = refresh_fotmob_stats(session, progress)
        progress(52, "market", "同步市場 1X2 證據")
        market_count = refresh_market_odds(session, raw_matches(session))
        progress(58, "market", "市場證據處理完成")
        predictions = refresh_predictions(session, progress)
        progress(76, "ai_analysis", "檢查賽前 AI 分析快取")
        ai_analyses = refresh_prematch_ai_analyses(session, progress)
        progress(84, "backtest", "更新回測報告")
        backtest_payload(session)
        progress(90, "reviews", "產生新完賽檢討")
        reviews = create_new_reviews(session)
        progress(100, "completed", "同步完成")
        return {
            "matches": synced,
            "fotmob_matches": fotmob_count,
            "market_events": market_count,
            "predictions": predictions,
            "ai_analyses": ai_analyses,
            "reviews": reviews,
        }


def run_simulation_pipeline(progress: Callable[[int, str, str], None]) -> dict[str, Any]:
    from backend import player_level_simulator as legacy

    started = time.perf_counter()
    progress(5, "simulation", "準備 10,000 次蒙地卡羅模擬")
    # The database is the sole match source for both /api/tournament and simulations.
    with SessionLocal() as session:
        games, base_teams, input_hash = get_simulation_hash_inputs(session)
    teams = legacy.apply_real_performance_boost(base_teams, games)
    real_games_lookup = legacy.build_real_games_lookup(games)
    finished_match_shortcuts = legacy.build_finished_match_shortcuts(real_games_lookup, teams)
    active_pqs_cache = {}
    counters = {
        team: {
            key: 0 for key in ("R32_pct", "R16_pct", "QF_pct", "SF_pct", "Final_pct", "Winner_pct")
        }
        for team in teams
    }
    runs = CHAMPIONSHIP_SIMULATION_RUNS
    for index in range(runs):
        result = legacy.simulate_tournament_once(
            teams, games, real_games_lookup, finished_match_shortcuts, active_pqs_cache
        )
        for key in ("R32", "R16", "QF", "SF", "Final"):
            for team in result[key]:
                counters[team][f"{key}_pct"] += 1
        counters[result["Winner"]]["Winner_pct"] += 1
        if index and index % 1000 == 0:
            progress(5 + int(index / runs * 90), "simulation", f"已完成 {index:,} 次模擬")
    probabilities = []
    for team, values in counters.items():
        probabilities.append(
            {
                "team_name": team,
                **{key: round(value / runs * 100, 2) for key, value in values.items()},
            }
        )
    probabilities.sort(key=lambda item: item["Winner_pct"], reverse=True)
    explanations = championship_explanations(probabilities, teams)
    validate_championship_explanations(explanations)
    payload = {
        "last_updated": now().isoformat(),
        "input_hash": input_hash,
        "probabilities": probabilities,
        "explanations_version": CHAMPIONSHIP_EXPLANATIONS_VERSION,
        "explanations": explanations,
    }
    with SessionLocal() as session:
        record = session.scalar(
            select(SnapshotRecord).where(SnapshotRecord.key == "championship_odds")
        )
        if record:
            record.payload = payload
            record.source = "backend_monte_carlo"
            record.fetched_at = now()
            record.confidence = 0.9
        else:
            session.add(
                SnapshotRecord(
                    key="championship_odds",
                    payload=payload,
                    source="backend_monte_carlo",
                    fetched_at=now(),
                    version=settings.model_version,
                    confidence=0.9,
                )
            )
        record_metric(session, "simulation_time", time.perf_counter() - started)
        session.commit()
    progress(100, "completed", "模擬完成")
    return {"runs": runs, "teams": len(probabilities)}
