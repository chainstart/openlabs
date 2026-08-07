#!/usr/bin/env bash
set -euo pipefail

# The 5-GiB default is for Python and light tools.  Mathlib probe compilation
# needs `AMRA_MEMORY_KIB=12582912` on this WSL image and must be globally
# serialized; the campaign round manifest records that policy.
memory_kib="${AMRA_MEMORY_KIB:-5242880}"
timeout_seconds="${AMRA_TIMEOUT_SECONDS:-1800}"

if [[ "$#" -eq 0 ]]; then
  echo "usage: run_bounded.sh COMMAND [ARG ...]" >&2
  exit 2
fi

ulimit -v "$memory_kib"
export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}"
export LEAN_NUM_THREADS="${LEAN_NUM_THREADS:-2}"

exec timeout --signal=TERM --kill-after=15s "$timeout_seconds" "$@"
