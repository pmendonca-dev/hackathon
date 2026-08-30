> **Um servidor só.** As chaves já não morrem com o processo — `AVAL_CUSTODY_SEED` as
> reproduz, então um segundo processo deixou de invalidar o primeiro. O que continua
> valendo é o SQLite: um escritor só, e dois `uvicorn` na mesma porta continuam sendo um
> erro. `.\scripts\production\start-aval.ps1` recusa subir se a porta já estiver
> escutando. Sem a semente, o aviso antigo volta inteiro: cada processo sorteia a chave
> do agente, regrava o perfil no banco compartilhado, e todo `/comprar` morre com
> `signature_invalid`.

# Roteiro da demo ao vivo

Duas superfícies, um núcleo. O navegador é onde o titular, o merchant e o auditor
olham; o Telegram é a superfície de bolso do titular. Nenhum dos dois decide nada.

## Subindo tudo

Em produção, um comando só — ele faz migrations, build, túnel HTTPS e API:

```powershell
.\scripts\production\start-aval.ps1
```

Para desenvolvimento, com o servidor separado do Vite:

```powershell
$env:AVAL_DATABASE_PATH = "var/aval.db"
.venv\Scripts\python.exe -m alembic upgrade head

$env:AVAL_OPERATOR_TOKEN = "demo-token"
$env:AVAL_DEMO_TAMPER    = "1"      # habilita a demonstração de adulteração da trilha
$env:AVAL_UI_LOCAL_HTTP  = "true"   # HTTP puro: afrouxa o cookie `Secure`
.venv\Scripts\python.exe -m uvicorn aval.main:app --port 8099
```

Em outro terminal:

```powershell
Set-Location web
$env:VITE_AVAL_API_BASE_URL  = "http://127.0.0.1:8099"
npm run dev
```

O token de operador **não** vai para o navegador. No console trial-by-fire ele é digitado
uma vez e trocado por uma sessão curta; o que a página guarda expira sozinha e some ao
fechar a aba. Um token embutido no bundle é um token publicado.

`AVAL_DEMO_TAMPER` é opcional e **destrutivo por natureza**: sem ele a rota de
adulteração não é montada — 404 de verdade, ausente até do OpenAPI. Ligue apenas para
a demonstração da cadeia de hash.

`AVAL_DEMO_ROGUE` segue a mesma regra e monta a cobrança por fora do núcleo: é o agente
que nunca perguntou ao mandato, e o único caminho que produz dinheiro que a camada não
consegue justificar — logo, o único em que o veredito devolve o valor. Ligue quando for
mostrar a disputa terminando em estorno.

O agente roda por regras. Para demonstrá-lo com um modelo de verdade — que pode
alucinar, e ser recusado mesmo assim:

```powershell
$env:AVAL_LLM_AGENT = "1"
$env:ANTHROPIC_API_KEY = "..."      # sem chave, ele volta às regras sozinho
```

## Verificação limpa

```powershell
.venv\Scripts\python.exe -m pytest -q       # a suíte inteira, verde
.venv\Scripts\python.exe scripts/smoke_demo.py

Set-Location web
npm test                            # a suíte do navegador
npm run build
npm run lint
```

> Os números de testes saíram destes comandos de propósito. Contagem escrita à mão
> envelhece em silêncio, e três documentos citando três totais diferentes é pior do que
> nenhum: o que a banca confere é a suíte verde, não o total.

Com o servidor de pé, a jornada do navegador ponta a ponta:

```powershell
$env:AVAL_OPERATOR_TOKEN = "demo-token"
node --experimental-strip-types tests/live-browser-journey.mjs http://127.0.0.1:8099
```

Ela usa a **mesma** classe de gateway e a **mesma** carteira WebCrypto que a página, e
percorre 29 passos: criar mandato, comprar, ser recusado pelo teto, mudar limite
assinado, gastar essa autorização, conferir a cadeia, checar a projeção do merchant,
abrir uma ordem permanente e vê-la disparar quando o preço cai, avançar o relógio,
adulterar a trilha, revogar — e provar que a vigília não compra depois disso. Se ela
passa, o jurado consegue fazer tudo no navegador.

## A demonstração, na ordem

1. **A pessoa cria o mandato** na visão do titular. A chave que vai assinar tudo é
   gerada no navegador; o servidor recebe só a metade pública. A tira lateral mostra
   qual chave está assinando — ela não rola para fora da tela.

   O mandato nasce **sem meio de pagamento** — ele é autoridade para gastar, não uma
   forma de pagar — então a mesma ação registra o cartão no processador logo em
   seguida, em três chamadas assinadas que nunca carregam um número. O aviso de
   sucesso diz com que cartão o mandato passou a pagar (`•••• 4242`). Se ele disser
   *nenhum cartão registrado*, o agente vai ser recusado em `instrument_not_in_mandate`
   antes de qualquer pergunta sobre dinheiro — e essa é a recusa certa.

2. **O agente compra.** Digite *"compre um voo para Córdoba abaixo de $150"*. A escada
   de avaliação aparece inteira, toda verde, com o orçamento no último degrau — que é
   onde ele tem que estar: autoridade antes de dinheiro.

3. **O agente tenta o que não pode.** *"compre a passagem executiva de $900"* → o teto
   recusa **sem** botão de aprovar. A escada mostra onde parou: `below_ceiling` em
   vermelho, `within_budget` em cinza — *nunca consultado*. Esse cinza é o argumento.

4. **Algo escalável.** *"reserve um hotel"* → `category_not_allowed`, com Aprovar e
   Recusar. Aprovar assina no navegador e a compra retoma.

5. **O jurado muda o limite** no console trial-by-fire e a próxima compra sente. O
   painel separa o que é provado pela chave do titular do que é provado pelo token de
   operador — e o operador, de propósito, não move dinheiro nenhum.

6. **O jurado derruba o processador.** A compra fica em dúvida com o orçamento retido,
   `502`, e `Reconciliar` fecha depois. Timeout não é recusa.

7. **O jurado avança o relógio** e vê o mandato expirar na frente dele. O relógio só
   avança: rebobinar reviveria um mandato expirado, e isso seria um operador devolvendo
   autoridade de gasto.

8. **As três visões.** Titular, merchant e auditor. Na do merchant, o painel lado a
   lado mostra o mesmo evento nas duas projeções e a lista de campos retidos — que vem
   do servidor, não do navegador.

9. **A trilha se defende.** Na visão do auditor, `Adulterar evento`. A linha continua
   bem formada e a cadeia acusa a posição exata. Não há botão que conserte.

10. **A revogação.** Assinada no navegador, irreversível. A tentativa seguinte falha
    com `mandate_revoked`, e a escada para antes de qualquer checagem de dinheiro —
    mesmo para uma compra que também estouraria o teto.

11. **O botão vermelho.** `Revogar tudo desta chave` encerra todos os mandatos que
    aquela chave sustenta, e nenhum outro.

## O que não fingimos

Se o runtime não responde, a tela diz que não respondeu. Não existe fixture por trás
do navegador: uma página que se preenchesse com dados inventados quando o servidor cai
seria indistinguível de uma que funciona, exatamente quando isso mais importa.
