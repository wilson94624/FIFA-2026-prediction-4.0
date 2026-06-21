from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from backend.app import services
from backend.app.analytics import (
    CHAMPIONSHIP_EXPLANATIONS_REQUIRED_TEAM_FIELDS,
    CHAMPIONSHIP_EXPLANATIONS_VERSION,
)
from backend.app.bracket import (
    calculate_group_standings,
    qualified_teams,
    resolve_match_teams,
    resolve_tournament_matches,
)


def _complete_group_data():
    teams = {}
    matches = []
    match_id = 1
    for group in "ABCDEFGHIJKL":
        names = [f"{group}{index}" for index in range(1, 5)]
        for index, name in enumerate(names):
            teams[name] = {"group": group, "fifa_points": 1600 - index}
        for home_index in range(4):
            for away_index in range(home_index + 1, 4):
                # Lower-numbered team always wins, producing deterministic 9/6/3/0 standings.
                matches.append(
                    {
                        "id": str(match_id),
                        "type": "group",
                        "group": group,
                        "home_team_name_en": names[home_index],
                        "away_team_name_en": names[away_index],
                        "home_score": "1",
                        "away_score": "0",
                        "finished": "TRUE",
                    }
                )
                match_id += 1
    return teams, matches


def test_group_rankings_produce_top_two_and_best_thirds():
    teams, matches = _complete_group_data()

    standings, complete = calculate_group_standings(teams, matches)
    top_two, best_thirds = qualified_teams(standings)

    assert complete is True
    assert standings["A"][0]["team"] == "A1"
    assert standings["A"][1]["team"] == "A2"
    assert len(top_two) == 24
    assert len(best_thirds) == 8
    assert all(row["team"].endswith("3") for row in best_thirds)


def test_tournament_payload_derives_from_db_matches_not_legacy_json(monkeypatch):
    teams, matches = _complete_group_data()
    matches.append(
        {
            "id": "73",
            "type": "r32",
            "home_team_name_en": None,
            "away_team_name_en": None,
            "home_team_label": "Runner-up Group A",
            "away_team_label": "Runner-up Group B",
            "finished": "FALSE",
        }
    )
    monkeypatch.setattr(services, "teams_payload", lambda: teams)
    monkeypatch.setattr(services, "all_matches", lambda _session: matches)

    payload = services.tournament_payload(object())
    match = next(item for item in payload["matches"] if item["id"] == "73")

    assert match["home_team_name_en"] == "A2"
    assert match["away_team_name_en"] == "B2"
    assert match["home_team_resolution"] == "derived"
    assert payload["bracket_resolution"]["groups_complete"] is True


def test_api_team_names_override_derived_slots():
    teams, matches = _complete_group_data()
    matches.append(
        {
            "id": "73",
            "type": "r32",
            "home_team_name_en": "D1",
            "away_team_name_en": "E2",
            "home_team_label": "Runner-up Group A",
            "away_team_label": "Runner-up Group B",
            "finished": "FALSE",
        }
    )

    resolved, _ = resolve_tournament_matches(teams, matches)
    match = next(item for item in resolved if item["id"] == "73")

    assert (match["home_team_name_en"], match["away_team_name_en"]) == ("D1", "E2")
    assert "home_team_resolution" not in match


def test_later_round_uses_winner_match_source_ids():
    match = {
        "id": "89",
        "type": "r16",
        "home_team_label": "Winner Match 74",
        "away_team_label": "Winner Match 77",
    }

    home, away = resolve_match_teams(
        match,
        standings={},
        third_assignments={},
        winners={"74": "E1", "77": "I1"},
    )

    assert (home, away) == ("E1", "I1")


def test_simulation_pipeline_uses_latest_database_matches(monkeypatch):
    latest_db_games = [
        {
            "id": "db-finished",
            "type": "group",
            "home_team_name_en": "A",
            "away_team_name_en": "B",
            "home_score": "2",
            "away_score": "0",
            "finished": "TRUE",
        }
    ]
    snapshot = SimpleNamespace(payload={}, source="", fetched_at=None, confidence=0.0)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def scalar(self, _query):
            return snapshot

        def add(self, _record):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(services, "SessionLocal", FakeSession)
    monkeypatch.setattr(services, "raw_matches", lambda _session: latest_db_games)
    monkeypatch.setattr(services, "record_metric", lambda *_args, **_kwargs: None)

    from backend import player_level_simulator as legacy

    seen = {}
    monkeypatch.setattr(
        legacy,
        "load_teams",
        lambda: {"A": {"has_data": False}, "B": {"has_data": False}},
    )
    monkeypatch.setattr(
        legacy,
        "load_real_games",
        Mock(side_effect=AssertionError("legacy JSON/database loader must not be called")),
    )

    def boost(teams, games):
        seen["boost_games"] = games
        return teams

    def simulate(_teams, games, lookup, shortcuts, active_pqs_cache):
        seen["simulation_games"] = games
        seen["simulation_lookup"] = lookup
        seen["simulation_shortcuts"] = shortcuts
        seen["active_pqs_cache"] = active_pqs_cache
        return {
            "R32": ["A", "B"],
            "R16": ["A"],
            "QF": ["A"],
            "SF": ["A"],
            "Final": ["A"],
            "Winner": "A",
        }

    monkeypatch.setattr(legacy, "apply_real_performance_boost", boost)
    monkeypatch.setattr(legacy, "simulate_tournament_once", simulate)

    result = services.run_simulation_pipeline(lambda *_args: None)

    assert result == {"runs": 10_000, "teams": 2}
    assert seen["boost_games"] is latest_db_games
    assert seen["simulation_games"] is latest_db_games
    assert seen["simulation_lookup"]["finished"]
    assert seen["simulation_shortcuts"]
    assert isinstance(seen["active_pqs_cache"], dict)
    assert snapshot.source == "backend_monte_carlo"
    assert snapshot.payload["explanations"]["generated_by"] == "rules"
    assert snapshot.payload["explanations_version"] == CHAMPIONSHIP_EXPLANATIONS_VERSION
    assert snapshot.payload["explanations"]["version"] == CHAMPIONSHIP_EXPLANATIONS_VERSION
    top_team = snapshot.payload["explanations"]["teams"][0]
    assert CHAMPIONSHIP_EXPLANATIONS_REQUIRED_TEAM_FIELDS.issubset(top_team)
    assert top_team["ranking_summary"]
    assert top_team["threat_label"] == "可能卡關對手"
    assert top_team["team_name"] == "A"
    assert snapshot.payload["input_hash"] == services.simulation_input_hash_for_data(
        latest_db_games,
        {"A": {"has_data": False}, "B": {"has_data": False}},
        legacy.SIMULATOR_INPUT_VERSION,
    )
    assert snapshot.payload["input_hash"] == services.simulation_input_hash(object())
