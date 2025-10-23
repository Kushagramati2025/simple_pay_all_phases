# simple_pay/tools/config_paths.py

from pathlib import Path

import os

import tempfile
 
# Choose a safe default cache directory

_env_root = os.getenv("SIMPLEPAY_CACHE_DIR")
 
if _env_root:

    PARQUET_ROOT = Path(_env_root).expanduser().resolve()

else:

    # Use AppData if available, otherwise system temp

    user_local = Path.home() / "AppData" / "Local"

    if user_local.exists():

        PARQUET_ROOT = user_local / "simple_pay" / "local_cache"

    else:

        PARQUET_ROOT = Path(tempfile.gettempdir()) / "simple_pay_cache"
 
# Ensure the directory exists

PARQUET_ROOT.mkdir(parents=True, exist_ok=True)
 
# Optional: fail fast if not writable

if not os.access(PARQUET_ROOT, os.W_OK):

    raise PermissionError(f"Cache directory is not writable: {PARQUET_ROOT}")
 
# Define subdirectories for each table

DISB_DIR = (PARQUET_ROOT / "disbursement").as_posix()

RECV_DIR = (PARQUET_ROOT / "receipt").as_posix()

MEMB_DIR = (PARQUET_ROOT / "members").as_posix()

BRANCH_DIR = (PARQUET_ROOT / "branch").as_posix()
 
# Define glob patterns (Parquet snapshot naming convention)

DISB_GLOB = f"{DISB_DIR}/snapshot_*.parquet"

RECV_GLOB = f"{RECV_DIR}/snapshot_*.parquet"

MEMB_GLOB = f"{MEMB_DIR}/snapshot_*.parquet"

BRANCH_GLOB = f"{BRANCH_DIR}/snapshot_*.parquet"

 