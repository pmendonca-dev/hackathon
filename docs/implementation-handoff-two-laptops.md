# AVAL — Handoff para dois laptops

**Baseline:** `main` no commit `a67db26` ou posterior.  
**AP2 alvo:** **v0.2**.  
**Regra central:** o `AuthorizationCore` é a única autoridade e o único escritor de estado de negócio.

## Estado de partida

O core persistente está verde com `uv run pytest -q` (42 testes): migrations incrementais, custódia ES256, JWS/JCS/digest, revogação escopada e fail-closed, idempotência, `AuthorizationProof` com replay durável e auditoria inicial de captura.

Ainda faltam os adaptadores UCP/AP2/ACP, checkout/API, PSP/recibos/disputa completos, UI integrada, painel trial-by-fire, E2E e entrega. x402 permanece proibido até a Task 12 estar verde.

## Divisão de ownership

| Laptop | Branch | Dono exclusivo | Não editar |
| --- | --- | --- | --- |
| A — Protocol/Core | `codex/laptop-a-protocol-core` | `src/aval/adapters/ucp/**`, `src/aval/adapters/ap2/**` (exceto `receipts.py`), `src/aval/api/middleware/**`, routers UCP/checkout, `agent_registry_repository.py`, testes UCP/AP2 e `docs/protocol-validation.md` | `web/**`, ACP, PSP/receipts/dispute, migrations e o core já estabilizado sem acordo explícito |
| B — Payments/UI | `codex/laptop-b-payments-ui` | `src/aval/adapters/acp/**`, `src/aval/adapters/settlement/**`, `src/aval/application/services/{vault,receipts,dispute}.py`, `src/aval/adapters/ap2/receipts.py`, routers ACP/audit, testes ACP/PSP/audit e `web/**` | UCP/AP2 checkout, `AuthorizationCore`, migrations e `docs/protocol-validation.md` |

Arquivos compartilhados (`src/aval/application/ports.py`, `src/aval/main.py`, `docs/decision-log.md`, `README.md`) só podem ser alterados pelo laptop que tiver um contrato aprovado em commit; o outro laptop deve rebasear e integrar esse commit antes de editá-los.

## Protocolo de integração

1. Cada laptop começa com `git fetch origin` e `git switch --create <branch> origin/main`.
2. Uma tarefa equivale a um commit pequeno, com teste escrito e observado falhar antes da implementação.
3. Antes de publicar: `uv run pytest -q` para Python; no frontend, executar os comandos definidos em `web/package.json`.
4. Publicar somente a própria branch: `git push --set-upstream origin <branch>`.
5. Antes de entregar para merge: `git fetch origin`, `git rebase origin/main`, resolver apenas conflitos nos próprios arquivos e repetir os testes.
6. Ordem de merge: A primeiro, para estabilizar o contrato UCP/AP2; B rebaseia depois e integra ACP/PSP/UI contra o contrato resultante.
7. Nunca usar `git push --force`, nunca editar o trabalho não publicado do outro laptop e nunca fazer commit direto em `main`.

## Marcos e contrato de handoff

### Laptop A entrega primeiro

- Task 6: registry local, middleware de bytes crus, RFC 9421 ES256 e discovery UCP.
- Task 7: `CheckoutIntent` canônico, lock da extensão AP2, `merchant_authorization` em JCS/JWS e validação AP2 **v0.2** de `aud`, `nonce`, expiração e evidência.
- Documentar o contrato HTTP em `docs/contracts/aval-checkout-api.md`: requests, responses, códigos de erro e payloads estáveis usados pela UI.

### Laptop B trabalha em paralelo e integra depois

- Task 8: token ACP `vt_*`, allowance derivada de estado vivo e nenhuma exposição de PAN.
- Task 9: PSP mock recebe apenas `Reservation.COMMITTED` + proof; receipts e auditoria/disputa são leitura/escrita pelo core, nunca pelo adaptador.
- Tasks 10–11: UI e preparação do console trial-by-fire; enquanto o contrato não estiver disponível, usar fixtures explicitamente marcadas como mock, sem alterar regras de negócio no browser.

## Gates não negociáveis

- Dinheiro: somente `Money`; jamais `float`.
- O mandato jamais tem estado `COMMITTED`; somente a reserva.
- Revogação e idempotência indisponíveis recusam a operação; nunca fail-open.
- Toda captura revalida revogação no storage primário antes do commit.
- Nenhum adaptador acessa banco, ledger ou política.
- Sem Gemini, ADK, A2A, MCP, Web3, PSP real ou x402 nesta etapa.

## Prompt — Laptop A: Protocol/Core

```text
Você é o Laptop A do AVAL. Trabalhe exclusivamente na branch codex/laptop-a-protocol-core, criada de origin/main no commit a67db26 ou posterior.

Objetivo: concluir Tasks 6 e 7 do plano com AP2 v0.2, sem implementar ACP, PSP/receipts/disputa, web ou x402.

Leia integralmente antes de editar:
- docs/aval-integration-architecture.md
- docs/protocol-validation.md
- docs/superpowers/plans/2026-08-29-aval-implementation.md
- docs/implementation-handoff-two-laptops.md

Ownership exclusivo: src/aval/adapters/ucp/**, src/aval/adapters/ap2/** exceto receipts.py, src/aval/api/middleware/**, routers UCP/checkout, agent_registry_repository.py, testes UCP/AP2 e docs/protocol-validation.md.
Não edite web/**, ACP, PSP/receipts/dispute, migrations, AuthorizationCore, README, main.py, ports.py ou decision-log sem um commit de contrato explicitamente combinado.

Implemente em TDD rigoroso: escreva um teste que falha, execute-o, implemente o mínimo, rode o teste focalizado e a suíte afetada, e faça commits pequenos. Registre decisões materiais em inglês no docs/decision-log.md somente se for autorizado a editar esse arquivo.

Entrega A:
1. UCP registry local, discovery, raw-body middleware e RFC 9421 ES256; rejeitar corpo reserializado, DER, perfil/chave não confiável e assinatura ausente.
2. Checkout UCP canônico + AP2 v0.2: lock da capability, merchant authorization JCS/JWS, validações aud/nonce/expiração e bloqueio de complete sem mandate.
3. Criar docs/contracts/aval-checkout-api.md com o contrato HTTP estável para Laptop B.

Invariantes: Core é único escritor; adapters não importam sessão/SQLAlchemy; ES256 usa r||s cru; Content-Digest usa bytes crus; AP2 é evidência estática e não política viva.

Antes de entregar: git fetch origin; git rebase origin/main; uv run pytest -q; git status --short; git push --set-upstream origin codex/laptop-a-protocol-core. Informe commits, testes e o contrato entregue. Não faça merge em main.
```

## Prompt — Laptop B: Payments/UI

```text
Você é o Laptop B do AVAL. Trabalhe exclusivamente na branch codex/laptop-b-payments-ui, criada de origin/main no commit a67db26 ou posterior.

Objetivo: avançar Tasks 8–11 em paralelo, sem tocar UCP/AP2 checkout, migrations ou AuthorizationCore. AP2 alvo é v0.2; x402 é proibido.

Leia integralmente antes de editar:
- docs/aval-integration-architecture.md
- docs/protocol-validation.md
- docs/superpowers/plans/2026-08-29-aval-implementation.md
- docs/implementation-handoff-two-laptops.md

Ownership exclusivo: src/aval/adapters/acp/**, src/aval/adapters/settlement/**, src/aval/application/services/vault.py, receipts.py e dispute.py, src/aval/adapters/ap2/receipts.py, routers ACP/audit, testes ACP/PSP/audit e web/**.
Não edite UCP/AP2 checkout, AuthorizationCore, migrations, docs/protocol-validation.md, main.py, ports.py, README ou decision-log sem contrato/commit coordenado.

Use TDD rigoroso e commits pequenos. O browser/UI nunca pode reimplementar política, revogação, saldo ou captura; até o contrato de checkout do Laptop A chegar, use fixtures claramente marcadas como mock.

Entrega B:
1. ACP Delegate Payment com token opaco vt_*, PAN nunca retornado/persistido, allowance derivada de estado vivo.
2. PSP mock que aceita somente Reservation.COMMITTED e AuthorizationProof válido; adaptador nunca escreve ledger/auditoria.
3. Receipts/audit/disputa com trilha append-only legível; preparar UI humano/merchant/auditor e console trial-by-fire contra fixtures/contrato estável.

Invariantes: Money sem float; mandato nunca COMMITTED; revogação pós-commit não cancela settlement em voo; não usar rede/PSP real/Gemini/ADK/A2A/MCP/Web3/x402.

Antes de entregar: git fetch origin; git rebase origin/main; rodar testes Python afetados e os comandos de verificação em web/package.json; git status --short; git push --set-upstream origin codex/laptop-b-payments-ui. Informe commits, testes, mocks temporários e dependências do contrato do Laptop A. Não faça merge em main.
```
