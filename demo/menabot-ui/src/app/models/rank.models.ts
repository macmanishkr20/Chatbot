/**
 * Organisation rank registry — MUST stay in sync with backend `core/rbac.py` RANKS.
 *
 * - `rank_code` drives access-control decisions on the backend.
 * - `rank_name` is sent to the backend for personalisation and disambiguation
 *   (e.g. rank_code 11 maps to both Partner and Principal).
 * - `rank_hierarchy`: 1 = most senior, 9 = administrative tier.
 */
export interface RankInfo {
  rank_code: number;
  rank_name: string;
  rank_hierarchy: number;
}

export const RANKS: readonly RankInfo[] = [
  { rank_code: 11, rank_name: 'Partner',                    rank_hierarchy: 1 },
  { rank_code: 11, rank_name: 'Principal',                  rank_hierarchy: 1 },
  { rank_code: 13, rank_name: 'Executive Manager',          rank_hierarchy: 2 },
  { rank_code: 21, rank_name: 'Senior Manager',             rank_hierarchy: 3 },
  { rank_code: 32, rank_name: 'Manager',                    rank_hierarchy: 4 },
  { rank_code: 42, rank_name: 'Senior',                     rank_hierarchy: 5 },
  { rank_code: 44, rank_name: 'Staff/Assistant',            rank_hierarchy: 6 },
  { rank_code: 51, rank_name: 'Intern',                     rank_hierarchy: 7 },
  { rank_code: 55, rank_name: 'Administrative Lead',        rank_hierarchy: 9 },
  { rank_code: 56, rank_name: 'Administrative Advanced',    rank_hierarchy: 9 },
  { rank_code: 57, rank_name: 'Administrative Intermediate',rank_hierarchy: 9 },
  { rank_code: 56, rank_name: 'Administrative Entry',       rank_hierarchy: 9 },
] as const;

/** Default demo rank when no user-specific rank is configured. */
export const DEFAULT_RANK: RankInfo = {
  rank_code: 32,
  rank_name: 'Manager',
  rank_hierarchy: 4,
};
