#!/usr/bin/env bash
# Computer A: the discovery edge and the Telegram bot. Nothing that can spend.
#
# Reads .env.edge, never .env.core. That is the whole point of two files: a process
# cannot leak a secret it was never handed, and the surest way not to hand it over is
# not to have it in the environment. The Python entrypoint checks again before it
# listens, because a launcher is a convenience and the process is the boundary.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python

[ -f .env.edge ] || {
  echo "falta .env.edge — veja docs/verification/two-computer-telegram-rehearsal.md" >&2
  exit 1
}
set -a; . ./.env.edge; set +a

for forbidden in AVAL_STRIPE_SECRET_KEY AVAL_CUSTODY_SEED AVAL_OPERATOR_TOKEN AVAL_OPERATOR_AUTHORITY_SEED; do
  if [ -n "${!forbidden:-}" ]; then
    echo "recusado: $forbidden é segredo do computador B e está no ambiente de A" >&2
    exit 2
  fi
done

: "${AVAL_CORE_TO_EDGE_SECRET:?AVAL_CORE_TO_EDGE_SECRET é obrigatória em A}"
: "${AVAL_EDGE_TO_CORE_SECRET:?AVAL_EDGE_TO_CORE_SECRET é obrigatória em A}"
: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN é obrigatório em A}"
: "${AVAL_API_BASE_URL:?AVAL_API_BASE_URL tem de apontar para o computador B}"

# B has to be answering before the bot takes its first /start, or the first person to
# tap sees a raw error instead of a mandate.
curl -sf -m 5 "${AVAL_API_BASE_URL}/health" >/dev/null || {
  echo "o núcleo não responde em ${AVAL_API_BASE_URL} — suba o computador B primeiro" >&2
  exit 1
}

# Two pollers on one Telegram token make the API hand each update to whichever asked
# last, and half the taps in a demo vanish silently.
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'aval.interfaces.(telegram|discovery)' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" 2>/dev/null || true

nohup "$PY" -m aval.interfaces.discovery >> discovery.log 2>&1 &
sleep 2
grep -q "ponta de descoberta" discovery.log || { echo "a ponta de descoberta não subiu:"; tail -20 discovery.log; exit 1; }

nohup "$PY" -m aval.interfaces.telegram >> bot.log 2>&1 &
sleep 3
grep -q "online" bot.log && tail -2 bot.log || { echo "o bot não subiu:"; tail -20 bot.log; exit 1; }

echo "computador A de pé: descoberta + bot, contra o núcleo em ${AVAL_API_BASE_URL}"
