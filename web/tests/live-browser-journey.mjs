/**
 * The browser lane, end to end, against a real AVAL server.
 *
 * Everything here is exactly what the page does: the same gateway class, the same
 * WebCrypto wallet, the same signed payloads. If this passes, a judge sitting in front
 * of the browser can create a mandate, watch the agent buy, approve an escalation,
 * move the limit and revoke — all with signatures the server never held a key for.
 *
 * Run with a server up:
 *   AVAL_OPERATOR_TOKEN=demo-token AVAL_DEMO_TAMPER=1 uvicorn aval.main:app --port 8137
 *   node --experimental-strip-types tests/live-browser-journey.mjs http://127.0.0.1:8137
 */


import { AuthorizationGateway } from '../src/gateways/authorizationGateway.ts';
import { generateHolderKeyPair, signCompactJws } from '../src/wallet/holderKey.ts';
import { mandateCreationClaims } from '../src/wallet/mandateCreation.ts';

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:8137';
const principalId = `usr_browser_${Date.now()}`;

const gateway = new AuthorizationGateway({
  baseUrl,
  operatorToken: process.env.AVAL_OPERATOR_TOKEN ?? 'demo-token',
});

const steps = [];
function check(label, condition, detail = '') {
  steps.push({ label, ok: Boolean(condition), detail });
  console.log(`${condition ? '  ok  ' : ' FAIL '} ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) process.exitCode = 1;
}

const wallet = await generateHolderKeyPair(`${principalId}_browser_k1`);

// 1 — the holder creates a mandate, registering this browser's public key.
const created = await gateway.createMandate({
  principal: { id: principalId, display_name: 'Marta Silva' },
  allowed_merchant_ids: ['vuelaya'],
  allowed_categories: ['travel'],
  limit: { minor_units: 20000, currency: 'USD', scale: 2 },
  ceiling: { minor_units: 50000, currency: 'USD', scale: 2 },
  expires_at: '2027-09-30T23:59:59Z',
  usage_limit: { max_uses: 3, window_seconds: 2592000 },
  authorities: [
    {
      kid: wallet.kid,
      role: 'holder',
      public_jwk: wallet.publicJwk,
      allowed_scopes: ['mandate', 'budget:zero'],
    },
  ],
  // The mandate is born signed by the key that will be able to revoke it, so the trail
  // starts at the holder's own consent instead of at someone's claim about it.
  creation_jws: await signCompactJws(
    mandateCreationClaims({
      principal: { id: principalId, display_name: 'Marta Silva' },
      allowed_merchant_ids: ['vuelaya'],
      allowed_categories: ['travel'],
      limit: { minor_units: 20000, currency: 'USD', scale: 2 },
      ceiling: { minor_units: 50000, currency: 'USD', scale: 2 },
      expires_at: '2027-09-30T23:59:59Z',
      usage_limit: { max_uses: 3, window_seconds: 2592000 },
    }),
    wallet,
  ),
});
const mandateId = created.mandate_id;
check('o navegador cria um mandato com a própria chave', Boolean(mandateId), mandateId);

// 2 — the listing the sidebar reads. Signed by this browser's own key: the principal id
// in the URL is a guessable name, so the key is what decides which mandates come back.
const readToken = await signCompactJws({ principal_id: principalId }, wallet);
const listed = await gateway.listMandates(principalId, readToken);
check(
  'a listagem escopada devolve o mandato',
  listed.mandates.some((item) => item.mandate_id === mandateId),
  `${listed.mandates.length} mandato(s)`,
);
check(
  'a condição de frequência viaja na projeção',
  listed.mandates[0]?.usage_limit?.max_uses === 3,
);

// 3 — the agent buys, and the ladder comes back.
const bought = await gateway.agentPurchase(mandateId, 'compre um voo para Córdoba abaixo de $150');
check('o agente conclui a compra', bought.outcome === 'settled', bought.reason_code);
check(
  'a escada de avaliação chega inteira',
  bought.evaluation_trace.at(-1)?.check === 'within_budget',
  `${bought.evaluation_trace.length} degraus`,
);

// 4 — a purchase over the ceiling refuses, and the ladder stops there.
const overCeiling = await gateway.agentPurchase(mandateId, 'compre a passagem executiva');
check('acima do teto é recusado', overCeiling.reason_code === 'mandate_ceiling');
check(
  'a escada para no teto e nunca chega ao orçamento',
  overCeiling.evaluation_trace.at(-1)?.check === 'below_ceiling'
    && !overCeiling.evaluation_trace.some((step) => step.check === 'within_budget'),
);

// 5 — the holder moves the live limit with a browser signature.
const beforeMove = (await gateway.listMandates(principalId, readToken)).mandates
  .find((item) => item.mandate_id === mandateId);
const signLimit = (minorUnits, policyVersion) => signCompactJws(
  {
    mandate_id: mandateId,
    limit_minor_units: minorUnits,
    currency: 'USD',
    scale: 2,
    policy_version: policyVersion,
  },
  wallet,
);
const staleJws = await signLimit(90000, beforeMove.policy_version);
const moved = await gateway.changeLimit(
  mandateId,
  { minor_units: 30000, currency: 'USD', scale: 2 },
  await signLimit(30000, beforeMove.policy_version),
);
check('o limite muda com assinatura do navegador', moved.policy_version >= 2, `v${moved.policy_version}`);

// 5b — and the authorization that moved it is spent. A limit change can be undone,
// so a replayable one would let an old, higher budget come back after the holder
// lowered it — the trial-by-fire move, reversed by whoever kept the token.
let replayReason = 'aceito';
try {
  await gateway.changeLimit(mandateId, { minor_units: 90000, currency: 'USD', scale: 2 }, staleJws);
} catch (error) {
  replayReason = error.reasonCode ?? String(error);
}
check('a autorização de limite não pode ser reusada', replayReason === 'limit_change_version_stale', replayReason);

// 6 — the trail verifies, and the three projections answer.
const auditor = await gateway.auditorLedger(mandateId);
check('a cadeia de hash está íntegra', auditor.chain.intact === true, `${auditor.chain.checked} elos`);
const merchant = await gateway.merchantLedger('vuelaya');
check(
  'a visão do merchant nunca carrega o mandato',
  !JSON.stringify(merchant.entries).includes(mandateId),
  `${merchant.redacted.length} campos retidos`,
);

// 6b — the standing order: the agent still working after the person stopped typing.
// This is the only part of the system where the buyer is not a person pressing pay,
// which is the premise of the case — so it has to be reachable from the browser lane.
const nothingYet = await gateway.agentPurchase(mandateId, 'compre um voo para Córdoba abaixo de $100');
check('nada atende ainda, e isso não é uma compra', nothingYet.outcome === 'no_offer', nothingYet.reason_code);

const beforeWatching = await gateway.listWatches(mandateId);
check(
  'e o beco não virou ordem permanente sozinho',
  beforeWatching.watches.length === 0,
  `${beforeWatching.watches.length} vigília(s)`,
);

const watch = await gateway.registerWatch(mandateId, 'compre um voo para Córdoba abaixo de $100');
check('o titular abre a vigília explicitamente', watch.status === 'OPEN', watch.watch_id);

const quiet = await gateway.tickWatches(mandateId);
check('sem oferta, a vigília continua esperando', quiet.fired.length === 0);

// The one the instruction actually names, at the merchant the mandate actually allows.
// Dropping the price of anything else proves nothing: the agent would still be right to
// leave it alone, and a green step there would be measuring the wrong refusal.
const cheapest = (await gateway.offers()).offers
  .filter(
    (offer) =>
      offer.merchant_id === 'vuelaya'
      && offer.item.category === 'travel'
      && offer.item.title.includes('Córdoba'),
  )
  .sort((left, right) => left.total.minor_units - right.total.minor_units)[0];
check('há um voo para Córdoba na VuelaYa para derrubar', Boolean(cheapest), cheapest?.item.sku);
await gateway.repriceOffer(cheapest.item.sku, 9000);
const fired = await gateway.tickWatches(mandateId);
check(
  'o preço cai e o agente compra sozinho',
  fired.fired.length === 1 && fired.fired[0].outcome === 'settled',
  `${fired.fired[0]?.outcome ?? 'nada disparou'}`,
);

// 7 — the demo clock and the tamper tool, both operator-gated.
const advanced = await gateway.advanceClock(3600);
check('o relógio da demonstração avança', advanced.offset_seconds >= 3600);
await gateway.tamperLedger(mandateId, 1);
const afterTamper = await gateway.verifyLedger(mandateId);
check(
  'a adulteração é detectada na posição exata',
  afterTamper.intact === false && afterTamper.broken_at === 1,
  `quebra em ${afterTamper.broken_at}`,
);

// 8 — revocation, signed here, ends the mandate.
const current = await gateway.readMandate(mandateId, readToken);
const revocationJws = await signCompactJws(
  {
    mandate_id: mandateId,
    scope: 'mandate',
    reason: 'revogado no navegador',
    epoch: current.revocation_epoch + 1,
  },
  wallet,
);
await gateway.revokeMandate(mandateId, revocationJws);
// The same instruction that was refused by the ceiling a moment ago. Now it is
// refused earlier, which is the ordering the whole design rests on: a revocation is
// never reachable by a purchase being cheap enough, or by any other property of it.
const afterRevocation = await gateway.agentPurchase(mandateId, 'compre a passagem executiva');
check(
  'depois da revogação a próxima tentativa falha',
  afterRevocation.reason_code === 'mandate_revoked',
  afterRevocation.reason_code,
);
check(
  'e a escada para antes de qualquer checagem de dinheiro',
  afterRevocation.evaluation_trace.at(-1)?.check === 'mandate_not_revoked'
    && !afterRevocation.evaluation_trace.some((step) => step.check === 'below_ceiling'),
);

// 9 — the standing order carries no authority of its own. Firing means calling the very
// same mandate, so a revoked one refuses it exactly as it refuses a typed instruction.
// The autonomy is in *when* the agent acts, never in *what* it may do.
let watchAfterRevocation = 'recusada ao registrar';
try {
  await gateway.registerWatch(mandateId, 'compre um voo para Córdoba abaixo de $100');
  const ticked = await gateway.tickWatches(mandateId);
  watchAfterRevocation = ticked.fired.some((item) => item.outcome === 'settled')
    ? 'comprou mesmo revogada'
    : 'não comprou';
} catch (error) {
  watchAfterRevocation = `recusada ao registrar (${error.reasonCode ?? error})`;
}
check(
  'uma vigília contra mandato revogado não compra',
  watchAfterRevocation !== 'comprou mesmo revogada',
  watchAfterRevocation,
);

const failed = steps.filter((step) => !step.ok);
console.log(`\n${steps.length - failed.length}/${steps.length} passos verdes contra ${baseUrl}`);
if (failed.length > 0) console.log('falhas:', failed.map((step) => step.label).join(', '));
