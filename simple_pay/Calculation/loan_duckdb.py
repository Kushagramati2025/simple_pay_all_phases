from __future__ import annotations

# --- ensure project root is importable ---
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, asdict, fields
from pathlib import Path
import json
import os
import glob
import duckdb
import pandas as pd
from typing import Optional, Dict, Any

# ============================================================
#  CONFIGURATION MODEL
# ============================================================
@dataclass(frozen=True)
class LoanCalcConfig:
    # Interest (0–30 days)
    flat_interest_days: int = 14
    incremental_interest_per_day_percent: float = 1.0
    max_interest_percent: float = 30.0

    # Penalties
    penalty_31_45_percent: float = 5.0
    penalty_46_60_percent: float = 10.0
    penalty_61_90_percent: float = 15.0

    # Windows (exclusive counting: Day 1 = disb_date + 1)
    bucket_0_30_start: int = 1
    bucket_0_30_end: int = 30
    bucket_31_45_start: int = 31
    bucket_31_45_end: int = 45
    bucket_46_60_start: int = 46
    bucket_46_60_end: int = 60
    bucket_61_90_start: int = 61
    bucket_61_90_end: int = 90

    # Control flags
    ignore_receipts_before_disb: bool = True     # ignore <= disb_date
    include_receipts_after_days: int = 90        # include up to 90 days after
    status_closed_principal_threshold: float = 0.0
    duck_threads: Optional[int] = None

# ============================================================
#  CONFIG LOADER
# ============================================================
def load_config(path: str | Path = "config/loan_rules.json") -> LoanCalcConfig:
    """Load loan calculation rules from JSON, fallback to defaults.
       Filters unknown keys so old JSONs with extra fields don't break."""
    defaults = LoanCalcConfig()
    p = Path(path)
    if not p.exists():
        return defaults
    with open(p, "r", encoding="utf-8") as f:
        try:
            data: Dict[str, Any] = json.load(f) or {}
        except Exception:
            print(f"⚠️ Failed to parse {p}, using defaults")
            return defaults

    # Merge then filter to dataclass fields (ignoring unknown keys like old 'flat_interest_percent')
    merged = {**asdict(defaults), **data}
    allowed = {f.name for f in fields(LoanCalcConfig)}
    filtered = {k: v for k, v in merged.items() if k in allowed}
    return LoanCalcConfig(**filtered)

# ============================================================
#  MAIN CALCULATION (final query integrated)
# ============================================================
def compute_all_38_duckdb(
    start_date: str,
    end_date: str,
    parquet_root: str | Path,
    *,
    disb_subdir: str = "disbursement",
    recv_subdir: str = "receipt",
    config_path: str = "config/loan_rules.json",
) -> pd.DataFrame:
    """
    Compute the loan report with interest (0–30) + penalties (31–90),
    exclusive day counting, payment allocation rules, and status that
    depends on the user-selected end_date.
    """
    cfg = load_config(config_path)

    # import snapshot path constants
    SNAP_DISB_GLOB = SNAP_RECV_GLOB = PARQUET_ROOT = None
    _last_err = None
    for mod in ("tools.config_paths", "tool.config_paths", "config_paths"):
        try:
            cp = __import__(mod, fromlist=["DISB_GLOB", "RECV_GLOB", "PARQUET_ROOT"])
            SNAP_DISB_GLOB = getattr(cp, "DISB_GLOB")
            SNAP_RECV_GLOB = getattr(cp, "RECV_GLOB")
            PARQUET_ROOT   = getattr(cp, "PARQUET_ROOT")
            break
        except Exception as e:
            _last_err = e
    if SNAP_DISB_GLOB is None or SNAP_RECV_GLOB is None:
        raise ModuleNotFoundError(
            "Could not import config_paths (tried tools.config_paths, tool.config_paths, config_paths). "
            f"Last error: {_last_err}"
        )

    # Prefer snapshots; fall back to partitioned files if snapshots don’t exist yet
    root = Path(parquet_root)
    PART_DISB_GLOB = (root / disb_subdir / "**" / "*.parquet").as_posix()
    PART_RECV_GLOB = (root / recv_subdir / "**" / "*.parquet").as_posix()

    def _pick_glob(snap_glob: str, part_glob: str) -> str:
        return snap_glob if glob.glob(snap_glob) else part_glob

    DISB_GLOB = _pick_glob(SNAP_DISB_GLOB, PART_DISB_GLOB)
    RECV_GLOB = _pick_glob(SNAP_RECV_GLOB, PART_RECV_GLOB)

    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    con.execute(f"SET threads TO {cfg.duck_threads or os.cpu_count() or 4}")

    # Interest setup (decimals)
    # Auto: flat percent = flat_days * incremental_per_day (percent terms)
    computed_flat_percent = float(cfg.flat_interest_days) * float(cfg.incremental_interest_per_day_percent)
    flat_pct = computed_flat_percent / 100.0           # fraction for SQL math
    incr_day = float(cfg.incremental_interest_per_day_percent) / 100.0
    max_pct  = float(cfg.max_interest_percent) / 100.0

    # Penalty decimals
    pen_5  = cfg.penalty_31_45_percent / 100.0
    pen_10 = cfg.penalty_46_60_percent / 100.0
    pen_15 = cfg.penalty_61_90_percent / 100.0

    # Exclusive start: ignore receipts on/before disb_date
    early_filter = "AND r.receipt_date > d.disb_date" if cfg.ignore_receipts_before_disb else ""

    sql = f"""
-- =========================
-- Interest till 30 (exclusive counting), then penalties (31–90)
-- =========================
WITH
-- 1) Disbursements within selected date range (original amounts)
disb AS (
  SELECT
    loan_id,
    borrower_name,
    branch,
    CAST(disb_date AS DATE)           AS disb_date,
    CAST(amount_disbursed AS DOUBLE)  AS disb_amount
  FROM read_parquet('{DISB_GLOB}')
  WHERE CAST(disb_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
),

-- 2) Receipts (raw)
recv_raw AS (
  SELECT
    loan_id,
    CAST(receipt_date AS DATE)            AS receipt_date,
    CAST(amount_received AS DOUBLE)       AS amount_received
  FROM read_parquet('{RECV_GLOB}')
),

-- 3) Same-day receipts (receipt_date = disb_date)
same_day AS (
  SELECT
    d.loan_id,
    SUM(r.amount_received) AS same_day_paid
  FROM disb d
  JOIN recv_raw r
    ON r.loan_id = d.loan_id
   AND r.receipt_date = d.disb_date
  GROUP BY d.loan_id
),

-- 4) Keep original for display; use NET for balance math; zero interest base if fully paid same day
disb2 AS (
  SELECT
    d.loan_id,
    d.borrower_name,
    d.branch,
    d.disb_date,

    -- keep ORIGINAL for display & for 30-day principal balance calc
    d.disb_amount                                 AS disb_amount_original,

    -- same-day paid (may be 0)
    COALESCE(s.same_day_paid, 0)                  AS same_day_paid,

    -- interest base: 0 if fully repaid same day, else ORIGINAL
    CASE
      WHEN COALESCE(s.same_day_paid, 0) >= d.disb_amount THEN 0
      ELSE d.disb_amount
    END                                           AS interest_base_amount,

    -- NET principal for internal daily balance math
    GREATEST(d.disb_amount - COALESCE(s.same_day_paid, 0), 0) AS disb_amount
  FROM disb d
  LEFT JOIN same_day s USING (loan_id)
),



-- 5) Receipts filtered to (disb_date, disb_date+90] per config; same-day excluded by '>'
recv AS (
  SELECT r.loan_id, r.receipt_date, r.amount_received
  FROM recv_raw r
  JOIN disb2 d USING (loan_id)
  WHERE DATE_DIFF('day', d.disb_date, r.receipt_date) BETWEEN 0 AND {cfg.include_receipts_after_days}
  {early_filter}   -- expands to: AND r.receipt_date > d.disb_date (if flag true)
),

-- 6) Generate day 1..90 per loan (exclusive counting: Day 1 = disb_date+1)
days AS (
  SELECT
    d.loan_id,
    d.borrower_name,
    d.branch,
    d.disb_date,
    d.disb_amount,            -- NET principal for balances
    d.interest_base_amount,   -- ORIGINAL for interest
    (seq + 1)                                   AS day_no,
    d.disb_date + ((seq + 1) * INTERVAL 1 DAY)  AS calc_date
  FROM disb2 d
  JOIN range(0,90) t(seq) ON TRUE
),

-- 7) Cumulative interest % by day (only used for display; accrual uses decimals)
rate AS (
  SELECT
    loan_id,
    borrower_name,
    branch,
    disb_date,
    disb_amount,
    interest_base_amount,
    day_no,
    calc_date,
    CASE
      WHEN day_no BETWEEN 1 AND {cfg.flat_interest_days} THEN {flat_pct} * 100.0
      WHEN day_no > {cfg.flat_interest_days} THEN ({flat_pct} + (day_no - {cfg.flat_interest_days}) * {incr_day}) * 100.0
      ELSE 0
    END AS cum_rate_percent
  FROM days
),

-- 8) Payments per day (sum same-day receipts on calc_date)
pay AS (
  SELECT
    r.loan_id,
    r.borrower_name,
    r.branch,
    r.disb_date,
    r.disb_amount,
    r.interest_base_amount,
    r.day_no,
    r.calc_date,
    r.cum_rate_percent,
    COALESCE(SUM(x.amount_received), 0) AS paid_today
  FROM rate r
  LEFT JOIN recv x
    ON x.loan_id = r.loan_id
   AND x.receipt_date = r.calc_date
  GROUP BY
    r.loan_id, r.borrower_name, r.branch, r.disb_date, r.disb_amount, r.interest_base_amount,
    r.day_no, r.calc_date, r.cum_rate_percent
),

-- 9) Window sums for 0–30, 31–45, 46–60, 61–90
paid_wins AS (
  SELECT
    loan_id,
    borrower_name,
    branch,
    SUM(CASE WHEN day_no BETWEEN {cfg.bucket_0_30_start}  AND {cfg.bucket_0_30_end}  THEN paid_today ELSE 0 END) AS amount_repaid_within_30_days,
    SUM(CASE WHEN day_no BETWEEN {cfg.bucket_31_45_start} AND {cfg.bucket_31_45_end} THEN paid_today ELSE 0 END) AS amount_received_within_31_45_days,
    SUM(CASE WHEN day_no BETWEEN {cfg.bucket_46_60_start} AND {cfg.bucket_46_60_end} THEN paid_today ELSE 0 END) AS amount_received_within_46_60_days,
    SUM(CASE WHEN day_no BETWEEN {cfg.bucket_61_90_start} AND {cfg.bucket_61_90_end} THEN paid_today ELSE 0 END) AS amount_received_within_61_90_days
  FROM pay
  GROUP BY loan_id, borrower_name, branch
),

-- 10) 0–30 window rows
pay_1_30 AS (
  SELECT * FROM pay WHERE day_no BETWEEN {cfg.bucket_0_30_start} AND {cfg.bucket_0_30_end}
),

-- 11) Cumulative paid and interest accrued TO THE DAY
pay_cum_30 AS (
  SELECT
    loan_id,
    borrower_name,
    branch,
    disb_date,
    disb_amount,             -- NET principal
    interest_base_amount,    -- ORIGINAL (for interest)
    day_no,
    calc_date,
    cum_rate_percent,
    paid_today,
    SUM(paid_today) OVER (PARTITION BY loan_id ORDER BY day_no
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_paid,
    -- ★ Accrue interest on ORIGINAL disbursement (per your policy)
    interest_base_amount * LEAST(
      ({flat_pct} + GREATEST(day_no - {cfg.flat_interest_days}, 0) * {incr_day}),
      {max_pct}
    ) AS cum_interest_accrued
  FROM pay_1_30
),

-- 12) At each payment day: how much of cum_paid goes to interest accrued to that day
payments_30 AS (
  SELECT
    loan_id,
    day_no,
    LEAST(cumulative_paid, cum_interest_accrued) AS interest_paid_cum_at_pay
  FROM pay_cum_30
  WHERE paid_today > 0
),

-- 13) Carry forward last payment-day’s allocation to non-payment days
carry_30 AS (
  SELECT
    t.loan_id,
    t.borrower_name,
    t.branch,
    t.disb_date,
    t.disb_amount,
    t.interest_base_amount,
    t.day_no,
    t.calc_date,
    t.cum_interest_accrued,
    t.cumulative_paid,
    MAX(CASE WHEN t.paid_today > 0 THEN t.day_no END)
      OVER (PARTITION BY t.loan_id ORDER BY t.day_no
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS last_pay_day
  FROM pay_cum_30 t
),

-- 14) Carried cumulative allocations
alloc_30 AS (
  SELECT
    c.loan_id,
    c.borrower_name,
    c.branch,
    c.disb_date,
    c.disb_amount,
    c.interest_base_amount,
    c.day_no,
    c.calc_date,
    c.cum_interest_accrued,
    c.cumulative_paid,
    LEAST(COALESCE(p.interest_paid_cum_at_pay, 0), c.cum_interest_accrued)             AS interest_paid_cum,
    GREATEST(c.cumulative_paid - COALESCE(p.interest_paid_cum_at_pay, 0), 0)           AS principal_paid_cum
  FROM carry_30 c
  LEFT JOIN payments_30 p
    ON p.loan_id = c.loan_id AND p.day_no = c.last_pay_day
),

-- 15) payoff day inside 1..30 if fully closed (principal NET + interest on ORIGINAL) at payment time
payoff_30 AS (
  SELECT loan_id, MIN(day_no) AS payoff_day
  FROM (
    SELECT
      loan_id,
      day_no,
      CASE WHEN paid_today > 0 THEN
        CASE WHEN (cumulative_paid >= disb_amount + cum_interest_accrued) THEN day_no ELSE NULL END
      ELSE NULL END AS payoff_flag_day
    FROM pay_cum_30
  ) s
  WHERE payoff_flag_day IS NOT NULL
  GROUP BY loan_id
),

-- 16) cutoff day = min(30, payoff_day)
cutoff AS (
  SELECT d.loan_id, COALESCE(LEAST({cfg.bucket_0_30_end}, p.payoff_day), {cfg.bucket_0_30_end}) AS cutoff_day
  FROM disb2 d
  LEFT JOIN payoff_30 p USING (loan_id)
),

-- 17) Snapshot at cutoff using carried allocations
calc_30 AS (
  WITH base AS (
    SELECT
      ac.loan_id,
      ac.borrower_name,
      ac.branch,
      ac.disb_date,
      d.disb_amount_original                      AS disb_amount,
      d.same_day_paid,
      ac.cumulative_paid                           AS amount_repaid_within_30_days,
      ac.cum_interest_accrued                      AS interest_accrued_30,
      ac.interest_paid_cum                         AS interest_paid_30,
      ac.principal_paid_cum                        AS principal_paid_cum_1_30,
      ac.cum_interest_accrued - ac.interest_paid_cum AS interest_balance_30
    FROM cutoff a
    JOIN alloc_30 ac
      ON ac.loan_id = a.loan_id
     AND ac.day_no  = a.cutoff_day
    JOIN disb2 d
      ON d.loan_id = ac.loan_id
  )
  SELECT
    loan_id,
    borrower_name,
    branch,
    disb_date,
    disb_amount,
    amount_repaid_within_30_days,
    interest_accrued_30,
    interest_paid_30,
    (principal_paid_cum_1_30 + COALESCE(same_day_paid, 0)) AS principal_paid_30,
    (disb_amount - (principal_paid_cum_1_30 + COALESCE(same_day_paid, 0)))
        + interest_balance_30 AS outstanding_after_30_days

  FROM base
),



-- 18) 31–45 (penalty {cfg.penalty_31_45_percent}% on outstanding_after_30)
calc_45 AS (
  SELECT
    c.*,
    COALESCE(w.amount_received_within_31_45_days, 0) AS amount_received_within_31_45_days,
    ROUND(c.outstanding_after_30_days * {pen_5}, 2)  AS penalty_31_45,
    LEAST(COALESCE(w.amount_received_within_31_45_days, 0), ROUND(c.outstanding_after_30_days * {pen_5}, 2)) AS penalty_paid_31_45,
    GREATEST(COALESCE(w.amount_received_within_31_45_days, 0) - ROUND(c.outstanding_after_30_days * {pen_5}, 2), 0) AS principal_paid_31_45,
    ROUND(c.outstanding_after_30_days * {pen_5}, 2) - LEAST(COALESCE(w.amount_received_within_31_45_days, 0), ROUND(c.outstanding_after_30_days * {pen_5}, 2)) AS penalty_balance_31_45,
    (c.outstanding_after_30_days - GREATEST(COALESCE(w.amount_received_within_31_45_days, 0) - ROUND(c.outstanding_after_30_days * {pen_5}, 2), 0)) AS principal_balance_31_45,
    ( (c.outstanding_after_30_days - GREATEST(COALESCE(w.amount_received_within_31_45_days, 0) - ROUND(c.outstanding_after_30_days * {pen_5}, 2), 0))
      + (ROUND(c.outstanding_after_30_days * {pen_5}, 2) - LEAST(COALESCE(w.amount_received_within_31_45_days, 0), ROUND(c.outstanding_after_30_days * {pen_5}, 2))) ) AS outstanding_after_45_days
  FROM calc_30 c
  LEFT JOIN paid_wins w USING (loan_id, borrower_name, branch)
),

-- 19) 46–60 (penalty {cfg.penalty_46_60_percent}% on outstanding_after_45)
calc_60 AS (
  SELECT
    c.*,
    COALESCE(w.amount_received_within_46_60_days, 0) AS amount_received_within_46_60_days,
    ROUND(c.outstanding_after_45_days * {pen_10}, 2) AS penalty_46_60,
    LEAST(COALESCE(w.amount_received_within_46_60_days, 0), ROUND(c.outstanding_after_45_days * {pen_10}, 2)) AS penalty_paid_46_60,
    GREATEST(COALESCE(w.amount_received_within_46_60_days, 0) - ROUND(c.outstanding_after_45_days * {pen_10}, 2), 0) AS principal_paid_46_60,
    ROUND(c.outstanding_after_45_days * {pen_10}, 2) - LEAST(COALESCE(w.amount_received_within_46_60_days, 0), ROUND(c.outstanding_after_45_days * {pen_10}, 2)) AS penalty_balance_46_60,
    (c.outstanding_after_45_days - GREATEST(COALESCE(w.amount_received_within_46_60_days, 0) - ROUND(c.outstanding_after_45_days * {pen_10}, 2), 0)) AS principal_balance_46_60,
    ( (c.outstanding_after_45_days - GREATEST(COALESCE(w.amount_received_within_46_60_days, 0) - ROUND(c.outstanding_after_45_days * {pen_10}, 2), 0))
      + (ROUND(c.outstanding_after_45_days * {pen_10}, 2) - LEAST(COALESCE(w.amount_received_within_46_60_days, 0), ROUND(c.outstanding_after_45_days * {pen_10}, 2))) ) AS outstanding_after_60_days
  FROM calc_45 c
  LEFT JOIN paid_wins w USING (loan_id, borrower_name, branch)
),

-- 20) 61–90 (penalty {cfg.penalty_61_90_percent}% on outstanding_after_60)
calc_90 AS (
  SELECT
    c.*,
    COALESCE(w.amount_received_within_61_90_days, 0) AS amount_received_within_61_90_days,
    ROUND(c.outstanding_after_60_days * {pen_15}, 2) AS penalty_61_90,
    LEAST(COALESCE(w.amount_received_within_61_90_days, 0), ROUND(c.outstanding_after_60_days * {pen_15}, 2)) AS penalty_paid_61_90,
    GREATEST(COALESCE(w.amount_received_within_61_90_days, 0) - ROUND(c.outstanding_after_60_days * {pen_15}, 2), 0) AS principal_paid_61_90,
    ROUND(c.outstanding_after_60_days * {pen_15}, 2) - LEAST(COALESCE(w.amount_received_within_61_90_days, 0), ROUND(c.outstanding_after_60_days * {pen_15}, 2)) AS penalty_balance_61_90,
    (c.outstanding_after_60_days - GREATEST(COALESCE(w.amount_received_within_61_90_days, 0) - ROUND(c.outstanding_after_60_days * {pen_15}, 2), 0)) AS principal_balance_61_90,
    ( (c.outstanding_after_60_days - GREATEST(COALESCE(w.amount_received_within_61_90_days, 0) - ROUND(c.outstanding_after_60_days * {pen_15}, 2), 0))
      + (ROUND(c.outstanding_after_60_days * {pen_15}, 2) - LEAST(COALESCE(w.amount_received_within_61_90_days, 0), ROUND(c.outstanding_after_60_days * {pen_15}, 2))) ) AS outstanding_after_90_days
  FROM calc_60 c
  LEFT JOIN paid_wins w USING (loan_id, borrower_name, branch)
)

-- =========================
-- Final SELECT (exact columns + Status based on user end_date)
-- =========================
SELECT
  loan_id,
  borrower_name,
  branch,
  disb_date                                  AS disb_date,
  ROUND(disb_amount, 2)                      AS disb_amount,

  -- 0–30 (interest window)
  ROUND(amount_repaid_within_30_days, 2)     AS Amount_repaid_within_30_days,
  ROUND(interest_accrued_30, 2)              AS Interest_accrued_30,
  ROUND(interest_paid_30, 2)                 AS Interest_paid_30,
  ROUND(principal_paid_30, 2)                AS Principal_paid_30,
  ROUND(outstanding_after_30_days, 2)        AS Outstanding_after_30_days,

  -- 31–45
  ROUND(amount_received_within_31_45_days, 2) AS Amount_Received_within_31_to_45_days,
  ROUND(penalty_31_45, 2)                     AS Penalty_31_45,
  ROUND(penalty_paid_31_45, 2)                AS Penalty_paid_31_45,
  ROUND(penalty_balance_31_45, 2)             AS Penalty_balance_31_45,
  ROUND(principal_paid_31_45, 2)              AS Principal_paid_31_45,
  ROUND(principal_balance_31_45, 2)           AS Principal_balance_31_45,
  ROUND(outstanding_after_45_days, 2)         AS Outstanding_after_45_days,

  -- 46–60
  ROUND(amount_received_within_46_60_days, 2) AS Amount_Received_within_46_to_60_days,
  ROUND(penalty_46_60, 2)                     AS Penalty_46_60,
  ROUND(penalty_paid_46_60, 2)                AS Penalty_paid_46_60,
  ROUND(penalty_balance_46_60, 2)             AS Penalty_balance_46_60,
  ROUND(principal_paid_46_60, 2)              AS Principal_paid_46_60,
  ROUND(principal_balance_46_60, 2)           AS Principal_balance_46_60,
  ROUND(outstanding_after_60_days, 2)         AS Outstanding_after_60_days,

  -- 61–90
  ROUND(amount_received_within_61_90_days, 2) AS Amount_Received_within_61_to_90_days,
  ROUND(penalty_61_90, 2)                     AS Penalty_61_90,
  ROUND(penalty_paid_61_90, 2)                AS Penalty_paid_61_90,
  ROUND(penalty_balance_61_90, 2)             AS Penalty_balance_61_90,
  ROUND(principal_paid_61_90, 2)              AS Principal_paid_61_90,
  ROUND(principal_balance_61_90, 2)           AS Principal_balance_61_90,
  ROUND(outstanding_after_90_days, 2)         AS Outstanding_after_90_days,

  -- Status (no CURRENT_DATE; based on user-selected end_date)
  CASE
    WHEN ROUND(outstanding_after_90_days, 2) <= {cfg.status_closed_principal_threshold} THEN 'Closed'
    WHEN disb_date + INTERVAL {cfg.bucket_61_90_end} DAY > DATE '{end_date}' THEN 'Active'
    ELSE 'Defaulter'
  END AS status

FROM calc_90
ORDER BY loan_id;

    """

    return con.sql(sql).df()

