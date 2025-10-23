DISBURSEMENT      = "disbursement"
RECEIPT           = "receipt"
MEMBERS           = "members"
BRANCH            = "branch"

PRINCIPAL_RECEIVED = "principal_received"
INTEREST_RECEIVED  = "interest_received"
PENALTY_RECEIVED   = "penalty_received"

FILE_HASHES       = "file_hashes"
LAST_UPLOAD       = "last_upload"
UPLOAD_SUMMARY    = "upload_summary"

# --- backward-compatible aliases (keep old code working) ---
# tables
DISBURSMENT = DISBURSEMENT          # old misspelling
MEMBER      = MEMBERS               # singular -> plural

# metrics
PRINCIPAL_RECIVED = PRINCIPAL_RECEIVED  # misspelling
INTERST_RECEIVED  = INTEREST_RECEIVED   # misspelling

# meta
FILE_HASES  = FILE_HASHES               # misspelling
LAST_upload = LAST_UPLOAD               # mixed case
