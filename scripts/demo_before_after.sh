#!/usr/bin/env bash
# Before -> after -> replay demo for Agent Black Box.
#
#   Terminal 1: python -m copilot.webhook_server
#   Terminal 2: ./scripts/demo_before_after.sh
#
# Story:
#   1. v1 (no retry budget) hits a retry storm -> alert fires -> copilot RCA.
#   2. We apply the copilot's fix (retry budget + fallback) as v2.
#   3. v2 replays the SAME scenario: 3 retries, graceful ticket, no storm.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "==============================================="
echo " BEFORE  —  v1, no retry budget (the bug)"
echo "==============================================="
for i in 1 2 3; do AGENT_VERSION=v1 RETRY_BUDGET=0 python -m src.main run retry_storm 2>&1 \
  | grep -E "failure_mode:|response:"; done
echo
echo ">> v1 sessions burn ~11 retries each and fail with failure_mode=retry_storm."
echo ">> The 'Agent retry storm' alert fires and the SRE copilot posts an RCA at :8099."
echo

echo "==============================================="
echo " AFTER  —  v2, retry budget + fallback (the fix)"
echo "==============================================="
for i in 1 2 3; do AGENT_VERSION=v2 RETRY_BUDGET=3 python -m src.main run retry_storm 2>&1 \
  | grep -E "failure_mode:|response:"; done
echo
echo ">> v2 sessions stop after 3 retries and open a support ticket (graceful)."
echo ">> failure_mode=none, retries below the threshold of 5 -> the alert resolves."
echo
echo "In SigNoz: split any panel by service.version to see v1 (failing) vs v2 (clean),"
echo "and watch the retry-storm alert move from firing -> resolved as v1 data ages out."
