import { formatTaiwanTime } from '../utils/constants';

const SAMPLE_THRESHOLD = 30;

const formatValue = (value, digits = 2, suffix = '') => {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(digits)}${suffix}`;
};

function PerformanceKpi({ label, value, description, tone = 'neutral' }) {
  return (
    <article className={`performance-kpi ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{description}</small>
    </article>
  );
}

function PerformanceEmpty({ title, description }) {
  return (
    <section className="performance-empty glass-card">
      <span aria-hidden="true">—</span>
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}

function CalibrationRow({ bucket }) {
  const modelRate = Number(bucket.predicted_midpoint ?? 0);
  const actualRate = bucket.actual_rate == null ? null : Number(bucket.actual_rate);
  const delta = actualRate == null ? null : actualRate - modelRate;
  return (
    <div className="calibration-row">
      <div className="calibration-range">
        <strong>{bucket.range}</strong>
        <span>{bucket.count} 場</span>
      </div>
      <div className="calibration-comparison">
        <div>
          <span>模型信心</span>
          <div className="calibration-track"><i className="model" style={{ width: `${modelRate}%` }} /></div>
          <b>{formatValue(modelRate, 0, '%')}</b>
        </div>
        <div>
          <span>實際命中</span>
          <div className="calibration-track"><i className="actual" style={{ width: `${actualRate ?? 0}%` }} /></div>
          <b>{actualRate == null ? '樣本不足' : formatValue(actualRate, 1, '%')}</b>
        </div>
      </div>
      <span className={delta == null ? 'calibration-delta empty' : Math.abs(delta) <= 10 ? 'calibration-delta aligned' : 'calibration-delta'}>
        {delta == null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(1)}pp`}
      </span>
    </div>
  );
}

function SystemMetric({ label, metric, suffix = ' 秒', description }) {
  const latest = typeof metric === 'number' ? metric : metric?.latest_seconds;
  const average = typeof metric === 'number' ? null : metric?.average_seconds;
  return (
    <div className="system-metric">
      <div><span>{label}</span><small>{description}</small></div>
      <strong>{formatValue(latest, 2, suffix)}</strong>
      {average != null && <small>平均 {formatValue(average, 2, suffix)}</small>}
    </div>
  );
}

export default function ModelPerformance({ backtest, metrics }) {
  if (!backtest) {
    return (
      <main className="page-container performance-page">
        <PerformanceEmpty title="尚無模型驗證資料" description="完成賽事並產生回測後，這裡會顯示模型品質、信心校準與系統狀態。" />
      </main>
    );
  }

  const sampleSize = Number(backtest.sample_size || 0);
  const insufficient = sampleSize < SAMPLE_THRESHOLD;
  const calibration = (backtest.calibration || []).filter((bucket) => Number(bucket.count || 0) > 0);
  const backtestUpdatedAt = backtest.metadata?.fetched_at;
  const metricsUpdatedAt = metrics?.metadata?.fetched_at;

  return (
    <main className="page-container performance-page">
      <section className="glass-card performance-hero">
        <header className="performance-heading">
          <div>
            <p className="eyebrow">MODEL VALIDATION</p>
            <h2>模型表現</h2>
            <p>以 2026 世界盃已完賽賽事進行逐場驗證；開發資料不計入正式成績。</p>
          </div>
          <div className="performance-dataset-meta">
            <span>資料區間<strong>2026 世界盃 · 已完賽至目前</strong></span>
            <span>樣本數<strong>{sampleSize} 場</strong></span>
            <span>最後更新<strong>{backtestUpdatedAt ? formatTaiwanTime(backtestUpdatedAt) : '尚無時間'}</strong></span>
          </div>
        </header>

        {insufficient && (
          <div className="sample-warning" role="status">
            <strong>{sampleSize === 0 ? '尚無正式樣本' : '目前樣本不足'}</strong>
            <span>{sampleSize === 0 ? '等待首批完賽資料後開始計算模型品質。' : `目前少於 ${SAMPLE_THRESHOLD} 場，指標僅供初步觀察，不宜做趨勢結論。`}</span>
          </div>
        )}

        <div className="performance-kpi-grid">
          <PerformanceKpi label="已驗證場次" value={`${sampleSize} 場`} description="正式回測樣本數" tone="sample" />
          <PerformanceKpi label="1X2 命中率" value={formatValue(backtest.accuracy_1x2, 1, '%')} description="勝／和／負方向判斷" tone="primary" />
          <PerformanceKpi label="Log Loss" value={formatValue(backtest.log_loss, 3)} description="越低越好 · 懲罰錯誤自信" />
          <PerformanceKpi label="Brier Score" value={formatValue(backtest.brier_score, 3)} description="越低越好 · 衡量機率預測品質" />
          <PerformanceKpi label="Top 3 比分命中率" value={formatValue(backtest.correct_score_top3_hit_rate, 1, '%')} description="實際比分落在前三候選" />
        </div>
      </section>

      <section className="glass-card calibration-card">
        <div className="performance-section-heading">
          <div>
            <p className="eyebrow">CALIBRATION</p>
            <h3>模型信心校準</h3>
            <p>比較模型宣稱的信心與該區間實際命中率；兩者越接近，機率越可信。</p>
          </div>
          <span className={insufficient ? 'quality-status warning' : 'quality-status'}>{insufficient ? '樣本累積中' : '持續驗證中'}</span>
        </div>

        {calibration.length ? (
          <div className="calibration-list">
            <div className="calibration-list-labels"><span>信心區間</span><span>模型與實際比較</span><span>差距</span></div>
            {calibration.map((bucket) => <CalibrationRow bucket={bucket} key={bucket.range} />)}
          </div>
        ) : (
          <div className="calibration-empty">
            <strong>尚無可顯示的信心區間</strong>
            <span>完成更多賽事後，系統會依模型信心分組比較實際命中率。</span>
          </div>
        )}
        <p className="calibration-note">差距以百分點（pp）表示；少量樣本容易產生大幅波動，請搭配每列場次判讀。</p>
      </section>

      <section className="glass-card monitoring-card">
        <div className="performance-section-heading">
          <div>
            <p className="eyebrow">SYSTEM HEALTH</p>
            <h3>系統狀態</h3>
            <p>這些數值反映資料管線與運算效率，不代表模型預測品質。</p>
          </div>
          <span className="system-updated">更新 {metricsUpdatedAt ? formatTaiwanTime(metricsUpdatedAt) : '尚無時間'}</span>
        </div>
        <div className="system-status-grid">
          <SystemMetric label="賽事 API 更新" metric={metrics?.worldcup_api_time} description="最近一次資料同步耗時" />
          <SystemMetric label="FotMob 更新" metric={metrics?.fotmob_time} description="比賽統計同步耗時" />
          <SystemMetric label="賽事模擬" metric={metrics?.simulation_time} description="完整模擬運算耗時" />
          <SystemMetric label="快取命中率" metric={metrics?.cache_hit_rate} suffix="%" description="重用既有資料的請求比例" />
        </div>
      </section>
    </main>
  );
}
