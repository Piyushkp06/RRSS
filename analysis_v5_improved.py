"""
T20 CRICKET PRESSURE PERFORMANCE ANALYSIS - V5 IMPROVED & EXTENDED
SupeRR Selector Season 2

Bug Fixes Applied vs Original v5:
1. Striker Dismissals: Striker dismissals only count when dismissed_player_id == striker_id
   (fixes 275 non-striker runouts incorrectly lowering striker averages).
2. Elimination of Look-Ahead Bias: Removed whole-match par run rate from in-play pressure definition.
3. Pre-Delivery State Tracking: Runs needed, balls remaining, wickets down, and RRR are calculated
   using the PRE-BALL state (before the current ball's runs/wickets/balls are counted).
4. Legal Deliveries: Correctly excludes both 'wide' and 'Overstep' (no-balls) from legal over balls.
5. Innings Scope: Excludes super overs (innings 3 & 4), analyzing pure 20-over T20 matches.

New Situational Pressure Dimensions Added:
1. Batting Post-Wicket Pressure: Performance in the 12 balls immediately following a wicket
   (post-wicket SR, dot %, and survival rate).
2. Bowling Breakthrough Capitalization: Performance in the 12 balls immediately after taking a wicket
   (post-wicket economy, dot %, and back-to-back wicket strike rate).
3. Bowling to New Batters: Choking batters facing their first 10 balls (new batter econ and wickets).
4. Wicket Cluster Survival: Batting when >= 2 wickets fell in the previous 18 balls.
5. Batting with the Tail: Strike rate and boundary percentage when batting with partners at #8-11.
6. Defending Low Totals (<150) for Bowlers.
7. Chasing High Targets (>=180) for Batters.
8. Stand Breakers: Taking wickets when the opposing partnership is >= 35 runs.
"""

import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = r"c:\Users\pkpan\rpcheck"
OUT_DIR = os.path.join(BASE_DIR, "results_v5_improved")
os.makedirs(OUT_DIR, exist_ok=True)

print("Loading data files...")
bbb = pd.read_csv(os.path.join(BASE_DIR, "ball_by_ball.csv"))
matches = pd.read_csv(os.path.join(BASE_DIR, "matches.csv"))
playing_eleven = pd.read_csv(os.path.join(BASE_DIR, "playing_eleven.csv"))
ctpm = pd.read_csv(os.path.join(BASE_DIR, "competition_team_player_mapping.csv"))

# Drop super overs (innings 3 & 4)
bbb = bbb[bbb['innings'].isin([1, 2])].copy()
print(f"  Ball-by-ball (Inn 1 & 2): {len(bbb):,} rows")

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

# Delivery-level flags & cleaning
et = bbb['extras_type'].fillna('').astype(str).str.lower()
bbb['is_wide'] = et.str.contains('wide')
bbb['is_noball'] = et.str.contains(r'no[\s_-]?ball|overstep')
bbb['is_legal'] = ~bbb['is_wide'] & ~bbb['is_noball']
bbb['is_dot'] = (bbb['runs'] == 0) & bbb['is_legal']

e1 = bbb['extras1_runs'].fillna(0)
e2 = bbb['extras_2_runs'].fillna(0)
bbb['bat_runs'] = np.where(bbb['is_wide'] | et.str.contains('bye'), 0, (bbb['runs'] - e1 - e2).clip(lower=0))
bbb['bowler_runs'] = np.where(et.str.contains('bye'), 0, (bbb['runs'] - e2).clip(lower=0))

NON_BOWL_DISMISSALS = ['run out', 'obstructing the field', 'handled the ball', 'retired hurt', 'retired', 'retired out']
dt = bbb['dismissal_type'].fillna('').astype(str).str.lower()
bbb['is_bowler_wicket'] = (
    bbb['is_wicket'] &
    (~dt.isin(NON_BOWL_DISMISSALS)) &
    (bbb['dismissed_player_id'] == bbb['striker_id'])
)
# Striker dismissal flag (only counts against striker when striker is the one dismissed)
bbb['is_striker_out'] = (
    bbb['is_wicket'] &
    (bbb['dismissed_player_id'] == bbb['striker_id'])
)

bbb = bbb.merge(match_meta, on='match_id', how='left')
bbb['opp_strength_bat'] = bbb['bowling_team_id'].apply(get_opp_strength)
bbb['opp_strength_bowl'] = bbb['batting_team_id'].apply(get_opp_strength)

# Target from Innings 1 total
inn1_runs = bbb[bbb['innings'] == 1].groupby('match_id')['runs'].sum().reset_index()
inn1_runs.rename(columns={'runs': 'inn1_total_runs'}, inplace=True)
bbb = bbb.merge(inn1_runs, on='match_id', how='left')

bbb['target'] = np.where(
    bbb['revised_target'].notna() & (bbb['revised_target'] > 0),
    bbb['revised_target'],
    bbb['inn1_total_runs'] + 1
)

# Sort chronologically for sequence tracking
bbb.sort_values(['match_id', 'innings', 'overid', 'over_ball_num'], inplace=True)

# Map batting order from playing_eleven
p_xi = playing_eleven[playing_eleven['is_played'] == True].copy()
p_order = p_xi.set_index(['match_id', 'player_id'])['batting_order'].to_dict()
bbb['striker_order'] = bbb.set_index(['match_id', 'striker_id']).index.map(p_order)
bbb['non_striker_order'] = bbb.set_index(['match_id', 'non_striker_id']).index.map(p_order)

# ─────────────────────────────────────────────────────────────
# PRE-DELIVERY STATE & SITUATION TRACKING
# ─────────────────────────────────────────────────────────────
print("Computing pre-delivery state & situational pressure features...")

pre_runs = []
pre_legal = []
pre_wkts = []
balls_since_wkt = []
cluster_flags = []
post_wkt_flags = []
batter_balls_faced = {}
batter_balls_so_far = []
partnership_runs = []

current_mi = None
c_runs = 0
c_legal = 0
c_wkts = 0
last_w_ball = -999
wkt_history = []
c_p_runs = 0

for row in bbb[['match_id', 'innings', 'runs', 'is_legal', 'is_wicket', 'striker_id', 'bat_runs']].itertuples(index=False):
    mi = (row.match_id, row.innings)
    if mi != current_mi:
        current_mi = mi
        c_runs = 0
        c_legal = 0
        c_wkts = 0
        last_w_ball = -999
        wkt_history = []
        batter_balls_faced = {}
        c_p_runs = 0
        
    # Store pre-delivery state
    pre_runs.append(c_runs)
    pre_legal.append(c_legal)
    pre_wkts.append(c_wkts)
    partnership_runs.append(c_p_runs)
    
    # Situational: post-wicket (within 12 legal balls of previous wicket)
    diff = c_legal - last_w_ball if last_w_ball >= 0 else 999
    post_wkt_flags.append(1 if (diff <= 12 and last_w_ball >= 0) else 0)
    
    # Situational: cluster shockwave (>= 2 wickets in the last 18 legal balls)
    recent_w = sum(1 for b in wkt_history if (c_legal - b) <= 18)
    cluster_flags.append(1 if recent_w >= 2 else 0)
    
    # Batter's balls faced so far
    bf = batter_balls_faced.get(row.striker_id, 0)
    batter_balls_so_far.append(bf)
    if row.is_legal:
        batter_balls_faced[row.striker_id] = bf + 1
        
    # Update running counters post-delivery
    c_runs += row.runs
    if row.is_legal:
        c_legal += 1
    if row.is_wicket:
        c_wkts += 1
        last_w_ball = c_legal
        wkt_history.append(c_legal)
        c_p_runs = 0
    else:
        c_p_runs += row.bat_runs

bbb['pre_runs'] = pre_runs
bbb['pre_legal_balls'] = pre_legal
bbb['pre_wickets'] = pre_wkts
bbb['partnership_before'] = partnership_runs
bbb['is_post_wicket'] = post_wkt_flags
bbb['is_wicket_cluster'] = cluster_flags
bbb['batter_balls_so_far'] = batter_balls_so_far
bbb['is_new_batter'] = (bbb['batter_balls_so_far'] <= 10).astype(int)

# Chase calculations using PRE-delivery state
bbb['runs_needed'] = (bbb['target'] - bbb['pre_runs']).clip(lower=0)
bbb['balls_remaining'] = (120 - bbb['pre_legal_balls']).clip(lower=0)
bbb['rrr'] = np.where(
    (bbb['innings'] == 2) & (bbb['balls_remaining'] > 0),
    (bbb['runs_needed'] / bbb['balls_remaining']) * 6,
    0.0
)

# Additional Situational Flags
bbb['is_bat_with_tail'] = ((bbb['striker_order'] <= 7) & (bbb['non_striker_order'] >= 8)).astype(int)
bbb['is_match_won'] = bbb['batting_team_id'] == bbb['win_team_id']
bbb['is_match_won_bowl'] = bbb['bowling_team_id'] == bbb['win_team_id']
bbb['is_collapse'] = (bbb['pre_wickets'] >= 5) | ((bbb['overid'] <= 6) & (bbb['pre_wickets'] >= 3))

# Dynamic Pressure Definition (Pre-ball state, NO look-ahead)
bbb['is_pressure_bat'] = (
    ((bbb['innings'] == 2) & (bbb['rrr'] >= 9.5) & (bbb['balls_remaining'] <= 60)) |
    ((bbb['innings'] == 2) & (bbb['rrr'] >= 10.5)) |
    (bbb['overid'] >= 16) |
    (bbb['is_collapse'] == 1) |
    (bbb['is_wicket_cluster'] == 1) |
    (bbb['knock_out'] == 1) |
    ((bbb['innings'] == 2) & (bbb['target'] >= 180)) # high chase pressure
)

bbb['is_pressure_bowl'] = (
    (bbb['overid'] >= 16) |
    ((bbb['innings'] == 2) & (bbb['overid'] >= 14) & (bbb['runs_needed'] <= 50)) |
    (bbb['partnership_before'] >= 35) |
    ((bbb['overid'] <= 6) & (bbb['innings'] == 2) & (bbb['target'] <= 150)) |
    (bbb['knock_out'] == 1)
)

# High-leverage Crunch Overs: 1, 6, 18, 19, 20
bbb['is_crunch_over'] = bbb['overid'].isin([1, 6, 18, 19, 20])

# Miracle Chase Heist
bbb['is_miracle_heist'] = (
    bbb['is_match_won'] &
    (bbb['innings'] == 2) &
    ((bbb['rrr'] >= 10.5) | (bbb['overid'] >= 18))
)

bbb_legal = bbb[bbb['is_legal']].copy()
print(f"  Legal deliveries: {len(bbb_legal):,}")
print(f"  Pressure batting deliveries: {bbb_legal['is_pressure_bat'].sum():,}")
print(f"  Pressure bowling deliveries: {bbb_legal['is_pressure_bowl'].sum():,}")
print(f"  Deliveries immediately after a wicket: {bbb_legal['is_post_wicket'].sum():,}")

# ─────────────────────────────────────────────────────────────
# PLAYER PARTICIPATION & ROLES
# ─────────────────────────────────────────────────────────────
player_names = ctpm[['player_id', 'player_name']].drop_duplicates('player_id')
player_match_stats = p_xi.groupby('player_id').agg(
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

# Man of the Match awards
motm_counts = matches[matches['man_of_the_match'] > 0]['man_of_the_match'].value_counts().reset_index()
motm_counts.columns = ['player_id', 'motm_count']

# ─────────────────────────────────────────────────────────────
# ADVANCED BATTING AGGREGATION
# ─────────────────────────────────────────────────────────────
print("\nAggregating comprehensive batting metrics...")
b_base = bbb_legal.groupby('striker_id').agg(
    total_runs=('bat_runs', 'sum'),
    total_balls=('is_legal', 'count'),
    total_dismissals=('is_striker_out', 'sum'),  # BUG FIX: ONLY striker dismissals
    total_dots=('is_dot', 'sum'),
    total_fours=('is_four', 'sum'),
    total_sixes=('is_six', 'sum'),
    strike_rot_balls=('bat_runs', lambda x: x.isin([1, 2, 3]).sum()),
    non_boundary_runs=('bat_runs', lambda x: x[x.isin([1, 2, 3])].sum()),
    opp_weighted_runs=('bat_runs', lambda x: (x * bbb_legal.loc[x.index, 'opp_strength_bat']).sum())
).reset_index()
b_base.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_base['baseline_avg'] = np.where(b_base['total_dismissals'] > 0, b_base['total_runs'] / b_base['total_dismissals'], b_base['total_runs'])
b_base['baseline_sr'] = (b_base['total_runs'] / b_base['total_balls'].replace(0, np.nan)) * 100
b_base['baseline_dot_pct'] = (b_base['total_dots'] / b_base['total_balls'].replace(0, np.nan)) * 100
b_base['strike_rotation_pct'] = (b_base['strike_rot_balls'] / b_base['total_balls'].replace(0, np.nan)) * 100
b_base['non_boundary_sr'] = (b_base['non_boundary_runs'] / b_base['total_balls'].replace(0, np.nan)) * 100

# 1. Pressure general
p_df = bbb_legal[bbb_legal['is_pressure_bat']]
b_press = p_df.groupby('striker_id').agg(
    pressure_runs=('bat_runs', 'sum'),
    pressure_balls=('is_legal', 'count'),
    pressure_dismissals=('is_striker_out', 'sum'),
    pressure_dots=('is_dot', 'sum')
).reset_index()
b_press.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_press['pressure_avg'] = np.where(b_press['pressure_dismissals'] > 0, b_press['pressure_runs'] / b_press['pressure_dismissals'], b_press['pressure_runs'])
b_press['pressure_sr'] = (b_press['pressure_runs'] / b_press['pressure_balls'].replace(0, np.nan)) * 100
b_press['pressure_dot_pct'] = (b_press['pressure_dots'] / b_press['pressure_balls'].replace(0, np.nan)) * 100

# 2. Post-Wicket Batting (NEW SITUATIONAL METRIC)
pw_df = bbb_legal[bbb_legal['is_post_wicket'] == 1]
b_pw = pw_df.groupby('striker_id').agg(
    pw_runs=('bat_runs', 'sum'),
    pw_balls=('is_legal', 'count'),
    pw_dots=('is_dot', 'sum'),
    pw_outs=('is_striker_out', 'sum')
).reset_index()
b_pw.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_pw['post_wkt_sr'] = (b_pw['pw_runs'] / b_pw['pw_balls'].replace(0, np.nan)) * 100
b_pw['post_wkt_dot_pct'] = (b_pw['pw_dots'] / b_pw['pw_balls'].replace(0, np.nan)) * 100
b_pw['post_wkt_out_rate'] = (b_pw['pw_outs'] / b_pw['pw_balls'].replace(0, np.nan)) * 100

# 3. Wicket Cluster Survival (NEW SITUATIONAL METRIC)
wc_df = bbb_legal[bbb_legal['is_wicket_cluster'] == 1]
b_wc = wc_df.groupby('striker_id').agg(
    cluster_runs=('bat_runs', 'sum'),
    cluster_balls=('is_legal', 'count'),
    cluster_outs=('is_striker_out', 'sum')
).reset_index()
b_wc.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_wc['cluster_sr'] = (b_wc['cluster_runs'] / b_wc['cluster_balls'].replace(0, np.nan)) * 100
b_wc['cluster_avg'] = np.where(b_wc['cluster_outs'] > 0, b_wc['cluster_runs'] / b_wc['cluster_outs'], b_wc['cluster_runs'])

# 4. Batting with Tail (NEW SITUATIONAL METRIC)
tail_df = bbb_legal[bbb_legal['is_bat_with_tail'] == 1]
b_tail = tail_df.groupby('striker_id').agg(
    tail_runs=('bat_runs', 'sum'),
    tail_balls=('is_legal', 'count'),
    tail_fours=('is_four', 'sum'),
    tail_sixes=('is_six', 'sum')
).reset_index()
b_tail.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_tail['tail_sr'] = (b_tail['tail_runs'] / b_tail['tail_balls'].replace(0, np.nan)) * 100
b_tail['tail_boundary_pct'] = ((b_tail['tail_fours'] + b_tail['tail_sixes']) / b_tail['tail_balls'].replace(0, np.nan)) * 100

# 5. Run Chases
chase_df = bbb_legal[bbb_legal['innings'] == 2]
b_chase = chase_df.groupby('striker_id').agg(
    chase_runs=('bat_runs', 'sum'),
    chase_balls=('is_legal', 'count'),
    chase_dismissals=('is_striker_out', 'sum')
).reset_index()
b_chase.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_chase['chase_avg'] = np.where(b_chase['chase_dismissals'] > 0, b_chase['chase_runs'] / b_chase['chase_dismissals'], b_chase['chase_runs'])
b_chase['chase_sr'] = (b_chase['chase_runs'] / b_chase['chase_balls'].replace(0, np.nan)) * 100

# High RRR Chase (RRR >= 9.5)
hr_df = bbb_legal[(bbb_legal['innings'] == 2) & (bbb_legal['rrr'] >= 9.5)]
b_hr = hr_df.groupby('striker_id').agg(
    hr_runs=('bat_runs', 'sum'),
    hr_balls=('is_legal', 'count')
).reset_index()
b_hr.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_hr['high_rrr_sr'] = (b_hr['hr_runs'] / b_hr['hr_balls'].replace(0, np.nan)) * 100

# High Target Chase (Target >= 180)
ht_df = bbb_legal[(bbb_legal['innings'] == 2) & (bbb_legal['target'] >= 180)]
b_ht = ht_df.groupby('striker_id').agg(
    ht_runs=('bat_runs', 'sum'),
    ht_balls=('is_legal', 'count')
).reset_index()
b_ht.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_ht['high_target_sr'] = (b_ht['ht_runs'] / b_ht['ht_balls'].replace(0, np.nan)) * 100

# 6. Death Overs (16-20)
death_df = bbb_legal[bbb_legal['overid'] >= 16]
b_death = death_df.groupby('striker_id').agg(
    death_runs=('bat_runs', 'sum'),
    death_balls=('is_legal', 'count'),
    death_dots=('is_dot', 'sum'),
    death_fours=('is_four', 'sum'),
    death_sixes=('is_six', 'sum')
).reset_index()
b_death.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_death['death_sr'] = (b_death['death_runs'] / b_death['death_balls'].replace(0, np.nan)) * 100
b_death['death_dot_pct'] = (b_death['death_dots'] / b_death['death_balls'].replace(0, np.nan)) * 100
b_death['death_boundary_pct'] = ((b_death['death_fours'] + b_death['death_sixes']) / b_death['death_balls'].replace(0, np.nan)) * 100

# 7. Miracle Chase Heists
heist_df = bbb_legal[bbb_legal['is_miracle_heist']]
b_heist = heist_df.groupby('striker_id').agg(
    heist_runs=('bat_runs', 'sum'),
    heist_balls=('is_legal', 'count')
).reset_index()
b_heist.rename(columns={'striker_id': 'player_id'}, inplace=True)
b_heist['heist_sr'] = (b_heist['heist_runs'] / b_heist['heist_balls'].replace(0, np.nan)) * 100

# Merge batting metrics
res_bat = b_base.merge(b_press, on='player_id', how='left') \
                .merge(b_pw, on='player_id', how='left') \
                .merge(b_wc, on='player_id', how='left') \
                .merge(b_tail, on='player_id', how='left') \
                .merge(b_chase, on='player_id', how='left') \
                .merge(b_hr[['player_id', 'high_rrr_sr']], on='player_id', how='left') \
                .merge(b_ht[['player_id', 'high_target_sr']], on='player_id', how='left') \
                .merge(b_death[['player_id', 'death_runs', 'death_balls', 'death_sr', 'death_dot_pct', 'death_boundary_pct']], on='player_id', how='left') \
                .merge(b_heist[['player_id', 'heist_runs', 'heist_sr']], on='player_id', how='left') \
                .merge(player_match_stats[['player_id', 'matches_in_xi', 'avg_batting_position', 'bat_role']], on='player_id', how='left') \
                .merge(motm_counts, on='player_id', how='left') \
                .merge(player_names, on='player_id', how='left')

res_bat['motm_count'] = res_bat['motm_count'].fillna(0)
res_bat.fillna(0, inplace=True)

# ─────────────────────────────────────────────────────────────
# ADVANCED BOWLING AGGREGATION
# ─────────────────────────────────────────────────────────────
print("Aggregating comprehensive bowling metrics...")
bw_base = bbb_legal.groupby('bowler_id').agg(
    total_runs_b=('bowler_runs', 'sum'),
    total_balls_b=('is_legal', 'count'),
    total_wickets=('is_bowler_wicket', 'sum'),
    total_dots_b=('is_dot', 'sum'),
    top_order_wickets=('is_bowler_wicket', lambda x: (x & (bbb_legal.loc[x.index, 'striker_order'] <= 4)).sum()),
    weighted_wickets=('is_bowler_wicket', lambda x: (x * bbb_legal.loc[x.index, 'opp_strength_bowl']).sum())
).reset_index()
bw_base.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_base['baseline_econ'] = (bw_base['total_runs_b'] / bw_base['total_balls_b'].replace(0, np.nan)) * 6
bw_base['baseline_sr'] = bw_base['total_balls_b'] / bw_base['total_wickets'].replace(0, np.nan)
bw_base['baseline_dot_pct'] = (bw_base['total_dots_b'] / bw_base['total_balls_b'].replace(0, np.nan)) * 100
bw_base['top_order_wkt_pct'] = (bw_base['top_order_wickets'] / bw_base['total_wickets'].replace(0, np.nan)) * 100

# 1. Pressure general
p_b_df = bbb_legal[bbb_legal['is_pressure_bowl']]
bw_press = p_b_df.groupby('bowler_id').agg(
    pressure_runs_b=('bowler_runs', 'sum'),
    pressure_balls_b=('is_legal', 'count'),
    pressure_wickets_b=('is_bowler_wicket', 'sum'),
    pressure_dots_b=('is_dot', 'sum')
).reset_index()
bw_press.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_press['pressure_econ'] = (bw_press['pressure_runs_b'] / bw_press['pressure_balls_b'].replace(0, np.nan)) * 6
bw_press['pressure_dot_pct'] = (bw_press['pressure_dots_b'] / bw_press['pressure_balls_b'].replace(0, np.nan)) * 100

# 2. Post-Wicket Bowling Breakthrough Capitalization (NEW SITUATIONAL METRIC)
bw_pw_df = bbb_legal[bbb_legal['is_post_wicket'] == 1]
bw_pw = bw_pw_df.groupby('bowler_id').agg(
    pw_runs_b=('bowler_runs', 'sum'),
    pw_balls_b=('is_legal', 'count'),
    pw_dots_b=('is_dot', 'sum'),
    pw_wkts_b=('is_bowler_wicket', 'sum')
).reset_index()
bw_pw.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_pw['post_wkt_econ'] = (bw_pw['pw_runs_b'] / bw_pw['pw_balls_b'].replace(0, np.nan)) * 6
bw_pw['post_wkt_dot_pct'] = (bw_pw['pw_dots_b'] / bw_pw['pw_balls_b'].replace(0, np.nan)) * 100
bw_pw['post_wkt_wkt_rate'] = (bw_pw['pw_wkts_b'] / (bw_pw['pw_balls_b'].replace(0, np.nan) / 6))

# 3. Bowling to New Batters (NEW SITUATIONAL METRIC)
nb_df = bbb_legal[bbb_legal['is_new_batter'] == 1]
bw_nb = nb_df.groupby('bowler_id').agg(
    nb_runs_b=('bowler_runs', 'sum'),
    nb_balls_b=('is_legal', 'count'),
    nb_dots_b=('is_dot', 'sum'),
    nb_wkts_b=('is_bowler_wicket', 'sum')
).reset_index()
bw_nb.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_nb['new_batter_econ'] = (bw_nb['nb_runs_b'] / bw_nb['nb_balls_b'].replace(0, np.nan)) * 6
bw_nb['new_batter_dot_pct'] = (bw_nb['nb_dots_b'] / bw_nb['nb_balls_b'].replace(0, np.nan)) * 100
bw_nb['new_batter_wkt_rate'] = (bw_nb['nb_wkts_b'] / (bw_nb['nb_balls_b'].replace(0, np.nan) / 6))

# 4. High-leverage Crunch Overs (1, 6, 18, 19, 20)
hl_df = bbb_legal[bbb_legal['is_crunch_over']]
bw_hl = hl_df.groupby('bowler_id').agg(
    hl_balls=('is_legal', 'count'),
    hl_runs=('bowler_runs', 'sum'),
    hl_wkts=('is_bowler_wicket', 'sum'),
    hl_dots=('is_dot', 'sum')
).reset_index()
bw_hl.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_hl['hl_econ'] = (bw_hl['hl_runs'] / bw_hl['hl_balls'].replace(0, np.nan)) * 6
bw_hl['hl_dot_pct'] = (bw_hl['hl_dots'] / bw_hl['hl_balls'].replace(0, np.nan)) * 100
bw_hl['hl_wpo'] = bw_hl['hl_wkts'] / (bw_hl['hl_balls'].replace(0, np.nan) / 6)

# 5. Death Overs (16-20)
death_b_df = bbb_legal[bbb_legal['overid'] >= 16]
bw_death = death_b_df.groupby('bowler_id').agg(
    death_runs_b=('bowler_runs', 'sum'),
    death_balls_b=('is_legal', 'count'),
    death_wkts_b=('is_bowler_wicket', 'sum'),
    death_dots_b=('is_dot', 'sum')
).reset_index()
bw_death.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_death['death_econ'] = (bw_death['death_runs_b'] / bw_death['death_balls_b'].replace(0, np.nan)) * 6
bw_death['death_dot_pct'] = (bw_death['death_dots_b'] / bw_death['death_balls_b'].replace(0, np.nan)) * 100

# Extreme Death (19-20)
ed_df = bbb_legal[bbb_legal['overid'] >= 19]
bw_ed = ed_df.groupby('bowler_id').agg(
    ed_runs=('bowler_runs', 'sum'),
    ed_balls=('is_legal', 'count')
).reset_index()
bw_ed.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_ed['ext_death_econ'] = (bw_ed['ed_runs'] / bw_ed['ed_balls'].replace(0, np.nan)) * 6

# 6. Powerplay (1-6)
pp_b_df = bbb_legal[bbb_legal['overid'] <= 6]
bw_pp = pp_b_df.groupby('bowler_id').agg(
    pp_balls=('is_legal', 'count'),
    pp_runs=('bowler_runs', 'sum'),
    pp_wkts=('is_bowler_wicket', 'sum'),
    pp_dots=('is_dot', 'sum')
).reset_index()
bw_pp.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_pp['pp_econ'] = (bw_pp['pp_runs'] / bw_pp['pp_balls'].replace(0, np.nan)) * 6
bw_pp['pp_dot_pct'] = (bw_pp['pp_dots'] / bw_pp['pp_balls'].replace(0, np.nan)) * 100

# 7. Middle Overs (7-15)
mid_b_df = bbb_legal[(bbb_legal['overid'] >= 7) & (bbb_legal['overid'] <= 15)]
bw_mid = mid_b_df.groupby('bowler_id').agg(
    mid_balls=('is_legal', 'count'),
    mid_runs=('bowler_runs', 'sum'),
    mid_wkts=('is_bowler_wicket', 'sum'),
    mid_dots=('is_dot', 'sum')
).reset_index()
bw_mid.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_mid['mid_econ'] = (bw_mid['mid_runs'] / bw_mid['mid_balls'].replace(0, np.nan)) * 6
bw_mid['mid_dot_pct'] = (bw_mid['mid_dots'] / bw_mid['mid_balls'].replace(0, np.nan)) * 100

# 8. Stand Breakers (partnership >= 35 runs)
sb_df = bbb_legal[(bbb_legal['partnership_before'] >= 35) & (bbb_legal['is_bowler_wicket'])]
bw_sb = sb_df.groupby('bowler_id')['is_bowler_wicket'].sum().reset_index()
bw_sb.columns = ['player_id', 'stand_breaks_35']

# 9. Defending Low Totals (Inn 2, Target <= 150)
low_df = bbb_legal[(bbb_legal['innings'] == 2) & (bbb_legal['target'] <= 150)]
bw_low = low_df.groupby('bowler_id').agg(
    low_runs=('bowler_runs', 'sum'),
    low_balls=('is_legal', 'count')
).reset_index()
bw_low.rename(columns={'bowler_id': 'player_id'}, inplace=True)
bw_low['low_total_econ'] = (bw_low['low_runs'] / bw_low['low_balls'].replace(0, np.nan)) * 6

# Merge bowling metrics
res_bowl = bw_base.merge(bw_press, on='player_id', how='left') \
                  .merge(bw_pw, on='player_id', how='left') \
                  .merge(bw_nb, on='player_id', how='left') \
                  .merge(bw_hl, on='player_id', how='left') \
                  .merge(bw_death, on='player_id', how='left') \
                  .merge(bw_ed[['player_id', 'ext_death_econ']], on='player_id', how='left') \
                  .merge(bw_pp, on='player_id', how='left') \
                  .merge(bw_mid, on='player_id', how='left') \
                  .merge(bw_sb, on='player_id', how='left') \
                  .merge(bw_low[['player_id', 'low_total_econ']], on='player_id', how='left') \
                  .merge(player_match_stats[['player_id', 'matches_in_xi']], on='player_id', how='left') \
                  .merge(bowler_phases[['player_id', 'pp_balls', 'mid_balls', 'death_balls', 'pp_ratio', 'mid_ratio', 'death_ratio', 'bowler_role']], on='player_id', how='left', suffixes=('', '_phase')) \
                  .merge(motm_counts, on='player_id', how='left') \
                  .merge(player_names, on='player_id', how='left')

res_bowl['motm_count'] = res_bowl['motm_count'].fillna(0)
res_bowl.fillna(0, inplace=True)

# ─────────────────────────────────────────────────────────────
# MULTI-GATE FLOOR CUTOFFS (BALANCED GATING)
# ─────────────────────────────────────────────────────────────
print("\nApplying Multi-Gate Cutoffs...")

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
print(f"  Total Batters Passing ALL Strict Cutoffs: {len(bat_eligible)}")

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
print(f"  Total Bowlers Passing ALL Strict Cutoffs: {len(bowl_eligible)}")

# ─────────────────────────────────────────────────────────────
# 5-DIMENSION BALANCED SCORING WITH SITUATIONAL PRESSURE PILLARS
# ─────────────────────────────────────────────────────────────
def norm_series(s, invert=False):
    s_min = s.min()
    s_max = s.max()
    if s_max == s_min:
        return pd.Series(50.0, index=s.index)
    if invert:
        return 100.0 * (s_max - s) / (s_max - s_min)
    return 100.0 * (s - s_min) / (s_max - s_min)

# BATTING BALANCED SCORING
be = bat_eligible.copy()
# Fill medians for situational subsets
be['high_rrr_sr'] = np.where(be['high_rrr_sr'] > 0, be['high_rrr_sr'], be['chase_sr'])
be['high_target_sr'] = np.where(be['high_target_sr'] > 0, be['high_target_sr'], be['chase_sr'])
be['post_wkt_sr'] = np.where(be['post_wkt_sr'] > 0, be['post_wkt_sr'], be['baseline_sr'])
be['cluster_sr'] = np.where(be['cluster_sr'] > 0, be['cluster_sr'], be['pressure_sr'])

# Dim 1: Run Chase Mastery & High Targets
d1_c_sr = norm_series(be['chase_sr'])
d1_c_avg = norm_series(be['chase_avg'])
d1_hr_sr = norm_series(be['high_rrr_sr'])
d1_ht_sr = norm_series(be['high_target_sr'])
be['dim1_chase'] = 0.35 * d1_c_sr + 0.30 * d1_c_avg + 0.20 * d1_hr_sr + 0.15 * d1_ht_sr

# Dim 2: Death Overs Power & Boundary Frequency
d2_d_sr = norm_series(be['death_sr'])
d2_d_bnd = norm_series(be['death_boundary_pct'])
d2_d_dot = norm_series(be['death_dot_pct'], invert=True)
be['dim2_death'] = 0.50 * d2_d_sr + 0.30 * d2_d_bnd + 0.20 * d2_d_dot

# Dim 3: Crisis, Post-Wicket & Cluster Shockwave (NEW SITUATIONAL PILLAR)
d3_pw_sr = norm_series(be['post_wkt_sr'])
d3_pw_dot = norm_series(be['post_wkt_dot_pct'], invert=True)
d3_pw_out = norm_series(be['post_wkt_out_rate'], invert=True) # avoiding double breakthrough
d3_cl_sr = norm_series(be['cluster_sr'])
d3_heist = norm_series(be['heist_runs'])
be['dim3_crisis'] = 0.25 * d3_pw_sr + 0.20 * d3_pw_dot + 0.20 * d3_pw_out + 0.20 * d3_cl_sr + 0.15 * d3_heist

# Dim 4: Strike Rotation & Pressure Dot Choke Resistance
d4_p_dot = norm_series(be['pressure_dot_pct'], invert=True)
d4_s_rot = norm_series(be['strike_rotation_pct'])
d4_nb_sr = norm_series(be['non_boundary_sr'])
be['dim4_strike_rot'] = 0.45 * d4_p_dot + 0.35 * d4_s_rot + 0.20 * d4_nb_sr

# Dim 5: Quality Baseline Consistency & Opponent Weighting
d5_b_sr = norm_series(be['baseline_sr'])
d5_b_avg = norm_series(be['baseline_avg'])
d5_opp = norm_series(be['opp_weighted_runs'] / be['total_runs'])
be['dim5_quality'] = 0.40 * d5_b_sr + 0.35 * d5_b_avg + 0.25 * d5_opp

# Batting Min Dimension Floor & Balanced Score
bat_dims = ['dim1_chase', 'dim2_death', 'dim3_crisis', 'dim4_strike_rot', 'dim5_quality']
be['dim_min'] = be[bat_dims].min(axis=1)
be['dim_weighted_mean'] = (
    0.25 * be['dim1_chase'] +
    0.25 * be['dim2_death'] +
    0.20 * be['dim3_crisis'] +
    0.15 * be['dim4_strike_rot'] +
    0.15 * be['dim5_quality']
)
be['balanced_pressure_score'] = 0.80 * be['dim_weighted_mean'] + 0.20 * be['dim_min']
bat_eligible = be.sort_values('balanced_pressure_score', ascending=False).reset_index(drop=True)

# BOWLING BALANCED SCORING
boe = bowl_eligible.copy()
boe['ext_death_econ'] = np.where(boe['ext_death_econ'] > 0, boe['ext_death_econ'], boe['death_econ'])
boe['low_total_econ'] = np.where(boe['low_total_econ'] > 0, boe['low_total_econ'], boe['baseline_econ'])

# Dim 1: High-Leverage Crunch Overs Lockdown (1, 6, 18, 19, 20)
b_d1_econ = norm_series(boe['hl_econ'], invert=True)
b_d1_dot = norm_series(boe['hl_dot_pct'])
b_d1_wpo = norm_series(boe['hl_wpo'])
boe['dim1_crunch'] = 0.50 * b_d1_econ + 0.30 * b_d1_dot + 0.20 * b_d1_wpo

# Dim 2: Death Overs Control
b_d2_econ = norm_series(boe['death_econ'], invert=True)
b_d2_edecon = norm_series(boe['ext_death_econ'], invert=True)
b_d2_dot = norm_series(boe['death_dot_pct'])
boe['dim2_death'] = 0.45 * b_d2_econ + 0.35 * b_d2_edecon + 0.20 * b_d2_dot

# Dim 3: Post-Wicket Breakthrough Capitalization & New Batter Choke (NEW SITUATIONAL PILLAR)
b_d3_pw_econ = norm_series(boe['post_wkt_econ'], invert=True)
b_d3_pw_dot = norm_series(boe['post_wkt_dot_pct'])
b_d3_nb_econ = norm_series(boe['new_batter_econ'], invert=True)
b_d3_nb_wkt = norm_series(boe['new_batter_wkt_rate'])
boe['dim3_breakthrough'] = 0.30 * b_d3_pw_econ + 0.25 * b_d3_pw_dot + 0.25 * b_d3_nb_econ + 0.20 * b_d3_nb_wkt

# Dim 4: Wicket Quality & Stand Breaking
b_d4_sr = norm_series(boe['baseline_sr'], invert=True)
b_d4_top = norm_series(boe['top_order_wkt_pct'])
b_d4_sb = norm_series(boe['stand_breaks_35'])
b_d4_opp = norm_series(boe['weighted_wickets'])
boe['dim4_quality'] = 0.35 * b_d4_sr + 0.30 * b_d4_top + 0.20 * b_d4_sb + 0.15 * b_d4_opp

# Dim 5: Discipline & Low Total Defense
b_d5_econ = norm_series(boe['baseline_econ'], invert=True)
b_d5_low = norm_series(boe['low_total_econ'], invert=True)
b_d5_dot = norm_series(boe['pressure_dot_pct'])
boe['dim5_discipline'] = 0.45 * b_d5_econ + 0.35 * b_d5_low + 0.20 * b_d5_dot

# Bowling Min Dimension Floor & Balanced Score
bowl_dims = ['dim1_crunch', 'dim2_death', 'dim3_breakthrough', 'dim4_quality', 'dim5_discipline']
boe['dim_min'] = boe[bowl_dims].min(axis=1)
boe['dim_weighted_mean'] = (
    0.25 * boe['dim1_crunch'] +
    0.25 * boe['dim2_death'] +
    0.20 * boe['dim3_breakthrough'] +
    0.15 * boe['dim4_quality'] +
    0.15 * boe['dim5_discipline']
)
boe['balanced_pressure_score'] = 0.80 * boe['dim_weighted_mean'] + 0.20 * boe['dim_min']
bowl_eligible = boe.sort_values('balanced_pressure_score', ascending=False).reset_index(drop=True)

# ─────────────────────────────────────────────────────────────
# PRINT TOP 10S
# ─────────────────────────────────────────────────────────────
print("\n=== TOP 10 OVERALL BATTERS (V5 IMPROVED) ===")
cols_bat_print = ['player_name', 'bat_role', 'matches_in_xi', 'baseline_sr', 'death_sr', 'chase_sr', 'post_wkt_sr', 'dim_min', 'balanced_pressure_score']
for i, r in bat_eligible.head(10).iterrows():
    print(f"  {i+1}. {r['player_name']:<20} | {r['bat_role']:<12} | Mat:{int(r['matches_in_xi']):<2} | BaseSR:{r['baseline_sr']:<5.1f} | DeathSR:{r['death_sr']:<5.1f} | ChaseSR:{r['chase_sr']:<5.1f} | PostWktSR:{r['post_wkt_sr']:<5.1f} | MinDim:{r['dim_min']:<4.1f} | Score:{r['balanced_pressure_score']:<5.1f}")

print("\n=== TOP 10 OVERALL BOWLERS (V5 IMPROVED) ===")
cols_bowl_print = ['player_name', 'bowler_role', 'matches_in_xi', 'total_wickets', 'baseline_econ', 'death_econ', 'hl_econ', 'post_wkt_econ', 'dim_min', 'balanced_pressure_score']
for i, r in bowl_eligible.head(10).iterrows():
    print(f"  {i+1}. {r['player_name']:<20} | {r['bowler_role']:<20} | Mat:{int(r['matches_in_xi']):<2} | Wkts:{int(r['total_wickets']):<3} | BaseEcon:{r['baseline_econ']:<5.2f} | DeathEcon:{r['death_econ']:<5.2f} | HLEcon:{r['hl_econ']:<5.2f} | PostWktEcon:{r['post_wkt_econ']:<5.2f} | MinDim:{r['dim_min']:<4.1f} | Score:{r['balanced_pressure_score']:<5.1f}")

# ─────────────────────────────────────────────────────────────
# ROLE-BASED SPLITS
# ─────────────────────────────────────────────────────────────
top_bat = bat_eligible[bat_eligible['bat_role'] == 'Top Order'].head(10).copy()
mid_bat = bat_eligible[bat_eligible['bat_role'] == 'Middle Order'].head(10).copy()
low_bat = bat_eligible[bat_eligible['bat_role'] == 'Lower Order'].head(10).copy()
top_bat['rank'] = range(1, len(top_bat) + 1)
mid_bat['rank'] = range(1, len(mid_bat) + 1)
low_bat['rank'] = range(1, len(low_bat) + 1)

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
                                     0.25 * norm_series(death_bowlers['death_wkts_b'])
death_bowlers = death_bowlers.sort_values('death_phase_score', ascending=False).head(10).reset_index(drop=True)
death_bowlers['rank'] = range(1, len(death_bowlers) + 1)

# Overall Top 10s
top10_overall_batters = bat_eligible.head(10).copy()
top10_overall_batters['rank'] = range(1, 11)

top10_overall_bowlers = bowl_eligible.head(10).copy()
top10_overall_bowlers['rank'] = range(1, 11)

# Save Outputs
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

with open(os.path.join(OUT_DIR, "analysis_v5_improved_summary.txt"), "w") as f:
    f.write("=== T20 CRICKET PRESSURE PERFORMANCE ANALYSIS - V5 IMPROVED ===\n")
    f.write("Includes Bug Fixes & Situational Post-Wicket / Breakthrough / New Batter Pillars\n\n")
    f.write(f"Eligible Batters: {len(bat_eligible)} | Eligible Bowlers: {len(bowl_eligible)}\n\n")
    f.write("TOP 10 OVERALL BATTERS:\n")
    for i, r in top10_overall_batters.iterrows():
        f.write(f"{int(r['rank'])}. {r['player_name']:<22} | Role:{r['bat_role']:<12} | Mat:{int(r['matches_in_xi']):<2} | BaseSR:{r['baseline_sr']:<5.1f} | DeathSR:{r['death_sr']:<5.1f} | ChaseSR:{r['chase_sr']:<5.1f} | PostWktSR:{r['post_wkt_sr']:<5.1f} | MinDim:{r['dim_min']:<4.1f} | Score:{r['balanced_pressure_score']:<5.1f}\n")
    f.write("\nTOP 10 OVERALL BOWLERS:\n")
    for i, r in top10_overall_bowlers.iterrows():
        f.write(f"{int(r['rank'])}. {r['player_name']:<22} | Role:{r['bowler_role']:<20} | Mat:{int(r['matches_in_xi']):<2} | Wkts:{int(r['total_wickets']):<3} | BaseEcon:{r['baseline_econ']:<5.2f} | DeathEcon:{r['death_econ']:<5.2f} | HLEcon:{r['hl_econ']:<5.2f} | PostWktEcon:{r['post_wkt_econ']:<5.2f} | MinDim:{r['dim_min']:<4.1f} | Score:{r['balanced_pressure_score']:<5.1f}\n")

print("\nAnalysis v5 Improved completed successfully! Outputs saved to results_v5_improved/")
