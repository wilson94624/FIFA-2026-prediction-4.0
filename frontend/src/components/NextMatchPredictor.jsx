import { useMemo, useRef, useState } from 'react';
import { formatTaiwanTime, toTaiwanTime } from '../utils/constants';
import ChampionshipOdds from './ChampionshipOdds';
import { TeamLabel } from './Flag';
import { ScoreMatrixModal } from './Modals';

const scoreLabel = (score) => `${score.home} : ${score.away}`;

function ScoreColumn({ title, scores, tone }) {
  const maximum = scores?.[0]?.probability || 1;
  return (
    <section className={`score-column ${tone}`}>
      <h4>{title}</h4>
      {(scores || []).map((score) => (
        <div className="score-row" key={`${score.home}-${score.away}`}>
          <strong>{scoreLabel(score)}</strong>
          <div className="score-track"><span style={{ width: `${score.probability / maximum * 100}%` }} /></div>
          <span>{score.probability.toFixed(1)}%</span>
        </div>
      ))}
    </section>
  );
}

const riskLabel = { High: '高', Medium: '中', Low: '低' };

function RiskBadge({ label, level, percentage }) {
  const translatedLevel = riskLabel[level] || level;
  return (
    <span className={`risk-badge ${level.toLowerCase()}`}>
      {label}：{translatedLevel}{percentage == null ? '' : `（${percentage.toFixed(1)}%）`}
    </span>
  );
}

function AvailabilityCard({ match, prediction }) {
  const predictionAvailability = prediction.availability;
  const matchAvailability = match?.stats?.unavailable_players;
  const sourceAvailable = Boolean(predictionAvailability || matchAvailability);
  const predictionSide = (side) => {
    const data = predictionAvailability?.[side];
    if (!data) return null;
    return [
      ...(data.unavailable || []),
      ...(data.injuries || []).map((player) => ({ ...player, type: player.type || 'injury' })),
      ...(data.suspensions || []).map((player) => ({ ...player, type: 'suspension' })),
    ];
  };
  const sides = {
    home: predictionSide('home') || matchAvailability?.home || [],
    away: predictionSide('away') || matchAvailability?.away || [],
  };
  const renderSide = (side, title) => (
    <div>
      <h4>{title}</h4>
      {sides[side].length ? sides[side].map((player) => (
        <div className="availability-player" key={`${side}-${player.name}`}>
          <strong>{player.name}</strong>
          <span className={player.type === 'suspension' ? 'suspension' : 'injury'}>
            {player.type === 'suspension' ? '停賽' : '受傷'}
          </span>
        </div>
      )) : <p>目前沒有已知傷停</p>}
    </div>
  );
  return (
    <section className="glass-card availability-card">
      <div className="section-heading-row">
        <div><p className="eyebrow">球員出賽狀況</p><h3>傷停名單</h3></div>
        <span className="freshness">不確定名單將持續更新</span>
      </div>
      {sourceAvailable ? (
        <div className="availability-grid">
          {renderSide('home', <><TeamLabel name={prediction.home} /> 缺陣</>)}
          {renderSide('away', <><TeamLabel name={prediction.away} /> 缺陣</>)}
        </div>
      ) : <p className="availability-unavailable">傷停資料暫時無法取得</p>}
    </section>
  );
}

const outcomeForScore = (score) => (
  score.home > score.away ? 'home' : score.home < score.away ? 'away' : 'draw'
);

const marketPopularScores = (model, consensus) => {
  const matrix = model.score_matrix || [];
  const modelOutcomeTotals = matrix.reduce((totals, score) => {
    const outcome = outcomeForScore(score);
    totals[outcome] += Number(score.probability) || 0;
    return totals;
  }, { home: 0, draw: 0, away: 0 });

  return matrix
    .map((score) => {
      const outcome = outcomeForScore(score);
      const outcomeTotal = modelOutcomeTotals[outcome];
      return {
        ...score,
        marketProbability: outcomeTotal > 0
          ? (Number(score.probability) || 0) * Number(consensus[outcome]) / outcomeTotal
          : 0,
      };
    })
    .sort((left, right) => right.marketProbability - left.marketProbability)
    .slice(0, 3);
};

const marketDifferenceDisplay = (value) => {
  const normalized = Math.abs(value) < 0.05 ? 0 : value;
  const pp = normalized === 0
    ? '±0.0pp'
    : `${normalized > 0 ? '+' : ''}${normalized.toFixed(1)}pp`;
  if (normalized >= 1) return { label: '市場高估', pp, tone: 'overestimate' };
  if (normalized <= -1) return { label: '市場低估', pp, tone: 'underestimate' };
  return { label: '市場接近', pp, tone: 'close' };
};

const marketVerdict = (outcomes) => {
  const maximumDifference = Math.max(...outcomes.map(({ difference }) => Math.abs(difference)));
  if (maximumDifference <= 3) {
    return {
      tone: 'aligned',
      label: '高度一致',
      title: '模型與市場看法一致',
      description: '三種結果的差距都在 3 個百分點內，市場沒有提出明顯反向訊號。',
      maximumDifference,
    };
  }
  if (maximumDifference <= 8) {
    return {
      tone: 'watch',
      label: '輕微分歧',
      title: '大方向一致，細節有落差',
      description: '主要判斷沒有翻轉，但部分結果的市場機率與模型已有可見差距。',
      maximumDifference,
    };
  }
  return {
    tone: 'divergent',
    label: '明顯分歧',
    title: '模型與市場看法不同',
    description: '至少一種結果相差超過 8 個百分點，值得優先檢查市場是否掌握額外資訊。',
    maximumDifference,
  };
};

const marketOutcomeLabel = (key, prediction) => (
  key === 'home'
    ? <TeamLabel name={prediction.home} />
    : key === 'away'
      ? <TeamLabel name={prediction.away} />
      : '和局'
);

function MarketEvidence({ prediction }) {
  const market = prediction.market_evidence;
  const hasConsensus = ['home', 'draw', 'away'].every(
    (key) => Number.isFinite(Number(market?.consensus?.[key])),
  );
  if (!market?.available || !hasConsensus) {
    return (
      <section className="glass-card market-card unavailable">
        <div>
          <p className="eyebrow">EXTERNAL EVIDENCE</p>
          <h3>目前沒有可用的市場資料</h3>
        </div>
        <p>市場共識僅作為外部參考，模型預測仍可正常使用。</p>
      </section>
    );
  }
  const outcomes = ['home', 'draw', 'away'].map((key) => {
    const marketValue = Number(market.consensus[key]);
    const modelValue = Number(prediction.model.probabilities[key]);
    return { key, marketValue, modelValue, difference: marketValue - modelValue };
  });
  const verdict = marketVerdict(outcomes);
  const rankedOutcomes = [...outcomes].sort(
    (left, right) => Math.abs(right.difference) - Math.abs(left.difference),
  );
  const popularScores = marketPopularScores(prediction.model, market.consensus);
  return (
    <section className="glass-card market-card">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">EXTERNAL EVIDENCE · {market.bookmaker_count} BOOKMAKERS</p>
          <h3>市場共識</h3>
        </div>
        <span className="freshness">
          更新 {formatTaiwanTime(market.last_update) || '—'}
          {market.locked ? ' · 已於開賽前鎖定' : ''}
        </span>
      </div>
      <div className={`market-verdict ${verdict.tone}`}>
        <div className="market-signal" aria-label={`市場信號：${verdict.label}`}>
          <span className="market-signal-light" aria-hidden="true" />
          <strong>{verdict.label}</strong>
        </div>
        <div className="market-verdict-copy">
          <h4>{verdict.title}</h4>
          <p>{verdict.description}</p>
        </div>
        <div className="market-gap-score">
          <span>最大差距</span>
          <strong>{verdict.maximumDifference.toFixed(1)}</strong>
          <small>百分點</small>
        </div>
      </div>
      <div className="market-ranking-heading">
        <strong>分歧排行</strong>
        <span><i className="model-key" />模型 <i className="market-key" />市場</span>
      </div>
      <div className="market-ranking">
        {rankedOutcomes.map(({ key, marketValue, modelValue, difference }, index) => {
          const differenceDisplay = marketDifferenceDisplay(difference);
          return (
            <div className="market-rank-row" key={key}>
              <span className="market-rank-number">{index + 1}</span>
              <strong className="market-outcome-title">{marketOutcomeLabel(key, prediction)}</strong>
              <div className="market-paired-bars">
                <div><span style={{ width: `${modelValue}%` }} /><b>{modelValue.toFixed(1)}%</b></div>
                <div><span style={{ width: `${marketValue}%` }} /><b>{marketValue.toFixed(1)}%</b></div>
              </div>
              <p className={`market-difference-label ${differenceDisplay.tone}`}>
                <span>{differenceDisplay.label}</span>
                <strong>{differenceDisplay.pp}</strong>
              </p>
            </div>
          );
        })}
      </div>
      {popularScores.length > 0 && (
        <div className="market-popular-scores">
          <strong>市場熱門比分</strong>
          <div>
            {popularScores.map((score) => (
              <span key={`${score.home}-${score.away}`}>{score.home}:{score.away}</span>
            ))}
          </div>
          <small>依市場 1X2 機率與模型比分條件分布換算</small>
        </div>
      )}
      <p className="disclaimer">市場資料僅作外部證據，不會取代模型主值。</p>
    </section>
  );
}

export default function NextMatchPredictor({ loading, predictions, championship, teams, matches = [], onViewChampionship }) {
  const [selectedId, setSelectedId] = useState(null);
  const [showMatrix, setShowMatrix] = useState(false);
  const [sharing, setSharing] = useState(false);
  const shareRef = useRef(null);
  const selected = useMemo(
    () => predictions.find((item) => item.match_id === selectedId) || predictions[0],
    [predictions, selectedId],
  );

  if (loading) return <main className="loading-panel">正在向模型 API 取得預測…</main>;
  if (!selected) {
    return <main className="loading-panel">🏁 目前沒有已確定對戰的未完賽賽程。</main>;
  }

  const model = selected.model;
  const homeTeam = teams[selected.home] || {};
  const awayTeam = teams[selected.away] || {};
  const selectedMatch = matches.find((match) => String(match.id) === String(selected.match_id));
  const top = model.top_scores;
  const generatedAt = selected.metadata?.fetched_at
    ? formatTaiwanTime(selected.metadata.fetched_at)
    : formatTaiwanTime(new Date());
  const handleShare = async () => {
    if (!shareRef.current || sharing) return;
    setSharing(true);
    try {
      const { default: html2canvas } = await import('html2canvas');
      const canvas = await html2canvas(shareRef.current, {
        backgroundColor: '#0b1021',
        width: 1080,
        height: 1350,
        windowWidth: 1080,
        windowHeight: 1350,
        scale: 1,
        useCORS: true,
      });
      const link = document.createElement('a');
      link.download = `predictor-4-${selected.match_id}.png`;
      link.href = canvas.toDataURL('image/png');
      link.click();
    } finally {
      setSharing(false);
    }
  };

  return (
    <main className="prediction-layout page-container">
      <aside className="upcoming-sidebar">
        <h3>📅 即將進行的賽程</h3>
        <div className="upcoming-list">
          {predictions.map((item) => (
            <button
              key={item.match_id}
              className={item.match_id === selected.match_id ? 'upcoming-card active' : 'upcoming-card'}
              onClick={() => setSelectedId(item.match_id)}
            >
              <span>Match #{item.match_id} · {item.group ? `${item.group}組` : item.stage}</span>
              <strong className="upcoming-match-teams"><TeamLabel name={item.home} /> <i>vs</i> <TeamLabel name={item.away} /></strong>
              <small>{toTaiwanTime(item.local_date)}</small>
            </button>
          ))}
        </div>
      </aside>

      <div className="prediction-content">
        <section className="glass-card prediction-hero">
          <div className="prediction-card-header">
            <div className="match-context">
              <span>{selected.group ? `${selected.group}組小組賽` : selected.stage}</span>
              <span>Match #{selected.match_id}</span>
            </div>
            <time dateTime={selected.local_date}>臺灣時間 {toTaiwanTime(selected.local_date)}</time>
            <button
              className="btn-secondary share-maintenance"
              onClick={handleShare}
              disabled
              aria-disabled="true"
              title="分享圖卡目前維護中"
            >
              分享圖卡維護中
            </button>
          </div>

          <div className="featured-match-grid">
            <div className="featured-team home-team">
              <h3><TeamLabel name={selected.home} /></h3>
              <p>FIFA #{homeTeam.fifa_rank || '—'} · ELO {Math.round(homeTeam.fifa_points || 0)}</p>
              <small>預期進球 {model.expected_goals.home.toFixed(2)} · 疲勞 {(model.inputs.fatigue.home * 100).toFixed(1)}%</small>
            </div>
            <div className="predicted-score-block">
              <span>模型預測</span>
              <strong>{model.predicted_score.home}<i>:</i>{model.predicted_score.away}</strong>
              <small>最可能比分</small>
            </div>
            <div className="featured-team away-team">
              <h3><TeamLabel name={selected.away} /></h3>
              <p>FIFA #{awayTeam.fifa_rank || '—'} · ELO {Math.round(awayTeam.fifa_points || 0)}</p>
              <small>預期進球 {model.expected_goals.away.toFixed(2)} · 疲勞 {(model.inputs.fatigue.away * 100).toFixed(1)}%</small>
            </div>
          </div>

          <div className="probability-section">
            <div className="probability-heading">
              <h2>勝平負機率</h2>
              <button className="text-button" onClick={() => setShowMatrix(true)}>完整比分矩陣</button>
            </div>
            <div className="probability-values">
              <div className="home"><span><TeamLabel name={selected.home} /> 勝</span><strong>{model.probabilities.home.toFixed(1)}%</strong></div>
              <div className="draw"><span>和局</span><strong>{model.probabilities.draw.toFixed(1)}%</strong></div>
              <div className="away"><span><TeamLabel name={selected.away} /> 勝</span><strong>{model.probabilities.away.toFixed(1)}%</strong></div>
            </div>
            <div className="probability-bar" aria-hidden="true">
              <span className="home" style={{ width: `${model.probabilities.home}%` }} />
              <span className="draw" style={{ width: `${model.probabilities.draw}%` }} />
              <span className="away" style={{ width: `${model.probabilities.away}%` }} />
            </div>
          </div>

          <div className="prediction-signals" aria-label="預測信號">
            <RiskBadge label="預測信心" level={model.confidence} />
            <RiskBadge label="爆冷風險" level={model.upset_risk.level} percentage={model.upset_risk.value} />
          </div>

          <div className="score-columns">
            <ScoreColumn title={<><TeamLabel name={selected.home} /> Top 3</>} scores={top.home} tone="home" />
            <ScoreColumn title="和局 Top 3" scores={top.draw} tone="draw" />
            <ScoreColumn title={<><TeamLabel name={selected.away} /> Top 3</>} scores={top.away} tone="away" />
          </div>
        </section>

        <section className="glass-card risk-analysis-card">
          <div className="section-heading-row">
            <div><p className="eyebrow">AI RISK ANALYSIS</p><h3>🔍 預測風險與失準因素</h3></div>
            <span className={`risk-dot ${model.upset_risk.level.toLowerCase()}`}>
              爆冷風險：{riskLabel[model.upset_risk.level] || model.upset_risk.level}（{model.upset_risk.value.toFixed(1)}%）
            </span>
          </div>
          <p>{selected.risk_analysis?.summary}</p>
          <ol>{model.upset_risk.factors.map((factor) => <li key={factor}>{factor}</li>)}</ol>
          <small>
            {selected.risk_analysis?.updated_at
              ? `AI 分析更新 ${formatTaiwanTime(selected.risk_analysis.updated_at)} · `
              : ''}
            LLM 僅解釋模型，不參與或修改任何機率。
          </small>
        </section>

        <AvailabilityCard match={selectedMatch} prediction={selected} />
        <MarketEvidence prediction={selected} />
        <ChampionshipOdds data={championship} variant="summary" onViewAll={onViewChampionship} />
      </div>

      <div className="share-card" ref={shareRef} aria-hidden="true" data-testid="share-card">
        <header className="share-header">
          <div><span>FIFA 2026</span><strong>PREDICTOR 4.0</strong></div>
          <p>{selected.group ? `${selected.group} 組小組賽` : selected.stage} · MATCH #{selected.match_id}</p>
        </header>
        <div className="share-teams">
          <section><h2><TeamLabel name={selected.home} /></h2><p>FIFA 世界排名 #{homeTeam.fifa_rank || '—'}</p></section>
          <div><span>預測比分</span><strong>{model.predicted_score.home}:{model.predicted_score.away}</strong></div>
          <section><h2><TeamLabel name={selected.away} /></h2><p>FIFA 世界排名 #{awayTeam.fifa_rank || '—'}</p></section>
        </div>
        <div className="share-probabilities">
          <div><span>主勝</span><strong>{model.probabilities.home.toFixed(1)}%</strong></div>
          <div><span>和局</span><strong>{model.probabilities.draw.toFixed(1)}%</strong></div>
          <div><span>客勝</span><strong>{model.probabilities.away.toFixed(1)}%</strong></div>
        </div>
        <div className="share-probability-bar">
          <span className="home" style={{ width: `${model.probabilities.home}%` }} />
          <span className="draw" style={{ width: `${model.probabilities.draw}%` }} />
          <span className="away" style={{ width: `${model.probabilities.away}%` }} />
        </div>
        <div className="share-top-scores">
          <section><span>主勝熱門比分</span><strong>{top.home.map(scoreLabel).join(' · ')}</strong></section>
          <section><span>和局熱門比分</span><strong>{top.draw.map(scoreLabel).join(' · ')}</strong></section>
          <section><span>客勝熱門比分</span><strong>{top.away.map(scoreLabel).join(' · ')}</strong></section>
        </div>
        <div className="share-insights">
          <span>預測信心：{riskLabel[model.confidence] || model.confidence}</span>
          <span>爆冷風險：{riskLabel[model.upset_risk.level] || model.upset_risk.level}（{model.upset_risk.value.toFixed(1)}%）</span>
        </div>
        <footer>
          <span><b>比賽時間</b><strong>{toTaiwanTime(selected.local_date)}</strong></span>
          <span><b>預測產生</b><strong>{generatedAt}</strong></span>
        </footer>
      </div>

      <ScoreMatrixModal prediction={selected} open={showMatrix} onClose={() => setShowMatrix(false)} />
    </main>
  );
}
