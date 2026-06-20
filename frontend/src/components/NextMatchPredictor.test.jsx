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
  it('shows factual model-market comparisons and market-implied scores', () => {
    const marketPrediction = {
      ...prediction,
      market_evidence: {
        available: true,
        bookmaker_count: 5,
        last_update: '2026-06-20T00:00:00Z',
        consensus: { home: 42, draw: 35, away: 23 },
        locked: true,
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

    const marketCard = screen.getByRole('heading', { name: '市場共識' }).closest('section');
    expect(within(marketCard).getByText('明顯分歧')).toBeInTheDocument();
    expect(within(marketCard).getByText('模型與市場看法不同')).toBeInTheDocument();
    expect(within(marketCard).getByText('16.2')).toBeInTheDocument();
    expect(within(marketCard).getByText('分歧排行')).toBeInTheDocument();
    expect(within(marketCard).getByText('市場低估')).toBeInTheDocument();
    expect(within(marketCard).getByText('-16.2pp')).toBeInTheDocument();
    expect(within(marketCard).getAllByText('市場高估')).toHaveLength(2);
    expect(within(marketCard).getByText('+8.4pp')).toBeInTheDocument();
    expect(within(marketCard).getByText('+7.8pp')).toBeInTheDocument();
    expect(within(marketCard).getByText('市場熱門比分')).toBeInTheDocument();
    expect(within(marketCard).getByText('0:0')).toBeInTheDocument();
    expect(within(marketCard).getByText('1:1')).toBeInTheDocument();
    expect(within(marketCard).getByText('2:2')).toBeInTheDocument();
    expect(within(marketCard).getByText(/已於開賽前鎖定/)).toBeInTheDocument();
    expect(within(marketCard).queryByText(/融合參考|70\/30|校正後勝率|推薦|下注|避開/)).not.toBeInTheDocument();
  });

  it('labels sub-one-point differences as close', () => {
    render(
      <NextMatchPredictor
        loading={false}
        predictions={[{
          ...prediction,
          market_evidence: {
            available: true,
            bookmaker_count: 4,
            last_update: '2026-06-20T00:00:00Z',
            consensus: { home: 58, draw: 27, away: 15 },
          },
        }]}
        championship={{ probabilities: [] }}
        teams={teams}
        matches={[]}
      />,
    );

    const marketCard = screen.getByRole('heading', { name: '市場共識' }).closest('section');
    expect(within(marketCard).getByText('高度一致')).toBeInTheDocument();
    expect(within(marketCard).getByText('模型與市場看法一致')).toBeInTheDocument();
    expect(within(marketCard).getByText('0.4')).toBeInTheDocument();
    expect(within(marketCard).getAllByText('市場接近')).toHaveLength(3);
    expect(within(marketCard).getAllByText('-0.2pp')).toHaveLength(2);
    expect(within(marketCard).getByText('+0.4pp')).toBeInTheDocument();
    expect(within(marketCard).queryByText(/⚠|較看好|一致程度/)).not.toBeInTheDocument();
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
    expect(screen.getByText('目前沒有可用的市場資料')).toBeInTheDocument();
    expect(screen.getByText('市場共識僅作為外部參考，模型預測仍可正常使用。')).toBeInTheDocument();
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
