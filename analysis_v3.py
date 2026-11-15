"""
T20 CRICKET PRESSURE PERFORMANCE ANALYSIS v3
SupeRR Selector Season 2
- Strict 40-Match Base Eligibility Criteria
- Role Classifications:
    Batting: Top Order (1-3), Middle Order (4-5), Lower Order / Finishers (6-7)
    Bowling: Powerplay Specialists, Middle Overs Specialists, Death Overs Specialists
- Deep Multi-Dimensional Cricket Metrics:
    * Run Chases (Innings 2, High RRR > 10, Chase Win Avg, Chase Not Out %)
    * Death Overs (Overs 16-20 SR, Dot%, Balls/Boundary, Boundary:Dot Ratio)
    * Powerplay Dynamics (Overs 1-6 SR, Dot%, Chase PP SR; Bowler PP Econ & WPO)
    * Dot Ball & Strike Rotation (Pressure Dot%, Dot Delta, Strike Rotation%, Non-Boundary SR)
    * Collapse Rescue (Runs & Avg when team 5+ down or 3 down in PP)
    * Playing Conditions / Pitch Adjustments (Relative SR/Econ vs Match Par, Tough Pitch vs Flat)
    * Opponent Strength Weighting (IPL Points Table + ICC T20I Team Rankings)
    * Match-Winning Performance (Man of the Match awards, Win Average / Win Economy)
    * Wicket Quality (Top-Order wickets 1-4 vs tail, Partnership Breaks 30+ & 50+)
    * Knockout Matches (Qualifiers, Eliminators, Finals)
"""

import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = r"c:\Users\pkpan\rpcheck"
OUT_DIR = os.path.join(BASE_DIR, "results_v3")
os.makedirs(OUT_DIR, exist_ok=True)

print("Loading data files...")
bbb = pd.read_csv(os.path.join(BASE_DIR, "ball_by_ball.csv"))
matches = pd.read_csv(os.path.join(BASE_DIR, "matches.csv"))
playing_eleven = pd.read_csv(os.path.join(BASE_DIR, "playing_eleven.csv"))
ctpm = pd.read_csv(os.path.join(BASE_DIR, "competition_team_player_mapping.csv"))
competitions = pd.read_csv(os.path.join(BASE_DIR, "competitions.csv"))
teams = pd.read_csv(os.path.join(BASE_DIR, "teams.csv"))

print(f"  Ball-by-ball: {len(bbb):,} rows")
print(f"  Matches: {len(matches):,}")
print(f"  Playing XI: {len(playing_eleven):,}")

# Opponent Strength Mapping
IPL_STRENGTH = {
    1: 0.95, 2: 0.90, 8: 0.88, 242: 0.85, 3508: 0.82,
    5: 0.80, 3: 0.78, 7: 0.75, 3509: 0.73, 4: 0.70
}
ICC_STRENGTH = {
    18: 1.00, 20: 0.95, 22: 0.92, 19: 0.90, 25: 0.88, 17: 0.85,
    27: 0.80, 28: 0.78, 78: 0.75, 21: 0.70, 23: 0.60, 72: 0.55,
    24: 0.55, 26: 0.50, 282: 0.50, 272: 0.50, 283: 0.48, 89: 0.45,
    315: 0.45, 311: 0.45, 312: 0.45, 313: 0.48
}

def get_opp_strength(team_id):
    if team_id in IPL_STRENGTH:
        return IPL_STRENGTH[team_id]
    if team_id in ICC_STRENGTH:
        return ICC_STRENGTH[team_id]
    return 0.55

# Match-level context
print("Calculating match-level pitch and victory context...")
match_meta = matches[['match_id', 'knock_out', 'win_team_id', 'revised_target', 'man_of_the_match']].copy()
match_meta['knock_out'] = match_meta['knock_out'].fillna(0).astype(int)

# Total runs and legal balls per match for match run rate / par score
bbb_legal_mask = ~bbb['extras_type'].isin(['wide'])
bbb_valid = bbb.copy()
bbb_valid['is_legal'] = bbb_legal_mask
bbb_valid['is_dot'] = (bbb_valid['runs'] == 0) & bbb_valid['is_legal']
bbb_valid['bat_runs'] = bbb_valid['runs'] - bbb_valid['extras1_runs'].fillna(0) - bbb_valid['extras_2_runs'].fillna(0)
bbb_valid['bat_runs'] = bbb_valid['bat_runs'].clip(lower=0)
bbb_valid['bowler_runs'] = bbb_valid['runs'] - bbb_valid['extras_2_runs'].fillna(0)
bbb_valid['bowler_runs'] = bbb_valid['bowler_runs'].clip(lower=0)

NON_BOWL_DISMISSALS = ['Run Out', 'Obstructing the field', 'Handled the ball']
bbb_valid['is_bowler_wicket'] = (
    bbb_valid['is_wicket'] &
    (~bbb_valid['dismissal_type'].isin(NON_BOWL_DISMISSALS)) &
    (bbb_valid['dismissed_player_id'] == bbb_valid['striker_id'])
)

# Merge match meta
bbb_valid = bbb_valid.merge(match_meta, on='match_id', how='left')

# Opponent strength per ball
bbb_valid['opp_strength_bat'] = bbb_valid['bowling_team_id'].apply(get_opp_strength)
bbb_valid['opp_strength_bowl'] = bbb_valid['batting_team_id'].apply(get_opp_strength)

# Match Par Score / Run Rate
match_stats = bbb_valid[bbb_valid['is_legal']].groupby('match_id').agg(
    m_runs=('runs', 'sum'),
    m_legal_balls=('is_legal', 'count')
).reset_index()
match_stats['match_rpo'] = (match_stats['m_runs'] / match_stats['m_legal_balls'].replace(0, np.nan)) * 6
match_stats['match_sr'] = (match_stats['m_runs'] / match_stats['m_legal_balls'].replace(0, np.nan)) * 100
bbb_valid = bbb_valid.merge(match_stats[['match_id', 'match_rpo', 'match_sr']], on='match_id', how='left')

# Innings 1 Total for Chases
inn1_runs = bbb_valid[bbb_valid['innings'] == 1].groupby('match_id')['runs'].sum().reset_index()
inn1_runs.rename(columns={'runs': 'inn1_total_runs'}, inplace=True)
bbb_valid = bbb_valid.merge(inn1_runs, on='match_id', how='left')

# Ball-by-ball cumulative score, wickets, and required run rate
bbb_valid.sort_values(['match_id', 'innings', 'overid', 'over_ball_num'], inplace=True)
bbb_valid['cum_runs'] = bbb_valid.groupby(['match_id', 'innings'])['runs'].cumsum()
bbb_valid['cum_legal_balls'] = bbb_valid.groupby(['match_id', 'innings'])['is_legal'].cumsum()
bbb_valid['cum_wickets'] = bbb_valid.groupby(['match_id', 'innings'])['is_wicket'].cumsum()
bbb_valid['wickets_before'] = bbb_valid['cum_wickets'] - bbb_valid['is_wicket'].astype(int)

# Target & RRR for Innings 2
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
print("Tracking partnerships and collapses...")
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

# Match Won flag per delivery
bbb_valid['is_match_won'] = bbb_valid['batting_team_id'] == bbb_valid['win_team_id']
bbb_valid['is_match_won_bowl'] = bbb_valid['bowling_team_id'] == bbb_valid['win_team_id']

# Collapse flag: 5+ wickets down OR (over <= 6 and 3+ wickets down)
bbb_valid['is_collapse'] = (bbb_valid['wickets_before'] >= 5) | ((bbb_valid['overid'] <= 6) & (bbb_valid['wickets_before'] >= 3))

# Pressure Situations
# Batting Pressure:
# 1. Chase pressure (Inn2 & RRR > 9.5 & balls_remaining < 60)
# 2. Extreme Chase pressure (Inn2 & RRR > 10.5)
# 3. Death overs (Overs 16-20)
# 4. Collapse rescue
# 5. Tough pitch (match RPO < 7.5)
# 6. Knockout matches
bbb_valid['is_pressure_bat'] = (
    ((bbb_valid['innings'] == 2) & (bbb_valid['rrr'] > 9.5) & (bbb_valid['balls_remaining'] < 60)) |
    ((bbb_valid['innings'] == 2) & (bbb_valid['rrr'] > 10.5)) |
    (bbb_valid['overid'] >= 16) |
    bbb_valid['is_collapse'] |
    (bbb_valid['knock_out'] == 1) |
    (bbb_valid['match_rpo'] < 7.5)
)

# Bowling Pressure:
# 1. Death overs (Overs 16-20)
# 2. Defending in Inn2 when RRR is high or close
# 3. Breaking stands >= 30
# 4. Powerplay defending < 155
# 5. Knockouts
bbb_valid['is_pressure_bowl'] = (
    (bbb_valid['overid'] >= 16) |
    ((bbb_valid['innings'] == 2) & (bbb_valid['overid'] >= 14) & (bbb_valid['runs_needed'] <= 50)) |
    (bbb_valid['partnership_before'] >= 30) |
    ((bbb_valid['overid'] <= 6) & (bbb_valid['innings'] == 2) & (bbb_valid['target'] <= 155)) |
    (bbb_valid['knock_out'] == 1)
)

print(f"  Pressure Batting Deliveries: {bbb_valid['is_pressure_bat'].sum():,}")
print(f"  Pressure Bowling Deliveries: {bbb_valid['is_pressure_bowl'].sum():,}")

# Filter to legal balls
bbb_legal = bbb_valid[bbb_valid['is_legal']].copy()

# ─────────────────────────────────────────────────────────────
# STEP 1: PLAYER MATCHES & ROLE CLASSIFICATION
# ─────────────────────────────────────────────────────────────
print("\n=== STEP 1: Matches & Role Classification (>=40 Matches Base Criteria) ===")

pe_played = playing_eleven[playing_eleven['is_played'] == True].copy()
player_names = ctpm[['player_id', 'player_name']].drop_duplicates('player_id')

player_match_stats = pe_played.groupby('player_id').agg(
    matches_in_xi=('match_id', 'nunique'),
    avg_batting_position=('batting_order', 'mean'),
    median_batting_position=('batting_order', 'median')
).reset_index()

# Role classification
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
    elif row['death_ratio'] >= 0.35:
        return 'Death Specialist'
    elif row['mid_ratio'] >= 0.45:
        return 'Middle Overs Specialist'
    else:
        return 'All-Phase Bowler'

bowler_phases['bowler_role'] = bowler_phases.apply(classify_bowler, axis=1)

# Man of the Match awards
motm_counts = matches[matches['man_of_the_match'] > 0]['man_of_the_match'].value_counts().reset_index()
motm_counts.columns = ['player_id', 'motm_count']

# ─────────────────────────────────────────────────────────────
# STEP 2: DEEP BATTING METRICS CALCULATION
# ─────────────────────────────────────────────────────────────
print("\n=== STEP 2: Computing Deep Batting Metrics ===")

def compute_detailed_batting(df_legal):
    # Overall baseline
    b_all = df_legal.groupby('striker_id').agg(
        total_runs=('bat_runs', 'sum'),
        total_balls=('is_legal', 'count'),
        total_dismissals=('is_wicket', 'sum'),
        total_dots=('is_dot', 'sum'),
        total_fours=('is_four', 'sum'),
        total_sixes=('is_six', 'sum'),
        strike_rot_balls=('bat_runs', lambda x: x.isin([1, 2, 3]).sum()),
        non_boundary_runs=('bat_runs', lambda x: x[x.isin([1, 2, 3])].sum()),
        weighted_runs=('bat_runs', lambda x: (x * df_legal.loc[x.index, 'opp_strength_bat']).sum())
    ).reset_index()
    b_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    b_all['baseline_avg'] = np.where(b_all['total_dismissals'] > 0, b_all['total_runs'] / b_all['total_dismissals'], b_all['total_runs'])
    b_all['baseline_sr'] = (b_all['total_runs'] / b_all['total_balls'].replace(0, np.nan)) * 100
    b_all['baseline_dot_pct'] = (b_all['total_dots'] / b_all['total_balls'].replace(0, np.nan)) * 100
    b_all['strike_rotation_pct'] = (b_all['strike_rot_balls'] / b_all['total_balls'].replace(0, np.nan)) * 100
    b_all['non_boundary_sr'] = (b_all['non_boundary_runs'] / b_all['total_balls'].replace(0, np.nan)) * 100
    b_all['opp_weighted_score'] = b_all['weighted_runs'] / b_all['total_balls'].replace(0, np.nan) * 100

    # Innings count
    inns_df = df_legal.groupby(['striker_id', 'match_id', 'innings']).size().reset_index()
    inns_count = inns_df.groupby('striker_id').size().reset_index(name='innings_batted')
    inns_count.rename(columns={'striker_id': 'player_id'}, inplace=True)
    b_all = b_all.merge(inns_count, on='player_id', how='left')

    # Pressure Overall
    p_df = df_legal[df_legal['is_pressure_bat']]
    b_press = p_df.groupby('striker_id').agg(
        pressure_runs=('bat_runs', 'sum'),
        pressure_balls=('is_legal', 'count'),
        pressure_dismissals=('is_wicket', 'sum'),
        pressure_dots=('is_dot', 'sum'),
        pressure_fours=('is_four', 'sum'),
        pressure_sixes=('is_six', 'sum'),
        pressure_weighted_runs=('bat_runs', lambda x: (x * df_legal.loc[x.index, 'opp_strength_bat']).sum())
    ).reset_index()
    b_press.rename(columns={'striker_id': 'player_id'}, inplace=True)
    b_press['pressure_avg'] = np.where(b_press['pressure_dismissals'] > 0, b_press['pressure_runs'] / b_press['pressure_dismissals'], b_press['pressure_runs'])
    b_press['pressure_sr'] = (b_press['pressure_runs'] / b_press['pressure_balls'].replace(0, np.nan)) * 100
    b_press['pressure_dot_pct'] = (b_press['pressure_dots'] / b_press['pressure_balls'].replace(0, np.nan)) * 100
    b_press['pressure_boundary_pct'] = ((b_press['pressure_fours'] + b_press['pressure_sixes']) / b_press['pressure_balls'].replace(0, np.nan)) * 100

    # Pressure Index PI_bat
    res = b_all.merge(b_press, on='player_id', how='left')
    res['PI_bat'] = np.where(
        (res['baseline_sr'] > 0) & (res['baseline_avg'] > 0),
        (res['pressure_sr'] / res['baseline_sr']) * (res['pressure_avg'] / res['baseline_avg']),
        1.0
    )
    res['dot_delta'] = res['pressure_dot_pct'] - res['baseline_dot_pct']

    # 1. Run Chases (Inn 2)
    chase_df = df_legal[df_legal['innings'] == 2]
    c_all = chase_df.groupby('striker_id').agg(
        chase_runs=('bat_runs', 'sum'),
        chase_balls=('is_legal', 'count'),
        chase_dismissals=('is_wicket', 'sum')
    ).reset_index()
    c_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    c_all['chase_avg'] = np.where(c_all['chase_dismissals'] > 0, c_all['chase_runs'] / c_all['chase_dismissals'], c_all['chase_runs'])
    c_all['chase_sr'] = (c_all['chase_runs'] / c_all['chase_balls'].replace(0, np.nan)) * 100
    res = res.merge(c_all, on='player_id', how='left')

    # High RRR Chases (RRR > 10.0)
    high_rrr_df = df_legal[(df_legal['innings'] == 2) & (df_legal['rrr'] > 10.0)]
    hr_all = high_rrr_df.groupby('striker_id').agg(
        hr_runs=('bat_runs', 'sum'),
        hr_balls=('is_legal', 'count')
    ).reset_index()
    hr_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    hr_all['high_rrr_sr'] = (hr_all['hr_runs'] / hr_all['hr_balls'].replace(0, np.nan)) * 100
    res = res.merge(hr_all[['player_id', 'high_rrr_sr']], on='player_id', how='left')

    # Chase Wins (Inn 2 & Match Won)
    chase_win_df = df_legal[(df_legal['innings'] == 2) & (df_legal['is_match_won'] == True)]
    cw_all = chase_win_df.groupby('striker_id').agg(
        cw_runs=('bat_runs', 'sum'),
        cw_dismissals=('is_wicket', 'sum')
    ).reset_index()
    cw_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    cw_all['chase_win_avg'] = np.where(cw_all['cw_dismissals'] > 0, cw_all['cw_runs'] / cw_all['cw_dismissals'], cw_all['cw_runs'])
    res = res.merge(cw_all[['player_id', 'chase_win_avg']], on='player_id', how='left')

    # 2. Death Overs (Overs 16-20)
    death_df = df_legal[df_legal['overid'] >= 16]
    d_all = death_df.groupby('striker_id').agg(
        death_runs=('bat_runs', 'sum'),
        death_balls=('is_legal', 'count'),
        death_dismissals=('is_wicket', 'sum'),
        death_dots=('is_dot', 'sum'),
        death_fours=('is_four', 'sum'),
        death_sixes=('is_six', 'sum')
    ).reset_index()
    d_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    d_all['death_sr'] = (d_all['death_runs'] / d_all['death_balls'].replace(0, np.nan)) * 100
    d_all['death_dot_pct'] = (d_all['death_dots'] / d_all['death_balls'].replace(0, np.nan)) * 100
    d_all['death_balls_per_boundary'] = d_all['death_balls'] / (d_all['death_fours'] + d_all['death_sixes']).replace(0, np.nan)
    d_all['death_boundary_dot_ratio'] = (d_all['death_fours'] + d_all['death_sixes']) / d_all['death_dots'].replace(0, np.nan)
    res = res.merge(d_all[['player_id', 'death_runs', 'death_balls', 'death_sr', 'death_dot_pct',
                           'death_balls_per_boundary', 'death_boundary_dot_ratio']], on='player_id', how='left')

    # 3. Powerplay (Overs 1-6)
    pp_df = df_legal[df_legal['overid'] <= 6]
    pp_all = pp_df.groupby('striker_id').agg(
        pp_runs=('bat_runs', 'sum'),
        pp_balls=('is_legal', 'count'),
        pp_dots=('is_dot', 'sum')
    ).reset_index()
    pp_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    pp_all['pp_sr'] = (pp_all['pp_runs'] / pp_all['pp_balls'].replace(0, np.nan)) * 100
    pp_all['pp_dot_pct'] = (pp_all['pp_dots'] / pp_all['pp_balls'].replace(0, np.nan)) * 100

    pp_chase_df = df_legal[(df_legal['overid'] <= 6) & (df_legal['innings'] == 2)]
    pp_c = pp_chase_df.groupby('striker_id').agg(
        pp_c_runs=('bat_runs', 'sum'),
        pp_c_balls=('is_legal', 'count')
    ).reset_index()
    pp_c.rename(columns={'striker_id': 'player_id'}, inplace=True)
    pp_c['pp_chase_sr'] = (pp_c['pp_c_runs'] / pp_c['pp_c_balls'].replace(0, np.nan)) * 100

    res = res.merge(pp_all[['player_id', 'pp_sr', 'pp_dot_pct']], on='player_id', how='left')
    res = res.merge(pp_c[['player_id', 'pp_chase_sr']], on='player_id', how='left')

    # 4. Collapse Situation
    col_df = df_legal[df_legal['is_collapse']]
    col_all = col_df.groupby('striker_id').agg(
        collapse_runs=('bat_runs', 'sum'),
        collapse_balls=('is_legal', 'count'),
        collapse_dismissals=('is_wicket', 'sum')
    ).reset_index()
    col_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    col_all['collapse_avg'] = np.where(col_all['collapse_dismissals'] > 0, col_all['collapse_runs'] / col_all['collapse_dismissals'], col_all['collapse_runs'])
    res = res.merge(col_all[['player_id', 'collapse_runs', 'collapse_avg']], on='player_id', how='left')

    # 5. Playing Conditions / Pitch Context
    # Relative SR = player SR vs match SR on that pitch
    df_legal['relative_ball_sr'] = (df_legal['bat_runs'] / df_legal['match_sr'].replace(0, np.nan)) * 100
    rel_sr = df_legal.groupby('striker_id')['relative_ball_sr'].mean().reset_index()
    rel_sr.columns = ['player_id', 'relative_sr_pct']
    res = res.merge(rel_sr, on='player_id', how='left')

    # Tough pitch (<7.5 RPO)
    tough_df = df_legal[df_legal['match_rpo'] < 7.5]
    t_all = tough_df.groupby('striker_id').agg(
        tough_runs=('bat_runs', 'sum'),
        tough_dismissals=('is_wicket', 'sum')
    ).reset_index()
    t_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    t_all['tough_pitch_avg'] = np.where(t_all['tough_dismissals'] > 0, t_all['tough_runs'] / t_all['tough_dismissals'], t_all['tough_runs'])
    res = res.merge(t_all[['player_id', 'tough_pitch_avg']], on='player_id', how='left')

    # 6. Matches Won vs Lost
    win_df = df_legal[df_legal['is_match_won'] == True]
    w_all = win_df.groupby('striker_id').agg(
        win_runs=('bat_runs', 'sum'),
        win_dismissals=('is_wicket', 'sum')
    ).reset_index()
    w_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    w_all['win_avg'] = np.where(w_all['win_dismissals'] > 0, w_all['win_runs'] / w_all['win_dismissals'], w_all['win_runs'])
    res = res.merge(w_all[['player_id', 'win_avg']], on='player_id', how='left')
    res['win_avg_ratio'] = res['win_avg'] / res['baseline_avg'].replace(0, np.nan)

    # 7. Knockout Matches
    ko_df = df_legal[df_legal['knock_out'] == 1]
    k_all = ko_df.groupby('striker_id').agg(
        ko_runs=('bat_runs', 'sum'),
        ko_dismissals=('is_wicket', 'sum'),
        ko_balls=('is_legal', 'count')
    ).reset_index()
    k_all.rename(columns={'striker_id': 'player_id'}, inplace=True)
    k_all['ko_avg'] = np.where(k_all['ko_dismissals'] > 0, k_all['ko_runs'] / k_all['ko_dismissals'], k_all['ko_runs'])
    k_all['ko_sr'] = (k_all['ko_runs'] / k_all['ko_balls'].replace(0, np.nan)) * 100
    res = res.merge(k_all[['player_id', 'ko_avg', 'ko_sr']], on='player_id', how='left')

    # Consistency CV
    inns_scores = df_legal.groupby(['striker_id', 'match_id', 'innings'])['bat_runs'].sum().reset_index()
    inns_scores_sig = inns_scores[inns_scores['bat_runs'] > 5]
    cv_df = inns_scores_sig.groupby('striker_id')['bat_runs'].agg(['std', 'mean']).reset_index()
    cv_df['consistency_cv'] = cv_df['std'] / cv_df['mean'].replace(0, np.nan)
    cv_df.rename(columns={'striker_id': 'player_id'}, inplace=True)
    res = res.merge(cv_df[['player_id', 'consistency_cv']], on='player_id', how='left')

    return res

bat_raw = compute_detailed_batting(bbb_legal)
bat_raw = bat_raw.merge(player_match_stats[['player_id', 'matches_in_xi', 'avg_batting_position', 'bat_role']], on='player_id', how='left')
bat_raw = bat_raw.merge(motm_counts, on='player_id', how='left')
bat_raw['motm_count'] = bat_raw['motm_count'].fillna(0)
bat_raw['motm_per_match'] = bat_raw['motm_count'] / bat_raw['matches_in_xi'].replace(0, np.nan)
bat_raw = bat_raw.merge(player_names, on='player_id', how='left')

# ─────────────────────────────────────────────────────────────
# STEP 3: DEEP BOWLING METRICS CALCULATION
# ─────────────────────────────────────────────────────────────
print("\n=== STEP 3: Computing Deep Bowling Metrics ===")

def compute_detailed_bowling(df_legal):
    # Overall baseline
    b_all = df_legal.groupby('bowler_id').agg(
        total_runs_b=('bowler_runs', 'sum'),
        total_balls_b=('is_legal', 'count'),
        total_wickets=('is_bowler_wicket', 'sum'),
        total_dots_b=('is_dot', 'sum'),
        total_fours_conceded=('is_four', 'sum'),
        total_sixes_conceded=('is_six', 'sum'),
        top_order_wickets=('is_bowler_wicket', lambda x: (x & (df_legal.loc[x.index, 'batting_order'] <= 4)).sum()),
        weighted_wickets=('is_bowler_wicket', lambda x: (x * df_legal.loc[x.index, 'opp_strength_bowl']).sum())
    ).reset_index()
    b_all.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    b_all['baseline_econ'] = (b_all['total_runs_b'] / b_all['total_balls_b'].replace(0, np.nan)) * 6
    b_all['baseline_sr'] = b_all['total_balls_b'] / b_all['total_wickets'].replace(0, np.nan)
    b_all['baseline_avg'] = b_all['total_runs_b'] / b_all['total_wickets'].replace(0, np.nan)
    b_all['baseline_dot_pct'] = (b_all['total_dots_b'] / b_all['total_balls_b'].replace(0, np.nan)) * 100
    b_all['top_order_wkt_pct'] = (b_all['top_order_wickets'] / b_all['total_wickets'].replace(0, np.nan)) * 100
    b_all['opp_weighted_wpo'] = (b_all['weighted_wickets'] / (b_all['total_balls_b'].replace(0, np.nan) / 6))

    # Pressure Overall
    p_df = df_legal[df_legal['is_pressure_bowl']]
    b_press = p_df.groupby('bowler_id').agg(
        pressure_runs_b=('bowler_runs', 'sum'),
        pressure_balls_b=('is_legal', 'count'),
        pressure_wickets_b=('is_bowler_wicket', 'sum'),
        pressure_dots_b=('is_dot', 'sum')
    ).reset_index()
    b_press.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    b_press['pressure_econ'] = (b_press['pressure_runs_b'] / b_press['pressure_balls_b'].replace(0, np.nan)) * 6
    b_press['pressure_wpo'] = (b_press['pressure_wickets_b'] / (b_press['pressure_balls_b'].replace(0, np.nan) / 6))
    b_press['pressure_dot_pct'] = (b_press['pressure_dots_b'] / b_press['pressure_balls_b'].replace(0, np.nan)) * 100

    res = b_all.merge(b_press, on='player_id', how='left')
    res['baseline_wpo'] = res['total_wickets'] / (res['total_balls_b'].replace(0, np.nan) / 6)
    res['PI_bowl'] = np.where(
        (res['pressure_econ'] > 0) & (res['baseline_wpo'] > 0),
        (res['baseline_econ'] / res['pressure_econ']) * (res['pressure_wpo'] / res['baseline_wpo']),
        1.0
    )

    # 1. Death Overs (Overs 16-20)
    death_df = df_legal[df_legal['overid'] >= 16]
    d_all = death_df.groupby('bowler_id').agg(
        death_runs_b=('bowler_runs', 'sum'),
        death_balls_b=('is_legal', 'count'),
        death_wickets_b=('is_bowler_wicket', 'sum'),
        death_dots_b=('is_dot', 'sum'),
        death_fours_c=('is_four', 'sum'),
        death_sixes_c=('is_six', 'sum')
    ).reset_index()
    d_all.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    d_all['death_econ'] = (d_all['death_runs_b'] / d_all['death_balls_b'].replace(0, np.nan)) * 6
    d_all['death_wpo'] = (d_all['death_wickets_b'] / (d_all['death_balls_b'].replace(0, np.nan) / 6))
    d_all['death_dot_pct'] = (d_all['death_dots_b'] / d_all['death_balls_b'].replace(0, np.nan)) * 100
    d_all['death_boundary_conceded_pct'] = ((d_all['death_fours_c'] + d_all['death_sixes_c']) / d_all['death_balls_b'].replace(0, np.nan)) * 100
    res = res.merge(d_all[['player_id', 'death_runs_b', 'death_balls_b', 'death_wickets_b',
                           'death_econ', 'death_wpo', 'death_dot_pct', 'death_boundary_conceded_pct']], on='player_id', how='left')

    # Extreme Death Overs (19-20)
    ext_death_df = df_legal[df_legal['overid'] >= 19]
    ed_all = ext_death_df.groupby('bowler_id').agg(
        ed_runs=('bowler_runs', 'sum'),
        ed_balls=('is_legal', 'count')
    ).reset_index()
    ed_all.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    ed_all['extreme_death_econ'] = (ed_all['ed_runs'] / ed_all['ed_balls'].replace(0, np.nan)) * 6
    res = res.merge(ed_all[['player_id', 'extreme_death_econ']], on='player_id', how='left')

    # 2. Powerplay Overs (1-6)
    pp_df = df_legal[df_legal['overid'] <= 6]
    pp_all = pp_df.groupby('bowler_id').agg(
        pp_runs_b=('bowler_runs', 'sum'),
        pp_balls_b=('is_legal', 'count'),
        pp_wickets_b=('is_bowler_wicket', 'sum'),
        pp_dots_b=('is_dot', 'sum')
    ).reset_index()
    pp_all.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    pp_all['pp_econ'] = (pp_all['pp_runs_b'] / pp_all['pp_balls_b'].replace(0, np.nan)) * 6
    pp_all['pp_wpo'] = (pp_all['pp_wickets_b'] / (pp_all['pp_balls_b'].replace(0, np.nan) / 6))
    pp_all['pp_dot_pct'] = (pp_all['pp_dots_b'] / pp_all['pp_balls_b'].replace(0, np.nan)) * 100
    res = res.merge(pp_all[['player_id', 'pp_econ', 'pp_wpo', 'pp_dot_pct']], on='player_id', how='left')

    # 3. Middle Overs (7-15)
    mid_df = df_legal[(df_legal['overid'] >= 7) & (df_legal['overid'] <= 15)]
    m_all = mid_df.groupby('bowler_id').agg(
        mid_runs_b=('bowler_runs', 'sum'),
        mid_balls_b=('is_legal', 'count'),
        mid_wickets_b=('is_bowler_wicket', 'sum')
    ).reset_index()
    m_all.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    m_all['mid_econ'] = (m_all['mid_runs_b'] / m_all['mid_balls_b'].replace(0, np.nan)) * 6
    m_all['mid_wpo'] = (m_all['mid_wickets_b'] / (m_all['mid_balls_b'].replace(0, np.nan) / 6))
    res = res.merge(m_all[['player_id', 'mid_econ', 'mid_wpo']], on='player_id', how='left')

    # 4. Partnership Breaks (30+ and 50+ stands)
    pb30_df = df_legal[(df_legal['partnership_before'] >= 30) & (df_legal['is_bowler_wicket'])]
    pb30 = pb30_df.groupby('bowler_id')['is_bowler_wicket'].sum().reset_index()
    pb30.columns = ['player_id', 'partnership_breaks_30']
    res = res.merge(pb30, on='player_id', how='left')

    pb50_df = df_legal[(df_legal['partnership_before'] >= 50) & (df_legal['is_bowler_wicket'])]
    pb50 = pb50_df.groupby('bowler_id')['is_bowler_wicket'].sum().reset_index()
    pb50.columns = ['player_id', 'partnership_breaks_50']
    res = res.merge(pb50, on='player_id', how='left')

    # 5. Relative Economy vs Match Run Rate
    df_legal['relative_ball_econ'] = (df_legal['bowler_runs'] / df_legal['match_rpo'].replace(0, np.nan)) * 6
    rel_econ = df_legal.groupby('bowler_id')['relative_ball_econ'].mean().reset_index()
    rel_econ.columns = ['player_id', 'relative_econ_pct']
    res = res.merge(rel_econ, on='player_id', how='left')

    # 6. Matches Won
    win_df = df_legal[df_legal['is_match_won_bowl'] == True]
    w_all = win_df.groupby('bowler_id').agg(
        win_runs_b=('bowler_runs', 'sum'),
        win_balls_b=('is_legal', 'count'),
        win_wickets_b=('is_bowler_wicket', 'sum')
    ).reset_index()
    w_all.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    w_all['win_econ'] = (w_all['win_runs_b'] / w_all['win_balls_b'].replace(0, np.nan)) * 6
    res = res.merge(w_all[['player_id', 'win_econ']], on='player_id', how='left')

    # 7. Knockouts
    ko_df = df_legal[df_legal['knock_out'] == 1]
    k_all = ko_df.groupby('bowler_id').agg(
        ko_runs_b=('bowler_runs', 'sum'),
        ko_balls_b=('is_legal', 'count'),
        ko_wickets_b=('is_bowler_wicket', 'sum')
    ).reset_index()
    k_all.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    k_all['ko_econ'] = (k_all['ko_runs_b'] / k_all['ko_balls_b'].replace(0, np.nan)) * 6
    k_all['ko_wpo'] = (k_all['ko_wickets_b'] / (k_all['ko_balls_b'].replace(0, np.nan) / 6))
    res = res.merge(k_all[['player_id', 'ko_econ', 'ko_wpo']], on='player_id', how='left')

    # Consistency CV
    match_wkts = df_legal.groupby(['bowler_id', 'match_id'])['is_bowler_wicket'].sum().reset_index()
    cv_df = match_wkts.groupby('bowler_id')['is_bowler_wicket'].agg(['std', 'mean']).reset_index()
    cv_df['bowl_consistency_cv'] = cv_df['std'] / cv_df['mean'].replace(0, np.nan)
    cv_df.rename(columns={'bowler_id': 'player_id'}, inplace=True)
    res = res.merge(cv_df[['player_id', 'bowl_consistency_cv']], on='player_id', how='left')

    return res

bowl_raw = compute_detailed_bowling(bbb_legal)
bowl_raw = bowl_raw.merge(player_match_stats[['player_id', 'matches_in_xi']], on='player_id', how='left')
bowl_raw = bowl_raw.merge(bowler_phases[['player_id', 'pp_ratio', 'mid_ratio', 'death_ratio', 'bowler_role']], on='player_id', how='left')
bowl_raw = bowl_raw.merge(motm_counts, on='player_id', how='left')
bowl_raw['motm_count'] = bowl_raw['motm_count'].fillna(0)
bowl_raw['motm_per_match'] = bowl_raw['motm_count'] / bowl_raw['matches_in_xi'].replace(0, np.nan)
bowl_raw = bowl_raw.merge(player_names, on='player_id', how='left')

# ─────────────────────────────────────────────────────────────
# STEP 4: APPLY 40-MATCH STRICT BASE FILTER
# ─────────────────────────────────────────────────────────────
print("\n=== STEP 4: Strict 40-Match Filter & Specialist Checks ===")

# Batters:
# 1. matches_in_xi >= 40
# 2. bat_role != 'Tail' (avg_batting_pos <= 7.5)
# 3. total_runs >= 300
# 4. total_balls >= 200
# 5. baseline_sr >= 100
bat_eligible = bat_raw[
    (bat_raw['matches_in_xi'] >= 40) &
    (bat_raw['bat_role'] != 'Tail') &
    (bat_raw['total_runs'] >= 300) &
    (bat_raw['total_balls'] >= 200) &
    (bat_raw['baseline_sr'] >= 100)
].copy()

print(f"  Eligible Batters (>=40 matches, specialist pos<=7.5, runs>=300, balls>=200, SR>=100): {len(bat_eligible)}")
print("  Batting Role Distribution:")
print(bat_eligible['bat_role'].value_counts())

# Bowlers:
# 1. matches_in_xi >= 40
# 2. total_balls_b >= 400
# 3. total_wickets >= 20
bowl_eligible = bowl_raw[
    (bowl_raw['matches_in_xi'] >= 40) &
    (bowl_raw['total_balls_b'] >= 400) &
    (bowl_raw['total_wickets'] >= 20)
].copy()

print(f"  Eligible Bowlers (>=40 matches, balls>=400, wkts>=20): {len(bowl_eligible)}")
print("  Bowling Role Distribution:")
print(bowl_eligible['bowler_role'].value_counts())

# ─────────────────────────────────────────────────────────────
# STEP 5: COMPOSITE SCORING FORMULAS
# ─────────────────────────────────────────────────────────────
print("\n=== STEP 5: Composite Scoring Normalization ===")

def normalize_series(s, invert=False):
    s_min = s.min()
    s_max = s.max()
    if s_max == s_min:
        return pd.Series([50.0] * len(s), index=s.index)
    norm = (s - s_min) / (s_max - s_min) * 100
    if invert:
        norm = 100 - norm
    return norm

# Fill NaNs with medians
be = bat_eligible.copy()
bat_median_cols = [
    'PI_bat', 'chase_sr', 'high_rrr_sr', 'chase_win_avg', 'death_sr',
    'death_balls_per_boundary', 'death_dot_pct', 'pp_chase_sr', 'pressure_dot_pct',
    'strike_rotation_pct', 'non_boundary_sr', 'collapse_runs', 'relative_sr_pct',
    'tough_pitch_avg', 'opp_weighted_score', 'motm_per_match', 'win_avg_ratio',
    'ko_avg', 'consistency_cv'
]
for col in bat_median_cols:
    if col in be.columns:
        be[col] = be[col].fillna(be[col].median())

# Normalize Batting Metrics
be['PI_bat_norm'] = normalize_series(be['PI_bat'])
be['chase_sr_norm'] = normalize_series(be['chase_sr'])
be['high_rrr_sr_norm'] = normalize_series(be['high_rrr_sr'])
be['chase_win_avg_norm'] = normalize_series(be['chase_win_avg'])
be['death_sr_norm'] = normalize_series(be['death_sr'])
be['death_bpb_norm'] = normalize_series(be['death_balls_per_boundary'], invert=True) # Lower balls/boundary is better
be['death_dot_inv_norm'] = normalize_series(be['death_dot_pct'], invert=True) # Lower death dot% is better
be['pp_chase_sr_norm'] = normalize_series(be['pp_chase_sr'])
be['press_dot_inv_norm'] = normalize_series(be['pressure_dot_pct'], invert=True) # Lower press dot% is better
be['strike_rot_norm'] = normalize_series(be['strike_rotation_pct'])
be['non_boundary_sr_norm'] = normalize_series(be['non_boundary_sr'])
be['collapse_runs_norm'] = normalize_series(be['collapse_runs'])
be['relative_sr_norm'] = normalize_series(be['relative_sr_pct'])
be['tough_pitch_norm'] = normalize_series(be['tough_pitch_avg'])
be['opp_weighted_norm'] = normalize_series(be['opp_weighted_score'])
be['motm_norm'] = normalize_series(be['motm_per_match'])
be['win_avg_ratio_norm'] = normalize_series(be['win_avg_ratio'])
be['ko_avg_norm'] = normalize_series(be['ko_avg'])
be['consistency_norm'] = normalize_series(be['consistency_cv'], invert=True) # Lower CV is better

# Balanced Batting Composite Weights
BAT_WEIGHTS = {
    'PI_bat_norm': 0.12,             # Overall pressure uplift
    'chase_sr_norm': 0.08,            # Innings 2 general SR
    'high_rrr_sr_norm': 0.08,         # High RRR > 10 crunch SR
    'chase_win_avg_norm': 0.07,       # Average in successful run chases
    'death_sr_norm': 0.09,            # Death overs strike rate
    'death_bpb_norm': 0.05,           # Death boundary striking frequency
    'death_dot_inv_norm': 0.05,       # Death dot ball resistance
    'pp_chase_sr_norm': 0.05,         # Powerplay chase momentum
    'press_dot_inv_norm': 0.06,       # Low dot balls under pressure
    'strike_rot_norm': 0.05,          # Strike rotation
    'non_boundary_sr_norm': 0.04,     # Gap finding / boundary-independent scoring
    'collapse_runs_norm': 0.06,       # Crisis rescue runs
    'relative_sr_norm': 0.05,         # Outperforming match pitch conditions
    'tough_pitch_norm': 0.04,         # Runs on bowling-friendly pitches
    'opp_weighted_norm': 0.05,        # Opponent quality adjustment
    'motm_norm': 0.03,                # Man of the match frequency
    'win_avg_ratio_norm': 0.03,       # Performance in team victories
    'ko_avg_norm': 0.03,              # Knockout average
    'consistency_norm': 0.02          # Match-to-match reliability
}

be['composite_score'] = sum(be[col] * w for col, w in BAT_WEIGHTS.items())
bat_eligible = be.copy()

# Fill NaNs with medians for Bowlers
boe = bowl_eligible.copy()
bowl_median_cols = [
    'PI_bowl', 'death_econ', 'extreme_death_econ', 'death_wpo', 'death_dot_pct',
    'death_boundary_conceded_pct', 'pp_econ', 'pp_wpo', 'pp_dot_pct', 'mid_econ',
    'mid_wpo', 'top_order_wkt_pct', 'pressure_dot_pct', 'partnership_breaks_30',
    'partnership_breaks_50', 'relative_econ_pct', 'opp_weighted_wpo', 'win_econ',
    'motm_per_match', 'ko_econ', 'ko_wpo', 'bowl_consistency_cv'
]
for col in bowl_median_cols:
    if col in boe.columns:
        boe[col] = boe[col].fillna(boe[col].median())

# Normalize Bowling Metrics
boe['PI_bowl_norm'] = normalize_series(boe['PI_bowl'])
boe['death_econ_inv_norm'] = normalize_series(boe['death_econ'], invert=True)
boe['ext_death_econ_inv_norm'] = normalize_series(boe['extreme_death_econ'], invert=True)
boe['death_wpo_norm'] = normalize_series(boe['death_wpo'])
boe['death_dot_norm'] = normalize_series(boe['death_dot_pct'])
boe['death_bound_inv_norm'] = normalize_series(boe['death_boundary_conceded_pct'], invert=True)
boe['pp_econ_inv_norm'] = normalize_series(boe['pp_econ'], invert=True)
boe['pp_wpo_norm'] = normalize_series(boe['pp_wpo'])
boe['pp_dot_norm'] = normalize_series(boe['pp_dot_pct'])
boe['mid_econ_inv_norm'] = normalize_series(boe['mid_econ'], invert=True)
boe['mid_wpo_norm'] = normalize_series(boe['mid_wpo'])
boe['top_order_wkt_norm'] = normalize_series(boe['top_order_wkt_pct'])
boe['press_dot_norm'] = normalize_series(boe['pressure_dot_pct'])
boe['pb30_norm'] = normalize_series(boe['partnership_breaks_30'])
boe['pb50_norm'] = normalize_series(boe['partnership_breaks_50'])
boe['rel_econ_inv_norm'] = normalize_series(boe['relative_econ_pct'], invert=True)
boe['opp_weighted_wpo_norm'] = normalize_series(boe['opp_weighted_wpo'])
boe['win_econ_inv_norm'] = normalize_series(boe['win_econ'], invert=True)
boe['motm_norm'] = normalize_series(boe['motm_per_match'])
boe['ko_econ_inv_norm'] = normalize_series(boe['ko_econ'], invert=True)
boe['ko_wpo_norm'] = normalize_series(boe['ko_wpo'])
boe['consistency_norm'] = normalize_series(boe['bowl_consistency_cv'], invert=True)

# Balanced Bowling Composite Weights
BOWL_WEIGHTS = {
    'PI_bowl_norm': 0.12,             # Overall pressure uplift
    'death_econ_inv_norm': 0.09,      # Death economy (lower is better)
    'ext_death_econ_inv_norm': 0.05,  # Extreme death (overs 19-20) economy
    'death_wpo_norm': 0.07,           # Death wickets per over
    'death_dot_norm': 0.05,           # Death dot ball %
    'death_bound_inv_norm': 0.05,     # Death boundary containment
    'pp_econ_inv_norm': 0.07,         # Powerplay economy
    'pp_wpo_norm': 0.05,              # Powerplay wicket strike rate
    'pp_dot_norm': 0.04,              # Powerplay dot ball pressure
    'mid_econ_inv_norm': 0.05,        # Middle overs control
    'mid_wpo_norm': 0.04,             # Middle overs wicket taking
    'top_order_wkt_norm': 0.07,       # Dismissing top-order batters (1-4)
    'press_dot_norm': 0.05,           # General pressure dot ball choke
    'pb30_norm': 0.04,                # Breaking 30+ partnerships
    'pb50_norm': 0.03,                # Breaking 50+ partnerships
    'rel_econ_inv_norm': 0.04,        # Outperforming match run rate
    'opp_weighted_wpo_norm': 0.03,    # Opponent quality-adjusted wickets
    'win_econ_inv_norm': 0.02,        # Economy in victories
    'motm_norm': 0.02,                # Match-winner recognition
    'ko_econ_inv_norm': 0.01,         # Knockout economy
    'ko_wpo_norm': 0.005,             # Knockout wicket taking
    'consistency_norm': 0.005         # Consistency
}

boe['composite_score'] = sum(boe[col] * w for col, w in BOWL_WEIGHTS.items())
bowl_eligible = boe.copy()

# ─────────────────────────────────────────────────────────────
# STEP 6: PRODUCE ALL RANKED LISTS
# ─────────────────────────────────────────────────────────────
print("\n=== STEP 6: Generating Top 10 Lists ===")

def get_top10(df, filter_col=None, filter_val=None, role_filter=None, label=""):
    sub = df.copy()
    if filter_col and filter_val:
        sub = sub[sub[filter_col] == filter_val]
    top = sub.sort_values('composite_score', ascending=False).head(10).copy()
    top['rank'] = range(1, len(top) + 1)
    print(f"\n  === {label} (from {len(sub)} eligible) ===")
    for _, r in top.iterrows():
        if 'bat_role' in r:
            print(f"    {int(r['rank'])}. {r['player_name']:<22} | Mtchs:{int(r['matches_in_xi']):<3} | "
                  f"Runs:{int(r['total_runs']):<5} | SR:{r['baseline_sr']:<5.1f} | Death-SR:{r['death_sr']:<5.1f} | "
                  f"Chase-SR:{r['chase_sr']:<5.1f} | Score:{r['composite_score']:<5.1f}")
        else:
            print(f"    {int(r['rank'])}. {r['player_name']:<22} | Mtchs:{int(r['matches_in_xi']):<3} | "
                  f"Wkts:{int(r['total_wickets']):<3} | Econ:{r['baseline_econ']:<5.2f} | Death-Econ:{r['death_econ']:<5.2f} | "
                  f"P-Econ:{r['pressure_econ']:<5.2f} | Score:{r['composite_score']:<5.1f}")
    return top

# Batters
top_order_bat = get_top10(bat_eligible, 'bat_role', 'Top Order', label="Top 10 Top Order Batters (1-3)")
middle_order_bat = get_top10(bat_eligible, 'bat_role', 'Middle Order', label="Top 10 Middle Order Batters (4-5)")
lower_order_bat = get_top10(bat_eligible, 'bat_role', 'Lower Order', label="Top 10 Lower Order / Finishers (6-7)")
overall_batters = bat_eligible.sort_values('composite_score', ascending=False).head(10).copy()
overall_batters['rank'] = range(1, len(overall_batters) + 1)
print(f"\n  === OVERALL TOP 10 BATTERS UNDER PRESSURE (from {len(bat_eligible)} eligible) ===")
for _, r in overall_batters.iterrows():
    print(f"    {int(r['rank'])}. {r['player_name']:<22} | Role:{r['bat_role']:<12} | Mtchs:{int(r['matches_in_xi']):<3} | "
          f"Runs:{int(r['total_runs']):<5} | BaseSR:{r['baseline_sr']:<5.1f} | PressSR:{r['pressure_sr']:<5.1f} | "
          f"DeathSR:{r['death_sr']:<5.1f} | HighRRR-SR:{r['high_rrr_sr']:<5.1f} | Score:{r['composite_score']:<5.1f}")

# Bowlers
# Powerplay specialists: pp_ratio >= 0.35
pp_bowlers = get_top10(bowl_eligible[bowl_eligible['pp_ratio'] >= 0.35], label="Top 10 Powerplay Bowlers (>=35% PP)")
# Middle overs specialists: mid_ratio >= 0.45
mid_bowlers = get_top10(bowl_eligible[bowl_eligible['mid_ratio'] >= 0.45], label="Top 10 Middle Overs Bowlers (>=45% Mid)")
# Death overs specialists: death_ratio >= 0.30
death_bowlers = get_top10(bowl_eligible[bowl_eligible['death_ratio'] >= 0.30], label="Top 10 Death Overs Bowlers (>=30% Death)")
overall_bowlers = bowl_eligible.sort_values('composite_score', ascending=False).head(10).copy()
overall_bowlers['rank'] = range(1, len(overall_bowlers) + 1)
print(f"\n  === OVERALL TOP 10 BOWLERS UNDER PRESSURE (from {len(bowl_eligible)} eligible) ===")
for _, r in overall_bowlers.iterrows():
    print(f"    {int(r['rank'])}. {r['player_name']:<22} | Role:{r['bowler_role']:<20} | Mtchs:{int(r['matches_in_xi']):<3} | "
          f"Wkts:{int(r['total_wickets']):<3} | BaseEcon:{r['baseline_econ']:<5.2f} | PressEcon:{r['pressure_econ']:<5.2f} | "
          f"DeathEcon:{r['death_econ']:<5.2f} | TopWkts:{int(r['top_order_wickets']):<3} | Score:{r['composite_score']:<5.1f}")

# ─────────────────────────────────────────────────────────────
# STEP 7: SAVE CSV OUTPUTS
# ─────────────────────────────────────────────────────────────
print("\n=== STEP 7: Saving CSV Files to results_v3 ===")

top_order_bat.to_csv(os.path.join(OUT_DIR, "top10_toporder_batters.csv"), index=False)
middle_order_bat.to_csv(os.path.join(OUT_DIR, "top10_middleorder_batters.csv"), index=False)
lower_order_bat.to_csv(os.path.join(OUT_DIR, "top10_lowerorder_batters.csv"), index=False)
overall_batters.to_csv(os.path.join(OUT_DIR, "top10_overall_batters.csv"), index=False)

pp_bowlers.to_csv(os.path.join(OUT_DIR, "top10_pp_bowlers.csv"), index=False)
mid_bowlers.to_csv(os.path.join(OUT_DIR, "top10_mid_bowlers.csv"), index=False)
death_bowlers.to_csv(os.path.join(OUT_DIR, "top10_death_bowlers.csv"), index=False)
overall_bowlers.to_csv(os.path.join(OUT_DIR, "top10_overall_bowlers.csv"), index=False)

bat_eligible.to_csv(os.path.join(OUT_DIR, "full_batter_metrics.csv"), index=False)
bowl_eligible.to_csv(os.path.join(OUT_DIR, "full_bowler_metrics.csv"), index=False)

# ─────────────────────────────────────────────────────────────
# STEP 8: WRITE SUMMARY REPORT
# ─────────────────────────────────────────────────────────────
print("\n=== STEP 8: Generating Detailed Text Summary ===")

def make_summary():
    lines = []
    lines.append("=" * 130)
    lines.append("T20 CRICKET COMPREHENSIVE PRESSURE PERFORMANCE ANALYSIS (v3)")
    lines.append("SupeRR Selector Season 2 — Deep Metrics & Strict 40-Match Threshold")
    lines.append("=" * 130)
    lines.append(f"Deliveries Analyzed : {len(bbb):,}")
    lines.append(f"Total Matches       : {len(matches):,}")
    lines.append(f"Base Criteria       : >= 40 Matches in Playing XI")
    lines.append(f"Eligible Batters    : {len(bat_eligible)} (Specialists, Pos <= 7.5, Runs >= 300, SR >= 100)")
    lines.append(f"Eligible Bowlers    : {len(bowl_eligible)} (Specialists, Balls >= 400, Wickets >= 20)")
    lines.append("")

    lines.append("─" * 130)
    lines.append("1. OVERALL TOP 10 BATTERS UNDER PRESSURE (CROSS-ROLE)")
    lines.append("─" * 130)
    lines.append(f"{'Rk':<4} {'Player':<22} {'Role':<13} {'Mtchs':<6} {'Runs':<6} {'BaseAvg':<8} {'BaseSR':<8} {'PressSR':<8} {'DeathSR':<8} {'ChaseSR':<8} {'HiRRR-SR':<9} {'P-Dot%':<7} {'Score':<6}")
    lines.append("-" * 130)
    for _, r in overall_batters.iterrows():
        lines.append(
            f"{int(r['rank']):<4} {r['player_name']:<22} {r['bat_role']:<13} {int(r['matches_in_xi']):<6} "
            f"{int(r['total_runs']):<6} {r['baseline_avg']:<8.1f} {r['baseline_sr']:<8.1f} {r['pressure_sr']:<8.1f} "
            f"{r['death_sr']:<8.1f} {r['chase_sr']:<8.1f} {r['high_rrr_sr']:<9.1f} {r['pressure_dot_pct']:<7.1f} {r['composite_score']:<6.1f}"
        )
    lines.append("")

    lines.append("─" * 130)
    lines.append("2. OVERALL TOP 10 BOWLERS UNDER PRESSURE (CROSS-PHASE)")
    lines.append("─" * 130)
    lines.append(f"{'Rk':<4} {'Player':<22} {'Role':<22} {'Mtchs':<6} {'Wkts':<6} {'BaseEcon':<9} {'PressEcon':<10} {'DeathEcon':<10} {'PPEcon':<8} {'TopWkts':<8} {'P-Dot%':<7} {'Score':<6}")
    lines.append("-" * 130)
    for _, r in overall_bowlers.iterrows():
        lines.append(
            f"{int(r['rank']):<4} {r['player_name']:<22} {r['bowler_role']:<22} {int(r['matches_in_xi']):<6} "
            f"{int(r['total_wickets']):<6} {r['baseline_econ']:<9.2f} {r['pressure_econ']:<10.2f} {r['death_econ']:<10.2f} "
            f"{r['pp_econ']:<8.2f} {int(r['top_order_wickets']):<8} {r['pressure_dot_pct']:<7.1f} {r['composite_score']:<6.1f}"
        )
    lines.append("")

    # Top Order
    lines.append("─" * 130)
    lines.append("3. TOP 10 TOP ORDER BATTERS (Positions 1-3)")
    lines.append("─" * 130)
    for _, r in top_order_bat.iterrows():
        lines.append(f"  #{int(r['rank'])} {r['player_name']:<20} | Mtchs:{int(r['matches_in_xi']):<3} | Runs:{int(r['total_runs']):<5} | "
                     f"Avg:{r['baseline_avg']:<4.1f} | SR:{r['baseline_sr']:<5.1f} | PP-Chase-SR:{r['pp_chase_sr']:<5.1f} | "
                     f"HighRRR-SR:{r['high_rrr_sr']:<5.1f} | Score:{r['composite_score']:<5.1f}")
    lines.append("")

    # Middle Order
    lines.append("─" * 130)
    lines.append("4. TOP 10 MIDDLE ORDER BATTERS (Positions 4-5)")
    lines.append("─" * 130)
    for _, r in middle_order_bat.iterrows():
        lines.append(f"  #{int(r['rank'])} {r['player_name']:<20} | Mtchs:{int(r['matches_in_xi']):<3} | Runs:{int(r['total_runs']):<5} | "
                     f"Avg:{r['baseline_avg']:<4.1f} | SR:{r['baseline_sr']:<5.1f} | Death-SR:{r['death_sr']:<5.1f} | "
                     f"Collapse-Runs:{int(r['collapse_runs']):<4} | Score:{r['composite_score']:<5.1f}")
    lines.append("")

    # Lower Order
    lines.append("─" * 130)
    lines.append("5. TOP 10 LOWER ORDER / FINISHERS (Positions 6-7)")
    lines.append("─" * 130)
    for _, r in lower_order_bat.iterrows():
        lines.append(f"  #{int(r['rank'])} {r['player_name']:<20} | Mtchs:{int(r['matches_in_xi']):<3} | Runs:{int(r['total_runs']):<5} | "
                     f"Avg:{r['baseline_avg']:<4.1f} | SR:{r['baseline_sr']:<5.1f} | Death-SR:{r['death_sr']:<5.1f} | "
                     f"Chase-SR:{r['chase_sr']:<5.1f} | Score:{r['composite_score']:<5.1f}")
    lines.append("")

    # Powerplay Bowlers
    lines.append("─" * 130)
    lines.append("6. TOP 10 POWERPLAY BOWLERS (>=35% PP Deliveries)")
    lines.append("─" * 130)
    for _, r in pp_bowlers.iterrows():
        lines.append(f"  #{int(r['rank'])} {r['player_name']:<20} | Mtchs:{int(r['matches_in_xi']):<3} | Wkts:{int(r['total_wickets']):<3} | "
                     f"PP-Econ:{r['pp_econ']:<5.2f} | PP-WPO:{r['pp_wpo']:<4.2f} | PP-Dot%:{r['pp_dot_pct']:<4.1f}% | "
                     f"Score:{r['composite_score']:<5.1f}")
    lines.append("")

    # Middle Overs Bowlers
    lines.append("─" * 130)
    lines.append("7. TOP 10 MIDDLE OVERS BOWLERS (>=45% Middle Deliveries)")
    lines.append("─" * 130)
    for _, r in mid_bowlers.iterrows():
        lines.append(f"  #{int(r['rank'])} {r['player_name']:<20} | Mtchs:{int(r['matches_in_xi']):<3} | Wkts:{int(r['total_wickets']):<3} | "
                     f"Mid-Econ:{r['mid_econ']:<5.2f} | Stand-Breaks(30+):{int(r['partnership_breaks_30']):<3} | "
                     f"Score:{r['composite_score']:<5.1f}")
    lines.append("")

    # Death Overs Bowlers
    lines.append("─" * 130)
    lines.append("8. TOP 10 DEATH OVERS BOWLERS (>=30% Death Deliveries)")
    lines.append("─" * 130)
    for _, r in death_bowlers.iterrows():
        lines.append(f"  #{int(r['rank'])} {r['player_name']:<20} | Mtchs:{int(r['matches_in_xi']):<3} | Wkts:{int(r['total_wickets']):<3} | "
                     f"Death-Econ:{r['death_econ']:<5.2f} | Death-WPO:{r['death_wpo']:<4.2f} | ExtDeath-Econ:{r['extreme_death_econ']:<5.2f} | "
                     f"Score:{r['composite_score']:<5.1f}")
    lines.append("")

    summary_text = "\n".join(lines)
    with open(os.path.join(OUT_DIR, "analysis_v3_summary.txt"), 'w', encoding='utf-8') as f:
        f.write(summary_text)
    print(f"Summary written to {os.path.join(OUT_DIR, 'analysis_v3_summary.txt')}")

make_summary()
print("\n============================================================")
print("ANALYSIS v3 COMPLETE!")
print("============================================================")
