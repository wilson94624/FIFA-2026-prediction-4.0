from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app import fotmob, services
from backend.app.archive import append_snapshot
from backend.app.db import Base
from backend.app.main import app
from backend.app.models import MatchRecord, RawSnapshotRecord

ROOT = Path(__file__).resolve().parents[2]


def _memory_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_raw_snapshot_is_created_and_duplicate_payload_hash_is_skipped():
    with _memory_session() as session:
        first = append_snapshot(
            session,
            source="fotmob",
            snapshot_type="fotmob_match_details",
            match_id="29",
            external_match_id="4667793",
            payload={"alpha": 1, "beta": [2, 3]},
        )
        duplicate = append_snapshot(
            session,
            source="fotmob",
            snapshot_type="fotmob_match_details",
            match_id="29",
            external_match_id="4667793",
            payload={"beta": [2, 3], "alpha": 1},
        )
        session.commit()

        assert first is not None
        assert duplicate is None
        assert len(session.scalars(select(RawSnapshotRecord)).all()) == 1


def test_fotmob_raw_response_archive_callback_can_be_mocked():
    archived = []

    class Response:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, **_kwargs):
            if "matches" in url:
                return Response(
                    {
                        "leagues": [
                            {
                                "matches": [
                                    {
                                        "id": "4667793",
                                        "home": {"name": "France"},
                                        "away": {"name": "Senegal"},
                                    }
                                ]
                            }
                        ]
                    }
                )
            return Response(
                {
                    "header": {"status": {"utcTime": "2026-06-21T19:00:00.000Z"}},
                    "content": {
                        "stats": {
                            "Periods": {
                                "All": {
                                    "stats": [
                                        {
                                            "stats": [
                                                {"title": "Expected goals (xG)", "stats": [1.2, 0.8]},
                                                {"title": "Ball possession", "stats": [52, 48]},
                                                {"title": "Total shots", "stats": [8, 5]},
                                            ]
                                        }
                                    ]
                                }
                            }
                        },
                        "lineup": {"homeTeam": {"unavailable": []}, "awayTeam": {"unavailable": []}},
                    },
                }
            )

    def archive_callback(**kwargs):
        archived.append(kwargs)

    original_client = fotmob.httpx.Client
    try:
        fotmob.httpx.Client = Client
        stats = fotmob.fetch_match_stats(
            {
                "id": "29",
                "home_team_name_en": "France",
                "away_team_name_en": "Senegal",
                "local_date": "06/21/2026 12:00",
            },
            archive_callback,
        )
    finally:
        fotmob.httpx.Client = original_client

    assert stats["fotmob_match_id"] == "4667793"
    assert [item["snapshot_type"] for item in archived] == [
        "fotmob_matches",
        "fotmob_match_details",
    ]


def test_injury_unavailable_snapshot_is_appended(monkeypatch):
    with _memory_session() as session:
        record = MatchRecord(
            match_id="29",
            payload={
                "id": "29",
                "finished": "TRUE",
                "home_team_name_en": "France",
                "away_team_name_en": "Senegal",
                "local_date": "06/21/2026 12:00",
            },
        )
        session.add(record)
        session.commit()
        monkeypatch.setattr(
            services,
            "fetch_match_stats",
            Mock(
                return_value={
                    "fotmob_match_id": "4667793",
                    "xgA": 1.1,
                    "xgB": 0.7,
                    "possessionA": 52,
                    "possessionB": 48,
                    "shotsA": 9,
                    "shotsB": 6,
                    "unavailable_players": {
                        "home": [{"name": "Player A", "type": "injury"}],
                        "away": [],
                    },
                    "fotmob_fetched_at": "2026-06-21T10:00:00+00:00",
                }
            ),
        )

        assert services.refresh_fotmob_stats(session, Mock()) == 1

        injury = session.scalar(
            select(RawSnapshotRecord).where(
                RawSnapshotRecord.snapshot_type == "injury_unavailable_players"
            )
        )
        assert injury is not None
        assert injury.payload_json["unavailable_players"]["home"][0]["name"] == "Player A"


def test_prediction_input_snapshot_is_appended_and_failure_does_not_interrupt(monkeypatch):
    teams = json.loads((ROOT / "frontend/src/teams_db.json").read_text())
    games = json.loads((ROOT / "frontend/src/real_games_results.json").read_text())
    match = next(
        game
        for game in games
        if game.get("home_team_name_en") in teams
        and game.get("away_team_name_en") in teams
        and game.get("finished") == "FALSE"
    )

    with _memory_session() as session:
        for game in games[:3]:
            session.add(MatchRecord(match_id=str(game["id"]), payload=game))
        session.add(MatchRecord(match_id=str(match["id"]), payload=match))
        session.commit()

        payload = services.prediction_for_match(session, match, force=True)
        snapshot = session.scalar(
            select(RawSnapshotRecord).where(RawSnapshotRecord.snapshot_type == "prediction_input")
        )

        assert payload["match_id"] == str(match["id"])
        assert snapshot is not None
        assert snapshot.payload_json["match_id"] == str(match["id"])
        assert snapshot.payload_json["xg"] == payload["model"]["expected_goals"]
        assert snapshot.payload_json["final_probabilities"] == payload["model"]["probabilities"]

    def failing_snapshot(*_args, **_kwargs):
        raise RuntimeError("archive unavailable")

    with _memory_session() as session:
        session.add(MatchRecord(match_id=str(match["id"]), payload=match))
        session.commit()
        monkeypatch.setattr(services, "safe_append_snapshot", failing_snapshot)

        payload = services.prediction_for_match(session, match, force=True)

        assert payload["match_id"] == str(match["id"])


def test_snapshot_summary_endpoint_reports_counts():
    with TestClient(app) as client:
        response = client.get("/api/admin/snapshots/summary")

    assert response.status_code == 200
    assert "total_snapshots" in response.json()
    assert "by_source" in response.json()
    assert "by_snapshot_type" in response.json()
    assert "matches_with_injury_snapshots" in response.json()
