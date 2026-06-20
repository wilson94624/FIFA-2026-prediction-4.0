from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .engine import parse_match_date

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Referer": "https://www.fotmob.com/",
    "Accept": "application/json, text/plain, */*",
}
ALIASES = {"Cabo Verde": "Cape Verde", "Congo DR": "DR Congo", "Turkey": "Turkiye"}
logger = logging.getLogger(__name__)
PRIMARY_STATS = ("xgA", "xgB", "possessionA", "possessionB", "shotsA", "shotsB")
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
            logger.warning("FotMob request failed; retrying (%s/3): %s", attempt + 1, url)
            time.sleep(0.25 * (2**attempt))
    raise RuntimeError("unreachable")


def _as_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("%", ""))
    except ValueError:
        return None


def _team_matches(candidate: str | None, expected: str) -> bool:
    if not candidate:
        return False
    left = candidate.casefold().replace(" ", "")
    right = ALIASES.get(expected, expected).casefold().replace(" ", "")
    return left == right or left in right or right in left


def _search_dates(local_date: str | None) -> list[str]:
    parsed = parse_match_date(local_date)
    if parsed == datetime.max:
        return []
    return [(parsed + timedelta(days=offset)).strftime("%Y%m%d") for offset in (0, 1, -1)]


def _find_match(client: httpx.Client, game: dict[str, Any]) -> tuple[str | None, bool]:
    game = game or {}
    home = str(game.get("home_team_name_en") or "")
    away = str(game.get("away_team_name_en") or "")
    for date in _search_dates(game.get("local_date")):
        response = _get_with_retry(
            client,
            "https://www.fotmob.com/api/data/matches", params={"date": date}, headers=HEADERS
        )
        if response.status_code != 200:
            continue
        payload = response.json() or {}
        if not isinstance(payload, dict):
            continue
        for league in payload.get("leagues") or []:
            if not isinstance(league, dict):
                continue
            for match in league.get("matches") or []:
                if not isinstance(match, dict):
                    continue
                match_home = (match.get("home") or {}).get("name")
                match_away = (match.get("away") or {}).get("name")
                if _team_matches(match_home, home) and _team_matches(match_away, away):
                    return str(match.get("id")), False
                if _team_matches(match_home, away) and _team_matches(match_away, home):
                    return str(match.get("id")), True
    return None, False


def _stat_pairs(detail: dict[str, Any]) -> dict[str, list[Any]]:
    content = (detail or {}).get("content") or {}
    stats = content.get("stats") or {}
    periods = stats.get("Periods") or {}
    all_periods = periods.get("All") or {}
    sections = all_periods.get("stats") or []
    result: dict[str, list[Any]] = {}
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict):
            continue
        for item in section.get("stats") or []:
            if not isinstance(item, dict):
                continue
            values = item.get("stats")
            if isinstance(values, list) and len(values) >= 2:
                result[str(item.get("title", "")).casefold()] = values
    return result


def _find_stat(stats: dict[str, list[Any]], *names: str) -> list[Any] | None:
    for title, values in stats.items():
        if any(name in title for name in names):
            return values
    return None


def has_complete_primary_stats(stats: dict[str, Any] | None) -> bool:
    stats = stats or {}
    return all(stats.get(key) is not None for key in PRIMARY_STATS)


def with_fotmob_status(stats: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(stats)
    complete = has_complete_primary_stats(normalized)
    has_any_primary = any(normalized.get(key) is not None for key in PRIMARY_STATS)
    normalized["fotmob_complete"] = complete
    normalized["fotmob_status"] = (
        "complete" if complete else "partial" if has_any_primary else "pending"
    )
    return normalized


def _card_totals(
    yellow: list[Any] | None, red: list[Any] | None
) -> list[float | None]:
    totals: list[float | None] = []
    for index in range(2):
        values = [
            number
            for pair in (yellow, red)
            if pair is not None and (number := _as_number(pair[index])) is not None
        ]
        totals.append(sum(values) if values else None)
    return totals


def _parse_unavailable(lineup: dict[str, Any], side: str) -> list[dict[str, str]]:
    lineup = lineup or {}
    side_payload = lineup.get(side) or {}
    unavailable = side_payload.get("unavailable") or [] if isinstance(side_payload, dict) else []
    result = []
    for player in unavailable:
        if not isinstance(player, dict) or not player.get("name"):
            continue
        detail = player.get("unavailability") or {}
        result.append({"name": str(player["name"]), "type": str(detail.get("type", "injury"))})
    return result


def _event_summary(detail: dict[str, Any]) -> dict[str, Any]:
    content = (detail or {}).get("content") or {}
    facts = content.get("matchFacts") or {}
    event_group = facts.get("events") or {}
    events = event_group.get("events") or [] if isinstance(event_group, dict) else []
    substitutions = []
    injury_events = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type", event.get("eventType", ""))).casefold()
        if "sub" in event_type:
            substitutions.append(event)
        if "injur" in event_type:
            injury_events.append(event)
    return {"substitutions": substitutions, "injury_events": injury_events}


def _parse_match_stats(
    detail: dict[str, Any], match_id: str, reversed_teams: bool = False
) -> dict[str, Any]:
    stats = _stat_pairs(detail)
    possession = _find_stat(stats, "ball possession") or [None, None]
    shots = _find_stat(stats, "total shots") or [None, None]
    fouls = _find_stat(stats, "fouls committed", "fouls") or [None, None]
    xg = _find_stat(stats, "expected goals", "xg") or [None, None]
    yellow = _find_stat(stats, "yellow cards")
    red = _find_stat(stats, "red cards")
    cards = _card_totals(yellow, red)
    content = detail.get("content") or {}
    lineup = content.get("lineup") or {} if isinstance(content, dict) else {}
    unavailable = {
        "home": _parse_unavailable(lineup, "homeTeam"),
        "away": _parse_unavailable(lineup, "awayTeam"),
    }
    events = _event_summary(detail)

    pairs = [possession, shots, fouls, xg, cards]
    if reversed_teams:
        for pair in pairs:
            pair[0], pair[1] = pair[1], pair[0]
        unavailable = {"home": unavailable["away"], "away": unavailable["home"]}

    return with_fotmob_status({
        "possessionA": _as_number(possession[0]),
        "possessionB": _as_number(possession[1]),
        "shotsA": _as_number(shots[0]),
        "shotsB": _as_number(shots[1]),
        "foulsA": _as_number(fouls[0]),
        "foulsB": _as_number(fouls[1]),
        "xgA": _as_number(xg[0]),
        "xgB": _as_number(xg[1]),
        "cardsA": cards[0],
        "cardsB": cards[1],
        "substitutions": events["substitutions"],
        "injury_events": events["injury_events"],
        "unavailable_players": unavailable,
        "fotmob_match_id": match_id,
        "fotmob_fetched_at": datetime.now(UTC).isoformat(),
    })


def fetch_match_stats(game: dict[str, Any]) -> dict[str, Any] | None:
    game = game or {}
    with httpx.Client(timeout=12) as client:
        match_id, reversed_teams = _find_match(client, game)
        if not match_id:
            return None
        response = _get_with_retry(
            client,
            "https://www.fotmob.com/api/data/matchDetails",
            params={"matchId": match_id},
            headers=HEADERS,
        )
        if response.status_code != 200:
            return None
        detail = response.json() or {}
        if not isinstance(detail, dict):
            return None

    return _parse_match_stats(detail, match_id, reversed_teams)
