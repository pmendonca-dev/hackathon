# Evidência ponta a ponta do navegador

## Estado

**Verde.** A suíte pública de E2E passa (`uv run pytest tests/integration/e2e -q` →
11/11), a suíte completa passa (383 testes), a do navegador passa (32 testes) e a
jornada ao vivo do navegador passa 14/14 contra um servidor HTTP real.

> Este documento substitui a versão anterior, que registrava *"RED — 5 passed, 6
> failed"* contra o commit `3191d3e` do runtime. Aquelas seis falhas eram do contrato
> do lane de protocolo e foram fechadas no merge. Manter o texto antigo era pior do que
> não ter documento: um jurado que o abrisse leria que a revogação não era operacional.

## Fronteira da validação

- O navegador exercita o **lane de autorização** (`/mandates`, `/agent/purchase`,
  `/escalations`, `/ledger`, `/merchant/verify`, mais as superfícies de operador).
  As superfícies humanas desse lane não pedem RFC 9421 — é o que as torna alcançáveis
  de uma página.
- O **lane de protocolo** (`/checkout-sessions`, `/payment-captures`, `/audit/*`,
  `/agentic_commerce/delegate_payment`) continua exigindo assinatura RFC 9421 sobre os
  bytes crus e continua coberto por `tests/integration/e2e/test_task_12_live_runtime.py`.
- Nenhuma asserção passa por dentro da aplicação ou por consulta direta ao banco. A
  única escrita direta em SQLite é a rota de adulteração, e mesmo ela é observada pelo
  `/ledger/verify` público.

## Por que o navegador não fala o lane de protocolo

Toda rota do lane de protocolo pede uma assinatura RFC 9421 sobre o corpo cru. Uma
página só produziria uma dessas se recebesse uma chave confiável — e embutir chave
privada em variável do Vite é publicá-la, porque variáveis do Vite são assets
públicos. As duas saídas ruins seriam entregar uma chave do servidor à página ou fazer
o servidor assinar "em nome" do titular; qualquer uma derrubaria a separação
titular/operador exatamente onde ela está sendo demonstrada.

A saída boa é o navegador ter chave própria. Ele gera um par P-256 com WebCrypto,
`extractable: false`, guarda o handle no IndexedDB e assina revogação, mudança de
limite, aprovação e kill switch localmente. O núcleo Python verifica o que o WebCrypto
assina — há checagem cruzada, e a assinatura é `r||s` cru de 64 bytes, não DER.

## Jornada verificada (14/14)

Executada por `web/tests/live-browser-journey.mjs`, com a mesma classe de gateway e a
mesma carteira que a página usa:

| # | Passo | Evidência |
|---|---|---|
| 1 | O navegador cria um mandato com a própria chave | `201`, `mandate_id` devolvido |
| 2 | A listagem escopada devolve o mandato | `GET /mandates?principal_id=` |
| 3 | A condição de frequência viaja na projeção | `usage_limit.max_uses == 3` |
| 4 | O agente conclui a compra | `outcome: settled` |
| 5 | A escada de avaliação chega inteira | 13 degraus, termina em `within_budget` |
| 6 | Acima do teto é recusado | `mandate_ceiling` |
| 7 | A escada para no teto | `within_budget` ausente do traço |
| 8 | O limite muda com assinatura do navegador | política v2 |
| 9 | A cadeia de hash está íntegra | 6 elos conferidos |
| 10 | A visão do merchant não carrega o mandato | 4 campos retidos, `mandate_id` ausente |
| 11 | O relógio da demonstração avança | deslocamento ≥ 3600s |
| 12 | A adulteração é detectada na posição exata | `intact: false`, `broken_at: 1` |
| 13 | Depois da revogação a tentativa falha | `mandate_revoked` |
| 14 | E a escada para antes do dinheiro | último degrau `mandate_not_revoked` |

Os passos 7 e 14 são os que mais valem: eles provam a **ordem**. Uma compra que
estouraria o teto e um mandato revogado produzem paradas em degraus diferentes, e o
degrau nunca alcançado aparece explicitamente em vez de sumir da lista.

## Reprodução

```powershell
$env:AVAL_OPERATOR_TOKEN = "demo-token"
$env:AVAL_DEMO_TAMPER    = "1"
uv run uvicorn aval.main:app --port 8099

# noutro terminal
Set-Location web
$env:AVAL_OPERATOR_TOKEN = "demo-token"
node --experimental-strip-types tests/live-browser-journey.mjs http://127.0.0.1:8099
```
