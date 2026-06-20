import { useState } from 'react';
import { TEAM_TRANSLATIONS, toTaiwanTime } from '../utils/constants';
import { parseRealScorers } from '../utils/format';

// 國名與國旗轉換
const t = (name) => {
  if (!name) return '🏳️ 待定';
  
  // 檢查是否是匹配範本 Label
  if (
    name.includes('Group') || 
    name.includes('Match') || 
    name.includes('Runner-up') || 
    name.includes('Winner') || 
    name.includes('3rd')
  ) {
    return translateLabel(name);
  }
  
  const item = TEAM_TRANSLATIONS?.[name] || { cn: name, flag: '🏳️' };
  return `${item.flag} ${item.cn}`;
};

// 翻譯 Matchup Template Labels 為中文
const translateLabel = (label) => {
  if (!label) return '待定';
  
  // Winner Group X -> X組第一
  let match = label.match(/Winner Group ([A-L])/i);
  if (match) {
    return `${match[1]}組第一`;
  }
  
  // Runner-up Group X -> X組第二
  match = label.match(/Runner-up Group ([A-L])/i);
  if (match) {
    return `${match[1]}組第二`;
  }
  
  // 3rd Group X/Y/Z -> X/Y/Z組第三
  match = label.match(/3rd Group ([A-L/]+)/i);
  if (match) {
    return `${match[1]}組第三`;
  }
  
  // Winner Match XX -> MXX 勝方
  match = label.match(/Winner Match (\d+)/i);
  if (match) {
    return `M${match[1]} 勝方`;
  }
  
  // Loser Match XX -> MXX 敗方
  match = label.match(/Loser Match (\d+)/i);
  if (match) {
    return `M${match[1]} 敗方`;
  }
  
  return label;
};

// 判定淘汰賽晉級得勝者
const getKnockoutWinner = (match, allMatches) => {
  if (!match || match.finished !== 'TRUE') return null;
  const scoreA = parseInt(match.home_score || 0);
  const scoreB = parseInt(match.away_score || 0);
  if (scoreA > scoreB) return match.home_team_name_en;
  if (scoreB > scoreA) return match.away_team_name_en;
  
  // 同分（PK戰或延長賽和局）- 從後續賽程尋找是哪一隊晉級
  const teamA = match.home_team_name_en;
  const teamB = match.away_team_name_en;
  if (!teamA || !teamB) return null;
  
  const matchId = parseInt(match.id);
  const nextMatches = allMatches.filter(m => {
    const mId = parseInt(m.id);
    return mId > matchId && (
      m.home_team_name_en === teamA || 
      m.away_team_name_en === teamA || 
      m.home_team_name_en === teamB || 
      m.away_team_name_en === teamB
    );
  });
  
  for (const nm of nextMatches) {
    if (nm.home_team_name_en === teamA || nm.away_team_name_en === teamA) return teamA;
    if (nm.home_team_name_en === teamB || nm.away_team_name_en === teamB) return teamB;
  }
  
  return teamA; // Fallback
};

export default function TournamentBracket({
  teams,
  realGames,
  onSelectMatch,
  onSelectTeam,
  initialSubTab = 'bracket',
}) {
  const [subTab, setSubTab] = useState(initialSubTab); // bracket | standings | results
  const [standingsGroup, setStandingsGroup] = useState('A'); // 當前選擇的小組積分榜

  // 1. 計算小組積分榜 A-L
  const groups = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L'];
  const groupStandings = {};
  
  groups.forEach(grp => {
    const grpTeams = Object.keys(teams).filter(tName => teams[tName].group === grp);
    
    const standingsList = grpTeams.map(tName => ({
      team: tName,
      played: 0,
      wins: 0,
      draws: 0,
      losses: 0,
      gs: 0,
      gc: 0,
      gd: 0,
      points: 0,
      fifa_points: teams[tName].fifa_points,
      avg_rating: teams[tName].avg_rating
    }));
    
    // 計算完賽的該分組小組賽
    const grpMatches = realGames.filter(g => g.type === 'group' && g.group === grp && g.finished === 'TRUE');
    
    grpMatches.forEach(match => {
      const home = match.home_team_name_en;
      const away = match.away_team_name_en;
      const homeScore = parseInt(match.home_score || 0);
      const awayScore = parseInt(match.away_score || 0);
      
      const homeTeam = standingsList.find(s => s.team === home);
      const awayTeam = standingsList.find(s => s.team === away);
      
      if (homeTeam && awayTeam) {
        homeTeam.played += 1;
        awayTeam.played += 1;
        homeTeam.gs += homeScore;
        homeTeam.gc += awayScore;
        awayTeam.gs += awayScore;
        awayTeam.gc += homeScore;
        homeTeam.gd = homeTeam.gs - homeTeam.gc;
        awayTeam.gd = awayTeam.gs - awayTeam.gc;
        
        if (homeScore > awayScore) {
          homeTeam.wins += 1;
          homeTeam.points += 3;
          awayTeam.losses += 1;
        } else if (awayScore > homeScore) {
          awayTeam.wins += 1;
          awayTeam.points += 3;
          homeTeam.losses += 1;
        } else {
          homeTeam.draws += 1;
          awayTeam.draws += 1;
          homeTeam.points += 1;
          awayTeam.points += 1;
        }
      }
    });
    
    // 小組內排序 (積分 -> 淨勝球 -> 進球數 -> FIFA積分)
    standingsList.sort((a, b) => {
      if (b.points !== a.points) return b.points - a.points;
      if (b.gd !== a.gd) return b.gd - a.gd;
      if (b.gs !== a.gs) return b.gs - a.gs;
      return b.fifa_points - a.fifa_points;
    });
    
    groupStandings[grp] = standingsList;
  });

  // 2. 獲取淘汰賽實時對決
  const r32Real = realGames.filter(g => g.type === 'r32');
  const r16Real = realGames.filter(g => g.type === 'r16');
  const qfReal = realGames.filter(g => g.type === 'qf');
  const sfReal = realGames.filter(g => g.type === 'sf');
  const finalReal = realGames.find(g => g.type === 'final');
  
  const mapRealMatch = (g) => {
    if (!g) return null;
    const teamA = g.home_team_name_en || g.home_team_label || '';
    const teamB = g.away_team_name_en || g.away_team_label || '';
    
    let result = null;
    let goalsA = '-';
    let goalsB = '-';
    let scorersA = [];
    let scorersB = [];
    let stats = null;
    
    if (g.finished === 'TRUE') {
      goalsA = parseInt(g.home_score || 0);
      goalsB = parseInt(g.away_score || 0);
      const winner = getKnockoutWinner(g, realGames);
      
      scorersA = parseRealScorers(g.home_scorers);
      scorersB = parseRealScorers(g.away_scorers);
      
      // 1. 優先使用 JSON 裡的真實 stats
      if (g.stats && 
          typeof g.stats.possessionA !== 'undefined' && 
          typeof g.stats.shotsA !== 'undefined') {
        stats = { ...g.stats };
      } else {
        // 2. Fallback: 動態計算，避免寫死 50/50
        const tA = teams?.[teamA];
        const tB = teams?.[teamB];
        
        if (tA && tB) {
          const pqsA = (tA.att_pqs || tA.starting_pqs || 0.5);
          const pqsDefA = (tA.def_pqs || tA.starting_pqs || 0.5);
          const pqsB = (tB.att_pqs || tB.starting_pqs || 0.5);
          const pqsDefB = (tB.def_pqs || tB.starting_pqs || 0.5);
          
          const avgPqsA = (pqsA + pqsDefA) / 2;
          const avgPqsB = (pqsB + pqsDefB) / 2;
          
          const goalDiff = goalsA - goalsB;
          let possession = Math.floor(50 + (avgPqsA - avgPqsB) * 100 + goalDiff * 2);
          possession = Math.max(30, Math.min(70, possession));
          
          const totalShots = 24;
          const shotsA_exp = Math.floor(totalShots * (possession / 100)) + goalsA;
          const shotsB_exp = totalShots - shotsA_exp + goalsB;
          
          const shotsA = Math.max(goalsA, shotsA_exp);
          const shotsB = Math.max(goalsB, shotsB_exp);
          const foulsA = 10 + (possession < 45 ? 3 : 0);
          const foulsB = 10 + (possession >= 55 ? 3 : 0);
          
          stats = {
            possessionA: possession,
            possessionB: 100 - possession,
            shotsA: Math.max(1, shotsA),
            shotsB: Math.max(1, shotsB),
            foulsA,
            foulsB
          };
        } else {
          // 最底限退路
          stats = {
            possessionA: 50,
            possessionB: 50,
            shotsA: goalsA + 6,
            shotsB: goalsB + 6,
            foulsA: 10,
            foulsB: 10
          };
        }
      }
      
      result = {
        winner,
        goalsA,
        goalsB,
        home_scorers: g.home_scorers,
        away_scorers: g.away_scorers
      };
    }
    
    return {
      id: g.id,
      teamA,
      teamB,
      home_team_name_en: teamA,
      away_team_name_en: teamB,
      home_score: g.home_score,
      away_score: g.away_score,
      home_scorers: g.home_scorers,
      away_scorers: g.away_scorers,
      goalsA,
      goalsB,
      scorersA,
      scorersB,
      stats,
      home_team_label: g.home_team_label,
      away_team_label: g.away_team_label,
      time_elapsed: g.time_elapsed,
      finished: g.finished,
      local_date: g.local_date,
      type: g.type,
      group: g.group,
      result
    };
  };

  const r32Matches = Array.from({ length: 16 }, (_, i) => {
    return mapRealMatch(r32Real[i]) || { teamA: '待定', teamB: '待定', result: null };
  });

  const r16Matches = Array.from({ length: 8 }, (_, i) => {
    return mapRealMatch(r16Real[i]) || { teamA: '待定', teamB: '待定', result: null };
  });

  const qfMatches = Array.from({ length: 4 }, (_, i) => {
    return mapRealMatch(qfReal[i]) || { teamA: '待定', teamB: '待定', result: null };
  });

  const sfMatches = Array.from({ length: 2 }, (_, i) => {
    return mapRealMatch(sfReal[i]) || { teamA: '待定', teamB: '待定', result: null };
  });

  const finalMatch = mapRealMatch(finalReal);
  const champion = finalReal && finalReal.finished === 'TRUE' ? getKnockoutWinner(finalReal, realGames) : null;
  const resultGroups = Object.entries(
    realGames
      .map(mapRealMatch)
      .filter(Boolean)
      .sort((a, b) => toTaiwanTime(a.local_date).localeCompare(toTaiwanTime(b.local_date)))
      .reduce((groupsByDate, match) => {
        const dateKey = toTaiwanTime(match.local_date).split(' ')[0] || '日期待定';
        groupsByDate[dateKey] = [...(groupsByDate[dateKey] || []), match];
        return groupsByDate;
      }, {}),
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', width: '100%' }}>
      
      {/* 🚀 Sub Tabs Navigation */}
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'center', borderBottom: '1px solid var(--glass-border)', paddingBottom: '14px' }}>
        <button 
          onClick={() => setSubTab('bracket')} 
          className={subTab === 'bracket' ? 'btn-primary' : 'btn-secondary'}
          style={{ padding: '8px 20px', fontSize: '13.5px' }}
        >
          🏆 淘汰賽對陣圖
        </button>
        <button 
          onClick={() => setSubTab('standings')} 
          className={subTab === 'standings' ? 'btn-primary' : 'btn-secondary'}
          style={{ padding: '8px 20px', fontSize: '13.5px' }}
        >
          📊 小組積分榜
        </button>
        <button 
          onClick={() => setSubTab('results')} 
          className={subTab === 'results' ? 'btn-primary' : 'btn-secondary'}
          style={{ padding: '8px 20px', fontSize: '13.5px' }}
        >
          ⚽ 已完賽比賽
        </button>
      </div>

      {/* 🔮 VIEW 1: TOURNAMENT BRACKET */}
      {subTab === 'bracket' && (
        <div className="glass-card animate-fade-in" style={{ padding: '24px' }}>
          <h3 style={{ fontSize: '18px', fontWeight: 800, marginBottom: '24px', textAlign: 'center' }} className="text-gradient">
            2026 世界盃淘汰賽對陣圖
          </h3>
          
          <div className="bracket-container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'stretch', height: '620px', width: '100%', padding: '10px 0', gap: '10px', overflowX: 'auto' }}>
            
            {/* ===== 左半區 ===== */}
            <div style={{ display: 'flex', gap: '8px', alignItems: 'stretch', flex: 1, justifyContent: 'space-between', height: '100%' }}>
              {/* Left R32 */}
              <div className="bracket-column" style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '90px' }}>
                <h4 style={{ fontSize: '10.5px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px', height: '20px', fontWeight: 800 }}>R32</h4>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-around' }}>
                  {r32Matches.slice(0, 8).map((m, i) => (
                    <div 
                      key={i} 
                      className="glass-card team-item-hover" 
                      onClick={() => m.result && onSelectMatch(m)} 
                      style={{ padding: '5px', width: '100%', cursor: m.result ? 'pointer' : 'default', borderLeft: m.result ? '3px solid var(--accent-blue)' : 'none' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamA ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamA ? 700 : 400 }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamA)}</span>
                        <span>{m.result ? m.result.goalsA : '-'}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamB ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamB ? 700 : 400, marginTop: '2px' }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamB)}</span>
                        <span>{m.result ? m.result.goalsB : '-'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Left R16 */}
              <div className="bracket-column" style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '90px' }}>
                <h4 style={{ fontSize: '10.5px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px', height: '20px', fontWeight: 800 }}>R16</h4>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-around' }}>
                  {r16Matches.slice(0, 4).map((m, i) => (
                    <div 
                      key={i} 
                      className="glass-card team-item-hover" 
                      onClick={() => m.result && onSelectMatch(m)} 
                      style={{ padding: '5px', width: '100%', cursor: m.result ? 'pointer' : 'default', borderLeft: m.result ? '3px solid var(--accent-purple)' : 'none' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamA ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamA ? 700 : 400 }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamA)}</span>
                        <span>{m.result ? m.result.goalsA : '-'}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamB ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamB ? 700 : 400, marginTop: '2px' }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamB)}</span>
                        <span>{m.result ? m.result.goalsB : '-'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Left QF */}
              <div className="bracket-column" style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '90px' }}>
                <h4 style={{ fontSize: '10.5px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px', height: '20px', fontWeight: 800 }}>QF</h4>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-around' }}>
                  {qfMatches.slice(0, 2).map((m, i) => (
                    <div 
                      key={i} 
                      className="glass-card team-item-hover" 
                      onClick={() => m.result && onSelectMatch(m)} 
                      style={{ padding: '5px', width: '100%', cursor: m.result ? 'pointer' : 'default', borderLeft: m.result ? '3px solid var(--accent-pink)' : 'none' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamA ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamA ? 700 : 400 }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamA)}</span>
                        <span>{m.result ? m.result.goalsA : '-'}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamB ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamB ? 700 : 400, marginTop: '2px' }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamB)}</span>
                        <span>{m.result ? m.result.goalsB : '-'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Left SF */}
              <div className="bracket-column" style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '90px' }}>
                <h4 style={{ fontSize: '10.5px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px', height: '20px', fontWeight: 800 }}>SF</h4>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-around' }}>
                  {sfMatches.slice(0, 1).map((m, i) => (
                    <div 
                      key={i} 
                      className="glass-card team-item-hover" 
                      onClick={() => m.result && onSelectMatch(m)} 
                      style={{ padding: '5px', width: '100%', cursor: m.result ? 'pointer' : 'default', borderLeft: m.result ? '4px solid var(--success)' : 'none' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamA ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamA ? 700 : 400 }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamA)}</span>
                        <span>{m.result ? m.result.goalsA : '-'}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamB ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamB ? 700 : 400, marginTop: '2px' }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamB)}</span>
                        <span>{m.result ? m.result.goalsB : '-'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* ===== 中間總決賽與冠軍區 ===== */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '24px', width: '130px', height: '100%' }}>
              <div>
                <h4 style={{ fontSize: '11px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px', fontWeight: 800 }}>決賽 Final</h4>
                {finalMatch ? (
                  <div 
                    className="glass-card team-item-hover glow-active" 
                    onClick={() => finalMatch.result && onSelectMatch(finalMatch)} 
                    style={{ padding: '8px', width: '120px', cursor: finalMatch.result ? 'pointer' : 'default', border: '2px solid var(--accent-blue)', borderRadius: '8px' }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: finalMatch.result?.winner === finalMatch.teamA ? '#fff' : 'var(--text-secondary)', fontWeight: finalMatch.result?.winner === finalMatch.teamA ? 800 : 400 }}>
                      <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(finalMatch.teamA)}</span>
                      <span>{finalMatch.result ? finalMatch.result.goalsA : '-'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: finalMatch.result?.winner === finalMatch.teamB ? '#fff' : 'var(--text-secondary)', fontWeight: finalMatch.result?.winner === finalMatch.teamB ? 800 : 400, marginTop: '8px' }}>
                      <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(finalMatch.teamB)}</span>
                      <span>{finalMatch.result ? finalMatch.result.goalsB : '-'}</span>
                    </div>
                  </div>
                ) : (
                  <div style={{ textAlign: 'center', fontSize: '11px', color: 'var(--text-secondary)', border: '1px dashed rgba(255,255,255,0.1)', padding: '12px', borderRadius: '8px', width: '120px' }}>決賽組合待定</div>
                )}
              </div>
              
              {champion && (
                <div className="glass-card animate-fade-in" style={{ padding: '8px 12px', width: '120px', textAlign: 'center', background: 'linear-gradient(135deg, rgba(250, 204, 21, 0.2) 0%, rgba(251, 191, 36, 0.2) 100%)', border: '1px solid #facc15', borderRadius: '8px' }}>
                  <p style={{ fontSize: '8px', color: '#fef08a', letterSpacing: '1.5px', marginBottom: '4px', fontWeight: 800 }}>🏆 CHAMPION 🏆</p>
                  <h4 style={{ fontSize: '12px', fontWeight: 900, color: '#fef08a' }}>{t(champion)}</h4>
                </div>
              )}
            </div>

            {/* ===== 右半區 ===== */}
            <div style={{ display: 'flex', flexDirection: 'row-reverse', gap: '8px', alignItems: 'stretch', flex: 1, justifyContent: 'space-between', height: '100%' }}>
              {/* Right R32 */}
              <div className="bracket-column" style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '90px' }}>
                <h4 style={{ fontSize: '10.5px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px', height: '20px', fontWeight: 800 }}>R32</h4>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-around' }}>
                  {r32Matches.slice(8, 16).map((m, i) => (
                    <div 
                      key={i} 
                      className="glass-card team-item-hover" 
                      onClick={() => m.result && onSelectMatch(m)} 
                      style={{ padding: '5px', width: '100%', cursor: m.result ? 'pointer' : 'default', borderLeft: m.result ? '3px solid var(--accent-blue)' : 'none' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamA ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamA ? 700 : 400 }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamA)}</span>
                        <span>{m.result ? m.result.goalsA : '-'}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamB ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamB ? 700 : 400, marginTop: '2px' }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamB)}</span>
                        <span>{m.result ? m.result.goalsB : '-'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Right R16 */}
              <div className="bracket-column" style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '90px' }}>
                <h4 style={{ fontSize: '10.5px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px', height: '20px', fontWeight: 800 }}>R16</h4>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-around' }}>
                  {r16Matches.slice(4, 8).map((m, i) => (
                    <div 
                      key={i} 
                      className="glass-card team-item-hover" 
                      onClick={() => m.result && onSelectMatch(m)} 
                      style={{ padding: '5px', width: '100%', cursor: m.result ? 'pointer' : 'default', borderLeft: m.result ? '3px solid var(--accent-purple)' : 'none' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamA ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamA ? 700 : 400 }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamA)}</span>
                        <span>{m.result ? m.result.goalsA : '-'}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamB ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamB ? 700 : 400, marginTop: '2px' }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamB)}</span>
                        <span>{m.result ? m.result.goalsB : '-'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Right QF */}
              <div className="bracket-column" style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '90px' }}>
                <h4 style={{ fontSize: '10.5px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px', height: '20px', fontWeight: 800 }}>QF</h4>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-around' }}>
                  {qfMatches.slice(2, 4).map((m, i) => (
                    <div 
                      key={i} 
                      className="glass-card team-item-hover" 
                      onClick={() => m.result && onSelectMatch(m)} 
                      style={{ padding: '5px', width: '100%', cursor: m.result ? 'pointer' : 'default', borderLeft: m.result ? '3px solid var(--accent-pink)' : 'none' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamA ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamA ? 700 : 400 }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamA)}</span>
                        <span>{m.result ? m.result.goalsA : '-'}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamB ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamB ? 700 : 400, marginTop: '2px' }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamB)}</span>
                        <span>{m.result ? m.result.goalsB : '-'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Right SF */}
              <div className="bracket-column" style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '90px' }}>
                <h4 style={{ fontSize: '10.5px', color: 'var(--text-secondary)', textAlign: 'center', marginBottom: '8px', height: '20px', fontWeight: 800 }}>SF</h4>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-around' }}>
                  {sfMatches.slice(1, 2).map((m, i) => (
                    <div 
                      key={i} 
                      className="glass-card team-item-hover" 
                      onClick={() => m.result && onSelectMatch(m)} 
                      style={{ padding: '5px', width: '100%', cursor: m.result ? 'pointer' : 'default', borderLeft: m.result ? '4px solid var(--success)' : 'none' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamA ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamA ? 700 : 400 }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamA)}</span>
                        <span>{m.result ? m.result.goalsA : '-'}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9.5px', color: m.result?.winner === m.teamB ? '#fff' : 'var(--text-secondary)', fontWeight: m.result?.winner === m.teamB ? 700 : 400, marginTop: '2px' }}>
                        <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{t(m.teamB)}</span>
                        <span>{m.result ? m.result.goalsB : '-'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

          </div>
        </div>
      )}

      {/* 🔮 VIEW 2: GROUP STANDINGS */}
      {subTab === 'standings' && (
        <div className="glass-card animate-fade-in" style={{ padding: '24px' }}>
          <h3 style={{ fontSize: '18px', fontWeight: 800, marginBottom: '20px', textAlign: 'center' }} className="text-gradient">
            2026 世界盃官方分組積分榜
          </h3>
          
          {/* Group Selector A-L */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', justifyContent: 'center', marginBottom: '20px' }}>
            {groups.map(gName => (
              <button 
                key={gName}
                onClick={() => setStandingsGroup(gName)}
                className={standingsGroup === gName ? 'btn-primary' : 'btn-secondary'}
                style={{ padding: '6px 14px', fontSize: '12px' }}
              >
                Group {gName}
              </button>
            ))}
          </div>

          {/* Group Table */}
          <div className="table-responsive">
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid rgba(255,255,255,0.1)', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '12px 8px', width: '60px' }}>排名</th>
                  <th style={{ padding: '12px 8px' }}>球隊</th>
                  <th style={{ padding: '12px 8px', width: '80px', textAlign: 'center' }}>已賽</th>
                  <th style={{ padding: '12px 8px', width: '60px', textAlign: 'center' }}>勝</th>
                  <th style={{ padding: '12px 8px', width: '60px', textAlign: 'center' }}>平</th>
                  <th style={{ padding: '12px 8px', width: '60px', textAlign: 'center' }}>負</th>
                  <th style={{ padding: '12px 8px', width: '80px', textAlign: 'center' }}>進/失球</th>
                  <th style={{ padding: '12px 8px', width: '80px', textAlign: 'center' }}>淨勝球</th>
                  <th style={{ padding: '12px 8px', width: '80px', textAlign: 'center', fontWeight: 'bold', color: 'var(--accent-blue)' }}>積分</th>
                </tr>
              </thead>
              <tbody>
                {groupStandings[standingsGroup]?.map((row, idx) => (
                  <tr 
                    key={row.team} 
                    style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', verticalAlign: 'middle' }}
                    className="team-item-hover"
                  >
                    <td style={{ padding: '14px 8px', fontWeight: 800, color: idx < 2 ? 'var(--accent-blue)' : (idx === 2 ? 'var(--accent-purple)' : 'var(--text-secondary)') }}>
                      {idx + 1}
                      {idx < 2 && <span style={{ fontSize: '10px', marginLeft: '4px', verticalAlign: 'middle' }}>晉級</span>}
                    </td>
                    <td 
                      style={{ padding: '14px 8px', cursor: 'pointer', fontWeight: 600 }}
                      onClick={() => onSelectTeam(teams[row.team])}
                    >
                      {t(row.team)}
                      <span style={{ fontSize: '10px', color: 'var(--text-secondary)', marginLeft: '8px' }}>
                        OVR {row.avg_rating.toFixed(0)}
                      </span>
                    </td>
                    <td style={{ padding: '14px 8px', textAlign: 'center' }}>{row.played}</td>
                    <td style={{ padding: '14px 8px', textAlign: 'center', color: row.wins > 0 ? '#fff' : 'var(--text-secondary)' }}>{row.wins}</td>
                    <td style={{ padding: '14px 8px', textAlign: 'center', color: row.draws > 0 ? '#fff' : 'var(--text-secondary)' }}>{row.draws}</td>
                    <td style={{ padding: '14px 8px', textAlign: 'center', color: row.losses > 0 ? '#fff' : 'var(--text-secondary)' }}>{row.losses}</td>
                    <td style={{ padding: '14px 8px', textAlign: 'center', color: 'var(--text-secondary)' }}>{row.gs} - {row.gc}</td>
                    <td style={{ padding: '14px 8px', textAlign: 'center', color: row.gd > 0 ? 'var(--success)' : (row.gd < 0 ? 'var(--accent-pink)' : 'var(--text-secondary)') }}>
                      {row.gd > 0 ? `+${row.gd}` : row.gd}
                    </td>
                    <td style={{ padding: '14px 8px', textAlign: 'center', fontWeight: 'bold', fontSize: '15px', color: 'var(--accent-blue)' }}>{row.points}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: '16px', fontSize: '11px', color: 'var(--text-secondary)', display: 'flex', gap: '16px' }}>
            <span>🔵 前二名：直接晉級 32 強</span>
            <span>🟣 最好的 8 個第三名：亦可晉級 32 強</span>
          </div>
        </div>
      )}

      {/* 🔮 VIEW 3: MATCH RESULTS */}
      {subTab === 'results' && (
        <section className="results-page glass-card animate-fade-in">
          <header className="results-page-header">
            <div>
              <p className="eyebrow">MATCH CENTRE</p>
              <h2>2026 世界盃賽程與賽果</h2>
            </div>
            <span>{realGames.filter((match) => match.finished === 'TRUE' || match.finished === true).length} 場已完賽</span>
          </header>

          <div className="results-date-list">
            {resultGroups.map(([date, matchesOnDate]) => (
              <section className="result-date-group" key={date}>
                <header>
                  <h3>{date}</h3>
                  <span>{matchesOnDate.length} 場比賽</span>
                </header>
                <div className="result-rows">
                  {matchesOnDate.map((mapped) => {
                    const isFinished = mapped.finished === 'TRUE' || mapped.finished === true || mapped.time_elapsed === 'finished';
                    const isLive = mapped.time_elapsed === 'live';
                    const time = toTaiwanTime(mapped.local_date).split(' ')[1] || '—';
                    const stage = mapped.type === 'group' ? `${mapped.group || '—'}組` : (mapped.group || mapped.type || '淘汰賽');
                    return (
                      <button
                        type="button"
                        key={mapped.id}
                        className={`match-result-row${isFinished ? ' finished' : ''}${isLive ? ' live' : ''}`}
                        onClick={() => isFinished && onSelectMatch(mapped)}
                        disabled={!isFinished}
                        aria-label={isFinished ? `查看比賽詳情：${t(mapped.teamA)} 對 ${t(mapped.teamB)}，比分 ${mapped.goalsA} 比 ${mapped.goalsB}` : undefined}
                      >
                        <span className="result-kickoff"><strong>{time}</strong><small>{stage}</small></span>
                        <span className="result-teams">
                          <span className={mapped.result?.winner === mapped.teamA ? 'winner' : ''}>{t(mapped.teamA)}</span>
                          <span className={mapped.result?.winner === mapped.teamB ? 'winner' : ''}>{t(mapped.teamB)}</span>
                        </span>
                        <span className="result-score" aria-label={isFinished ? `實際比分 ${mapped.goalsA} 比 ${mapped.goalsB}` : '尚未開賽'}>
                          <strong>{isFinished ? mapped.goalsA : '–'}</strong>
                          <strong>{isFinished ? mapped.goalsB : '–'}</strong>
                        </span>
                        <span className={`result-state ${isLive ? 'live' : ''}`}>{isLive ? 'LIVE' : isFinished ? '完賽' : '未賽'}</span>
                        <span className="result-row-arrow" aria-hidden="true">›</span>
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </section>
      )}

    </div>
  );
}
