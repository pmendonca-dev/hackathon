> ⚠️ **Um servidor só, e sem `--reload`.** Cada processo gera a chave do agente em
> memória e regrava o perfil no banco compartilhado, então dois `uvicorn` na mesma
> porta — ou um `--reload` recarregando no meio da demo — fazem o último a subir vencer
> e o outro passar a assinar com uma chave que o banco não reconhece: todo `/comprar`
> morre com `signature_invalid`. Antes do pitch: `netstat -ano | findstr 8099` e garanta
> que só existe um.

# Roteiro da demo ao vivo

Duas superfícies, um núcleo. O navegador é onde o titular, o merchant e o auditor
olham; o Telegram é a superfície de bolso do titular. Nenhum dos dois decide nada.

## Subindo tudo

```powershell
uv run alembic upgrade head

$env:AVAL_OPERATOR_TOKEN = "demo-token"
$env:AVAL_DEMO_TAMPER    = "1"      # habilita a demonstração de adulteração da trilha
uv run uvicorn aval.main:app --port 8099
```

Em outro terminal:

```powershell
Set-Location web
$env:VITE_AVAL_API_BASE_URL  = "http://127.0.0.1:8099"
$env:VITE_AVAL_OPERATOR_TOKEN = "demo-token"
npm run dev
```

`AVAL_DEMO_TAMPER` é opcional e **destrutivo por natureza**: sem ele a rota de
adulteração não é montada — 404 de verdade, ausente até do OpenAPI. Ligue apenas para
a demonstração da cadeia de hash.

O agente roda por regras. Para demonstrá-lo com um modelo de verdade — que pode
alucinar, e ser recusado mesmo assim:

```powershell
$env:AVAL_LLM_AGENT = "1"
$env:ANTHROPIC_API_KEY = "..."      # sem chave, ele volta às regras sozinho
```

## Verificação limpa

```powershell
uv run pytest -q                    # 404 testes
uv run python scripts/smoke_demo.py

Set-Location web
npm test                            # 32 testes
npm run build
npm run lint
```

Com o servidor de pé, a jornada do navegador ponta a ponta:

```powershell
$env:AVAL_OPERATOR_TOKEN = "demo-token"
node --experimental-strip-types tests/live-browser-journey.mjs http://127.0.0.1:8099
```

Ela usa a **mesma** classe de gateway e a **mesma** carteira WebCrypto que a página, e
percorre 14 passos: criar mandato, comprar, ser recusado pelo teto, mudar limite
assinado, conferir a cadeia, checar a projeção do merchant, avançar o relógio,
adulterar a trilha e revogar. Se ela passa, o jurado consegue fazer tudo no navegador.

## A demonstração, na ordem

1. **A pessoa cria o mandato** na visão do titular. A chave que vai assinar tudo é
   gerada no navegador; o servidor recebe só a metade pública. A tira lateral mostra
   qual chave está assinando — ela não rola para fora da tela.

2. **O agente compra.** Digite *"compre um voo para Córdoba abaixo de $150"*. A escada
   de avaliação aparece inteira: doze degraus verdes, com o orçamento no fim.

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
