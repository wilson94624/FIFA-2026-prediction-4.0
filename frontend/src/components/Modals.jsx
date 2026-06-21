import { TeamLabel } from './Flag';

const OUTCOME_LABELS = { home: '主勝', draw: '和局', away: '客勝' };

function reviewMetrics(model, actualHome, actualAway) {
  if (!model) return null;
  const probabilities = model.probabilities || {};
  const sortedOutcomes = Object.entries(probabilities).sort(([, a], [, b]) => Number(b) - Number(a));
  const probabilityGap = Number(sortedOutcomes[0]?.[1] || 0) - Number(sortedOutcomes[1]?.[1] || 0);
  const confidence = probabilityGap >= 25
    ? { label: '高', note: `領先次高選項 ${probabilityGap.toFixed(1)} 個百分點`, tone: 'high' }
    : probabilityGap >= 12
      ? { label: '中', note: `領先次高選項 ${probabilityGap.toFixed(1)} 個百分點`, tone: 'medium' }
      : { label: '低', note: `前兩個選項僅差 ${probabilityGap.toFixed(1)} 個百分點`, tone: 'low' };
  const rankedScores = [...(model.score_matrix || [])]
    .sort((a, b) => Number(b.probability) - Number(a.probability));
  const actualScoreIndex = rankedScores.findIndex(
    (score) => Number(score.home) === actualHome && Number(score.away) === actualAway,
  );
  const actualScore = actualScoreIndex >= 0 ? rankedScores[actualScoreIndex] : null;
  const rank = actualScoreIndex >= 0 ? actualScoreIndex + 1 : null;
  const scoreProbability = actualScore ? Number(actualScore.probability) : null;
  const surpriseStars = rank === null ? 5
    : rank <= 3 && scoreProbability >= 8 ? 1
      : rank <= 8 && scoreProbability >= 4 ? 2
        : rank <= 16 ? 3
          : rank <= 28 ? 4 : 5;
  const mainOutcome = sortedOutcomes[0]?.[0];
  const advantage = mainOutcome === 'draw'
    ? '雙方接近，和局是最高機率結果'
    : `${mainOutcome === 'home' ? '主隊' : '客隊'}較有優勢（${Number(probabilities[mainOutcome]).toFixed(1)}%）`;

  return { confidence, rank, scoreProbability, surpriseStars, mainOutcome, advantage };
}

function isGenericReview(review) {
  return /Random Football Variance|隨機波動|實際結果仍位於模型保留的機率分布內/i.test(
    `${review?.failure_type || ''} ${review?.review || review?.summary || ''}`,
  );
}

function buildFailureAnalysis({ model, stats, actualHome, actualAway, directionHit, scoreHit, review }) {
  const supplied = review?.review || review?.summary;
  const genericReview = isGenericReview(review);
  if (supplied && !genericReview) return supplied;
  if (scoreHit) return '模型同時命中勝負方向與正確比分，本場賽事走勢與賽前機率分布的中心一致。';

  const expectedHome = Number(model?.expected_goals?.home);
  const expectedAway = Number(model?.expected_goals?.away);
  const actualXgHome = Number(stats.xgA);
  const actualXgAway = Number(stats.xgB);
  const hasExpected = Number.isFinite(expectedHome) && Number.isFinite(expectedAway);
  const hasActualXg = Number.isFinite(actualXgHome) && Number.isFinite(actualXgAway);
  const notes = [];

  if (!directionHit && hasExpected && hasActualXg && (expectedHome - expectedAway) * (actualXgHome - actualXgAway) < 0) {
    notes.push('實際創造機會的優勢方與模型賽前預期相反，顯示比賽的進攻主導權發生偏移');
  } else if (hasActualXg) {
    const homeEfficiency = actualHome - actualXgHome;
    const awayEfficiency = actualAway - actualXgAway;
    if (Math.abs(homeEfficiency) >= 0.75 || Math.abs(awayEfficiency) >= 0.75) {
      const efficientSide = homeEfficiency > awayEfficiency ? '主隊' : '客隊';
      notes.push(`${efficientSide}的實際進球明顯高於 xG，臨門效率放大了比分偏差`);
    }
    if ((actualHome === 0 && actualXgHome >= 1) || (actualAway === 0 && actualXgAway >= 1)) {
      notes.push('至少一方創造出足夠機會卻未能轉化為進球，射門效率低於正常預期');
    }
  }

  if (Number(stats.cardsA) >= 4 || Number(stats.cardsB) >= 4) {
    notes.push('較多牌張可能改變防守強度、壓迫節奏與後續換人策略');
  }
  if (!notes.length && !directionHit) {
    notes.push('勝負方向偏離賽前最可能情境，主要差異來自單場攻防執行與關鍵機會轉化，而不是模型完全排除這個結果');
  } else if (!notes.length) {
    notes.push('勝負方向雖然命中，但進球數偏離分布中心，較可能是臨門效率或個別防守事件造成的比分誤差');
  }
  return `${notes.join('；')}。${review?.reasons?.length ? ` 模型紀錄：${review.reasons.join('；')}。` : ''}`;
}

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
      <p><TeamLabel name={prediction.home} /> vs <TeamLabel name={prediction.away} /> · 合計 100%</p>
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
  const metrics = finished ? reviewMetrics(model, actualHome, actualAway) : null;
  const failureAnalysis = finished && model
    ? buildFailureAnalysis({ model, stats, actualHome, actualAway, directionHit, scoreHit, review })
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
        <div><span><TeamLabel name={selectedMatch.home_team_name_en} /></span><strong>{finished ? selectedMatch.home_score : '—'}</strong></div>
        <span className="detail-score-separator">:</span>
        <div><span><TeamLabel name={selectedMatch.away_team_name_en} /></span><strong>{finished ? selectedMatch.away_score : '—'}</strong></div>
      </div>

      {loading && <div className="detail-loading">正在載入賽前預測與賽後檢討…</div>}

      {model && !finished && (
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

      {finished && model && metrics && (
        <section className="post-match-review" aria-labelledby="post-match-review-title">
          <div className="review-header">
            <div>
              <p className="eyebrow">POST-MATCH MODEL REVIEW</p>
              <h3 id="post-match-review-title">賽後模型檢討</h3>
            </div>
            <span className={`review-verdict ${directionHit ? 'hit' : 'miss'}`}>
              {directionHit ? '方向命中' : '預測失準'}
            </span>
          </div>

          <section className="review-block review-overview" aria-labelledby="review-summary-title">
            <div className="review-block-title">
              <span>01</span><div><h4 id="review-summary-title">預測摘要</h4><p>模型原本怎麼看，結果又如何</p></div>
            </div>
            <div className="review-summary-grid">
              <div><span>預測比分</span><strong>{model.predicted_score.home}:{model.predicted_score.away}</strong></div>
              <div><span>實際比分</span><strong>{actualHome}:{actualAway}</strong></div>
              <div aria-label={`勝負方向${directionHit ? '命中' : '未命中'}`}><span>勝負方向</span><strong className={directionHit ? 'positive' : 'negative'}>{directionHit ? '命中' : '未命中'}</strong></div>
              <div aria-label={`比分${scoreHit ? '命中' : '未命中'}`}><span>正確比分</span><strong className={scoreHit ? 'positive' : 'negative'}>{scoreHit ? '命中' : '未命中'}</strong></div>
              <div className="review-confidence">
                <span>賽前信心</span><strong>{metrics.confidence.label}</strong>
                <small>{metrics.confidence.note}</small>
              </div>
            </div>
          </section>

          <div className="review-two-column">
            <section className="review-block surprise-card" aria-labelledby="surprise-title">
              <div className="review-block-title compact">
                <span>02</span><div><h4 id="surprise-title">結果意外程度</h4><p>實際比分在分布中的罕見程度</p></div>
              </div>
              <div className="surprise-rating" aria-label={`意外程度 ${metrics.surpriseStars} 星（滿分 5 星）`}>
                <strong>{'★'.repeat(metrics.surpriseStars)}<i>{'★'.repeat(5 - metrics.surpriseStars)}</i></strong>
                <span>{metrics.surpriseStars}/5</span>
              </div>
              <dl className="review-data-list">
                <div><dt>實際比分機率</dt><dd>{metrics.scoreProbability === null ? '低於矩陣範圍' : `${metrics.scoreProbability.toFixed(2)}%`}</dd></div>
                <div><dt>比分矩陣排名</dt><dd>{metrics.rank ? `第 ${metrics.rank} / ${model.score_matrix.length} 名` : '0–5 矩陣外'}</dd></div>
              </dl>
            </section>

            <section className="review-block" aria-labelledby="prematch-title">
              <div className="review-block-title compact">
                <span>03</span><div><h4 id="prematch-title">模型賽前認知</h4><p>賽前分布的核心判斷</p></div>
              </div>
              <div className="expected-goals-row">
                <span>預期進球</span>
                <strong>{model.expected_goals.home.toFixed(2)} <i>:</i> {model.expected_goals.away.toFixed(2)}</strong>
              </div>
              <div className="review-probabilities">
                {['home', 'draw', 'away'].map((outcome) => (
                  <div key={outcome} className={metrics.mainOutcome === outcome ? 'primary' : ''}>
                    <span>{OUTCOME_LABELS[outcome]}</span><strong>{Number(model.probabilities[outcome]).toFixed(1)}%</strong>
                  </div>
                ))}
              </div>
              <p className="advantage-note"><span>主要優勢方</span>{metrics.advantage}</p>
            </section>
          </div>

          <section className="review-block failure-analysis" aria-labelledby="failure-title">
            <div className="review-block-title compact">
              <span>04</span><div><h4 id="failure-title">失準分析</h4><p>進攻、防守與效率如何拉開預期</p></div>
            </div>
            <p>{failureAnalysis}</p>
            {isGenericReview(review) && (review?.review || review?.summary) && (
              <p className="legacy-review-note">{review.review || review.summary}</p>
            )}
            {review?.failure_type && <span className="failure-tag">模型分類 · {review.failure_type}</span>}
          </section>

          <section className="review-block matrix-position" aria-labelledby="matrix-position-title">
            <div className="review-block-title compact">
              <span>05</span><div><h4 id="matrix-position-title">模型是否考慮過這個結果</h4><p>實際比分在賽前 0–5 機率矩陣的位置</p></div>
            </div>
            <div className="matrix-position-content">
              <div className="mini-score-matrix" aria-label={`實際比分 ${actualHome} 比 ${actualAway} 在賽前比分矩陣中的位置`}>
                {[0, 1, 2, 3, 4, 5].map((homeGoal) => [0, 1, 2, 3, 4, 5].map((awayGoal) => (
                  <span
                    key={`${homeGoal}-${awayGoal}`}
                    className={homeGoal === actualHome && awayGoal === actualAway ? 'actual' : ''}
                    title={`${homeGoal}:${awayGoal}`}
                  />
                )))}
              </div>
              <div className="matrix-position-copy">
                <strong>{metrics.scoreProbability === null ? '矩陣範圍外' : '有，模型納入此結果'}</strong>
                <p>主隊 {actualHome} 球 × 客隊 {actualAway} 球</p>
                <div><span>賽前機率</span><b>{metrics.scoreProbability === null ? '—' : `${metrics.scoreProbability.toFixed(2)}%`}</b></div>
                <div><span>矩陣排名</span><b>{metrics.rank ? `#${metrics.rank}` : '—'}</b></div>
              </div>
            </div>
          </section>

          <section className="review-block observation-placeholder" aria-labelledby="observation-title">
            <div className="review-block-title compact">
              <span>06</span><div><h4 id="observation-title">模型觀察</h4><p>跨場趨勢與持續校準</p></div>
            </div>
            <div className="observation-empty">
              <div><span>COMING SOON</span><strong>近期失準模式累積中</strong></div>
              <p>未來將彙整最近 N 場的進攻、效率、防守與特殊事件偏差，協助辨識模型的系統性盲點。</p>
            </div>
          </section>
        </section>
      )}
      {finished && !model && !loading && (
        <section className="review-summary"><h3>賽後模型檢討</h3><p>目前找不到這場比賽的賽前預測快照，因此無法重建機率矩陣與失準原因。</p></section>
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
      <h2><TeamLabel name={selectedTeam.team_name} /> 國家隊名單</h2>
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
