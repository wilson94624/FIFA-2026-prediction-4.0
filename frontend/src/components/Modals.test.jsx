import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MatchDetailModal } from './Modals';

describe('MatchDetailModal', () => {
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
});
