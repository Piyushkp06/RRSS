"""
T20 CRICKET PRESSURE PERFORMANCE ANALYSIS v6
SupeRR Selector Season 2

What changed vs v5
------------------
BUG FIXES
  * Super overs removed (innings 1 and 2 only); no-result matches removed.
  * Match state (runs needed, RRR, balls left) is the PRE-ball state, not post-ball.
  * Batter dismissals count only when the striker is out (no non-striker run-out inflation).
  * Wides and no-balls count against the bowler's runs; balls bowled are legal balls only.
  * Look-ahead flags (match_rpo < 7.5) removed.

METHOD
  * Win-probability model (gradient boosting, out-of-fold by match) -> WPA per ball.
  * Pressure = high-leverage AND still-contested deliveries (data-driven, not hand flags).
  * Hard performance gates replaced by volume gates + Bayesian shrinkage toward league average.
  * Counting stats replaced by per-ball rates; percentile ranks replace min-max.
  * Final score = 0.75 * weighted mean of 5 dimensions + 0.25 * geometric mean of dimensions.
  * Context-adjusted run value (runs above expectation by innings/over/wickets).

VALIDATION
  * Split-half reliability of every metric (Spearman-Brown corrected).
  * Bootstrap-over-matches rank stability of the top 10.

Requires: pandas, numpy, scikit-learn
"""

import os
import warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import log_loss, brier_score_loss

warnings.filterwarnings("ignore")

BASE_DIR = r"c:\Users\pkpan\rpcheck"
OUT_DIR = os.path.join(BASE_DIR, "results_v6")
os.makedirs(OUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
CFG = dict(
    min_matches=30,
    max_avg_bat_pos=7.5,
    bat_min_balls=300,
    bat_min_pressure_balls=100,
    bowl_min_balls=400,
    bowl_min_pressure_balls=100,
    phase_min_balls=dict(pp=100, mid=150, death=70),
    lev_quantile=0.70,          # top 30% leverage deliveries
    contested_lo=0.10,          # ignore deliveries when the match is already decided
    contested_hi=0.90,
    alpha_mean=0.75,            # score = alpha*weighted_mean + (1-alpha)*geometric_mean
    bootstrap_n=200,
    split_half_reps=20,
    seed=42,
)

# Shrinkage strength (in balls unless noted): prior is the league average of the same subset
K = dict(press=120, chase=120, death=80, collapse=100, all=200,
         wkt=250, share=10, pb=300, phase=100)

NONBOWLER_DISMISSALS = {"run out", "obstructing the field", "handled the ball",
                        "hit the ball twice", "timed out",
                        "retired hurt", "retired", "retired out"}
RETIRED = {"retired hurt", "retired", "retired out"}

# ─────────────────────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────────────────────
print("Loading data files...")
bbb = pd.read_csv(os.path.join(BASE_DIR, "ball_by_ball.csv"))
matches = pd.read_csv(os.path.join(BASE_DIR, "matches.csv"))
playing_eleven = pd.read_csv(os.path.join(BASE_DIR, "playing_eleven.csv"))
ctpm = pd.read_csv(os.path.join(BASE_DIR, "competition_team_player_mapping.csv"))
print(f"  Ball-by-ball: {len(bbb):,} rows | Matches: {len(matches):,} | Playing XI: {len(playing_eleven):,}")

bbb = bbb[bbb["innings"].isin([1, 2])].copy()           # drop super overs
print("  overid range:", bbb["overid"].min(), "-", bbb["overid"].max(), "(script assumes 1..20)")
print("  extras_type values:", bbb["extras_type"].fillna("none").value_counts().head(8).to_dict())

# ─────────────────────────────────────────────────────────────
# DELIVERY-LEVEL CLEANING
# ─────────────────────────────────────────────────────────────
et = bbb["extras_type"].fillna("").astype(str).str.lower()
bbb["is_wide"] = et.str.contains("wide")
bbb["is_noball"] = et.str.contains(r"no[\s_-]?ball")
bbb["is_bye"] = et.str.contains("bye")                   # bye and leg bye
bbb["faced"] = ~bbb["is_wide"]                           # ball faced by batter
bbb["legal"] = ~bbb["is_wide"] & ~bbb["is_noball"]       # ball counted in the over

e1 = bbb["extras1_runs"].fillna(0)
e2 = bbb["extras_2_runs"].fillna(0)
bbb["bat_runs"] = np.where(bbb["is_wide"] | bbb["is_bye"], 0, (bbb["runs"] - e1 - e2).clip(lower=0))
bbb["bowler_runs"] = np.where(bbb["is_bye"], 0, (bbb["runs"] - e2).clip(lower=0))

dt = bbb["dismissal_type"].fillna("").astype(str).str.lower()
is_w = bbb["is_wicket"].fillna(False).astype(bool)
striker_out = bbb["dismissed_player_id"] == bbb["striker_id"]
bbb["team_wkt"] = is_w & ~dt.isin({"retired hurt", "retired"})
bbb["bat_out"] = is_w & striker_out & ~dt.isin(RETIRED)
bbb["bowler_wkt"] = is_w & striker_out & ~dt.isin(NONBOWLER_DISMISSALS)
bbb["is_bnd"] = (bbb["is_four"].fillna(0).astype(bool) | bbb["is_six"].fillna(0).astype(bool)) & (bbb["bat_runs"] > 0)

# match results (drop no-result / tied matches with no winner)
match_meta = matches[["match_id", "win_team_id", "revised_target"]].copy()
bbb = bbb.merge(match_meta, on="match_id", how="left")
bbb = bbb[bbb["win_team_id"].notna()].copy()
bbb["y"] = (bbb["batting_team_id"] == bbb["win_team_id"]).astype(int)

# striker's batting position (for "top-order wickets")
pe = playing_eleven[playing_eleven["is_played"] == True].copy()
pe_bo = (pe[["match_id", "player_id", "batting_order"]]
         .drop_duplicates(["match_id", "player_id"])
         .rename(columns={"player_id": "striker_id", "batting_order": "striker_bo"}))
bbb = bbb.merge(pe_bo, on=["match_id", "striker_id"], how="left")

bbb = bbb.sort_values(["match_id", "innings", "overid", "over_ball_num"]).reset_index(drop=True)

# ─────────────────────────────────────────────────────────────
# PRE-BALL MATCH STATE
# ─────────────────────────────────────────────────────────────
bbb["legal_i"] = bbb["legal"].astype(int)
bbb["wkt_i"] = bbb["team_wkt"].astype(int)
g = bbb.groupby(["match_id", "innings"])
bbb["runs_before"] = g["runs"].cumsum() - bbb["runs"]
bbb["legal_before"] = g["legal_i"].cumsum() - bbb["legal_i"]
bbb["wickets_before"] = g["wkt_i"].cumsum() - bbb["wkt_i"]
bbb["balls_left"] = (120 - bbb["legal_before"]).clip(lower=0)

# partnership runs before this ball (vectorised)
gp = bbb.groupby(["match_id", "innings", "wickets_before"])
bbb["partnership_before"] = gp["runs"].cumsum() - bbb["runs"]

inn1_total = bbb[bbb["innings"] == 1].groupby("match_id")["runs"].sum()
bbb["inn1_total"] = bbb["match_id"].map(inn1_total)
is2 = bbb["innings"] == 2
rev = bbb["revised_target"]
bbb["target"] = np.where(is2, np.where(rev.notna() & (rev > 0), rev, bbb["inn1_total"] + 1), np.nan)
bbb["runs_needed"] = np.where(is2, (bbb["target"] - bbb["runs_before"]).clip(lower=0), np.nan)
bbb["rrr"] = np.where(is2 & (bbb["balls_left"] > 0), bbb["runs_needed"] / bbb["balls_left"].replace(0, np.nan) * 6, np.nan)
bbb["crr"] = bbb["runs_before"] / bbb["legal_before"].clip(lower=1) * 6

# ─────────────────────────────────────────────────────────────
# WIN PROBABILITY MODEL (out-of-fold by match) -> WPA
# ─────────────────────────────────────────────────────────────
print("\nFitting win-probability model (5-fold grouped by match)...")
FEATS = ["innings", "balls_left", "wickets_before", "runs_before", "target", "runs_needed", "rrr", "crr"]
oof = np.zeros(len(bbb))
for tr, te in GroupKFold(n_splits=5).split(bbb[FEATS], bbb["y"], bbb["match_id"]):
    clf = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, max_leaf_nodes=31,
                                         min_samples_leaf=300, l2_regularization=1.0,
                                         random_state=CFG["seed"])
    clf.fit(bbb.iloc[tr][FEATS], bbb.iloc[tr]["y"])
    oof[te] = clf.predict_proba(bbb.iloc[te][FEATS])[:, 1]
bbb["wp_before"] = np.clip(oof, 0.01, 0.99)
print(f"  OOF log-loss: {log_loss(bbb['y'], bbb['wp_before']):.4f} | Brier: {brier_score_loss(bbb['y'], bbb['wp_before']):.4f}")

bbb["wp_after"] = bbb.groupby(["match_id", "innings"])["wp_before"].shift(-1)
last = bbb["wp_after"].isna()
m2 = last & (bbb["innings"] == 2)
bbb.loc[m2, "wp_after"] = bbb.loc[m2, "y"].astype(float)          # final outcome
first2 = bbb[bbb["innings"] == 2].groupby("match_id")["wp_before"].first()
m1 = last & (bbb["innings"] == 1)
bbb.loc[m1, "wp_after"] = 1 - bbb.loc[m1, "match_id"].map(first2)  # chasing side's opening WP
bbb["wpa_bat"] = (bbb["wp_after"] - bbb["wp_before"]).fillna(0.0)
bbb["wpa_bowl"] = -bbb["wpa_bat"]

# ─────────────────────────────────────────────────────────────
# PRESSURE = HIGH LEVERAGE & STILL CONTESTED
# ─────────────────────────────────────────────────────────────
bbb["wk_b"] = bbb["wickets_before"].clip(upper=8)
rrr_bin = pd.cut(bbb["rrr"].fillna(-0.5), [-1, 6, 8, 10, 12, 15, 1e9], labels=False)
bbb["rrr_bin"] = np.where(bbb["innings"] == 1, -1, rrr_bin)
lev_keys = ["innings", "overid", "wk_b", "rrr_bin"]
bbb["abs_wpa"] = bbb["wpa_bat"].abs()
bbb["leverage"] = bbb.groupby(lev_keys)["abs_wpa"].transform("mean")
lev_thr = bbb["leverage"].quantile(CFG["lev_quantile"])
bbb["is_pressure"] = (bbb["leverage"] >= lev_thr) & bbb["wp_before"].between(CFG["contested_lo"], CFG["contested_hi"])
bbb["is_collapse"] = (bbb["wickets_before"] >= 5) | ((bbb["overid"] <= 6) & (bbb["wickets_before"] >= 3))
print(f"  Pressure deliveries: {bbb['is_pressure'].mean():.1%} of all | collapse deliveries: {bbb['is_collapse'].mean():.1%}")

# ─────────────────────────────────────────────────────────────
# EXPECTED RUNS (context adjustment)
# ─────────────────────────────────────────────────────────────
exp_keys = ["innings", "overid", "wk_b"]
exp_bat = bbb[bbb["faced"]].groupby(exp_keys)["bat_runs"].mean().rename("exp_bat").reset_index()
exp_bowl = bbb.groupby(exp_keys)["bowler_runs"].mean().rename("exp_bowl").reset_index()
bbb = bbb.merge(exp_bat, on=exp_keys, how="left").merge(exp_bowl, on=exp_keys, how="left")
bbb["rae_bat"] = np.where(bbb["faced"], bbb["bat_runs"] - bbb["exp_bat"], 0.0)
bbb["rae_bowl"] = bbb["bowler_runs"] - bbb["exp_bowl"]

# ─────────────────────────────────────────────────────────────
# MATCH-LEVEL ADDITIVE TABLES (everything else is sums of these)
# ─────────────────────────────────────────────────────────────
true_all = pd.Series(True, index=bbb.index)

BAT_SUBSETS = {
    "all": true_all,
    "press": bbb["is_pressure"],
    "death": bbb["overid"] >= 16,
    "chase": bbb["innings"] == 2,
    "collapse": bbb["is_collapse"],
}
bat_df = pd.DataFrame({"match_id": bbb["match_id"], "player_id": bbb["striker_id"]})
for s, m in BAT_SUBSETS.items():
    f = bbb["faced"] & m
    bat_df[f"{s}_balls"] = f.astype(int)
    bat_df[f"{s}_runs"] = np.where(f, bbb["bat_runs"], 0)
    bat_df[f"{s}_out"] = (bbb["bat_out"] & m).astype(int)
    bat_df[f"{s}_dot"] = (f & (bbb["bat_runs"] == 0)).astype(int)
    bat_df[f"{s}_bnd"] = (f & bbb["is_bnd"]).astype(int)
    bat_df[f"{s}_wpa"] = np.where(f, bbb["wpa_bat"], 0.0)
bat_df["all_rae"] = bbb["rae_bat"]
bat_match = bat_df.groupby(["match_id", "player_id"]).sum().reset_index()
bat_match["apps"] = 1

BOWL_SUBSETS = {
    "all": true_all,
    "press": bbb["is_pressure"],
    "death": bbb["overid"] >= 16,
    "crunch": bbb["overid"].isin([1, 6, 18, 19, 20]),
    "pp": bbb["overid"] <= 6,
    "mid": (bbb["overid"] >= 7) & (bbb["overid"] <= 15),
}
bowl_df = pd.DataFrame({"match_id": bbb["match_id"], "player_id": bbb["bowler_id"]})
for s, m in BOWL_SUBSETS.items():
    bowl_df[f"{s}_balls"] = (bbb["legal"] & m).astype(int)
    bowl_df[f"{s}_runs"] = np.where(m, bbb["bowler_runs"], 0)
    bowl_df[f"{s}_wkts"] = (bbb["bowler_wkt"] & m).astype(int)
    bowl_df[f"{s}_dots"] = (bbb["legal"] & (bbb["bowler_runs"] == 0) & m).astype(int)
    bowl_df[f"{s}_wpa"] = np.where(m, bbb["wpa_bowl"], 0.0)
bowl_df["all_rae"] = bbb["rae_bowl"]
bowl_df["top_wkts"] = (bbb["bowler_wkt"] & (bbb["striker_bo"] <= 4)).astype(int)
bowl_df["pb30"] = (bbb["bowler_wkt"] & (bbb["partnership_before"] >= 30)).astype(int)
bowl_match = bowl_df.groupby(["match_id", "player_id"]).sum().reset_index()
bowl_match["apps"] = 1

# ─────────────────────────────────────────────────────────────
# STATIC PLAYER INFO
# ─────────────────────────────────────────────────────────────
names = ctpm[["player_id", "player_name"]].drop_duplicates("player_id").set_index("player_id")["player_name"]


def classify_batter(pos):
    if pd.isna(pos) or pos > 7.5:
        return "Tail"
    if pos <= 3.5:
        return "Top Order"
    if pos <= 5.5:
        return "Middle Order"
    return "Lower Order"


static_bat = pe.groupby("player_id").agg(matches_in_xi=("match_id", "nunique"),
                                         avg_batting_position=("batting_order", "mean"))
static_bat["bat_role"] = static_bat["avg_batting_position"].apply(classify_batter)

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def aggregate(mdf, counts=None):
    """Sum a match-level table to player level. counts = {match_id: multiplicity} for
    resampling / half-splits; matches missing from counts get weight 0."""
    if counts is None:
        return mdf.drop(columns="match_id").groupby("player_id").sum()
    w = mdf["match_id"].map(counts).fillna(0).values
    vals = mdf.drop(columns=["match_id", "player_id"]).mul(w, axis=0)
    vals["player_id"] = mdf["player_id"].values
    return vals.groupby("player_id").sum()


def shrink(num, den, prior_ratio, k):
    return (num + prior_ratio * k) / (den + k)


def pct(s, invert=False):
    s = s.fillna(s.median())
    return s.rank(pct=True, ascending=not invert) * 100


def score_pool(df, spec, alpha=CFG["alpha_mean"]):
    out = df.copy()
    dims = list(spec.keys())
    for name, (_, items) in spec.items():
        out[name] = sum(w * pct(out[c], inv) for c, inv, w in items)
    W = np.array([spec[n][0] for n in dims])
    M = out[dims].values
    out["wmean"] = (M * W).sum(axis=1) / W.sum()
    out["gmean"] = np.exp(np.log(np.clip(M, 1, None)).mean(axis=1))
    out["min_dim"] = M.min(axis=1)
    out["score"] = alpha * out["wmean"] + (1 - alpha) * out["gmean"]
    return out.sort_values("score", ascending=False)


# ─────────────────────────────────────────────────────────────
# BATTER METRICS & SCORING
# ─────────────────────────────────────────────────────────────
def bat_metrics(A, L):
    d = pd.DataFrame(index=A.index)
    d["balls"] = A["all_balls"]
    d["runs"] = A["all_runs"]
    d["avg"] = A["all_runs"] / A["all_out"].clip(lower=1)
    d["sr"] = A["all_runs"] / A["all_balls"].clip(lower=1) * 100
    for s in ["press", "death", "chase", "collapse"]:
        d[f"{s}_balls"] = A[f"{s}_balls"]
    for s, k in [("press", "press"), ("chase", "chase"), ("death", "death"), ("collapse", "collapse")]:
        b = A[f"{s}_balls"]
        for col, name, mult in [("runs", "sr", 100), ("dot", "dot_pct", 100), ("bnd", "bnd_pct", 100),
                                ("out", "out_per100", 100), ("wpa", "wpa100", 100)]:
            d[f"{s}_{name}"] = shrink(A[f"{s}_{col}"], b, L[f"{s}_{col}"] / L[f"{s}_balls"], K[k]) * mult
    d["rae100"] = shrink(A["all_rae"], A["all_balls"], L["all_rae"] / L["all_balls"], K["all"]) * 100
    return d


def bat_table(A, L):
    d = bat_metrics(A, L).join(static_bat, how="left")
    keep = ((d["matches_in_xi"] >= CFG["min_matches"]) &
            (d["balls"] >= CFG["bat_min_balls"]) &
            (d["press_balls"] >= CFG["bat_min_pressure_balls"]) &
            (d["avg_batting_position"] <= CFG["max_avg_bat_pos"]))
    return d[keep]


BAT_DIMS = {
    "d1_pressure":   (0.30, [("press_wpa100", False, 0.5), ("press_sr", False, 0.3), ("press_out_per100", True, 0.2)]),
    "d2_efficiency": (0.15, [("press_dot_pct", True, 0.5), ("press_bnd_pct", False, 0.5)]),
    "d3_chase":      (0.20, [("chase_sr", False, 0.5), ("chase_wpa100", False, 0.5)]),
    "d4_death":      (0.15, [("death_sr", False, 0.5), ("death_bnd_pct", False, 0.3), ("death_dot_pct", True, 0.2)]),
    "d5_value":      (0.20, [("rae100", False, 0.5), ("collapse_wpa100", False, 0.5)]),
}

# ─────────────────────────────────────────────────────────────
# BOWLER METRICS & SCORING
# ─────────────────────────────────────────────────────────────
def bowl_metrics(A, L):
    d = pd.DataFrame(index=A.index)
    d["balls"] = A["all_balls"]
    d["wkts"] = A["all_wkts"]
    d["econ"] = A["all_runs"] / A["all_balls"].clip(lower=1) * 6
    d["sr"] = A["all_balls"] / A["all_wkts"].clip(lower=1)
    d["matches_bowled"] = A["apps"]
    for s in ["press", "crunch", "death", "pp", "mid"]:
        d[f"{s}_balls"] = A[f"{s}_balls"]
    for s, k in [("press", "press"), ("crunch", "press"), ("death", "death"), ("pp", "phase"), ("mid", "phase")]:
        b = A[f"{s}_balls"]
        d[f"{s}_econ"] = shrink(A[f"{s}_runs"], b, L[f"{s}_runs"] / L[f"{s}_balls"], K[k]) * 6
        d[f"{s}_dot_pct"] = shrink(A[f"{s}_dots"], b, L[f"{s}_dots"] / L[f"{s}_balls"], K[k]) * 100
        d[f"{s}_wkt_rate"] = shrink(A[f"{s}_wkts"], b, L[f"{s}_wkts"] / L[f"{s}_balls"], K["wkt"]) * 24
        d[f"{s}_wpa100"] = shrink(A[f"{s}_wpa"], b, L[f"{s}_wpa"] / L[f"{s}_balls"], K[k]) * 100
    ab = A["all_balls"]
    d["all_wkt_rate"] = shrink(A["all_wkts"], ab, L["all_wkts"] / L["all_balls"], K["wkt"]) * 24
    d["all_dot_pct"] = shrink(A["all_dots"], ab, L["all_dots"] / L["all_balls"], K["all"]) * 100
    d["top_order_share"] = shrink(A["top_wkts"], A["all_wkts"], L["top_wkts"] / L["all_wkts"], K["share"]) * 100
    d["pb30_rate"] = shrink(A["pb30"], ab, L["pb30"] / L["all_balls"], K["pb"]) * 24
    d["rae_per_over"] = shrink(A["all_rae"], ab, L["all_rae"] / L["all_balls"], K["all"]) * 6
    return d


def bowl_table(A, L):
    d = bowl_metrics(A, L)
    keep = ((d["matches_bowled"] >= CFG["min_matches"]) &
            (d["balls"] >= CFG["bowl_min_balls"]) &
            (d["press_balls"] >= CFG["bowl_min_pressure_balls"]))
    d = d[keep].copy()
    ppr, mdr, dtr = d["pp_balls"] / d["balls"], d["mid_balls"] / d["balls"], d["death_balls"] / d["balls"]
    d["bowler_role"] = np.select([ppr >= 0.35, dtr >= 0.30, mdr >= 0.45],
                                 ["PP Specialist", "Death Specialist", "Middle Overs Specialist"],
                                 default="All-Phase Bowler")
    return d


BOWL_DIMS = {
    "d1_pressure":   (0.30, [("press_wpa100", False, 0.5), ("press_econ", True, 0.3), ("press_wkt_rate", False, 0.2)]),
    "d2_crunch":     (0.20, [("crunch_econ", True, 0.5), ("crunch_dot_pct", False, 0.3), ("crunch_wkt_rate", False, 0.2)]),
    "d3_death":      (0.15, [("death_econ", True, 0.6), ("death_dot_pct", False, 0.4)]),
    "d4_wickets":    (0.20, [("all_wkt_rate", False, 0.45), ("top_order_share", False, 0.30), ("pb30_rate", False, 0.25)]),
    "d5_prevention": (0.15, [("rae_per_over", True, 0.6), ("all_dot_pct", False, 0.4)]),
}

# ─────────────────────────────────────────────────────────────
# RUN: OVERALL RANKINGS
# ─────────────────────────────────────────────────────────────
L_bat = aggregate(bat_match).sum()
L_bowl = aggregate(bowl_match).sum()

bat_pool = bat_table(aggregate(bat_match), L_bat)
bowl_pool = bowl_table(aggregate(bowl_match), L_bowl)
print(f"\nEligible batters: {len(bat_pool)} | Eligible bowlers: {len(bowl_pool)}")

bat_scored = score_pool(bat_pool, BAT_DIMS)
bowl_scored = score_pool(bowl_pool, BOWL_DIMS)
for df in (bat_scored, bowl_scored):
    df.insert(0, "player_name", df.index.map(names))
    df.insert(0, "rank", range(1, len(df) + 1))

BAT_SHOW = ["rank", "player_name", "bat_role", "matches_in_xi", "balls", "sr", "press_sr", "press_wpa100",
            "press_dot_pct", "chase_sr", "death_sr", "rae100", "min_dim", "score"]
BOWL_SHOW = ["rank", "player_name", "bowler_role", "matches_bowled", "balls", "wkts", "econ", "press_econ",
             "press_wpa100", "death_econ", "crunch_econ", "rae_per_over", "min_dim", "score"]

pd.set_option("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.2f}".format)
print("\n--- TOP 10 BATTERS UNDER PRESSURE ---")
print(bat_scored[BAT_SHOW].head(10).to_string(index=False))
print("\n--- TOP 10 BOWLERS UNDER PRESSURE ---")
print(bowl_scored[BOWL_SHOW].head(10).to_string(index=False))

# ─────────────────────────────────────────────────────────────
# ROLE-BASED LISTS (scored within role, so percentiles are role-relative)
# ─────────────────────────────────────────────────────────────
role_lists = {}
for role, fname in [("Top Order", "toporder"), ("Middle Order", "middleorder"), ("Lower Order", "lowerorder")]:
    sub = bat_pool[bat_pool["bat_role"] == role]
    if len(sub) >= 8:
        sc = score_pool(sub, BAT_DIMS)
        sc.insert(0, "player_name", sc.index.map(names))
        sc.insert(0, "rank", range(1, len(sc) + 1))
        role_lists[f"top10_{fname}_batters"] = sc.head(10)

for ph, label in [("pp", "pp"), ("mid", "mid"), ("death", "death")]:
    sub = bowl_pool[bowl_pool[f"{ph}_balls"] >= CFG["phase_min_balls"][ph]].copy()
    if len(sub) >= 8:
        spec = {"phase": (1.0, [(f"{ph}_econ", True, 0.35), (f"{ph}_dot_pct", False, 0.20),
                                (f"{ph}_wkt_rate", False, 0.20), (f"{ph}_wpa100", False, 0.25)])}
        sc = score_pool(sub, spec, alpha=1.0)
        sc.insert(0, "player_name", sc.index.map(names))
        sc.insert(0, "rank", range(1, len(sc) + 1))
        role_lists[f"top10_{label}_bowlers"] = sc.head(10)

# ─────────────────────────────────────────────────────────────
# VALIDATION 1: SPLIT-HALF RELIABILITY
# ─────────────────────────────────────────────────────────────
def split_half(mdf, metric_fn, cols, pool_index, reps, seed):
    rng = np.random.default_rng(seed)
    ids = mdf["match_id"].unique()
    rs = {c: [] for c in cols}
    for _ in range(reps):
        perm = rng.permutation(ids)
        h1, h2 = perm[: len(ids) // 2], perm[len(ids) // 2:]
        m1 = metric_fn(aggregate(mdf, pd.Series(1, index=h1))).reindex(pool_index)
        m2 = metric_fn(aggregate(mdf, pd.Series(1, index=h2))).reindex(pool_index)
        for c in cols:
            rs[c].append(m1[c].corr(m2[c], method="spearman"))
    out = pd.DataFrame({"split_half_r": {c: np.nanmean(v) for c, v in rs.items()}})
    out["spearman_brown"] = 2 * out["split_half_r"] / (1 + out["split_half_r"])
    return out.sort_values("spearman_brown", ascending=False)


print("\nSplit-half reliability (Spearman-Brown corrected; < 0.3 = mostly noise)...")
bat_cols = sorted({c for _, items in BAT_DIMS.values() for c, _, _ in items})
bowl_cols = sorted({c for _, items in BOWL_DIMS.values() for c, _, _ in items})
rel_bat = split_half(bat_match, lambda A: bat_metrics(A, L_bat), bat_cols, bat_pool.index,
                     CFG["split_half_reps"], CFG["seed"])
rel_bowl = split_half(bowl_match, lambda A: bowl_metrics(A, L_bowl), bowl_cols, bowl_pool.index,
                      CFG["split_half_reps"], CFG["seed"])
print("\nBatter metrics:\n", rel_bat.to_string())
print("\nBowler metrics:\n", rel_bowl.to_string())

# ─────────────────────────────────────────────────────────────
# VALIDATION 2: BOOTSTRAP RANK STABILITY (resample matches)
# ─────────────────────────────────────────────────────────────
def stability(mdf, table_fn, spec, n, seed):
    rng = np.random.default_rng(seed)
    ids = mdf["match_id"].unique()
    ranks = {}
    for _ in range(n):
        counts = pd.Series(rng.choice(ids, size=len(ids), replace=True)).value_counts()
        t = table_fn(aggregate(mdf, counts))
        if len(t) < 10:
            continue
        for r, pid in enumerate(score_pool(t, spec).index, 1):
            ranks.setdefault(pid, []).append(r)
    rows = []
    for pid, rs in ranks.items():
        rs = np.array(rs)
        rows.append(dict(player_id=pid, player_name=names.get(pid), top10_freq=(rs <= 10).sum() / n,
                         mean_rank=rs.mean(), rank_p10=np.percentile(rs, 10), rank_p90=np.percentile(rs, 90)))
    return pd.DataFrame(rows).sort_values("top10_freq", ascending=False)


print(f"\nBootstrap stability ({CFG['bootstrap_n']} resamples of matches)...")
stab_bat = stability(bat_match, lambda A: bat_table(A, L_bat), BAT_DIMS, CFG["bootstrap_n"], CFG["seed"])
stab_bowl = stability(bowl_match, lambda A: bowl_table(A, L_bowl), BOWL_DIMS, CFG["bootstrap_n"], CFG["seed"])
print("\nBatters - share of resamples in top 10:\n", stab_bat.head(15).to_string(index=False))
print("\nBowlers - share of resamples in top 10:\n", stab_bowl.head(15).to_string(index=False))

# ─────────────────────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────────────────────
bat_scored.head(10).to_csv(os.path.join(OUT_DIR, "top10_overall_batters.csv"))
bowl_scored.head(10).to_csv(os.path.join(OUT_DIR, "top10_overall_bowlers.csv"))
bat_scored.to_csv(os.path.join(OUT_DIR, "full_eligible_batters.csv"))
bowl_scored.to_csv(os.path.join(OUT_DIR, "full_eligible_bowlers.csv"))
for name, df in role_lists.items():
    df.to_csv(os.path.join(OUT_DIR, f"{name}.csv"))
rel_bat.to_csv(os.path.join(OUT_DIR, "reliability_batters.csv"))
rel_bowl.to_csv(os.path.join(OUT_DIR, "reliability_bowlers.csv"))
stab_bat.to_csv(os.path.join(OUT_DIR, "stability_batters.csv"), index=False)
stab_bowl.to_csv(os.path.join(OUT_DIR, "stability_bowlers.csv"), index=False)

with open(os.path.join(OUT_DIR, "analysis_v6_summary.txt"), "w", encoding="utf-8") as f:
    f.write("=== T20 PRESSURE PERFORMANCE ANALYSIS v6 ===\n")
    f.write(f"Pressure = top {int((1 - CFG['lev_quantile']) * 100)}% leverage deliveries with win prob "
            f"between {CFG['contested_lo']} and {CFG['contested_hi']}\n")
    f.write(f"Eligible batters: {len(bat_scored)} | Eligible bowlers: {len(bowl_scored)}\n\n")
    f.write("TOP 10 BATTERS\n" + bat_scored[BAT_SHOW].head(10).to_string(index=False) + "\n\n")
    f.write("TOP 10 BOWLERS\n" + bowl_scored[BOWL_SHOW].head(10).to_string(index=False) + "\n\n")
    f.write("BATTER STABILITY (share of bootstrap resamples in top 10)\n" + stab_bat.head(15).to_string(index=False) + "\n\n")
    f.write("BOWLER STABILITY\n" + stab_bowl.head(15).to_string(index=False) + "\n")

print(f"\nDone. Outputs in {OUT_DIR}")