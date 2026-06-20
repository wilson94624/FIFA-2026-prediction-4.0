import json
from pathlib import Path

import pytest

from backend.app.engine import (
    confidence_level,
    mix_matrices,
    outcome_probabilities,
    predict_match,
    sample_score,
    score_matrix,
    upset_risk,
)

ROOT = Path(__file__).resolve().parents[2]


def test_score_matrix_and_domination_mix_are_normalized():
    normal = score_matrix(1.4, 1.0)
    domination = score_matrix(2.1, 0.7)
    mixed = mix_matrices(normal, domination)
    assert len(mixed) == 36
    assert sum(item["probability"] for item in mixed) == pytest.approx(1.0)
    assert outcome_probabilities(mixed).values()


@pytest.mark.parametrize(
    ("maximum", "expected"),
    [(0.5499, "Low"), (0.55, "Medium"), (0.70, "Medium"), (0.7001, "High")],
)
def test_confidence_boundaries(maximum, expected):
    remainder = (1 - maximum) / 2
    assert confidence_level({"home": maximum, "draw": remainder, "away": remainder}) == expected


def test_upset_risk_formula_and_labels():
    low = upset_risk({"home": 0.85, "draw": 0.10, "away": 0.05}, 3.4, 500, "final")
    high = upset_risk({"home": 0.42, "draw": 0.31, "away": 0.27}, 1.8, 40, "group")
    assert low["level"] == "Low"
    assert high["level"] == "High"


def test_prediction_is_reproducible_and_keeps_full_score_outputs():
    teams = json.loads((ROOT / "frontend/src/teams_db.json").read_text())
    games = json.loads((ROOT / "frontend/src/real_games_results.json").read_text())
    match = next(
        game
        for game in games
        if game.get("home_team_name_en") in teams
        and game.get("away_team_name_en") in teams
        and game.get("finished") == "FALSE"
    )
    first = predict_match(match, teams, games, seed=77)
    second = predict_match(match, teams, games, seed=77)
    assert first == second
    market_prediction = predict_match(
        match,
        teams,
        games,
        {
            "available": True,
            "consensus": {"home": 45, "draw": 30, "away": 25},
        },
        seed=77,
    )
    assert "market_fused" not in market_prediction
    assert market_prediction["market_evidence"]["value_scores"]
    assert len(first["model"]["score_matrix"]) == 36
    assert all(len(first["model"]["top_scores"][key]) == 3 for key in ("home", "draw", "away"))
    matrix = [
        {**score, "probability": score["probability"] / 100}
        for score in first["model"]["score_matrix"]
    ]
    assert sample_score(matrix, 12) == sample_score(matrix, 12)
