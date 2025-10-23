# tools/refresh_parquet_cache.py
from __future__ import annotations

# -----------------------------
# Early: load .env if available
# -----------------------------
import os
from pathlib import Path

def _load_dotenv():
    try:
        from dotenv import load_dotenv  # make sure 'python-dotenv' is in requirements
    except Exception:
        return
    # Prefer .env in the current working directory (where you launch the app/EXE)
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        load_dotenv(cwd_env, override=False)
    # Also try alongside this file (useful in dev)
    here_env = Path(__file__).resolve().parent / ".env"
    if here_env.exists():
        load_dotenv(here_env, override=False)

_load_dotenv()

import json, time
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

# Use the unified path config (SIMPLEPAY_CACHE_DIR respected there)
from tools.config_paths import PARQUET_ROOT

# ========= CONFIG (env-driven) =========
DB_USER = os.getenv("DB_USER", "root")
DB_PWD  = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "keny")

# Use mysql-connector-python (already in requirements)
CONN_STR = (
    f"mysql+mysqlconnector://{DB_USER}:{DB_PWD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)

# Connection pool tuning is safe to keep modest
engine = create_engine(CONN_STR, pool_pre_ping=True, pool_size=5, max_overflow=10)

# Tables to snapshot (add/remove as needed)
TABLES: List[str] = [
    "disbursement", "receipt", "members", "branch"
]

# Optional freshness column per table (MAX(updated_at)); falls back to COUNT(*)
UPDATED_AT_COL: Dict[str, str] = {
    # "disbursement": "updated_at",
    # "receipt": "updated_at",
    # "members": "updated_at",
    # "branch": "updated_at",
}

# Retention & polling from env
RETENTION = int(os.getenv("SIMPLEPAY_RETENTION", "10"))
POLL_SECONDS = int(os.getenv("SIMPLEPAY_POLL_SECONDS", "60"))

# ---------- Stable schema for each table (match your MySQL) ----------
EXPECTED_DTYPES: Dict[str, Dict[str, str]] = {
    "receipt": {
        "id": "Int64",
        "receipt_date": "datetime64[ns]",
        "loan_id": "string",
        "receipt_id": "string",
        "amount_received": "float64",
        "transcode": "string",
        "resolve": "string",
        "created_at": "datetime64[ns]",
        # "updated_at": "datetime64[ns]",
    },
    "disbursement": {
        "id": "Int64",
        "loan_id": "string",
        "branch": "string",
        "disbursement_id": "string",
        "amount_disbursed": "float64",
        "transcode": "string",
        "disb_date": "datetime64[ns]",
        "borrower_name": "string",
        "principal": "float64",
        "created_at": "datetime64[ns]",
        "updated_at": "datetime64[ns]",
    },
    "members": {
        "id": "Int64",
        "disb_date": "datetime64[ns]",
        "borrower_name": "string",
        "branch": "string",
        "membership_income": "float64",
        "transcode": "string",
        "created_at": "datetime64[ns]",
    },
    "branch": {
        "branch": "string",
        "created_at": "datetime64[ns]",
    },
}

# ========= HELPERS =========
def load_state(table: str) -> Dict[str, Any]:
    """Load last seen metadata for a table."""
    state_path = PARQUET_ROOT / table / "_state.json"
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_state(table: str, state: Dict[str, Any]) -> None:
    state_path = PARQUET_ROOT / table / "_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def table_exists(conn, table_name: str, schema: str | None = None) -> bool:
    """Check if a table exists in the current schema (MySQL)."""
    q = text("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = :table
        LIMIT 1
    """)
    db = schema or conn.engine.url.database
    return (conn.execute(q, {"schema": db, "table": table_name}).scalar() or 0) > 0

def get_table_metrics(table: str) -> Dict[str, Any]:
    """Return count and (optionally) max(updated_at). Robust to missing tables/columns."""
    with engine.begin() as conn:
        if not table_exists(conn, table):
            return {"exists": False, "count": 0, "max_updated_at": None}

        info: Dict[str, Any] = {"exists": True, "count": 0, "max_updated_at": None}
        try:
            cnt = conn.execute(text(f"SELECT COUNT(*) AS c FROM `{table}`")).scalar_one()
            info["count"] = int(cnt or 0)
        except ProgrammingError:
            info["count"] = 0

        if table in UPDATED_AT_COL:
            col = UPDATED_AT_COL[table]
            try:
                mx = conn.execute(text(f"SELECT MAX(`{col}`) FROM `{table}`")).scalar()
                info["max_updated_at"] = (
                    mx.isoformat() if hasattr(mx, "isoformat") and mx is not None
                    else (str(mx) if mx is not None else None)
                )
            except ProgrammingError:
                info["max_updated_at"] = None

        return info

def table_changed(table: str, prev: Dict[str, Any], current: Dict[str, Any]) -> bool:
    """Decide if we should take a fresh snapshot."""
    if current.get("max_updated_at") is not None:
        return current.get("max_updated_at") != prev.get("max_updated_at")
    return int(current.get("count", 0)) != int(prev.get("count", -1))

# ---------- DType Coercion ----------
def _empty_series_for_dtype(dt: str) -> pd.Series:
    """Return an empty Series with the requested dtype."""
    if dt == "string":
        return pd.Series(pd.array([], dtype="string"))
    if dt.startswith("datetime"):
        return pd.to_datetime([])
    if dt in ("Int64", "Int32", "Int16"):
        return pd.Series(pd.array([], dtype=dt))
    return pd.Series(dtype=dt)

def coerce_dtypes(table: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure DataFrame matches EXPECTED_DTYPES:
      - create missing columns with correct dtype
      - coerce existing columns
      - fill string columns with "" so Arrow doesn't emit NULL logical type
      - keep a stable column order (expected columns first)
    """
    spec = EXPECTED_DTYPES.get(table, {})
    if not spec:
        return df

    for col, dt in spec.items():
        if col not in df.columns:
            df[col] = _empty_series_for_dtype(dt)

    for col, dt in spec.items():
        if dt == "string":
            df[col] = df[col].astype("string")
        elif dt.startswith("datetime"):
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif dt in ("Int64", "Int32", "Int16"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(dt)
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col, dt in spec.items():
        if dt == "string":
            df[col] = df[col].fillna("")

    ordered = list(spec.keys()) + [c for c in df.columns if c not in spec]
    return df[ordered]

# ---------- Snapshotting ----------
def snapshot_table(table: str) -> Optional[Path]:
    """Dump entire table to a timestamped Parquet file with stable schema."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PARQUET_ROOT / table
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"snapshot_{ts}.parquet"

    df = pd.read_sql(f"SELECT * FROM `{table}`", engine)

    if df.empty:
        spec = EXPECTED_DTYPES.get(table, {})
        if spec:
            df = pd.DataFrame({c: _empty_series_for_dtype(dt) for c, dt in spec.items()})

    df = coerce_dtypes(table, df)

    # Requires 'pyarrow' or 'fastparquet'. Prefer 'pyarrow' in requirements.
    df.to_parquet(out_path, index=False)
    return out_path

def enforce_retention(table: str, keep: int = RETENTION) -> None:
    """Keep only the newest 'keep' snapshots, delete older ones."""
    out_dir = PARQUET_ROOT / table
    if not out_dir.exists():
        return
    files = sorted(
        [p for p in out_dir.glob("snapshot_*.parquet") if p.is_file()],
        key=lambda p: p.name,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
        except Exception:
            pass  # ignore

# ---------- Public API ----------
def refresh_once(verbose: bool = True, *, force: bool = False) -> None:
    any_change = False
    for table in TABLES:
        prev_state = load_state(table)
        current = get_table_metrics(table)

        if not current.get("exists", False):
            if verbose:
                print(f"[skip] table '{table}' not found in schema '{DB_NAME}'")
            save_state(table, {"exists": False, "count": 0, "max_updated_at": None})
            continue

        if verbose:
            print(f"[{table}] current={{'count': {current['count']}, 'max_updated_at': {current['max_updated_at']}}} "
                  f"prev={prev_state}")

        if force or table_changed(table, prev_state, current):
            any_change = True
            fp = snapshot_table(table)
            enforce_retention(table, RETENTION)
            save_state(table, {"count": current["count"], "max_updated_at": current["max_updated_at"]})
            if verbose:
                print(f"  → snapshotted to {fp.name}; retention kept {RETENTION}")
        else:
            if verbose:
                print("  → no change; skip snapshot")

    if verbose and not any_change and not force:
        print("No tables changed. Nothing to do.")

def run_daemon(force: bool = False) -> None:
    print(f"Starting daemon: polling every {POLL_SECONDS}s … Ctrl+C to stop.")
    while True:
        try:
            refresh_once(verbose=True, force=force)
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("Stopping daemon.")
            break
        except Exception as e:
            print("Error in loop:", e)
            time.sleep(POLL_SECONDS)

# ---------- CLI ----------
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Snapshot MySQL tables to Parquet with retention.")
    ap.add_argument("--once", action="store_true", help="Run one refresh pass and exit.")
    ap.add_argument("--daemon", action="store_true", help="Run forever, polling every N seconds.")
    ap.add_argument("--force", action="store_true", help="Force a fresh snapshot even if nothing changed.")
    args = ap.parse_args()

    if args.daemon:
        run_daemon(force=args.force)
    else:
        refresh_once(verbose=True, force=args.force)
