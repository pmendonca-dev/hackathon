# Identidade visual oficial — AVAL

## Essência

AVAL é um **workspace editorial de confiança**: apresenta mandato, autoridade, evidência e decisão de forma legível, sem parecer um dashboard financeiro genérico. O tom é **sereno, técnico, humano e verificável**. A interface explica o que é conhecido, o que está indisponível e o que exige ação; não simula certeza.

`web/src/index.css` é a fonte dos valores abaixo. Este guia registra o frontend existente; não cria uma segunda paleta, fonte ou linguagem de componentes.

## Paleta semântica

| Token | Significado | Uso permitido | Uso proibido |
| --- | --- | --- | --- |
| `ink` (`950`–`750`) | Papel e elevações discretas | Fundo da aplicação, navegação, painéis e superfícies internas | Estado operacional, alerta ou ênfase semântica |
| `fg` (`fg`, `dim`, `mute`, `faint`) | Leitura e hierarquia editorial | Texto, metadado, placeholder e conteúdo secundário conforme a variante | Decisão de autorização ou substituto de contraste suficiente |
| `line` (`line`, `line-hi`) | Estrutura silenciosa | Bordas, divisores, campos e conexão da timeline | Sinalizar sucesso, recusa ou ação principal |
| `allow` (`allow`, `allow-dk`) | Permissão, mandato ativo ou avanço autorizado | CTA primário, badge positivo, rota/medidor autorizado e ícone de aprovação | Aviso, verificação pendente, negação ou decoração sem significado |
| `escalate` (`escalate`, `escalate-dk`) | Atenção humana ou exceção a revisar | Escalonamento, aviso, dado de demonstração e trilha de guarda | Sucesso, erro definitivo ou CTA padrão |
| `deny` (`deny`, `deny-dk`) | Recusa, quebra ou bloqueio seguro | Erro de recusa, evento de trilha rompida e ação destrutiva | Disponibilidade, carregamento ou estado neutro |
| `verify` (`verify`, `verify-dk`) | Evidência, checagem e leitura confiável | Foco, auditabilidade, notas seguras, atualização e metadados de prova | Aprovação automática ou erro/recusa |
| `hold` (`hold`, `hold-dk`) | Espera, retenção ou capacidade ainda não publicada | Estado pendente, indisponibilidade controlada e autonomia em espera | Permissão, perigo ou substituto de `verify` |

As variantes `*-dk` são superfícies leves para seus respectivos tokens; a variante base dá texto, ícone, borda ou traço. Estados críticos nunca dependem somente de cor: sempre trazer texto claro, ícone ou rótulo — como badge, título de erro ou mensagem de status.

## Tipografia

- **Display serif** (`--font-display`: Georgia/Times): títulos narrativos, nomes de painéis, chamadas do mandato e marca. Títulos principais usam `clamp` de 2.15–4rem; títulos internos ficam próximos de 1–1.6rem, com peso moderado e tracking levemente negativo.
- **Sans** (`--font-sans`: Inter/system): leitura, descrições, controles e texto de interface. Texto corrente permanece compacto e legível (em geral 11–13px), com line-height confortável para explicações.
- **Mono** (`--font-mono`: JetBrains Mono/Consolas): IDs, valores técnicos, códigos HTTP, status, rótulos `eyebrow`, horários e evidência. Usa números tabulares e caixa alta apenas para rótulos curtos.

Não usar mono para parágrafos, display para dados técnicos, nem todas as três famílias no mesmo elemento. Não usar título display como rótulo de botão ou campo.

## Sistema de interface

**Superfícies.** O `Panel` é o card padrão: `ink-850`, borda `line`, raio `rounded-2xl`, cabeçalho separado por linha e padding de 1.25rem. Cards especiais mantêm raios suaves entre .75rem e 1.35rem; sombras são baixas e neutras, reservadas para atlas, cenários e nós. Não usar sombras pesadas ou gradientes como estado.

**Grid e espaço.** A página usa `page-shell` com máximo de 1240px, padding lateral de 1.25rem e gap base de 1rem; conteúdo interno usa passos de 0.5–1.25rem. Grids operacionais usam `gap-4`. A grade de cenários vai de cinco para três colunas em 1080px, duas em 760px e uma em 480px. Cabeçalhos empilham em 760px; não comprimir títulos ou controles para preservar uma linha artificialmente.

**Timeline de auditoria.** Usar lista ordenada, sequência mono em cápsula, linha `line-hi` entre eventos e card de evento com borda. `verify` marca a sequência normal; uma quebra usa `deny` mais texto de evento. A ordem, o número e a data são evidência legível, não ornamento.

**Formulários e labels.** Todo controle recebe label visível, `form-control`, fonte mono e altura mínima de 2.8rem. Bordas começam em `line-hi` e foco usa `verify`; placeholder usa `fg-faint`. Ajuda e validação ficam junto ao controle.

**Labels e botões.** `eyebrow` é mono, 10px, em caixa alta e apenas para contexto curto. Badges unem texto e tom; não substituem a explicação. Botões são mono, mínimo de 2.5rem e raio `rounded-lg`: `primary` é `allow`, `ghost` é neutro e `danger` é `deny`. Ícones acompanham o texto; não são o único nome de uma ação.

**Estados.** Carregamento mostra spinner mais mensagem com `role=status` e `aria-live=polite`; atualização usa `verify`. Indisponibilidade e falha usam `RuntimeFailure`, com título, código, orientação e foco no alerta. Sucesso usa `allow` com rótulo e ícone; escalonamento usa `escalate` e indica a revisão humana; recusa usa `deny`, motivo e próximo passo seguro. Uma capacidade não publicada usa `hold` ou controle desabilitado com explicação explícita — jamais sucesso simulado.

## Acessibilidade e segurança visual

- Manter `:focus-visible` de 3px em `verify`, offset e anel de superfície; preservar o skip link e o tratamento `forced-colors`.
- Garantir contraste entre texto, superfície e borda; texto `fg-faint` é apenas placeholder ou apoio, nunca informação essencial.
- Respeitar `prefers-reduced-motion`: animação e transição tornam-se praticamente instantâneas. Animação nunca é a única indicação de mudança de estado.
- Estados `disabled` ou `aria-disabled` continuam legíveis, com cursor bloqueado, saturação/opacidade reduzidas e motivo visível quando a ação não está disponível.
- Nunca renderizar PAN, `vt_`, JWS, `proof`, chaves ou credenciais em projeções, timeline, status, logs, erros ou evidência. Um formulário de autenticação pode receber uma credencial local em campo protegido, mas nunca a reapresenta.

## Governança

- `web/src/index.css` é a origem de tokens; componentes reutilizam esses tokens e utilitários Tailwind correspondentes, sem hexadecimais arbitrários.
- Mudança de paleta, tipografia ou significado de `allow`, `escalate`, `deny`, `verify` ou `hold` exige atualização deste guia e de `docs/decision-log.md`.
- Novos estados devem escolher um token semântico existente e incluir texto, ícone ou rótulo acessível; não criar cor para contornar uma decisão de produto.
