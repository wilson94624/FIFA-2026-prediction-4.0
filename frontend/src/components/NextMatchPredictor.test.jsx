import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import NextMatchPredictor from './NextMatchPredictor';

const prediction = {
  match_id: '26',
  home: 'Switzerland',
  away: 'Bosnia and Herzegovina',
  local_date: '06/18/2026 12:00',
  stage: 'group',
  group: 'B',
  model: {
    probabilities: { home: 58.2, draw: 26.6, away: 15.2 },
    predicted_score: { home: 1, away: 0, probability: 15.1 },
    expected_goals: { home: 1.5, away: 0.8 },
    confidence: 'Medium',
    upset_risk: { value: 31.2, level: 'Medium', factors: ['和局機率超過 20%'] },
    inputs: { fatigue: { home: 0.03, away: 0.02 } },
    top_scores: {
      home: [{ home: 1, away: 0, probability: 15.1 }, { home: 2, away: 0, probability: 12 }, { home: 2, away: 1, probability: 9 }],
      draw: [{ home: 1, away: 1, probability: 11 }, { home: 0, away: 0, probability: 10 }, { home: 2, away: 2, probability: 3 }],
      away: [{ home: 0, away: 1, probability: 6 }, { home: 1, away: 2, probability: 4 }, { home: 0, away: 2, probability: 2 }],
    },
    score_matrix: Array.from({ length: 36 }, (_, index) => ({
      home: Math.floor(index / 6), away: index % 6, probability: 100 / 36,
    })),
  },
  risk_analysis: { summary: '這是一場中等風險對局。', updated_at: '2026-06-20T00:00:00Z' },
  market_evidence: { available: false, reason: 'No fresh market data' },
};

const teams = {
  Switzerland: { fifa_rank: 19, fifa_points: 1700 },
  'Bosnia and Herzegovina': { fifa_rank: 59, fifa_points: 1450 },
};

afterEach(cleanup);

describe('NextMatchPredictor', () => {
  it('describes market value in plain language', () => {
    const marketPrediction = {
      ...prediction,
      market_evidence: {
        available: true,
        bookmaker_count: 5,
        last_update: '2026-06-20T00:00:00Z',
        consensus: { home: 60, draw: 25, away: 15 },
        value_scores: { home: -22.5, draw: 13.8, away: 0.2 },
      },
    };

    render(
      <NextMatchPredictor
        loading={false}
        predictions={[marketPrediction]}
        championship={{ probabilities: [] }}
        teams={teams}
        matches={[]}
      />,
    );

    expect(screen.getByText('市場高估 22.5%')).toBeInTheDocument();
    expect(screen.getByText('模型較看好 13.8%')).toBeInTheDocument();
    expect(screen.getByText('市場與模型接近')).toBeInTheDocument();
  });

  it('renders model risk, market fallback and complete matrix modal', () => {
    render(
      <NextMatchPredictor
        loading={false}
        predictions={[prediction]}
        championship={{ probabilities: [] }}
        teams={teams}
        matches={[{
          id: '26',
          stats: {
            unavailable_players: {
              home: [{ name: 'Miro Muheim', type: 'injury' }],
              away: [{ name: '客隊停賽球員', type: 'suspension' }],
            },
          },
        }]}
      />,
    );
    expect(screen.getAllByText('預測信心：中').length).toBeGreaterThan(0);
    expect(screen.getAllByText('爆冷風險：中（31.2%）').length).toBeGreaterThan(0);
    expect(screen.getByText(/AI 分析更新/)).toBeInTheDocument();
    expect(screen.getByText('市場證據目前未啟用')).toBeInTheDocument();
    expect(screen.getByText('Miro Muheim')).toBeInTheDocument();
    expect(screen.getByText('客隊停賽球員')).toBeInTheDocument();
    expect(screen.getByText('受傷')).toBeInTheDocument();
    expect(screen.getByText('停賽')).toBeInTheDocument();
    const shareCard = screen.getByTestId('share-card');
    expect(within(shareCard).getByText('B 組小組賽 · MATCH #26')).toBeInTheDocument();
    expect(within(shareCard).getByText('FIFA 世界排名 #19')).toBeInTheDocument();
    expect(within(shareCard).getByText('預測信心：中')).toBeInTheDocument();
    expect(within(shareCard).getByText(/主勝熱門比分/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /完整比分矩陣/ }));
    expect(screen.getByRole('dialog', { name: '完整比分機率矩陣' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '關閉視窗' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
