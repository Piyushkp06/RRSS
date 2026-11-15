"""
T20 Pressure Performance Analysis v2
======================================
Major improvements over v1:
- Proper role classification using batting_order from playing_eleven
- Specialist batter filter eliminates tail-enders (Ish Sodhi etc.)
- Opponent strength weighting
- Refined pressure situation definitions
- Role-based bowling categories
- 6 role-specific ranked lists + 2 overall lists
"""

import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────
# 0. Setup
# ─────────────────────────────────────────
OUT_DIR = r'c:\Users\pkpan\rpcheck\results_v2'
os.makedirs(OUT_DIR, exist_ok=True)

print("Loading data...")
bbb = pd.read_csv(r'c:\Users\pkpan\rpcheck\ball_by_ball.csv')
matches = pd.read_csv(r'c:\Users\pkpan\rpcheck\matches.csv')
playing_eleven = pd.read_csv(r'c:\Users\pkpan\rpcheck\playing_eleven.csv')
ctpm = pd.read_csv(r'c:\Users\pkpan\rpcheck\competition_team_player_mapping.csv')
competitions = pd.read_csv(r'c:\Users\pkpan\rpcheck\competitions.csv')
teams = pd.read_csv(r'c:\Users\pkpan\rpcheck\teams.csv')

print(f"  Ball-by-ball: {len(bbb):,} rows")
print(f"  Matches: {len(matches):,}")
print(f"  Playing XI: {len(playing_eleven):,}")

# ─────────────────────────────────────────
# 0A. Opponent Strength Dictionaries
# ─────────────────────────────────────────
IPL_TEAM_STRENGTH = {
    1: 0.95,    # Chennai Super Kings
    2: 0.90,    # Mumbai Indians
    8: 0.88,    # Kolkata Knight Riders
    242: 0.85,  # Sunrisers Hyderabad
    3508: 0.82, # Gujarat Titans
    5: 0.80,    # Royal Challengers Bengaluru
    3: 0.78,    # Rajasthan Royals
    7: 0.75,    # Delhi Capitals
    3509: 0.73, # Lucknow Super Giants
    4: 0.70,    # Punjab Kings
}

ICC_TEAM_STRENGTH = {
    18: 1.00,   # India
    20: 0.95,   # Australia
    22: 0.92,   # England
    19: 0.90,   # South Africa
    25: 0.88,   # Pakistan
    17: 0.85,   # New Zealand
    27: 0.80,   # Sri Lanka
    28: 0.78,   # West Indies
    78: 0.75,   # Afghanistan
    21: 0.70,   # Bangladesh
    23: 0.60,   # Ireland
    72: 0.55,   # Zimbabwe
    24: 0.55,   # Netherlands
    26: 0.50,   # Scotland
    282: 0.50,  # Nepal
    272: 0.50,  # UAE
    283: 0.48,  # Hong Kong
    89: 0.45,   # Canada
    315: 0.45,  # USA
    311: 0.45,  # Singapore
    312: 0.45,  # Kuwait
    313: 0.48,  # Oman
}

# Identify IPL matches
ipl_comp_ids = set(competitions[competitions['match_format'] == 'T20']['comp_id'].tolist())
ipl_match_ids = set(matches[matches['comp_id'].isin(ipl_comp_ids)]['match_id'].tolist())

# ─────────────────────────────────────────
# 0B. Compute bat_runs & legal delivery flags
# ─────────────────────────────────────────
# extras_type: 'wide' = not faced by batter, not legal for bowler SR
#              'Overstep' (no-ball) = legal for batter SR, extras1_runs goes to team
#              'legbyes','byes' = batter doesn't score, but delivery is legal for both
#              NaN = normal delivery

# is_wide: wides are not legal deliveries (don't count for batter SR or bowler SR)
bbb['is_wide'] = bbb['extras_type'] == 'wide'

# is_legal: legal delivery = not a wide
bbb['is_legal'] = ~bbb['is_wide']

# bat_runs: runs attributed to the batter
# For wides: 0 (batter didn't face it)
# For no-balls (Overstep): runs - extras1_runs (the no-ball run) - extras_2_runs (leg byes on no-ball)
# For legbyes/byes: runs - extras_2_runs (wait - legbyes use extras1_runs not extras_2_runs based on data)
# From data inspection: legbyes show extras1_runs>0, extras_2_runs=0
# Normal: bat_runs = runs (since extras_2_runs=0 almost always)
# Conservative approach: bat_runs = runs - extras1_runs - extras_2_runs, clamp >=0

bbb['bat_runs'] = np.maximum(0, bbb['runs'] - bbb['extras1_runs'] - bbb['extras_2_runs'])

# Bowler wickets: exclude run-outs and obstruction
NON_BOWLER_DISMISSALS = {'RunOut', 'Obstracting the field', 'Obstructing the field', 'Handled the ball'}
bbb['is_bowler_wicket'] = (
    bbb['is_wicket'] &
    (~bbb['dismissal_type'].isin(NON_BOWLER_DISMISSALS))
)

# Runs conceded by bowler: runs - extras_2_runs (leg byes/byes don't count vs bowler)
# But extras1_runs on no-ball DO count vs bowler
bbb['bowler_runs'] = bbb['runs'] - bbb['extras_2_runs']

# Is dot ball (legal delivery with 0 bat_runs)
bbb['is_dot'] = bbb['is_legal'] & (bbb['bat_runs'] == 0) & (~bbb['is_wicket'])

# ─────────────────────────────────────────
# 0C. Merge match info into bbb
# ─────────────────────────────────────────
match_cols = ['match_id', 'comp_id', 'knock_out', 'revised_target', 'win_team_id']
bbb = bbb.merge(matches[match_cols], on='match_id', how='left')
bbb['is_ipl'] = bbb['match_id'].isin(ipl_match_ids)

# ─────────────────────────────────────────
# 0D. Opponent Strength per delivery
# ─────────────────────────────────────────
def get_opponent_strength_batter(row):
    """For a batter, opponent is the bowling team."""
    opp = int(row['bowling_team_id']) if not pd.isna(row['bowling_team_id']) else -1
    if row['is_ipl']:
        return IPL_TEAM_STRENGTH.get(opp, 0.70)
    else:
        return ICC_TEAM_STRENGTH.get(opp, 0.55)

def get_opponent_strength_bowler(row):
    """For a bowler, opponent is the batting team."""
    opp = int(row['batting_team_id']) if not pd.isna(row['batting_team_id']) else -1
    if row['is_ipl']:
        return IPL_TEAM_STRENGTH.get(opp, 0.70)
    else:
        return ICC_TEAM_STRENGTH.get(opp, 0.55)

# Vectorized version
def vectorized_strength(team_ids, is_ipl_flags, strength_dict_ipl, strength_dict_icc, default_ipl=0.70, default_icc=0.55):
    result = np.zeros(len(team_ids))
    for i, (tid, is_ipl) in enumerate(zip(team_ids, is_ipl_flags)):
        if pd.isna(tid):
            result[i] = default_icc
        elif is_ipl:
            result[i] = strength_dict_ipl.get(int(tid), default_ipl)
        else:
            result[i] = strength_dict_icc.get(int(tid), default_icc)
    return result

print("Computing opponent strengths...")
bbb['opp_strength_bat'] = vectorized_strength(
    bbb['bowling_team_id'], bbb['is_ipl'], IPL_TEAM_STRENGTH, ICC_TEAM_STRENGTH
)
bbb['opp_strength_bowl'] = vectorized_strength(
    bbb['batting_team_id'], bbb['is_ipl'], IPL_TEAM_STRENGTH, ICC_TEAM_STRENGTH
)

# ─────────────────────────────────────────
# 0E. Compute required_run_rate and balls_remaining for innings 2
# ─────────────────────────────────────────
print("Computing match targets and required run rates...")

# Get first innings totals per match
inn1 = bbb[bbb['innings'] == 1].groupby('match_id').agg(
    inn1_total_runs=('runs', 'sum')
).reset_index()

bbb = bbb.merge(inn1, on='match_id', how='left')

# Target for innings 2: use revised_target if available, else inn1_total_runs + 1
bbb['target'] = np.where(
    (~bbb['revised_target'].isna()) & (bbb['innings'] == 2),
    bbb['revised_target'],
    bbb['inn1_total_runs'] + 1
)

# Running score per match+innings up to and including this ball
# (cumulative runs before this ball for the batting team)
bbb = bbb.sort_values(['match_id', 'innings', 'innings_ball_num'])
bbb['cum_runs'] = bbb.groupby(['match_id', 'innings'])['runs'].cumsum()
bbb['runs_before'] = bbb['cum_runs'] - bbb['runs']

# Runs needed BEFORE this delivery
bbb['runs_needed'] = np.where(
    bbb['innings'] == 2,
    bbb['target'] - bbb['runs_before'],
    np.nan
)

# Total legal balls in innings (120 for full 20-over game)
# Max overs from matches - for simplicity use 120 total and subtract balls faced
# innings_ball_num = legal balls faced so far (doesn't include wides based on typical cricket data)
# Actually check: does innings_ball_num increment on wides?
# From structure it's the ball number including wides in this dataset.
# Use overid and over_ball_num to compute legal ball number
bbb['legal_ball_num'] = bbb.groupby(['match_id', 'innings'])['is_legal'].transform('cumsum')
bbb['balls_remaining'] = np.where(
    bbb['innings'] == 2,
    120 - bbb['legal_ball_num'],
    np.nan
)
bbb['balls_remaining'] = bbb['balls_remaining'].clip(lower=0)

# Required run rate (runs needed / overs remaining)
bbb['overs_remaining'] = bbb['balls_remaining'] / 6.0
bbb['rrr'] = np.where(
    bbb['overs_remaining'] > 0,
    bbb['runs_needed'] / bbb['overs_remaining'],
    np.nan
)

# ─────────────────────────────────────────
# 0F. Wickets fallen so far per match+innings (for collapse detection)
# ─────────────────────────────────────────
bbb['wickets_fallen'] = bbb.groupby(['match_id', 'innings'])['is_wicket'].transform('cumsum')
# Wickets fallen BEFORE this ball
bbb['wickets_before'] = bbb['wickets_fallen'] - bbb['is_wicket'].astype(int)

# ─────────────────────────────────────────
# 0G. Partnership tracking (for bowler partnership breaks)
# ─────────────────────────────────────────
print("Computing partnership tracking...")
bbb['partnership_runs'] = 0.0
match_innings_groups = bbb.groupby(['match_id', 'innings'], sort=False)

partnership_vals = []
for (mid, inn), grp in match_innings_groups:
    p_runs = 0
    vals = []
    for _, row in grp.iterrows():
        vals.append(p_runs)  # partnership BEFORE this ball
        if row['is_wicket']:
            p_runs = 0
        else:
            p_runs += row['bat_runs']
    partnership_vals.extend(vals)

bbb['partnership_before'] = partnership_vals

# ─────────────────────────────────────────
# 0H. 3-wicket-in-15-balls collapse flag
# ─────────────────────────────────────────
# For collapse: team has 5+ wickets fallen OR 3 wickets in last 15 balls
# Compute rolling wickets in last 15 legal balls per match+innings
print("Computing collapse flags...")

def rolling_wickets_15(group):
    """Count wickets in last 15 balls (rolling window) for each ball."""
    is_wkt = group['is_wicket'].astype(int).values
    n = len(is_wkt)
    result = np.zeros(n, dtype=int)
    for i in range(n):
        start = max(0, i - 15)
        result[i] = is_wkt[start:i].sum()
    return result

bbb['wickets_last_15'] = 0
for (mid, inn), grp in match_innings_groups:
    idx = grp.index
    bbb.loc[idx, 'wickets_last_15'] = rolling_wickets_15(grp)

bbb['is_collapse'] = (bbb['wickets_before'] >= 5) | (bbb['wickets_last_15'] >= 3)

# ─────────────────────────────────────────
# 0I. First innings totals for context (for high/low score match avg)
# ─────────────────────────────────────────
# Already have inn1_total_runs in bbb

# ─────────────────────────────────────────
# STEP 1: ROLE CLASSIFICATION
# ─────────────────────────────────────────
print("\n=== STEP 1: Role Classification ===")

# 1A. Batting role from playing_eleven
pe_played = playing_eleven[playing_eleven['is_played'] == True].copy()

batting_pos_stats = pe_played.groupby('player_id').agg(
    avg_batting_position=('batting_order', 'mean'),
    median_batting_position=('batting_order', 'median'),
    matches_in_xi=('match_id', 'nunique')
).reset_index()

# Innings batted from bbb (faced at least 1 ball)
innings_batted = bbb[bbb['is_legal']].groupby(['striker_id', 'match_id', 'innings']).size().reset_index()
innings_batted_count = innings_batted.groupby('striker_id').size().reset_index(name='total_innings_batted')
innings_batted_count.rename(columns={'striker_id': 'player_id'}, inplace=True)

batting_pos_stats = batting_pos_stats.merge(innings_batted_count, on='player_id', how='left')
batting_pos_stats['total_innings_batted'] = batting_pos_stats['total_innings_batted'].fillna(0)

# 1B. Bowler role
legal_bowled = bbb[bbb['is_legal']].copy()
bowler_phase = legal_bowled.groupby('bowler_id').apply(lambda g: pd.Series({
    'pp_balls': (g['overid'] <= 6).sum(),
    'middle_balls': ((g['overid'] >= 7) & (g['overid'] <= 15)).sum(),
    'death_balls': (g['overid'] >= 16).sum(),
    'total_balls_bowled': len(g),
})).reset_index()
bowler_phase.rename(columns={'bowler_id': 'player_id'}, inplace=True)

bowler_phase['pp_ratio'] = bowler_phase['pp_balls'] / bowler_phase['total_balls_bowled'].replace(0, np.nan)
bowler_phase['mid_ratio'] = bowler_phase['middle_balls'] / bowler_phase['total_balls_bowled'].replace(0, np.nan)
bowler_phase['death_ratio'] = bowler_phase['death_balls'] / bowler_phase['total_balls_bowled'].replace(0, np.nan)

def classify_bowler_role(row):
    if row['pp_ratio'] >= 0.40:
        return 'PP Specialist'
    elif row['death_ratio'] >= 0.35:
        return 'Death Specialist'
    elif row['mid_ratio'] >= 0.50:
        return 'Middle Overs Specialist'
    else:
        return 'All-Phase Bowler'

bowler_phase['bowler_role'] = bowler_phase.apply(classify_bowler_role, axis=1)

print("Bowler role distribution:")
print(bowler_phase['bowler_role'].value_counts())

# ─────────────────────────────────────────
# STEP 2: PRESSURE SITUATION FLAGS (Batting)
# ─────────────────────────────────────────
print("\n=== STEP 2: Pressure Situations ===")

# For batters - pressure on legal deliveries faced
bbb_legal = bbb[bbb['is_legal']].copy()

bbb_legal['press_run_chase'] = (
    (bbb_legal['innings'] == 2) &
    (bbb_legal['rrr'] > 9) &
    (bbb_legal['balls_remaining'] < 60)
)
bbb_legal['press_death'] = bbb_legal['overid'] >= 16
bbb_legal['press_collapse'] = bbb_legal['is_collapse']
bbb_legal['press_hpc_finish'] = (
    (bbb_legal['innings'] == 2) &
    (bbb_legal['balls_remaining'] <= 18) &
    (bbb_legal['runs_needed'] > 25)
)
bbb_legal['press_pp_chase'] = (
    (bbb_legal['innings'] == 2) &
    (bbb_legal['overid'] <= 6)
)
bbb_legal['press_match_defining'] = (
    (bbb_legal['innings'] == 2) &
    (bbb_legal['runs_needed'] <= 20) &
    (bbb_legal['runs_needed'] > 0) &
    (bbb_legal['balls_remaining'] <= 24)
)
bbb_legal['press_knockout'] = bbb_legal['knock_out'] == 1

bbb_legal['is_pressure_bat'] = (
    bbb_legal['press_run_chase'] |
    bbb_legal['press_death'] |
    bbb_legal['press_collapse'] |
    bbb_legal['press_hpc_finish'] |
    bbb_legal['press_pp_chase'] |
    bbb_legal['press_match_defining'] |
    bbb_legal['press_knockout']
)

# Pressure flags for bowlers (on legal deliveries)
bbb_legal['press_death_bowl'] = bbb_legal['overid'] >= 16
bbb_legal['press_pp_bowl'] = bbb_legal['overid'] <= 6
bbb_legal['press_chase_critical'] = (
    (bbb_legal['innings'] == 2) &
    (bbb_legal['overid'] >= 15)
)
bbb_legal['press_partnership_break'] = bbb_legal['partnership_before'] >= 30
bbb_legal['press_ko_bowl'] = bbb_legal['knock_out'] == 1

bbb_legal['is_pressure_bowl'] = (
    bbb_legal['press_death_bowl'] |
    bbb_legal['press_pp_bowl'] |
    bbb_legal['press_chase_critical'] |
    bbb_legal['press_partnership_break'] |
    bbb_legal['press_ko_bowl']
)

print(f"  Pressure batting balls: {bbb_legal['is_pressure_bat'].sum():,}")
print(f"  Pressure bowling balls: {bbb_legal['is_pressure_bowl'].sum():,}")

# ─────────────────────────────────────────
# STEP 3: BATTING METRICS
# ─────────────────────────────────────────
print("\n=== STEP 3: Batting Metrics ===")

# Get player names
player_names = ctpm[['player_id', 'player_name']].drop_duplicates('player_id')

def compute_batting_metrics(df_legal):
    """Compute all batting metrics for all strikers."""
    g = df_legal.groupby('striker_id')

    # Basic totals
    basic = g.agg(
        total_runs=('bat_runs', 'sum'),
        total_legal_balls=('is_legal', 'count'),  # already filtered to legal
        total_dismissals=('is_wicket', 'sum'),
        total_matches=('match_id', 'nunique'),
        is_four_sum=('is_four', 'sum'),
        is_six_sum=('is_six', 'sum'),
    ).reset_index()

    basic.rename(columns={'striker_id': 'player_id'}, inplace=True)
    inns_batted_df = df_legal.groupby(['striker_id', 'match_id', 'innings']).size().reset_index()
    inns_count_df = inns_batted_df.groupby('striker_id').size().reset_index(name='total_innings_batted')
    inns_count_df.rename(columns={'striker_id': 'player_id'}, inplace=True)
    basic = basic.merge(inns_count_df, on='player_id', how='left')
    basic['total_innings_batted'] = basic['total_innings_batted'].fillna(0)
    basic['baseline_avg'] = np.where(
        basic['total_dismissals'] > 0,
        basic['total_runs'] / basic['total_dismissals'],
        basic['total_runs']
    )
    basic['baseline_sr'] = (basic['total_runs'] / basic['total_legal_balls'].replace(0, np.nan)) * 100

    # Pressure metrics
    pressure = df_legal[df_legal['is_pressure_bat']].groupby('striker_id').agg(
        pressure_runs=('bat_runs', 'sum'),
        pressure_balls=('is_legal', 'count'),
        pressure_dismissals=('is_wicket', 'sum'),
        pressure_dots=('is_dot', 'sum'),
        pressure_fours=('is_four', 'sum'),
        pressure_sixes=('is_six', 'sum'),
        pressure_weighted_runs=('bat_runs', lambda x: (x * df_legal.loc[x.index, 'opp_strength_bat']).sum()),
    ).reset_index()
    pressure.rename(columns={'striker_id': 'player_id'}, inplace=True)

    # Chase SR (innings==2, rrr>9)
    chase_df = df_legal[(df_legal['innings'] == 2) & (df_legal['rrr'] > 9)]
    chase = chase_df.groupby('striker_id').agg(
        chase_runs=('bat_runs', 'sum'),
        chase_balls=('is_legal', 'count'),
    ).reset_index()
    chase.rename(columns={'striker_id': 'player_id'}, inplace=True)
    chase['chase_sr'] = (chase['chase_runs'] / chase['chase_balls'].replace(0, np.nan)) * 100

    # Death SR (overs 16-20)
    death_df = df_legal[df_legal['overid'] >= 16]
    death_bat = death_df.groupby('striker_id').agg(
        death_runs=('bat_runs', 'sum'),
        death_balls=('is_legal', 'count'),
    ).reset_index()
    death_bat.rename(columns={'striker_id': 'player_id'}, inplace=True)
    death_bat['death_sr'] = (death_bat['death_runs'] / death_bat['death_balls'].replace(0, np.nan)) * 100

    # PP Chase SR (innings==2, overid<=6)
    pp_chase_df = df_legal[(df_legal['innings'] == 2) & (df_legal['overid'] <= 6)]
    pp_chase = pp_chase_df.groupby('striker_id').agg(
        pp_chase_runs=('bat_runs', 'sum'),
        pp_chase_balls=('is_legal', 'count'),
    ).reset_index()
    pp_chase.rename(columns={'striker_id': 'player_id'}, inplace=True)
    pp_chase['pp_chase_sr'] = (pp_chase['pp_chase_runs'] / pp_chase['pp_chase_balls'].replace(0, np.nan)) * 100

    # Strike rotation: balls with bat_runs in [1,2,3] - compute separately then merge
    strike_rot = g.apply(
        lambda x: (x['bat_runs'].isin([1,2,3])).sum() / max(len(x), 1) * 100
    ).reset_index()
    strike_rot.columns = ['striker_id', 'strike_rotation_pct']
    strike_rot.rename(columns={'striker_id': 'player_id'}, inplace=True)

    # Collapse rescue runs (5+ wickets fallen)
    collapse_df = df_legal[df_legal['wickets_before'] >= 5]
    collapse = collapse_df.groupby('striker_id').agg(
        collapse_rescue_runs=('bat_runs', 'sum')
    ).reset_index()
    collapse.rename(columns={'striker_id': 'player_id'}, inplace=True)

    # KO match avg
    ko_df = df_legal[df_legal['knock_out'] == 1]
    ko_bat = ko_df.groupby('striker_id').agg(
        ko_runs=('bat_runs', 'sum'),
        ko_dismissals=('is_wicket', 'sum'),
        ko_balls=('is_legal', 'count'),
    ).reset_index()
    ko_bat.rename(columns={'striker_id': 'player_id'}, inplace=True)
    ko_bat['ko_avg'] = np.where(
        ko_bat['ko_dismissals'] > 0,
        ko_bat['ko_runs'] / ko_bat['ko_dismissals'],
        ko_bat['ko_runs']
    )

    # High score match avg (1st innings > 180)
    high_score_match_ids = set(df_legal[df_legal['inn1_total_runs'] > 180]['match_id'].unique())
    hs_df = df_legal[df_legal['match_id'].isin(high_score_match_ids)]
    hs_bat = hs_df.groupby('striker_id').agg(
        hs_runs=('bat_runs', 'sum'),
        hs_dismissals=('is_wicket', 'sum'),
    ).reset_index()
    hs_bat.rename(columns={'striker_id': 'player_id'}, inplace=True)
    hs_bat['high_score_avg'] = np.where(
        hs_bat['hs_dismissals'] > 0,
        hs_bat['hs_runs'] / hs_bat['hs_dismissals'],
        hs_bat['hs_runs']
    )

    # Low score match avg (1st innings < 150)
    low_score_match_ids = set(df_legal[df_legal['inn1_total_runs'] < 150]['match_id'].unique())
    ls_df = df_legal[df_legal['match_id'].isin(low_score_match_ids)]
    ls_bat = ls_df.groupby('striker_id').agg(
        ls_runs=('bat_runs', 'sum'),
        ls_dismissals=('is_wicket', 'sum'),
    ).reset_index()
    ls_bat.rename(columns={'striker_id': 'player_id'}, inplace=True)
    ls_bat['low_score_avg'] = np.where(
        ls_bat['ls_dismissals'] > 0,
        ls_bat['ls_runs'] / ls_bat['ls_dismissals'],
        ls_bat['ls_runs']
    )

    # Consistency: CV of innings scores
    innings_scores = df_legal.groupby(['striker_id', 'match_id', 'innings'])['bat_runs'].sum().reset_index()
    # Only innings > 5 runs
    innings_scores_filt = innings_scores[innings_scores['bat_runs'] > 5]
    consistency = innings_scores_filt.groupby('striker_id')['bat_runs'].agg(['std', 'mean']).reset_index()
    consistency.columns = ['player_id', 'score_std', 'score_mean']
    consistency['consistency_cv'] = consistency['score_std'] / consistency['score_mean'].replace(0, np.nan)

    # Merge all
    result = basic.copy()
    result = result.merge(strike_rot, on='player_id', how='left')
    result = result.merge(pressure, on='player_id', how='left')
    result = result.merge(chase, on='player_id', how='left')
    result = result.merge(death_bat, on='player_id', how='left')
    result = result.merge(pp_chase, on='player_id', how='left')
    result = result.merge(collapse, on='player_id', how='left')
    result = result.merge(ko_bat, on='player_id', how='left')
    result = result.merge(hs_bat, on='player_id', how='left')
    result = result.merge(ls_bat, on='player_id', how='left')
    result = result.merge(consistency, on='player_id', how='left')

    # Fill NaN
    for col in ['pressure_runs','pressure_balls','pressure_dismissals','pressure_dots',
                'pressure_fours','pressure_sixes','pressure_weighted_runs',
                'chase_runs','chase_balls','death_runs','death_balls',
                'pp_chase_runs','pp_chase_balls','collapse_rescue_runs',
                'ko_runs','ko_balls','ko_dismissals']:
        if col in result.columns:
            result[col] = result[col].fillna(0)

    result['pressure_avg'] = np.where(
        result['pressure_dismissals'] > 0,
        result['pressure_runs'] / result['pressure_dismissals'],
        result['pressure_runs']
    )
    result['pressure_sr'] = (result['pressure_runs'] / result['pressure_balls'].replace(0, np.nan)) * 100
    result['PI_bat'] = (
        (result['pressure_sr'] / result['baseline_sr'].replace(0, np.nan)) *
        (result['pressure_avg'] / result['baseline_avg'].replace(0, np.nan))
    )
    result['dot_pct_pressure'] = (result['pressure_dots'] / result['pressure_balls'].replace(0, np.nan)) * 100
    result['boundary_pct_pressure'] = (
        (result['pressure_fours'] + result['pressure_sixes']) /
        result['pressure_balls'].replace(0, np.nan) * 100
    )
    result['weighted_pressure_score'] = (
        result['pressure_weighted_runs'] / result['pressure_balls'].replace(0, np.nan)
    )

    return result

bat_metrics = compute_batting_metrics(bbb_legal)

# Merge batting position info
batting_pos_stats_merge = batting_pos_stats[['player_id','avg_batting_position','median_batting_position','matches_in_xi']]
bat_metrics = bat_metrics.merge(batting_pos_stats_merge, on='player_id', how='left')

# Merge player names
bat_metrics = bat_metrics.merge(player_names, on='player_id', how='left')

print(f"  Total players with batting data: {len(bat_metrics)}")

# ─────────────────────────────────────────
# STEP 4: APPLY BATTER FILTERS
# ─────────────────────────────────────────
print("\n=== STEP 4: Batter Filters ===")

# Classify batting roles
def classify_bat_role(avg_pos):
    if pd.isna(avg_pos) or avg_pos > 7.5:
        return 'Tail'
    elif avg_pos <= 3.5:
        return 'Top Order'
    elif avg_pos <= 5.5:
        return 'Middle Order'
    else:
        return 'Lower Order'

bat_metrics['bat_role'] = bat_metrics['avg_batting_position'].apply(classify_bat_role)

# Record filtered players for reporting
all_batters_pre = bat_metrics.copy()

# SPECIALIST BATTER FILTER
# Require matches_in_xi >= 20, not a tail-ender, total runs >= 200, baseline_sr >= 100
bat_eligible = bat_metrics[
    (bat_metrics['bat_role'] != 'Tail') &
    (bat_metrics['matches_in_xi'] >= 20) &
    (bat_metrics['total_runs'] >= 200) &
    (bat_metrics['baseline_sr'] >= 100)
].copy()

print(f"  After specialist filter (pos<=7.5, matches>=20, runs>=200, sr>=100): {len(bat_eligible)}")

# Players filtered out (who had meaningful balls)
filtered_out = all_batters_pre[
    ~all_batters_pre['player_id'].isin(bat_eligible['player_id']) &
    (all_batters_pre['total_legal_balls'] >= 100)
].copy()

print("  Batter role distribution:")
print(bat_eligible['bat_role'].value_counts())

# ─────────────────────────────────────────
# STEP 5: BATTING COMPOSITE SCORE
# ─────────────────────────────────────────
print("\n=== STEP 5: Batting Composite Score ===")

def normalize_col(series, invert=False):
    """Min-max normalize to 0-100; invert if lower=better."""
    s_min = series.min()
    s_max = series.max()
    if s_max == s_min:
        return pd.Series([50.0] * len(series), index=series.index)
    norm = (series - s_min) / (s_max - s_min) * 100
    if invert:
        norm = 100 - norm
    return norm

be = bat_eligible.copy()

# Ratios
be['chase_sr_ratio'] = be['chase_sr'] / be['baseline_sr'].replace(0, np.nan)
be['death_sr_ratio'] = be['death_sr'] / be['baseline_sr'].replace(0, np.nan)

# Fill NaN with median for each metric before normalizing
for col in ['PI_bat', 'chase_sr_ratio', 'death_sr_ratio', 'dot_pct_pressure',
            'collapse_rescue_runs', 'strike_rotation_pct', 'pp_chase_sr',
            'ko_avg', 'consistency_cv', 'weighted_pressure_score', 'boundary_pct_pressure']:
    if col in be.columns:
        be[col] = be[col].fillna(be[col].median())

be['PI_bat_norm'] = normalize_col(be['PI_bat'])
be['chase_sr_ratio_norm'] = normalize_col(be['chase_sr_ratio'])
be['death_sr_ratio_norm'] = normalize_col(be['death_sr_ratio'])
be['dot_pct_pressure_inv_norm'] = normalize_col(be['dot_pct_pressure'], invert=True)
be['collapse_rescue_norm'] = normalize_col(be['collapse_rescue_runs'])
be['strike_rotation_norm'] = normalize_col(be['strike_rotation_pct'])
be['pp_chase_sr_norm'] = normalize_col(be['pp_chase_sr'])
be['ko_avg_norm'] = normalize_col(be['ko_avg'])
be['consistency_inv_norm'] = normalize_col(be['consistency_cv'], invert=True)
be['weighted_opp_score_norm'] = normalize_col(be['weighted_pressure_score'])
be['boundary_pct_norm'] = normalize_col(be['boundary_pct_pressure'])

batter_weights = {
    'PI_bat_norm': 0.20,
    'chase_sr_ratio_norm': 0.15,
    'death_sr_ratio_norm': 0.12,
    'dot_pct_pressure_inv_norm': 0.08,
    'collapse_rescue_norm': 0.08,
    'strike_rotation_norm': 0.05,
    'pp_chase_sr_norm': 0.05,
    'ko_avg_norm': 0.07,
    'consistency_inv_norm': 0.05,
    'weighted_opp_score_norm': 0.10,
    'boundary_pct_norm': 0.05,
}

be['composite_score'] = sum(be[col] * w for col, w in batter_weights.items())

bat_eligible = be.copy()

# ─────────────────────────────────────────
# STEP 6: BOWLING METRICS
# ─────────────────────────────────────────
print("\n=== STEP 6: Bowling Metrics ===")

def compute_bowling_metrics(df_legal):
    """Compute all bowling metrics."""
    g = df_legal.groupby('bowler_id')

    basic = g.agg(
        total_legal_balls_b=('is_legal', 'count'),
        total_runs_conceded=('bowler_runs', 'sum'),
        total_wickets=('is_bowler_wicket', 'sum'),
        total_matches_b=('match_id', 'nunique'),
    ).reset_index()
    basic.rename(columns={'bowler_id': 'player_id'}, inplace=True)

    basic['baseline_econ'] = (basic['total_runs_conceded'] / basic['total_legal_balls_b'].replace(0, np.nan)) * 6
    basic['baseline_sr'] = basic['total_legal_balls_b'] / basic['total_wickets'].replace(0, np.nan)
    basic['baseline_avg'] = basic['total_runs_conceded'] / basic['total_wickets'].replace(0, np.nan)
    basic['baseline_wpo'] = (basic['total_wickets'] / basic['total_legal_balls_b'].replace(0, np.nan)) * 6

    # Pressure bowling
    pressure_b = df_legal[df_legal['is_pressure_bowl']].groupby('bowler_id').agg(
        pressure_runs_b=('bowler_runs', 'sum'),
        pressure_balls_b=('is_legal', 'count'),
        pressure_wickets_b=('is_bowler_wicket', 'sum'),
        pressure_dots_b=('is_dot', 'sum'),
        pressure_weighted_wkts=('is_bowler_wicket', lambda x: (x * df_legal.loc[x.index, 'opp_strength_bowl']).sum()),
    ).reset_index()
    pressure_b.rename(columns={'bowler_id': 'player_id'}, inplace=True)

    # Phase: Death (16-20)
    death_b_df = df_legal[df_legal['overid'] >= 16]
    death_b = death_b_df.groupby('bowler_id').agg(
        death_runs=('bowler_runs', 'sum'),
        death_balls=('is_legal', 'count'),
        death_wickets=('is_bowler_wicket', 'sum'),
        death_dots=('is_dot', 'sum'),
    ).reset_index()
    death_b.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    death_b['death_econ'] = (death_b['death_runs'] / death_b['death_balls'].replace(0, np.nan)) * 6
    death_b['death_wpo'] = (death_b['death_wickets'] / death_b['death_balls'].replace(0, np.nan)) * 6
    death_b['death_dot_pct'] = (death_b['death_dots'] / death_b['death_balls'].replace(0, np.nan)) * 100

    # Phase: PP (1-6)
    pp_b_df = df_legal[df_legal['overid'] <= 6]
    pp_b = pp_b_df.groupby('bowler_id').agg(
        pp_runs=('bowler_runs', 'sum'),
        pp_balls=('is_legal', 'count'),
        pp_wickets=('is_bowler_wicket', 'sum'),
        pp_dots=('is_dot', 'sum'),
    ).reset_index()
    pp_b.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    pp_b['pp_econ'] = (pp_b['pp_runs'] / pp_b['pp_balls'].replace(0, np.nan)) * 6
    pp_b['pp_wpo'] = (pp_b['pp_wickets'] / pp_b['pp_balls'].replace(0, np.nan)) * 6
    pp_b['pp_dot_pct'] = (pp_b['pp_dots'] / pp_b['pp_balls'].replace(0, np.nan)) * 100

    # Phase: Middle (7-15)
    mid_b_df = df_legal[(df_legal['overid'] >= 7) & (df_legal['overid'] <= 15)]
    mid_b = mid_b_df.groupby('bowler_id').agg(
        mid_runs=('bowler_runs', 'sum'),
        mid_balls=('is_legal', 'count'),
        mid_wickets=('is_bowler_wicket', 'sum'),
    ).reset_index()
    mid_b.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    mid_b['mid_econ'] = (mid_b['mid_runs'] / mid_b['mid_balls'].replace(0, np.nan)) * 6
    mid_b['mid_wpo'] = (mid_b['mid_wickets'] / mid_b['mid_balls'].replace(0, np.nan)) * 6

    # KO matches
    ko_b_df = df_legal[df_legal['knock_out'] == 1]
    ko_b = ko_b_df.groupby('bowler_id').agg(
        ko_runs_b=('bowler_runs', 'sum'),
        ko_balls_b=('is_legal', 'count'),
        ko_wickets=('is_bowler_wicket', 'sum'),
    ).reset_index()
    ko_b.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    ko_b['ko_econ'] = (ko_b['ko_runs_b'] / ko_b['ko_balls_b'].replace(0, np.nan)) * 6
    ko_b['ko_wpo'] = (ko_b['ko_wickets'] / ko_b['ko_balls_b'].replace(0, np.nan)) * 6

    # Partnership breaks: wickets taken when partnership >= 30
    pb_df = df_legal[(df_legal['partnership_before'] >= 30) & (df_legal['is_bowler_wicket'])]
    pb = pb_df.groupby('bowler_id')['is_bowler_wicket'].sum().reset_index()
    pb.columns = ['player_id', 'partnership_breaks']

    # Consistency: CV of match wickets
    match_wkts = df_legal.groupby(['bowler_id', 'match_id'])['is_bowler_wicket'].sum().reset_index()
    bowl_consistency = match_wkts.groupby('bowler_id')['is_bowler_wicket'].agg(['std','mean']).reset_index()
    bowl_consistency.columns = ['player_id', 'wkt_std', 'wkt_mean']
    bowl_consistency['bowl_consistency_cv'] = bowl_consistency['wkt_std'] / bowl_consistency['wkt_mean'].replace(0, np.nan)

    # Merge
    result = basic.copy()
    result = result.merge(pressure_b, on='player_id', how='left')
    result = result.merge(death_b, on='player_id', how='left')
    result = result.merge(pp_b, on='player_id', how='left')
    result = result.merge(mid_b, on='player_id', how='left')
    result = result.merge(ko_b, on='player_id', how='left')
    result = result.merge(pb, on='player_id', how='left')
    result = result.merge(bowl_consistency, on='player_id', how='left')

    # Fill NaN
    for col in ['pressure_runs_b','pressure_balls_b','pressure_wickets_b','pressure_dots_b',
                'pressure_weighted_wkts','death_runs','death_balls','death_wickets','death_dots',
                'pp_runs','pp_balls','pp_wickets','pp_dots',
                'mid_runs','mid_balls','mid_wickets',
                'ko_runs_b','ko_balls_b','ko_wickets','partnership_breaks']:
        if col in result.columns:
            result[col] = result[col].fillna(0)

    result['pressure_econ'] = (result['pressure_runs_b'] / result['pressure_balls_b'].replace(0, np.nan)) * 6
    result['pressure_wpo'] = (result['pressure_wickets_b'] / result['pressure_balls_b'].replace(0, np.nan)) * 6
    result['PI_bowl'] = np.where(
        (result['baseline_wpo'] > 0) & (result['pressure_econ'] > 0),
        (result['baseline_econ'] / result['pressure_econ']) * (result['pressure_wpo'] / result['baseline_wpo']),
        np.nan
    )
    result['pressure_dot_pct'] = (result['pressure_dots_b'] / result['pressure_balls_b'].replace(0, np.nan)) * 100
    result['weighted_pressure_wickets'] = (
        result['pressure_weighted_wkts'] / (result['pressure_balls_b'].replace(0, np.nan) / 6)
    )

    return result

bowl_metrics = compute_bowling_metrics(bbb_legal)

# Merge role info
bowl_metrics = bowl_metrics.merge(bowler_phase[['player_id','pp_balls','middle_balls','death_balls',
                                                 'total_balls_bowled','pp_ratio','mid_ratio','death_ratio',
                                                 'bowler_role']], 
                                   on='player_id', how='left')
bowl_metrics = bowl_metrics.merge(player_names, on='player_id', how='left')

print(f"  Total players with bowling data: {len(bowl_metrics)}")

# ─────────────────────────────────────────
# STEP 7: APPLY BOWLER FILTERS
# ─────────────────────────────────────────
print("\n=== STEP 7: Bowler Filters ===")

bowl_eligible = bowl_metrics[
    (bowl_metrics['total_wickets'] >= 15) &
    (bowl_metrics['total_legal_balls_b'] >= 400) &
    (bowl_metrics['total_matches_b'] >= 20)
].copy()

print(f"  After bowler filter (wkts>=15, balls>=400, matches>=20): {len(bowl_eligible)}")

# ─────────────────────────────────────────
# STEP 8: BOWLING COMPOSITE SCORE
# ─────────────────────────────────────────
print("\n=== STEP 8: Bowling Composite Score ===")

boe = bowl_eligible.copy()

for col in ['PI_bowl','death_econ','death_wpo','pressure_dot_pct','pp_econ','pp_wpo',
            'ko_econ','ko_wpo','partnership_breaks','weighted_pressure_wickets','bowl_consistency_cv']:
    if col in boe.columns:
        boe[col] = boe[col].fillna(boe[col].median())

boe['PI_bowl_norm'] = normalize_col(boe['PI_bowl'])
boe['death_econ_inv_norm'] = normalize_col(boe['death_econ'], invert=True)
boe['death_wpo_norm'] = normalize_col(boe['death_wpo'])
boe['pressure_dot_pct_norm'] = normalize_col(boe['pressure_dot_pct'])
boe['pp_econ_inv_norm'] = normalize_col(boe['pp_econ'], invert=True)
boe['pp_wpo_norm'] = normalize_col(boe['pp_wpo'])
boe['ko_econ_inv_norm'] = normalize_col(boe['ko_econ'], invert=True)
boe['ko_wpo_norm'] = normalize_col(boe['ko_wpo'])
boe['partnership_breaks_norm'] = normalize_col(boe['partnership_breaks'])
boe['weighted_opp_wickets_norm'] = normalize_col(boe['weighted_pressure_wickets'])
boe['consistency_inv_norm'] = normalize_col(boe['bowl_consistency_cv'], invert=True)

bowler_weights = {
    'PI_bowl_norm': 0.20,
    'death_econ_inv_norm': 0.15,
    'death_wpo_norm': 0.12,
    'pressure_dot_pct_norm': 0.08,
    'pp_econ_inv_norm': 0.08,
    'pp_wpo_norm': 0.05,
    'ko_econ_inv_norm': 0.08,
    'ko_wpo_norm': 0.05,
    'partnership_breaks_norm': 0.07,
    'weighted_opp_wickets_norm': 0.07,
    'consistency_inv_norm': 0.05,
}

boe['composite_score'] = sum(boe[col] * w for col, w in bowler_weights.items())

bowl_eligible = boe.copy()

# ─────────────────────────────────────────
# STEP 9: GENERATE RANKED LISTS
# ─────────────────────────────────────────
print("\n=== STEP 9: Rankings ===")

def top10_batters(df, role_filter=None, additional_filter=None, label=""):
    sub = df.copy()
    if role_filter:
        sub = sub[sub['bat_role'] == role_filter]
    if additional_filter is not None:
        sub = sub[additional_filter(sub)]
    top = sub.sort_values('composite_score', ascending=False).head(10)
    top['rank'] = range(1, len(top)+1)
    print(f"\n  {label} ({len(sub)} eligible):")
    for _, r in top.iterrows():
        print(f"    {int(r['rank'])}. {r['player_name']} | Pos:{r['avg_batting_position']:.1f} | "
              f"SR:{r['baseline_sr']:.1f} | Avg:{r['baseline_avg']:.1f} | "
              f"Runs:{int(r['total_runs'])} | Score:{r['composite_score']:.1f}")
    return top

def top10_bowlers(df, phase_filter=None, ratio_col=None, ratio_thresh=None, label=""):
    sub = df.copy()
    if phase_filter and ratio_col and ratio_thresh:
        sub = sub[sub[ratio_col] >= ratio_thresh]
    top = sub.sort_values('composite_score', ascending=False).head(10)
    top['rank'] = range(1, len(top)+1)
    print(f"\n  {label} ({len(sub)} eligible):")
    for _, r in top.iterrows():
        print(f"    {int(r['rank'])}. {r['player_name']} | Econ:{r['baseline_econ']:.2f} | "
              f"SR:{r['baseline_sr']:.1f} | Wkts:{int(r['total_wickets'])} | Score:{r['composite_score']:.1f}")
    return top

# BATTING RANKINGS
top_order = top10_batters(bat_eligible, role_filter='Top Order', label="Top Order Batters")
middle_order = top10_batters(bat_eligible, role_filter='Middle Order', label="Middle Order Batters")
lower_order = top10_batters(bat_eligible, role_filter='Lower Order',
                             additional_filter=lambda x: (x['baseline_sr'] >= 100) & (x['total_runs'] >= 150),
                             label="Lower Order / Finishers")
overall_batters = bat_eligible.sort_values('composite_score', ascending=False).head(10).copy()
overall_batters['rank'] = range(1, len(overall_batters)+1)

# BOWLING RANKINGS
pp_bowlers = top10_bowlers(bowl_eligible, ratio_col='pp_ratio', ratio_thresh=0.35, phase_filter=True, label="Powerplay Specialists")
mid_bowlers = top10_bowlers(bowl_eligible, ratio_col='mid_ratio', ratio_thresh=0.45, phase_filter=True, label="Middle Overs Specialists")
death_bowlers = top10_bowlers(bowl_eligible, ratio_col='death_ratio', ratio_thresh=0.35, phase_filter=True, label="Death Overs Specialists")
overall_bowlers = bowl_eligible.sort_values('composite_score', ascending=False).head(10).copy()
overall_bowlers['rank'] = range(1, len(overall_bowlers)+1)

# ─────────────────────────────────────────
# STEP 10: SAVE OUTPUTS
# ─────────────────────────────────────────
print("\n=== STEP 10: Saving outputs ===")

BATTER_COLS = ['rank','player_name','bat_role','avg_batting_position','total_matches','total_innings_batted',
               'total_runs','baseline_sr','baseline_avg','pressure_sr','pressure_avg',
               'chase_sr','death_sr','ko_avg','consistency_cv','weighted_pressure_score',
               'opp_strength_bat_avg','composite_score']

BOWLER_COLS = ['rank','player_name','bowler_role','total_matches_b','total_wickets','total_legal_balls_b',
               'baseline_econ','baseline_sr','baseline_avg','pressure_econ','pressure_wpo',
               'death_econ','death_wpo','pp_econ','pp_wpo','ko_econ','ko_wpo',
               'partnership_breaks','weighted_pressure_wickets','bowl_consistency_cv','composite_score']

def safe_cols(df, cols):
    available = [c for c in cols if c in df.columns]
    return df[available]

# Compute avg opp strength for display
avg_opp_bat = bbb_legal.groupby('striker_id')['opp_strength_bat'].mean().reset_index()
avg_opp_bat.columns = ['player_id','opp_strength_bat_avg']

for df in [top_order, middle_order, lower_order, overall_batters]:
    df_m = df.merge(avg_opp_bat, on='player_id', how='left')
    df.loc[:, 'opp_strength_bat_avg'] = df_m['opp_strength_bat_avg'].values

for name, df in [('top10_toporder_batters', top_order),
                  ('top10_middleorder_batters', middle_order),
                  ('top10_lowerorder_batters', lower_order),
                  ('top10_overall_batters', overall_batters)]:
    path = os.path.join(OUT_DIR, f'{name}.csv')
    safe_cols(df, BATTER_COLS).to_csv(path, index=False)
    print(f"  Saved {path}")

for name, df in [('top10_pp_bowlers', pp_bowlers),
                  ('top10_mid_bowlers', mid_bowlers),
                  ('top10_death_bowlers', death_bowlers),
                  ('top10_overall_bowlers', overall_bowlers)]:
    path = os.path.join(OUT_DIR, f'{name}.csv')
    safe_cols(df, BOWLER_COLS).to_csv(path, index=False)
    print(f"  Saved {path}")

# Full metrics
bat_full_path = os.path.join(OUT_DIR, 'full_batter_metrics.csv')
bowl_full_path = os.path.join(OUT_DIR, 'full_bowler_metrics.csv')
bat_eligible.to_csv(bat_full_path, index=False)
bowl_eligible.to_csv(bowl_full_path, index=False)
print(f"  Saved {bat_full_path}")
print(f"  Saved {bowl_full_path}")

# ─────────────────────────────────────────
# STEP 11: GENERATE SUMMARY
# ─────────────────────────────────────────
print("\n=== STEP 11: Generating Summary ===")

# Find filtered-out notable players
notable_filtered = all_batters_pre[
    ~all_batters_pre['player_id'].isin(bat_eligible['player_id']) &
    (all_batters_pre['total_legal_balls'] >= 150)
].copy()
notable_filtered = notable_filtered.sort_values('total_runs', ascending=False).head(20)

def format_top10_table(df, kind='batter'):
    lines = []
    if kind == 'batter':
        lines.append(f"{'Rk':<4} {'Player':<25} {'Role':<15} {'Mtchs':<6} {'Innings':<8} {'Runs':<6} {'Avg':<7} {'SR':<7} {'P-SR':<7} {'KO-Avg':<8} {'OppWt':<7} {'Score':<7}")
        lines.append("-" * 115)
        for _, r in df.iterrows():
            lines.append(
                f"{int(r.get('rank',0)):<4} {str(r.get('player_name','')):<25} "
                f"{str(r.get('bat_role','')):<15} {int(r.get('total_matches',0)):<6} "
                f"{int(r.get('total_innings_batted',0)):<8} {int(r.get('total_runs',0)):<6} "
                f"{r.get('baseline_avg',0):<7.1f} {r.get('baseline_sr',0):<7.1f} "
                f"{r.get('pressure_sr',0):<7.1f} {r.get('ko_avg',0):<8.1f} "
                f"{r.get('opp_strength_bat_avg',0):<7.3f} {r.get('composite_score',0):<7.1f}"
            )
    else:
        lines.append(f"{'Rk':<4} {'Player':<25} {'Role':<22} {'Mtchs':<6} {'Wkts':<6} {'Econ':<7} {'BaseSR':<8} {'P-Econ':<8} {'P-WPO':<7} {'KO-Econ':<9} {'PBrks':<7} {'Score':<7}")
        lines.append("-" * 125)
        for _, r in df.iterrows():
            lines.append(
                f"{int(r.get('rank',0)):<4} {str(r.get('player_name','')):<25} "
                f"{str(r.get('bowler_role','')):<22} {int(r.get('total_matches_b',0)):<6} "
                f"{int(r.get('total_wickets',0)):<6} {r.get('baseline_econ',0):<7.2f} "
                f"{r.get('baseline_sr',0):<8.1f} {r.get('pressure_econ',0):<8.2f} "
                f"{r.get('pressure_wpo',0):<7.2f} {r.get('ko_econ',0):<9.2f} "
                f"{int(r.get('partnership_breaks',0)):<7} {r.get('composite_score',0):<7.1f}"
            )
    return "\n".join(lines)

summary_lines = []
summary_lines.append("=" * 120)
summary_lines.append("T20 PRESSURE PERFORMANCE ANALYSIS v2 — FULL SUMMARY")
summary_lines.append("=" * 120)
summary_lines.append(f"Dataset: 200,999 deliveries | 883 matches | IPL 2022-2026 + T20I 2022-2026")
summary_lines.append(f"Eligible Batters (after filters): {len(bat_eligible)}")
summary_lines.append(f"Eligible Bowlers (after filters): {len(bowl_eligible)}")
summary_lines.append("")

# Role classification summary
summary_lines.append("─" * 60)
summary_lines.append("ROLE CLASSIFICATION SUMMARY")
summary_lines.append("─" * 60)
summary_lines.append("")
summary_lines.append("BATTING ROLES (eligible players):")
for role, cnt in bat_eligible['bat_role'].value_counts().items():
    summary_lines.append(f"  {role:<20}: {cnt}")
summary_lines.append("")
summary_lines.append("BOWLING ROLES (eligible players):")
for role, cnt in bowl_eligible['bowler_role'].value_counts().items():
    summary_lines.append(f"  {role:<25}: {cnt}")
summary_lines.append("")

# Filtered out section
summary_lines.append("─" * 60)
summary_lines.append("TOP 5 PLAYERS FILTERED OUT (from previous v1 rankings) WITH REASON:")
summary_lines.append("─" * 60)
# Try to find specific examples from filtered_out

notable_names_to_check = ['Ish Sodhi', 'Mitchell Starc', 'Jasprit Bumrah', 'Rashid Khan', 'Sunil Narine']
for name in notable_names_to_check:
    match = all_batters_pre[all_batters_pre['player_name'].str.contains(name.split()[0], case=False, na=False)]
    if len(match) > 0:
        r = match.iloc[0]
        pos_row = batting_pos_stats[batting_pos_stats['player_id'] == r['player_id']]
        avg_pos = pos_row['avg_batting_position'].values[0] if len(pos_row) > 0 else r.get('avg_batting_position', '?')
        reason_parts = []
        if not pd.isna(avg_pos) and avg_pos > 7.5:
            reason_parts.append(f"avg batting pos={avg_pos:.1f} (>7.5, tail-ender)")
        if r['total_runs'] < 200:
            reason_parts.append(f"runs={int(r['total_runs'])} (<200)")
        if r['baseline_sr'] < 100:
            reason_parts.append(f"SR={r['baseline_sr']:.1f} (<100)")
        if r['total_innings_batted'] < 20:
            reason_parts.append(f"innings={int(r['total_innings_batted'])} (<20)")
        reason = "; ".join(reason_parts) if reason_parts else "passed all filters (included in rankings)"
        summary_lines.append(f"  {name}: {reason}")

summary_lines.append("")
# Add a few more from notable_filtered
shown = set(notable_names_to_check)
count = 0
for _, r in notable_filtered.iterrows():
    nm = str(r.get('player_name',''))
    if nm not in shown and count < 5:
        avg_pos_v = r.get('avg_batting_position', np.nan)
        reason_parts = []
        if not pd.isna(avg_pos_v) and avg_pos_v > 7.5:
            reason_parts.append(f"avg batting pos={avg_pos_v:.1f} (>7.5, tail-ender)")
        if r['total_runs'] < 200:
            reason_parts.append(f"runs={int(r['total_runs'])} (<200)")
        if r['baseline_sr'] < 100:
            reason_parts.append(f"SR={r['baseline_sr']:.1f} (<100)")
        reason = "; ".join(reason_parts) if reason_parts else "insufficient matches/innings"
        summary_lines.append(f"  {nm}: {reason}")
        shown.add(nm)
        count += 1

summary_lines.append("")

# ── TOP 10 LISTS ──

sections = [
    ("1. TOP ORDER BATTERS (avg batting pos ≤ 3) — Pressure Performance", top_order, 'batter'),
    ("2. MIDDLE ORDER BATTERS (avg batting pos 4-6) — Pressure Performance", middle_order, 'batter'),
    ("3. LOWER ORDER / FINISHERS (avg batting pos 7+) — Pressure Performance", lower_order, 'batter'),
    ("4. OVERALL TOP 10 BATTERS — Cross-Role Pressure Champions", overall_batters, 'batter'),
    ("5. POWERPLAY BOWLERS (pp_balls/total ≥ 35%) — Pressure Performance", pp_bowlers, 'bowler'),
    ("6. MIDDLE OVERS BOWLERS (mid_balls/total ≥ 45%) — Pressure Performance", mid_bowlers, 'bowler'),
    ("7. DEATH OVERS BOWLERS (death_balls/total ≥ 35%) — Pressure Performance", death_bowlers, 'bowler'),
    ("8. OVERALL TOP 10 BOWLERS — Cross-Phase Pressure Champions", overall_bowlers, 'bowler'),
]

for section_title, df, kind in sections:
    summary_lines.append("=" * 120)
    summary_lines.append(section_title)
    summary_lines.append("=" * 120)
    summary_lines.append(format_top10_table(df, kind=kind))
    summary_lines.append("")
    # Brief reasons
    summary_lines.append("KEY REASONS:")
    for _, r in df.iterrows():
        name = str(r.get('player_name',''))
        rank = int(r.get('rank', 0))
        score = r.get('composite_score', 0)
        if kind == 'batter':
            pi = r.get('PI_bat', 0) if not pd.isna(r.get('PI_bat', np.nan)) else 0
            chase = r.get('chase_sr', 0) if not pd.isna(r.get('chase_sr', np.nan)) else 0
            death = r.get('death_sr', 0) if not pd.isna(r.get('death_sr', np.nan)) else 0
            baseline_sr = r.get('baseline_sr', 0)
            collapse = r.get('collapse_rescue_runs', 0) if not pd.isna(r.get('collapse_rescue_runs', np.nan)) else 0
            summary_lines.append(
                f"  #{rank} {name}: PI={pi:.2f}, Chase-SR={chase:.1f} vs Base-SR={baseline_sr:.1f}, "
                f"Death-SR={death:.1f}, Collapse-Rescue={int(collapse)} runs. "
                f"Composite={score:.1f}/100"
            )
        else:
            pi = r.get('PI_bowl', 0) if not pd.isna(r.get('PI_bowl', np.nan)) else 0
            d_econ = r.get('death_econ', 0) if not pd.isna(r.get('death_econ', np.nan)) else 0
            pp_econ_v = r.get('pp_econ', 0) if not pd.isna(r.get('pp_econ', np.nan)) else 0
            pb = int(r.get('partnership_breaks', 0))
            wkts = int(r.get('total_wickets', 0))
            summary_lines.append(
                f"  #{rank} {name}: PI={pi:.2f}, Death-Econ={d_econ:.2f}, PP-Econ={pp_econ_v:.2f}, "
                f"Partnership-Breaks={pb}, Total-Wkts={wkts}. Composite={score:.1f}/100"
            )
    summary_lines.append("")

# Methodology note
summary_lines.append("=" * 120)
summary_lines.append("METHODOLOGY NOTES")
summary_lines.append("=" * 120)
summary_lines.append("""
Pressure Situations (Batting):
  - Run Chase Pressure: Inn2, RRR>9, balls_remaining<60
  - Death Overs: Over 16-20 (any innings)
  - Collapse: 5+ wickets fallen OR 3 wickets in last 15 balls
  - High-pressure Chase Finish: Inn2, ≤18 balls remaining, >25 runs needed
  - Powerplay Chase: Inn2, over 1-6
  - Match-defining: Inn2, ≤20 runs needed, ≤24 balls left
  - Knock-out matches

Pressure Situations (Bowling):
  - Death over defence: over 16+
  - Powerplay attack: over 1-6
  - Chase-critical: Inn2, over 15+
  - Partnership break opportunity: 30+ run partnership
  - Knock-out matches

Batter Eligibility Filter:
  - avg_batting_position ≤ 6 (excludes tail-enders)
  - total_innings_batted ≥ 20
  - total_runs ≥ 300
  - baseline_SR ≥ 100

Bowler Eligibility Filter:
  - wickets ≥ 15
  - balls_bowled ≥ 400
  - matches ≥ 20

Opponent Strength Weighting:
  - IPL teams: CSK(0.95) → PBKS(0.70)
  - ICC teams: India(1.00) → Associates(0.45-0.55)

Composite Scoring: Weighted normalization (0-100) of 11 batting / 11 bowling metrics.
""")

summary_text = "\n".join(summary_lines)

summary_path = os.path.join(OUT_DIR, 'analysis_v2_summary.txt')
with open(summary_path, 'w', encoding='utf-8') as f:
    f.write(summary_text)

print(f"\n  Summary saved to: {summary_path}")
print("\n" + "=" * 60)
print("ANALYSIS COMPLETE!")
print("=" * 60)

# Print full summary
print("\n\n" + summary_text)
