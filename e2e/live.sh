#!/bin/sh
# Owner-operated MacBook check. Never enable shell tracing here.
set -eu
cd "$(dirname "$0")/.."
phub=${PREVIEW_HUB_DIR:-$HOME/Project/cafitac/portfolio/preview-hub}/scripts/phub-remote
cap=${AIQA_CALL_CAP:-30}
case $cap in ''|*[!0-9]*) echo 'AIQA_CALL_CAP must be a nonnegative integer' >&2; exit 2;; esac
[ -x "$phub" ] || { echo 'preview-hub scripts/phub-remote is missing' >&2; exit 2; }
[ -x .venv/bin/python ] || { echo 'Run uv sync first' >&2; exit 2; }
work=$(mktemp -d)
short=$(date -u +%s)-$$
ok=qa-ok-$short
broken=qa-broken-$short
missing=aiqa-missing-$(date -u +%s)
created_ok=0
created_broken=0
calls=0
check() { .venv/bin/python e2e/check.py "$@"; }
# Polls are bounded: down is asynchronous, so wait for the name to leave the list,
# then for the inventory to report empty. Output is never printed.
gone() {
    tries=0
    while [ "$tries" -lt 60 ]; do
        if "$phub" list > "$work/list.json" 2>/dev/null &&
            ! grep -Fq "\"$1\"" "$work/list.json"; then return 0; fi
        tries=$((tries + 1))
        sleep 5
    done
    return 1
}
empty() {
    tries=0
    while [ "$tries" -lt 12 ]; do
        "$phub" inventory "$1" --expect-empty > /dev/null 2>&1 && return 0
        tries=$((tries + 1))
        sleep 5
    done
    return 1
}
cleanup() {
    code=$?
    trap - EXIT HUP INT TERM
    for entry in "$ok:$created_ok" "$broken:$created_broken"; do
        name=${entry%:*}
        created=${entry##*:}
        [ "$created" -eq 1 ] || continue
        if "$phub" down "$name" > /dev/null 2>&1 && gone "$name" && empty "$name"; then
            printf 'cleanup: %s absent inventory=empty\n' "$name"
        else
            printf 'cleanup FAILED: %s; owner must retry phub-remote down/inventory --expect-empty\n' "$name" >&2
            code=1
        fi
    done
    printf 'agent calls (attempt directories): %s\n' "$calls"
    rm -rf "$work"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
if ! uv run aiqa doctor > "$work/doctor" 2>&1; then
    echo 'Doctor failed: owner must run uv run aiqa login and check CLI/browser dependencies.' >&2
    exit 3
fi
# Doctor checks presence and permissions; run preflight checks expiry.
check config "$work/normal.yaml" "$work/capped.yaml"
runs_dir=$(check runs-dir "$work/normal.yaml")
mkdir -p "$runs_dir"
reserve() {
    [ "$((calls + $1))" -le "$cap" ] || {
        printf 'Call cap: %s used; step needs at most %s; cap=%s\n' "$calls" "$1" "$cap" >&2
        exit 1
    }
}
run() {
    expected=$1
    env=$2
    config=$3
    shift 3
    reserve "$(check reservation "$config" "$@")"
    rc=0
    uv run aiqa run "$env" --config "$config" --agent claude "$@" > "$work/run-output" 2>&1 || rc=$?
    # Unique environment names; B5 waits a second before reusing the ok name.
    run_dir=$(find "$runs_dir" -maxdepth 1 -type d -name "$env-*" | LC_ALL=C sort | tail -n 1)
    [ -n "$run_dir" ] || { echo 'No run directory written' >&2; exit 1; }
    count=$(find "$run_dir/scenarios" -mindepth 2 -maxdepth 2 -type d -name 'attempt-*' 2>/dev/null | wc -l | tr -d ' ')
    calls=$((calls + count))
    [ "$calls" -le "$cap" ] || { echo 'Agent call cap exceeded' >&2; exit 1; }
    [ "$rc" -eq "$expected" ] || { printf 'Unexpected exit: %s (expected %s)\n' "$rc" "$expected" >&2; exit 1; }
}
ready() {
    # wait-ready exits 0 only for READY with every service healthy (5 FAILED/DELETED, 6 timeout).
    "$phub" wait-ready "$1" --timeout 600 --interval 5 > "$work/status.json" 2>/dev/null || {
        echo 'Environment did not reach READY within 600 seconds' >&2
        exit 1
    }
}
reserve 0
run 3 "$missing" "$work/normal.yaml"
check B3 "$run_dir"
printf 'B3: REFUSED environment_not_ready; calls=0\n'
reserve "$(check reservation "$work/normal.yaml")"
created_ok=1
"$phub" up "$ok" --set backend=main --set frontend=main --ttl 1h > /dev/null 2>&1
ready "$ok"
run 0 "$ok" "$work/normal.yaml"
ok_run=$run_dir
check B1 "$ok_run" "$work/status.json"
printf 'B1: two PASSED; schema/screenshots/commits verified; %s\n' "$ok_run"
reserve "$(check reservation "$work/normal.yaml")"
created_broken=1
"$phub" up "$broken" --set backend=e2e-broken-add-note --set frontend=main --ttl 1h > /dev/null 2>&1
ready "$broken"
run 1 "$broken" "$work/normal.yaml"
broken_run=$run_dir
check B2 "$broken_run"
printf 'B2: seed PASSED; add-note FAILED; %s\n' "$broken_run"
scan() {
    hits=0
    rc=0
    # -l prints filenames only; -a scans binary screenshots too. Never print matches.
    grep -aElr 'CF_Authorization|CF_AppSession|CF_Binding|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_' "$1" > "$work/hits" 2>/dev/null || rc=$?
    [ "$rc" -le 1 ] || { echo 'Secret scan failed' >&2; exit 1; }
    hits=$(wc -l < "$work/hits" | tr -d ' ')
    printf 'B4: %s matching files=%s\n' "$1" "$hits"
    [ "$hits" -eq 0 ] || exit 1
}
scan "$ok_run"
scan "$broken_run"
sleep 1
run 1 "$ok" "$work/capped.yaml" --only frontend/seed-notes-listed
check B5 "$run_dir"
scan "$run_dir"
printf 'Live check passed; evidence retained under %s\n' "$runs_dir"
