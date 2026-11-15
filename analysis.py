"""
T20 Cricket Pressure Performance Analysis
Comprehensive analysis to rank Top 10 Batters and Top 10 Bowlers
based on multi-dimensional pressure performance metrics.
"""

import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 0. Setup
# ============================================================
RESULTS_DIR = r'c:\Users\pkpan\rpcheck\results'
os.makedirs(RESULTS_DIR, exist_ok=True)

MIN_MATCHES = 20

print("Loading data files...")

# ============================================================
# 1. Load Data
# ============================================================
bbb = pd.read_csv(r'c:\Users\pkpan\rpcheck\ball_by_ball.csv')
matches = pd.read_csv(r'c:\Users\pkpan\rpcheck\matches.csv')
competitions = pd.read_csv(r'c:\Users\pkpan\rpcheck\competitions.csv')
mapping = pd.read_csv(r'c:\Users\pkpan\rpcheck\competition_team_player_mapping.csv')

print(f"Ball-by-ball: {len(bbb):,} rows")
print(f"Matches: {len(matches):,} rows")

# ============================================================
# 2. Enrich Matches with Context
# ============================================================
print("\nEnriching match context...")

# First innings total runs (sum of runs column per match, inn=1)
inn1_scores = bbb[bbb['innings'] == 1].groupby('match_id')['runs'].sum().reset_index()
inn1_scores.columns = ['match_id', 'inn1_total']

# Second innings total runs
inn2_scores = bbb[bbb['innings'] == 2].groupby('match_id')['runs'].sum().reset_index()
inn2_scores.columns = ['match_id', 'inn2_total']

matches = matches.merge(inn1_scores, on='match_id', how='left')
matches = matches.merge(inn2_scores, on='match_id', how='left')

# High/low scoring flags based on first innings score
matches['high_scoring'] = matches['inn1_total'] >= 180      # batting team scored big
matches['low_scoring']  = matches['inn1_total'] < 140       # tough pitch

# Knock-out flag
matches['is_knockout'] = matches['knock_out'].fillna(0).astype(int) == 1

print(f"High scoring matches: {matches['high_scoring'].sum()}")
print(f"Low scoring matches:  {matches['low_scoring'].sum()}")
print(f"Knock-out matches:    {matches['is_knockout'].sum()}")

# ============================================================
# 3. Enrich Ball-by-Ball with Match Context
# ============================================================
print("\nEnriching ball-by-ball data...")

bbb = bbb.merge(
    matches[['match_id', 'inn1_total', 'inn2_total', 'high_scoring', 'low_scoring', 'is_knockout']],
    on='match_id', how='left'
)

# Legal delivery flag (not wide or no-ball)
bbb['is_wide']  = bbb['extras_type'] == 'wide'
bbb['is_noball'] = bbb['extras_type'] == 'Overstep'
bbb['is_legal'] = ~(bbb['is_wide'] | bbb['is_noball'])

# Batter runs (runs column minus extras - but extras_type=wide/nb means 0 to batter normally)
# runs column = total runs on delivery (bat_runs + extras)
# extras1_runs = wides/nb (batter doesn't get credit)
# extras_2_runs = leg byes/byes (team gets, batter doesn't)
# batter runs = runs - extras1_runs - extras_2_runs
bbb['bat_runs'] = bbb['runs'] - bbb['extras1_runs'] - bbb['extras_2_runs']
bbb['bat_runs'] = bbb['bat_runs'].clip(lower=0)

# Dot ball (legal delivery, 0 batter runs)
bbb['is_dot'] = bbb['is_legal'] & (bbb['bat_runs'] == 0) & ~bbb['is_wicket']

# ============================================================
# 4. Build Running Totals for Pressure Context per Delivery
# ============================================================
print("Computing per-ball pressure context...")

# Sort by match, innings, ball order
bbb = bbb.sort_values(['match_id', 'innings', 'innings_ball_num']).reset_index(drop=True)

# Cumulative innings runs and wickets before this ball
bbb['cum_runs_bf'] = bbb.groupby(['match_id', 'innings'])['runs'].cumsum() - bbb['runs']
bbb['cum_wkts_bf'] = bbb.groupby(['match_id', 'innings'])['is_wicket'].cumsum() - bbb['is_wicket']

# Total balls in an innings = 120 (or less for DLS)
# Remaining balls = max legal ball number - innings_ball_num (approximation)
# Better: use overid and over_ball_num to compute ball in over (0-indexed)
bbb['ball_in_over'] = bbb['over_ball_num']  # 1-indexed
bbb['balls_bowled'] = (bbb['overid'] - 1) * 6 + bbb['ball_in_over']

# For chase (inn2): compute remaining runs needed and remaining overs
# Target = inn1_total + 1
bbb['target'] = np.where(bbb['innings'] == 2, bbb['inn1_total'] + 1, np.nan)
bbb['runs_needed_bf'] = bbb['target'] - bbb['cum_runs_bf']
bbb['balls_remaining'] = np.where(bbb['innings'] == 2, 120 - bbb['balls_bowled'] + 1, np.nan)
bbb['overs_remaining']  = bbb['balls_remaining'] / 6

# Required run rate (runs per over needed)
bbb['rrr'] = np.where(
    (bbb['innings'] == 2) & (bbb['overs_remaining'] > 0),
    bbb['runs_needed_bf'] / bbb['overs_remaining'],
    np.nan
)

# ============================================================
# 5. Wickets in Last 10 Balls (Mini-Collapse Detection)
# ============================================================
print("Computing mini-collapse context...")

# For each ball, count wickets in previous 10 balls (rolling)
def rolling_wkts_last10(group):
    wkts = group['is_wicket'].astype(int)
    return wkts.rolling(window=10, min_periods=1).sum().shift(1).fillna(0)

bbb['wkts_last10'] = bbb.groupby(['match_id', 'innings'], group_keys=False).apply(rolling_wkts_last10)

# ============================================================
# 6. Partnership Context for Bowlers
# ============================================================
print("Computing partnership context...")

# Track partnership runs: reset on each wicket
# We'll compute it as: cumulative batter runs since last wicket fell
def partnership_runs(group):
    runs = group['bat_runs'].values
    wkt  = group['is_wicket'].astype(int).values
    part = np.zeros(len(runs))
    running = 0
    for i, (r, w) in enumerate(zip(runs, wkt)):
        part[i] = running
        running += r
        if w:
            running = 0
    return pd.Series(part, index=group.index)

bbb['partnership_bf'] = bbb.groupby(['match_id', 'innings'], group_keys=False).apply(partnership_runs)

# ============================================================
# 7. Define Pressure Flags
# ============================================================
print("Defining pressure situation flags...")

# ---- BATTER PRESSURE FLAGS ----
# 1. Run Chase Pressure: Innings 2, RRR > 9, balls remaining < 60
bbb['press_chase'] = (
    (bbb['innings'] == 2) &
    (bbb['rrr'] > 9) &
    (bbb['balls_remaining'] < 60)
)

# 2. Death Overs: Overs 16-20 in ANY innings
bbb['press_death'] = bbb['overid'].between(16, 20)

# 3. Collapse: team lost 3+ wickets in last 10 balls AND total wkts > 5
bbb['press_collapse'] = (
    (bbb['wkts_last10'] >= 3) &
    (bbb['cum_wkts_bf'] > 5)
)

# 4. High-pressure chase finish: Last 3 overs of chase, needs > 30 runs
bbb['press_chase_finish'] = (
    (bbb['innings'] == 2) &
    (bbb['overid'] >= 18) &
    (bbb['runs_needed_bf'] > 30)
)

# 5. Low-scoring match (pitch difficulty): inn1_total < 140
bbb['press_low_score'] = bbb['low_scoring'].fillna(False)

# 6. Powerplay in chase: Overs 1-6 when chasing
bbb['press_pp_chase'] = (
    (bbb['innings'] == 2) &
    (bbb['overid'].between(1, 6))
)

# 7. Match-defining moments: within 15 runs of target, <20 balls remain
bbb['press_match_def'] = (
    (bbb['innings'] == 2) &
    (bbb['runs_needed_bf'] <= 15) &
    (bbb['balls_remaining'] < 20) &
    (bbb['runs_needed_bf'] > 0)
)

# 8. Knockout match
bbb['press_knockout'] = bbb['is_knockout'].fillna(False)

# Combined batter pressure flag (any of the above)
bbb['is_batter_pressure'] = (
    bbb['press_chase'] |
    bbb['press_death'] |
    bbb['press_collapse'] |
    bbb['press_chase_finish'] |
    bbb['press_low_score'] |
    bbb['press_pp_chase'] |
    bbb['press_match_def'] |
    bbb['press_knockout']
)

# ---- BOWLER PRESSURE FLAGS ----
# 1. Death overs defence: Overs 16-20, team needs < 30 to win (inn2)
bbb['bpress_death_def'] = (
    (bbb['innings'] == 2) &
    (bbb['overid'].between(16, 20)) &
    (bbb['runs_needed_bf'] < 30)
)

# 2. Powerplay attack: Overs 1-6, defending total < 150
bbb['bpress_pp_attack'] = (
    (bbb['innings'] == 2) &
    (bbb['overid'].between(1, 6)) &
    (bbb['inn1_total'] < 150)
)

# 3. Partnership break: bowling when partnership > 40
bbb['bpress_partnership'] = bbb['partnership_bf'] > 40

# 4. Dot ball under chase: inn2, RRR > 9
bbb['bpress_chase_dot'] = (
    (bbb['innings'] == 2) &
    (bbb['rrr'] > 9)
)

# 5. Economy in slog (overs 16-20, inn2 defending)
bbb['bpress_slog_econ'] = (
    (bbb['innings'] == 1) & (bbb['overid'].between(16, 20))
) | (
    (bbb['innings'] == 2) & (bbb['overid'].between(16, 20))
)

# 6. Wickets in overs 15-20
bbb['bpress_wicket_overs'] = bbb['overid'].between(15, 20)

# 7. Knockout
bbb['bpress_knockout'] = bbb['is_knockout'].fillna(False)

# Combined bowler pressure flag
bbb['is_bowler_pressure'] = (
    bbb['bpress_death_def'] |
    bbb['bpress_pp_attack'] |
    bbb['bpress_partnership'] |
    bbb['bpress_chase_dot'] |
    bbb['bpress_slog_econ'] |
    bbb['bpress_wicket_overs'] |
    bbb['bpress_knockout']
)

# High-pressure chase defense: last 2 overs (19-20), needs < 20
bbb['bpress_hp_chase_def'] = (
    (bbb['innings'] == 2) &
    (bbb['overid'].between(19, 20)) &
    (bbb['runs_needed_bf'] < 20)
)

print(f"Batter pressure balls: {bbb['is_batter_pressure'].sum():,}")
print(f"Bowler pressure balls: {bbb['is_bowler_pressure'].sum():,}")

# ============================================================
# 8. Dismissal Flags
# ============================================================
# Batter dismissal: is_wicket=True and dismissed_player_id == striker_id
bbb['batter_dismissed'] = (
    bbb['is_wicket'] &
    (bbb['dismissed_player_id'] == bbb['striker_id'])
)

# Bowler dismissal: is_wicket=True, but NOT RunOut or Obstructing
run_out_types = ['RunOut', 'Run Out', 'Obstracting the field', 'Obstructing the field', 'Obstruction']
bbb['bowler_wicket'] = (
    bbb['is_wicket'] &
    ~bbb['dismissal_type'].isin(run_out_types)
)

# ============================================================
# 9. Match-Level Player Tracking
# ============================================================
print("\nTracking player matches...")

# Batter matches: distinct match_ids where player was striker or non-striker
batter_matches = (
    pd.concat([
        bbb[['match_id', 'striker_id', 'striker_name']].rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name'}),
        bbb[['match_id', 'non_striker_id', 'non_striker_name']].rename(columns={'non_striker_id': 'player_id', 'non_striker_name': 'player_name'})
    ])
    .drop_duplicates(['match_id', 'player_id'])
    .groupby(['player_id', 'player_name'])
    .agg(bat_matches=('match_id', 'nunique'))
    .reset_index()
)

# Bowler matches
bowler_matches = (
    bbb[['match_id', 'bowler_id', 'bowler_name']]
    .drop_duplicates(['match_id', 'bowler_id'])
    .groupby(['bowler_id', 'bowler_name'])
    .agg(bowl_matches=('match_id', 'nunique'))
    .reset_index()
    .rename(columns={'bowler_id': 'player_id', 'bowler_name': 'player_name'})
)

print(f"Unique batters: {len(batter_matches)}")
print(f"Unique bowlers: {len(bowler_matches)}")
print(f"Batters with 20+ matches: {(batter_matches['bat_matches'] >= MIN_MATCHES).sum()}")
print(f"Bowlers with 20+ matches: {(bowler_matches['bowl_matches'] >= MIN_MATCHES).sum()}")

# ============================================================
# 10. BATTING METRICS
# ============================================================
print("\nComputing batting metrics...")

# Work on striker deliveries only
bat = bbb.copy()
# Note: wides are not faced by batter for SR purposes, but can still dismiss (rarely)
# We only count legal deliveries as balls faced by batter

# --- BASELINE METRICS (all balls) ---
def batting_baseline(df, pid_col='striker_id', name_col='striker_name'):
    legal = df[df['is_legal']]
    grp_all = df.groupby([pid_col, name_col])
    grp_legal = legal.groupby([pid_col, name_col])

    agg = grp_all.agg(
        total_runs=('bat_runs', 'sum'),
        dismissals=('batter_dismissed', 'sum'),
    ).reset_index()

    legal_agg = grp_legal.agg(
        legal_balls=('bat_runs', 'count'),
    ).reset_index()

    base = agg.merge(legal_agg, on=[pid_col, name_col], how='left')
    base['baseline_avg'] = np.where(base['dismissals'] > 0, base['total_runs'] / base['dismissals'], base['total_runs'])
    base['baseline_sr']  = np.where(base['legal_balls'] > 0, base['total_runs'] / base['legal_balls'] * 100, 0)
    return base

baseline = batting_baseline(bat)
baseline = baseline.rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name'})

# --- PRESSURE BATTING ---
press_bat = bat[bat['is_batter_pressure']]
press_bat_legal = press_bat[press_bat['is_legal']]

def pressure_batting_agg(df, df_legal):
    grp = df.groupby(['striker_id', 'striker_name']).agg(
        press_runs=('bat_runs', 'sum'),
        press_dismissals=('batter_dismissed', 'sum'),
    ).reset_index()
    grp_l = df_legal.groupby(['striker_id', 'striker_name']).agg(
        press_legal_balls=('bat_runs', 'count'),
        press_dot_balls=('is_dot', 'sum'),
    ).reset_index()
    merged = grp.merge(grp_l, on=['striker_id', 'striker_name'], how='outer').fillna(0)
    merged['press_avg'] = np.where(merged['press_dismissals'] > 0,
                                    merged['press_runs'] / merged['press_dismissals'],
                                    merged['press_runs'])
    merged['press_sr']  = np.where(merged['press_legal_balls'] > 0,
                                    merged['press_runs'] / merged['press_legal_balls'] * 100, 0)
    merged['press_dot_pct'] = np.where(merged['press_legal_balls'] > 0,
                                        merged['press_dot_balls'] / merged['press_legal_balls'] * 100, 50)
    return merged.rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name'})

press_agg = pressure_batting_agg(press_bat, press_bat_legal)

# --- RUN CHASE SR (Inn2, RRR > 9) ---
chase_bat = bat[(bat['innings'] == 2) & (bat['rrr'] > 9) & bat['is_legal']]
chase_sr = chase_bat.groupby(['striker_id', 'striker_name']).agg(
    chase_runs=('bat_runs', 'sum'),
    chase_balls=('bat_runs', 'count'),
).reset_index()
chase_sr['chase_sr'] = np.where(chase_sr['chase_balls'] > 0,
                                 chase_sr['chase_runs'] / chase_sr['chase_balls'] * 100, 0)
chase_sr = chase_sr.rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name'})

# --- DEATH OVER SR (Overs 16-20) ---
death_bat = bat[bat['overid'].between(16, 20) & bat['is_legal']]
death_sr = death_bat.groupby(['striker_id', 'striker_name']).agg(
    death_runs=('bat_runs', 'sum'),
    death_balls=('bat_runs', 'count'),
    death_dismissals=('batter_dismissed', 'sum'),
).reset_index()
death_sr['death_sr']  = np.where(death_sr['death_balls'] > 0,
                                   death_sr['death_runs'] / death_sr['death_balls'] * 100, 0)
death_sr['death_avg'] = np.where(death_sr['death_dismissals'] > 0,
                                   death_sr['death_runs'] / death_sr['death_dismissals'],
                                   death_sr['death_runs'])
death_sr = death_sr.rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name'})

# --- STRIKE ROTATION % (balls where 1,2,3 scored) ---
bat_legal = bat[bat['is_legal']]
rot_grp = bat_legal.groupby(['striker_id', 'striker_name']).apply(
    lambda x: pd.Series({
        'rotation_runs': ((x['bat_runs'] >= 1) & (x['bat_runs'] <= 3)).sum(),
        'rotation_total': len(x)
    })
).reset_index()
rot_grp['strike_rotation_pct'] = np.where(rot_grp['rotation_total'] > 0,
                                            rot_grp['rotation_runs'] / rot_grp['rotation_total'] * 100, 0)
rot_grp = rot_grp.rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name'})

# --- COLLAPSE RESCUE RUNS (after 3+ wickets in 10 balls) ---
collapse_bat = bat[bat['press_collapse']]
collapse_grp = collapse_bat.groupby(['striker_id', 'striker_name']).agg(
    collapse_runs=('bat_runs', 'sum'),
    collapse_balls=('bat_runs', 'count'),
).reset_index()
collapse_grp = collapse_grp.rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name'})

# --- POWERPLAY CHASE CONTRIBUTION (Overs 1-6, Inn2) ---
pp_chase = bat[(bat['innings'] == 2) & bat['overid'].between(1, 6) & bat['is_legal']]
pp_chase_grp = pp_chase.groupby(['striker_id', 'striker_name']).agg(
    pp_chase_runs=('bat_runs', 'sum'),
    pp_chase_balls=('bat_runs', 'count'),
).reset_index()
pp_chase_grp['pp_chase_sr'] = np.where(pp_chase_grp['pp_chase_balls'] > 0,
                                         pp_chase_grp['pp_chase_runs'] / pp_chase_grp['pp_chase_balls'] * 100, 0)
pp_chase_grp = pp_chase_grp.rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name'})

# --- KNOCKOUT BATTING ---
ko_bat = bat[bat['is_knockout'] & bat['is_legal']]
ko_bat_grp = ko_bat.groupby(['striker_id', 'striker_name']).agg(
    ko_runs=('bat_runs', 'sum'),
    ko_balls=('bat_runs', 'count'),
    ko_dismissals=('batter_dismissed', 'sum'),
).reset_index()
ko_bat_grp['ko_avg'] = np.where(ko_bat_grp['ko_dismissals'] > 0,
                                  ko_bat_grp['ko_runs'] / ko_bat_grp['ko_dismissals'],
                                  ko_bat_grp['ko_runs'])
ko_bat_grp['ko_sr_bat'] = np.where(ko_bat_grp['ko_balls'] > 0,
                                     ko_bat_grp['ko_runs'] / ko_bat_grp['ko_balls'] * 100, 0)
ko_bat_grp = ko_bat_grp.rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name'})

# --- CONSISTENCY: Coefficient of Variation of innings scores ---
# Per innings (match+innings combo) sum of batter runs
innings_scores = (
    bat[bat['is_legal']]
    .groupby(['striker_id', 'striker_name', 'match_id', 'innings'])['bat_runs']
    .sum()
    .reset_index()
)
# CV = std/mean
consist = innings_scores.groupby(['striker_id', 'striker_name'])['bat_runs'].agg(['mean', 'std', 'count']).reset_index()
consist['cv'] = np.where(consist['mean'] > 0, consist['std'].fillna(0) / consist['mean'], 1)
consist = consist.rename(columns={'striker_id': 'player_id', 'striker_name': 'player_name',
                                   'count': 'innings_count'})

# ============================================================
# 11. MERGE ALL BATTING METRICS
# ============================================================
print("Merging batting metrics...")

bat_df = baseline.merge(batter_matches, on=['player_id', 'player_name'], how='left')
bat_df = bat_df.merge(press_agg, on=['player_id', 'player_name'], how='left')
bat_df = bat_df.merge(chase_sr[['player_id', 'player_name', 'chase_runs', 'chase_balls', 'chase_sr']], on=['player_id', 'player_name'], how='left')
bat_df = bat_df.merge(death_sr[['player_id', 'player_name', 'death_runs', 'death_balls', 'death_sr', 'death_avg']], on=['player_id', 'player_name'], how='left')
bat_df = bat_df.merge(rot_grp[['player_id', 'player_name', 'strike_rotation_pct']], on=['player_id', 'player_name'], how='left')
bat_df = bat_df.merge(collapse_grp[['player_id', 'player_name', 'collapse_runs', 'collapse_balls']], on=['player_id', 'player_name'], how='left')
bat_df = bat_df.merge(pp_chase_grp[['player_id', 'player_name', 'pp_chase_runs', 'pp_chase_balls', 'pp_chase_sr']], on=['player_id', 'player_name'], how='left')
bat_df = bat_df.merge(ko_bat_grp[['player_id', 'player_name', 'ko_runs', 'ko_balls', 'ko_avg', 'ko_sr_bat']], on=['player_id', 'player_name'], how='left')
bat_df = bat_df.merge(consist[['player_id', 'player_name', 'cv', 'innings_count']], on=['player_id', 'player_name'], how='left')

bat_df = bat_df.fillna(0)

# Apply eligibility filter
bat_elig = bat_df[bat_df['bat_matches'] >= MIN_MATCHES].copy()
print(f"Eligible batters: {len(bat_elig)}")

# Pressure Index for batting
bat_elig['PI_bat'] = np.where(
    (bat_elig['baseline_sr'] > 0) & (bat_elig['baseline_avg'] > 0),
    (bat_elig['press_sr'] / bat_elig['baseline_sr']) * (bat_elig['press_avg'] / bat_elig['baseline_avg']),
    0
)

# Chase SR vs baseline SR ratio
bat_elig['chase_sr_ratio'] = np.where(bat_elig['baseline_sr'] > 0, bat_elig['chase_sr'] / bat_elig['baseline_sr'], 0)
# Death SR vs baseline SR ratio
bat_elig['death_sr_ratio'] = np.where(bat_elig['baseline_sr'] > 0, bat_elig['death_sr'] / bat_elig['baseline_sr'], 0)

# ============================================================
# 12. BOWLING METRICS
# ============================================================
print("\nComputing bowling metrics...")

bowl = bbb.copy()

# Bowler runs conceded = runs - leg byes - byes (extras_2_runs)
bowl['bowl_runs'] = bowl['runs'] - bowl['extras_2_runs']
bowl['bowl_runs'] = bowl['bowl_runs'].clip(lower=0)

# Legal bowling deliveries (count wides and no-balls for economy but not SR)
# Economy uses all deliveries that count toward over (legal only for over count)
# Standard: wides/no-balls still count as runs but not balls (for bowler SR)
# Here: legal balls = not wide/noball for bowling SR
bowl['bowl_legal'] = bowl['is_legal'].astype(int)
bowl['bowl_all'] = 1  # count every delivery

# --- BASELINE BOWLING ---
def bowling_baseline(df):
    # Group by bowler
    grp = df.groupby(['bowler_id', 'bowler_name'])
    
    agg = grp.agg(
        total_bowl_runs=('bowl_runs', 'sum'),
        total_wkts=('bowler_wicket', 'sum'),
        total_legal=('bowl_legal', 'sum'),
        total_overs_balls=('bowl_all', 'count'),
    ).reset_index()
    
    agg['overs'] = agg['total_legal'] / 6
    agg['baseline_econ'] = np.where(agg['overs'] > 0, agg['total_bowl_runs'] / agg['overs'], 0)
    agg['baseline_avg']  = np.where(agg['total_wkts'] > 0, agg['total_bowl_runs'] / agg['total_wkts'], 999)
    agg['baseline_sr']   = np.where(agg['total_wkts'] > 0, agg['total_legal'] / agg['total_wkts'], 999)
    agg['baseline_wpo']  = np.where(agg['overs'] > 0, agg['total_wkts'] / agg['overs'], 0)
    return agg

bowl_base = bowling_baseline(bowl)
bowl_base = bowl_base.rename(columns={'bowler_id': 'player_id', 'bowler_name': 'player_name'})

# --- PRESSURE BOWLING ---
press_bowl = bowl[bowl['is_bowler_pressure']]

def pressure_bowl_agg(df):
    grp = df.groupby(['bowler_id', 'bowler_name']).agg(
        press_bowl_runs=('bowl_runs', 'sum'),
        press_wkts=('bowler_wicket', 'sum'),
        press_legal=('bowl_legal', 'sum'),
        press_dot=('is_dot', 'sum'),
    ).reset_index()
    grp['press_overs'] = grp['press_legal'] / 6
    grp['press_econ'] = np.where(grp['press_overs'] > 0,
                                   grp['press_bowl_runs'] / grp['press_overs'], 0)
    grp['press_wpo']  = np.where(grp['press_overs'] > 0,
                                   grp['press_wkts'] / grp['press_overs'], 0)
    grp['press_dot_pct'] = np.where(grp['press_legal'] > 0,
                                      grp['press_dot'] / grp['press_legal'] * 100, 0)
    return grp.rename(columns={'bowler_id': 'player_id', 'bowler_name': 'player_name'})

press_bowl_agg = pressure_bowl_agg(press_bowl)

# --- DEATH OVER BOWLING (Overs 16-20) ---
death_bowl = bowl[bowl['overid'].between(16, 20)]
death_bowl_grp = death_bowl.groupby(['bowler_id', 'bowler_name']).agg(
    death_bowl_runs=('bowl_runs', 'sum'),
    death_wkts=('bowler_wicket', 'sum'),
    death_legal=('bowl_legal', 'sum'),
).reset_index()
death_bowl_grp['death_overs'] = death_bowl_grp['death_legal'] / 6
death_bowl_grp['death_econ']  = np.where(death_bowl_grp['death_overs'] > 0,
                                           death_bowl_grp['death_bowl_runs'] / death_bowl_grp['death_overs'], 99)
death_bowl_grp['death_wpo']   = np.where(death_bowl_grp['death_overs'] > 0,
                                           death_bowl_grp['death_wkts'] / death_bowl_grp['death_overs'], 0)
death_bowl_grp = death_bowl_grp.rename(columns={'bowler_id': 'player_id', 'bowler_name': 'player_name'})

# --- POWERPLAY BOWLING (Overs 1-6) ---
pp_bowl = bowl[bowl['overid'].between(1, 6)]
pp_bowl_grp = pp_bowl.groupby(['bowler_id', 'bowler_name']).agg(
    pp_bowl_runs=('bowl_runs', 'sum'),
    pp_wkts=('bowler_wicket', 'sum'),
    pp_legal=('bowl_legal', 'sum'),
).reset_index()
pp_bowl_grp['pp_overs'] = pp_bowl_grp['pp_legal'] / 6
pp_bowl_grp['pp_econ']  = np.where(pp_bowl_grp['pp_overs'] > 0,
                                     pp_bowl_grp['pp_bowl_runs'] / pp_bowl_grp['pp_overs'], 99)
pp_bowl_grp['pp_wpo']   = np.where(pp_bowl_grp['pp_overs'] > 0,
                                     pp_bowl_grp['pp_wkts'] / pp_bowl_grp['pp_overs'], 0)
pp_bowl_grp = pp_bowl_grp.rename(columns={'bowler_id': 'player_id', 'bowler_name': 'player_name'})

# --- KNOCKOUT BOWLING ---
ko_bowl = bowl[bowl['is_knockout']]
ko_bowl_grp = ko_bowl.groupby(['bowler_id', 'bowler_name']).agg(
    ko_bowl_runs=('bowl_runs', 'sum'),
    ko_wkts=('bowler_wicket', 'sum'),
    ko_legal=('bowl_legal', 'sum'),
).reset_index()
ko_bowl_grp['ko_overs'] = ko_bowl_grp['ko_legal'] / 6
ko_bowl_grp['ko_econ']  = np.where(ko_bowl_grp['ko_overs'] > 0,
                                     ko_bowl_grp['ko_bowl_runs'] / ko_bowl_grp['ko_overs'], 99)
ko_bowl_grp['ko_wpo']   = np.where(ko_bowl_grp['ko_overs'] > 0,
                                     ko_bowl_grp['ko_wkts'] / ko_bowl_grp['ko_overs'], 0)
ko_bowl_grp = ko_bowl_grp.rename(columns={'bowler_id': 'player_id', 'bowler_name': 'player_name'})

# --- HIGH PRESSURE CHASE DEFENSE ---
hp_bowl = bowl[bowl['bpress_hp_chase_def']]
hp_bowl_grp = hp_bowl.groupby(['bowler_id', 'bowler_name']).agg(
    hp_bowl_runs=('bowl_runs', 'sum'),
    hp_wkts=('bowler_wicket', 'sum'),
    hp_legal=('bowl_legal', 'sum'),
).reset_index()
hp_bowl_grp['hp_overs'] = hp_bowl_grp['hp_legal'] / 6
hp_bowl_grp['hp_econ']  = np.where(hp_bowl_grp['hp_overs'] > 0,
                                     hp_bowl_grp['hp_bowl_runs'] / hp_bowl_grp['hp_overs'], 99)
hp_bowl_grp = hp_bowl_grp.rename(columns={'bowler_id': 'player_id', 'bowler_name': 'player_name'})

# --- PARTNERSHIP BREAKING ---
# Bowler took wicket when partnership was > 40
pb_bowl = bowl[(bowl['partnership_bf'] > 40) & bowl['bowler_wicket']]
pb_bowl_grp = pb_bowl.groupby(['bowler_id', 'bowler_name']).agg(
    partnership_breaks=('bowler_wicket', 'sum'),
).reset_index().rename(columns={'bowler_id': 'player_id', 'bowler_name': 'player_name'})

# --- BOWLING CONSISTENCY (CV of per-match economy) ---
match_econ = (
    bowl[bowl['bowl_legal'] > 0]
    .groupby(['bowler_id', 'bowler_name', 'match_id'])
    .apply(lambda x: pd.Series({
        'match_runs': x['bowl_runs'].sum(),
        'match_legal': x['bowl_legal'].sum()
    }))
    .reset_index()
)
match_econ['match_econ'] = np.where(match_econ['match_legal'] > 0,
                                      match_econ['match_runs'] / (match_econ['match_legal'] / 6), 0)
bowl_consist = match_econ.groupby(['bowler_id', 'bowler_name'])['match_econ'].agg(['mean', 'std', 'count']).reset_index()
bowl_consist['bowl_cv'] = np.where(bowl_consist['mean'] > 0,
                                    bowl_consist['std'].fillna(0) / bowl_consist['mean'], 1)
bowl_consist = bowl_consist.rename(columns={'bowler_id': 'player_id', 'bowler_name': 'player_name',
                                             'count': 'bowl_match_count'})

# ============================================================
# 13. MERGE ALL BOWLING METRICS
# ============================================================
print("Merging bowling metrics...")

bowl_df = bowl_base.merge(bowler_matches, on=['player_id', 'player_name'], how='left')
bowl_df = bowl_df.merge(press_bowl_agg, on=['player_id', 'player_name'], how='left')
bowl_df = bowl_df.merge(death_bowl_grp, on=['player_id', 'player_name'], how='left')
bowl_df = bowl_df.merge(pp_bowl_grp, on=['player_id', 'player_name'], how='left')
bowl_df = bowl_df.merge(ko_bowl_grp, on=['player_id', 'player_name'], how='left')
bowl_df = bowl_df.merge(hp_bowl_grp, on=['player_id', 'player_name'], how='left')
bowl_df = bowl_df.merge(pb_bowl_grp, on=['player_id', 'player_name'], how='left')
bowl_df = bowl_df.merge(bowl_consist[['player_id', 'player_name', 'bowl_cv', 'bowl_match_count']], on=['player_id', 'player_name'], how='left')

# Fill defaults
bowl_df['death_econ']  = bowl_df['death_econ'].fillna(99)
bowl_df['pp_econ']     = bowl_df['pp_econ'].fillna(99)
bowl_df['ko_econ']     = bowl_df['ko_econ'].fillna(99)
bowl_df['hp_econ']     = bowl_df['hp_econ'].fillna(99)
bowl_df['press_econ']  = bowl_df['press_econ'].fillna(99)
bowl_df = bowl_df.fillna(0)

# Apply eligibility
bowl_elig = bowl_df[bowl_df['bowl_matches'] >= MIN_MATCHES].copy()
print(f"Eligible bowlers: {len(bowl_elig)}")

# Pressure Bowling Index
bowl_elig['PI_bowl'] = np.where(
    (bowl_elig['baseline_econ'] > 0) & (bowl_elig['press_econ'] > 0) & (bowl_elig['baseline_wpo'] > 0),
    (bowl_elig['baseline_econ'] / bowl_elig['press_econ']) * (bowl_elig['press_wpo'] / bowl_elig['baseline_wpo']),
    0
)

# ============================================================
# 14. NORMALIZATION & COMPOSITE SCORING
# ============================================================
print("\nNormalizing metrics and computing composite scores...")

def minmax_norm(series, invert=False):
    """Min-max normalize a series. If invert=True, lower is better."""
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([0.5] * len(series), index=series.index)
    norm = (series - mn) / (mx - mn)
    return 1 - norm if invert else norm

# ---- BATTER COMPOSITE ----
# Components and weights:
# PI_bat: 25%
# chase_sr_ratio: 20%
# death_sr_ratio: 15%
# press_dot_pct (invert): 10%
# collapse_runs: 10%
# strike_rotation_pct: 5%
# pp_chase_sr (vs baseline): 5%
# ko_avg: 5%
# cv (invert): 5%

bat_elig['n_PI_bat']        = minmax_norm(bat_elig['PI_bat'])
bat_elig['n_chase_sr']      = minmax_norm(bat_elig['chase_sr_ratio'])
bat_elig['n_death_sr']      = minmax_norm(bat_elig['death_sr_ratio'])
bat_elig['n_dot_pct']       = minmax_norm(bat_elig['press_dot_pct'], invert=True)
bat_elig['n_collapse']      = minmax_norm(bat_elig['collapse_runs'])
bat_elig['n_rotation']      = minmax_norm(bat_elig['strike_rotation_pct'])
bat_elig['pp_chase_sr_ratio'] = np.where(bat_elig['baseline_sr'] > 0,
                                           bat_elig['pp_chase_sr'] / bat_elig['baseline_sr'], 0)
bat_elig['n_pp_chase']      = minmax_norm(bat_elig['pp_chase_sr_ratio'])
bat_elig['n_ko_bat']        = minmax_norm(bat_elig['ko_avg'])
bat_elig['n_consist_bat']   = minmax_norm(bat_elig['cv'], invert=True)

bat_elig['composite_score'] = (
    bat_elig['n_PI_bat']      * 25 +
    bat_elig['n_chase_sr']    * 20 +
    bat_elig['n_death_sr']    * 15 +
    bat_elig['n_dot_pct']     * 10 +
    bat_elig['n_collapse']    * 10 +
    bat_elig['n_rotation']    *  5 +
    bat_elig['n_pp_chase']    *  5 +
    bat_elig['n_ko_bat']      *  5 +
    bat_elig['n_consist_bat'] *  5
)

# ---- BOWLER COMPOSITE ----
# PI_bowl: 25%
# death_econ (lower=better): 20%
# death_wpo: 15%
# press_dot_pct (higher=better): 10%
# pp_econ (lower=better): 10%
# pp_wpo: 5%
# ko performance (econ lower=better): 10%
# bowl_cv (lower=better): 5%

bowl_elig['n_PI_bowl']     = minmax_norm(bowl_elig['PI_bowl'])
bowl_elig['n_death_econ']  = minmax_norm(bowl_elig['death_econ'].clip(0, 20), invert=True)
bowl_elig['n_death_wpo']   = minmax_norm(bowl_elig['death_wpo'])
bowl_elig['n_press_dot']   = minmax_norm(bowl_elig['press_dot_pct'])
bowl_elig['n_pp_econ']     = minmax_norm(bowl_elig['pp_econ'].clip(0, 20), invert=True)
bowl_elig['n_pp_wpo']      = minmax_norm(bowl_elig['pp_wpo'])
bowl_elig['n_ko_bowl']     = minmax_norm(bowl_elig['ko_econ'].clip(0, 20), invert=True)
bowl_elig['n_consist_bowl']= minmax_norm(bowl_elig['bowl_cv'], invert=True)

bowl_elig['composite_score'] = (
    bowl_elig['n_PI_bowl']      * 25 +
    bowl_elig['n_death_econ']   * 20 +
    bowl_elig['n_death_wpo']    * 15 +
    bowl_elig['n_press_dot']    * 10 +
    bowl_elig['n_pp_econ']      * 10 +
    bowl_elig['n_pp_wpo']       *  5 +
    bowl_elig['n_ko_bowl']      * 10 +
    bowl_elig['n_consist_bowl'] *  5
)

# ============================================================
# 15. FINAL RANKINGS
# ============================================================
print("\nComputing final rankings...")

top10_bat = bat_elig.sort_values('composite_score', ascending=False).head(10).reset_index(drop=True)
top10_bat.index = top10_bat.index + 1
top10_bat.index.name = 'rank'

top10_bowl = bowl_elig.sort_values('composite_score', ascending=False).head(10).reset_index(drop=True)
top10_bowl.index = top10_bowl.index + 1
top10_bowl.index.name = 'rank'

# ============================================================
# 16. SAVE RESULTS
# ============================================================
print("\nSaving results...")

# Key batter columns for top10
bat_key_cols = [
    'player_id', 'player_name', 'bat_matches', 'total_runs', 'dismissals', 'legal_balls',
    'baseline_avg', 'baseline_sr',
    'press_runs', 'press_dismissals', 'press_legal_balls', 'press_avg', 'press_sr', 'press_dot_pct',
    'PI_bat',
    'chase_sr', 'chase_sr_ratio',
    'death_sr', 'death_sr_ratio',
    'collapse_runs', 'strike_rotation_pct',
    'pp_chase_sr', 'ko_avg', 'cv',
    'n_PI_bat', 'n_chase_sr', 'n_death_sr', 'n_dot_pct', 'n_collapse',
    'n_rotation', 'n_pp_chase', 'n_ko_bat', 'n_consist_bat',
    'composite_score'
]

# Key bowler columns for top10
bowl_key_cols = [
    'player_id', 'player_name', 'bowl_matches', 'total_bowl_runs', 'total_wkts', 'total_legal',
    'overs', 'baseline_econ', 'baseline_avg', 'baseline_sr', 'baseline_wpo',
    'press_bowl_runs', 'press_wkts', 'press_econ', 'press_wpo', 'press_dot_pct',
    'PI_bowl',
    'death_econ', 'death_wpo',
    'pp_econ', 'pp_wpo',
    'ko_econ', 'ko_wpo',
    'bowl_cv', 'partnership_breaks',
    'n_PI_bowl', 'n_death_econ', 'n_death_wpo', 'n_press_dot',
    'n_pp_econ', 'n_pp_wpo', 'n_ko_bowl', 'n_consist_bowl',
    'composite_score'
]

top10_bat_save = top10_bat[[c for c in bat_key_cols if c in top10_bat.columns]]
top10_bowl_save = top10_bowl[[c for c in bowl_key_cols if c in top10_bowl.columns]]

top10_bat_save.to_csv(rf'{RESULTS_DIR}\top10_batters.csv')
top10_bowl_save.to_csv(rf'{RESULTS_DIR}\top10_bowlers.csv')

bat_elig[[c for c in bat_key_cols if c in bat_elig.columns]].sort_values('composite_score', ascending=False).to_csv(rf'{RESULTS_DIR}\batter_full_metrics.csv', index=False)
bowl_elig[[c for c in bowl_key_cols if c in bowl_elig.columns]].sort_values('composite_score', ascending=False).to_csv(rf'{RESULTS_DIR}\bowler_full_metrics.csv', index=False)

# ============================================================
# 17. SUMMARY REPORT
# ============================================================
print("\nGenerating summary report...")

summary_lines = []
summary_lines.append("=" * 80)
summary_lines.append("T20 CRICKET PRESSURE PERFORMANCE ANALYSIS — SUMMARY REPORT")
summary_lines.append("=" * 80)
summary_lines.append(f"\nTotal deliveries analyzed : {len(bbb):,}")
summary_lines.append(f"Total matches             : {len(matches):,}")
summary_lines.append(f"Eligibility threshold     : {MIN_MATCHES} matches")
summary_lines.append(f"Eligible batters          : {len(bat_elig)}")
summary_lines.append(f"Eligible bowlers          : {len(bowl_elig)}")
summary_lines.append(f"Batter pressure balls     : {bbb['is_batter_pressure'].sum():,}")
summary_lines.append(f"Bowler pressure balls     : {bbb['is_bowler_pressure'].sum():,}")

summary_lines.append("\n" + "=" * 80)
summary_lines.append("TOP 10 BATTERS — PRESSURE PERFORMANCE RANKING")
summary_lines.append("=" * 80)
summary_lines.append(f"{'Rank':<5} {'Player':<25} {'Matches':<8} {'Runs':<8} {'Avg':<8} {'SR':<8} "
                     f"{'Press SR':<10} {'Press Avg':<10} {'PI_bat':<8} {'Chase SR':<10} "
                     f"{'Death SR':<10} {'Collapse R':<12} {'Score':<8}")
summary_lines.append("-" * 130)
for rank, row in top10_bat_save.iterrows():
    summary_lines.append(
        f"{rank:<5} {row['player_name']:<25} {int(row['bat_matches']):<8} "
        f"{int(row['total_runs']):<8} {row['baseline_avg']:<8.1f} {row['baseline_sr']:<8.1f} "
        f"{row['press_sr']:<10.1f} {row['press_avg']:<10.1f} {row['PI_bat']:<8.3f} "
        f"{row['chase_sr']:<10.1f} {row['death_sr']:<10.1f} "
        f"{int(row.get('collapse_runs', 0)):<12} {row['composite_score']:<8.2f}"
    )

summary_lines.append("\n" + "=" * 80)
summary_lines.append("TOP 10 BOWLERS — PRESSURE PERFORMANCE RANKING")
summary_lines.append("=" * 80)
summary_lines.append(f"{'Rank':<5} {'Player':<25} {'Matches':<8} {'Wkts':<6} {'Econ':<7} "
                     f"{'Avg':<7} {'SR':<7} {'Press Econ':<12} {'Press WPO':<11} {'PI_bowl':<9} "
                     f"{'Death Econ':<12} {'Death WPO':<11} {'PP Econ':<9} {'Score':<8}")
summary_lines.append("-" * 140)
for rank, row in top10_bowl_save.iterrows():
    summary_lines.append(
        f"{rank:<5} {row['player_name']:<25} {int(row['bowl_matches']):<8} "
        f"{int(row['total_wkts']):<6} {row['baseline_econ']:<7.2f} "
        f"{row['baseline_avg']:<7.2f} {row['baseline_sr']:<7.2f} "
        f"{row['press_econ']:<12.2f} {row['press_wpo']:<11.3f} {row['PI_bowl']:<9.3f} "
        f"{row['death_econ']:<12.2f} {row['death_wpo']:<11.3f} {row['pp_econ']:<9.2f} "
        f"{row['composite_score']:<8.2f}"
    )

summary_lines.append("\n" + "=" * 80)
summary_lines.append("DETAILED TOP-10 BATTER PROFILES")
summary_lines.append("=" * 80)
for rank, row in top10_bat_save.iterrows():
    summary_lines.append(f"\n#{rank} {row['player_name']}")
    summary_lines.append(f"   Matches: {int(row['bat_matches'])} | Runs: {int(row['total_runs'])} | Avg: {row['baseline_avg']:.1f} | SR: {row['baseline_sr']:.1f}")
    summary_lines.append(f"   Pressure: Runs={int(row['press_runs'])} | Avg={row['press_avg']:.1f} | SR={row['press_sr']:.1f} | Dot%={row['press_dot_pct']:.1f}%")
    summary_lines.append(f"   Pressure Index (PI_bat): {row['PI_bat']:.3f}")
    summary_lines.append(f"   Chase SR: {row['chase_sr']:.1f} (ratio vs baseline: {row['chase_sr_ratio']:.2f})")
    summary_lines.append(f"   Death SR: {row['death_sr']:.1f} (ratio vs baseline: {row['death_sr_ratio']:.2f})")
    summary_lines.append(f"   Collapse Rescue Runs: {int(row.get('collapse_runs', 0))}")
    summary_lines.append(f"   Strike Rotation%: {row['strike_rotation_pct']:.1f}%")
    summary_lines.append(f"   PP Chase SR: {row['pp_chase_sr']:.1f} | KO Avg: {row['ko_avg']:.1f}")
    summary_lines.append(f"   Consistency CV: {row['cv']:.3f}")
    summary_lines.append(f"   >>> COMPOSITE SCORE: {row['composite_score']:.2f} / 100")

summary_lines.append("\n" + "=" * 80)
summary_lines.append("DETAILED TOP-10 BOWLER PROFILES")
summary_lines.append("=" * 80)
for rank, row in top10_bowl_save.iterrows():
    summary_lines.append(f"\n#{rank} {row['player_name']}")
    summary_lines.append(f"   Matches: {int(row['bowl_matches'])} | Wickets: {int(row['total_wkts'])} | Econ: {row['baseline_econ']:.2f} | Avg: {row['baseline_avg']:.2f} | SR: {row['baseline_sr']:.2f}")
    summary_lines.append(f"   Pressure: Econ={row['press_econ']:.2f} | WPO={row['press_wpo']:.3f} | Dot%={row['press_dot_pct']:.1f}%")
    summary_lines.append(f"   Pressure Index (PI_bowl): {row['PI_bowl']:.3f}")
    summary_lines.append(f"   Death Overs: Econ={row['death_econ']:.2f} | WPO={row['death_wpo']:.3f}")
    summary_lines.append(f"   Powerplay:   Econ={row['pp_econ']:.2f} | WPO={row['pp_wpo']:.3f}")
    summary_lines.append(f"   Knockout:    Econ={row['ko_econ']:.2f} | WPO={row['ko_wpo']:.3f}")
    summary_lines.append(f"   Partnership Breaks (40+ stand): {int(row.get('partnership_breaks', 0))}")
    summary_lines.append(f"   Consistency CV: {row['bowl_cv']:.3f}")
    summary_lines.append(f"   >>> COMPOSITE SCORE: {row['composite_score']:.2f} / 100")

summary_lines.append("\n" + "=" * 80)
summary_lines.append("COMPONENT SCORE BREAKDOWN — TOP 10 BATTERS")
summary_lines.append("=" * 80)
bat_comp_cols = {
    'n_PI_bat':      ('Pressure Index',   25),
    'n_chase_sr':    ('Chase SR Ratio',   20),
    'n_death_sr':    ('Death SR Ratio',   15),
    'n_dot_pct':     ('Dot% (inv)',        10),
    'n_collapse':    ('Collapse Rescue',  10),
    'n_rotation':    ('Strike Rotation',   5),
    'n_pp_chase':    ('PP Chase SR',       5),
    'n_ko_bat':      ('KO Avg',            5),
    'n_consist_bat': ('Consistency',       5),
}
hdr = f"{'Player':<25}"
for col, (lbl, wt) in bat_comp_cols.items():
    hdr += f" {lbl[:12]+'('+str(wt)+'%)':<17}"
hdr += f" {'TOTAL':<8}"
summary_lines.append(hdr)
summary_lines.append("-" * 190)
for rank, row in top10_bat_save.iterrows():
    line = f"{row['player_name']:<25}"
    for col, (lbl, wt) in bat_comp_cols.items():
        contrib = row.get(col, 0) * wt
        line += f" {contrib:<17.2f}"
    line += f" {row['composite_score']:<8.2f}"
    summary_lines.append(line)

summary_lines.append("\n" + "=" * 80)
summary_lines.append("COMPONENT SCORE BREAKDOWN — TOP 10 BOWLERS")
summary_lines.append("=" * 80)
bowl_comp_cols = {
    'n_PI_bowl':      ('PI_bowl',       25),
    'n_death_econ':   ('Death Econ',    20),
    'n_death_wpo':    ('Death WPO',     15),
    'n_press_dot':    ('Press Dot%',    10),
    'n_pp_econ':      ('PP Econ',       10),
    'n_pp_wpo':       ('PP WPO',         5),
    'n_ko_bowl':      ('KO Econ',       10),
    'n_consist_bowl': ('Consistency',    5),
}
hdr = f"{'Player':<25}"
for col, (lbl, wt) in bowl_comp_cols.items():
    hdr += f" {lbl[:12]+'('+str(wt)+'%)':<17}"
hdr += f" {'TOTAL':<8}"
summary_lines.append(hdr)
summary_lines.append("-" * 165)
for rank, row in top10_bowl_save.iterrows():
    line = f"{row['player_name']:<25}"
    for col, (lbl, wt) in bowl_comp_cols.items():
        contrib = row.get(col, 0) * wt
        line += f" {contrib:<17.2f}"
    line += f" {row['composite_score']:<8.2f}"
    summary_lines.append(line)

summary_lines.append("\n" + "=" * 80)
summary_lines.append("END OF REPORT")
summary_lines.append("=" * 80)

summary_text = "\n".join(summary_lines)
with open(rf'{RESULTS_DIR}\analysis_summary.txt', 'w') as f:
    f.write(summary_text)

print("\n" + summary_text)
print("\n\n--- TOP 10 BATTERS (CSV head) ---")
print(top10_bat_save.to_string())
print("\n\n--- TOP 10 BOWLERS (CSV head) ---")
print(top10_bowl_save.to_string())
print("\nAll files saved to:", RESULTS_DIR)
