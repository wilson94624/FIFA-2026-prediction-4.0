import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { api } from './api';
import { MatchDetailModal, TeamRosterModal } from './components/Modals';
import { formatTaiwanTime } from './utils/constants';

const NextMatchPredictor = lazy(() => import('./components/NextMatchPredictor'));
const TournamentBracket = lazy(() => import('./components/TournamentBracket'));
const ModelPerformance = lazy(() => import('./components/ModelPerformance'));
const ChampionshipOdds = lazy(() => import('./components/ChampionshipOdds'));

const EMPTY_DATA = {
  tournament: { teams: {}, matches: [] },
  predictions: [],
  championship: { probabilities: [] },
  backtest: null,
  metrics: null,
};

const delay = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

const JOB_STAGE_LABELS = {
  queued: '排隊中',
  started: '準備中',
  worldcup: '更新賽事資料',
  fotmob: '更新比賽統計',
  market: '更新市場資料',
  predictions: '更新預測',
  ai_analysis: '更新賽前 AI 分析',
  backtest: '更新模型表現',
  reviews: '更新賽後回顧',
  simulation: '重新模擬奪冠機率',
  completed: '完成',
  failed: '失敗',
  interrupted: '已中斷',
  submit: '無法啟動',
};

const parseJobResult = (message) => {
  if (typeof message !== 'string' || !message.trim().startsWith('{')) return null;
  try {
    return JSON.parse(message);
  } catch {
    return null;
  }
};

const jobMessage = (job) => {
  if (job.status === 'failed') {
    return job.job_type === 'simulation' ? '奪冠機率模擬失敗' : '賽事資料更新失敗';
  }
  if (job.status !== 'completed') return job.message;
  const result = parseJobResult(job.message);
  if (job.job_type === 'simulation' && result) {
    return `模擬完成：已執行 ${Number(result.runs || 0).toLocaleString('zh-TW')} 次，涵蓋 ${result.teams || 0} 支球隊`;
  }
  if (job.job_type === 'sync' && result) {
    return `資料更新完成：${result.matches || 0} 場賽事、${result.fotmob_matches || 0} 場 FotMob 資料、${result.market_events || 0} 筆市場資料、${result.predictions || 0} 筆預測、${result.reviews || 0} 筆賽後回顧`;
  }
  return job.job_type === 'simulation' ? '奪冠機率模擬完成' : '賽事資料更新完成';
};

const jobError = (error) => {
  if (!error) return '';
  if (typeof error !== 'string' || !error.trim().startsWith('{')) return error;
  try {
    return JSON.parse(error).error || error;
  } catch {
    return error;
  }
};

export default function App() {
  const [activeTab, setActiveTab] = useState('next-match');
  const [data, setData] = useState(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [job, setJob] = useState(null);
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [selectedTeam, setSelectedTeam] = useState(null);

  const loadData = useCallback(async () => {
    try {
      setError('');
      const [tournament, predictionData, championship, backtest, metrics] = await Promise.all([
        api.get('/api/tournament'),
        api.get('/api/predictions'),
        api.get('/api/championship-odds'),
        api.get('/api/backtests/summary'),
        api.get('/api/metrics'),
      ]);
      setData({
        tournament,
        predictions: predictionData.predictions || [],
        championship,
        backtest,
        metrics,
      });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetching initial API state is the external synchronization owned by this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData();
  }, [loadData]);

  const pollJob = async (jobId) => {
    for (;;) {
      const status = await api.get(`/api/sync-status?job_id=${encodeURIComponent(jobId)}`);
      setJob(status);
      if (status.status === 'completed') {
        await delay(120);
        try {
          const finalStatus = await api.get(`/api/sync-status?job_id=${encodeURIComponent(jobId)}`);
          setJob(finalStatus);
        } catch {
          setJob(status);
        }
        await loadData();
        return;
      }
      if (status.status === 'failed') return;
      await delay(800);
    }
  };

  const startJob = async (type) => {
    try {
      setError('');
      const endpoint = type === 'sync' ? '/api/sync' : '/api/simulations';
      const nextJob = await api.post(endpoint);
      setJob(nextJob);
      await pollJob(nextJob.job_id);
    } catch (requestError) {
      setError(requestError.message);
      setJob(null);
    }
  };

  const openMatch = async (match) => {
    if (!match?.id) return;
    setSelectedDetail({ match, prediction: null, review: null, loading: true });
    const [predictionResult, reviewResult] = await Promise.allSettled([
      api.get(`/api/predictions/${match.id}`),
      api.get(`/api/reviews/${match.id}`),
    ]);
    setSelectedDetail({
      match,
      prediction: predictionResult.status === 'fulfilled' ? predictionResult.value : null,
      review: reviewResult.status === 'fulfilled' ? reviewResult.value : null,
      loading: false,
    });
  };

  const busy = job?.status === 'queued' || job?.status === 'running';
  const teams = data.tournament.teams || {};
  const matches = data.tournament.matches || [];

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-topline">
          <div className="brand-lockup">
            <span className="brand-trophy" aria-hidden="true">🏆</span>
            <div>
              <h1>FIFA PREDICTOR <span>4.0</span></h1>
              <p>World Cup prediction intelligence</p>
            </div>
          </div>

          <details className="data-status-menu">
            <summary>
              <span className={busy ? 'status-dot busy' : 'status-dot'} aria-hidden="true" />
              <span className="data-status-copy">
                <strong>資料狀態</strong>
                <small>{busy ? JOB_STAGE_LABELS[job?.stage] || '處理中' : '資料已就緒'}</small>
              </span>
            </summary>
            <div className="data-status-popover">
              <div className="data-status-heading">
                <strong>資料與模擬</strong>
                <span>{busy ? `${job?.progress || 0}%` : 'READY'}</span>
              </div>
              <p>更新賽事、傷停與市場資料，或重新計算奪冠機率。</p>
              <button className="btn-secondary" disabled={busy} onClick={() => startJob('sync')}>
                {busy && job?.job_type === 'sync' ? '更新賽事資料中' : '更新賽事資料'}
              </button>
              <button className="btn-secondary" disabled={busy} onClick={() => startJob('simulation')}>
                {busy && job?.job_type === 'simulation' ? '重新模擬中' : '重新模擬奪冠機率'}
              </button>
            </div>
          </details>
        </div>

        <nav className="product-nav" aria-label="產品導覽">
          {[
            ['next-match', '預測'],
            ['schedule', '賽程'],
            ['bracket', '淘汰賽'],
            ['championship', '奪冠機率'],
            ['performance', '模型表現'],
          ].map(([tab, label]) => (
            <button
              key={tab}
              className={activeTab === tab ? 'product-nav-item active' : 'product-nav-item'}
              aria-current={activeTab === tab ? 'page' : undefined}
              onClick={() => setActiveTab(tab)}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      {job && (
        <section className={`job-banner ${job.status}`} aria-live="polite">
          <div>
            <strong>{jobMessage(job)}</strong>
            <span>
              {JOB_STAGE_LABELS[job.stage] || job.stage} · {job.progress}%
              {job.status === 'completed' && job.updated_at
                ? ` · 完成時間 ${formatTaiwanTime(job.updated_at)}`
                : ''}
            </span>
          </div>
          <div className="job-progress"><span style={{ width: `${job.progress}%` }} /></div>
          {job.error && <p>{jobError(job.error)}</p>}
        </section>
      )}

      {error && <div className="error-banner" role="alert">⚠️ {error}</div>}

      <Suspense fallback={<main className="loading-panel">載入 Predictor 4.0…</main>}>
        {activeTab === 'next-match' && (
          <NextMatchPredictor
            loading={loading}
            predictions={data.predictions}
            championship={data.championship}
            teams={teams}
            matches={matches}
            onViewChampionship={() => setActiveTab('championship')}
          />
        )}
        {(activeTab === 'schedule' || activeTab === 'bracket') && (
          <main className="page-container tournament-page">
            <TournamentBracket
              key={activeTab}
              initialSubTab={activeTab === 'bracket' ? 'bracket' : 'results'}
              teams={teams}
              realGames={matches}
              onSelectMatch={openMatch}
              onSelectTeam={setSelectedTeam}
            />
          </main>
        )}
        {activeTab === 'championship' && (
          <main className="page-container championship-page">
            <ChampionshipOdds data={data.championship} />
          </main>
        )}
        {activeTab === 'performance' && (
          <ModelPerformance backtest={data.backtest} metrics={data.metrics} />
        )}
      </Suspense>

      <MatchDetailModal
        selectedMatch={selectedDetail?.match}
        prediction={selectedDetail?.prediction}
        review={selectedDetail?.review}
        loading={selectedDetail?.loading}
        onClose={() => setSelectedDetail(null)}
      />
      <TeamRosterModal selectedTeam={selectedTeam} onClose={() => setSelectedTeam(null)} />

      <footer>⚽ FIFA 2026 Predictor 4.0 — 模型與市場證據分開呈現，所有運彩資訊僅供研究參考。</footer>
    </div>
  );
}
