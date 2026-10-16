#!/usr/bin/env sh
# Post-deploy smoke test: health and readiness, one planner turn, and confirmation that the data directory is not exposed.
# Usage: scripts/smoke.sh https://railsaathi-backend-xxxx.a.run.app
set -eu

BASE="${1:?usage: smoke.sh <backend-base-url>}"
BASE="${BASE%/}"

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "$1 is required"; }
need curl

echo "1) health and readiness"
HEALTH="$(curl -fsS --max-time 15 "$BASE/api/health")" || fail "health request failed"
echo "$HEALTH" | grep -q '"status":"ok"' || fail "health status not ok: $HEALTH"
READY="$(curl -sS --max-time 15 "$BASE/readyz")" || fail "readiness request failed"
echo "$READY" | grep -q '"status":"ready"' || fail "not ready: $READY"

echo "2) planner turn"
SESSION="$(curl -fsS --max-time 15 -H 'Content-Type: application/json' -d '{"language":"en"}' "$BASE/api/planner/sessions")" \
  || fail "session creation failed"
SESSION_ID="$(printf '%s' "$SESSION" | sed -n 's/.*"session_id":"\([^"]*\)".*/\1/p')"
[ -n "$SESSION_ID" ] || fail "no session_id in response: $SESSION"
# Planner routes need the signed token issued with the session (X-Session-Token).
SESSION_TOKEN="$(printf '%s' "$SESSION" | sed -n 's/.*"session_token":"\([^"]*\)".*/\1/p')"
[ -n "$SESSION_TOKEN" ] || fail "no session_token in response"
REPLY="$(curl -fsS --max-time 20 -H 'Content-Type: application/json' -H "X-Session-Token: $SESSION_TOKEN" \
  -d '{"message":"I need to reach Chennai before 9 AM tomorrow from Coimbatore","language":"en"}' \
  "$BASE/api/planner/sessions/$SESSION_ID/messages")" || fail "planner message failed"
printf '%s' "$REPLY" | grep -q '"status"' || fail "unexpected planner reply: $REPLY"

echo "3) data directory is not served"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$BASE/data/knowledge/railsaathi.db")"
[ "$CODE" = "404" ] || fail "expected 404 for /data/knowledge/railsaathi.db, got $CODE"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$BASE/api/stations/chennai_central/map")"
[ "$CODE" = "200" ] || fail "expected 200 for station map asset, got $CODE"

echo "SMOKE OK: $BASE"
