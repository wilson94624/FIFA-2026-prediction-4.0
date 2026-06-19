import os
import json
import numpy as np
import pandas as pd
import time
import re

try:
    from backend.app.bracket import (
        assign_best_thirds,
        resolve_match_teams,
    )
    from backend.app.engine import mix_matrices, sample_score, score_matrix
except ModuleNotFoundError:  # Direct `python backend/player_level_simulator.py` compatibility.
    from app.bracket import assign_best_thirds, resolve_match_teams
    from app.engine import mix_matrices, sample_score, score_matrix

# 設定路徑
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(BACKEND_DIR)

# 自適應載入 .env 檔案中的環境變數 (免去額外安裝 python-dotenv 的依賴)
def load_env_fallback():
    for env_path in [os.path.join(BACKEND_DIR, ".env"), os.path.join(BASE_DIR, ".env")]:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")

load_env_fallback()
DATA_PATH = os.path.join(BASE_DIR, "frontend/src/teams_db.json")
REAL_GAMES_PATH = os.path.join(BASE_DIR, "frontend/src/real_games_results.json")
PROBABILITY_JSON_PATH = os.path.join(BASE_DIR, "frontend/src/simulation_probabilities.json")
ANALYSIS_JSON_PATH = os.path.join(BASE_DIR, "frontend/src/match_analyses.json")

LLM_ANALYSES = {}
if os.path.exists(ANALYSIS_JSON_PATH):
    try:
        with open(ANALYSIS_JSON_PATH, 'r', encoding='utf-8') as f:
            LLM_ANALYSES = json.load(f)
    except Exception:
        pass

def load_teams():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        teams = json.load(f)
    for name, t in teams.items():
        if t.get('has_data'):
            sorted_players = sorted(t['players'], key=lambda x: x['efficiency_score'], reverse=True)
            starters = sorted_players[:11]
            fw_mf = [p for p in starters if p['position'] in ['FW', 'MF']]
            df_gk = [p for p in starters if p['position'] in ['DF', 'GK']]
            t['att_pqs'] = sum(p['efficiency_score'] for p in fw_mf) / len(fw_mf) if fw_mf else t['starting_pqs']
            t['def_pqs'] = sum(p['efficiency_score'] for p in df_gk) / len(df_gk) if df_gk else t['starting_pqs']
        else:
            t['att_pqs'] = t.get('starting_pqs', 0.5)
            t['def_pqs'] = t.get('starting_pqs', 0.5)
    return teams

def get_active_pqs(team_data, unavailable_names, fatigue_val=0.0):
    if not team_data.get('has_data'):
        pqs = team_data.get('starting_pqs', 0.5)
        return pqs * (1.0 - fatigue_val), pqs * (1.0 - fatigue_val), team_data.get('bench_pqs', 0.2)
        
    players = team_data['players']
    active_players = []
    
    for p in players:
        p_name = p['name'].lower()
        is_injured = False
        for un_name in unavailable_names:
            un_name_lower = un_name.lower()
            p_parts = p_name.split('.')[-1].strip().split()
            last_name = p_parts[-1] if p_parts else p_name
            if last_name in un_name_lower or un_name_lower in p_name:
                is_injured = True
                break
        if not is_injured:
            active_players.append(p)
            
    if not active_players:
        active_players = players
        
    sorted_players = sorted(active_players, key=lambda x: x['efficiency_score'], reverse=True)
    starters = sorted_players[:11]
    bench = sorted_players[11:]
    
    fw_mf = [p for p in starters if p['position'] in ['FW', 'MF']]
    df_gk = [p for p in starters if p['position'] in ['DF', 'GK']]
    
    att_pqs = sum(p['efficiency_score'] for p in fw_mf) / len(fw_mf) if fw_mf else team_data.get('starting_pqs', 0.5)
    def_pqs = sum(p['efficiency_score'] for p in df_gk) / len(df_gk) if df_gk else team_data.get('starting_pqs', 0.5)
    bench_pqs = sum(p['efficiency_score'] for p in bench) / len(bench) if bench else 0.01
    
    att_pqs_active = att_pqs * (1.0 - fatigue_val)
    def_pqs_active = def_pqs * (1.0 - fatigue_val)
    
    return att_pqs_active, def_pqs_active, bench_pqs

def load_real_games():
    try:
        from backend.app.db import SessionLocal
        from backend.app.models import MatchRecord
        from sqlalchemy import select

        with SessionLocal() as session:
            records = session.scalars(select(MatchRecord)).all()
            return [dict(record.payload) for record in records]
    except Exception:
        return []

# 解析真實進球球員
def parse_real_scorers(scorers_str):
    if not scorers_str or scorers_str == "null" or scorers_str == "undefined":
        return []
    try:
        # 移除大括弧與引號
        clean = re.sub(r'[{}"\'\\]', '', scorers_str)
        clean = re.sub(r'[“”]', '', clean)
        parts = [p.strip() for p in clean.split(',') if p.strip()]
        
        scorers = []
        for part in parts:
            match = re.match(r"(.+?)\s+(\d+)\'?", part)
            if match:
                scorers.append({
                    "name": match.group(1).strip(),
                    "min": int(match.group(2))
                })
            else:
                scorers.append({"name": part, "min": 45})
        return sorted(scorers, key=lambda x: x['min'])
    except Exception:
        return []

# 真實大賽表現動態更新模型
def apply_real_performance_boost(teams, real_games):
    updated_teams = json.loads(json.dumps(teams))
    if not real_games:
        return updated_teams

    for game in real_games:
        if game.get("finished") != "TRUE":
            continue

        home = game.get("home_team_name_en")
        away = game.get("away_team_name_en")
        home_score = int(game.get("home_score") or 0)
        away_score = int(game.get("away_score") or 0)

        tHome = updated_teams.get(home)
        tAway = updated_teams.get(away)

        if not tHome or not tAway:
            continue

        # 1. 大賽基本經驗提升
        if tHome.get('has_data'):
            for p in tHome['players']:
                p['efficiency_score'] += 0.01
        if tAway.get('has_data'):
            for p in tAway['players']:
                p['efficiency_score'] += 0.01

        # 2. 進球爆發加成
        home_scorers = parse_real_scorers(game.get("home_scorers"))
        for scorer in home_scorers:
            if tHome.get('has_data'):
                # 模糊匹配名字
                matched = False
                for p in tHome['players']:
                    if scorer['name'] in p['name'] or p['name'] in scorer['name']:
                        p['efficiency_score'] += 0.20
                        matched = True
                        break
                if not matched:
                    # 找不到就加給第一個前鋒/中場
                    for p in tHome['players']:
                        if p['position'] in ['FW', 'MF']:
                            p['efficiency_score'] += 0.20
                            break

        away_scorers = parse_real_scorers(game.get("away_scorers"))
        for scorer in away_scorers:
            if tAway.get('has_data'):
                matched = False
                for p in tAway['players']:
                    if scorer['name'] in p['name'] or p['name'] in scorer['name']:
                        p['efficiency_score'] += 0.20
                        matched = True
                        break
                if not matched:
                    for p in tAway['players']:
                        if p['position'] in ['FW', 'MF']:
                            p['efficiency_score'] += 0.20
                            break

        # 3. 門將零封加成
        if tHome.get('has_data'):
            for p in tHome['players']:
                if p['position'] == 'GK':
                    if away_score == 0:
                        p['overall'] += 2
                    elif away_score >= 3:
                        p['overall'] = max(60, p['overall'] - 1)

        if tAway.get('has_data'):
            for p in tAway['players']:
                if p['position'] == 'GK':
                    if home_score == 0:
                        p['overall'] += 2
                    elif home_score >= 3:
                        p['overall'] = max(60, p['overall'] - 1)

        # 4. 重新計算戰力上限與下限
        if tHome.get('has_data'):
            sorted_players = sorted(tHome['players'], key=lambda x: x['efficiency_score'], reverse=True)
            starters = sorted_players[:11]
            tHome['starting_pqs'] = sum(p['efficiency_score'] for p in starters) / 11.0
            tHome['bench_pqs'] = sum(p['efficiency_score'] for p in sorted_players[11:]) / 15.0
            
            fw_mf = [p for p in starters if p['position'] in ['FW', 'MF']]
            df_gk = [p for p in starters if p['position'] in ['DF', 'GK']]
            tHome['att_pqs'] = sum(p['efficiency_score'] for p in fw_mf) / len(fw_mf) if fw_mf else tHome['starting_pqs']
            tHome['def_pqs'] = sum(p['efficiency_score'] for p in df_gk) / len(df_gk) if df_gk else tHome['starting_pqs']

        if tAway.get('has_data'):
            sorted_players = sorted(tAway['players'], key=lambda x: x['efficiency_score'], reverse=True)
            starters = sorted_players[:11]
            tAway['starting_pqs'] = sum(p['efficiency_score'] for p in starters) / 11.0
            tAway['bench_pqs'] = sum(p['efficiency_score'] for p in sorted_players[11:]) / 15.0
            
            fw_mf = [p for p in starters if p['position'] in ['FW', 'MF']]
            df_gk = [p for p in starters if p['position'] in ['DF', 'GK']]
            tAway['att_pqs'] = sum(p['efficiency_score'] for p in fw_mf) / len(fw_mf) if fw_mf else tAway['starting_pqs']
            tAway['def_pqs'] = sum(p['efficiency_score'] for p in df_gk) / len(df_gk) if df_gk else tAway['starting_pqs']

    return updated_teams

def play_match(team_a, team_b, teams, fatigue, real_games, stage_type="group", is_knockout=False, simulated_standings=None, simulated_played_counts=None):
    tA = teams[team_a]
    tB = teams[team_b]
    
    # 1. 優先檢查真實賽果
    real_game = None
    if real_games:
        for g in real_games:
            if (g.get("finished") == "TRUE" and 
                g.get("type") == stage_type and 
                ((g.get("home_team_name_en") == team_a and g.get("away_team_name_en") == team_b) or
                 (g.get("home_team_name_en") == team_b and g.get("away_team_name_en") == team_a))):
                real_game = g
                break

    if real_game:
        is_home_a = real_game.get("home_team_name_en") == team_a
        goalsA = int(real_game.get("home_score") or 0) if is_home_a else int(real_game.get("away_score") or 0)
        goalsB = int(real_game.get("away_score") or 0) if is_home_a else int(real_game.get("home_score") or 0)
        
        # 判定勝負
        if goalsA > goalsB:
            winner = team_a
        elif goalsB > goalsA:
            winner = team_b
        else:
            winner = team_a if is_knockout else 'DRAW'
            
        # 疲勞增加
        fA = fatigue.get(team_a, 0.0)
        fB = fatigue.get(team_b, 0.0)
        benchA = tA['bench_pqs'] if tA['has_data'] else 0.2
        benchB = tB['bench_pqs'] if tB['has_data'] else 0.2
        fatigue[team_a] = fA + 0.04 * (1.0 - benchA)
        fatigue[team_b] = fB + 0.04 * (1.0 - benchB)
        
        return winner, goalsA, goalsB

    # 2. 處理無大名單國家的輪空邏輯
    if not tA['has_data'] or not tB['has_data']:
        if not tA['has_data'] and not tB['has_data']:
            return team_a if is_knockout else 'DRAW', 0, 0
        if not tA['has_data']:
            return team_b, 0, 3
        if not tB['has_data']:
            return team_a, 3, 0

    # 3. 雙泊松隨機預測
    unavailable_a = []
    unavailable_b = []
    if real_games:
        for g in real_games:
            if (((g.get("home_team_name_en") == team_a and g.get("away_team_name_en") == team_b) or
                 (g.get("home_team_name_en") == team_b and g.get("away_team_name_en") == team_a))):
                stats = g.get("stats", {})
                if stats and "unavailable_players" in stats:
                    un_players = stats["unavailable_players"]
                    is_home_a = g.get("home_team_name_en") == team_a
                    if is_home_a:
                        unavailable_a = [p["name"] for p in un_players.get("home", [])]
                        unavailable_b = [p["name"] for p in un_players.get("away", [])]
                    else:
                        unavailable_a = [p["name"] for p in un_players.get("away", [])]
                        unavailable_b = [p["name"] for p in un_players.get("home", [])]
                break

    fA = fatigue.get(team_a, 0.0)
    fB = fatigue.get(team_b, 0.0)

    eloA = tA['fifa_points'] * (1.0 - fA * 0.05)
    eloB = tB['fifa_points'] * (1.0 - fB * 0.05)
    
    # 拆分攻防與替補 PQS (受傷與板凳遞補計算)
    att_pqsA, def_pqsA, bench_pqsA = get_active_pqs(tA, unavailable_a, fA)
    att_pqsB, def_pqsB, bench_pqsB = get_active_pqs(tB, unavailable_b, fB)

    # A. 動態小組賽第三輪戰意懲罰機制 (Motivation Penalty)
    pts_a, pts_b = 0, 0
    played_a, played_b = 0, 0
    if simulated_standings and simulated_played_counts:
        pts_a = simulated_standings[team_a]['points']
        pts_b = simulated_standings[team_b]['points']
        played_a = simulated_played_counts[team_a]
        played_b = simulated_played_counts[team_b]
    else:
        # 回退：掃描 real_games 計算積分
        if real_games:
            for g in real_games:
                if g.get("finished") == "TRUE" and g.get("type") == stage_type:
                    home = g.get("home_team_name_en")
                    away = g.get("away_team_name_en")
                    h_score = int(g.get("home_score") or 0)
                    a_score = int(g.get("away_score") or 0)
                    if home == team_a:
                        played_a += 1
                        if h_score > a_score: pts_a += 3
                        elif h_score == a_score: pts_a += 1
                    elif away == team_a:
                        played_a += 1
                        if a_score > h_score: pts_a += 3
                        elif a_score == h_score: pts_a += 1
                    
                    if home == team_b:
                        played_b += 1
                        if h_score > a_score: pts_b += 3
                        elif h_score == a_score: pts_b += 1
                    elif away == team_b:
                        played_b += 1
                        if a_score > h_score: pts_b += 3
                        elif a_score == h_score: pts_b += 1
                        
    if stage_type == "group":
        if played_a == 2 and pts_a == 6:
            att_pqsA *= 0.85
            def_pqsA *= 0.85
        if played_b == 2 and pts_b == 6:
            att_pqsB *= 0.85
            def_pqsB *= 0.85

    # B. 戰術球風相剋矩陣 (Style Clashing Matrix)
    style_a = tA.get('style', 'Standard')
    style_b = tB.get('style', 'Standard')
    if style_a == 'Possession' and style_b == 'CounterAttack':
        att_pqsA *= 0.90
        att_pqsB *= 1.10
    elif style_a == 'CounterAttack' and style_b == 'Possession':
        att_pqsA *= 1.10
        att_pqsB *= 0.90
        
    if style_a == 'HighPress' and style_b == 'Possession':
        att_pqsB *= 0.95
        att_pqsA *= 1.05
    elif style_a == 'Possession' and style_b == 'HighPress':
        att_pqsA *= 0.95
        att_pqsB *= 1.05
        
    if style_a == 'HighPress' and style_b == 'CounterAttack':
        att_pqsB *= 0.92
        att_pqsA *= 1.08
    elif style_a == 'CounterAttack' and style_b == 'HighPress':
        att_pqsA *= 0.92
        att_pqsB *= 1.08
    

    
    # 東道主優勢與中立球場期望值修正 (美、加、墨為東道主)
    host_hosts = {"USA", "Mexico", "Canada"}
    is_home_host = team_a in host_hosts
    is_away_host = team_b in host_hosts
    
    base_a = 1.2
    base_b = 1.2
    
    if is_home_host and not is_away_host:
        base_a = 1.3
        base_b = 1.1
    elif not is_home_host and is_away_host:
        base_a = 1.1
        base_b = 1.3
        
    # C. 解耦 ELO 與 PQS 的共線性 (經真實盃賽擬合最優：c1 = 0.75, c2 = 0.20)
    c1 = 0.75
    c2 = 0.20
    normal_lambda = max(0.2, base_a + c1 * (eloA - eloB) / 450 + c2 * (att_pqsA - def_pqsB) / 0.3)
    normal_mu = max(0.2, base_b - c1 * (eloA - eloB) / 450 + c2 * (att_pqsB - def_pqsA) / 0.3)
    
    # 🌟 非線性強弱懸殊 (Domination) 壓制因子
    elo_diff = eloA - eloB
    domination_lambda = normal_lambda
    domination_mu = normal_mu
    if elo_diff > 250:
        domination_lambda += (elo_diff - 250) * 0.0018
        domination_mu = max(0.15, domination_mu - (elo_diff - 250) * 0.0005)
    elif elo_diff < -250:
        domination_mu += (-elo_diff - 250) * 0.0018
        domination_lambda = max(0.15, domination_lambda - (-elo_diff - 250) * 0.0005)

    # Predictor 4.0: 在完整比分分布層級混合 70% Normal + 30% Domination。
    mixed_matrix = mix_matrices(
        score_matrix(normal_lambda, normal_mu),
        score_matrix(domination_lambda, domination_mu),
    )
    goalsA, goalsB = sample_score(mixed_matrix, int(np.random.randint(0, 2**31 - 1)))
    lambda_val = 0.7 * normal_lambda + 0.3 * domination_lambda
    mu_val = 0.7 * normal_mu + 0.3 * domination_mu
            
    winner = 'DRAW'
    extra_time_played = False

    if goalsA > goalsB:
        winner = team_a
    elif goalsB > goalsA:
        winner = team_b
    else:
        if is_knockout:
            extra_time_played = True
            extra_a = np.random.poisson(lambda_val * 0.33)
            extra_b = np.random.poisson(mu_val * 0.33)
            goalsA += extra_a
            goalsB += extra_b
            
            if goalsA > goalsB:
                winner = team_a
            elif goalsB > goalsA:
                winner = team_b
            else:
                # PK 大戰
                gk_a = max([p['overall'] for p in tA['players'] if p['position'] == 'GK'] or [60])
                gk_b = max([p['overall'] for p in tB['players'] if p['position'] == 'GK'] or [60])
                
                shooters_a = np.mean(sorted([p['overall'] for p in tA['players'] if p['position'] != 'GK'], reverse=True)[:5] or [65])
                shooters_b = np.mean(sorted([p['overall'] for p in tB['players'] if p['position'] != 'GK'], reverse=True)[:5] or [65])
                
                rate_a = max(0.55, min(0.90, 0.75 + (shooters_a - gk_b) / 200.0))
                rate_b = max(0.55, min(0.90, 0.75 + (shooters_b - gk_a) / 200.0))
                
                pen_a, pen_b = 0, 0
                for _ in range(5):
                    if np.random.rand() < rate_a: pen_a += 1
                    if np.random.rand() < rate_b: pen_b += 1
                while pen_a == pen_b:
                    if np.random.rand() < rate_a: pen_a += 1
                    if np.random.rand() < rate_b: pen_b += 1
                
                winner = team_a if pen_a > pen_b else team_b

    # 累加疲勞值
    benchA = bench_pqsA
    benchB = bench_pqsB
    fatigue[team_a] = fA + 0.04 * (1.0 - benchA) + (0.02 if extra_time_played else 0.0)
    fatigue[team_b] = fB + 0.04 * (1.0 - benchB) + (0.02 if extra_time_played else 0.0)

    return winner, goalsA, goalsB

def simulate_group_stage(teams, fatigue, real_games):
    standings = {}
    played_counts = {}
    for team in teams.keys():
        standings[team] = {
            'team': team,
            'points': 0,
            'gd': 0,
            'gs': 0,
            'elo': teams[team]['fifa_points']
        }
        played_counts[team] = 0
        
    groups = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']
    
    for grp in groups:
        grp_teams = [t for t in teams.keys() if teams[t]['group'] == grp]
        
        for i in range(len(grp_teams)):
            for j in range(i + 1, len(grp_teams)):
                team_a = grp_teams[i]
                team_b = grp_teams[j]
                
                winner, gA, gB = play_match(
                    team_a, team_b, teams, fatigue, real_games, 
                    stage_type="group", is_knockout=False,
                    simulated_standings=standings,
                    simulated_played_counts=played_counts
                )
                
                played_counts[team_a] += 1
                played_counts[team_b] += 1
                
                standings[team_a]['gs'] += gA
                standings[team_a]['gd'] += (gA - gB)
                standings[team_b]['gs'] += gB
                standings[team_b]['gd'] += (gB - gA)
                
                if winner == team_a:
                    standings[team_a]['points'] += 3
                elif winner == team_b:
                    standings[team_b]['points'] += 3
                else:
                    standings[team_a]['points'] += 1
                    standings[team_b]['points'] += 1
                    
    group_results = {}
    for grp in groups:
        grp_teams = [t for t in teams.keys() if teams[t]['group'] == grp]
        sorted_grp = sorted(
            [standings[t] for t in grp_teams],
            key=lambda x: (x['points'], x['gd'], x['gs'], x['elo']),
            reverse=True
        )
        group_results[grp] = sorted_grp
        
    qualified_1st_2nd = []
    qualified_3rds = []
    
    for grp in groups:
        qualified_1st_2nd.append(group_results[grp][0]['team'])
        qualified_1st_2nd.append(group_results[grp][1]['team'])
        qualified_3rds.append(group_results[grp][2])
        
    sorted_thirds = sorted(
        qualified_3rds,
        key=lambda x: (x['points'], x['gd'], x['gs'], x['elo']),
        reverse=True
    )
    
    qualified_thirds_teams = [x['team'] for x in sorted_thirds[:8]]
    return group_results, qualified_thirds_teams

def simulate_tournament_once(teams, real_games):
    fatigue = {t: 0.0 for t in teams.keys()}
    
    # 1. 小組賽
    group_results, qualified_thirds = simulate_group_stage(teams, fatigue, real_games)
    
    # 2. Resolve every round from the API/DB slot labels and source match IDs.
    knockout_matches = sorted(
        [g for g in real_games if g.get("type") in {"r32", "r16", "qf", "sf", "final"}],
        key=lambda g: int(g["id"]) if str(g.get("id", "")).isdigit() else 10_000,
    )
    r32_matches = [g for g in knockout_matches if g.get("type") == "r32"]
    third_rows = [row for rows in group_results.values() for row in rows if row["team"] in qualified_thirds]
    for row in third_rows:
        row["group"] = teams[row["team"]]["group"]
    third_assignments, _ = assign_best_thirds(r32_matches, third_rows)

    winners = {}
    participants = {stage: [] for stage in ("r32", "r16", "qf", "sf", "final")}
    for match in knockout_matches:
        stage = match.get("type")
        team_a, team_b = resolve_match_teams(match, group_results, third_assignments, winners)
        if team_a not in teams or team_b not in teams:
            raise ValueError(f"Cannot resolve knockout match {match.get('id')}: {team_a} vs {team_b}")
        participants[stage].extend([team_a, team_b])
        winner, _, _ = play_match(
            team_a, team_b, teams, fatigue, real_games, stage_type=stage, is_knockout=True
        )
        winners[str(match.get("id"))] = winner

    final_matches = [g for g in knockout_matches if g.get("type") == "final"]
    if len(final_matches) != 1:
        raise ValueError("Expected exactly one final match in database bracket")
    champion = winners[str(final_matches[0].get("id"))]
    
    return {
        'R32': participants['r32'],
        'R16': participants['r16'],
        'QF': participants['qf'],
        'SF': participants['sf'],
        'Final': participants['final'],
        'Winner': champion
    }

def run_monte_carlo(n_simulations=10000):
    teams = load_teams()
    real_games = load_real_games()
    
    # 1. 模擬前，先依據真實世界賽果，動態疊加更新球員與球隊戰力！
    boosted_teams = apply_real_performance_boost(teams, real_games)
    
    stats = {}
    for team in boosted_teams.keys():
        stats[team] = {
            'R32_pct': 0.0,
            'R16_pct': 0.0,
            'QF_pct': 0.0,
            'SF_pct': 0.0,
            'Final_pct': 0.0,
            'Winner_pct': 0.0
        }
        
    print(f"開始執行球員級蒙地卡羅模擬 ({n_simulations} 次)...")
    start_time = time.time()
    
    for _ in range(n_simulations):
        run = simulate_tournament_once(boosted_teams, real_games)
        
        for team in run['R32']:
            stats[team]['R32_pct'] += 1
        for team in run['R16']:
            stats[team]['R16_pct'] += 1
        for team in run['QF']:
            stats[team]['QF_pct'] += 1
        for team in run['SF']:
            stats[team]['SF_pct'] += 1
        for team in run['Final']:
            stats[team]['Final_pct'] += 1
        stats[run['Winner']]['Winner_pct'] += 1
        
    # 計算百分比
    for team in stats.keys():
        for stage in stats[team].keys():
            stats[team][stage] = (stats[team][stage] / n_simulations) * 100
            
    df_stats = pd.DataFrame.from_dict(stats, orient='index')
    df_stats = df_stats.sort_values(by='Winner_pct', ascending=False)
    
    # 輸出前 15 強
    print("\n球員級模擬 - 奪冠機率前 15 名：")
    print(df_stats.head(15).to_string(formatters={
        'R32_pct': '{:,.2f}%'.format,
        'R16_pct': '{:,.2f}%'.format,
        'QF_pct': '{:,.2f}%'.format,
        'SF_pct': '{:,.2f}%'.format,
        'Final_pct': '{:,.2f}%'.format,
        'Winner_pct': '{:,.2f}%'.format
    }))
    
    # 儲存 CSV
    out_dir = BACKEND_DIR
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    csv_path = os.path.join(out_dir, "simulation_results_player_level.csv")
    df_stats.to_csv(csv_path)
    
    # 儲存 JSON 供前端直接讀取
    probability_list = []
    for team, row in df_stats.iterrows():
        probability_list.append({
            "team_name": team,
            "R32_pct": round(row['R32_pct'], 2),
            "R16_pct": round(row['R16_pct'], 2),
            "QF_pct": round(row['QF_pct'], 2),
            "SF_pct": round(row['SF_pct'], 2),
            "Final_pct": round(row['Final_pct'], 2),
            "Winner_pct": round(row['Winner_pct'], 2)
        })
    
    prob_output = {
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "probabilities": probability_list
    }
    
    with open(PROBABILITY_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(prob_output, f, ensure_ascii=False, indent=2)
        
    print(f"\n結果已儲存至: {csv_path} 與 {PROBABILITY_JSON_PATH}")
    print(f"模擬耗時: {time.time() - start_time:.2f} 秒。")
    
    # 額外生成即將進行比賽的 LLM 深度解析
    generate_upcoming_matches_analysis()

# ==========================================
# 🔮 LLM 預測深度解析自動生成模組 (Vercel/GitHub Actions 部署用)
# ==========================================
def generate_upcoming_matches_analysis():
    import requests
    import math

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("\n[LLM] 未偵測到 GEMINI_API_KEY 環境變數，跳過 LLM 預測深度解析生成。")
        return

    print("\n[LLM] 偵測到 GEMINI_API_KEY，開始為即將進行的比賽生成/更新 LLM 深度解析...")
    
    # 載入資料
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        teams = json.load(f)
    with open(REAL_GAMES_PATH, 'r', encoding='utf-8') as f:
        real_games = json.load(f)
        
    ANALYSIS_JSON_PATH = os.path.join(BASE_DIR, "frontend/src/match_analyses.json")
    
    existing_analyses = {}
    if os.path.exists(ANALYSIS_JSON_PATH):
        try:
            with open(ANALYSIS_JSON_PATH, 'r', encoding='utf-8') as f:
                existing_analyses = json.load(f)
        except Exception:
            existing_analyses = {}

    # 找出所有未結束的比賽
    upcoming = []
    for g in real_games:
        if g.get("finished") == "FALSE":
            upcoming.append(g)
            
    # 排序
    def parse_date(dStr):
        if not dStr: return 0
        try:
            d, t = dStr.split(' ')
            m, day, y = map(int, d.split('/'))
            h, min_val = map(int, t.split(':'))
            return y * 100000000 + m * 1000000 + day * 10000 + h * 100 + min_val
        except Exception:
            return 0
            
    upcoming.sort(key=lambda x: parse_date(x.get("local_date")))
    
    # 批次模式下，可擴大處理前 10 場，大幅降低請求次數
    target_matches = upcoming[:10]
    
    # 輔助計算函數
    def get_fatigue_before_match(team_name, match_id):
        current_match = next((g for g in real_games if g['id'] == match_id), None)
        if not current_match: return 0.0
        current_time = parse_date(current_match['local_date'])
        
        accumulated_fatigue = 0.0
        for g in real_games:
            if g.get('finished') == 'TRUE' and parse_date(g['local_date']) < current_time:
                if g['home_team_name_en'] == team_name or g['away_team_name_en'] == team_name:
                    t_info = teams.get(team_name, {})
                    bench = t_info.get('bench_pqs', 0.2) if t_info.get('has_data') else 0.2
                    accumulated_fatigue += 0.04 * (1.0 - bench)
        return accumulated_fatigue

    def poisson_pmf(k, lam):
        return (lam ** k) * math.exp(-lam) / math.factorial(k)

    def calculate_match_probs(lambda_val, mu_val):
        max_goals = 5
        rho = -0.05
        gamma = 0.08
        
        def dc_correction(x, y, p):
            if x == 0 and y == 0: return p * (1.0 - rho * lambda_val * mu_val)
            if x == 1 and y == 1: return p * (1.0 - rho)
            if x == 1 and y == 0: return p * (1.0 + rho * mu_val)
            if x == 0 and y == 1: return p * (1.0 + rho * lambda_val)
            return p

        # 雙變量泊松 PMF 函數
        def bivariate_pmf(x, y):
            g = min(gamma, lambda_val - 0.01, mu_val - 0.01)
            if g < 0: g = 0
            lam1 = lambda_val - g
            lam2 = mu_val - g
            lam3 = g
            
            p_sum = 0.0
            for k in range(min(x, y) + 1):
                p1 = poisson_pmf(x - k, lam1)
                p2 = poisson_pmf(y - k, lam2)
                p3 = poisson_pmf(k, lam3)
                p_sum += p1 * p2 * p3
            return p_sum

        win_a, win_b, draw = 0.0, 0.0, 0.0
        scores = []
        for x in range(max_goals + 1):
            for y in range(max_goals + 1):
                prob = bivariate_pmf(x, y)
                prob = max(0.0, dc_correction(x, y, prob))
                scores.append({'home': x, 'away': y, 'prob': prob})
                if x > y: win_a += prob
                elif y > x: win_b += prob
                else: draw += prob

        total = win_a + win_b + draw
        win_a, draw, win_b = win_a / total, draw / total, win_b / total
        for s in scores: s['prob'] /= total

        scores_a = sorted([s for s in scores if s['home'] > s['away']], key=lambda s: s['prob'], reverse=True)[:3]
        scores_b = sorted([s for s in scores if s['away'] > s['home']], key=lambda s: s['prob'], reverse=True)[:3]
        all_top = sorted(scores_a + scores_b, key=lambda s: s['prob'], reverse=True)[:3]
        return win_a * 100, draw * 100, win_b * 100, all_top

    def get_key_players_summary(team_info):
        if not team_info or not team_info.get('has_data'):
            return "   該隊無核心大名單資料，為預設實力。"
        players = team_info.get('players', [])
        if not players:
            return "   無球員資料。"
        # 明星球員
        star_players = [p for p in players if p.get('is_star') or p.get('is_star') == 1]
        # 按照 overall 排序的前 5 名主力
        top_ovr_players = sorted(players, key=lambda x: x.get('overall', 0), reverse=True)[:5]
        # 合併去重
        seen = set()
        key_players = []
        for p in star_players:
            if p['name'] not in seen:
                seen.add(p['name'])
                key_players.append(p)
        for p in top_ovr_players:
            if p['name'] not in seen:
                seen.add(p['name'])
                key_players.append(p)
        key_players = key_players[:6]
        summary_parts = []
        for p in key_players:
            star_flag = " (明星球員★)" if p.get('is_star') else ""
            summary_parts.append(
                f"- {p['name']} ({p.get('position', 'N/A')}, 評分: {p.get('overall', 0)}, PQS: {p.get('efficiency_score', 0.0):.2f}){star_flag}"
            )
        return "\n".join(summary_parts)

    # 封裝所有即將進行比賽的 model 預測數據
    match_payloads = []
    for m in target_matches:
        match_id = m['id']
        home = m['home_team_name_en']
        away = m['away_team_name_en']
        
        tA = teams.get(home)
        tB = teams.get(away)
        if not tA or not tB: continue
        
        fA = get_fatigue_before_match(home, match_id)
        fB = get_fatigue_before_match(away, match_id)
        
        eloA = tA['fifa_points'] * (1.0 - fA * 0.05)
        eloB = tB['fifa_points'] * (1.0 - fB * 0.05)
        
        # 拆分攻防 PQS
        att_pqsA = tA.get('att_pqs', tA['starting_pqs']) * (1.0 - fA)
        def_pqsA = tA.get('def_pqs', tA['starting_pqs']) * (1.0 - fA)
        att_pqsB = tB.get('att_pqs', tB['starting_pqs']) * (1.0 - fB)
        def_pqsB = tB.get('def_pqs', tB['starting_pqs']) * (1.0 - fB)
        
        host_hosts = {"USA", "Mexico", "Canada"}
        is_home_host = home in host_hosts
        is_away_host = away in host_hosts
        
        base_a = 1.2
        base_b = 1.2
        
        if is_home_host and not is_away_host:
            base_a = 1.3
            base_b = 1.1
        elif not is_home_host and is_away_host:
            base_a = 1.1
            base_b = 1.3
            
        c1 = 0.75
        c2 = 0.20
        lambda_val = max(0.2, base_a + c1 * (eloA - eloB) / 450 + c2 * (att_pqsA - def_pqsB) / 0.3)
        mu_val = max(0.2, base_b - c1 * (eloA - eloB) / 450 + c2 * (att_pqsB - def_pqsA) / 0.3)
        
        # 🌟 非線性強弱懸殊 (Domination) 壓制因子
        elo_diff = eloA - eloB
        if elo_diff > 250:
            lambda_val += (elo_diff - 250) * 0.0018
            mu_val = max(0.15, mu_val - (elo_diff - 250) * 0.0005)
        elif elo_diff < -250:
            mu_val += (-elo_diff - 250) * 0.0018
            lambda_val = max(0.15, lambda_val - (-elo_diff - 250) * 0.0005)
        
        win_a, draw, win_b, top_scores = calculate_match_probs(lambda_val, mu_val)
        top_scores_str = ", ".join([f"{s['home']}:{s['away']}" for s in top_scores])
        
        home_players_summary = get_key_players_summary(tA)
        away_players_summary = get_key_players_summary(tB)
        
        payload = {
            "match_id": str(match_id),
            "home": home,
            "away": away,
            "model_prediction": {
                "home_win_prob": f"{win_a:.1f}%",
                "draw_prob": f"{draw:.1f}%",
                "away_win_prob": f"{win_b:.1f}%",
                "top_scores": top_scores_str
            },
            "home_team_stats": {
                "starting_pqs": float(f"{tA.get('starting_pqs', 0.0):.2f}"),
                "fatigue": float(f"{fA:.2f}"),
                "key_players": home_players_summary
            },
            "away_team_stats": {
                "starting_pqs": float(f"{tB.get('starting_pqs', 0.0):.2f}"),
                "fatigue": float(f"{fB:.2f}"),
                "key_players": away_players_summary
            }
        }
        match_payloads.append(payload)

    # 批次打包並防禦性延時 (調整為 10 讓 10 場對局只需 1 次呼叫)
    BATCH_SIZE = 10
    batches = [match_payloads[i:i + BATCH_SIZE] for i in range(0, len(match_payloads), BATCH_SIZE)]
    
    updated_count = 0
    import time
    
    for idx, batch in enumerate(batches):
        if idx > 0:
            print(f"\n[LLM] 為避開頻率限制，強制序列化等待 30 秒後繼續下一批...")
            time.sleep(30)
            
        print(f"\n[LLM] 正在發送第 {idx + 1}/{len(batches)} 批對局（共 {len(batch)} 場）至 Gemini API...")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        
        prompt = f"""
你是一位專業的世界盃足球分析師。請為以下傳入的 {len(batch)} 場即將進行的 2026 世界盃對局進行深度戰術分析與球評撰寫。

傳入的對局 JSON 資料如下：
{json.dumps(batch, ensure_ascii=False, indent=2)}

【分析要求】：
對於資料中的每一場對局（透過 "match_id" 區分）：
1. 在 "llm_analysis" 中，你必須結合雙方的主力與明星球員（尤其是 marked as 明星球員★ 或高評分的主力），從他們的場上位置、整體評分與 PQS 戰力期望值出發，進行深度的戰術策略分析。
2. 請用這套球員級的戰術與策略分析，去「佐證」為什麼模型給出以上的預測勝率是合理且正確的。
3. 球評語氣需隨性、流暢，帶有臺灣本土球評的風格（『對位』、『防線漏洞』、『碾壓』、『基本盤』、『大當機』、『黑馬』、『爆冷』等），段落清晰，長度控制在 150-200 字左右，無 markdown 標題。

請嚴格以 JSON 格式回傳，必須是一個 JSON Array，裡面包含每場對局的分析，結構必須如下：
[
  {{
    "match_id": "對局的 match_id (字串，例如 '21')",
    "llm_analysis": "球評 analysis 的內容 (繁體中文)"
  }},
  ...
]
"""
        data = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }
        
        # 實作防禦性重試機制 (最多重試 3 次)
        max_retries = 3
        retry_delay = 45
        response = None
        
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=data, timeout=90)
                if response.status_code == 200:
                    break
                elif response.status_code == 429:
                    try:
                        err_json = response.json()
                        details = err_json.get('error', {}).get('details', [])
                        for detail in details:
                            if 'RetryInfo' in detail.get('@type', ''):
                                delay_str = detail.get('retryDelay', '').replace('s', '')
                                retry_delay = int(float(delay_str)) + 2
                                break
                    except Exception:
                        pass
                    print(f"   [LLM] 遇到 429 頻率限制 (第 {attempt + 1}/{max_retries} 次嘗試)，將等待 {retry_delay} 秒後重試...")
                    time.sleep(retry_delay)
                else:
                    break
            except Exception as e:
                print(f"   API request failed on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    
        try:
            if response and response.status_code == 200:
                res_json = response.json()
                raw_text = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
                
                try:
                    parsed_list = json.loads(raw_text)
                    if isinstance(parsed_list, dict) and not isinstance(parsed_list, list):
                        # 如果模型不小心包裝了 key，嘗試解開
                        for k, v in parsed_list.items():
                            if isinstance(v, list):
                                parsed_list = v
                                break
                    
                    if isinstance(parsed_list, list):
                        for parsed_analysis in parsed_list:
                            m_id = parsed_analysis.get('match_id')
                            if not m_id:
                                continue
                            
                            # 尋找對應的原始 payload
                            orig_match = next((item for item in batch if str(item['match_id']) == str(m_id)), None)
                            if not orig_match:
                                continue
                            
                            home = orig_match['home']
                            away = orig_match['away']
                            
                            home_att_mod = 1.0
                            home_def_mod = 1.0
                            away_att_mod = 1.0
                            away_def_mod = 1.0
                            
                            home_att_mod_reason = "無特別事件"
                            home_def_mod_reason = "無特別事件"
                            away_att_mod_reason = "無特別事件"
                            away_def_mod_reason = "無特別事件"
                            llm_analysis = parsed_analysis.get('llm_analysis', "無法產生解析")
                            
                            existing_analyses[str(m_id)] = {
                                "match_id": str(m_id),
                                "home": home,
                                "away": away,
                                "home_att_mod": home_att_mod,
                                "home_att_mod_reason": home_att_mod_reason,
                                "home_def_mod": home_def_mod,
                                "home_def_mod_reason": home_def_mod_reason,
                                "away_att_mod": away_att_mod,
                                "away_att_mod_reason": away_att_mod_reason,
                                "away_def_mod": away_def_mod,
                                "away_def_mod_reason": away_def_mod_reason,
                                "llm_analysis": llm_analysis
                            }
                            updated_count += 1
                    else:
                        print(f"   API 回傳格式錯誤，未包含有效的 JSON List")
                except Exception as parse_err:
                    print(f"   解析 JSON 失敗: {parse_err}")
            else:
                status_code = response.status_code if response else "None"
                res_text = response.text if response else "No response"
                print(f"   API error {status_code}: {res_text}")
        except Exception as e:
            print(f"   API request failed: {e}")
            
    if updated_count > 0:
        with open(ANALYSIS_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(existing_analyses, f, ensure_ascii=False, indent=2)
        print(f"[LLM] 解析已成功批次寫入 {ANALYSIS_JSON_PATH}。新增/更新: {updated_count} 場。")
    else:
        print("[LLM] 沒有新增或需要更新的解析。")

if __name__ == '__main__':
    run_monte_carlo(10000)
