# Tasks 10–11 — UI de auditoria e console trial-by-fire

## Problema

O protótipo React existente tem uma identidade visual forte, mas mantém política e
transições de negócio em um reducer do browser. Isso contraria o contrato do AVAL:
o `AuthorizationCore` é a única autoridade para política, revogação, saldo e captura.
O contrato HTTP integrado do Laptop A cobre criação e conclusão de checkout, mas não
publica snapshots de administração nem comandos de trial-by-fire. A UI precisa
continuar demonstrável sem inventar endpoints ou transformar fixtures em uma segunda
fonte de verdade.

## Abordagem

- Introduzir uma boundary `AvalGateway` substituível. A implementação desta branch
  lê fixtures explicitamente identificadas como `mock` e devolve snapshots canônicos.
- Fazer a UI renderizar somente fatos e resultados recebidos da boundary. Comandos do
  console representam intenções e recebem um novo snapshot; não calculam impacto local.
- Organizar as três perspectivas pedidas: humano (autoridade e compras), merchant
  (evidência mínima verificada) e auditor (timeline append-only e disputa).
- Manter um console trial-by-fire separado, com intervenções preparadas contra a
  boundary e aviso permanente de que a sessão atual usa dados mock.
- Adicionar testes nativos de Node para o contrato puro, sem rede e sem novas
  dependências; `build` e `lint` continuam sendo os gates do pacote.

## Direção visual

**Assunto:** uma sala de controle local para autoridade de pagamentos por agentes.
**Público:** titular humano, merchant e auditor/júri. **Trabalho único:** tornar
imediatamente legível o que o core decidiu, com qual evidência e em que ordem.

### Tokens

- `ink` `#101418`: base de alto contraste e texto principal.
- `paper` `#F4F7F8`: superfície de leitura.
- `allow` `#C6F24E`: autoridade concedida.
- `escalate` `#F5B942`: decisão humana necessária.
- `deny` `#FF5C5C`: recusa canônica.
- `verify` `#4ED8F2`: evidência verificada.

Inter Tight permanece como display; Inter como texto; JetBrains Mono como voz de
dados, hashes e estados. As fontes existentes já diferenciam narrativa de prova.

### Layout

```text
desktop  [ navegação por perspectiva ][ contexto + origem MOCK ][ prova/ação ]
mobile   [ contexto ][ tabs roláveis ][ conteúdo ][ ação segura ]
```

### Assinatura

O **Authority Rail** existente continua sendo o gesto memorável: ele passa a ser uma
visualização de limites já informados pelo snapshot, nunca um motor de decisão.

### Autocrítica

A paleta escura com verde ácido poderia cair no default “terminal hacker”. O ajuste é
tratar as telas como instrumentos de aviação: grandes superfícies claras de leitura,
marcação semântica contida e uma única faixa de autoridade. Removemos qualquer efeito
que sugira atividade de rede real. A identidade vem da estrutura da prova, não de glow.

## Descartado

- **Manter `policy.ts`/reducer como demo:** cria estado e regra concorrentes ao core.
- **Chamar endpoints de administração presumidos:** o contrato integrado é estável
  apenas para checkout; inventar o restante esconderia uma dependência real.
- **Adicionar biblioteca de testes:** exigiria rede/dependências sem ganho para uma
  boundary pequena e pura; Node 24 já executa os testes TypeScript necessários.
- **Simular PSP ou captura no browser:** fora do ownership da UI e enganoso na demo.

## Escopo

Somente `web/**`: boundary, fixtures mock, páginas/componentes, estilos, testes e
documentação local. Nenhuma alteração em checkout UCP/AP2, core, migrations ou APIs.

## Verificação

1. Observar os testes da nova boundary falharem antes da implementação.
2. `npm test`
3. `npm run build`
4. `npm run lint`
5. QA responsivo e de teclado/reduced-motion no browser local, sem requisições de rede.

### Ajuste descoberto no QA

O primeiro QA no browser revelou um ciclo de renderização: o valor default de
`AvalProvider` criava uma nova instância do gateway mock a cada render e reacionava o
efeito de carga. A instância default agora tem identidade estável em escopo de módulo,
protegida por teste de regressão. Uma aba limpa confirmou zero erros ou warnings no
console após a correção.
