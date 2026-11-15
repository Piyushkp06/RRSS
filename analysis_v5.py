"""
T20 CRICKET COMPREHENSIVE PRESSURE PERFORMANCE ANALYSIS v5
SupeRR Selector Season 2 - Multi-Gate Balanced Cutoffs

Eliminates "One Metric Too Good, One Too Bad" Outliers:
1. Multi-Gate Floor Cutoffs for Batters:
   - Matches in XI >= 40
   - Total Runs >= 600
   - Non-tail (avg_batting_position <= 7.5)
   - Baseline Avg >= 26.0 (prevents low-average boom-or-bust sluggers)
   - Baseline SR >= 145.0 (prevents slow anchors)
   - Death SR >= 170.0 AND Death Balls >= 20 (prevents small-sample death SR flukes)
   - Chase SR >= 135.0 (prevents players who collapse/crawl in run chases)
   - Pressure Dot % <= 40.0% (prevents dot ball accumulators under pressure)

2. Multi-Gate Ceiling/Floor Cutoffs for Bowlers:
   - Matches in XI >= 40
   - Total Wickets >= 50
   - Balls Bowled >= 500
   - Baseline Economy <= 8.80 (eliminates leakers)
   - Death Economy <= 9.75 (strict death containment)
   - Crunch Overs Economy <= 9.20 (overs 1, 6, 18, 19, 20)
   - Bowling Strike Rate <= 24.0 (takes a wicket every 4 overs)
   - Crunch Overs Balls >= 70 (captain actually trusts them in crunch overs)
   - Pressure Dot % >= 30.0% (creates choke pressure)

3. 5-Dimension Balanced Scoring Formula:
   - Evaluates 5 independent pillars (Chase, Death, Baseline, Strike Rotation, Crisis/Heists).
   - Balanced Score = 0.80 * Weighted_Mean + 0.20 * Min(Dimensions).
   - Any player with a glaring deficiency in any single dimension receives a substantial score penalty.
"""

import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = r"c:\Users\pkpan\rpcheck"
OUT_DIR = os.path.join(BASE_DIR, "results_v5")
os.makedirs(OUT_DIR, exist_ok=True)

print("Loading data files...")
bbb = pd.read_csv(os.path.join(BASE_DIR, "ball_by_ball.csv"))
matches = pd.read_csv(os.path.join(BASE_DIR, "matches.csv"))
playing_eleven = pd.read_csv(os.path.join(BASE_DIR, "playing_eleven.csv"))
ctpm = pd.read_csv(os.path.join(BASE_DIR, "competition_team_player_mapping.csv"))

print(f"  Ball-by-ball: {len(bbb):,} rows")
print(f"  Matches: {len(matches):,}")
print(f"  Playing XI: {len(playing_eleven):,}")

# Opponent Strength Mapping
IPL_STRENGTH = {
    1: 0.95, 2: 0.90, 8: 0.88, 242: 0.85, 3508: 0.82,
    5: 0.80, 243: 0.78, 6: 0.75, 7: 0.72, 3507: 0.70
}
ICC_STRENGTH = {
    18: 1.00, 19: 0.98, 20: 0.95, 21: 0.92, 22: 0.88,
    23: 0.85, 24: 0.82, 25: 0.80, 26: 0.75, 27: 0.72,
    28: 0.60, 29: 0.58, 30: 0.55, 31: 0.52, 32: 0.50
}

def get_opp_strength(team_id):
    if team_id in IPL_STRENGTH:
        return IPL_STRENGTH[team_id]
    if team_id in ICC_STRENGTH:
        return ICC_STRENGTH[team_id]
    return 0.55

# Match-level context
match_meta = matches[['match_id', 'knock_out', 'win_team_id', 'revised_target', 'man_of_the_match']].copy()
match_meta['knock_out'] = match_meta['knock_out'].fillna(0).astype(int)

bbb_valid = bbb.copy()
bbb_valid['is_legal'] = ~bbb_valid['extras_type'].isin(['wide'])
bbb_valid['is_dot'] = (bbb_valid['runs'] == 0) & bbb_valid['is_legal']
bbb_valid['bat_runs'] = (bbb_valid['runs'] - bbb_valid['extras1_runs'].fillna(0) - bbb_valid['extras_2_runs'].fillna(0)).clip(lower=0)
bbb_valid['bowler_runs'] = (bbb_valid['runs'] - bbb_valid['extras_2_runs'].fillna(0)).clip(lower=0)

NON_BOWL_DISMISSALS = ['Run Out', 'Obstructing the field', 'Handled the ball']
bbb_valid['is_bowler_wicket'] = (
    bbb_valid['is_wicket'] &
    (~bbb_valid['dismissal_type'].isin(NON_BOWL_DISMISSALS)) &
    (bbb_valid['dismissed_player_id'] == bbb_valid['striker_id'])
)

bbb_valid = bbb_valid.merge(match_meta, on='match_id', how='left')
bbb_valid['opp_strength_bat'] = bbb_valid['bowling_team_id'].apply(get_opp_strength)
bbb_valid['opp_strength_bowl'] = bbb_valid['batting_team_id'].apply(get_opp_strength)

# Match Par Run Rate
match_stats = bbb_valid[bbb_valid['is_legal']].groupby('match_id').agg(
    m_runs=('runs', 'sum'),
    m_legal_balls=('is_legal', 'count')
).reset_index()
match_stats['match_rpo'] = (match_stats['m_runs'] / match_stats['m_legal_balls'].replace(0, np.nan)) * 6
match_stats['match_sr'] = (match_stats['m_runs'] / match_stats['m_legal_balls'].replace(0, np.nan)) * 100
bbb_valid = bbb_valid.merge(match_stats[['match_id', 'match_rpo', 'match_sr']], on='match_id', how='left')

# Innings 1 Total for Targets
inn1_runs = bbb_valid[bbb_valid['innings'] == 1].groupby('match_id')['runs'].sum().reset_index()
inn1_runs.rename(columns={'runs': 'inn1_total_runs'}, inplace=True)
bbb_valid = bbb_valid.merge(inn1_runs, on='match_id', how='left')

# Cumulative tracking & RRR
bbb_valid.sort_values(['match_id', 'innings', 'overid', 'over_ball_num'], inplace=True)
bbb_valid['cum_runs'] = bbb_valid.groupby(['match_id', 'innings'])['runs'].cumsum()
bbb_valid['cum_legal_balls'] = bbb_valid.groupby(['match_id', 'innings'])['is_legal'].cumsum()
bbb_valid['cum_wickets'] = bbb_valid.groupby(['match_id', 'innings'])['is_wicket'].cumsum()
bbb_valid['wickets_before'] = bbb_valid['cum_wickets'] - bbb_valid['is_wicket'].astype(int)

bbb_valid['target'] = np.where(
    bbb_valid['revised_target'].notna() & (bbb_valid['revised_target'] > 0),
    bbb_valid['revised_target'],
    bbb_valid['inn1_total_runs'] + 1
)
bbb_valid['runs_needed'] = (bbb_valid['target'] - bbb_valid['cum_runs']).clip(lower=0)
bbb_valid['balls_remaining'] = (120 - bbb_valid['cum_legal_balls']).clip(lower=0)
bbb_valid['rrr'] = np.where(
    (bbb_valid['innings'] == 2) & (bbb_valid['balls_remaining'] > 0),
    (bbb_valid['runs_needed'] / bbb_valid['balls_remaining']) * 6,
    0.0
)

# Partnership tracking
p_runs = []
current_match_inn = None
current_p = 0
for row in bbb_valid[['match_id', 'innings', 'bat_runs', 'is_wicket']].itertuples(index=False):
    mi = (row.match_id, row.innings)
    if mi != current_match_inn:
        current_match_inn = mi
        current_p = 0
    p_runs.append(current_p)
    if row.is_wicket:
        current_p = 0
    else:
        current_p += row.bat_runs

bbb_valid['partnership_before'] = p_runs

# Match Won flags
bbb_valid['is_match_won'] = bbb_valid['batting_team_id'] == bbb_valid['win_team_id']
bbb_valid['is_match_won_bowl'] = bbb_valid['bowling_team_id'] == bbb_valid['win_team_id']

# Collapse flag: 5+ wickets down OR (over <= 6 and 3+ wickets down)
bbb_valid['is_collapse'] = (bbb_valid['wickets_before'] >= 5) | ((bbb_valid['overid'] <= 6) & (bbb_valid['wickets_before'] >= 3))

# Pressure Flags
bbb_valid['is_pressure_bat'] = (
    ((bbb_valid['innings'] == 2) & (bbb_valid['rrr'] > 9.5) & (bbb_valid['balls_remaining'] < 60)) |
    ((bbb_valid['innings'] == 2) & (bbb_valid['rrr'] > 10.5)) |
    (bbb_valid['overid'] >= 16) |
    bbb_valid['is_collapse'] |
    (bbb_valid['knock_out'] == 1) |
    (bbb_valid['match_rpo'] < 7.5)
)

bbb_valid['is_pressure_bowl'] = (
    (bbb_valid['overid'] >= 16) |
    ((bbb_valid['innings'] == 2) & (bbb_valid['overid'] >= 14) & (bbb_valid['runs_needed'] <= 50)) |
    (bbb_valid['partnership_before'] >= 30) |
    ((bbb_valid['overid'] <= 6) & (bbb_valid['innings'] == 2) & (bbb_valid['target'] <= 155)) |
    (bbb_valid['knock_out'] == 1)
)

# HIGH-LEVERAGE CRUNCH OVERS: Overs 1, 6, 18, 19, 20
bbb_valid['is_high_leverage_over'] = bbb_valid['overid'].isin([1, 6, 18, 19, 20])

# MIRACLE CHASE HEIST: Won in Innings 2 where RRR >= 10.5 OR in overs 18-20
bbb_valid['is_miracle_heist'] = (
    bbb_valid['is_match_won'] &
    (bbb_valid['innings'] == 2) &
    ((bbb_valid['rrr'] >= 10.5) | (bbb_valid['overid'] >= 18))
)

bbb_legal = bbb_valid[bbb_valid['is_legal']].copy()

print(f"  Total Legal Deliveries: {len(bbb_legal):,}")
print(f"  Pressure Batting Deliveries: {bbb_legal['is_pressure_bat'].sum():,}")
print(f"  Pressure Bowling Deliveries: {bbb_legal['is_pressure_bowl'].sum():,}")
print(f"  High-Leverage Crunch Overs Deliveries: {bbb_legal['is_high_leverage_over'].sum():,}")

# --- ROLES AND MATCH PARTICIPATION ---
pe_played = playing_eleven[playing_eleven['is_played'] == True].copy()
player_names = ctpm[['player_id', 'player_name']].drop_duplicates('player_id')

player_match_stats = pe_played.groupby('player_id').agg(
    matches_in_xi=('match_id', 'nunique'),
    avg_batting_position=('batting_order', 'mean')
).reset_index()

def classify_batter(pos):
    if pd.isna(pos) or pos > 7.5:
        return 'Tail'
    elif pos <= 3.5:
        return 'Top Order'
    elif pos <= 5.5:
        return 'Middle Order'
    else:
        return 'Lower Order'

player_match_stats['bat_role'] = player_match_stats['avg_batting_position'].apply(classify_batter)

# Bowler phases
bowler_phases = bbb_legal.groupby('bowler_id').agg(
    total_balls_bowled=('is_legal', 'count'),
    pp_balls=('overid', lambda x: (x <= 6).sum()),
    mid_balls=('overid', lambda x: ((x >= 7) & (x <= 15)).sum()),
    death_balls=('overid', lambda x: (x >= 16).sum())
).reset_index()
bowler_phases.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bowler_phases['pp_ratio'] = bowler_phases['pp_balls'] / bowler_phases['total_balls_bowled'].replace(0, np.nan)
bowler_phases['mid_ratio'] = bowler_phases['mid_balls'] / bowler_phases['total_balls_bowled'].replace(0, np.nan)
bowler_phases['death_ratio'] = bowler_phases['death_balls'] / bowler_phases['total_balls_bowled'].replace(0, np.nan)

def classify_bowler(row):
    if row['pp_ratio'] >= 0.35:
        return 'PP Specialist'
    elif row['death_ratio'] >= 0.30:
        return 'Death Specialist'
    elif row['mid_ratio'] >= 0.45:
        return 'Middle Overs Specialist'
    else:
        return 'All-Phase Bowler'

bowler_phases['bowler_role'] = bowler_phases.apply(classify_bowler, axis=1)

motm_counts = matches[matches['man_of_the_match'] > 0]['man_of_the_match'].value_counts().reset_index()
motm_counts.columns = ['player_id', 'motm_count']

# --- COMPUTE COMPREHENSIVE BATTING METRICS ---
print("\nComputing comprehensive batting metrics...")
b_all = bbb_legal.groupby('striker_id').agg(
    total_runs=('bat_runs', 'sum'),
    total_balls=('is_legal', 'count'),
    total_dismissals=('is_wicket', 'sum'),
    total_dots=('is_dot', 'sum'),
    total_fours=('is_four', 'sum'),
    total_sixes=('is_six', 'sum'),
    strike_rot_balls=('bat_runs', lambda x: x.isin([1, 2, 3]).sum()),
    non_boundary_runs=('bat_runs', lambda x: x[x.isin([1, 2, 3])].sum()),
    weighted_runs=('bat_runs', lambda x: (x * bbb_legal.loc[x.index, 'opp_strength_bat']).sum())
).reset_index()
b_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_all['baseline_avg'] = np.where(b_all['total_dismissals'] > 0, b_all['total_runs'] / b_all['total_dismissals'], b_all['total_runs'])
b_all['baseline_sr'] = (b_all['total_runs'] / b_all['total_balls'].replace(0, np.nan)) * 100
b_all['baseline_dot_pct'] = (b_all['total_dots'] / b_all['total_balls'].replace(0, np.nan)) * 100
b_all['strike_rotation_pct'] = (b_all['strike_rot_balls'] / b_all['total_balls'].replace(0, np.nan)) * 100
b_all['non_boundary_sr'] = (b_all['non_boundary_runs'] / b_all['total_balls'].replace(0, np.nan)) * 100
b_all['opp_weighted_runs'] = b_all['weighted_runs']

# Pressure subset
p_df = bbb_legal[bbb_legal['is_pressure_bat']]
b_press = p_df.groupby('striker_id').agg(
    pressure_runs=('bat_runs', 'sum'),
    pressure_balls=('is_legal', 'count'),
    pressure_dismissals=('is_wicket', 'sum'),
    pressure_dots=('is_dot', 'sum')
).reset_index()
b_press.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_press['pressure_avg'] = np.where(b_press['pressure_dismissals'] > 0, b_press['pressure_runs'] / b_press['pressure_dismissals'], b_press['pressure_runs'])
b_press['pressure_sr'] = (b_press['pressure_runs'] / b_press['pressure_balls'].replace(0, np.nan)) * 100
b_press['pressure_dot_pct'] = (b_press['pressure_dots'] / b_press['pressure_balls'].replace(0, np.nan)) * 100
res_bat = b_all.merge(b_press, on='player_id', how='left')

# Chase subset
chase_df = bbb_legal[bbb_legal['innings'] == 2]
c_all = chase_df.groupby('striker_id').agg(
    chase_runs=('bat_runs', 'sum'),
    chase_balls=('is_legal', 'count'),
    chase_dismissals=('is_wicket', 'sum')
).reset_index()
c_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
c_all['chase_avg'] = np.where(c_all['chase_dismissals'] > 0, c_all['chase_runs'] / c_all['chase_dismissals'], c_all['chase_runs'])
c_all['chase_sr'] = (c_all['chase_runs'] / c_all['chase_balls'].replace(0, np.nan)) * 100
res_bat = res_bat.merge(c_all, on='player_id', how='left')

# High RRR Chase (RRR > 9.5)
high_rrr_df = bbb_legal[(bbb_legal['innings'] == 2) & (bbb_legal['rrr'] > 9.5)]
hr_all = high_rrr_df.groupby('striker_id').agg(
    hr_runs=('bat_runs', 'sum'),
    hr_balls=('is_legal', 'count')
).reset_index()
hr_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
hr_all['high_rrr_sr'] = (hr_all['hr_runs'] / hr_all['hr_balls'].replace(0, np.nan)) * 100
res_bat = res_bat.merge(hr_all[['player_id', 'high_rrr_sr']], on='player_id', how='left')

# Death subset
death_df = bbb_legal[bbb_legal['overid'] >= 16]
d_all = death_df.groupby('striker_id').agg(
    death_runs=('bat_runs', 'sum'),
    death_balls=('is_legal', 'count'),
    death_dots=('is_dot', 'sum'),
    death_fours=('is_four', 'sum'),
    death_sixes=('is_six', 'sum')
).reset_index()
d_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
d_all['death_sr'] = (d_all['death_runs'] / d_all['death_balls'].replace(0, np.nan)) * 100
d_all['death_dot_pct'] = (d_all['death_dots'] / d_all['death_balls'].replace(0, np.nan)) * 100
d_all['death_balls_per_boundary'] = d_all['death_balls'] / (d_all['death_fours'] + d_all['death_sixes']).replace(0, np.nan)
res_bat = res_bat.merge(d_all[['player_id', 'death_runs', 'death_balls', 'death_sr', 'death_dot_pct', 'death_balls_per_boundary']], on='player_id', how='left')

# Miracle Heist Comebacks
heist_df = bbb_legal[bbb_legal['is_miracle_heist']]
h_all = heist_df.groupby('striker_id').agg(
    heist_runs=('bat_runs', 'sum'),
    heist_balls=('is_legal', 'count')
).reset_index()
h_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
h_all['heist_sr'] = (h_all['heist_runs'] / h_all['heist_balls'].replace(0, np.nan)) * 100
res_bat = res_bat.merge(h_all[['player_id', 'heist_runs', 'heist_sr']], on='player_id', how='left')

# Collapse Rescue
col_df = bbb_legal[bbb_legal['is_collapse']]
col_all = col_df.groupby('striker_id').agg(
    collapse_runs=('bat_runs', 'sum'),
    collapse_dismissals=('is_wicket', 'sum')
).reset_index()
col_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
col_all['collapse_avg'] = np.where(col_all['collapse_dismissals'] > 0, col_all['collapse_runs'] / col_all['collapse_dismissals'], col_all['collapse_runs'])
res_bat = res_bat.merge(col_all[['player_id', 'collapse_runs', 'collapse_avg']], on='player_id', how='left')

# Pitch Adjusted Relative SR
bbb_legal['relative_ball_sr'] = (bbb_legal['bat_runs'] / bbb_legal['match_sr'].replace(0, np.nan)) * 100
rel_sr = bbb_legal.groupby('striker_id')['relative_ball_sr'].mean().reset_index()
rel_sr.columns = ['player_id', 'relative_sr_pct']
res_bat = res_bat.merge(rel_sr, on='player_id', how='left')

# Attach metadata
res_bat = res_bat.merge(player_match_stats[['player_id', 'matches_in_xi', 'avg_batting_position', 'bat_role']], on='player_id', how='left')
res_bat = res_bat.merge(motm_counts, on='player_id', how='left')
res_bat['motm_count'] = res_bat['motm_count'].fillna(0)
res_bat = res_bat.merge(player_names, on='player_id', how='left')

# Fill missing numericals with 0 or sensible floors
fill_zeros = ['heist_runs', 'heist_sr', 'collapse_runs', 'death_runs', 'death_balls']
for col in fill_zeros:
    res_bat[col] = res_bat[col].fillna(0)

# ─────────────────────────────────────────────────────────────
# MULTI-GATE FLOOR CUTOFFS FOR BATTERS
# ─────────────────────────────────────────────────────────────
print("\nApplying Multi-Gate Cutoffs for Batters...")
bat_cutoff = (
    (res_bat['matches_in_xi'] >= 40) &
    (res_bat['total_runs'] >= 600) &
    (res_bat['avg_batting_position'] <= 7.5) &
    (res_bat['baseline_avg'] >= 26.0) &
    (res_bat['baseline_sr'] >= 145.0) &
    (res_bat['death_sr'] >= 170.0) &
    (res_bat['death_balls'] >= 20) &
    (res_bat['chase_sr'] >= 135.0) &
    (res_bat['pressure_dot_pct'] <= 40.0)
)

bat_eligible = res_bat[bat_cutoff].copy()
print(f"  Total Batters Passing ALL 8 Strict Cutoffs: {len(bat_eligible)}")

# --- BATTING 5-DIMENSION BALANCED SCORING ---
def norm_series(s, invert=False):
    s_min = s.min()
    s_max = s.max()
    if s_max == s_min:
        return pd.Series(50.0, index=s.index)
    if invert:
        return 100.0 * (s_max - s) / (s_max - s_min)
    return 100.0 * (s - s_min) / (s_max - s_min)

be = bat_eligible.copy()

# Fill median for auxiliary components
be['high_rrr_sr'] = be['high_rrr_sr'].fillna(be['high_rrr_sr'].median())
be['collapse_avg'] = be['collapse_avg'].fillna(be['collapse_avg'].median())
be['death_balls_per_boundary'] = be['death_balls_per_boundary'].fillna(be['death_balls_per_boundary'].median())

# Dim 1: Chase Mastery
d1_c_sr = norm_series(be['chase_sr'])
d1_c_avg = norm_series(be['chase_avg'])
d1_hr_sr = norm_series(be['high_rrr_sr'])
be['dim1_chase'] = 0.45 * d1_c_sr + 0.35 * d1_c_avg + 0.20 * d1_hr_sr

# Dim 2: Death Overs Power
d2_d_sr = norm_series(be['death_sr'])
d2_d_bpb = norm_series(be['death_balls_per_boundary'], invert=True)
d2_d_dot = norm_series(be['death_dot_pct'], invert=True)
be['dim2_death'] = 0.50 * d2_d_sr + 0.30 * d2_d_bpb + 0.20 * d2_d_dot

# Dim 3: Baseline Quality & Consistency
d3_b_sr = norm_series(be['baseline_sr'])
d3_b_avg = norm_series(be['baseline_avg'])
d3_opp = norm_series(be['opp_weighted_runs'] / be['total_runs'])
be['dim3_quality'] = 0.40 * d3_b_sr + 0.35 * d3_b_avg + 0.25 * d3_opp

# Dim 4: Strike Rotation & Dot Control
d4_p_dot = norm_series(be['pressure_dot_pct'], invert=True)
d4_s_rot = norm_series(be['strike_rotation_pct'])
d4_nb_sr = norm_series(be['non_boundary_sr'])
be['dim4_strike_rot'] = 0.45 * d4_p_dot + 0.35 * d4_s_rot + 0.20 * d4_nb_sr

# Dim 5: Crisis & Clutch Heists
d5_heist = norm_series(be['heist_runs'])
d5_col = norm_series(be['collapse_runs'])
d5_rel = norm_series(be['relative_sr_pct'])
be['dim5_crisis'] = 0.45 * d5_heist + 0.35 * d5_col + 0.20 * d5_rel

# Calculate Minimum Dimension (Floor) and Weighted Mean
dim_cols = ['dim1_chase', 'dim2_death', 'dim3_quality', 'dim4_strike_rot', 'dim5_crisis']
be['dim_min'] = be[dim_cols].min(axis=1)
be['dim_weighted_mean'] = (
    0.25 * be['dim1_chase'] +
    0.25 * be['dim2_death'] +
    0.20 * be['dim3_quality'] +
    0.15 * be['dim4_strike_rot'] +
    0.15 * be['dim5_crisis']
)

# Balanced Pressure Score: 80% Mean + 20% Min Dimension Floor
be['balanced_pressure_score'] = 0.80 * be['dim_weighted_mean'] + 0.20 * be['dim_min']
bat_eligible = be.sort_values('balanced_pressure_score', ascending=False).reset_index(drop=True)

print("\n--- TOP 10 BALANCED BATTERS (OVERALL) ---")
for i, r in bat_eligible.head(10).iterrows():
    print(f"  {i+1}. {r['player_name']:<20} | Role: {r['bat_role']:<12} | Mat: {int(r['matches_in_xi']):<2} | BaseSR: {r['baseline_sr']:<5.1f} | DeathSR: {r['death_sr']:<5.1f} | ChaseSR: {r['chase_sr']:<5.1f} | PressDot: {r['pressure_dot_pct']:<4.1f}% | MinDim: {r['dim_min']:<4.1f} | Score: {r['balanced_pressure_score']:<5.1f}")


# --- COMPUTE COMPREHENSIVE BOWLING METRICS ---
print("\nComputing comprehensive bowling metrics...")
bw_all = bbb_legal.groupby('bowler_id').agg(
    total_runs_b=('bowler_runs', 'sum'),
    total_balls_b=('is_legal', 'count'),
    total_wickets=('is_bowler_wicket', 'sum'),
    total_dots_b=('is_dot', 'sum'),
    top_order_wickets=('is_bowler_wicket', lambda x: (x & (bbb_legal.loc[x.index, 'batting_order'] <= 4)).sum()),
    weighted_wickets=('is_bowler_wicket', lambda x: (x * bbb_legal.loc[x.index, 'opp_strength_bowl']).sum())
).reset_index()
bw_all.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_all['baseline_econ'] = (bw_all['total_runs_b'] / bw_all['total_balls_b'].replace(0, np.nan)) * 6
bw_all['baseline_sr'] = bw_all['total_balls_b'] / bw_all['total_wickets'].replace(0, np.nan)
bw_all['baseline_dot_pct'] = (bw_all['total_dots_b'] / bw_all['total_balls_b'].replace(0, np.nan)) * 100
bw_all['top_order_wkt_pct'] = (bw_all['top_order_wickets'] / bw_all['total_wickets'].replace(0, np.nan)) * 100

# Pressure subset
p_bowl_df = bbb_legal[bbb_legal['is_pressure_bowl']]
bw_press = p_bowl_df.groupby('bowler_id').agg(
    pressure_runs_b=('bowler_runs', 'sum'),
    pressure_balls_b=('is_legal', 'count'),
    pressure_wickets_b=('is_bowler_wicket', 'sum'),
    pressure_dots_b=('is_dot', 'sum')
).reset_index()
bw_press.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_press['pressure_econ'] = (bw_press['pressure_runs_b'] / bw_press['pressure_balls_b'].replace(0, np.nan)) * 6
bw_press['pressure_dot_pct'] = (bw_press['pressure_dots_b'] / bw_press['pressure_balls_b'].replace(0, np.nan)) * 100
res_bowl = bw_all.merge(bw_press, on='player_id', how='left')

# High-leverage Crunch Overs (1, 6, 18, 19, 20)
hl_df = bbb_legal[bbb_legal['is_high_leverage_over']]
hl_all = hl_df.groupby('bowler_id').agg(
    hl_balls=('is_legal', 'count'),
    hl_runs=('bowler_runs', 'sum'),
    hl_wkts=('is_bowler_wicket', 'sum'),
    hl_dots=('is_dot', 'sum')
).reset_index()
hl_all.rename(columns={'bowler_id': 'player_id'}, inplace=True)
hl_all['hl_econ'] = (hl_all['hl_runs'] / hl_all['hl_balls'].replace(0, np.nan)) * 6
hl_all['hl_dot_pct'] = (hl_all['hl_dots'] / hl_all['hl_balls'].replace(0, np.nan)) * 100
res_bowl = res_bowl.merge(hl_all, on='player_id', how='left')

# Death Overs (16-20)
death_df_b = bbb_legal[bbb_legal['overid'] >= 16]
d_bowl = death_df_b.groupby('bowler_id').agg(
    death_runs_b=('bowler_runs', 'sum'),
    death_balls_b=('is_legal', 'count'),
    death_wickets_b=('is_bowler_wicket', 'sum'),
    death_dots_b=('is_dot', 'sum')
).reset_index()
d_bowl.rename(columns={'bowler_id': 'player_id'}, inplace=True)
d_bowl['death_econ'] = (d_bowl['death_runs_b'] / d_bowl['death_balls_b'].replace(0, np.nan)) * 6
d_bowl['death_dot_pct'] = (d_bowl['death_dots_b'] / d_bowl['death_balls_b'].replace(0, np.nan)) * 100
res_bowl = res_bowl.merge(d_bowl, on='player_id', how='left')

# Extreme Death (19-20)
ed_df = bbb_legal[bbb_legal['overid'] >= 19]
ed_bowl = ed_df.groupby('bowler_id').agg(
    ed_runs=('bowler_runs', 'sum'),
    ed_balls=('is_legal', 'count')
).reset_index()
ed_bowl.rename(columns={'bowler_id': 'player_id'}, inplace=True)
ed_bowl['ext_death_econ'] = (ed_bowl['ed_runs'] / ed_bowl['ed_balls'].replace(0, np.nan)) * 6
res_bowl = res_bowl.merge(ed_bowl[['player_id', 'ext_death_econ']], on='player_id', how='left')

# Powerplay (1-6)
pp_df_b = bbb_legal[bbb_legal['overid'] <= 6]
pp_bowl = pp_df_b.groupby('bowler_id').agg(
    pp_balls=('is_legal', 'count'),
    pp_runs=('bowler_runs', 'sum'),
    pp_wkts=('is_bowler_wicket', 'sum'),
    pp_dots=('is_dot', 'sum')
).reset_index()
pp_bowl.rename(columns={'bowler_id': 'player_id'}, inplace=True)
pp_bowl['pp_econ'] = (pp_bowl['pp_runs'] / pp_bowl['pp_balls'].replace(0, np.nan)) * 6
pp_bowl['pp_dot_pct'] = (pp_bowl['pp_dots'] / pp_bowl['pp_balls'].replace(0, np.nan)) * 100
res_bowl = res_bowl.merge(pp_bowl, on='player_id', how='left')

# Middle (7-15)
mid_df_b = bbb_legal[(bbb_legal['overid'] >= 7) & (bbb_legal['overid'] <= 15)]
mid_bowl = mid_df_b.groupby('bowler_id').agg(
    mid_balls=('is_legal', 'count'),
    mid_runs=('bowler_runs', 'sum'),
    mid_wkts=('is_bowler_wicket', 'sum'),
    mid_dots=('is_dot', 'sum')
).reset_index()
mid_bowl.rename(columns={'bowler_id': 'player_id'}, inplace=True)
mid_bowl['mid_econ'] = (mid_bowl['mid_runs'] / mid_bowl['mid_balls'].replace(0, np.nan)) * 6
mid_bowl['mid_dot_pct'] = (mid_bowl['mid_dots'] / mid_bowl['mid_balls'].replace(0, np.nan)) * 100
res_bowl = res_bowl.merge(mid_bowl, on='player_id', how='left')

# Partnership Breaks
pb30_df = bbb_legal[(bbb_legal['partnership_before'] >= 30) & (bbb_legal['is_bowler_wicket'])]
pb30 = pb30_df.groupby('bowler_id')['is_bowler_wicket'].sum().reset_index()
pb30.columns = ['player_id', 'pb_30']
res_bowl = res_bowl.merge(pb30, on='player_id', how='left')

# Relative Economy vs Par
bbb_legal['relative_ball_econ'] = (bbb_legal['bowler_runs'] / bbb_legal['match_rpo'].replace(0, np.nan)) * 6
rel_econ = bbb_legal.groupby('bowler_id')['relative_ball_econ'].mean().reset_index()
rel_econ.columns = ['player_id', 'relative_econ_pct']
res_bowl = res_bowl.merge(rel_econ, on='player_id', how='left')

# Attach metadata
res_bowl = res_bowl.merge(player_match_stats[['player_id', 'matches_in_xi']], on='player_id', how='left')
res_bowl = res_bowl.merge(bowler_phases[['player_id', 'pp_balls', 'mid_balls', 'death_balls', 'pp_ratio', 'mid_ratio', 'death_ratio', 'bowler_role']], on='player_id', how='left', suffixes=('', '_phase'))
res_bowl = res_bowl.merge(player_names, on='player_id', how='left')

# Fill missing
res_bowl['pb_30'] = res_bowl['pb_30'].fillna(0)
res_bowl['hl_balls'] = res_bowl['hl_balls'].fillna(0)
res_bowl['death_balls_b'] = res_bowl['death_balls_b'].fillna(0)

# ─────────────────────────────────────────────────────────────
# MULTI-GATE FLOOR/CEILING CUTOFFS FOR BOWLERS
# ─────────────────────────────────────────────────────────────
print("\nApplying Multi-Gate Cutoffs for Bowlers...")
bowl_cutoff = (
    (res_bowl['matches_in_xi'] >= 40) &
    (res_bowl['total_wickets'] >= 50) &
    (res_bowl['total_balls_b'] >= 500) &
    (res_bowl['baseline_econ'] <= 8.80) &
    (res_bowl['death_econ'] <= 9.75) &
    (res_bowl['hl_econ'] <= 9.20) &
    (res_bowl['baseline_sr'] <= 24.0) &
    (res_bowl['hl_balls'] >= 70) &
    (res_bowl['pressure_dot_pct'] >= 30.0)
)

bowl_eligible = res_bowl[bowl_cutoff].copy()
print(f"  Total Bowlers Passing ALL 9 Strict Cutoffs: {len(bowl_eligible)}")

# --- BOWLING 5-DIMENSION BALANCED SCORING ---
boe = bowl_eligible.copy()

# Fill medians for extreme death
boe['ext_death_econ'] = boe['ext_death_econ'].fillna(boe['ext_death_econ'].median())

# Dim 1: Crunch Overs Lockdown (1, 6, 18, 19, 20)
d1_hl_econ = norm_series(boe['hl_econ'], invert=True)
d1_hl_dot = norm_series(boe['hl_dot_pct'])
d1_hl_wkts = norm_series(boe['hl_wkts'] / (boe['hl_balls'] / 6))
boe['dim1_crunch'] = 0.50 * d1_hl_econ + 0.30 * d1_hl_dot + 0.20 * d1_hl_wkts

# Dim 2: Death Overs Control
d2_d_econ = norm_series(boe['death_econ'], invert=True)
d2_ed_econ = norm_series(boe['ext_death_econ'], invert=True)
d2_d_dot = norm_series(boe['death_dot_pct'])
boe['dim2_death'] = 0.45 * d2_d_econ + 0.35 * d2_ed_econ + 0.20 * d2_d_dot

# Dim 3: Wicket Threat & Quality
d3_b_sr = norm_series(boe['baseline_sr'], invert=True)
d3_top = norm_series(boe['top_order_wkt_pct'])
d3_opp = norm_series(boe['weighted_wickets'])
boe['dim3_wickets'] = 0.40 * d3_b_sr + 0.35 * d3_top + 0.25 * d3_opp

# Dim 4: Dot Ball Pressure Creation
d4_p_dot = norm_series(boe['pressure_dot_pct'])
d4_b_dot = norm_series(boe['baseline_dot_pct'])
d4_pb = norm_series(boe['pb_30'])
boe['dim4_dots'] = 0.45 * d4_p_dot + 0.35 * d4_b_dot + 0.20 * d4_pb

# Dim 5: Overall Economy & Par Containment
d5_b_econ = norm_series(boe['baseline_econ'], invert=True)
d5_rel_econ = norm_series(boe['relative_econ_pct'], invert=True)
boe['dim5_econ'] = 0.60 * d5_b_econ + 0.40 * d5_rel_econ

# Minimum Dimension Floor & Weighted Mean
bowl_dim_cols = ['dim1_crunch', 'dim2_death', 'dim3_wickets', 'dim4_dots', 'dim5_econ']
boe['dim_min'] = boe[bowl_dim_cols].min(axis=1)
boe['dim_weighted_mean'] = (
    0.25 * boe['dim1_crunch'] +
    0.25 * boe['dim2_death'] +
    0.20 * boe['dim3_wickets'] +
    0.15 * boe['dim4_dots'] +
    0.15 * boe['dim5_econ']
)

# Balanced Pressure Score: 80% Mean + 20% Min Dimension Floor
boe['balanced_pressure_score'] = 0.80 * boe['dim_weighted_mean'] + 0.20 * boe['dim_min']
bowl_eligible = boe.sort_values('balanced_pressure_score', ascending=False).reset_index(drop=True)

print("\n--- TOP 10 BALANCED BOWLERS (OVERALL) ---")
for i, r in bowl_eligible.head(10).iterrows():
    print(f"  {i+1}. {r['player_name']:<20} | Role: {r['bowler_role']:<20} | Mat: {int(r['matches_in_xi']):<2} | Wkts: {int(r['total_wickets']):<3} | BaseEcon: {r['baseline_econ']:<5.2f} | DeathEcon: {r['death_econ']:<5.2f} | HLEcon: {r['hl_econ']:<5.2f} | MinDim: {r['dim_min']:<4.1f} | Score: {r['balanced_pressure_score']:<5.1f}")

# ─────────────────────────────────────────────────────────────
# ROLE-BASED CLASSIFICATION & SPLITS
# ─────────────────────────────────────────────────────────────
print("\nGenerating Role-Based Top 10s...")

# Batting Roles:
# Top Order: avg_batting_position <= 3.5
# Middle Order: 3.5 < avg_batting_position <= 5.5
# Lower Order / Finishers: avg_batting_position > 5.5
top_bat = bat_eligible[bat_eligible['bat_role'] == 'Top Order'].head(10).copy()
mid_bat = bat_eligible[bat_eligible['bat_role'] == 'Middle Order'].head(10).copy()
low_bat = bat_eligible[bat_eligible['bat_role'] == 'Lower Order'].head(10).copy()

top_bat['rank'] = range(1, len(top_bat) + 1)
mid_bat['rank'] = range(1, len(mid_bat) + 1)
low_bat['rank'] = range(1, len(low_bat) + 1)

# Bowling Roles:
# Powerplay Specialists: pp_ratio >= 0.35 (or pp_balls >= 150)
# Middle Overs Specialists: mid_ratio >= 0.40
# Death Overs Specialists: death_ratio >= 0.25 (or death_balls >= 100)
pp_bowlers = bowl_eligible[bowl_eligible['pp_balls'] >= 100].copy()
pp_bowlers['pp_score'] = 0.40 * norm_series(pp_bowlers['pp_econ'], invert=True) + \
                         0.35 * norm_series(pp_bowlers['pp_dot_pct']) + \
                         0.25 * norm_series(pp_bowlers['pp_wkts'])
pp_bowlers = pp_bowlers.sort_values('pp_score', ascending=False).head(10).reset_index(drop=True)
pp_bowlers['rank'] = range(1, len(pp_bowlers) + 1)

mid_bowlers = bowl_eligible[bowl_eligible['mid_balls'] >= 150].copy()
mid_bowlers['mid_score'] = 0.40 * norm_series(mid_bowlers['mid_econ'], invert=True) + \
                           0.35 * norm_series(mid_bowlers['mid_dot_pct']) + \
                           0.25 * norm_series(mid_bowlers['mid_wkts'])
mid_bowlers = mid_bowlers.sort_values('mid_score', ascending=False).head(10).reset_index(drop=True)
mid_bowlers['rank'] = range(1, len(mid_bowlers) + 1)

death_bowlers = bowl_eligible[bowl_eligible['death_balls_b'] >= 70].copy()
death_bowlers['death_phase_score'] = 0.45 * norm_series(death_bowlers['death_econ'], invert=True) + \
                                     0.30 * norm_series(death_bowlers['death_dot_pct']) + \
                                     0.25 * norm_series(death_bowlers['death_wickets_b'])
death_bowlers = death_bowlers.sort_values('death_phase_score', ascending=False).head(10).reset_index(drop=True)
death_bowlers['rank'] = range(1, len(death_bowlers) + 1)

# Overall Top 10s
top10_overall_batters = bat_eligible.head(10).copy()
top10_overall_batters['rank'] = range(1, 11)

top10_overall_bowlers = bowl_eligible.head(10).copy()
top10_overall_bowlers['rank'] = range(1, 11)

# Save CSVs
top10_overall_batters.to_csv(os.path.join(OUT_DIR, "top10_overall_batters.csv"), index=False)
top10_overall_bowlers.to_csv(os.path.join(OUT_DIR, "top10_overall_bowlers.csv"), index=False)

top_bat.to_csv(os.path.join(OUT_DIR, "top10_toporder_batters.csv"), index=False)
mid_bat.to_csv(os.path.join(OUT_DIR, "top10_middleorder_batters.csv"), index=False)
low_bat.to_csv(os.path.join(OUT_DIR, "top10_lowerorder_batters.csv"), index=False)

pp_bowlers.to_csv(os.path.join(OUT_DIR, "top10_pp_bowlers.csv"), index=False)
mid_bowlers.to_csv(os.path.join(OUT_DIR, "top10_mid_bowlers.csv"), index=False)
death_bowlers.to_csv(os.path.join(OUT_DIR, "top10_death_bowlers.csv"), index=False)

bat_eligible.to_csv(os.path.join(OUT_DIR, "full_eligible_batters.csv"), index=False)
bowl_eligible.to_csv(os.path.join(OUT_DIR, "full_eligible_bowlers.csv"), index=False)

# Write Summary File
with open(os.path.join(OUT_DIR, "analysis_v5_summary.txt"), "w") as f:
    f.write("=== T20 CRICKET PRESSURE PERFORMANCE ANALYSIS v5 ===\n")
    f.write("Multi-Gate Cutoffs & 5-Dimension Balanced Scoring\n\n")
    f.write(f"Eligible Batters Passing All 8 Cutoffs: {len(bat_eligible)}\n")
    f.write(f"Eligible Bowlers Passing All 9 Cutoffs: {len(bowl_eligible)}\n\n")

    f.write("TOP 10 OVERALL BATTERS UNDER PRESSURE:\n")
    for i, r in top10_overall_batters.iterrows():
        f.write(f"{int(r['rank'])}. {r['player_name']:<22} | Role:{r['bat_role']:<12} | Mat:{int(r['matches_in_xi']):<2} | BaseSR:{r['baseline_sr']:<5.1f} | DeathSR:{r['death_sr']:<5.1f} | ChaseSR:{r['chase_sr']:<5.1f} | PressDot:{r['pressure_dot_pct']:<4.1f}% | MinDim:{r['dim_min']:<4.1f} | Score:{r['balanced_pressure_score']:<5.1f}\n")

    f.write("\nTOP 10 OVERALL BOWLERS UNDER PRESSURE:\n")
    for i, r in top10_overall_bowlers.iterrows():
        f.write(f"{int(r['rank'])}. {r['player_name']:<22} | Role:{r['bowler_role']:<20} | Mat:{int(r['matches_in_xi']):<2} | Wkts:{int(r['total_wickets']):<3} | BaseEcon:{r['baseline_econ']:<5.2f} | DeathEcon:{r['death_econ']:<5.2f} | HLEcon:{r['hl_econ']:<5.2f} | MinDim:{r['dim_min']:<4.1f} | Score:{r['balanced_pressure_score']:<5.1f}\n")

print("\nAnalysis v5 completed successfully! All files generated in results_v5/")
