# load_config.py
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml  # Optional; only used if .yaml/.yml
except Exception:
    yaml = None

# -----------------------------
# Defaults (human-friendly %’s)
# -----------------------------
DEFAULTS: Dict[str, Any] = {
    # Interest config (store as PERCENT values for readability)
    "flat_interest_percent": 14,                   # 14%
    "flat_interest_days": 14,
    "incremental_interest_per_day_percent": 1,     # +1% per day after flat window
    "max_interest_percent": 30,                    # 30% cap

    # Penalty (percent of outstanding at the start of the window)
    "penalty_31_45_percent": 5,
    "penalty_46_60_percent": 10,
    "penalty_61_90_percent": 15,

    # Day buckets (your pipeline uses day_no = 1..90)
    "bucket_0_30_start": 1,
    "bucket_0_30_end": 30,
    "bucket_31_45_start": 31,
    "bucket_31_45_end": 45,
    "bucket_46_60_start": 46,
    "bucket_46_60_end": 60,
    "bucket_61_90_start": 61,
    "bucket_61_90_end": 90,

    # Receipts window / filtering
    # Note: elsewhere you treat this as "ignore on or before disb_date" (r.receipt_date > d.disb_date)
    "ignore_receipts_before_disb": True,           # ignore receipts on dates < disb_date (see note above)
    "include_receipts_after_days": 90,             # keep receipts up to N days after disb

    # Back-compat (older names some pages still use)
    "receipts_window_days": 90,                    # alias of include_receipts_after_days
    "include_receipts_on_or_after_disb": True,     # alias of ignore_receipts_before_disb

    # Status rule
    "status_closed_principal_threshold": 0.0,      # <= this considered Closed

    # Execution tuning
    "duck_threads": None,                          # None → auto (use os.cpu_count())
}


def _merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (updates or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"true", "1", "yes", "y", "on"}:
        return True
    if s in {"false", "0", "no", "n", "off"}:
        return False
    # fallback: python truthiness
    return bool(v)


def _num_or_str(v: str) -> Any:
    # best-effort numeric parsing
    s = v.strip()
    try:
        if "." in s:
            return float(s)
        return int(s)
    except Exception:
        return v


def _percent_to_fraction(x: float) -> float:
    """
    Accept both percent (e.g., 14, 1, 30) and fraction (0.14, 0.01, 0.30).
    If x >= 1, treat as percent and divide by 100.
    """
    try:
        xf = float(x)
    except Exception:
        return 0.0
    return xf / 100.0 if xf >= 1.0 else xf


def _normalize_duck_threads(value: Optional[Any]) -> Optional[int]:
    """
    Normalize duck_threads:
      - None / "auto" / "" / "none" → None (let caller pick os.cpu_count()).
      - numeric-like strings → int >= 1
      - invalid → None
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "none", "auto"}:
        return None
    try:
        n = int(float(value))
        return max(1, n)
    except Exception:
        return None


def load_config(
    path: str | Path = "config/loan_rules.json",
    env_prefix: str = "LOANCFG_",
) -> Dict[str, Any]:
    """
    Load rules from JSON/YAML + allow simple env overrides like:
      LOANCFG_flat_interest_percent=12
      LOANCFG_penalty_31_45_percent=6
      LOANCFG_include_receipts_after_days=120
      LOANCFG_ignore_receipts_before_disb=false

    Returns a dict that includes BOTH:
      - human % keys (e.g., flat_interest_percent)
      - derived fraction keys for SQL templating:
            flat_pct, incr_day, max_pct, pen_5, pen_10, pen_15
    """
    path = Path(path)
    cfg: Dict[str, Any] = dict(DEFAULTS)

    # 1) File overrides (JSON/YAML)
    if path.exists():
        if path.suffix.lower() in {".yaml", ".yml"}:
            if not yaml:
                raise RuntimeError("PyYAML not installed; install pyyaml or use JSON.")
            with path.open("r", encoding="utf-8") as f:
                file_cfg = yaml.safe_load(f) or {}
        else:
            with path.open("r", encoding="utf-8") as f:
                file_cfg = json.load(f)
        cfg = _merge(cfg, file_cfg)

    # 2) Env overrides (flat key → value)
    for k, v in os.environ.items():
        if not k.startswith(env_prefix):
            continue
        key = k[len(env_prefix):]
        # try bool first, then numeric, else raw string
        if v.strip().lower() in {"true","false","1","0","yes","no","on","off"}:
            cfg[key] = _to_bool(v)
        else:
            cfg[key] = _num_or_str(v)

    # 3) Basic clamps / types
    # interest + penalties as PERCENT values (keep human readable)
    for pkey in [
        "flat_interest_percent",
        "incremental_interest_per_day_percent",
        "max_interest_percent",
        "penalty_31_45_percent",
        "penalty_46_60_percent",
        "penalty_61_90_percent",
    ]:
        cfg[pkey] = max(0.0, float(cfg.get(pkey, DEFAULTS[pkey])))

    cfg["flat_interest_days"] = int(max(0, int(cfg.get("flat_interest_days", DEFAULTS["flat_interest_days"]))))  # noqa: E501

    # buckets (ensure inclusive ranges and order)
    for k in [
        "bucket_0_30_start","bucket_0_30_end",
        "bucket_31_45_start","bucket_31_45_end",
        "bucket_46_60_start","bucket_46_60_end",
        "bucket_61_90_start","bucket_61_90_end",
    ]:
        cfg[k] = int(cfg.get(k, DEFAULTS[k]))

    # receipts window (unify names)
    # prefer explicit include_receipts_after_days if present; else fall back
    ira = cfg.get("include_receipts_after_days", None)
    if ira is None:
        ira = cfg.get("receipts_window_days", DEFAULTS["receipts_window_days"])
    # clamp to a reasonable upper bound (keep generous)
    cfg["include_receipts_after_days"] = int(max(0, min(int(ira), 365)))

    # ignore flag: prefer explicit ignore_receipts_before_disb
    irbd = cfg.get("ignore_receipts_before_disb", None)
    if irbd is None:
        # legacy "include_on_or_after_disb" means "do NOT ignore before disb"
        # so: include_on_or_after=True ⇒ ignore_before=True
        legacy = _to_bool(cfg.get("include_receipts_on_or_after_disb", DEFAULTS["include_receipts_on_or_after_disb"]))  # noqa: E501
        irbd = bool(legacy)
    cfg["ignore_receipts_before_disb"] = bool(irbd)

    cfg["status_closed_principal_threshold"] = float(cfg.get("status_closed_principal_threshold", 0.0))

    # Normalize duck_threads after env/file merges
    cfg["duck_threads"] = _normalize_duck_threads(cfg.get("duck_threads", None))

    # 4) DERIVED FRACTION FIELDS for SQL templating

    # --- 3.5 Auto-adjust interest relationships -------------------------
    flat_days = int(cfg.get("flat_interest_days", DEFAULTS["flat_interest_days"]))
    incr_per_day = float(cfg.get("incremental_interest_per_day_percent", DEFAULTS["incremental_interest_per_day_percent"]))

    # Compute derived fractions directly (no flat_interest_percent key anymore)
    computed_flat_percent = flat_days * incr_per_day
    cfg["flat_pct"] = _percent_to_fraction(computed_flat_percent)



    cfg["flat_pct"] = _percent_to_fraction(cfg["flat_interest_percent"])
    cfg["incr_day"] = _percent_to_fraction(cfg["incremental_interest_per_day_percent"])
    cfg["max_pct"]  = _percent_to_fraction(cfg["max_interest_percent"])

    cfg["pen_5"]  = _percent_to_fraction(cfg["penalty_31_45_percent"])
    cfg["pen_10"] = _percent_to_fraction(cfg["penalty_46_60_percent"])
    cfg["pen_15"] = _percent_to_fraction(cfg["penalty_61_90_percent"])

    # 5) Safety assertions (non-fatal clamps)
    # Ensure buckets are within 1..90 and ordered
    def _clamp(a: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, a))

    b0s = _clamp(cfg["bucket_0_30_start"], 1, 30)
    b0e = _clamp(cfg["bucket_0_30_end"],   b0s, 30)
    cfg["bucket_0_30_start"], cfg["bucket_0_30_end"] = b0s, b0e

    b1s = _clamp(cfg["bucket_31_45_start"], 31, 45)
    b1e = _clamp(cfg["bucket_31_45_end"],   b1s, 45)
    cfg["bucket_31_45_start"], cfg["bucket_31_45_end"] = b1s, b1e

    b2s = _clamp(cfg["bucket_46_60_start"], 46, 60)
    b2e = _clamp(cfg["bucket_46_60_end"],   b2s, 60)
    cfg["bucket_46_60_start"], cfg["bucket_46_60_end"] = b2s, b2e

    b3s = _clamp(cfg["bucket_61_90_start"], 61, 90)
    b3e = _clamp(cfg["bucket_61_90_end"],   b3s, 90)
    cfg["bucket_61_90_start"], cfg["bucket_61_90_end"] = b3s, b3e

    return cfg
