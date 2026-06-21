import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MatchDetailModal } from './Modals';

afterEach(cleanup);

describe('MatchDetailModal', () => {
  const prediction = {
    model: {
      probabilities: { home: 58, draw: 25, away: 17 },
      predicted_score: { home: 1, away: 0 },
      expected_goals: { home: 1.6, away: 0.8 },
      score_matrix: Array.from({ length: 36 }, (_, index) => ({
        home: Math.floor(index / 6),
        away: index % 6,
        probability: 36 - index,
      })),
    },
  };

  it('labels incomplete finished-match stats as unavailable', () => {
    render(
      <MatchDetailModal
        selectedMatch={{
          id: '29',
          type: 'group',
          group: 'C',
          finished: 'TRUE',
          home_team_name_en: 'Brazil',
          away_team_name_en: 'Haiti',
          home_score: '3',
          away_score: '0',
          stats: { fotmob_complete: false, fotmob_status: 'pending' },
        }}
        prediction={null}
        review={null}
        loading={false}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('資料來源尚未提供完整數據')).toBeInTheDocument();
    expect(screen.getAllByText('— : —', { selector: 'strong' })).toHaveLength(3);
  });

  it('explains a finished result with prematch context and matrix position', () => {
    render(
      <MatchDetailModal
        selectedMatch={{
          id: '30',
          type: 'group',
          group: 'D',
          finished: true,
          home_team_name_en: 'Japan',
          away_team_name_en: 'Netherlands',
          home_score: '0',
          away_score: '2',
          stats: { xgA: 1.2, xgB: 0.9, possessionA: 49, possessionB: 51, shotsA: 11, shotsB: 8, cardsA: 1, cardsB: 2 },
        }}
        prediction={prediction}
        review={{ failure_type: 'Random Football Variance', review: '本場屬於 Random Football Variance。' }}
        loading={false}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: '賽後模型檢討' })).toBeInTheDocument();
    expect(screen.getByText('結果意外程度')).toBeInTheDocument();
    expect(screen.getByText('模型賽前認知')).toBeInTheDocument();
    expect(screen.getByText('模型是否考慮過這個結果')).toBeInTheDocument();
    expect(screen.getByText('近期失準模式累積中')).toBeInTheDocument();
    expect(screen.getByText('本場屬於 Random Football Variance。')).toBeInTheDocument();
    expect(screen.getByText(/關鍵機會轉化|實際進球明顯高於 xG/)).toBeInTheDocument();
  });
});
