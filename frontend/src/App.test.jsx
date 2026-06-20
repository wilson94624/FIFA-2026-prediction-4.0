import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const predictionResponse = {
  predictions: [{
    match_id: '26', home: 'Switzerland', away: 'Bosnia and Herzegovina', local_date: '06/18/2026 12:00', stage: 'group', group: 'B',
    model: {
      probabilities: { home: 58, draw: 27, away: 15 }, predicted_score: { home: 1, away: 0, probability: 15 },
      expected_goals: { home: 1.5, away: 0.8 }, confidence: 'Medium', upset_risk: { value: 31, level: 'Medium', factors: [] },
      inputs: { fatigue: { home: 0, away: 0 } },
      top_scores: {
        home: [{ home: 1, away: 0, probability: 15 }], draw: [{ home: 1, away: 1, probability: 11 }], away: [{ home: 0, away: 1, probability: 6 }],
      },
      score_matrix: Array.from({ length: 36 }, (_, index) => ({ home: Math.floor(index / 6), away: index % 6, probability: 100 / 36 })),
    },
    risk_analysis: { summary: '規則式分析' }, market_evidence: { available: false },
  }],
};

const responses = {
  '/api/tournament': { teams: { Switzerland: {}, 'Bosnia and Herzegovina': {} }, matches: [] },
  '/api/predictions': predictionResponse,
  '/api/championship-odds': { probabilities: [] },
  '/api/backtests/summary': { sample_size: 0, calibration: [] },
  '/api/metrics': {},
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('App', () => {
  it('loads API data and polls a background job to completion', async () => {
    const fetchMock = vi.fn(async (path, options) => {
      if (path === '/api/sync' && options?.method === 'POST') {
        return { ok: true, json: async () => ({ job_id: 'job-1', job_type: 'sync', status: 'queued', progress: 0, stage: 'queued', message: 'queued' }) };
      }
      if (String(path).startsWith('/api/sync-status')) {
        return { ok: true, json: async () => ({ job_id: 'job-1', job_type: 'sync', status: 'completed', progress: 100, stage: 'completed', message: '完成' }) };
      }
      return { ok: true, json: async () => responses[path] };
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    expect(await screen.findByText('勝平負機率')).toBeInTheDocument();
    fireEvent.click(screen.getByText('資料狀態').closest('summary'));
    fireEvent.click(screen.getByRole('button', { name: '更新賽事資料' }));
    await waitFor(() => expect(screen.getByText('賽事資料更新完成')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith('/api/sync', expect.objectContaining({ method: 'POST' }));
  });

  it('opens a finished match detail and loads its review', async () => {
    const finishedMatch = {
      id: '1', home_team_name_en: 'Switzerland', away_team_name_en: 'Bosnia and Herzegovina',
      home_score: '2', away_score: '1', finished: 'TRUE', time_elapsed: 'finished',
      type: 'group', group: 'B', local_date: '06/12/2026 12:00',
      stats: { possessionA: 52, possessionB: 48, shotsA: 10, shotsB: 8, xgA: 1.7, xgB: 0.9, cardsA: 2, cardsB: 1 },
    };
    const fetchMock = vi.fn(async (path) => {
      const payloads = {
        ...responses,
        '/api/tournament': {
          teams: {
            Switzerland: { group: 'B', fifa_points: 1700, avg_rating: 80 },
            'Bosnia and Herzegovina': { group: 'B', fifa_points: 1450, avg_rating: 76 },
          },
          matches: [finishedMatch],
        },
        '/api/predictions/1': predictionResponse.predictions[0],
        '/api/reviews/1': { failure_type: '隨機波動', review: '比賽由少數關鍵事件決定。' },
      };
      return { ok: true, json: async () => payloads[path] };
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    await screen.findByText('勝平負機率');
    fireEvent.click(screen.getByRole('button', { name: '賽程' }));
    await screen.findByText('2026 世界盃賽程與賽果');
    fireEvent.click(await screen.findByRole('button', { name: '查看比賽詳情：🇨🇭 瑞士 對 🇧🇦 波赫，比分 2 比 1' }));
    expect(await screen.findByRole('dialog', { name: '比賽詳情' })).toBeInTheDocument();
    expect(await screen.findByLabelText('勝負方向命中')).toBeInTheDocument();
    expect(await screen.findByLabelText('比分未命中')).toBeInTheDocument();
    expect(await screen.findByText('依射門品質估算的預期進球')).toBeInTheDocument();
    expect(await screen.findByText('比賽由少數關鍵事件決定。')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/reviews/1', expect.any(Object));
  });
});
