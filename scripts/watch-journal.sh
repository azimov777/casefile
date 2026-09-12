#!/bin/sh
# TEMPORARY SAMPLE — not a supported part of Casefile. It is not wired into any
# docker-compose*.yml, it writes nothing to the tracker, and it has no idea
# whether the agent it is watching for is alive. A harness with its own way to
# learn about news (a background watcher, a hook) needs none of this — see
# docs/agent-install.md, "Learn about news in your tasks", for the recipe this
# script only demonstrates.
#
# Long-polls GET /api/v1/journal, one request per watched task, and prints one
# line "<seq> <task> <title>" per new entry to stdout as it arrives.
#
# Usage:
#   WATCH_TASKS=TRK-77,TRK-75 TRACKER_URL=http://localhost:8000 \
#     TRACKER_TOKEN_FILE=/path/to/token ./scripts/watch-journal.sh [after]
#
# TRACKER_TOKEN_FILE must hold nothing but the bearer token: it is read once
# into memory and never appears on the command line or in any output.
set -eu

: "${TRACKER_URL:?tracker API base, e.g. http://localhost:8000}"
: "${TRACKER_TOKEN_FILE:?file holding the bearer token}"
: "${WATCH_TASKS:?comma-separated task keys, e.g. TRK-77,TRK-75}"
after=${1:-0}                # seq to resume from; 0 replays the whole case
wait_s=${WAIT_SECONDS:-30}   # long-poll seconds per task per round, max 60

token=$(cat "$TRACKER_TOKEN_FILE")
state=$(mktemp -d)
cleanup() { rm -rf "$state"; }
trap cleanup EXIT
trap 'exit 0' INT TERM
tab=$(printf '\t')

tasks=$(printf '%s' "$WATCH_TASKS" | tr ',' ' ')
for task in $tasks; do echo "$after" >"$state/$task"; done

while :; do
  for task in $tasks; do
    since=$(cat "$state/$task")
    body=$(curl -sf --max-time $((wait_s + 10)) -H "Authorization: Bearer $token" \
      "$TRACKER_URL/api/v1/journal?task=$task&after=$since&wait=$wait_s&limit=100") ||
      { sleep 2; continue; }
    printf '%s' "$body" | grep -o '"seq":[0-9]*' | cut -d: -f2 >"$state/$task.seq"
    printf '%s' "$body" | grep -o '"title":"[^"]*"' | cut -d'"' -f4 >"$state/$task.title"
    [ -s "$state/$task.seq" ] || continue
    paste -d "$tab" "$state/$task.seq" "$state/$task.title" |
      while IFS="$tab" read -r seq title; do
        printf '%s %s %s\n' "$seq" "$task" "$title"
      done
    tail -n 1 "$state/$task.seq" >"$state/$task"
  done
done
