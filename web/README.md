# AVAL — UI de auditoria e trial-by-fire

Interface React das Tasks 10–11: perspectivas do humano, merchant e auditor, além
de um console que prepara comandos de trial-by-fire.

> **MOCK EXPLÍCITO:** a implementação atual usa `mockAvalGateway.ts`. Não há
> backend, banco, rede ou integração de pagamento. Enviar um comando retorna
> `fixture-only` e nunca altera estado canônico.

## Boundaries do Laptop A

O contrato de checkout integrado está modelado em
`src/contracts/checkoutApi.ts`, seguindo `docs/contracts/aval-checkout-api.md`:

- dinheiro HTTP usa `amount` inteiro, `currency` e `scale`;
- os estados são `ready_for_complete`, `requires_escalation` e `canceled`;
- a UI apresenta escalonamento e jamais o reinterpreta como pagamento concluído.

`src/contracts/avalGateway.ts` é a fronteira de apresentação substituível:

- `loadWorkspace()` devolve um snapshot pronto para apresentação;
- `submitTrialCommand()` transporta uma intenção e devolve o resultado canônico;
- política, revogação, allowance/saldo e captura jamais são calculados no browser.

O contrato HTTP publicado ainda não oferece snapshots de administração nem
comandos de trial-by-fire. Por isso, essas duas operações continuam em fixture
explícita até um handoff adicional, sem inventar endpoints. O snapshot carrega
`dataSource`, `contractStatus` e `contractVersion` para impedir que mock pareça
produção.

## Perspectivas

- **Humano:** mandato, allowance viva projetada, última decisão e recibos.
- **Merchant:** recibo seletivo, token opaco `vt_*` e evidência AP2 v0.2.
- **Auditor:** timeline append-only, hashes e reconstrução de disputa.
- **Trial-by-fire:** envelopes para reduzir limite, alterar escopo, zerar orçamento
  e revogar; na fixture, nenhum efeito é presumido.

## Verificação

```bash
npm test
npm run build
npm run lint
```

O teste usa o suporte nativo a TypeScript do Node 24, sem dependências adicionais.
Todos os valores monetários do contrato usam `minorUnits` inteiros e `scale`.

## Identidade

A cor é semântica: verde para autoridade concedida, amarelo para decisão humana,
vermelho para recusa, ciano para prova e violeta para estado indeterminado. O
**Authority Rail** desenha uma projeção já decidida pelo core; ele não classifica
o valor no browser.
