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

const EXPLANATIONS_VERSION = 'championship-explanations-v2';

const data = {
  last_updated: '2026-06-20T00:00:00Z',
  explanations_version: EXPLANATIONS_VERSION,
  probabilities,
  explanations: {
    version: EXPLANATIONS_VERSION,
    generated_by: 'rules',
    teams: probabilities.slice(0, 5).map((team, index) => ({
      rank: index + 1,
      team_name: team.team_name,
      championship_probability: team.Winner_pct,
      final_probability: team.Final_pct,
      semifinal_probability: team.SF_pct,
      quarterfinal_probability: team.QF_pct,
      round_of_16_probability: team.R16_pct,
      round_of_32_probability: team.R32_pct,
      ranking_summary: index === 0
        ? 'Argentina目前領先Spain 2.0pp，主要優勢來自四強率高出 1.0pp。'
        : `${team.team_name}與前一名的差距來自決賽率。`,
      comparison_target: index === 0 ? 'Spain' : probabilities[index - 1].team_name,
      comparison_delta: { championship_probability: index === 0 ? 2 : -2 },
      ranking_factors: [{ metric: 'semifinal_probability', label: '四強率', delta_pp: 1 }],
      key_risk_round: '十六強晉級八強',
      choke_point_drop_pp: 20,
      most_likely_exit_round: '十六強',
      biggest_threat_teams: ['France', 'Spain'].filter((name) => name !== team.team_name),
      threat_label: '可能卡關對手',
      threat_note: '依奪冠率與潛在路徑推估',
      path_difficulty_label: index === 0 ? '路徑偏順' : '路徑中等',
      reason_bullets: ['四強率比相鄰隊伍高 1.0pp。', '真正分水嶺在十六強晉級八強。'],
    })),
  },
};

afterEach(cleanup);

describe('ChampionshipOdds', () => {
  it('shows only the top five on the homepage and opens the full view', () => {
    const onViewAll = vi.fn();
    render(<ChampionshipOdds data={data} variant="summary" onViewAll={onViewAll} />);

    expect(screen.getByText('阿根廷')).toBeInTheDocument();
    expect(screen.queryByText('葡萄牙')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看全部' }));
    expect(onViewAll).toHaveBeenCalledOnce();
  });

  it('renders every round in the complete ranking table', () => {
    render(<ChampionshipOdds data={data} />);

    expect(screen.getByRole('heading', { name: '48 隊奪冠與晉級機率' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '冠軍機率' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '三十二強' })).toBeInTheDocument();
    expect(screen.getByText('葡萄牙')).toBeInTheDocument();
    expect(screen.getByText('10,000')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '奪冠熱門解讀' })).toBeInTheDocument();
    expect(screen.getAllByText(/主要卡關點 · 十六強晉級八強/)).toHaveLength(5);
    expect(screen.getAllByText('可能卡關對手')).toHaveLength(5);
    expect(screen.queryByText(/最可能出局/)).not.toBeInTheDocument();
    expect(screen.queryByText('主要潛在威脅')).not.toBeInTheDocument();
    expect(screen.getByText('阿根廷目前領先西班牙 2.0pp，主要優勢來自四強率高出 1.0pp。')).toBeInTheDocument();
  });

  it('shows a safe fallback for legacy v1 explanations', () => {
    render(<ChampionshipOdds data={{
      last_updated: data.last_updated,
      explanations_version: EXPLANATIONS_VERSION,
      probabilities,
      explanations: { version: 'championship-explanations-v1', teams: data.explanations.teams },
    }} />);

    expect(screen.getByText('重新模擬後將產生新版奪冠解讀')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('shows the same fallback when explanations are missing', () => {
    render(<ChampionshipOdds data={{ last_updated: data.last_updated, probabilities }} />);

    expect(screen.getByText('重新模擬後將產生新版奪冠解讀')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});
