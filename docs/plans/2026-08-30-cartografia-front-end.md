# Plano — front-end Cartografia da Confiança

## Objetivo

Transformar as quatro perspectivas do AVAL em uma demonstração visual clara, calma e
memorável. A interface deve explicar a regra central do produto antes de pedir que o
jurado leia detalhes técnicos: o agente pode propor uma compra, mas apenas o mandato
define a autoridade de gasto.

O runtime continua sendo a única fonte de verdade. Nenhuma animação, contador ou estado
de ataque poderá sugerir que uma operação ocorreu se a API não confirmou isso.

## Direção visual

- **Tom:** editorial e tátil, com papel quente, tinta azul-petróleo e cartões claros;
  nunca uma estética de terminal ou ficção científica.
- **Semântica estável:** petróleo para provas e fluxos válidos, dourado para ação humana,
  coral para bloqueio ou revogação, azul profundo para contexto e texto.
- **Tipografia:** título serifado de alta legibilidade, sans neutra para decisões e mono
  apenas para identificadores, hashes e outros artefatos criptográficos.
- **Movimento:** rápido e causal. Uma rota só se move depois de uma compra, uma cadeia só
  se rompe depois da resposta real da adulteração e o usuário pode reduzir movimento.

## Arquitetura de interface

1. Criar `AuthorityAtlas`, uma composição SVG/CSS que representa Titular → Agente →
   Mandato → Merchant → Trilha. Ela recebe o mandato, a última execução do agente e o
   estado da cadeia; não possui uma fonte paralela de estado.
2. Criar `AttackScenarios`, um painel reutilizável de cenários alcançáveis pelo catálogo
   real. Os atalhos enviam instruções reais para o agente e exibem o motivo devolvido pelo
   runtime. Os cenários serão:
   - voo direto para Córdoba dentro do mandato;
   - hotel em Córdoba, fora da categoria `travel`;
   - voo executivo de US$900, acima do teto imutável;
   - voo mais barato para Santiago, oferecido por merchant fora do escopo;
   - compra após revogação, acionada pela própria ação assinada da titular.
3. Renovar o shell para uma navegação horizontal leve em telas pequenas e trilhos de
   contexto em telas grandes. A identidade da chave e o estado da cadeia continuam
   persistentes, pois são fatos que tornam a sessão confiável.
4. Renovar a perspectiva da titular em torno do cartão de mandato, do atlas e dos
   cenários. O formulário de criação permanece disponível, mas deixa de competir com a
   demonstração principal.
5. Renovar as perspectivas do merchant e auditor sem alterar suas propriedades de
   privacidade: o primeiro mantém a comparação entre dados recebidos e retidos; o segundo
   torna a cadeia uma linha de evidências com um ponto de ruptura real.
6. Renovar o console trial-by-fire como dois trilhos explicitamente separados: ações
   assinadas pela titular e ações permitidas ao operador. Recibos continuam mostrando a
   resposta canônica do runtime.

## Elementos interativos e animações

- A rota do atlas é desenhada no carregamento do mandato e um marcador viaja uma vez
  quando há uma nova execução do agente.
- A escolha de um cenário destaca a regra correspondente na escada de avaliação; ao fim,
  a resposta API substitui o estado de “em execução”.
- A revogação fecha a rota visual somente depois de `revokeSelected()` confirmar.
- O auditor revela a quebra da cadeia com uma transição coral após `tamperLedger()`
  retornar e `chain.intact` ficar falso.
- Todos os movimentos têm alternativa com `prefers-reduced-motion`.

## Fora de escopo deliberado

- Não incluir globo 3D decorativo; geografia só entra como contexto da oferta de voo e
  não como uma alegação genérica de cobertura global.
- Não simular ataques de assinatura, replay ou alteração de digest no navegador. Eles são
  defendidos na borda do protocolo e aparecem como proteções documentadas; a UI não pode
  fingir que executou uma invasão que o runtime não recebeu.
- Não mudar contratos de API, decisões do núcleo, carteira local ou regras de autorização.

## Validação

1. `npm run lint`, `npm run test` e `npm run build` no diretório `web`.
2. Subir o runtime e executar a jornada de navegador já existente para confirmar que os
   novos elementos não criaram um caminho paralelo ou fixture local.
3. Verificar visualmente desktop e mobile, com redução de movimento ativada.
4. Revisar `git diff`, criar um commit focado e abrir uma pull request com a narrativa da
   mudança e os comandos de verificação.
