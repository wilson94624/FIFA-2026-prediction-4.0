from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

OUTCOMES = ("home", "draw", "away")
CHAMPIONSHIP_EXPLANATIONS_VERSION = "championship-explanations-v2"
CHAMPIONSHIP_ROUNDS = (
    ("小組賽出線", "小組賽", 100.0, "R32_pct"),
    ("三十二強晉級十六強", "三十二強", "R32_pct", "R16_pct"),
    ("十六強晉級八強", "十六強", "R16_pct", "QF_pct"),
    ("八強晉級四強", "八強", "QF_pct", "SF_pct"),
    ("四強晉級決賽", "四強", "SF_pct", "Final_pct"),
    ("決賽奪冠", "決賽", "Final_pct", "Winner_pct"),
)
CHAMPIONSHIP_COMPARISON_METRICS = (
    ("quarterfinal_probability", "QF_pct", "八強率"),
    ("semifinal_probability", "SF_pct", "四強率"),
    ("final_probability", "Final_pct", "決賽率"),
)
CHAMPIONSHIP_EXPLANATIONS_REQUIRED_TEAM_FIELDS = frozenset(
    {
        "ranking_summary",
        "comparison_target",
        "comparison_delta",
        "ranking_factors",
        "key_risk_round",
        "choke_point_drop_pp",
        "threat_label",
        "threat_note",
    }
)


def championship_explanations_are_current(explanations: Any) -> bool:
    return (
        isinstance(explanations, dict)
        and explanations.get("version") == CHAMPIONSHIP_EXPLANATIONS_VERSION
    )


def validate_championship_explanations(explanations: Any) -> None:
    if not championship_explanations_are_current(explanations):
        raise ValueError(
            "Championship explanations version mismatch: "
            f"expected {CHAMPIONSHIP_EXPLANATIONS_VERSION}"
        )
    teams = explanations.get("teams")
    if not isinstance(teams, list) or not teams:
        raise ValueError("Championship explanations must contain team metadata")
    for team in teams:
        missing = CHAMPIONSHIP_EXPLANATIONS_REQUIRED_TEAM_FIELDS.difference(team)
        if missing:
            raise ValueError(
                "Championship explanations team metadata is incomplete: "
                f"{', '.join(sorted(missing))}"
            )
        if team.get("threat_label") != "可能卡關對手":
            raise ValueError("Championship explanations threat label is outdated")


def actual_outcome(match: dict[str, Any]) -> str:
    home = int(match.get("home_score") or 0)
    away = int(match.get("away_score") or 0)
    return "home" if home > away else "away" if away > home else "draw"


def calculate_backtest(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    if not rows:
        return {
            "sample_size": 0,
            "accuracy_1x2": None,
            "log_loss": None,
            "brier_score": None,
            "correct_score_top3_hit_rate": None,
            "calibration": [],
        }

    correct = 0
    log_loss = 0.0
    brier = 0.0
    score_hits = 0
    calibration: dict[int, list[int]] = defaultdict(list)

    for prediction, match in rows:
        probabilities = {
            key: float(prediction["model"]["probabilities"][key]) / 100 for key in OUTCOMES
        }
        actual = actual_outcome(match)
        predicted = max(probabilities, key=probabilities.get)
        is_correct = int(predicted == actual)
        correct += is_correct
        log_loss -= math.log(max(probabilities[actual], 1e-15))
        brier += sum(
            (probabilities[key] - (1.0 if key == actual else 0.0)) ** 2 for key in OUTCOMES
        )

        all_scores = sorted(
            prediction["model"]["score_matrix"],
            key=lambda score: float(score["probability"]),
            reverse=True,
        )[:3]
        actual_score = (int(match.get("home_score") or 0), int(match.get("away_score") or 0))
        score_hits += int(
            actual_score in {(int(score["home"]), int(score["away"])) for score in all_scores}
        )

        confidence = probabilities[predicted]
        bucket = min(9, int(confidence * 10))
        calibration[bucket].append(is_correct)

    size = len(rows)
    bins = []
    for bucket in range(10):
        observations = calibration.get(bucket, [])
        bins.append(
            {
                "range": f"{bucket * 10}-{(bucket + 1) * 10}%",
                "predicted_midpoint": bucket * 10 + 5,
                "actual_rate": round(sum(observations) / len(observations) * 100, 2)
                if observations
                else None,
                "count": len(observations),
            }
        )
    return {
        "sample_size": size,
        "accuracy_1x2": round(correct / size * 100, 2),
        "log_loss": round(log_loss / size, 5),
        "brier_score": round(brier / size, 5),
        "correct_score_top3_hit_rate": round(score_hits / size * 100, 2),
        "calibration": bins,
    }


def classify_failure(prediction: dict[str, Any], match: dict[str, Any]) -> tuple[str, list[str]]:
    actual = actual_outcome(match)
    probabilities = prediction["model"]["probabilities"]
    predicted = max(probabilities, key=probabilities.get)
    stats = match.get("stats") or {}
    reasons: list[str] = []

    expected_fields = ("xgA", "xgB", "cardsA", "cardsB", "substitutions")
    missing = [field for field in expected_fields if stats.get(field) is None]
    if predicted != actual and missing:
        reasons.append(f"缺少賽後欄位：{', '.join(missing)}")
        return "Missing Information", reasons

    market = prediction.get("market_evidence") or {}
    if market.get("available") and market.get("consensus"):
        model_actual = float(probabilities[actual])
        market_actual = float(market["consensus"][actual])
        if predicted != actual and market_actual - model_actual >= 10:
            reasons.append("市場對實際結果的支持比模型高至少 10 個百分點")
            return "Market Signal Missing", reasons

    if predicted != actual and stats.get("shotsA") is not None and stats.get("shotsB") is not None:
        shot_diff = int(stats["shotsA"]) - int(stats["shotsB"])
        expected_diff = (
            prediction["model"]["expected_goals"]["home"]
            - prediction["model"]["expected_goals"]["away"]
        )
        if shot_diff * expected_diff < 0:
            reasons.append("實際攻勢方向與模型預期相反")
            return "Style Mismatch", reasons

    if predicted != actual and max(float(value) for value in probabilities.values()) >= 70:
        reasons.append("高信心預測失準，需檢查 λ 與強弱參數偏誤")
        return "Parameter Bias", reasons

    reasons.append("實際結果仍位於模型保留的機率分布內")
    return "Random Football Variance", reasons


def deterministic_review(prediction: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    failure_type, reasons = classify_failure(prediction, match)
    predicted_score = prediction["model"]["predicted_score"]
    actual_score = f"{int(match.get('home_score') or 0)}-{int(match.get('away_score') or 0)}"
    summary = (
        f"模型預測 {predicted_score['home']}-{predicted_score['away']}，實際為 {actual_score}。"
        f"本場歸類為 {failure_type}；{reasons[0]}。"
    )
    return {
        "match_id": prediction["match_id"],
        "prediction": f"{predicted_score['home']}-{predicted_score['away']}",
        "actual_result": actual_score,
        "failure_type": failure_type,
        "confidence_level": prediction["model"]["confidence"],
        "reasons": reasons,
        "review": summary,
        "generated_by": "rules",
    }


def _probability(row: dict[str, Any], key: str) -> float:
    return max(0.0, float(row.get(key) or 0.0))


def _bounded_probability(row: dict[str, Any], key: str) -> float:
    return min(100.0, _probability(row, key))


def _risk_profile(row: dict[str, Any]) -> tuple[str, str, float]:
    exits: list[tuple[str, str, float]] = []
    for transition, exit_round, reached, next_round in CHAMPIONSHIP_ROUNDS:
        reached_probability = reached if isinstance(reached, float) else _bounded_probability(row, reached)
        exits.append(
            (
                transition,
                exit_round,
                round(max(0.0, reached_probability - _bounded_probability(row, next_round)), 2),
            )
        )
    return max(exits, key=lambda item: item[2])


def _comparison_factors(
    row: dict[str, Any], target: dict[str, Any]
) -> list[dict[str, Any]]:
    factors = []
    for payload_key, source_key, label in CHAMPIONSHIP_COMPARISON_METRICS:
        factors.append(
            {
                "metric": payload_key,
                "label": label,
                "delta_pp": round(_probability(row, source_key) - _probability(target, source_key), 2),
            }
        )
    return sorted(factors, key=lambda factor: abs(float(factor["delta_pp"])), reverse=True)


def _ranking_summary(
    rank: int,
    team_name: str,
    target_name: str,
    championship_delta: float,
    comparison_factors: list[dict[str, Any]],
    path_difficulty: str,
    target_path_difficulty: str,
) -> str:
    strongest = comparison_factors[0]
    metric_label = str(strongest["label"])
    metric_delta = float(strongest["delta_pp"])
    title_gap = abs(championship_delta)
    if rank == 1:
        if metric_delta > 0:
            return (
                f"{team_name}目前領先{target_name} {title_gap:.1f}pp，"
                f"主要優勢來自{metric_label}高出 {metric_delta:.1f}pp。"
            )
        if path_difficulty == "路徑偏順" and target_path_difficulty != "路徑偏順":
            return (
                f"{team_name}以 {title_gap:.1f}pp 領先{target_name}；"
                "高輪次路徑較順，是守住榜首的關鍵。"
            )
        return (
            f"{team_name}以 {title_gap:.1f}pp 微幅領先{target_name}；"
            "前段晉級率未明顯佔優，差距主要來自決賽後的奪冠轉化。"
        )
    if rank <= 3:
        if metric_delta < 0:
            return (
                f"{team_name}落後{target_name} {title_gap:.1f}pp，"
                f"最大差距是{metric_label}低 {abs(metric_delta):.1f}pp。"
            )
        return (
            f"{team_name}與{target_name}相差 {title_gap:.1f}pp；"
            f"雖然{metric_label}高 {metric_delta:.1f}pp，最終奪冠轉化仍略低。"
        )
    if metric_delta < 0:
        return (
            f"{team_name}仍在 Top 5，但落後{target_name} {title_gap:.1f}pp；"
            f"主要瓶頸是{metric_label}低 {abs(metric_delta):.1f}pp。"
        )
    return (
        f"{team_name}仍在 Top 5，與{target_name}相差 {title_gap:.1f}pp；"
        "高輪次轉化不足，限制了冠軍率上升空間。"
    )


def championship_explanations(
    probabilities: list[dict[str, Any]], teams: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Build deterministic Top-5 interpretation metadata from one simulation snapshot."""
    ranked = sorted(
        probabilities, key=lambda item: float(item.get("Winner_pct") or 0), reverse=True
    )
    top_five = ranked[:5]
    if not top_five:
        return {
            "version": CHAMPIONSHIP_EXPLANATIONS_VERSION,
            "generated_by": "rules",
            "threat_basis": "top_championship_probability",
            "teams": [],
        }

    strength_order = sorted(
        teams,
        key=lambda name: (
            float((teams.get(name) or {}).get("fifa_points") or 0)
            + float((teams.get(name) or {}).get("starting_pqs") or 0) * 1000
            + float((teams.get(name) or {}).get("bench_pqs") or 0) * 300
        ),
        reverse=True,
    )
    path_difficulties: dict[str, str] = {}
    strength_ranks = {name: index + 1 for index, name in enumerate(strength_order)}
    for championship_rank, row in enumerate(top_five, start=1):
        team_name = str(row["team_name"])
        strength_rank = strength_ranks.get(team_name, len(teams) or len(ranked))
        late_retention = _probability(row, "Final_pct") / max(_probability(row, "QF_pct"), 0.01)
        difficulty_score = 0
        if championship_rank <= strength_rank - 2:
            difficulty_score -= 1
        elif championship_rank >= strength_rank + 2:
            difficulty_score += 1
        if late_retention >= 0.48:
            difficulty_score -= 1
        elif late_retention < 0.34:
            difficulty_score += 1
        path_difficulties[team_name] = (
            "路徑偏順"
            if difficulty_score <= -1
            else "路徑艱難"
            if difficulty_score >= 1
            else "路徑中等"
        )
    explanation_rows = []

    for championship_rank, row in enumerate(top_five, start=1):
        team_name = str(row["team_name"])
        strength_rank = strength_ranks.get(team_name, len(teams) or len(ranked))
        path_difficulty = path_difficulties[team_name]
        target = (
            top_five[1]
            if championship_rank == 1 and len(top_five) > 1
            else top_five[championship_rank - 2]
            if championship_rank > 1
            else row
        )
        target_name = str(target["team_name"])
        factors = _comparison_factors(row, target)
        championship_delta = round(
            _probability(row, "Winner_pct") - _probability(target, "Winner_pct"), 2
        )
        key_risk_round, legacy_exit_round, choke_point_drop = _risk_profile(row)
        ranking_summary = _ranking_summary(
            championship_rank,
            team_name,
            target_name,
            championship_delta,
            factors,
            path_difficulty,
            path_difficulties[target_name],
        )
        threats = [
            str(candidate["team_name"])
            for candidate in ranked
            if candidate.get("team_name") != team_name
        ][:2]

        strongest_factor = factors[0]
        factor_delta = float(strongest_factor["delta_pp"])
        comparison_phrase = (
            f"{strongest_factor['label']}比{target_name}高 {factor_delta:.1f}pp，"
            "是目前排名的主要支撐。"
            if factor_delta >= 0
            else f"{strongest_factor['label']}低於{target_name} {abs(factor_delta):.1f}pp，"
            "是與相鄰名次的最大差距。"
        )
        reasons = [
            comparison_phrase,
            (
                f"前段出線率為 {_probability(row, 'R32_pct'):.1f}%，"
                f"真正分水嶺在{key_risk_round}，單段掉落 {choke_point_drop:.1f}pp。"
            ),
            (
                f"基礎戰力排第 {strength_rank}、模擬奪冠排第 {championship_rank}，"
                f"整體路徑評估為{path_difficulty}。"
            ),
        ]

        explanation_rows.append(
            {
                "rank": championship_rank,
                "team_name": team_name,
                "championship_probability": _probability(row, "Winner_pct"),
                "final_probability": _probability(row, "Final_pct"),
                "semifinal_probability": _probability(row, "SF_pct"),
                "quarterfinal_probability": _probability(row, "QF_pct"),
                "round_of_16_probability": _probability(row, "R16_pct"),
                "round_of_32_probability": _probability(row, "R32_pct"),
                "ranking_summary": ranking_summary,
                "comparison_target": target_name,
                "comparison_delta": {
                    "championship_probability": championship_delta,
                    "final_probability": round(
                        _probability(row, "Final_pct") - _probability(target, "Final_pct"), 2
                    ),
                    "semifinal_probability": round(
                        _probability(row, "SF_pct") - _probability(target, "SF_pct"), 2
                    ),
                    "quarterfinal_probability": round(
                        _probability(row, "QF_pct") - _probability(target, "QF_pct"), 2
                    ),
                    "strength_rank": strength_rank - strength_ranks.get(target_name, len(teams)),
                },
                "ranking_factors": factors,
                "key_risk_round": key_risk_round,
                "choke_point_drop_pp": choke_point_drop,
                "most_likely_exit_round": legacy_exit_round,
                "biggest_threat_teams": threats,
                "threat_label": "可能卡關對手",
                "threat_note": "依奪冠率與潛在路徑推估",
                "path_difficulty_label": path_difficulty,
                "reason_bullets": reasons,
                "strength_rank": strength_rank,
            }
        )

    return {
        "version": CHAMPIONSHIP_EXPLANATIONS_VERSION,
        "generated_by": "rules",
        "threat_basis": "top_championship_probability",
        "teams": explanation_rows,
    }
