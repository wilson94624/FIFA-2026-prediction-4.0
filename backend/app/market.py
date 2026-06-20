from __future__ import annotations

import logging
import re
import statistics
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .config import settings

ODDS_URL = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds"
logger = logging.getLogger(__name__)
RETRYABLE_ERRORS = (
    ConnectionResetError,
    TimeoutError,
    httpx.ReadError,
    httpx.ConnectError,
    httpx.TimeoutException,
)


def _get_with_retry(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    for attempt in range(3):
        try:
            return client.get(url, **kwargs)
        except RETRYABLE_ERRORS:
            if attempt == 2:
                raise
            logger.warning("Odds request failed; retrying (%s/3)", attempt + 1)
            time.sleep(0.25 * (2**attempt))
    raise RuntimeError("unreachable")


def normalize_team(name: str | None) -> str:
    if not name:
        return ""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    aliases = {
        "united states": "usa",
        "united states of america": "usa",
        "south korea": "korea republic",
        "korea republic": "korea republic",
        "czech republic": "czechia",
        "cape verde": "cabo verde",
        "dr congo": "congo dr",
        "democratic republic of congo": "congo dr",
        "ivory coast": "cote divoire",
    }
    cleaned = re.sub(r"[^a-z0-9 ]", "", ascii_name.casefold()).strip()
    return aliases.get(cleaned, cleaned)


def devig_decimal_prices(prices: dict[str, float]) -> dict[str, float]:
    implied = {key: 1 / value for key, value in prices.items() if value > 1}
    total = sum(implied.values())
    if len(implied) != 3 or total <= 0:
        raise ValueError("A complete 1X2 market is required")
    return {key: value / total for key, value in implied.items()}


def consensus_from_bookmakers(
    event: dict[str, Any], home_name: str, away_name: str
) -> tuple[dict[str, float], int, datetime | None]:
    samples: dict[str, list[float]] = {"home": [], "draw": [], "away": []}
    latest_update: datetime | None = None
    for bookmaker in (event or {}).get("bookmakers") or []:
        if not isinstance(bookmaker, dict):
            continue
        market = next(
            (
                item
                for item in bookmaker.get("markets") or []
                if isinstance(item, dict) and item.get("key") == "h2h"
            ),
            None,
        )
        if not market:
            continue
        prices: dict[str, float] = {}
        for outcome in market.get("outcomes") or []:
            if not isinstance(outcome, dict):
                continue
            normalized = normalize_team(outcome.get("name"))
            try:
                price = float(outcome.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if normalized == normalize_team(home_name):
                prices["home"] = price
            elif normalized == normalize_team(away_name):
                prices["away"] = price
            elif normalized in {"draw", "tie"}:
                prices["draw"] = price
        try:
            devigged = devig_decimal_prices(prices)
        except (ValueError, ZeroDivisionError):
            continue
        for key, value in devigged.items():
            samples[key].append(value)
        raw_update = bookmaker.get("last_update")
        if raw_update:
            try:
                update = datetime.fromisoformat(str(raw_update).replace("Z", "+00:00"))
                latest_update = max(latest_update, update) if latest_update else update
            except ValueError:
                pass

    count = min(len(values) for values in samples.values())
    if not count:
        raise ValueError("No complete bookmaker 1X2 markets")
    consensus = {key: statistics.median(values) for key, values in samples.items()}
    total = sum(consensus.values()) or 1.0
    return {key: value / total for key, value in consensus.items()}, count, latest_update


def _match_event(game: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    game = game or {}
    home = normalize_team(game.get("home_team_name_en"))
    away = normalize_team(game.get("away_team_name_en"))
    for event in events:
        if not isinstance(event, dict):
            continue
        event_home = normalize_team(event.get("home_team"))
        event_away = normalize_team(event.get("away_team"))
        if (event_home, event_away) == (home, away):
            return event
    return None


def fetch_market_evidence(games: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    fetched_at = datetime.now(UTC)
    if not settings.odds_api_key:
        return {}
    with httpx.Client(timeout=20) as client:
        response = _get_with_retry(
            client,
            ODDS_URL,
            params={
                "apiKey": settings.odds_api_key,
                "regions": "eu,uk",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
        )
        response.raise_for_status()
        events = response.json() or []
        if not isinstance(events, list):
            return {}

    evidence: dict[str, dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        if not game.get("id"):
            continue
        event = _match_event(game, events)
        if not event:
            continue
        try:
            consensus, bookmaker_count, latest_update = consensus_from_bookmakers(
                event, str(game.get("home_team_name_en")), str(game.get("away_team_name_en"))
            )
        except ValueError:
            continue
        stale = not latest_update or fetched_at - latest_update > timedelta(
            minutes=settings.odds_stale_minutes
        )
        confidence = min(1.0, bookmaker_count / 8)
        evidence[str(game.get("id"))] = {
            "available": True,
            "provider": "The Odds API",
            "provider_event_id": event.get("id"),
            "consensus": {key: round(value * 100, 2) for key, value in consensus.items()},
            "bookmaker_count": bookmaker_count,
            "last_update": latest_update.isoformat() if latest_update else None,
            "stale": stale,
            "source": "the_odds_api",
            "fetched_at": fetched_at.isoformat(),
            "version": settings.model_version,
            "confidence": round(confidence, 2),
            "reason": None,
        }
    return evidence
