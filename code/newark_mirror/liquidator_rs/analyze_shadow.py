import pandas as pd
import json
import glob
import os
import sys
from datetime import datetime

# --- CONFIGURATION ---
THRESHOLDS = {
    "GO": {"freq": 10, "p95_profit": 2.0, "exec_prob": 0.01},
    "ABANDON": {"p95_profit": 0.50, "exec_prob": 0.001}
}

def get_session(hour):
    if 0 <= hour < 8: return "Asia"
    if 8 <= hour < 16: return "EU"
    return "US"

def analyze(files):
    data = []
    for file in files:
        with open(file, 'r') as f:
            for line in f:
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    df = pd.DataFrame(data)
    if df.empty:
        print("No data found in JSONL files.")
        return

    # Filter out missing-data records (outliers)
    clean_df = df[df['stale_due_to_missing_ticks'] == False].copy()
    stale_count = len(df) - len(clean_df)

    # R29 Q6 — Circuit Breaker outlier filter
    if 'is_outlier' in clean_df.columns:
        before = len(clean_df)
        clean_df = clean_df[clean_df['is_outlier'] == False].copy()
        outlier_count = before - len(clean_df)
    else:
        outlier_count = 0

    # Pre-processing
    clean_df['timestamp'] = pd.to_datetime(clean_df['timestamp'])
    clean_df['hour'] = clean_df['timestamp'].dt.hour
    clean_df['session'] = clean_df['hour'].apply(get_session)

    # Amount Buckets
    bins = [0, 10, 100, 1000, float('inf')]
    labels = ['<10', '10-100', '100-1k', '1k+']
    clean_df['amount_bucket'] = pd.cut(clean_df['amount_in_usd'], bins=bins, labels=labels)

    # --- KPI CALCULATIONS ---
    # 1. Opportunity Frequency (per hour)
    total_hours = (clean_df['timestamp'].max() - clean_df['timestamp'].min()).total_seconds() / 3600
    freq = len(clean_df) / total_hours if total_hours > 0 else 0

    # 2. P95 Profit
    p95_profit = clean_df['amount_in_usd'].quantile(0.95) if 'amount_in_usd' in clean_df else 0

    # 3. Execution Probability (would_send == true)
    exec_prob = clean_df['would_send'].mean() if 'would_send' in clean_df else 0

    # 4. Latency
    p50_lat = clean_df['latency_ms'].quantile(0.50)
    p95_lat = clean_df['latency_ms'].quantile(0.95)

    print("\n" + "="*40)
    print(f"SHADOW RUN ANALYSIS - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*40)
    print(f"Total Records: {len(df)} (Stale: {stale_count}, Outlier: {outlier_count})")
    print(f"Freq: {freq:.2f} opps/h")
    print(f"P95 Profit: ${p95_profit:.4f}")
    print(f"Exec Prob: {exec_prob*100:.2f}%")
    print(f"Latency: P50={p50_lat:.2f}ms, P95={p95_lat:.2f}ms")
    print("-"*40)

    # VERDICT
    if freq > THRESHOLDS['GO']['freq'] and p95_profit > THRESHOLDS['GO']['p95_profit'] and exec_prob > THRESHOLDS['GO']['exec_prob']:
        verdict = "GO_PHASE_3"
    elif p95_profit < THRESHOLDS['ABANDON']['p95_profit'] or exec_prob < THRESHOLDS['ABANDON']['exec_prob']:
        verdict = "ABANDON"
    else:
        verdict = "NEED_MORE_DATA"

    print(f"VERDICT: {verdict}")
    print("="*40 + "\n")

    # ===== R36 Q4 Green Light KPIs (5 checks, ALL must pass for first probe LIVE) =====
    print("GREEN LIGHT CHECKLIST (R36 Q4 — all 5 must pass):")
    print("-"*40)
    green = {}

    # KPI 1: Profitability ratio (only over would_send=true rows) >= 2.0
    sent = clean_df[clean_df['would_send'] == True].copy() if 'would_send' in clean_df else clean_df.head(0)
    if len(sent) > 0 and 'net_profit_usd' in sent.columns and 'total_cost_usd' in sent.columns:
        non_zero = sent[sent['total_cost_usd'] > 0]
        if len(non_zero) > 0:
            ratios = non_zero['net_profit_usd'] / non_zero['total_cost_usd']
            ratio_median = float(ratios.median())
            green['profit_ratio'] = (ratio_median >= 2.0, f"{ratio_median:.2f}x", ">=2.00x")
        else:
            green['profit_ratio'] = (False, "no costs", ">=2.00x")
    else:
        green['profit_ratio'] = (False, "0 sends", ">=2.00x")

    # KPI 2: slippage_bps_0 p95 <= 15
    if 'slippage_bps_0' in clean_df.columns:
        slip_p95 = float(clean_df['slippage_bps_0'].quantile(0.95))
        green['slippage_p95'] = (slip_p95 <= 15, f"{slip_p95:.1f}bps", "<=15bps")
    else:
        green['slippage_p95'] = (False, "missing", "<=15bps")

    # KPI 3: slot_lag p95 <= 1 AND stale_due_to_missing_ticks ~ 0%
    if 'slot_lag' in clean_df.columns:
        lag_p95 = float(clean_df['slot_lag'].quantile(0.95))
        stale_pct = float(df['stale_due_to_missing_ticks'].mean()) * 100 if 'stale_due_to_missing_ticks' in df.columns else 0
        green['data_freshness'] = (lag_p95 <= 1 and stale_pct < 1.0,
                                   f"lag_p95={lag_p95:.0f}, stale={stale_pct:.2f}%",
                                   "lag<=1 & stale<1%")
    else:
        green['data_freshness'] = (False, "missing", "lag<=1 & stale<1%")

    # KPI 4: opportunity density >= 1 per hour
    opp_per_hour = freq
    green['opp_density'] = (opp_per_hour >= 1, f"{opp_per_hour:.2f}/h", ">=1.00/h")

    # KPI 5: outlier count == 0
    outlier_total = int(df['is_outlier'].sum()) if 'is_outlier' in df.columns else 0
    green['outlier_clean'] = (outlier_total == 0, f"{outlier_total} outliers", "0 outliers")

    all_pass = True
    for name, (passed, value, threshold) in green.items():
        symbol = "PASS" if passed else "FAIL"
        all_pass = all_pass and passed
        print(f"  [{symbol}] {name:20s} = {value:30s} (target: {threshold})")
    print("-"*40)
    if all_pass:
        print("LIVE GATE: GREEN — all 5 KPIs pass. PROBE LIVE may be activated.")
    else:
        failing = [n for n, (p, _, _) in green.items() if not p]
        print(f"LIVE GATE: RED — failing KPIs: {', '.join(failing)}")
    print("="*40 + "\n")

    # STRATIFICATION
    print("Stratification by Session:")
    print(clean_df.groupby('session')[['amount_in_usd']].agg(['count', 'mean', lambda x: x.quantile(0.95)]).rename(columns={'<lambda_0>': 'p95'}))

    print("\nStratification by Amount Bucket:")
    print(clean_df.groupby('amount_bucket')[['amount_in_usd']].agg(['count', 'mean']))

    print("\nStratification by Path Direction:")
    if 'leg0_dir' in clean_df.columns:
        clean_df['dir_combo'] = clean_df['leg0_dir'] + " -> " + clean_df['leg1_dir']
        print(clean_df.groupby('dir_combo')['amount_in_usd'].count().sort_values(ascending=False))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_shadow.py <path_to_jsonl_or_glob>")
        sys.exit(1)

    files = glob.glob(sys.argv[1])
    analyze(files)
