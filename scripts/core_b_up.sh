#!/usr/bin/env bash
# Computer B: migrations, the AVAL API, the watch scheduler and Stripe.
#
# Reads .env.core, never .env.edge. B has no business holding the Telegram token or the
# OpenAI key: it is the half that can move money, and the half most worth attacking. It
# does not reach the open web at all — when a watch needs candidates it asks A, over a
# signed request, and treats the answer as untrusted data.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python

[ -f .env.core ] || {
  echo "falta .env.core — veja docs/verification/two-computer-telegram-rehearsal.md" >&2
  exit 1
}
set -a; . ./.env.core; set +a

for forbidden in TELEGRAM_BOT_TOKEN OPENAI_API_KEY; do
  if [ -n "${!forbidden:-}" ]; then
    echo "recusado: $forbidden é segredo do computador A e está no ambiente de B" >&2
    exit 2
  fi
done

: "${AVAL_EDGE_TO_CORE_SECRET:?AVAL_EDGE_TO_CORE_SECRET é obrigatória em B}"
: "${AVAL_CORE_TO_EDGE_SECRET:?AVAL_CORE_TO_EDGE_SECRET é obrigatória em B}"
: "${AVAL_DISCOVERY_EDGE_URL:?AVAL_DISCOVERY_EDGE_URL tem de apontar para o computador A}"
# Without a stable seed every boot draws new keys while the database keeps the old
# public halves, and every purchase after the first restart dies as signature_invalid.
: "${AVAL_CUSTODY_SEED:?AVAL_CUSTODY_SEED é obrigatória: sem ela um restart invalida as identidades}"

if [ "${AVAL_PSP:-demo}" = "stripe" ]; then
  : "${AVAL_STRIPE_SECRET_KEY:?AVAL_PSP=stripe exige AVAL_STRIPE_SECRET_KEY}"
  case "$AVAL_STRIPE_SECRET_KEY" in
    sk_live_*) echo "recusado: chave de produção da Stripe. Use sk_test_." >&2; exit 2 ;;
  esac
fi

# Migrations own the schema. Running them here means a restart on a database written by
# an older revision is a loud failure now instead of a confusing one at the first write.
"$PY" -m alembic upgrade head

# Without an interval no watch ever fires by itself, and the standing order the person
# armed is registered, alive, and never asked.
: "${AVAL_WATCH_TICK_SECONDS:=30}"
export AVAL_WATCH_TICK_SECONDS

exec "$PY" -m uvicorn aval.main:app \
  --host "${AVAL_HOST:-127.0.0.1}" --port "${AVAL_PORT:-8099}"
