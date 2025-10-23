# service/vector_math.py
from __future__ import annotations
import numpy as np
import pandas as pd
 
def build_event_snapshot(
    disb_df: pd.DataFrame,
    rcpt_df: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp,
    due_date_col: str = "due_date",
) -> pd.DataFrame:
    # (unchanged — keep your original implementation)
    d = (disb_df[["loan_id", "disbursed_date", "disbursed_amount"]]
         .rename(columns={"disbursed_date": "event_date", "disbursed_amount": "delta"})).copy()
    r = (rcpt_df[["loan_id", "receipt_date", "amount"]]
         .rename(columns={"receipt_date": "event_date", "amount": "delta"})).copy()
 
    d["delta"] = pd.to_numeric(d["delta"], errors="coerce").fillna(0.0).astype("float64")
    r["delta"] = -pd.to_numeric(r["delta"], errors="coerce").fillna(0.0).astype("float64")
 
    events = pd.concat([d, r], ignore_index=True)
    events["event_date"] = pd.to_datetime(events["event_date"], errors="coerce")
    events = events.dropna(subset=["loan_id", "event_date"]).sort_values(["loan_id","event_date"], kind="mergesort")
 
    as_of = pd.to_datetime(as_of)
    events = events[events["event_date"] <= as_of]
    if events.empty:
        return pd.DataFrame(columns=["loan_id", "balance", "days_overdue"])
 
    events["balance"] = events.groupby("loan_id", sort=False)["delta"].cumsum().astype("float64")
 
    snap = (events.groupby("loan_id", sort=False)
                  .tail(1)[["loan_id", "balance"]].copy())
    snap["balance"] = np.clip(snap["balance"].to_numpy(dtype="float64"), 0.0, None)
 
    if due_date_col in disb_df.columns:
        due_map = (disb_df[["loan_id", due_date_col]]
                   .dropna()
                   .drop_duplicates("loan_id")
                   .assign(**{due_date_col: lambda x: pd.to_datetime(x[due_date_col], errors="coerce")}))
        snap = snap.merge(due_map, on="loan_id", how="left")
        days = (as_of - snap[due_date_col]).dt.days
        days = days.fillna(0).astype("int32").to_numpy()
        days = np.maximum(days, 0)
    else:
        days = np.zeros(len(snap), dtype="int32")
        snap[due_date_col] = pd.NaT
 
    snap["days_overdue"] = days
    return snap[["loan_id", "balance", "days_overdue"]]
 
 
def compute_slab_components_vector(
    principal_arr: np.ndarray,
    days_arr: np.ndarray,
) -> dict[str, np.ndarray]:
    principal = np.asarray(principal_arr, dtype="float64")
    # be conservative converting days: if floats or NaN present, coerce via astype after nan->0
    days = np.asarray(days_arr)
    if np.issubdtype(days.dtype, np.floating):
        days = np.nan_to_num(days, nan=0.0).astype("int32")
    else:
        days = days.astype("int32")
 
    # Clean principal: NaN or negative -> 0; set posinf/neginf explicitly
    principal = np.nan_to_num(principal, nan=0.0, posinf=0.0, neginf=0.0)
    principal = np.maximum(principal, 0.0)
 
    # Initialize outputs
    interest = np.zeros_like(principal)
    p30 = np.zeros_like(principal)   # principal_30
    pe30 = np.zeros_like(principal)  # penalty_30
    p45 = np.zeros_like(principal)
    pe45 = np.zeros_like(principal)
    p60 = np.zeros_like(principal)
    pe60 = np.zeros_like(principal)
 
    # Masks
    m_1_14  = (days >= 1)  & (days <= 14)
    m_15_30 = (days >= 15) & (days <= 30)
    m_31_45 = (days >= 31) & (days <= 45)
    m_46_60 = (days >= 46) & (days <= 60)
    m_61_90 = (days >= 61) & (days <= 90)
 
    # 1–14: 14%
    if m_1_14.any():
        interest[m_1_14] = 0.14 * principal[m_1_14]
 
    # 15–30: 14% + 1% per day after 14
    if m_15_30.any():
        extra_days = (days - 14).clip(min=0)
        interest[m_15_30] = (0.14 + 0.01 * extra_days[m_15_30]) * principal[m_15_30]
 
    # >=31 logic uses interest@30 = 30% * principal
    base_interest_30 = 0.30 * principal
    p30_base = principal + base_interest_30  # principal_30 for >=31

    m_ge_31 = (days >= 31)
    if m_ge_31.any():
        interest[m_ge_31] = base_interest_30[m_ge_31]
 
    # 31–45 penalties
    pe30_ = 0.05 * p30_base
    p45_  = p30_base + pe30_
    pe45_ = 0.10 * p45_
 
    # 60-day layer
    p60_  = p45_ + pe45_
    pe60_ = 0.15 * p60_
 
    # Assign slices
    if m_31_45.any():
        pe30[m_31_45] = pe30_[m_31_45]
        p30[m_31_45]  = p30_base[m_31_45]
        pe45[m_31_45] = pe45_[m_31_45]
        p45[m_31_45]  = p45_[m_31_45]
 
    if m_46_60.any():
        pe30[m_46_60] = pe30_[m_46_60]
        p30[m_46_60]  = p30_base[m_46_60]
        pe45[m_46_60] = pe45_[m_46_60]
        p45[m_46_60]  = p45_[m_46_60]
        pe60[m_46_60] = pe60_[m_46_60]
        p60[m_46_60]  = p60_[m_46_60]
 
    if m_61_90.any():
        pe30[m_61_90] = pe30_[m_61_90]
        p30[m_61_90]  = p30_base[m_61_90]
        pe45[m_61_90] = pe45_[m_61_90]
        p45[m_61_90]  = p45_[m_61_90]
        pe60[m_61_90] = pe60_[m_61_90]
        p60[m_61_90]  = p60_[m_61_90]
 
    total_due = interest + pe30 + pe45 + pe60 + principal
    
 
    return {
        "interest": interest,
        "penalty_30": pe30,
        "penalty_45": pe45,
        "penalty_60": pe60,
        "principal_30": p30,
        "principal_45": p45,
        "principal_60": p60,
        "total_due": total_due,
    }
 
 
def compute_slab_df(
    loan_ids: list[str] | np.ndarray,
    principal_arr: np.ndarray,
    days_arr: np.ndarray,
    round_2: bool = True,
) -> pd.DataFrame:
    comp = compute_slab_components_vector(principal_arr, days_arr)
 
    loan_ids_arr = np.asarray(loan_ids)
    if len(loan_ids_arr) != len(principal_arr):
        raise ValueError("loan_ids length must match principal_arr length")
 
    out = pd.DataFrame({
        "loan_id": loan_ids_arr,
        "interest": comp["interest"],
        "penalty_30": comp["penalty_30"],
        "penalty_45": comp["penalty_45"],
        "penalty_60": comp["penalty_60"],
        "principal_30": comp["principal_30"],
        "principal_45": comp["principal_45"],
        "principal_60": comp["principal_60"],
        "total_due": comp["total_due"],
    })
    if round_2:
        for c in ["interest","penalty_30","penalty_45","penalty_60","principal_30","principal_45","principal_60","total_due"]:
            out[c] = np.round(out[c], 2)
 
    return out
 