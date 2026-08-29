# Integração AP2 no AVAL — Documento de Decisão

**Data da investigação:** 29 de agosto de 2026  
**Upstream analisado:** [`google-agentic-commerce/AP2`](https://github.com/google-agentic-commerce/AP2) no commit [`e1ea56db72a6385bce3e5c1112b3a56ce60acb43`](https://github.com/google-agentic-commerce/AP2/tree/e1ea56db72a6385bce3e5c1112b3a56ce60acb43)  
**Escopo:** análise técnica somente de leitura; nada do AP2 foi importado, instalado ou executado.

## Resumo executivo

O AP2 deve ser usado como camada de protocolo criptográfico para mandatos e recibos, não como arquitetura do produto AVAL. O valor reutilizável está nos schemas, SD-JWT/KB-SD-JWT, validação de cadeias e vínculo de recibos. Revogação, orçamento vivo, prevenção de double-spend, decisão de captura e ledger devem ser implementados por código determinístico do AVAL.

O OpenAI API fica exclusivamente na camada de conversa e solicitação de ferramentas. O modelo nunca recebe chaves nem autoridade para assinar, revogar, consumir orçamento, capturar pagamento ou emitir recibos.

## 1. Inventário atual do AVAL

O repositório contém apenas um `README.md` inicial e a skill de Flight Log em `.agents/`. Não há aplicação, API, banco, manifestos de dependência, testes ou UI implementados. O diretório `tmp/` já existia como conteúdo não rastreado e não foi alterado.

Antes da integração AP2, faltam:

1. API/backend autenticado e modelo de domínio.
2. Custódia de chaves e assinatura determinística.
3. Banco durável para mandatos, revogações, nonces, contadores, recibos e auditoria.
4. Serviço de autorização/captura transacional.
5. Registro confiável de merchants e suas chaves.
6. Merchant mock, PSP mock, UI e testes de segurança/concorrência.

## 2. Inventário AP2 relevante

| Área | Paths upstream | Uso pretendido |
|---|---|---|
| Schemas canônicos | `code/sdk/schemas/ap2/{open_checkout_mandate,checkout_mandate,open_payment_mandate,payment_mandate,checkout_receipt,payment_receipt}.json`; `code/sdk/schemas/ap2/types/*.json` | Contratos do protocolo e tipos. |
| Modelos gerados | `code/sdk/python/ap2/sdk/generated/**/*.py` | Modelos Pydantic para mandatos, recibos e tipos AP2. |
| Fachada de mandatos | `code/sdk/python/ap2/sdk/mandate.py` | `create`, `present`, `verify` e hash do JWT fechado. |
| Primitivas criptográficas | `code/sdk/python/ap2/sdk/sdjwt/{common,sd_jwt,kb_sd_jwt,chain}.py` | SD-JWT, KB-SD-JWT, `cnf`, bindings, `aud`, `nonce` e trust chain. |
| Constraints e chains | `code/sdk/python/ap2/sdk/{constraints,payment_mandate_chain,checkout_mandate_chain,max_flow_helper}.py` | Validação estática de constraints e line items. |
| Recibos | `code/sdk/python/ap2/sdk/{receipt_wrapper,jwt_helper,utils}.py` | Payloads AP2, ES256 e referência SHA-256. |
| Disclosure | `code/sdk/python/ap2/sdk/disclosure_metadata.py` | Regras de selective disclosure. |

O SDK declara `cryptography==46.0.5`, `jwcrypto==1.5.6`, `pydantic==2.12.5` e `sd-jwt==0.10.4`. O código AP2 é Apache-2.0.

### Componentes de demo a excluir

- Python shopping agents: `code/samples/python/src/roles/shopping_agent/**` e `shopping_agent_v2/**` usam Gemini, ADK, A2A e MCP.
- Infraestrutura A2A/MCP: `code/samples/python/src/common/{a2a_*,base_server_executor,payment_remote_a2a_client,server}.py` e `roles/*_mcp/**`.
- x402: `roles/x402_*`, que usa Web3 e chaves de demo.
- Go: `code/samples/go/**`, que usa Gemini e `GOOGLE_API_KEY`.
- Android: `code/samples/android/**`, que usa Gemini Android SDK, `GEMINI_API_KEY`, Compose e A2A.
- Web client: `code/web-client/**`; pode servir de referência visual, mas não como base da arquitetura.

## 3. Classificação de importação futura

| Área AP2 | Classificação | Razão |
|---|---|---|
| Schemas `code/sdk/schemas/ap2/**` | **Import unchanged** | Vendorizar imutáveis no commit pinado; criar `aval.*` fora dos schemas AP2. |
| Modelos `sdk/generated/**` | **Vendor and adapt** | Regenerar a partir de schemas pinados e encapsular no domínio AVAL. |
| `sdk/sdjwt/**` | **Vendor and adapt** | Núcleo de verificação AP2; expor somente por interface local. |
| `sdk/mandate.py` | **Vendor and adapt** | Escreve em `.logs/mandate_operations.log` e acessa API privada de `sd-jwt`; esses comportamentos devem ser isolados. |
| `sdk/{payment_mandate_chain,checkout_mandate_chain}.py` | **Reimplement behind a local interface** | AVAL precisa adicionar estado vivo, locks e idempotência à validação estática AP2. |
| `sdk/constraints.py` | **Use only as a reference** | Orçamento e recorrência dependem de contexto em memória, sem consumo atômico. |
| `sdk/max_flow_helper.py` | **Import unchanged** | Algoritmo puro útil para constraints de line items, desde que cuberto por testes de equivalência. |
| `sdk/disclosure_metadata.py` | **Vendor and adapt** | Útil, mas disclosure deve obedecer a política por destinatário. |
| `sdk/utils.py` | **Import unchanged** | `compute_sha256_b64url` é adequado para referência estável de recibos. |
| `sdk/{jwt_helper,receipt_wrapper}.py` | **Reimplement behind a local interface** | Recibos devem usar custódia de chaves AVAL e emissão pós-captura. |
| `code/sdk/python/ap2/models/**` | **Use only as a reference** | Modelos de demos/Payment Request, fora do núcleo atual de mandates. |
| `code/sdk/python/ap2/tests/**` | **Use only as a reference** | Transformar casos importantes em testes AVAL, sem importar testes como dependência. |
| `code/samples/**` | **Ignore** | Acoplamento a Gemini, ADK, A2A, MCP, Web3 e UI de demonstração. |

Ao vendorizar código Apache-2.0, preservar `LICENSE`, headers de copyright e atribuição, marcar arquivos modificados e manter um manifesto com commit e hashes. O commit analisado não possui um arquivo `NOTICE`. Licenças das dependências transitivas devem ser revisadas separadamente.

## 4. Design de migração para OpenAI

O Shopping Agent usa a Responses API apenas para conversação e chamadas de funções tipadas. A documentação oficial confirma que Responses aceita ferramentas personalizadas para chamar código da aplicação: [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).

```text
Usuário ↔ Shopping Agent (OpenAI)
                  ↓ solicitação não confiável
          Gateway determinístico de ferramentas
          ├─ pesquisar catálogo
          ├─ criar rascunho de compra
          └─ enviar request_id imutável para autorização
                           ↓
          AVAL Authorization/Capture Service
          ├─ valida AP2 e estado vivo
          ├─ aplica locks, limites e revogação
          └─ chama merchant e PSP mocks
```

Regras:

- Ferramentas do modelo só podem ler catálogo, montar rascunho e solicitar compra por `request_id` criado pelo servidor.
- Preço, merchant, itens e mandatos são recuperados pelo backend; nunca aceitos como verdade a partir do modelo.
- Confirmação humana, assinatura, revogação, consumo de limite, captura e recibo são endpoints/serviços determinísticos.
- Não reter Gemini, Google AI Studio, Vertex AI, ADK, A2A, MCP/FastMCP ou dependências Gemini.

Nenhum modelo OpenAI foi escolhido. A escolha posterior deve considerar tool calling/JSON estruturado, desempenho em português, robustez contra prompt injection, latência, custo, limites e resultados de avaliações adversariais.

## 5. Arquitetura mínima AP2 + AVAL

| AP2 | AVAL |
|---|---|
| Open/Closed Checkout e Payment Mandates | Estado de mandatos, política versionada e revogação ao vivo |
| SD-JWT, KB-SD-JWT, `cnf`, `aud`, `nonce` e bindings | Limites vivos, contadores duráveis e locks contra replay/double-spend |
| Validação estática de constraints | Constraints `aval.*`, revalidação no capture e merchant registry |
| Hash do JWT fechado e modelos de recibo | Ledger compartilhado, idempotência e emissão de recibo após captura |

Fluxo mock:

1. Merchant mock entrega catálogo, checkout assinado e desafio único `{aud, nonce, transaction_id}`.
2. Após confirmação humana, serviço de assinatura AVAL produz/apresenta a cadeia AP2 usando chaves de demo gerenciadas no servidor.
3. Merchant mock valida a cadeia e chama AVAL Capture.
4. Capture obtém lock por mandato/transação/nonce, revalida AP2 e política viva e registra tentativa idempotente.
5. PSP mock devolve resultado determinístico `approved` ou `declined`, sem PAN, CVV ou rede real.
6. AVAL grava o ledger e emite recibos AP2 ligados ao hash do JWT fechado.

## 6. Riscos e validação

| Risco | Mitigação |
|---|---|
| README aponta schemas em path diferente do real (`code/sdk/python/ap2/schemas` versus `code/sdk/schemas`). | Usar paths reais e manifesto de origem. |
| `schemas/generate.py` depende de `datamodel_code_generator`, não declarado no `pyproject.toml`. | Fixar ferramenta/versão e revisar modelos gerados. |
| `MandateClient.verify` suporta cadeia arbitrária, mas os parsers tipados exigem exatamente dois payloads. | Limitar MVP a uma delegação ou normalizar cadeias explicitamente. |
| Checkout chain decodifica, mas não verifica assinatura do JWT de checkout. | Verificar assinatura/chave do merchant antes de aplicar constraints. |
| `ReceiptClient.verify_receipt` declara callback opcional, mas o chama mesmo quando `None`. | Corrigir atrás da interface local e testar. |
| Default de clock skew é 300 segundos. | Configuração AVAL explícita e testes de relógio. |
| `main` é mutável e o commit atual removeu `uv.lock`. | Pin por SHA; nunca instalar diretamente de `main`. |
| AP2 não implementa revogação, ledger, locks ou consumo atômico. | Implementar esses controles exclusivamente no AVAL. |

Testes mínimos obrigatórios:

1. Compra válida, incluindo cadeia, `aud`, `nonce`, constraints e recibos.
2. Mandato expirado antes da reserva/captura.
3. Mandato revogado após emissão, recusado no capture.
4. Duas capturas concorrentes: exatamente uma consome o mandato.
5. Compra fora de constraints: valor, merchant, instrumento ou item inválido.
6. Complementares: adulteração de JWT, `aud`/`nonce` incorretos, mudança de limite entre aprovação e captura e recibo com referência desconhecida.

## 7. Próximos passos recomendados

### Trabalho obrigatório, em ordem

1. Ratificar a stack do backend. Python é recomendado porque o SDK AP2 relevante é Python, mas essa escolha ainda precisa de confirmação do time.
2. Definir interfaces locais: `MandateVerifier`, `MandateSigner`, `AuthorizationPolicy`, `CaptureService`, `ReceiptService` e `AuditLedger`.
3. Vendorizar os schemas AP2 no SHA fixado e registrar origem, hashes e licenças.
4. Integrar SD-JWT/KB-SD-JWT atrás de `MandateVerifier`; não expor o SDK diretamente às rotas.
5. Implementar banco/ledger, revogação, nonces, limites vivos, reservas e captura idempotente.
6. Implementar merchant mock e PSP mock determinísticos.
7. Integrar o adaptador OpenAI com ferramentas apenas de leitura, rascunho e submissão segura.
8. Criar a suíte de testes de mandato, captura e concorrência antes da UI.

### Reuso opcional de AP2

- Consultar `shopping_agent_v2/shopping_agent/mandate_tools.py` apenas para compreender a sequência de mandates.
- Reaproveitar `max_flow_helper.py` depois de testes de equivalência.
- Usar o web client somente como referência visual de apresentação de mandatos e recibos.
- Não reutilizar código Gemini/ADK/A2A/MCP/x402/Android/Go.

## Flight Log proposto

As entradas abaixo ainda não foram registradas; estão prontas para uso quando o time ratificar as decisões.

### Scope of AP2 adoption

**Decision:** Scope of AP2 adoption  
**Options considered (one per line):**  
Adopt AP2 samples as the product architecture  
Use AP2 only as the cryptographic mandate and receipt protocol layer  
Reimplement the entire protocol independently  
**What we chose:** Use AP2 as the cryptographic mandate and receipt protocol layer, not as the product architecture.  
**Why:** The samples depend on Gemini, ADK, A2A, MCP, and demo infrastructure that conflict with AVAL’s OpenAI-only and deterministic-authority requirements.

### AP2 version source

**Decision:** AP2 version source  
**Options considered (one per line):**  
Track AP2 main directly  
Pin AP2 to the investigated commit  
Wait for a future packaged release  
**What we chose:** Pin any later vendored AP2 material to commit e1ea56db72a6385bce3e5c1112b3a56ce60acb43.  
**Why:** Main is mutable, the current commit removed the lockfile, and reproducible cryptographic protocol behavior requires an explicit source revision.

### Trusted authorization boundary

**Decision:** Trusted authorization boundary  
**Options considered (one per line):**  
Allow the LLM to sign and capture purchases  
Allow the LLM to call privileged services directly  
Keep signing, revocation, budget use, capture, and receipts in deterministic server-side services  
**What we chose:** Keep all trusted purchase authority in deterministic server-side services.  
**Why:** The LLM is untrusted and must not control keys, policy state, funds, or evidence issuance.

### OpenAI integration role

**Decision:** OpenAI integration role  
**Options considered (one per line):**  
Replace AP2 with LLM-generated purchase records  
Use OpenAI only for conversation and constrained tool requests  
Retain Gemini or ADK alongside OpenAI  
**What we chose:** Use OpenAI only for conversation and constrained tool requests.  
**Why:** This preserves AP2 verification semantics and prevents model output from becoming authorization.

### Live authorization controls

**Decision:** Live authorization controls  
**Options considered (one per line):**  
Rely only on AP2 static constraints  
Implement revocation and limits in the LLM prompt  
Implement AVAL revocation, durable counters, locks, and capture-time revalidation  
**What we chose:** Implement live controls in AVAL with durable transactional state.  
**Why:** AP2 constraints do not provide revocation, concurrent-spend protection, or durable budget accounting.

### Demonstration payment mechanism

**Decision:** Demonstration payment mechanism  
**Options considered (one per line):**  
Integrate a real card processor  
Reuse x402 or Web3 demo flows  
Use deterministic merchant and payment-processor mocks  
**What we chose:** Use deterministic merchant and payment-processor mocks for the hackathon flow.  
**Why:** This demonstrates authorization, capture, receipts, and auditability without card data, external settlement risk, or Gemini-linked sample dependencies.
