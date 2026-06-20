import { TEAM_TRANSLATIONS } from '../utils/constants';

const label = (name) => {
  const team = TEAM_TRANSLATIONS[name] || { flag: '🏳️', cn: name };
  return `${team.flag} ${team.cn}`;
};

function ModalShell({ children, onClose, title, panelClassName = '', backdropClassName = '' }) {
  return (
    <div className={`modal-backdrop ${backdropClassName}`.trim()} role="presentation" onMouseDown={onClose}>
      <section className={`modal-panel glass-card ${panelClassName}`.trim()} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" aria-label="關閉" onClick={onClose}>×</button>
        {children}
      </section>
    </div>
  );
}

export function ScoreMatrixModal({ prediction, open, onClose }) {
  if (!open || !prediction) return null;
  const model = prediction.model;
  return (
    <ModalShell onClose={onClose} title="完整比分機率矩陣">
      <p className="eyebrow">DIXON-COLES · BIVARIATE POISSON</p>
      <h2>📊 0–5 完整比分機率矩陣</h2>
      <p>{label(prediction.home)} vs {label(prediction.away)} · 合計 100%</p>
      <div className="matrix-table-wrap">
        <table className="matrix-table">
          <thead><tr><th>主\客</th>{[0, 1, 2, 3, 4, 5].map((goal) => <th key={goal}>{goal}</th>)}</tr></thead>
          <tbody>
            {[0, 1, 2, 3, 4, 5].map((homeGoal) => (
              <tr key={homeGoal}>
                <th>{homeGoal}</th>
                {[0, 1, 2, 3, 4, 5].map((awayGoal) => {
                  const score = model.score_matrix.find((item) => item.home === homeGoal && item.away === awayGoal);
                  const outcome = homeGoal > awayGoal ? 'home' : homeGoal < awayGoal ? 'away' : 'draw';
                  return <td className={outcome} key={awayGoal}>{score?.probability.toFixed(1)}%</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button className="btn-primary modal-action" onClick={onClose}>關閉視窗</button>
    </ModalShell>
  );
}

export function MatchDetailModal({ selectedMatch, prediction, review, loading, onClose }) {
  if (!selectedMatch) return null;
  const finished = selectedMatch.finished === 'TRUE' || selectedMatch.finished === true;
  const stats = selectedMatch.stats || {};
  const primaryStatsComplete = ['xgA', 'xgB', 'possessionA', 'possessionB', 'shotsA', 'shotsB']
    .every((key) => stats[key] !== null && typeof stats[key] !== 'undefined');
  const model = prediction?.model;
  const actualHome = Number(selectedMatch.home_score || 0);
  const actualAway = Number(selectedMatch.away_score || 0);
  const actualOutcome = actualHome > actualAway ? 'home' : actualHome < actualAway ? 'away' : 'draw';
  const predictedOutcome = model
    ? Object.entries(model.probabilities).sort(([, a], [, b]) => b - a)[0][0]
    : null;
  const directionHit = predictedOutcome ? predictedOutcome === actualOutcome : null;
  const scoreHit = model
    ? Number(model.predicted_score.home) === actualHome && Number(model.predicted_score.away) === actualAway
    : null;
  return (
    <ModalShell onClose={onClose} title="比賽詳情" panelClassName="match-detail-panel" backdropClassName="match-detail-backdrop">
      <header className="match-detail-header">
        <div>
          <p className="eyebrow">MATCH #{selectedMatch.id} · {selectedMatch.group ? `${selectedMatch.group}組` : selectedMatch.type}</p>
          <h2>比賽詳情</h2>
        </div>
        <span className="match-finished-badge">{finished ? '完賽' : '未賽'}</span>
      </header>

      <div className="detail-scoreboard">
        <div><span>{label(selectedMatch.home_team_name_en)}</span><strong>{finished ? selectedMatch.home_score : '—'}</strong></div>
        <span className="detail-score-separator">:</span>
        <div><span>{label(selectedMatch.away_team_name_en)}</span><strong>{finished ? selectedMatch.away_score : '—'}</strong></div>
      </div>

      {loading && <div className="detail-loading">正在載入賽前預測與賽後檢討…</div>}

      {model && (
        <section className="detail-prediction-section">
          <div className="detail-section-heading">
            <div><span>原始模型預測</span><strong>{model.predicted_score.home}:{model.predicted_score.away}</strong></div>
            <div className="hit-status-list">
              <span className={directionHit ? 'hit' : 'miss'} aria-label={`勝負方向${directionHit ? '命中' : '未命中'}`}>{directionHit ? '✓' : '×'} 勝負方向{directionHit ? '命中' : '未命中'}</span>
              <span className={scoreHit ? 'hit' : 'miss'} aria-label={`比分${scoreHit ? '命中' : '未命中'}`}>{scoreHit ? '✓' : '×'} 比分{scoreHit ? '命中' : '未命中'}</span>
            </div>
          </div>
          <div className="detail-probabilities">
            <div><span>主勝</span><strong>{model.probabilities.home.toFixed(1)}%</strong></div>
            <div><span>和局</span><strong>{model.probabilities.draw.toFixed(1)}%</strong></div>
            <div><span>客勝</span><strong>{model.probabilities.away.toFixed(1)}%</strong></div>
          </div>
        </section>
      )}

      {finished && (
        <section className="detail-stats-section">
          <div className="detail-section-title"><span>比賽數據</span><small>主隊 : 客隊</small></div>
          {!primaryStatsComplete && <p className="detail-stats-unavailable">資料來源尚未提供完整數據</p>}
          <div className="stats-grid">
            <div><span>預期進球 xG</span><strong>{stats.xgA ?? '—'} : {stats.xgB ?? '—'}</strong><small>依射門品質估算的預期進球</small></div>
            <div><span>控球</span><strong>{stats.possessionA ?? '—'}% : {stats.possessionB ?? '—'}%</strong></div>
            <div><span>射門</span><strong>{stats.shotsA ?? '—'} : {stats.shotsB ?? '—'}</strong></div>
            <div><span>黃紅牌</span><strong>{stats.cardsA ?? '—'} : {stats.cardsB ?? '—'}</strong></div>
          </div>
        </section>
      )}

      {finished && (
        <section className="review-summary">
          <p className="eyebrow">賽後模型檢討</p>
          <h3>{review?.failure_type ? `失準分類：${review.failure_type}` : '賽後檢討'}</h3>
          <p>{review?.review || review?.summary || '尚無完整賽後檢討；目前先保留真實比分、基礎統計與賽前預測供比較。'}</p>
        </section>
      )}
      <button className="btn-primary modal-action" onClick={onClose}>關閉詳情</button>
    </ModalShell>
  );
}

export function TeamRosterModal({ selectedTeam, onClose }) {
  if (!selectedTeam) return null;
  const players = [...(selectedTeam.players || [])].sort((a, b) => b.overall - a.overall);
  return (
    <ModalShell onClose={onClose} title="國家隊名單">
      <p className="eyebrow">FC26 PLAYER DATABASE</p>
      <h2>{label(selectedTeam.team_name)} 國家隊名單</h2>
      <p>先發 PQS {selectedTeam.starting_pqs?.toFixed(2)} · 替補 PQS {selectedTeam.bench_pqs?.toFixed(2)} · 身價 €{selectedTeam.market_value_million_eur?.toFixed(1)}M</p>
      <div className="roster-list">
        {players.map((player) => (
          <div key={`${player.name}-${player.position}`}>
            <span>{player.position}</span><strong>{player.name}</strong><b>{player.overall}</b>
          </div>
        ))}
      </div>
      <button className="btn-primary modal-action" onClick={onClose}>關閉視窗</button>
    </ModalShell>
  );
}
