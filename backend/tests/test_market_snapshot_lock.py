from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app import services
from backend.app.db import Base
from backend.app.models import MarketOddsRecord

GAME = {
    "id": "29",
    "local_date": "06/20/2026 13:00",
    "home_team_name_en": "France",
    "away_team_name_en": "Senegal",
    "finished": "FALSE",
}


def market_payload(fetched_at: str) -> dict:
    return {
        "available": True,
        "consensus": {"home": 50.0, "draw": 30.0, "away": 20.0},
        "bookmaker_count": 5,
        "last_update": fetched_at,
        "fetched_at": fetched_at,
        "confidence": 0.75,
    }


def test_prematch_snapshot_is_updated_then_locked_without_live_refill(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    fetched_games = []

    with Session(engine) as session:
        monkeypatch.setattr(services, "now", lambda: datetime(2026, 6, 20, 15, tzinfo=UTC))
        monkeypatch.setattr(
            services,
            "fetch_market_evidence",
            lambda games: fetched_games.append(list(games))
            or {"29": market_payload("2026-06-20T14:55:00+00:00")},
        )

        assert services.refresh_market_odds(session, [GAME]) == 1
        record = session.scalar(select(MarketOddsRecord).where(MarketOddsRecord.match_id == "29"))
        assert record.payload["snapshot_status"] == "open"
        assert record.payload["locked"] is False

        monkeypatch.setattr(services, "now", lambda: datetime(2026, 6, 20, 18, tzinfo=UTC))
        read_payload = services._market_for_match(session, GAME)
        assert read_payload["snapshot_status"] == "locked"
        assert read_payload["locked"] is True
        assert services.refresh_market_odds(session, [GAME]) == 0
        session.refresh(record)

        assert fetched_games[0] == [GAME]
        assert fetched_games[1] == []
        assert record.payload["snapshot_status"] == "locked"
        assert record.payload["locked"] is True
        assert record.payload["available"] is True
        assert record.payload["consensus"] == {"home": 50.0, "draw": 30.0, "away": 20.0}


def test_started_match_without_valid_prematch_snapshot_stays_unavailable(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            MarketOddsRecord(
                match_id="29",
                payload=market_payload("2026-06-20T18:05:00+00:00"),
                source="the_odds_api",
                fetched_at=datetime(2026, 6, 20, 18, 5, tzinfo=UTC),
                confidence=0.75,
            )
        )
        session.commit()
        requested_games = []
        monkeypatch.setattr(services, "now", lambda: datetime(2026, 6, 20, 19, tzinfo=UTC))
        monkeypatch.setattr(
            services,
            "fetch_market_evidence",
            lambda games: requested_games.extend(games) or {},
        )

        assert services.refresh_market_odds(session, [GAME]) == 0
        record = session.scalar(select(MarketOddsRecord).where(MarketOddsRecord.match_id == "29"))

        assert requested_games == []
        assert record.payload["snapshot_status"] == "missing"
        assert record.payload["locked"] is False
        assert record.payload["available"] is False
        assert record.payload["reason"] == "No pre-match odds snapshot"
