from __future__ import annotations

import copy
import re
from typing import Any

GROUPS = tuple("ABCDEFGHIJKL")
KNOCKOUT_STAGES = ("r32", "r16", "qf", "sf", "final")


def _finished(match: dict[str, Any]) -> bool:
    return match.get("finished") in {"TRUE", True}


def _match_number(match: dict[str, Any]) -> tuple[int, str]:
    value = str(match.get("id", ""))
    return (int(value), value) if value.isdigit() else (10_000, value)


def calculate_group_standings(
    teams: dict[str, dict[str, Any]], matches: list[dict[str, Any]]
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    """Calculate standings from completed DB matches and report whether all groups are complete."""
    standings: dict[str, list[dict[str, Any]]] = {}
    all_complete = True
    for group in GROUPS:
        group_teams = [name for name, team in teams.items() if team.get("group") == group]
        rows = {
            name: {
                "team": name,
                "played": 0,
                "points": 0,
                "gd": 0,
                "gs": 0,
                "elo": float(teams[name].get("fifa_points") or 0),
                "group": group,
            }
            for name in group_teams
        }
        for match in matches:
            if match.get("type") != "group" or match.get("group") != group or not _finished(match):
                continue
            home = match.get("home_team_name_en")
            away = match.get("away_team_name_en")
            if home not in rows or away not in rows:
                continue
            home_score = int(match.get("home_score") or 0)
            away_score = int(match.get("away_score") or 0)
            rows[home]["played"] += 1
            rows[away]["played"] += 1
            rows[home]["gs"] += home_score
            rows[away]["gs"] += away_score
            rows[home]["gd"] += home_score - away_score
            rows[away]["gd"] += away_score - home_score
            if home_score > away_score:
                rows[home]["points"] += 3
            elif away_score > home_score:
                rows[away]["points"] += 3
            else:
                rows[home]["points"] += 1
                rows[away]["points"] += 1
        standings[group] = sorted(
            rows.values(),
            key=lambda row: (row["points"], row["gd"], row["gs"], row["elo"]),
            reverse=True,
        )
        expected_played = max(0, len(group_teams) - 1)
        if len(group_teams) != 4 or any(row["played"] != expected_played for row in rows.values()):
            all_complete = False
    return standings, all_complete


def qualified_teams(
    standings: dict[str, list[dict[str, Any]]]
) -> tuple[list[str], list[dict[str, Any]]]:
    top_two = [row["team"] for group in GROUPS for row in standings.get(group, [])[:2]]
    thirds = [rows[2] for group in GROUPS if len(rows := standings.get(group, [])) >= 3]
    best_thirds = sorted(
        thirds,
        key=lambda row: (row["points"], row["gd"], row["gs"], row["elo"]),
        reverse=True,
    )[:8]
    return top_two, best_thirds


def _third_candidates(label: str | None) -> set[str]:
    match = re.fullmatch(r"3rd Group ([A-L/]+)", label or "", re.IGNORECASE)
    return set(match.group(1).upper().split("/")) if match else set()


def assign_best_thirds(
    r32_matches: list[dict[str, Any]], best_thirds: list[dict[str, Any]]
) -> tuple[dict[str, str], bool]:
    """Assign third-place teams to API template slots.

    TODO: replace this constraint fallback with FIFA's complete combination lookup table once
    the authoritative 2026 table is published in a stable machine-readable form.
    """
    team_by_group = {row["group"]: row["team"] for row in best_thirds}
    slots: list[tuple[str, set[str]]] = []
    for match in r32_matches:
        for side in ("home", "away"):
            candidates = _third_candidates(match.get(f"{side}_team_label"))
            if candidates:
                slots.append((f"{match.get('id')}:{side}", candidates & team_by_group.keys()))
    slots.sort(key=lambda item: (len(item[1]), item[0]))
    assignment: dict[str, str] = {}

    def search(index: int, used: set[str]) -> bool:
        if index == len(slots):
            return True
        slot, candidates = slots[index]
        for group in sorted(candidates - used):
            assignment[slot] = team_by_group[group]
            if search(index + 1, used | {group}):
                return True
            assignment.pop(slot, None)
        return False

    complete = len(slots) == 8 and len(team_by_group) == 8 and search(0, set())
    if complete:
        return assignment, True

    # Explicitly provisional fallback: use only eligible, unused groups where possible.
    assignment.clear()
    unused = set(team_by_group)
    for slot, candidates in slots:
        group = next(iter(sorted(candidates & unused)), None)
        if group is not None:
            assignment[slot] = team_by_group[group]
            unused.remove(group)
    return assignment, False


def completed_match_winner(match: dict[str, Any]) -> str | None:
    if not _finished(match):
        return None
    explicit = match.get("winner_team_name_en") or match.get("winner")
    if explicit:
        return explicit
    home_score = int(match.get("home_score") or 0)
    away_score = int(match.get("away_score") or 0)
    if home_score > away_score:
        return match.get("home_team_name_en")
    if away_score > home_score:
        return match.get("away_team_name_en")
    return None


def resolve_slot(
    label: str | None,
    *,
    side_key: str,
    standings: dict[str, list[dict[str, Any]]],
    third_assignments: dict[str, str],
    winners: dict[str, str],
) -> str | None:
    if not label:
        return None
    match = re.fullmatch(r"Winner Group ([A-L])", label, re.IGNORECASE)
    if match:
        rows = standings.get(match.group(1).upper(), [])
        return rows[0]["team"] if rows else None
    match = re.fullmatch(r"Runner-up Group ([A-L])", label, re.IGNORECASE)
    if match:
        rows = standings.get(match.group(1).upper(), [])
        return rows[1]["team"] if len(rows) > 1 else None
    if _third_candidates(label):
        return third_assignments.get(side_key)
    match = re.fullmatch(r"Winner Match (\d+)", label, re.IGNORECASE)
    if match:
        return winners.get(match.group(1))
    return None


def resolve_match_teams(
    match: dict[str, Any],
    standings: dict[str, list[dict[str, Any]]],
    third_assignments: dict[str, str],
    winners: dict[str, str],
) -> tuple[str | None, str | None]:
    match_id = str(match.get("id"))
    home = match.get("home_team_name_en") or resolve_slot(
        match.get("home_team_label"),
        side_key=f"{match_id}:home",
        standings=standings,
        third_assignments=third_assignments,
        winners=winners,
    )
    away = match.get("away_team_name_en") or resolve_slot(
        match.get("away_team_label"),
        side_key=f"{match_id}:away",
        standings=standings,
        third_assignments=third_assignments,
        winners=winners,
    )
    return home, away


def resolve_tournament_matches(
    teams: dict[str, dict[str, Any]], matches: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved = copy.deepcopy(matches)
    standings, groups_complete = calculate_group_standings(teams, resolved)
    if not groups_complete:
        return resolved, {"groups_complete": False, "third_place_mapping_complete": False}

    _, best_thirds = qualified_teams(standings)
    r32 = [match for match in resolved if match.get("type") == "r32"]
    third_assignments, mapping_complete = assign_best_thirds(r32, best_thirds)
    winners: dict[str, str] = {}
    for match in sorted(resolved, key=_match_number):
        if match.get("type") not in KNOCKOUT_STAGES:
            continue
        home, away = resolve_match_teams(match, standings, third_assignments, winners)
        if not match.get("home_team_name_en") and home:
            match["home_team_name_en"] = home
            match["home_team_resolution"] = "derived"
        if not match.get("away_team_name_en") and away:
            match["away_team_name_en"] = away
            match["away_team_resolution"] = "derived"
        winner = completed_match_winner(match)
        if winner:
            winners[str(match.get("id"))] = winner
    return resolved, {
        "groups_complete": True,
        "third_place_mapping_complete": mapping_complete,
        "third_place_mapping": "api_slot_constraints_fallback",
    }
