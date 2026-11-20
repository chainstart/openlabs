#!/bin/sh
# Run in WSL as the user that owns openlabs-remote-bridge.service.
# Finds the bridge.py the service actually runs. If that is this checkout, it only
# restarts the service; if it is a separate copy, it backs the copy up beside itself,
# installs this checkout's bridge.py/protocol.py over it, then restarts.
# Restarting does not touch jobs on ailab: their systemd units keep running and the new
# bridge re-attaches to every job whose status is "running".
set -eu
unit=openlabs-remote-bridge.service
here=$(cd "$(dirname "$0")" && pwd)
grep -q 'class Dispatcher' "$here/bridge.py" || { echo "this checkout lacks the fixed bridge" >&2; exit 1; }
exec_line=$(systemctl --user show -p ExecStart --value "$unit")
target=$(printf '%s\n' "$exec_line" | tr ' ;' '\n\n' | sed 's/^[a-z_]*\(\[\]\)\{0,1\}=//' | grep 'bridge\.py$' | head -n 1)
[ -n "$target" ] || { echo "cannot find bridge.py in ExecStart: $exec_line" >&2; exit 1; }
case "$target" in /*) ;; *) echo "relative bridge path in unit: $target" >&2; exit 1;; esac
real_target=$(readlink -f "$target")
if [ "$real_target" = "$(readlink -f "$here/bridge.py")" ]; then
  echo "service runs this checkout directly: $target"
else
  dir=$(dirname "$real_target")
  backup="$dir/backup-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$backup"
  for f in bridge.py protocol.py; do [ -f "$dir/$f" ] && cp -p "$dir/$f" "$backup/$f"; done
  install -m 644 "$here/bridge.py" "$here/protocol.py" "$dir/"
  echo "installed into $dir (previous copy kept in $backup)"
fi
systemctl --user restart "$unit"
sleep 3
systemctl --user --no-pager status "$unit" | head -n 12
