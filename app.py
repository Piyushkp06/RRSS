import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os

# ─────────────────────────────────────────────────────────────
# PAGE CONFIGURATION & RR THEME
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Rajasthan Royals | IPL 2027 Auction Pressure Dashboard",
    page_icon="🏏",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling (Rajasthan Royals Theme)
st.markdown("""
<style>
    .main { background-color: #0B0F19; }
    .stApp { background-color: #0B0F19; color: #F1F5F9; }
    
    /* Headers */
    h1, h2, h3 { color: #FFFFFF !important; font-family: 'Inter', sans-serif; }
    h1 { font-weight: 800; }
    
    /* Metric Cards */
    div[data-testid="stMetricValue"] {
        color: #E91E63 !important;
        font-weight: 800 !important;
    }
    
    /* Buttons */
    .stButton>button {
        background-color: #E91E63;
        color: white;
        border-radius: 8px;
        border: none;
        font-weight: 700;
        transition: all 0.3s;
    }
    .stButton>button:hover {
        background-color: #C2185B;
        color: white;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #141852;
        padding: 8px 12px;
        border-radius: 12px;
    }
    .stTabs [data-baseweb="tab"] {
        color: #94A3B8;
        font-weight: 600;
        border-radius: 8px;
        padding: 8px 16px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #E91E63 !important;
        color: white !important;
    }
    
    /* Custom Card */
    .rr-card {
        background-color: #1E293B;
        border-radius: 12px;
        padding: 16px;
        border: 1px solid #334155;
        margin-bottom: 12px;
    }
    .rr-card-highlight {
        background: linear-gradient(135deg, rgba(233, 30, 99, 0.15) 0%, rgba(20, 24, 82, 0.4) 100%);
        border: 1px solid #E91E63;
        border-radius: 12px;
        padding: 18px;
        margin-bottom: 12px;
    }
    .badge-pink {
        background-color: #E91E63;
        color: white;
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: bold;
    }
    .badge-blue {
        background-color: #2563EB;
        color: white;
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    base_path = os.path.dirname(os.path.abspath(__file__))
    res_dir = os.path.join(base_path, "results_v5_improved")
    if not os.path.exists(res_dir):
        res_dir = "results_v5_improved"
        
    bat_all = pd.read_csv(os.path.join(res_dir, "full_eligible_batters.csv"))
    bowl_all = pd.read_csv(os.path.join(res_dir, "full_eligible_bowlers.csv"))
    bat_top = pd.read_csv(os.path.join(res_dir, "top10_overall_batters.csv"))
    bowl_top = pd.read_csv(os.path.join(res_dir, "top10_overall_bowlers.csv"))
    return bat_all, bowl_all, bat_top, bowl_top

try:
    bat_all, bowl_all, bat_top, bowl_top = load_data()
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()

# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────
st.sidebar.image("https://upload.wikimedia.org/wikipedia/en/thumb/6/60/Rajasthan_Royals_Logo.svg/300px-Rajasthan_Royals_Logo.svg.png", width=110)
st.sidebar.title("SupeRR Selector S2")
st.sidebar.markdown("**IPL 2027 Auction Strategy Engine**")
st.sidebar.caption("T20 Pressure Index (v5 Improved)")

st.sidebar.markdown("---")
st.sidebar.subheader("Dataset Scope")
st.sidebar.markdown("""
- **Matches Evaluated**: 883
- **Deliveries Analyzed**: 200,961
- **Situational Window**: 12 Balls Post-Wkt
- **Min-Dimension Floor**: 20%
""")

st.sidebar.markdown("---")
st.sidebar.subheader("Download Reports")
methodology_pdf = "T20_Pressure_Performance_Methodology_Report.pdf"
pptx_file = "Rajasthan_Royals_IPL_2027_Auction_Strategy.pptx"
pdf_file = "Rajasthan_Royals_IPL_2027_Auction_Strategy.pdf"

if os.path.exists(methodology_pdf):
    with open(methodology_pdf, "rb") as f:
        st.sidebar.download_button(
            label="📑 Download Technical Methodology Report (.pdf)",
            data=f,
            file_name=methodology_pdf,
            mime="application/pdf"
        )

if os.path.exists(pptx_file):
    with open(pptx_file, "rb") as f:
        st.sidebar.download_button(
            label="📊 Download PowerPoint Deck (.pptx)",
            data=f,
            file_name=pptx_file,
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )

if os.path.exists(pdf_file):
    with open(pdf_file, "rb") as f:
        st.sidebar.download_button(
            label="📄 Download Executive Dossier (.pdf)",
            data=f,
            file_name=pdf_file,
            mime="application/pdf"
        )

# ─────────────────────────────────────────────────────────────
# TOP BANNER
# ─────────────────────────────────────────────────────────────
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("Rajasthan Royals — IPL 2027 Auction Strategy")
    st.markdown("##### *Identifying Most Reliable Players Under Pressure via Multi-Gate Gating & Situational Analytics*")

with col_h2:
    st.markdown("""
    <div style="background-color: #141852; border: 1px solid #E91E63; padding: 10px; border-radius: 10px; text-align: center;">
        <span style="color: #FFC107; font-weight: bold; font-size: 13px;">PURSE BUDGET</span><br>
        <span style="color: #FFFFFF; font-size: 20px; font-weight: 800;">₹120.0 Crore</span>
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab_ppt, tab4 = st.tabs([
    "🏏 Batting Pressure Leaderboard",
    "🎯 Bowling Pressure Leaderboard",
    "👑 Rajasthan Royals Auction Blueprint",
    "📊 PPT Slide Deck Preview",
    "📐 Methodology & Multi-Gate Cutoffs"
])

# =============================================================
# TAB 1: BATTING
# =============================================================
with tab1:
    st.subheader("Top Performers Under Batting Pressure")
    st.caption("Gated simultaneously by 8 cutoffs: Base SR ≥ 145, Death SR ≥ 170, Chase SR ≥ 135, Post-Wkt (12b) Tracking, and Dot % ≤ 40%.")

    # Filters
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        role_filter = st.selectbox("Filter by Batting Role:", ["All Roles", "Top Order", "Middle Order", "Lower Order"])
    with col_f2:
        min_runs = st.slider("Minimum Total Runs:", 600, 3500, 600, step=100)
    with col_f3:
        min_score = st.slider("Minimum Pressure Score:", 30.0, 65.0, 40.0, step=2.5)

    df_b_view = bat_all.copy()
    if role_filter != "All Roles":
        df_b_view = df_b_view[df_b_view['bat_role'] == role_filter]
    df_b_view = df_b_view[(df_b_view['total_runs'] >= min_runs) & (df_b_view['balanced_pressure_score'] >= min_score)]

    # Metrics Overview Cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Top Ranked Batter", f"{bat_top.iloc[0]['player_name']}", f"Score: {bat_top.iloc[0]['balanced_pressure_score']:.1f}")
    with c2:
        st.metric("Highest Death SR", f"{bat_all.sort_values('death_sr', ascending=False).iloc[0]['player_name']}", f"{bat_all['death_sr'].max():.1f} SR")
    with c3:
        st.metric("Best Post-Wicket SR", f"{bat_all.sort_values('post_wkt_sr', ascending=False).iloc[0]['player_name']}", f"{bat_all['post_wkt_sr'].max():.1f} SR")
    with c4:
        st.metric("Qualified Pool Size", f"{len(df_b_view)} Batters", "Passed All Floors")

    # Interactive Table
    show_cols_bat = [
        'player_name', 'bat_role', 'matches_in_xi', 'total_runs',
        'baseline_sr', 'death_sr', 'chase_sr', 'post_wkt_sr',
        'pressure_dot_pct', 'dim_min', 'balanced_pressure_score'
    ]
    st.dataframe(
        df_b_view[show_cols_bat].rename(columns={
            'player_name': 'Player',
            'bat_role': 'Role',
            'matches_in_xi': 'Matches',
            'total_runs': 'Runs',
            'baseline_sr': 'Base SR',
            'death_sr': 'Death SR',
            'chase_sr': 'Chase SR',
            'post_wkt_sr': 'Post-Wkt SR (12b)',
            'pressure_dot_pct': 'Press Dot %',
            'dim_min': 'Min Dim',
            'balanced_pressure_score': 'Pressure Score'
        }).style.format({
            'Base SR': '{:.1f}', 'Death SR': '{:.1f}', 'Chase SR': '{:.1f}',
            'Post-Wkt SR (12b)': '{:.1f}', 'Press Dot %': '{:.1f}%',
            'Min Dim': '{:.1f}', 'Pressure Score': '{:.1f}'
        }),
        use_container_width=True,
        height=320
    )

    # Plotly Scatter: Chase SR vs Death SR
    st.markdown("#### ⚡ Chase Mastery vs Death Overs Execution")
    fig_bat = px.scatter(
        df_b_view,
        x="chase_sr",
        y="death_sr",
        size="balanced_pressure_score",
        color="bat_role",
        hover_name="player_name",
        text="player_name",
        labels={"chase_sr": "Run Chase Strike Rate", "death_sr": "Death Overs (16-20) Strike Rate", "bat_role": "Role"},
        color_discrete_map={"Top Order": "#3B82F6", "Middle Order": "#EC4899", "Lower Order": "#10B981"}
    )
    fig_bat.update_traces(textposition='top center', textfont_size=10)
    fig_bat.update_layout(
        plot_bgcolor="#0B0F19",
        paper_bgcolor="#1E293B",
        font_color="#E2E8F0",
        height=500
    )
    st.plotly_chart(fig_bat, use_container_width=True)

    # Head-to-Head Radar Comparison
    st.markdown("#### 🆚 Batter Head-to-Head Radar Comparison")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        p1 = st.selectbox("Select Batter 1:", bat_all['player_name'].tolist(), index=0)
    with col_p2:
        p2 = st.selectbox("Select Batter 2:", bat_all['player_name'].tolist(), index=1)

    r1 = bat_all[bat_all['player_name'] == p1].iloc[0]
    r2 = bat_all[bat_all['player_name'] == p2].iloc[0]

    categories = ['Chase Mastery', 'Death Overs', 'Post-Wkt Crisis', 'Strike Rotation', 'Baseline Quality']
    fig_radar_b = go.Figure()
    fig_radar_b.add_trace(go.Scatterpolar(
        r=[r1['dim1_chase'], r1['dim2_death'], r1['dim3_crisis'], r1['dim4_strike_rot'], r1['dim5_quality']],
        theta=categories,
        fill='toself',
        name=p1,
        line_color='#E91E63'
    ))
    fig_radar_b.add_trace(go.Scatterpolar(
        r=[r2['dim1_chase'], r2['dim2_death'], r2['dim3_crisis'], r2['dim4_strike_rot'], r2['dim5_quality']],
        theta=categories,
        fill='toself',
        name=p2,
        line_color='#3B82F6'
    ))
    fig_radar_b.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], color="#94A3B8"),
            bgcolor="#1E293B"
        ),
        paper_bgcolor="#1E293B",
        font_color="#E2E8F0",
        height=400
    )
    st.plotly_chart(fig_radar_b, use_container_width=True)

# =============================================================
# TAB 2: BOWLING
# =============================================================
with tab2:
    st.subheader("Top Performers Under Bowling Pressure")
    st.caption("Gated simultaneously by 9 cutoffs: Econ ≤ 8.80, Death Econ ≤ 9.75, Crunch Overs (1,6,18,19,20) Econ ≤ 9.20, and Wkts ≥ 50.")

    col_bf1, col_bf2, col_bf3 = st.columns(3)
    with col_bf1:
        bowl_role_filter = st.selectbox("Filter by Bowling Role:", ["All Roles", "PP Specialist", "Middle Overs Specialist", "Death Specialist"])
    with col_bf2:
        min_wkts = st.slider("Minimum Career Wickets:", 50, 180, 50, step=10)
    with col_bf3:
        max_death_econ = st.slider("Maximum Death Economy Ceiling:", 7.0, 9.75, 9.5, step=0.25)

    df_bw_view = bowl_all.copy()
    if bowl_role_filter != "All Roles":
        df_bw_view = df_bw_view[df_bw_view['bowler_role'] == bowl_role_filter]
    df_bw_view = df_bw_view[(df_bw_view['total_wickets'] >= min_wkts) & (df_bw_view['death_econ'] <= max_death_econ)]

    # Metrics Overview Cards
    cb1, cb2, cb3, cb4 = st.columns(4)
    with cb1:
        st.metric("Top Ranked Bowler", f"{bowl_top.iloc[0]['player_name']}", f"Score: {bowl_top.iloc[0]['balanced_pressure_score']:.1f}")
    with cb2:
        st.metric("Lowest Death Economy", f"{bowl_all.sort_values('death_econ').iloc[0]['player_name']}", f"{bowl_all['death_econ'].min():.2f} RPO")
    with cb3:
        st.metric("Best Post-Wkt Econ", f"{bowl_all.sort_values('post_wkt_econ').iloc[0]['player_name']}", f"{bowl_all['post_wkt_econ'].min():.2f} RPO")
    with cb4:
        st.metric("Qualified Pool Size", f"{len(df_bw_view)} Bowlers", "Passed All Floors")

    # Interactive Table
    show_cols_bowl = [
        'player_name', 'bowler_role', 'matches_in_xi', 'total_wickets',
        'baseline_econ', 'death_econ', 'hl_econ', 'post_wkt_econ',
        'pressure_dot_pct', 'dim_min', 'balanced_pressure_score'
    ]
    st.dataframe(
        df_bw_view[show_cols_bowl].rename(columns={
            'player_name': 'Player',
            'bowler_role': 'Primary Role',
            'matches_in_xi': 'Matches',
            'total_wickets': 'Wickets',
            'baseline_econ': 'Base Econ',
            'death_econ': 'Death Econ',
            'hl_econ': 'Crunch Econ (1,6,18-20)',
            'post_wkt_econ': 'Post-Wkt Econ (12b)',
            'pressure_dot_pct': 'Press Dot %',
            'dim_min': 'Min Dim',
            'balanced_pressure_score': 'Pressure Score'
        }).style.format({
            'Base Econ': '{:.2f}', 'Death Econ': '{:.2f}', 'Crunch Econ (1,6,18-20)': '{:.2f}',
            'Post-Wkt Econ (12b)': '{:.2f}', 'Press Dot %': '{:.1f}%',
            'Min Dim': '{:.1f}', 'Pressure Score': '{:.1f}'
        }),
        use_container_width=True,
        height=320
    )

    # Scatter: Crunch Econ vs Death Econ
    st.markdown("#### 🔒 Crunch Overs (1,6,18,19,20) vs Death Overs Economy")
    fig_bowl = px.scatter(
        df_bw_view,
        x="hl_econ",
        y="death_econ",
        size="total_wickets",
        color="bowler_role",
        hover_name="player_name",
        text="player_name",
        labels={"hl_econ": "Crunch Overs (1,6,18,19,20) Economy", "death_econ": "Death Overs Economy", "bowler_role": "Role"}
    )
    fig_bowl.update_traces(textposition='top center', textfont_size=10)
    fig_bowl.update_layout(
        plot_bgcolor="#0B0F19",
        paper_bgcolor="#1E293B",
        font_color="#E2E8F0",
        height=500,
        xaxis=dict(autorange="reversed"),
        yaxis=dict(autorange="reversed")
    )
    st.plotly_chart(fig_bowl, use_container_width=True)

    # Head-to-Head Radar Comparison
    st.markdown("#### 🆚 Bowler Head-to-Head Radar Comparison")
    col_bw1, col_bw2 = st.columns(2)
    with col_bw1:
        bw1 = st.selectbox("Select Bowler 1:", bowl_all['player_name'].tolist(), index=0)
    with col_bw2:
        bw2 = st.selectbox("Select Bowler 2:", bowl_all['player_name'].tolist(), index=1)

    rb1 = bowl_all[bowl_all['player_name'] == bw1].iloc[0]
    rb2 = bowl_all[bowl_all['player_name'] == bw2].iloc[0]

    b_categories = ['Crunch Overs', 'Death Control', 'Breakthrough Cap', 'Wicket Quality', 'Low Total Defense']
    fig_radar_bw = go.Figure()
    fig_radar_bw.add_trace(go.Scatterpolar(
        r=[rb1['dim1_crunch'], rb1['dim2_death'], rb1['dim3_breakthrough'], rb1['dim4_quality'], rb1['dim5_discipline']],
        theta=b_categories,
        fill='toself',
        name=bw1,
        line_color='#10B981'
    ))
    fig_radar_bw.add_trace(go.Scatterpolar(
        r=[rb2['dim1_crunch'], rb2['dim2_death'], rb2['dim3_breakthrough'], rb2['dim4_quality'], rb2['dim5_discipline']],
        theta=b_categories,
        fill='toself',
        name=bw2,
        line_color='#F59E0B'
    ))
    fig_radar_bw.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], color="#94A3B8"),
            bgcolor="#1E293B"
        ),
        paper_bgcolor="#1E293B",
        font_color="#E2E8F0",
        height=400
    )
    st.plotly_chart(fig_radar_bw, use_container_width=True)

# =============================================================
# TAB 3: RAJASTHAN ROYALS STRATEGY
# =============================================================
with tab3:
    st.subheader("Rajasthan Royals — IPL 2027 Auction Target Strategy")
    st.markdown("""
    Rajasthan Royals has historically fielded world-class top-order anchors (Sanju Samson, Jos Buttler, Yashasvi Jaiswal) and opening swing (Trent Boult).
    However, **knockout eliminations were driven by two chronic vulnerabilities**:
    1. **Death Overs Run Leakage (Overs 18–20)**: Conceding > 11.5 RPO in close playoff games.
    2. **Post-Wicket Chase Freeze**: Scoring rate dropping by 2.4 RPO in the 2 overs after an early top-order wicket.
    """)

    # Regulatory compliance callout
    st.info("⚠️ **BCCI & IPL Regulatory Compliance Notice:** Under BCCI regulations and bilateral sporting guidelines, Pakistani players are ineligible for participation in the IPL auction. While Mohammad Nawaz (#1) and Shaheen Afridi (#4) feature in the global technical T20 pressure rankings, Rajasthan Royals' auction targets are strictly selected from eligible Indian domestic and overseas pools.")

    # Target Cards
    st.markdown("### 🎯 Key Auction Acquisition Targets (IPL-Eligible)")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown("""
        <div class="rr-card-highlight">
            <span class="badge-pink">PRIMARY BATTING TARGET #1</span>
            <h4 style="color:white; margin-top:8px; margin-bottom:4px;">Phil Salt (WK / Opener) — Score: 60.1</h4>
            <p style="font-size:12px; color:#CBD5E1; margin-bottom:8px;">
                <b>The Solution:</b> Completely eliminates powerplay stagnation. Boasts an astonishing <b>170.4 SR in the 12 balls immediately following a partner's dismissal</b> and a 171.2 Chase SR.
            </p>
            <div style="font-size:12px; color:#FFC107; font-weight:bold;">Projected Auction Valuation: ₹22.0 Cr</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="rr-card">
            <span class="badge-pink">DOMESTIC FINISHER TARGET #2</span>
            <h4 style="color:white; margin-top:8px; margin-bottom:4px;">Shashank Singh (Lower Order) — Score: 55.7</h4>
            <p style="font-size:12px; color:#CBD5E1; margin-bottom:8px;">
                <b>The Solution:</b> Fills RR's domestic finishing hole. Elite <b>195.4 Death SR</b> with a stellar 27.2% pressure dot-ball rate, ensuring RR never wastes deliveries at the death.
            </p>
            <div style="font-size:12px; color:#FFC107; font-weight:bold;">Projected Auction Valuation: ₹14.0 Cr</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="rr-card">
            <span class="badge-pink">OVERSEAS FINISHER TARGET #3</span>
            <h4 style="color:white; margin-top:8px; margin-bottom:4px;">Tim David (#6-7 Finisher) — Score: 55.3</h4>
            <p style="font-size:12px; color:#CBD5E1; margin-bottom:8px;">
                <b>The Solution:</b> The ultimate death overs weapon. <b>199.8 Death SR</b>, 182.2 Chase SR, and exceptional tail-end strike farming (164.5 Post-Wicket SR).
            </p>
            <div style="font-size:12px; color:#FFC107; font-weight:bold;">Projected Auction Valuation: ₹18.0 Cr</div>
        </div>
        """, unsafe_allow_html=True)

    with col_t2:
        st.markdown("""
        <div class="rr-card-highlight">
            <span class="badge-blue">PRIMARY BOWLING TARGET #1 (SPIN)</span>
            <h4 style="color:white; margin-top:8px; margin-bottom:4px;">Varun Chakravarthy (Mystery Spin) — Score: 61.1</h4>
            <p style="font-size:12px; color:#CBD5E1; margin-bottom:8px;">
                <b>The Solution:</b> 136 career wickets with a <b>7.30 crunch-overs economy</b> and 6.68 post-wicket economy. The proven stand-breaker RR needs to dismantle opposition middle-overs partnerships.
            </p>
            <div style="font-size:12px; color:#FFC107; font-weight:bold;">Projected Auction Valuation: ₹18.0 Cr</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="rr-card">
            <span class="badge-blue">PRIMARY BOWLING TARGET #2 (DEATH PACE)</span>
            <h4 style="color:white; margin-top:8px; margin-bottom:4px;">Matheesha Pathirana (Death Slinger) — Score: 51.8</h4>
            <p style="font-size:12px; color:#CBD5E1; margin-bottom:8px;">
                <b>The Solution:</b> Takes over overs 18 & 20. 85 career wickets with an <b>8.17 Death Economy</b> and 41.8% dot ball rate makes boundary hitting nearly impossible under high RRR.
            </p>
            <div style="font-size:12px; color:#FFC107; font-weight:bold;">Projected Auction Valuation: ₹28.0 Cr</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="rr-card">
            <span class="badge-blue">TACTICAL ALL-ROUNDER / PACE TARGET #3</span>
            <h4 style="color:white; margin-top:8px; margin-bottom:4px;">Taskin Ahmed / Axar Patel — Score: 57.3 / 48.1</h4>
            <p style="font-size:12px; color:#CBD5E1; margin-bottom:8px;">
                <b>The Solution:</b> Taskin provides ferocious powerplay pace (7.30 crunch econ, 6.57 post-wkt econ); Axar offers elite middle-phase containment (6.61 post-wkt econ) + batting depth.
            </p>
            <div style="font-size:12px; color:#FFC107; font-weight:bold;">Projected Auction Valuation: ₹12.0 Cr - ₹14.0 Cr</div>
        </div>
        """, unsafe_allow_html=True)

    # Purse Allocation Donut Chart
    st.markdown("### 💰 Recommended Auction Purse Deployment (₹120.0 Cr)")
    purse_df = pd.DataFrame([
        {"Category": "Death Finishers (#6-7)", "Target": "Tim David / Shashank Singh", "Amount_Cr": 32.0, "Share": "26.7%"},
        {"Category": "Death Yorker Pace (#18, 20)", "Target": "Matheesha Pathirana", "Amount_Cr": 28.0, "Share": "23.3%"},
        {"Category": "Explosive WK Opener", "Target": "Phil Salt", "Amount_Cr": 22.0, "Share": "18.3%"},
        {"Category": "Mystery Middle Spinner", "Target": "Varun Chakravarthy", "Amount_Cr": 18.0, "Share": "15.0%"},
        {"Category": "Tactical Bench & Depth", "Target": "Sai Sudharsan, Naman Dhir, Pace backups", "Amount_Cr": 20.0, "Share": "16.7%"}
    ])

    fig_purse = px.pie(
        purse_df,
        values="Amount_Cr",
        names="Category",
        color="Category",
        hole=0.45,
        color_discrete_sequence=["#E91E63", "#3B82F6", "#F59E0B", "#10B981", "#8B5CF6"]
    )
    fig_purse.update_layout(paper_bgcolor="#1E293B", font_color="#E2E8F0", height=380)
    st.plotly_chart(fig_purse, use_container_width=True)

    # Projected Starting XI
    st.markdown("### 🏆 Projected Blueprint Starting XI for IPL 2027")
    xi_data = [
        {"Bat Pos": "1", "Player": "Yashasvi Jaiswal", "Type": "Retained", "Role": "Aggressive LH Opener"},
        {"Bat Pos": "2", "Player": "Phil Salt (WK)", "Type": "Target [₹22 Cr]", "Role": "High Post-Wkt SR Powerplay Enforcer"},
        {"Bat Pos": "3", "Player": "Sanju Samson (C)", "Type": "Retained", "Role": "Anchor & Momentum Accelerator"},
        {"Bat Pos": "4", "Player": "Heinrich Klaasen", "Type": "Target [₹18 Cr]", "Role": "Middle-Overs Spin Destroyer"},
        {"Bat Pos": "5", "Player": "Riyan Parag", "Type": "Retained", "Role": "Middle-Overs Aggressor"},
        {"Bat Pos": "6", "Player": "Shashank Singh", "Type": "Target [₹14 Cr]", "Role": "Domestic Clutch Death Finisher"},
        {"Bat Pos": "7", "Player": "Tim David", "Type": "Target [₹18 Cr]", "Role": "Overseas Death Destroyer"},
        {"Bat Pos": "8", "Player": "Ravichandran Ashwin / Axar Patel", "Type": "Retained/Target", "Role": "Spin All-Rounder"},
        {"Bat Pos": "9", "Player": "Varun Chakravarthy", "Type": "Target [₹18 Cr]", "Role": "Mystery Wicket-Taker"},
        {"Bat Pos": "10", "Player": "Trent Boult", "Type": "Retained", "Role": "Powerplay Swing Specialist"},
        {"Bat Pos": "11", "Player": "Matheesha Pathirana", "Type": "Target [₹28 Cr]", "Role": "Death Yorker Slinger"},
    ]
    st.table(pd.DataFrame(xi_data))

# =============================================================
# TAB: POWERPOINT DECK PREVIEW (10 SLIDES)
# =============================================================
with tab_ppt:
    st.subheader("📊 Executive Presentation Deck — Rajasthan Royals IPL 2027 Auction Strategy")
    st.caption("10-Slide 16:9 Presentation Deck built for Rajasthan Royals Executive Leadership & Auction Table.")

    slides = [
        {
            "num": "Slide 1",
            "title": "Title & Executive Strategy Brief",
            "tag": "EXECUTIVE COVER",
            "desc": "Rajasthan Royals IPL 2027 Auction Strategy: Quantifying T20 Pressure Reliability. Presentation by Analytics Division."
        },
        {
            "num": "Slide 2",
            "title": "Executive Summary & The Rajasthan Royals Imperative",
            "tag": "STRATEGIC IMPERATIVE",
            "desc": "Analysis of RR playoff eliminations. Core problem: Death run leakage (>11.5 RPO in overs 18-20) and Post-Wicket Chase Freeze (-2.4 RPO in the 2 overs post-dismissal). Target: Deploying ₹120 Cr purse on proven high-pressure anchors and execution specialists."
        },
        {
            "num": "Slide 3",
            "title": "BCCI & IPL Regulatory Compliance Notice",
            "tag": "REGULATORY MANDATE",
            "desc": "Formal clarification of IPL auction eligibility: Pakistani players (Nawaz, Afridi) rank high in pure global analytics but cannot participate in the IPL auction under BCCI policy. Rajasthan Royals auction strategy strictly targets eligible Indian domestic and overseas pools."
        },
        {
            "num": "Slide 4",
            "title": "Technical Methodology & Multi-Gate Gating Architecture",
            "tag": "DATA SCIENCE",
            "desc": "883 matches, 200,961 balls evaluated. 5 situational dimensions per discipline, 12-ball post-wicket shockwave tracking, and min-dimension floors (dim_min ≥ 20%) eliminating one-dimensional specialists."
        },
        {
            "num": "Slide 5",
            "title": "Definitive Top 10 Batters Under Pressure (Dropdown Selections)",
            "tag": "GLOBAL RANKINGS",
            "desc": "Unstop dropdown selections: #1 Phil Salt (Score 60.1), #2 Shashank Singh (55.7), #3 Tim David (55.3), #4 Sai Sudharsan (53.4), #5 Heinrich Klaasen (52.5), #6 Suryakumar Yadav (52.2), #7 Shreyas Iyer (49.7), #8 Naman Dhir (49.2), #9 Jos Buttler (47.9), #10 Tristan Stubbs (47.4)."
        },
        {
            "num": "Slide 6",
            "title": "Definitive Top 10 Bowlers Under Pressure (Dropdown Selections)",
            "tag": "GLOBAL RANKINGS",
            "desc": "Unstop dropdown selections: #1 Mohammad Nawaz (Score 65.3), #2 Varun Chakravarthy (61.1), #3 Jasprit Bumrah (59.7), #4 Shaheen Afridi (59.3), #5 Taskin Ahmed (57.3), #6 Akeal Hosein (54.3), #7 Matheesha Pathirana (51.8), #8 Maheesh Theekshana (50.7), #9 Noor Ahmad (50.4), #10 Axar Patel (48.1)."
        },
        {
            "num": "Slide 7",
            "title": "RR Priority Batting Targets: Eliminating Powerplay & Death Freezes",
            "tag": "AUCTION TARGETING",
            "desc": "Target #1: Phil Salt (₹22 Cr, 170.4 post-wkt SR, 209.6 death SR); Target #2: Shashank Singh (₹14 Cr, 195.4 death SR, 27.2% dot %); Target #3: Tim David (₹18 Cr, 199.8 death SR, 182.2 chase SR)."
        },
        {
            "num": "Slide 8",
            "title": "RR Priority Bowling Targets: Locking Down Middle & Death Overs",
            "tag": "AUCTION TARGETING",
            "desc": "Target #1: Varun Chakravarthy (₹18 Cr, 7.30 crunch econ, 6.68 post-wkt econ, 136 wkts); Target #2: Matheesha Pathirana (₹28 Cr, 8.17 death econ, 41.8% dot ball rate); Target #3: Taskin Ahmed / Axar Patel (₹12-14 Cr, Powerplay pace & spin containment)."
        },
        {
            "num": "Slide 9",
            "title": "Financial Engineering & ₹120.0 Crore Purse Allocation",
            "tag": "FINANCIAL STRATEGY",
            "desc": "Strategic allocation: ₹32 Cr (26.7%) Death Finishers, ₹28 Cr (23.3%) Death Yorker Pace, ₹22 Cr (18.3%) Explosive WK Opener, ₹18 Cr (15.0%) Mystery Spin, ₹20 Cr (16.7%) Tactical Squad Depth."
        },
        {
            "num": "Slide 10",
            "title": "Blueprint IPL 2027 Starting XI & Championship Impact",
            "tag": "TACTICAL EXECUTION",
            "desc": "Starting XI featuring Jaiswal, Salt (WK), Samson (C), Klaasen, Parag, Shashank, Tim David, Axar Patel, Varun Chakravarthy, Boult, Pathirana. Eliminates collapse vulnerability and guarantees sub-8.5 RPO at the death."
        }
    ]

    col_sl_sel, col_sl_dl = st.columns([3, 1])
    with col_sl_sel:
        st.markdown("#### 📑 Slide Navigator")
    with col_sl_dl:
        if os.path.exists("Rajasthan_Royals_IPL_2027_Auction_Strategy.pptx"):
            with open("Rajasthan_Royals_IPL_2027_Auction_Strategy.pptx", "rb") as f:
                st.download_button(
                    label="📥 Download Full PPTX Deck",
                    data=f,
                    file_name="Rajasthan_Royals_IPL_2027_Auction_Strategy.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    use_container_width=True
                )

    for s in slides:
        with st.expander(f"**{s['num']}: {s['title']}** [{s['tag']}]", expanded=(s['num'] in ['Slide 2', 'Slide 3', 'Slide 7', 'Slide 8'])):
            st.markdown(f"**Tag:** `{s['tag']}`")
            st.markdown(f"**Content Summary:** {s['desc']}")

# =============================================================
# TAB 4: METHODOLOGY & AUDIT
# =============================================================
with tab4:
    st.subheader("Methodology, Bug Audit & Multi-Gate Cutoffs")
    st.markdown("""
    #### 🛠️ Audit Findings & Bugs Corrected vs Original v5
    1. **Striker Dismissal Isolation**:
       * *Original Bug*: Grouped by striker and summed `is_wicket`, which unfairly penalized the striker when the **non-striker** was run out (275 occurrences in dataset).
       * *Correction*: Dismissals now strictly enforce `dismissed_player_id == striker_id`.
    2. **Pre-Delivery vs Post-Delivery State Tracking**:
       * *Original Bug*: Evaluated required run rate and runs needed *after* the ball's outcome was counted.
       * *Correction*: All pressure variables are computed strictly prior to ball release.
    3. **Elimination of Look-Ahead Bias**:
       * *Original Bug*: Used `match_rpo < 7.5` across all 40 overs on Ball 1 of Inning 1.
       * *Correction*: Completely replaced by live in-play conditions (target size, cluster shockwaves).
    4. **Overstep & Wide Separation**:
       * *Original Bug*: Only excluded wides, counting no-balls as legal balls in the 120-ball over limit.
       * *Correction*: Correctly excluded both wides and no-balls from legal delivery counters.
    5. **Super Overs Exclusion**:
       * *Original Bug*: Merged innings 3 & 4 into 20-over rate statistics.
       * *Correction*: Restricted strictly to pure T20 innings 1 & 2.
    """)

    st.markdown("---")
    st.markdown("""
    #### 📐 Multi-Gate Cutoff Floors Table
    | Discipline | Metric | Hard Cutoff Floor | Rationale |
    | :--- | :--- | :--- | :--- |
    | **Batting** | Playing XI Matches | **$\ge 40$ Matches** | Eliminates small-sample variance. |
    | **Batting** | Total Runs | **$\ge 600$ Runs** | Mandates established volume. |
    | **Batting** | Batting Order | **$\le 7.5$** | Eliminates tail-enders with inflated rates. |
    | **Batting** | Baseline Average | **$\ge 26.0$** | Eliminates fragile boom-or-bust hitters. |
    | **Batting** | Baseline Strike Rate | **$\ge 145.0$** | Eliminates slow modern T20 anchors. |
    | **Batting** | Death Overs Strike Rate | **$\ge 170.0$** (min 20b) | Mandates proven finishing ability. |
    | **Batting** | Run Chase Strike Rate | **$\ge 135.0$** | Eliminates chase crawlers. |
    | **Batting** | Pressure Dot Ball % | **$\le 40.0\%$** | Eliminates strike stagnators. |
    | **Bowling** | Playing XI Matches | **$\ge 40$ Matches** | Established workload requirement. |
    | **Bowling** | Career Wickets | **$\ge 50$ Wickets** | Proven wicket-taking threat. |
    | **Bowling** | Balls Bowled | **$\ge 500$ Balls** | Significant match involvement. |
    | **Bowling** | Baseline Economy | **$\le 8.80$ RPO** | Eliminates run-leakers. |
    | **Bowling** | Death Overs Economy | **$\le 9.75$ RPO** | Strict death containment ceiling. |
    | **Bowling** | Crunch Overs (1,6,18-20) Econ | **$\le 9.20$ RPO** | Essential clutch over discipline. |
    | **Bowling** | Bowling Strike Rate | **$\le 24.0$ Balls/Wkt** | Takes at least one wicket per 4 overs. |
    | **Bowling** | Pressure Dot Ball % | **$\ge 30.0\%$** | Choke pressure generation. |
    """)

# Footer
st.markdown("---")
st.caption("SupeRR Selector Season 2 • Rajasthan Royals IPL 2027 Auction Strategy • Developed with Streamlit & Plotly")
