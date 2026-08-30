#!/usr/bin/env bash
# Bring the whole demo up on localhost, exactly once.
#
# The reason this exists rather than two remembered command lines: restarting by hand
# leaves the old uvicorn holding :8099, so the browser talks to yesterday's code while
# the new log file stays empty and every symptom points at the wrong place. This kills
# what is listening first, then starts one API and one Vite, and refuses to claim
# success before /health answers.
#
#   bash scripts/dev_up.sh          # API + web
#   bash scripts/dev_up.sh --fresh  # ...after wiping the dev database
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
# The processor and its key live in .env, which is gitignored. Sourced rather than
# hardcoded: a secret in a tracked script is a secret already leaked.
[ -f .env ] && { set -a; . ./.env; set +a; }
export AVAL_OPERATOR_TOKEN=${AVAL_OPERATOR_TOKEN:-demo-token}
# Without this the trial-by-fire console's tamper panel 404s. It is a judge surface, so
# on a demo host it is on; nothing else in the system turns it on for you.
export AVAL_DEMO_TAMPER=1

# Killing by port alone is not enough: --reload leaves a supervisor that re-binds, and
# SQLite keeps the file handle a moment after the process is asked to go. So: kill every
# uvicorn for this app by command line, then wait for the port to actually come free.
kill_uvicorn() {
  # `-eq 'python.exe'` matters: without it the filter also matches the shell that is
  # running this script, because its own command line contains this very string.
  powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.Name -eq 'python.exe' -and \$_.CommandLine -like '*uvicorn*aval.main:app*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1 || true
  pkill -f 'uvicorn aval.main:app' >/dev/null 2>&1 || true
}
port_free() {
  ! netstat -ano 2>/dev/null | grep ":$1 " | grep -qi listening
}
kill_port() {
  local pid
  pid=$(netstat -ano 2>/dev/null | grep ":$1 " | grep -i listening | awk '{print $NF}' | head -1 || true)
  if [ -n "${pid:-}" ]; then
    taskkill //PID "$pid" //T //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null || true
  fi
}

kill_uvicorn
kill_port 8099
kill_port 5173
for _ in $(seq 1 15); do
  if port_free 8099; then break; fi
  sleep 1
  kill_port 8099
done
port_free 8099 || { echo "algo ainda escuta na 8099 e não morreu"; exit 1; }
# The handle can outlive the process by a beat; deleting the file while it is held is
# exactly the failure that leaves --fresh running on yesterday's database.
sleep 1

if [ "${1:-}" = "--fresh" ]; then
  # `metadata.create_all` adds tables but never columns, so a dev database from before a
  # migration is not behind — it is wrong, and fails with `no such column` much later.
  rm -f var/aval.db var/aval.db-shm var/aval.db-wal .aval/runtime.sqlite3
  # The bot's chat directory has to go with it. Keeping it would leave every chat
  # pointing at a mandate id this runtime no longer has — which is not an empty demo,
  # it is a demo that greets each judge with "mandato não encontrado".
  rm -f var/telegram-identities.json
  echo "banco de dev e chats do bot apagados"
fi

nohup "$PY" -m uvicorn aval.main:app --port 8099 > api.log 2>&1 < /dev/null &
(cd web && VITE_AVAL_API_BASE_URL=http://127.0.0.1:8099 \
  VITE_AVAL_OPERATOR_TOKEN="$AVAL_OPERATOR_TOKEN" \
  npm run dev -- --port 5173 --strictPort > ../web.log 2>&1 &)

for _ in $(seq 1 30); do
  if curl -sf -m 2 http://127.0.0.1:8099/health >/dev/null; then break; fi
  sleep 1
done
curl -sf -m 2 http://127.0.0.1:8099/health >/dev/null || { echo "API não subiu — veja api.log"; tail -20 api.log; exit 1; }

echo "API  http://127.0.0.1:8099/docs"
echo "Web  http://localhost:5173   (Vite escuta em IPv6: use localhost, não 127.0.0.1)"
