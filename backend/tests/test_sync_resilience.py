from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import httpx

from backend.app import fotmob, jobs, services
from backend.app.models import MatchRecord


class FakeSession:
    def __init__(self, records=None):
        self.records = records or []
        self.added = []
        self.job = None

    def scalar(self, _query):
        return None

    def scalars(self, _query):
        return SimpleNamespace(all=lambda: self.records)

    def add(self, value):
        self.added.append(value)
        if isinstance(value, jobs.JobRecord):
            self.job = value

    def commit(self):
        return None

    def refresh(self, _value):
        return None


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=Mock(), response=Mock(status_code=self.status_code)
            )


def test_fotmob_none_and_missing_payloads_are_safe():
    assert fotmob._stat_pairs({"content": None}) == {}
    assert fotmob._stat_pairs({"content": {"stats": None}}) == {}
    assert fotmob._parse_unavailable({}, "homeTeam") == []
    assert fotmob._parse_unavailable({"homeTeam": None}, "homeTeam") == []
    assert fotmob._event_summary({"content": {"matchFacts": None}}) == {
        "substitutions": [],
        "injury_events": [],
    }


def test_world_cup_connection_reset_uses_cache(monkeypatch):
    attempts = 0

    class ResettingClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            raise ConnectionResetError("peer reset")

    monkeypatch.setattr(services.httpx, "Client", ResettingClient)
    monkeypatch.setattr(services.time, "sleep", lambda _delay: None)
    session = FakeSession()
    progress = Mock()

    assert services.sync_remote_matches(session, progress) == 0
    assert attempts == 3
    progress.assert_any_call(35, "worldcup", "世界盃 API 暫時無法連線，沿用快取資料")


def test_tournament_payload_exposes_kickoff_metadata_keys():
    record = MatchRecord(
        match_id="37",
        payload={"id": "37", "local_date": "06/21/2026 12:00"},
        source="worldcup",
        fetched_at=services.now(),
        confidence=0.8,
    )

    [match] = services.all_matches(FakeSession([record]))

    assert match["kickoff_utc"] is None
    assert match["kickoff_status"] is None
    assert match["kickoff_source"] is None


def test_cached_prediction_merges_match_kickoff_metadata(monkeypatch):
    monkeypatch.setattr(services, "_market_for_match", lambda *_args, **_kwargs: None)
    cached = SimpleNamespace(
        input_version=services.data_version(),
        payload={"match_id": "37", "home": "Belgium", "away": "Iran"},
    )

    class PredictionCacheSession:
        committed = False

        def scalar(self, _query):
            return cached

        def commit(self):
            self.committed = True

    session = PredictionCacheSession()
    payload = services.prediction_for_match(
        session,
        {
            "id": "37",
            "kickoff_utc": "2026-06-21T19:00:00Z",
            "kickoff_status": "confirmed",
            "kickoff_source": "fotmob",
        },
    )

    assert payload["kickoff_utc"] == "2026-06-21T19:00:00Z"
    assert payload["kickoff_status"] == "confirmed"
    assert payload["kickoff_source"] == "fotmob"
    assert cached.payload == payload
    assert session.committed is True


def test_fotmob_per_match_failure_does_not_stop_sync(monkeypatch):
    records = [
        SimpleNamespace(
            match_id="p0-one",
            payload={"id": "p0-one", "finished": True, "local_date": "2026-06-19"},
            source="seed",
            fetched_at=None,
            confidence=0.8,
        ),
        SimpleNamespace(
            match_id="p0-two",
            payload={"id": "p0-two", "finished": True, "local_date": "2026-06-19"},
            source="seed",
            fetched_at=None,
            confidence=0.8,
        ),
    ]
    responses = iter(
        [
            httpx.ReadError("peer reset"),
            {
                "fotmob_complete": True,
                "xgA": 1.2,
                "xgB": 0.8,
                "possessionA": 52,
                "possessionB": 48,
                "shotsA": 8,
                "shotsB": 5,
            },
        ]
    )

    def fetch(_payload):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(services, "fetch_match_stats", fetch)
    session = FakeSession(records)

    assert services.refresh_fotmob_stats(session, Mock()) == 1
    assert "stats" not in records[0].payload
    assert records[1].payload["stats"]["fotmob_complete"] is True


def test_fotmob_kickoff_utc_is_promoted_to_match_payload(monkeypatch):
    record = SimpleNamespace(
        match_id="37",
        payload={
            "id": "37",
            "finished": "FALSE",
            "local_date": datetime.now().strftime("%m/%d/%Y %H:%M"),
            "stats": {},
        },
        source="worldcup26_api",
        fetched_at=None,
        confidence=0.9,
    )
    monkeypatch.setattr(
        services,
        "fetch_match_stats",
        Mock(
            return_value={
                "xgA": None,
                "xgB": None,
                "possessionA": None,
                "possessionB": None,
                "shotsA": None,
                "shotsB": None,
                "kickoff_utc": "2026-06-21T19:00:00Z",
                "kickoff_source": "fotmob",
                "kickoff_status": "confirmed",
            }
        ),
    )

    assert services.refresh_fotmob_stats(FakeSession([record]), Mock()) == 1

    assert record.payload["kickoff_utc"] == "2026-06-21T19:00:00Z"
    assert record.payload["kickoff_source"] == "fotmob"
    assert record.payload["kickoff_status"] == "confirmed"
    assert "kickoff_utc" not in record.payload["stats"]


def test_fotmob_sync_refetches_complete_stats_when_kickoff_utc_is_missing(monkeypatch):
    record = SimpleNamespace(
        match_id="37",
        payload={
            "id": "37",
            "finished": "FALSE",
            "local_date": services.now().strftime("%m/%d/%Y %H:%M"),
            "home_team_name_en": "Belgium",
            "away_team_name_en": "Iran",
            "stats": {
                "fotmob_match_id": "4667793",
                "fotmob_complete": True,
                "fotmob_status": "complete",
                "xgA": 1.2,
                "xgB": 0.8,
                "possessionA": 52,
                "possessionB": 48,
                "shotsA": 8,
                "shotsB": 5,
            },
        },
        source="worldcup26_api+fotmob",
        fetched_at=None,
        confidence=0.95,
    )
    fetch = Mock(
        return_value={
            "fotmob_match_id": "4667793",
            "kickoff_utc": "2026-06-21T19:00:00Z",
            "kickoff_source": "fotmob",
            "kickoff_status": "confirmed",
        }
    )
    monkeypatch.setattr(services, "fetch_match_stats", fetch)

    assert services.refresh_fotmob_stats(FakeSession([record]), Mock()) == 1

    fetch.assert_called_once()
    assert record.payload["kickoff_utc"] == "2026-06-21T19:00:00Z"
    assert record.payload["kickoff_source"] == "fotmob"
    assert record.payload["kickoff_status"] == "confirmed"
    assert record.payload["stats"]["fotmob_complete"] is True


def test_worldcup_sync_preserves_confirmed_kickoff_utc(monkeypatch):
    record = SimpleNamespace(
        match_id="37",
        payload={
            "id": "37",
            "home_team_name_en": "Belgium",
            "away_team_name_en": "Iran",
            "finished": "FALSE",
            "local_date": "06/21/2026 12:00",
            "kickoff_utc": "2026-06-21T19:00:00Z",
            "kickoff_source": "fotmob",
            "kickoff_status": "confirmed",
            "stats": {"fotmob_match_id": "4667793"},
        },
        source="worldcup26_api+fotmob",
        fetched_at=None,
        confidence=0.95,
    )

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            return FakeResponse(
                {
                    "games": [
                        {
                            "id": "37",
                            "home_team_name_en": "Belgium",
                            "away_team_name_en": "Iran",
                            "finished": False,
                            "local_date": "06/21/2026 12:00",
                        }
                    ]
                }
            )

    monkeypatch.setattr(services.httpx, "Client", Client)
    monkeypatch.setattr(services, "record_metric", lambda *_args, **_kwargs: None)

    assert services.sync_remote_matches(FakeSession([record]), Mock()) == 1

    assert record.payload["kickoff_utc"] == "2026-06-21T19:00:00Z"
    assert record.payload["kickoff_source"] == "fotmob"
    assert record.payload["kickoff_status"] == "confirmed"
    assert record.payload["stats"]["fotmob_match_id"] == "4667793"


def _fotmob_detail(*items):
    return {
        "content": {
            "stats": {"Periods": {"All": {"stats": [{"stats": list(items)}]}}},
        }
    }


def test_empty_stats_are_pending_and_missing_cards_stay_unknown():
    parsed = fotmob._parse_match_stats(_fotmob_detail(), "fotmob-1")

    assert parsed["fotmob_complete"] is False
    assert parsed["fotmob_status"] == "pending"
    assert parsed["cardsA"] is None
    assert parsed["cardsB"] is None


def test_fotmob_detail_extracts_confirmed_utc_kickoff():
    detail = {
        "header": {"status": {"utcTime": "2026-06-21T19:00:00.000Z"}},
        "content": {"stats": {"Periods": {"All": {"stats": []}}}},
    }

    parsed = fotmob._parse_match_stats(detail, "4667793")

    assert parsed["kickoff_utc"] == "2026-06-21T19:00:00Z"
    assert parsed["kickoff_source"] == "fotmob"
    assert parsed["kickoff_status"] == "confirmed"


def test_partial_finished_stats_are_retried_on_next_sync(monkeypatch):
    record = SimpleNamespace(
        match_id="29",
        payload={
            "id": "29",
            "finished": "TRUE",
            "local_date": "06/19/2026 21:00",
            "stats": {
                "xgA": None,
                "xgB": None,
                "possessionA": None,
                "possessionB": None,
                "shotsA": None,
                "shotsB": None,
                "cardsA": 0,
                "cardsB": 0,
                "fotmob_complete": True,
            },
        },
        source="worldcup26_api",
        fetched_at=None,
        confidence=0.9,
    )
    partial = {
        "xgA": None,
        "xgB": None,
        "possessionA": 51,
        "possessionB": 49,
        "shotsA": None,
        "shotsB": None,
        "cardsA": None,
        "cardsB": None,
        "fotmob_complete": False,
        "fotmob_status": "partial",
    }
    fetch = Mock(return_value=partial)
    monkeypatch.setattr(services, "fetch_match_stats", fetch)
    session = FakeSession([record])

    assert services.refresh_fotmob_stats(session, Mock()) == 1
    assert services.refresh_fotmob_stats(session, Mock()) == 1

    assert fetch.call_count == 2
    assert record.payload["stats"]["fotmob_complete"] is False
    assert record.payload["stats"]["fotmob_status"] == "partial"
    assert record.payload["stats"]["cardsA"] is None


def test_complete_primary_stats_are_marked_complete():
    detail = _fotmob_detail(
        {"title": "Expected goals (xG)", "stats": [1.7, 0.9]},
        {"title": "Ball possession", "stats": [55, 45]},
        {"title": "Total shots", "stats": [14, 8]},
        {"title": "Yellow cards", "stats": [2, 1]},
    )

    parsed = fotmob._parse_match_stats(detail, "fotmob-2")

    assert parsed["fotmob_complete"] is True
    assert parsed["fotmob_status"] == "complete"
    assert parsed["cardsA"] == 2
    assert parsed["cardsB"] == 1


def test_submit_failure_is_persisted_instead_of_queued(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(
        jobs.executor,
        "submit",
        Mock(side_effect=RuntimeError("executor unavailable")),
    )

    payload, reused = jobs.create_or_reuse_job(session, "sync")

    assert reused is False
    assert payload["status"] == "failed"
    assert payload["stage"] == "submit"
    assert "executor unavailable" in payload["error"]
