#!/usr/bin/env bash
# Install the Hackmash sync job as a systemd user timer on this machine (the home server).
#
#   deploy/home-server/install.sh            install or update, and start the timer
#   deploy/home-server/install.sh --now      ... and run one sync straight away
#
# Needs: uv, systemd, and ~/.config/hackmash/sync.env (see sync.env.example).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
env_file="$HOME/.config/hackmash/sync.env"
units="$HOME/.config/systemd/user"

uv="$(command -v uv || true)"
[ -z "$uv" ] && [ -x "$HOME/.local/bin/uv" ] && uv="$HOME/.local/bin/uv"
if [ -z "$uv" ]; then
  echo "uv is not installed: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [ ! -f "$env_file" ] || ! grep -q '^HACKMASH_INGEST_KEY=..*' "$env_file"; then
  mkdir -p "$(dirname "$env_file")"
  [ -f "$env_file" ] || sed "s#/home/YOU#$HOME#" "$here/sync.env.example" > "$env_file"
  chmod 600 "$env_file"
  echo "Put the Worker's INGEST_KEY into $env_file (HACKMASH_INGEST_KEY=...), then run this again." >&2
  exit 1
fi
chmod 600 "$env_file"

data_dir="$(sed -n 's/^HACKMASH_DATA_DIR=//p' "$env_file")"
[ -n "$data_dir" ] && mkdir -p "$data_dir"

echo "installing dependencies…"
(cd "$repo/backend" && "$uv" sync --frozen --no-dev --extra og --quiet)
echo "installing the headless browser that draws link-preview posters (once, ~100 MB)…"
(cd "$repo/backend" && "$uv" run --frozen --no-dev --extra og playwright install chromium --only-shell)

mkdir -p "$units"
sed -e "s#@REPO@#$repo#g" -e "s#@UV@#$uv#g" "$here/hackmash-sync.service" > "$units/hackmash-sync.service"
cp "$here/hackmash-sync.timer" "$units/hackmash-sync.timer"
systemctl --user daemon-reload
systemctl --user enable --now hackmash-sync.timer

if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo "note: run 'sudo loginctl enable-linger $USER' so the timer runs while you're logged out"
fi
if [ "${1:-}" = "--now" ]; then
  echo "running one sync now (follow it with: journalctl --user -fu hackmash-sync)…"
  systemctl --user start hackmash-sync.service
fi
systemctl --user list-timers hackmash-sync.timer --no-pager
