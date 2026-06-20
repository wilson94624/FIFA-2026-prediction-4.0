from __future__ import annotations

import math
import random
from datetime import datetime
from typing import Any

MAX_GOALS = 5
GAMMA = 0.08
RHO = -0.05
HOSTS = {"USA", "Mexico", "Canada"}


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def parse_match_date(value: str | None) -> datetime:
    if not value:
        return datetime.max
    for fmt in ("%m/%d/%Y %H:%M", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.max


def _player_is_unavailable(player_name: str, unavailable: list[Any]) -> bool:
    normalized = player_name.casefold().replace(".", " ").split()
    last_name = normalized[-1] if normalized else player_name.casefold()
    for item in unavailable:
        name = str(item.get("name", "")) if isinstance(item, dict) else str(item)
        if last_name in name.casefold() or name.casefold() in player_name.casefold():
            return True
    return False


def active_pqs(
    team: dict[str, Any], unavailable: list[Any] | None = None, fatigue: float = 0.0
) -> tuple[float, float, float]:
    unavailable = unavailable or []
    if not team.get("has_data") or not team.get("players"):
        base = float(team.get("starting_pqs", 0.25))
        return base * (1 - fatigue), base * (1 - fatigue), float(team.get("bench_pqs", 0.2))

    active = [
        player
        for player in team["players"]
        if not _player_is_unavailable(str(player.get("name", "")), unavailable)
    ]
    if not active:
        active = list(team["players"])
    active.sort(key=lambda player: float(player.get("efficiency_score", 0)), reverse=True)
    starters, bench = active[:11], active[11:]
    attackers = [p for p in starters if p.get("position") in {"FW", "MF"}]
    defenders = [p for p in starters if p.get("position") in {"DF", "GK"}]

    fallback = float(team.get("starting_pqs", 0.25))
    attack = (
        sum(float(p.get("efficiency_score", 0)) for p in attackers) / len(attackers)
        if attackers
        else fallback
    )
    defense = (
        sum(float(p.get("efficiency_score", 0)) for p in defenders) / len(defenders)
        if defenders
        else fallback
    )
    bench_score = (
        sum(float(p.get("efficiency_score", 0)) for p in bench) / len(bench) if bench else 0.01
    )
    return attack * (1 - fatigue), defense * (1 - fatigue), bench_score


def fatigue_before(
    team_name: str, match: dict[str, Any], games: list[dict[str, Any]], team: dict[str, Any]
) -> float:
    target_date = parse_match_date(match.get("local_date"))
    bench = float(team.get("bench_pqs", 0.2))
    fatigue = 0.0
    for game in games:
        if game.get("finished") not in {"TRUE", True}:
            continue
        if parse_match_date(game.get("local_date")) >= target_date:
            continue
        if team_name not in {game.get("home_team_name_en"), game.get("away_team_name_en")}:
            continue
        fatigue += 0.04 * (1 - bench)
        if game.get("extra_time"):
            fatigue += 0.02
    return clamp(fatigue, 0.0, 0.35)


def dynamic_elos_before(
    match: dict[str, Any], teams: dict[str, dict[str, Any]], games: list[dict[str, Any]]
) -> dict[str, float]:
    elos = {name: float(team.get("fifa_points", 1500)) for name, team in teams.items()}
    target_date = parse_match_date(match.get("local_date"))
    previous = sorted(
        (
            game
            for game in games
            if game.get("finished") in {"TRUE", True}
            and parse_match_date(game.get("local_date")) < target_date
        ),
        key=lambda game: parse_match_date(game.get("local_date")),
    )
    for game in previous:
        home = game.get("home_team_name_en")
        away = game.get("away_team_name_en")
        if home not in elos or away not in elos:
            continue
        home_score = int(game.get("home_score") or 0)
        away_score = int(game.get("away_score") or 0)
        actual_home = 1.0 if home_score > away_score else 0.0 if home_score < away_score else 0.5
        expected_home = 1 / (1 + 10 ** ((elos[away] - elos[home]) / 400))
        delta = 60 * (actual_home - expected_home)
        elos[home] += delta
        elos[away] -= delta
    return elos


def _apply_style_clash(
    attack_home: float, attack_away: float, style_home: str, style_away: str
) -> tuple[float, float]:
    modifiers = {
        ("Possession", "CounterAttack"): (0.90, 1.10),
        ("CounterAttack", "Possession"): (1.10, 0.90),
        ("HighPress", "Possession"): (1.05, 0.95),
        ("Possession", "HighPress"): (0.95, 1.05),
        ("HighPress", "CounterAttack"): (1.08, 0.92),
        ("CounterAttack", "HighPress"): (0.92, 1.08),
    }
    home_mod, away_mod = modifiers.get((style_home, style_away), (1.0, 1.0))
    return attack_home * home_mod, attack_away * away_mod


def expected_goals(
    home: str,
    away: str,
    home_team: dict[str, Any],
    away_team: dict[str, Any],
    home_elo: float,
    away_elo: float,
    home_fatigue: float,
    away_fatigue: float,
    unavailable_home: list[str] | None = None,
    unavailable_away: list[str] | None = None,
) -> dict[str, float]:
    attack_home, defense_home, _ = active_pqs(home_team, unavailable_home, home_fatigue)
    attack_away, defense_away, _ = active_pqs(away_team, unavailable_away, away_fatigue)
    attack_home, attack_away = _apply_style_clash(
        attack_home,
        attack_away,
        str(home_team.get("style", "Standard")),
        str(away_team.get("style", "Standard")),
    )

    active_home_elo = home_elo * (1 - home_fatigue * 0.05)
    active_away_elo = away_elo * (1 - away_fatigue * 0.05)
    base_home, base_away = 1.2, 1.2
    if home in HOSTS and away not in HOSTS:
        base_home, base_away = 1.3, 1.1
    elif away in HOSTS and home not in HOSTS:
        base_home, base_away = 1.1, 1.3

    elo_diff = active_home_elo - active_away_elo
    normal_home = max(
        0.2, base_home + 0.75 * elo_diff / 450 + 0.20 * (attack_home - defense_away) / 0.3
    )
    normal_away = max(
        0.2, base_away - 0.75 * elo_diff / 450 + 0.20 * (attack_away - defense_home) / 0.3
    )
    domination_home, domination_away = normal_home, normal_away
    if elo_diff > 250:
        domination_home += (elo_diff - 250) * 0.0018
        domination_away = max(0.15, domination_away - (elo_diff - 250) * 0.0005)
    elif elo_diff < -250:
        domination_away += (-elo_diff - 250) * 0.0018
        domination_home = max(0.15, domination_home - (-elo_diff - 250) * 0.0005)
    return {
        "normal_home": normal_home,
        "normal_away": normal_away,
        "domination_home": domination_home,
        "domination_away": domination_away,
        "elo_diff": elo_diff,
        "attack_home": attack_home,
        "attack_away": attack_away,
        "defense_home": defense_home,
        "defense_away": defense_away,
    }


def _poisson_pmf(k: int, rate: float) -> float:
    return rate**k * math.exp(-rate) / math.factorial(k)


def score_matrix(home_rate: float, away_rate: float) -> list[dict[str, float | int]]:
    shared = max(0.0, min(GAMMA, home_rate - 0.01, away_rate - 0.01))
    home_independent = home_rate - shared
    away_independent = away_rate - shared
    scores: list[dict[str, float | int]] = []
    for home_goals in range(MAX_GOALS + 1):
        for away_goals in range(MAX_GOALS + 1):
            probability = 0.0
            for common in range(min(home_goals, away_goals) + 1):
                probability += (
                    _poisson_pmf(home_goals - common, home_independent)
                    * _poisson_pmf(away_goals - common, away_independent)
                    * _poisson_pmf(common, shared)
                )
            if home_goals == 0 and away_goals == 0:
                probability *= 1 - RHO * home_rate * away_rate
            elif home_goals == 1 and away_goals == 1:
                probability *= 1 - RHO
            elif home_goals == 1 and away_goals == 0:
                probability *= 1 + RHO * away_rate
            elif home_goals == 0 and away_goals == 1:
                probability *= 1 + RHO * home_rate
            scores.append(
                {"home": home_goals, "away": away_goals, "probability": max(0.0, probability)}
            )
    total = sum(float(score["probability"]) for score in scores) or 1.0
    for score in scores:
        score["probability"] = float(score["probability"]) / total
    return scores


def mix_matrices(
    normal: list[dict[str, float | int]], domination: list[dict[str, float | int]]
) -> list[dict[str, float | int]]:
    mixed = []
    for normal_score, domination_score in zip(normal, domination, strict=True):
        mixed.append(
            {
                "home": int(normal_score["home"]),
                "away": int(normal_score["away"]),
                "probability": 0.7 * float(normal_score["probability"])
                + 0.3 * float(domination_score["probability"]),
            }
        )
    total = sum(float(score["probability"]) for score in mixed) or 1.0
    for score in mixed:
        score["probability"] = float(score["probability"]) / total
    return mixed


def outcome_probabilities(matrix: list[dict[str, float | int]]) -> dict[str, float]:
    probabilities = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for score in matrix:
        home, away, probability = (
            int(score["home"]),
            int(score["away"]),
            float(score["probability"]),
        )
        key = "home" if home > away else "away" if away > home else "draw"
        probabilities[key] += probability
    return probabilities


def top_scores(matrix: list[dict[str, float | int]]) -> dict[str, list[dict[str, float | int]]]:
    result: dict[str, list[dict[str, float | int]]] = {}
    for outcome in ("home", "draw", "away"):
        candidates = [
            score
            for score in matrix
            if (outcome == "home" and int(score["home"]) > int(score["away"]))
            or (outcome == "draw" and int(score["home"]) == int(score["away"]))
            or (outcome == "away" and int(score["home"]) < int(score["away"]))
        ]
        candidates.sort(key=lambda score: float(score["probability"]), reverse=True)
        result[outcome] = [
            {**score, "probability": round(float(score["probability"]) * 100, 2)}
            for score in candidates[:3]
        ]
    return result


def confidence_level(probabilities: dict[str, float]) -> str:
    maximum = max(probabilities.values()) * 100
    if maximum > 70:
        return "High"
    if maximum >= 55:
        return "Medium"
    return "Low"


def upset_risk(
    probabilities: dict[str, float], total_expected_goals: float, elo_difference: float, stage: str
) -> dict[str, float | str | list[str]]:
    underdog = min(probabilities["home"], probabilities["away"])
    low_goals = clamp((2.8 - total_expected_goals) / 1.8)
    elo_closeness = 1 - clamp(abs(elo_difference) / 600)
    group_factor = 1.0 if stage == "group" else 0.0
    value = 100 * (
        0.30 * probabilities["draw"]
        + 0.30 * underdog
        + 0.15 * low_goals
        + 0.15 * elo_closeness
        + 0.10 * group_factor
    )
    level = "Low" if value < 25 else "Medium" if value <= 40 else "High"
    factors: list[str] = []
    if probabilities["draw"] >= 0.20:
        factors.append("和局機率超過 20%")
    if underdog >= 0.18:
        factors.append("弱勢方仍保有可觀勝率")
    if total_expected_goals < 2.5:
        factors.append("低進球期望放大單一事件影響")
    if abs(elo_difference) < 180:
        factors.append("雙方 ELO 差距有限")
    if stage == "group":
        factors.append("小組賽輪換與策略波動較高")
    return {"value": round(value, 2), "level": level, "factors": factors}


def sample_score(matrix: list[dict[str, float | int]], seed: int) -> tuple[int, int]:
    generator = random.Random(seed)
    draw = generator.random()
    for score in matrix:
        draw -= float(score["probability"])
        if draw <= 0:
            return int(score["home"]), int(score["away"])
    last = matrix[-1]
    return int(last["home"]), int(last["away"])


def predict_match(
    match: dict[str, Any],
    teams: dict[str, dict[str, Any]],
    games: list[dict[str, Any]],
    market_evidence: dict[str, Any] | None = None,
    seed: int = 2026,
) -> dict[str, Any]:
    home, away = match.get("home_team_name_en"), match.get("away_team_name_en")
    if not home or not away or home not in teams or away not in teams:
        raise ValueError(f"Match {match.get('id')} has unresolved teams")

    stats = match.get("stats") or {}
    unavailable = stats.get("unavailable_players") or {"home": [], "away": []}
    home_fatigue = fatigue_before(home, match, games, teams[home])
    away_fatigue = fatigue_before(away, match, games, teams[away])
    elos = dynamic_elos_before(match, teams, games)
    rates = expected_goals(
        home,
        away,
        teams[home],
        teams[away],
        elos[home],
        elos[away],
        home_fatigue,
        away_fatigue,
        list(unavailable.get("home") or []),
        list(unavailable.get("away") or []),
    )
    normal = score_matrix(rates["normal_home"], rates["normal_away"])
    domination = score_matrix(rates["domination_home"], rates["domination_away"])
    matrix = mix_matrices(normal, domination)
    probabilities = outcome_probabilities(matrix)
    expected_home = 0.7 * rates["normal_home"] + 0.3 * rates["domination_home"]
    expected_away = 0.7 * rates["normal_away"] + 0.3 * rates["domination_away"]
    top = top_scores(matrix)
    predicted = max(matrix, key=lambda score: float(score["probability"]))
    risk = upset_risk(
        probabilities,
        expected_home + expected_away,
        rates["elo_diff"],
        str(match.get("type", "group")),
    )

    response: dict[str, Any] = {
        "match_id": str(match.get("id")),
        "home": home,
        "away": away,
        "local_date": match.get("local_date"),
        "stage": match.get("type", "group"),
        "group": match.get("group"),
        "model": {
            "probabilities": {key: round(value * 100, 2) for key, value in probabilities.items()},
            "predicted_score": {
                "home": int(predicted["home"]),
                "away": int(predicted["away"]),
                "probability": round(float(predicted["probability"]) * 100, 2),
            },
            "expected_goals": {"home": round(expected_home, 3), "away": round(expected_away, 3)},
            "score_matrix": [
                {**score, "probability": round(float(score["probability"]) * 100, 4)}
                for score in matrix
            ],
            "top_scores": top,
            "confidence": confidence_level(probabilities),
            "upset_risk": risk,
            "inputs": {
                "elo_difference": round(rates["elo_diff"], 2),
                "fatigue": {"home": round(home_fatigue, 4), "away": round(away_fatigue, 4)},
                "injuries": unavailable,
                "seed": seed,
            },
        },
        "market_evidence": market_evidence
        or {"available": False, "reason": "No fresh market data"},
    }

    consensus = (market_evidence or {}).get("consensus")
    if (market_evidence or {}).get("available") and consensus:
        market = {key: float(consensus[key]) / 100 for key in ("home", "draw", "away")}
        edges = {key: (probabilities[key] - market[key]) * 100 for key in probabilities}
        response["market_evidence"]["value_scores"] = {
            key: round(edge, 2) for key, edge in edges.items()
        }
    return response
