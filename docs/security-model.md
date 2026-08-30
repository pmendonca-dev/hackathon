# Modelo de segurança

Quem pode fazer o quê, provado como, e por quê essa divisão. Este documento é a
resposta à pergunta de defesa técnica *"o que impede um atacante de simplesmente
chamar sua API?"*.

---

## As três autoridades, e por que são separadas

O sistema responde a três perguntas distintas com três mecanismos distintos. Confundi-las
é o erro que transforma uma camada de autorização em teatro.

| pergunta | mecanismo | quem detém | onde |
|---|---|---|---|
| *Quem está chamando?* | assinatura HTTP RFC 9421 (ES256) | o agente, com chave própria | `security/http_signature.py` |
| *Esta compra pode acontecer?* | avaliação do mandato | ninguém — é determinística | `application/authorization_core.py` |
| *Quem autoriza mudar a autoridade?* | JWS ES256 do titular | o humano dono do mandato | `_verified_approval` |
| *Quem opera esta instância?* | token de operador | o time | `api/operator_auth.py` |

A divisão que mais importa: **o operador não pode mexer em dinheiro.** O token de
operador libera registro de agente e o interruptor do PSP; ele **não** libera aumentar
um limite nem aprovar uma escalação. Essas duas coisas exigem a chave do titular. Um
operador capaz de subir um limite seria um operador capaz de gastar o dinheiro dos
outros.

Simetricamente, **passar pela assinatura de agente não dá nada.** Um agente perfeitamente
autenticado ainda recebe exatamente o que o mandato permite. Autenticar não é autorizar.

---

## Matriz de autorização

| endpoint | exige |
|---|---|
| `POST /authorize`, `POST /capture` | assinatura RFC 9421 de agente confiável |
| `PATCH /mandates/{id}/limit` | **JWS do titular** sobre mandato + valor exato |
| `POST /mandates/{id}/revocation` | **JWS do titular** sobre o mandato nomeado |
| `POST /escalations/{id}/decision` | **JWS do titular** sobre handle + mandato + valor + decisão |
| `POST /agents` | token de operador |
| `POST /admin/psp`, `GET /admin/psp`, `POST /reconcile` | token de operador |
| `POST /mandates` | nada — criar mandato próprio não afeta terceiros |
| `POST /agent/purchase`, `GET /ledger`, `POST /disputes` | conhecimento do `mandate_id` |

### O modelo de capability do `mandate_id`

`mandate_id` é UUID4 (128 bits). Quem o conhece pode instruir o agente a comprar dentro
do escopo e ler a visão humana da trilha — é um modelo de *capability URL*, deliberado e
adequado a uma demo operada por jurados. **Está declarado aqui porque um modelo de
segurança implícito não é um modelo de segurança.**

O que o `mandate_id` **não** dá, mesmo para quem o conhece: aumentar o limite, revogar,
aprovar uma escalação, comprar acima do teto ou fora do escopo. Todo dano possível está
limitado pelo que o mandato já autorizava.

Em produção, `/agent/purchase` e `/ledger` ficariam atrás da sessão do titular. O núcleo
não muda: ele nunca confiou no chamador.

---

## Como cada ataque morre

### Agente impostor

Assinatura RFC 9421 sobre `@method`, `@path` e `content-digest`, verificada antes de o
corpo ser interpretado.

| ataque | resposta |
|---|---|
| requisição sem assinatura | `401 signature_missing` |
| chave não registrada | `401 key_not_found` |
| mesmo corpo, chave errada | `401 signature_invalid` |
| corpo trocado depois de assinar | `401 content_digest_mismatch` |
| assinatura reenviada | `401 signature_replayed` |
| assinatura antiga | `401 signature_stale` |
| assinatura que não cobre o corpo | `401 signature_components_insufficient` |
| perfil conhecido, não confiável | `403 profile_not_trusted` |

Decisões que sustentam isso:

- **Os componentes cobertos são fixos.** Deixar o chamador escolher o que a própria
  assinatura cobre é como corpos assinados são trocados: a assinatura segue válida sobre
  as partes que ninguém conferiu.
- **Os parâmetros recebidos são ecoados literalmente** na base de assinatura. Uma
  reserialização que normalizasse algo verificaria uma mensagem que o remetente nunca
  assinou.
- **O nonce é queimado por último**, depois da assinatura verificar. Do contrário um
  atacante gastaria nonces alheios com lixo assinado por ninguém.
- **`hmac.compare_digest`** no digest e no token de operador. Comparação byte a byte
  entregaria o segredo um caractere por vez.

### Registro de agente

O registro é a raiz de toda a defesa acima: `require_signed_agent` conclui o que essas
linhas dizem. Por isso:

- exige token de operador — `401 operator_token_missing` / `403 operator_token_invalid`;
- **recusa um `kid` já registrado por outro perfil** (`409 agent_kid_already_registered`).
  Sem isso, um segundo perfil declarando o mesmo `kid` faria `agent_for_kid` responder
  com a linha que a varredura encontrasse primeiro — e a ordem não é determinística.

### Mudança de limite e revogação

Ambas exigem JWS ES256 do titular, verificado contra as autoridades **daquele** mandato.
A revogação casa `mandate_id` do payload com o da URL; a mudança de limite casa
`mandate_id`, `limit_minor_units`, `currency`, `scale` e `policy_version`.
O último é a versão que a mudança substitui, e é o que torna o token de uso único:
uma revogação é irreversível, então repeti-la não muda nada, mas um limite pode
voltar a subir — sem essa amarração, quem capturasse a autorização antiga desfaria
a redução que o titular acabou de fazer. Recusa: `limit_change_version_stale`.

Um token assinado para o mandato A não funciona no mandato B
(`limit_change_mandate_mismatch`, `revocation_mandate_mismatch`), e um token assinado
para $300 não aplica $1000 (`limit_change_amount_mismatch`).

### Aprovação de escalação

O JWS nomeia `decision_handle`, `mandate_id`, `decision` e `amount_minor_units` — todos
conferidos contra a escalação congelada, e só autoridades de papel `holder` são aceitas.
Um guardião pode revogar autoridade; não pode gastar em nome do titular.

A aprovação **não é atalho**: tudo é reavaliado no momento da retomada. Uma revogação
que chegou enquanto a pessoa decidia ainda recusa a compra. E o teto nunca gera handle,
logo nunca há o que assinar acima dele.

### CORS

`allow_origins` é uma lista nomeada (padrões do Vite e do Next, mais
`AVAL_ALLOWED_ORIGINS`), nunca `*`. Com curinga, qualquer página aberta na máquina do
apresentador poderia dirigir esta API durante a demo.

---

## O que não é defendido, e por quê

Fronteiras de demonstração, assumidas conscientemente:

- **Chaves em memória.** `KeyCustodyService` é a interface que um HSM implementaria —
  chaves privadas nunca cruzam a fronteira do serviço — mas aqui vivem no processo.
  Reiniciar troca a chave de prova, invalidando provas antigas.
- **Nonces em processo.** `ReplayGuard` não sobrevive a reinício nem a múltiplas
  instâncias. A proteção durável contra cobrança dupla é a idempotência no banco; esta é
  a camada barata na frente, que também cobre requisições de leitura.
- **Sem TLS.** A demo roda em `localhost`. Em rede real, tudo aqui pressupõe TLS: as
  assinaturas provam integridade e autoria, não confidencialidade.
- **Token de operador único**, sem rotação nem escopo. Se não houver
  `AVAL_OPERATOR_TOKEN`, **nenhum token existe** e as superfícies de operador ficam
  inalcançáveis: `resolve_operator_token()` devolve string vazia, e uma credencial
  apresentada contra ela nunca confere (`403 operator_token_invalid`). A instância nasce
  fechada, não aberta — e nada é sorteado nem impresso. Uma credencial gerada e escrita
  na saída de subida viraria segredo em log de processo, e há dois testes de bootstrap
  que falham se um token aparecer em `stdout`.
- **Dois valores de política vivem em constante, não em configuração.**
  `ESCALATION_WINDOW = 1h` decide por quanto tempo uma escalação pode ser assinada, e
  `AuthorizationCore(max_live_reservations=3)` é o que produz `reservation_limit` — a
  recusa que aparece quando um agente segura o orçamento com capturas sem resposta.
  Nenhum dos dois é lido do ambiente, então mudá-los é mudar código. Ficam registrados
  aqui porque um número que altera comportamento visível e não está escrito em lugar
  nenhum é uma surpresa esperando um jurado.
- **Sem limitação de taxa.** Fora do escopo do case e irrelevante para as invariantes:
  nenhuma quantidade de tentativas produz uma compra que o mandato não permitia.
- **Leitura por `mandate_id` é uma capability, não uma sessão.** `GET /mandates/{id}`,
  `GET /ledger` e `GET /escalations?mandate_id=` respondem a quem apresentar o id, sem
  autenticar. O id é 32 hex aleatórios, então conhecê-lo *é* a autorização — o mesmo
  modelo de um link secreto. É fronteira assumida, e vale registrar o que a sustenta:
  quem conhece o id de um mandato quase sempre é quem participou dele.

  **A escolha por `principal_id` não se sustentava, e por isso não é mais aceita.** Um
  `usr_tg_{chat_id}` ou `usr_marta` é um nome que qualquer um adivinha, não um segredo de
  32 hex. As duas listagens escopadas por pessoa — `GET /mandates` e
  `GET /escalations?principal_id=` — exigem hoje um JWS do titular, e respondem pela
  interseção: os mandatos que *aquela chave* sustenta, verificados um a um contra a
  autoridade registrada de cada mandato, exatamente como o kill switch decide seu
  alcance. Uma chave que não sustenta nada recebe lista vazia, e não uma recusa — a
  mesma resposta que um titular novo recebe antes de criar o primeiro mandato, de modo
  que a rota não vira oráculo de quais pessoas existem.

  O que isso corrige: o isolamento de **autoridade** entre jurados sempre existiu e é
  testado — um jurado não revoga o mandato do outro. O de **visibilidade** não existia.
  Numa sala com um bot só, adivinhar o chat id vizinho lia o mandato do outro, o limite e
  o quanto já tinha gasto. `tests/integration/api/test_listing_api.py`
- **A leitura de auditor de terceiro vive na faixa de protocolo, não nesta.**
  `GET /audit/mandates/{id}` é autenticado por RFC 9421 e escopado por `can_read`, com
  `auditor-key` própria: um auditor prova quem é sem nunca autorizar uma compra. O
  `/ledger?view=auditor` desta faixa é a projeção de demonstração da mesma trilha.
  Exigir assinatura *do titular* nele seria incoerente — um auditor não é o titular.

---

## Achados corrigidos nesta implementação

Revisão de segurança conduzida sobre o próprio código, com correção e teste para cada um:

| # | achado | correção |
|---|---|---|
| 1 | `POST /agents` aceitava `trusted: true` de qualquer um, derrotando toda a defesa contra impostor — e permitia sobrescrever a chave do agente legítimo | token de operador + recusa de `kid` já registrado |
| 2 | `PATCH /mandates/{id}/limit` elevava autoridade de gasto sem prova nenhuma, enquanto revogar já exigia assinatura | JWS do titular vinculando mandato e valor exato |
| 3 | CORS `*` tornava 1 e 2 exploráveis por qualquer página aberta na máquina | lista de origens nomeadas |
| 4 | `/admin/psp` e `/reconcile` controlavam a liquidação sem autenticação | token de operador |

Três bugs de correção foram encontrados antes disso: a primeira mudança de limite não
avançava a versão de política; uma compra recusada pelo processador ficava permanentemente
bloqueada para nova tentativa; e a aprovação de escalação pedia uma segunda confirmação da
mesma compra congelada.

---

## Superfícies acrescentadas depois, e o que cada uma custa

### Listagem por titular — divulgação assumida, e a mais cara delas

`GET /mandates?principal_id=` e `GET /escalations?principal_id=` são as rotas que o bot
e o navegador usam para responder *"o que eu tenho?"* sem conhecer um id de antemão.

**O custo é real e vale ser dito em voz alta.** Até aqui, ler um mandato exigia o
`mandate_id` — 32 hexadecimais aleatórios, que funcionam como capacidade: quem não o
recebeu não o adivinha. Um `principal_id` não tem essa propriedade; `usr_marta` é
adivinhável. Então estas duas rotas transformam "saber um segredo" em "saber um nome",
e quem souber o nome lê limite, gasto, merchants e as compras pendentes daquela pessoa.

O que **não** mudou: nada aqui autoriza gasto. Listar não move dinheiro, não aprova
escalação e não revoga; todas essas continuam exigindo assinatura do titular.

O que fizemos para reduzir o dano:

- **Não existe listagem global.** Os repositórios só sabem responder por titular, e a
  consulta de escalações alcança as linhas por *join* no mandato que as possui. Não há
  variante sem escopo em lugar nenhum da pilha para alguém encontrar depois.
- **Titular desconhecido devolve lista vazia**, não 404 — a rota não vira um oráculo de
  quais ids de titular existem.
- **A visão do merchant não foi tocada.** Ela continua construída por lista branca e
  continua sem `mandate_id` e sem `principal_id`, com teste que falha se vazarem.

**Em produção, a resposta é sessão do titular.** A listagem deveria exigir prova de que
o chamador é aquele titular — um desafio assinado pela mesma chave que já assina
revogação, ou um cookie de sessão emitido contra ela. A forma da rota não muda; só
ganha uma dependência de autenticação. Não fizemos isso porque as superfícies humanas
deste lane são deliberadamente abertas na demo, e adicionar meia autenticação em uma
rota enquanto as vizinhas seguem abertas daria uma sensação de segurança sem a
propriedade.

### Relógio de demonstração — monotônico por segurança

`POST /admin/clock` avança e nunca rebobina. Avançar só retira autoridade: mandatos
expiram, nada é concedido. Rebobinar reviveria um mandato expirado, o que seria um
token de operador devolvendo autoridade de gasto que a validade do próprio titular já
tinha encerrado — exatamente o poder que a decisão nº 5 nega ao operador.

### Adulteração da trilha — não montada por padrão

`POST /admin/ledger/{id}/tamper` corrompe um log de auditoria de propósito, para que a
cadeia possa ser testada por quem duvida dela. Sem `AVAL_DEMO_TAMPER` o router **não é
registrado**: 404 real, ausente do OpenAPI. Isso é deliberadamente mais forte que uma
checagem de permissão, que pode ser mal configurada para o lado permissivo; uma rota que
não foi montada não pode. Com a variável, ainda exige token de operador. Não há
contrapartida que conserte a cadeia — ela destruiria a propriedade que esta prova.

### Kill switch do titular — assinatura, não identidade

`POST /principals/{id}/revocations` alcança apenas os mandatos em que aquela chave já é
autoridade registrada, verificados um a um. Nomear um titular no payload não é o mesmo
que sustentá-lo: um token que reivindica o titular alheio, assinado por chave que não é
autoridade nos mandatos dele, é recusado e não muda nada. O titular da URL precisa bater
com o assinado, fechando a mesma brecha de "andar com o token" que a rota de mandato
único fecha comparando `mandate_id`.

### Chave do titular no navegador — o que sai e o que não sai

O par P-256 é gerado com `extractable: false` e persistido no IndexedDB como
`CryptoKey`, o que é a única forma de guardar uma chave não-extraível: o navegador
mantém o material, a página mantém um handle que assina e não consegue ler. Não existe
função de exportação no módulo, e há teste estrutural que falha se aparecer uma.

Limites honestos: um XSS na origem da página pode **usar** a chave para assinar (não
para exportá-la), e limpar os dados do site a apaga — os mandatos que ela sustenta
ficam revogáveis apenas por outra autoridade registrada. Em produção isso pede uma
segunda autoridade `guardian` no mandato, que o schema já suporta.

### Agente com LLM — o que o modelo nunca vê

O leitor de intenção recebe a instrução e **nada mais**: não existe parâmetro para
limite, teto ou saldo. Um modelo com prompt injetado não tem número privado para
repetir, e ler uma frase nunca manda o orçamento da compradora a um terceiro. A saída
é coagida a um `PurchaseIntent` — categoria de um conjunto fechado, preço inteiro e
sanidade checada, palavras-chave truncadas — e qualquer falha cai nas regras. O modelo
propõe; ele não decide, e o núcleo nunca lê o texto dele.
