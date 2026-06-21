from datetime import UTC, datetime
from types import SimpleNamespace

from backend.app import services
from backend.app.analytics import (
    CHAMPIONSHIP_EXPLANATIONS_REQUIRED_TEAM_FIELDS,
    CHAMPIONSHIP_EXPLANATIONS_VERSION,
    championship_explanations,
    validate_championship_explanations,
)


def _row(name, r32, r16, qf, sf, final, winner):
    return {
        "team_name": name,
        "R32_pct": r32,
        "R16_pct": r16,
        "QF_pct": qf,
        "SF_pct": sf,
        "Final_pct": final,
        "Winner_pct": winner,
    }


def test_championship_explanations_include_top_five_and_exit_round():
    probabilities = [
        _row("A", 90, 70, 45, 25, 15, 8),
        _row("B", 95, 75, 50, 30, 18, 7),
        _row("C", 92, 72, 47, 27, 16, 6),
        _row("D", 88, 68, 43, 23, 13, 5),
        _row("E", 86, 66, 41, 21, 12, 4),
        _row("F", 84, 64, 39, 19, 10, 3),
    ]
    teams = {
        name: {"fifa_points": 2000 - index * 20, "starting_pqs": 0.35 - index * 0.01}
        for index, name in enumerate("ABCDEF")
    }

    payload = championship_explanations(probabilities, teams)

    assert payload["generated_by"] == "rules"
    assert payload["version"] == CHAMPIONSHIP_EXPLANATIONS_VERSION
    assert payload["threat_basis"] == "top_championship_probability"
    assert len(payload["teams"]) == 5
    leader = payload["teams"][0]
    assert leader["team_name"] == "A"
    assert leader["most_likely_exit_round"] == "十六強"
    assert leader["key_risk_round"] == "十六強晉級八強"
    assert leader["choke_point_drop_pp"] == 25
    assert leader["biggest_threat_teams"] == ["B", "C"]
    assert leader["threat_label"] == "可能卡關對手"
    assert leader["threat_note"] == "依奪冠率與潛在路徑推估"
    assert leader["comparison_target"] == "B"
    assert leader["comparison_delta"]["championship_probability"] == 1
    assert CHAMPIONSHIP_EXPLANATIONS_REQUIRED_TEAM_FIELDS.issubset(leader)
    assert leader["ranking_summary"]
    assert leader["ranking_factors"]
    assert 2 <= len(leader["reason_bullets"]) <= 3
    assert leader["path_difficulty_label"] in {"路徑偏順", "路徑中等", "路徑艱難"}
    summaries = [team["ranking_summary"] for team in payload["teams"][:3]]
    assert len(set(summaries)) == 3
    assert all("奪冠率排名前 3" not in bullet for team in payload["teams"] for bullet in team["reason_bullets"])


def test_championship_explanations_handle_empty_snapshot():
    payload = championship_explanations([], {})

    assert payload["teams"] == []
    assert payload["version"] == CHAMPIONSHIP_EXPLANATIONS_VERSION


def test_championship_payload_advertises_current_version_for_legacy_snapshot():
    record = SimpleNamespace(
        payload={
            "probabilities": [],
            "explanations": {"version": "championship-explanations-v1"},
        },
        source="backend_monte_carlo",
        confidence=0.9,
        fetched_at=datetime(2026, 6, 21, tzinfo=UTC),
    )

    class FakeSession:
        def scalar(self, _query):
            return record

    payload = services.championship_payload(FakeSession())

    assert payload["explanations_version"] == CHAMPIONSHIP_EXPLANATIONS_VERSION
    assert payload["explanations"]["version"] == "championship-explanations-v1"


def test_v2_builder_output_satisfies_snapshot_contract():
    probabilities = [
        _row("A", 90, 70, 45, 25, 15, 8),
        _row("B", 95, 75, 50, 30, 18, 7),
        _row("C", 92, 72, 47, 27, 16, 6),
        _row("D", 88, 68, 43, 23, 13, 5),
        _row("E", 86, 66, 41, 21, 12, 4),
    ]
    teams = {
        name: {"fifa_points": 2000 - index * 20, "starting_pqs": 0.35 - index * 0.01}
        for index, name in enumerate("ABCDE")
    }

    validate_championship_explanations(championship_explanations(probabilities, teams))
