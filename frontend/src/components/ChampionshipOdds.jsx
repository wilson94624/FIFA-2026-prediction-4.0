import { useMemo, useState } from 'react';
import { formatTaiwanTime, TEAM_TRANSLATIONS } from '../utils/constants';

const SIMULATION_RUNS = 10_000;

const label = (name) => {
  const team = TEAM_TRANSLATIONS[name] || { flag: '🏳️', cn: name };
  return `${team.flag} ${team.cn}`;
};

const percent = (value) => `${Number(value || 0).toFixed(1)}%`;

function SimulationMeta({ data, compact = false }) {
  const updatedAt = data?.last_updated || data?.metadata?.fetched_at;
  return (
    <div className={compact ? 'simulation-meta compact' : 'simulation-meta'}>
      <span><strong>{SIMULATION_RUNS.toLocaleString('zh-TW')}</strong> 次模擬</span>
      <span>最後更新 <strong>{updatedAt ? formatTaiwanTime(updatedAt) : '尚無資料'}</strong></span>
    </div>
  );
}

function OddsTopFive({ probabilities }) {
  const leader = Math.max(Number(probabilities[0]?.Winner_pct || 0), 0.01);
  return (
    <div className="championship-top-five">
      {probabilities.slice(0, 5).map((item, index) => (
        <div className={`championship-rank-row rank-${index + 1}`} key={item.team_name}>
          <span className="championship-rank">{index + 1}</span>
          <strong>{label(item.team_name)}</strong>
          <div className="championship-bar" aria-label={`${label(item.team_name)}奪冠機率 ${percent(item.Winner_pct)}`}>
            <i style={{ width: `${Math.max(2, Number(item.Winner_pct || 0) / leader * 100)}%` }} />
          </div>
          <b>{percent(item.Winner_pct)}</b>
        </div>
      ))}
    </div>
  );
}

export default function ChampionshipOdds({ data, variant = 'full', onViewAll }) {
  const [query, setQuery] = useState('');
  const probabilities = useMemo(
    () => [...(data?.probabilities || [])].sort((a, b) => Number(b.Winner_pct || 0) - Number(a.Winner_pct || 0)),
    [data?.probabilities],
  );
  const filtered = probabilities.filter((item) => {
    const translated = TEAM_TRANSLATIONS[item.team_name]?.cn || '';
    return `${item.team_name} ${translated}`.toLowerCase().includes(query.trim().toLowerCase());
  });

  if (variant === 'summary') {
    return (
      <section className="glass-card championship-card championship-summary-card">
        <div className="championship-card-heading">
          <div>
            <p className="eyebrow">CHAMPIONSHIP OUTLOOK</p>
            <h3>奪冠熱門 Top 5</h3>
          </div>
          <button className="text-button" type="button" onClick={onViewAll}>查看全部</button>
        </div>
        {probabilities.length ? <OddsTopFive probabilities={probabilities} /> : <p className="championship-empty">尚無奪冠模擬資料</p>}
        <SimulationMeta data={data} compact />
      </section>
    );
  }

  return (
    <section className="glass-card championship-card championship-full-card">
      <header className="championship-page-heading">
        <div>
          <p className="eyebrow">TOURNAMENT SIMULATION</p>
          <h2>48 隊奪冠與晉級機率</h2>
          <p>以目前賽程、球隊強度與已完賽結果進行蒙地卡羅模擬；數值為各隊進入指定輪次的估計機率。</p>
        </div>
        <SimulationMeta data={data} />
      </header>

      <div className="championship-podium" aria-label="奪冠機率前三名">
        {probabilities.slice(0, 3).map((item, index) => (
          <article className={`podium-team rank-${index + 1}`} key={item.team_name}>
            <span>#{index + 1}</span>
            <strong>{label(item.team_name)}</strong>
            <b>{percent(item.Winner_pct)}</b>
            <small>奪冠機率</small>
          </article>
        ))}
      </div>

      <div className="championship-table-tools">
        <div>
          <h3>完整排名</h3>
          <span>{filtered.length} / {probabilities.length || 48} 隊</span>
        </div>
        <input
          className="search-input championship-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜尋國家隊"
          aria-label="搜尋國家隊"
        />
      </div>

      <div className="championship-table-wrap" tabIndex="0" aria-label="48 隊奪冠與各輪晉級機率，可橫向捲動">
        <table className="championship-table">
          <thead>
            <tr><th>排名</th><th>球隊</th><th>冠軍機率</th><th>決賽</th><th>四強</th><th>八強</th><th>十六強</th><th>三十二強</th></tr>
          </thead>
          <tbody>
            {filtered.map((item) => {
              const rank = probabilities.findIndex((team) => team.team_name === item.team_name) + 1;
              const leader = Math.max(Number(probabilities[0]?.Winner_pct || 0), 0.01);
              return (
                <tr className={rank <= 3 ? `top-team rank-${rank}` : ''} key={item.team_name}>
                  <td><span className="table-rank">{rank}</span></td>
                  <td><strong>{label(item.team_name)}</strong></td>
                  <td>
                    <div className="table-champion-cell">
                      <div className="championship-bar"><i style={{ width: `${Math.max(1, Number(item.Winner_pct || 0) / leader * 100)}%` }} /></div>
                      <b>{percent(item.Winner_pct)}</b>
                    </div>
                  </td>
                  <td>{percent(item.Final_pct)}</td>
                  <td>{percent(item.SF_pct)}</td>
                  <td>{percent(item.QF_pct)}</td>
                  <td>{percent(item.R16_pct)}</td>
                  <td>{percent(item.R32_pct)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <footer className="championship-data-note">
        <strong>資料說明</strong>
        <span>機率來自 {SIMULATION_RUNS.toLocaleString('zh-TW')} 次賽事模擬，不代表比賽保證結果；已晉級或已完賽狀態會隨資料更新納入下一次模擬。</span>
      </footer>
    </section>
  );
}
