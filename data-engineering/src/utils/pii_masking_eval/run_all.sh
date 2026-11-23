#!/usr/bin/env bash
# Runs the whole #585 evaluation locally.
#   ./run_all.sh                       # clones the repo for users.csv, runs approaches 1, 2, 4
#   ./run_all.sh /path/to/users.csv    # use your own copy of users.csv
#   RUN_COMPREHEND=1 ./run_all.sh      # also run approach 3 (needs boto3 + AWS creds with comprehend:DetectPiiEntities)
#   CHECK_PRESIDIO=1 ./run_all.sh      # also measure Presidio's install size (downloads ~300 MB)
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

USERS_CSV=${1:-}
if [ -z "$USERS_CSV" ]; then
  # 1) users.csv in the surrounding repo (data-engineering/src/utils/pii_masking_eval -> data-analytics/sql)
  IN_REPO="../../../../data-analytics/sql/users.csv"
  if [ -f "$IN_REPO" ]; then
    USERS_CSV="$IN_REPO"
  else
    # 2) otherwise clone OUTSIDE any git repo so nothing gets committed by accident
    CLONE_DIR="${TMPDIR:-/tmp}/saayam_data_repo"
    if [ ! -d "$CLONE_DIR" ]; then
      echo ">> cloning saayam-for-all/data (shallow) to $CLONE_DIR to get users.csv"
      git clone --depth 1 https://github.com/saayam-for-all/data.git "$CLONE_DIR"
    fi
    USERS_CSV="$CLONE_DIR/data-analytics/sql/users.csv"
  fi
fi
echo ">> using users.csv: $USERS_CSV"
[ -f "$USERS_CSV" ] || { echo "users.csv not found: $USERS_CSV"; exit 1; }

echo ">> offline unit tests for the Comprehend wrapper (fake client, no AWS)"
$PY -m unittest discover -s tests

echo; echo ">> approaches 1, 2, 4 on the labelled test set"
$PY -I run_eval.py "$USERS_CSV" out

echo; echo ">> extra false-positive probes for approach 4"
$PY -I fp_probe.py "$USERS_CSV"
echo; $PY -I fresh_probe.py "$USERS_CSV"

if [ "${RUN_COMPREHEND:-0}" = "1" ]; then
  echo; echo ">> approach 3: Amazon Comprehend (uses your AWS credentials, small cost/free tier)"
  $PY -m pip install --quiet boto3
  mkdir -p out
  $PY run_comprehend.py out/comprehend_spans.json "${AWS_REGION:-us-east-1}"
  $PY -I run_eval.py "$USERS_CSV" out out/comprehend_spans.json
fi

if [ "${CHECK_PRESIDIO:-0}" = "1" ]; then
  echo; echo ">> Presidio size check"
  rm -rf /tmp/presidio_probe && mkdir -p /tmp/presidio_probe
  $PY -m pip install --quiet --target /tmp/presidio_probe presidio-analyzer
  du -sm /tmp/presidio_probe   # Lambda limit is 250 MB unzipped
fi

echo; echo "Done. Results: out/results.json, out/details_*.txt (every miss / false positive), out/redacted_samples.json"
