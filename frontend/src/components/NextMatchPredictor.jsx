import { useMemo, useRef, useState } from 'react';
import { formatTaiwanTime, TEAM_TRANSLATIONS, toTaiwanTime } from '../utils/constants';
import ChampionshipOdds from './ChampionshipOdds';
import { ScoreMatrixModal } from './Modals';

const teamLabel = (name) => {
  const team = TEAM_TRANSLATIONS[name] || { flag: '🏳️', cn: name };
  return `${team.flag} ${team.cn}`;
};

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
          {renderSide('home', `${teamLabel(prediction.home)} 缺陣`)}
          {renderSide('away', `${teamLabel(prediction.away)} 缺陣`)}
        </div>
      ) : <p className="availability-unavailable">傷停資料暫時無法取得</p>}
    </section>
  );
}

function MarketEvidence({ prediction }) {
  const market = prediction.market_evidence;
  if (!market?.available) {
    return (
      <section className="glass-card market-card unavailable">
        <div>
          <p className="eyebrow">EXTERNAL EVIDENCE</p>
          <h3>市場證據目前未啟用</h3>
        </div>
        <p>{market?.reason || '設定 THE_ODDS_API_KEY 後即可顯示去水市場共識。'}</p>
      </section>
    );
  }
  const values = market.value_scores || {};
  const fused = prediction.market_fused?.probabilities;
  const valueDisplay = (value) => {
    if (Math.abs(value) < 0.5) return { text: '市場與模型接近', tone: 'neutral' };
    if (value < 0) return { text: `市場高估 ${Math.abs(value).toFixed(1)}%`, tone: 'negative' };
    return { text: `模型較看好 ${value.toFixed(1)}%`, tone: 'positive' };
  };
  return (
    <section className="glass-card market-card">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">EXTERNAL EVIDENCE · {market.bookmaker_count} BOOKMAKERS</p>
          <h3>市場共識與 70/30 校正參考</h3>
        </div>
        <span className="freshness">更新 {formatTaiwanTime(market.last_update) || '—'}</span>
      </div>
      <div className="market-grid">
        {['home', 'draw', 'away'].map((key) => {
          const display = valueDisplay(values[key] || 0);
          return (
            <div key={key}>
              <span>{key === 'home' ? teamLabel(prediction.home) : key === 'away' ? teamLabel(prediction.away) : '🤝 和局'}</span>
              <strong>{market.consensus[key].toFixed(1)}%</strong>
              <small className={display.tone}>{display.text}</small>
              {fused && <em>融合參考 {fused[key].toFixed(1)}%</em>}
            </div>
          );
        })}
      </div>
      {(market.recommended_scores?.length > 0 || market.avoid_scores?.length > 0) && (
        <div className="market-score-notes">
          <p><strong>可留意：</strong>{market.recommended_scores?.map(scoreLabel).join('、') || '無明顯正向 edge'}</p>
          <p><strong>宜避開：</strong>{market.avoid_scores?.map(scoreLabel).join('、') || '無明顯負向 edge'}</p>
        </div>
      )}
      <p className="disclaimer">市場只作外部證據，不會取代首頁模型主值；內容不構成投注建議。</p>
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
              <strong>{teamLabel(item.home)} <i>vs</i> {teamLabel(item.away)}</strong>
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
              <h3>{teamLabel(selected.home)}</h3>
              <p>FIFA #{homeTeam.fifa_rank || '—'} · ELO {Math.round(homeTeam.fifa_points || 0)}</p>
              <small>預期進球 {model.expected_goals.home.toFixed(2)} · 疲勞 {(model.inputs.fatigue.home * 100).toFixed(1)}%</small>
            </div>
            <div className="predicted-score-block">
              <span>模型預測</span>
              <strong>{model.predicted_score.home}<i>:</i>{model.predicted_score.away}</strong>
              <small>最可能比分</small>
            </div>
            <div className="featured-team away-team">
              <h3>{teamLabel(selected.away)}</h3>
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
              <div className="home"><span>{teamLabel(selected.home)} 勝</span><strong>{model.probabilities.home.toFixed(1)}%</strong></div>
              <div className="draw"><span>和局</span><strong>{model.probabilities.draw.toFixed(1)}%</strong></div>
              <div className="away"><span>{teamLabel(selected.away)} 勝</span><strong>{model.probabilities.away.toFixed(1)}%</strong></div>
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
            <ScoreColumn title={`${teamLabel(selected.home)} Top 3`} scores={top.home} tone="home" />
            <ScoreColumn title="和局 Top 3" scores={top.draw} tone="draw" />
            <ScoreColumn title={`${teamLabel(selected.away)} Top 3`} scores={top.away} tone="away" />
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
          <section><h2>{teamLabel(selected.home)}</h2><p>FIFA 世界排名 #{homeTeam.fifa_rank || '—'}</p></section>
          <div><span>預測比分</span><strong>{model.predicted_score.home}:{model.predicted_score.away}</strong></div>
          <section><h2>{teamLabel(selected.away)}</h2><p>FIFA 世界排名 #{awayTeam.fifa_rank || '—'}</p></section>
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
