# Arquitetura do AVAL

Entregável do Mission Control. O PDF que vai no formulário é
[`architecture.pdf`](architecture.pdf), gerado deste arquivo — regenere depois de
qualquer edição, para que a imagem enviada e o documento versionado não divirjam:

```bash
uv run --with markdown python scripts/export_architecture.py
```

---

## A tese, em uma linha

**O LLM propõe. O núcleo determinístico dispõe. O modelo nunca está no caminho de
confiança.**

Todo o desenho abaixo existe para tornar essa frase verificável em vez de dita.

---

## Visão geral

```mermaid
flowchart TB
    subgraph clientes["Quem age"]
        H["Titular<br/><i>navegador · Telegram</i>"]
        A["Agente comprador<br/><i>propõe; chave própria</i>"]
        M["Merchant VuelaYa<br/><i>verifica antes de aceitar</i>"]
        AUD["Auditor"]
    end

    subgraph borda["Borda HTTP — autentica, nunca autoriza"]
        AUTH9421["RFC 9421<br/><i>quem está chamando?</i>"]
        OPTOK["Token de operador<br/><i>quem opera a instância?</i>"]
        FORMA["Validação de forma<br/><i>Pydantic</i>"]
    end

    subgraph nucleo["AuthorizationCore — o único que decide autoridade"]
        LADDER["Escada de avaliação<br/><i>ordem fixa, para no 1º não</i>"]
        ESC["Escalação<br/><i>awaiting_human + handle</i>"]
    end

    subgraph persist["Persistência — SQLite WAL, escritor único"]
        MAND[("mandatos<br/>+ autoridades")]
        RES[("reservas<br/>+ commit stamp")]
        REV[("revogações")]
        LEDGER[("trilha<br/><i>cadeia de hash</i>")]
    end

    PSP["PSP simulado<br/><i>online · offline · decline</i>"]

    H -->|"JWS ES256 assinado<br/>no próprio navegador"| FORMA
    A -->|"assinatura sobre<br/>método, caminho e digest"| AUTH9421
    M -->|"prova de autorização"| FORMA
    AUD --> FORMA
    H -.->|"derrubar PSP · reconciliar<br/>relógio · adulterar"| OPTOK

    AUTH9421 --> nucleo
    OPTOK --> PSP
    FORMA --> nucleo

    LADDER --> MAND
    LADDER --> REV
    LADDER --> RES
    LADDER -->|"fora do mandato,<br/>mas aprovável"| ESC
    nucleo --> LEDGER
    nucleo --> PSP

    classDef core fill:#1E2610,stroke:#C6F24E,color:#C6F24E
    classDef edge fill:#0D2229,stroke:#4ED8F2,color:#4ED8F2
    class nucleo,LADDER,ESC core
    class borda,AUTH9421,OPTOK,FORMA edge
```

A separação que mais importa está nas duas setas que saem do titular: uma leva uma
**assinatura**, a outra leva um **token de operador**. A primeira move dinheiro; a
segunda opera a instância e, de propósito, não move dinheiro nenhum.

---

## A escada de avaliação

A ordem **é** a regra. O núcleo para no primeiro degrau que falha, e os degraus abaixo
nunca são consultados — é isso que impede uma revogação de ser contornada por uma
compra pequena o bastante.

```mermaid
flowchart TD
    S([compra proposta]) --> E1{mandato existe?}
    E1 -->|não| R1[/rejected<br/>mandate_not_found/]
    E1 --> E2{revogação legível?}
    E2 -->|não| R2[/rejected<br/>revocation_unavailable/]
    E2 --> E3{não revogado?}
    E3 -->|não| R3[/rejected<br/>mandate_revoked/]
    E3 --> E4{merchant não revogado?}
    E4 -->|não| R4[/rejected<br/>merchant_revoked/]
    E4 --> E4B{instrumento não revogado?}
    E4B -->|não| R4B[/rejected<br/>instrument_revoked/]
    E4B --> E5{orçamento não zerado?}
    E5 -->|não| H1[/awaiting_human<br/>budget_revoked/]
    E5 --> E6{dentro da validade?}
    E6 -->|não| R6[/rejected<br/>mandate_expired/]

    E6 --> E7{merchant no escopo?}
    E7 -->|não| H2[/awaiting_human/]
    E7 --> E8{categoria no escopo?}
    E8 -->|não| H3[/awaiting_human/]
    E8 --> E8B{é o cartão do mandato?<br/><i>só na captura</i>}
    E8B -->|não| R8B[/rejected<br/>instrument_not_in_mandate/]
    E8B --> E9{moeda e escala?}
    E9 -->|não| R9[/rejected/]
    E9 --> E10{valor positivo?}
    E10 -->|não| R10[/rejected/]
    E10 --> E11{abaixo do TETO?}
    E11 -->|não| R11[/rejected<br/>mandate_ceiling<br/><b>sem botão de aprovar</b>/]
    E11 --> E11B{há vaga de reserva?}
    E11B -->|não| R11B[/rejected<br/>reservation_limit<br/><b>sem botão de aprovar</b>/]
    E11B --> E12{dentro da frequência?}
    E12 -->|não| H4[/awaiting_human/]
    E12 --> E13{dentro do ORÇAMENTO?}
    E13 -->|não| H5[/awaiting_human/]
    E13 --> OK[/authorized/]

    classDef authority fill:#0D2229,stroke:#4ED8F2,color:#4ED8F2
    classDef money fill:#2A2010,stroke:#F5B942,color:#F5B942
    class E1,E2,E3,E4,E4B,E5,E6,E7,E8,E8B authority
    class E9,E10,E11,E11B,E12,E13 money
```

Dezesseis degraus, e a lista acima é a ordem literal de `_evaluate_with()`. Três deles
respondem perguntas que só existem porque o mandato nomeia um cartão e porque um agente
pode travar o orçamento sem gastar nada: **o cartão foi cancelado** (`instrument_revoked`),
**é o cartão certo** (`instrument_not_in_mandate`, checado só na captura, que é onde a
pergunta é real) e **sobrou vaga de reserva** (`reservation_limit`). Este último recusa em
vez de escalar de propósito: apertar aprovar não solta dinheiro que já está preso — quem
solta é `POST /reconcile`.

Em azul, autoridade. Em amarelo, dinheiro. **Autoridade sempre primeiro.** Cada decisão
devolve `evaluation_trace` com exatamente os degraus percorridos, e o front-end desenha
os não percorridos em cinza — a ausência é a evidência.

Três resultados, não dois: `authorized`, `awaiting_human` (fora do mandato mas
aprovável, com handle assinável) e `rejected` (teto, revogação, expiração — sem caminho
de volta, porque não há o que aprovar).

---

## As quatro autoridades

| pergunta | prova | quem detém |
|---|---|---|
| *quem está chamando?* | assinatura RFC 9421 | o agente |
| *esta compra pode acontecer?* | avaliação do mandato | ninguém: é determinística |
| *quem muda a autoridade de gasto?* | JWS ES256 | o titular (chave no navegador) |
| *quem opera a instância?* | token de operador | o time |

```mermaid
flowchart LR
    subgraph titular["Chave do titular — WebCrypto, extractable: false"]
        T1["mudar limite"]
        T2["aprovar escalação"]
        T3["revogar mandato"]
        T4["revogar tudo"]
    end
    subgraph operador["Token de operador"]
        O1["registrar agente"]
        O2["derrubar / religar PSP"]
        O3["reconciliar"]
        O4["avançar relógio<br/><i>só para frente</i>"]
        O5["adulterar trilha<br/><i>+ AVAL_DEMO_TAMPER</i>"]
    end
    titular ==>|move dinheiro| DINHEIRO(("💰"))
    operador -.->|"nunca move dinheiro"| DINHEIRO

    classDef holder fill:#1E2610,stroke:#C6F24E,color:#C6F24E
    classDef op fill:#171833,stroke:#8B93FF,color:#8B93FF
    class titular,T1,T2,T3,T4 holder
    class operador,O1,O2,O3,O4,O5 op
```

O relógio só avança porque rebobiná-lo reviveria um mandato expirado — e isso seria um
operador devolvendo autoridade de gasto.

---

## O circuito completo de uma compra

```mermaid
sequenceDiagram
    participant P as Titular
    participant B as Navegador
    participant AG as Agente
    participant N as AuthorizationCore
    participant ME as VuelaYa
    participant PS as PSP
    participant L as Trilha

    P->>B: cria mandato
    B->>B: gera par P-256 (não-extraível)
    B->>N: POST /mandates + JWK público
    N->>L: mandate.registered

    P->>AG: "compre um voo abaixo de $150"
    AG->>ME: GET /merchant/offers
    ME-->>AG: ofertas assinadas (JWS + nonce)
    AG->>N: POST /authorize (assinado RFC 9421)
    N->>N: escada de avaliação
    N-->>AG: authorized + evaluation_trace
    AG->>N: POST /capture
    N->>PS: autorizar
    PS-->>N: liquidado
    N->>L: capture.committed
    N-->>AG: prova de autorização

    AG->>ME: entrega a prova
    ME->>N: POST /merchant/verify
    N-->>ME: accepted ✓ (sem mandato, sem comprador)

    P->>B: revogar
    B->>B: assina JWS com a chave local
    B->>N: POST /mandates/{id}/revocation
    N->>L: revocation.holder
    AG->>N: tenta comprar de novo
    N-->>AG: mandate_revoked (parou no 3º degrau)
```

O merchant verifica sem receber `mandate_id` nem `principal_id`. A prova vincula
`checkout_id`, `merchant_id`, valor, moeda e `terms_hash` — e **omite** os dois. Um
recibo que vazasse o orçamento da compradora vazaria a compradora.

---

## A trilha que se defende

```mermaid
flowchart LR
    G["genesis<br/>000…000"] --> E1["evento 1<br/>sha256(canônico + prev)"]
    E1 --> E2["evento 2"]
    E2 --> E3["evento 3"]
    E3 --> E4["evento 4"]

    X["✎ alguém edita<br/>o evento 2"] -.-> E2
    E2 -.->|"digest não bate"| BREAK["/ledger/verify<br/>intact: false<br/>broken_at: 2"]
    E3 -.->|"elo herda a quebra"| BREAK
    E4 -.-> BREAK

    classDef ok fill:#1E2610,stroke:#C6F24E,color:#C6F24E
    classDef bad fill:#2A1315,stroke:#FF5C5C,color:#FF5C5C
    class G,E1 ok
    class X,BREAK bad
```

Cada evento canonicaliza a si mesmo (RFC 8785) e encadeia o digest do anterior. Não é
um log que o operador promete não editar — é um log que o auditor confere sem confiar
no operador. Com `AVAL_DEMO_TAMPER=1` o jurado quebra um elo e vê a posição ser
apontada. Não existe rota que conserte a cadeia.

---

## Camadas do código

```mermaid
flowchart TB
    subgraph web["web/ — navegador"]
        W1["wallet/<br/><i>chave nunca exportável</i>"]
        W2["gateways/<br/><i>transporte, não decide</i>"]
        W3["pages/<br/><i>titular · merchant · auditor · trial</i>"]
    end
    subgraph tg["interfaces/telegram/"]
        G1["gateway.py<br/><i>único seam com o AVAL</i>"]
    end
    subgraph api["api/ — casca HTTP fina"]
        A1["routes/ · routers/"]
        A2["agent_auth · operator_auth"]
    end
    subgraph app["application/"]
        C1["AuthorizationCore<br/><b>o único que decide</b>"]
        C2["ledger_views<br/><i>3 projeções</i>"]
    end
    subgraph dom["domain/"]
        D1["entidades e invariantes<br/><i>sem I/O, sem framework</i>"]
    end
    subgraph inf["infrastructure/ · security/"]
        I1["SQLite WAL"]
        I2["JWS · RFC 9421 · RFC 8785"]
    end

    web --> api
    tg --> api
    api --> app
    app --> dom
    app --> inf

    classDef core fill:#1E2610,stroke:#C6F24E,color:#C6F24E
    class app,C1,C2 core
```

O núcleo não sabe o que foi comprado — recebe `checkout_id` como string opaca. Produto,
oferta e liquidação vivem fora dele, o que é o que permite trocar o merchant sem tocar
em uma linha de regra de autorização.

---

## Fronteiras assumidas

Escolhas de demonstração, e defensáveis como tal:

- **SQLite** com WAL e `BEGIN IMMEDIATE`; repositórios atrás de portas para trocar por
  Postgres sem tocar no núcleo.
- **Custódia de chave em memória** no servidor. Em produção seria HSM/KMS, e a interface
  (`KeyCustodyService`) já é a que um HSM implementaria. A chave do **titular** já não
  vive no servidor: ela é do navegador.
- **PSP simulado**, controlável, para que a história de falha seja demonstrada e não
  narrada.
- **Sem PAN em lugar nenhum.** Não é que o cartão esteja bem guardado: ele nunca existe
  no sistema.
