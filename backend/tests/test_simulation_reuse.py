from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app import jobs, services
from backend.app.analytics import CHAMPIONSHIP_EXPLANATIONS_VERSION


class FakeSession:
    def __init__(self, scalar_results):
        self.scalar_results = iter(scalar_results)
        self.added = []
        self.commits = 0

    def scalar(self, _query):
        return next(self.scalar_results)

    def add(self, record):
        self.added.append(record)

    def commit(self):
        self.commits += 1

    def refresh(self, _record):
        return None


def _input_fixture():
    games = [
        {
            "id": "73",
            "type": "r32",
            "group": None,
            "local_date": "2026-06-28T15:00:00Z",
            "home_team_name_en": "A",
            "away_team_name_en": "B",
            "home_team_label": "Winner Group A",
            "away_team_label": "3rd Group C/D/E/F",
            "finished": "TRUE",
            "home_score": "1",
            "away_score": "1",
            "winner_team_name_en": "A",
            "home_penalty_score": 5,
            "away_penalty_score": 4,
            "stats": {
                "unavailable_players": {
                    "home": [{"name": "A Player"}],
                    "away": [],
                },
                "xg": [1.2, 0.8],
            },
        }
    ]
    teams = {
        "A": {
            "group": "A",
            "fifa_points": 1800,
            "players": [{"name": "A Player", "overall": 85, "efficiency_score": 0.8}],
        },
        "B": {"group": "B", "fifa_points": 1700, "players": []},
    }
    return games, teams


def test_simulation_input_hash_is_canonical_and_tracks_relevant_inputs():
    games, teams = _input_fixture()
    baseline = services.simulation_input_hash_for_data(games, teams, "sim-v1")
    reordered_teams = {"B": teams["B"], "A": teams["A"]}

    assert services.simulation_input_hash_for_data(games, reordered_teams, "sim-v1") == baseline

    mutations = []
    for path, value in (
        (("game", "home_score"), "2"),
        (("game", "home_team_label"), "Runner-up Group A"),
        (("game", "home_penalty_score"), 6),
        (("unavailable",), [{"name": "Different Player"}]),
        (("team", "fifa_points"), 1801),
    ):
        changed_games = deepcopy(games)
        changed_teams = deepcopy(teams)
        if path[0] == "game":
            changed_games[0][path[1]] = value
        elif path[0] == "unavailable":
            changed_games[0]["stats"]["unavailable_players"]["home"] = value
        else:
            changed_teams["A"][path[1]] = value
        mutations.append(services.simulation_input_hash_for_data(changed_games, changed_teams, "sim-v1"))

    assert all(value != baseline for value in mutations)
    assert services.simulation_input_hash_for_data(games, teams, "sim-v2") != baseline

    irrelevant_stats = deepcopy(games)
    irrelevant_stats[0]["stats"]["xg"] = [9.0, 9.0]
    assert services.simulation_input_hash_for_data(irrelevant_stats, teams, "sim-v1") == baseline


def test_matching_snapshot_returns_completed_reused_job_without_submit(monkeypatch):
    from backend import player_level_simulator as legacy

    games, teams = _input_fixture()
    expected_hash = services.simulation_input_hash_for_data(
        games, teams, legacy.SIMULATOR_INPUT_VERSION
    )
    snapshot = SimpleNamespace(
        payload={
            "input_hash": expected_hash,
            "last_updated": "2026-06-21T00:00:00Z",
            "explanations": {"version": CHAMPIONSHIP_EXPLANATIONS_VERSION},
        }
    )
    session = FakeSession([None, snapshot])
    submit = Mock()
    monkeypatch.setattr(services, "raw_matches", lambda _session: games)
    monkeypatch.setattr(legacy, "load_teams", lambda: teams)
    monkeypatch.setattr(jobs.executor, "submit", submit)

    payload, reused = jobs.create_or_reuse_job(session, "simulation")

    assert reused is True
    assert payload["status"] == "completed"
    assert payload["stage"] == "snapshot_reused"
    assert session.added[0].job_type == "simulation"
    submit.assert_not_called()


def test_snapshot_metadata_does_not_affect_reuse(monkeypatch):
    from backend import player_level_simulator as legacy

    games, teams = _input_fixture()
    input_hash = services.simulation_input_hash_for_data(
        games, teams, legacy.SIMULATOR_INPUT_VERSION
    )
    monkeypatch.setattr(services, "raw_matches", lambda _session: games)
    monkeypatch.setattr(legacy, "load_teams", lambda: teams)
    submit = Mock()
    monkeypatch.setattr(jobs.executor, "submit", submit)

    for snapshot_payload in (
        {
            "input_hash": input_hash,
            "last_updated": "2026-06-21T00:00:00Z",
            "probabilities": [{"team_name": "A", "Winner_pct": 10.0}],
            "explanations": {"version": CHAMPIONSHIP_EXPLANATIONS_VERSION},
        },
        {
            "input_hash": input_hash,
            "last_updated": "2030-01-01T00:00:00Z",
            "probabilities": [{"team_name": "A", "Winner_pct": 99.0}],
            "metadata": {"source": "changed"},
            "explanations": {
                "version": CHAMPIONSHIP_EXPLANATIONS_VERSION,
                "generated_by": "rules",
                "teams": [{"team_name": "A"}],
            },
        },
    ):
        original_payload = dict(snapshot_payload)
        snapshot = SimpleNamespace(payload=snapshot_payload)
        payload, reused = jobs.create_or_reuse_job(
            FakeSession([None, snapshot]), "simulation"
        )
        assert reused is True
        assert payload["stage"] == "snapshot_reused"
        assert snapshot.payload == original_payload

    submit.assert_not_called()


@pytest.mark.parametrize(
    "explanations",
    [None, {"version": "championship-explanations-v1"}],
    ids=["missing", "outdated"],
)
def test_matching_hash_without_current_explanations_creates_simulation_job(
    monkeypatch, explanations
):
    snapshot_payload = {"input_hash": "current-hash"}
    if explanations is not None:
        snapshot_payload["explanations"] = explanations
    snapshot = SimpleNamespace(payload=snapshot_payload)
    session = FakeSession([None, snapshot])
    submit = Mock()
    monkeypatch.setattr(jobs, "simulation_input_hash", lambda _session: "current-hash")
    monkeypatch.setattr(jobs.executor, "submit", submit)

    payload, reused = jobs.create_or_reuse_job(session, "simulation")

    assert reused is False
    assert payload["status"] == "queued"
    assert payload["stage"] == "queued"
    submit.assert_called_once()


def test_changed_input_creates_heavy_simulation_job(monkeypatch):
    snapshot = SimpleNamespace(payload={"input_hash": "old-hash"})
    session = FakeSession([None, snapshot])
    submit = Mock()
    monkeypatch.setattr(jobs, "simulation_input_hash", lambda _session: "new-hash")
    monkeypatch.setattr(jobs.executor, "submit", submit)

    payload, reused = jobs.create_or_reuse_job(session, "simulation")

    assert reused is False
    assert payload["status"] == "queued"
    submit.assert_called_once()


def test_active_simulation_job_is_reused_before_hash_check(monkeypatch):
    active = SimpleNamespace(
        id="active-job",
        job_type="simulation",
        status="running",
        progress=42,
        stage="simulation",
        message="running",
        error=None,
        created_at=None,
        updated_at=None,
    )
    session = FakeSession([active])
    hash_check = Mock(side_effect=AssertionError("hash should not run for an active job"))
    monkeypatch.setattr(jobs, "simulation_input_hash", hash_check)

    payload, reused = jobs.create_or_reuse_job(session, "simulation")

    assert reused is True
    assert payload["job_id"] == "active-job"
    hash_check.assert_not_called()


@pytest.mark.parametrize("snapshot_payload", [{}, None])
def test_snapshot_without_hash_does_not_reuse(monkeypatch, snapshot_payload):
    snapshot = SimpleNamespace(payload=snapshot_payload) if snapshot_payload is not None else None
    session = FakeSession([None, snapshot])
    monkeypatch.setattr(jobs, "simulation_input_hash", lambda _session: "current-hash")
    monkeypatch.setattr(jobs.executor, "submit", Mock())

    payload, reused = jobs.create_or_reuse_job(session, "simulation")

    assert reused is False
    assert payload["status"] == "queued"
