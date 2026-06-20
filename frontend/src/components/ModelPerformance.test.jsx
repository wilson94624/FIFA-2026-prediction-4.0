import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import ModelPerformance from './ModelPerformance';

afterEach(cleanup);

describe('ModelPerformance', () => {
  it('separates model quality from system health and explains professional metrics', () => {
    render(<ModelPerformance
      backtest={{
        sample_size: 20,
        accuracy_1x2: 55,
        log_loss: 0.88,
        brier_score: 0.19,
        correct_score_top3_hit_rate: 30,
        calibration: [{ range: '50–60%', predicted_midpoint: 55, actual_rate: 52, count: 6 }],
        development_sets: { total: 127 },
        metadata: { fetched_at: '2026-06-20T00:00:00Z' },
      }}
      metrics={{
        cache_hit_rate: 75,
        worldcup_api_time: { latest_seconds: 1.2, average_seconds: 1.4 },
        metadata: { fetched_at: '2026-06-20T00:00:00Z' },
      }}
    />);

    expect(screen.getByRole('heading', { name: '模型表現' })).toBeInTheDocument();
    expect(screen.getByText('1X2 命中率')).toBeInTheDocument();
    expect(screen.getByText('Log Loss')).toBeInTheDocument();
    expect(screen.getByText('Brier Score')).toBeInTheDocument();
    expect(screen.getByText('越低越好 · 衡量機率預測品質')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '模型信心校準' })).toBeInTheDocument();
    expect(screen.getByText('-3.0pp')).toBeInTheDocument();
    expect(screen.getByText('快取命中率')).toBeInTheDocument();
    expect(screen.getByText('目前樣本不足')).toBeInTheDocument();
  });

  it('shows a clear empty state when no backtest exists', () => {
    render(<ModelPerformance backtest={null} metrics={null} />);
    expect(screen.getByRole('heading', { name: '尚無模型驗證資料' })).toBeInTheDocument();
  });
});
