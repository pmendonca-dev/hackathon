#!/usr/bin/env bash
# Start the Telegram bot against the local API, reading .env for the token.
#
# The bot itself never loads .env — BotConfig reads os.environ and nothing else,
# so the file is sourced here. Existing bot processes are killed first: two
# pollers on one token make Telegram hand each update to whichever asked last,
# and half the taps in a demo silently vanish.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python

[ -f .env ] || { echo "falta .env com TELEGRAM_BOT_TOKEN" >&2; exit 1; }
set -a; . ./.env; set +a

powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'aval.interfaces.telegram' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" 2>/dev/null || true

curl -sf -m 5 "${AVAL_API_BASE_URL}/health" >/dev/null || {
  echo "API não responde em ${AVAL_API_BASE_URL} — rode scripts/dev_up.sh primeiro" >&2
  exit 1
}

nohup "$PY" -m aval.interfaces.telegram >> bot.log 2>&1 &
sleep 3
grep -q "online" bot.log && tail -2 bot.log || { echo "o bot não subiu:"; tail -20 bot.log; exit 1; }
