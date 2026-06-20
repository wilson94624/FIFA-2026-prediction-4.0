import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChampionshipOdds from './ChampionshipOdds';

const probabilities = ['Argentina', 'Spain', 'France', 'Brazil', 'England', 'Portugal'].map((team_name, index) => ({
  team_name,
  R32_pct: 98 - index,
  R16_pct: 78 - index,
  QF_pct: 58 - index,
  SF_pct: 42 - index,
  Final_pct: 28 - index,
  Winner_pct: 18 - index * 2,
}));

const data = {
  last_updated: '2026-06-20T00:00:00Z',
  probabilities,
};

afterEach(cleanup);

describe('ChampionshipOdds', () => {
  it('shows only the top five on the homepage and opens the full view', () => {
    const onViewAll = vi.fn();
    render(<ChampionshipOdds data={data} variant="summary" onViewAll={onViewAll} />);

    expect(screen.getByText('🇦🇷 阿根廷')).toBeInTheDocument();
    expect(screen.queryByText('🇵🇹 葡萄牙')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看全部' }));
    expect(onViewAll).toHaveBeenCalledOnce();
  });

  it('renders every round in the complete ranking table', () => {
    render(<ChampionshipOdds data={data} />);

    expect(screen.getByRole('heading', { name: '48 隊奪冠與晉級機率' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '冠軍機率' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '三十二強' })).toBeInTheDocument();
    expect(screen.getByText('🇵🇹 葡萄牙')).toBeInTheDocument();
    expect(screen.getByText('10,000')).toBeInTheDocument();
  });
});
