# Regras oficiais — NextWave Hackathon 2026

> Fonte de verdade para o time. Levantamento feito em 29/08/2026 somente nas páginas públicas oficiais do evento. Quando o site não publica um detalhe, isso é dito explicitamente em vez de inferi-lo.

## Leitura rápida

- O evento tem **24 horas de desenvolvimento**: de `T-ZERO` até o `code freeze`.
- Cada equipe trabalha em **exatamente um** dos quatro desafios; a escolha é final.
- O resultado esperado é um **protótipo funcional**, operável pelos jurados sem intervenção do time.
- A submissão tem cinco artefatos: **slides, demo, repositório GitHub público com README, diagrama de arquitetura e decision log**.
- A defesa técnica pesa tanto quanto a demo. Profundidade, funcionamento real e capacidade de justificar escolhas têm prioridade sobre volume de funcionalidades ou espetáculo.
- Para este repositório, o desafio escolhido é o **Challenge 01 — The Buyer Who Isn't Human**.

Fontes: [Challenges](https://nextwave-hackathon-2026.vercel.app/challenges), [Timeline](https://nextwave-hackathon-2026.vercel.app/schedule), [Evaluation Guidelines](https://nextwave-hackathon-2026.vercel.app/judging).

## Regras gerais do jogo

### Obrigações publicadas

1. Trabalhar em **um único desafio**. Cada equipe enfrenta exatamente um dos quatro desafios e a escolha não pode ser desfeita.
2. Entregar um **protótipo funcional**. A página descreve equipes de quatro pessoas e orienta escolher profundidade em vez de dificuldade.
3. Passar pelo **trial by fire**: os jurados operam o sistema ao vivo com uma entrada não ensaiada; o sistema deve reagir corretamente sem que o time toque em nada.
4. Defender cada escolha relevante. É permitido inventar dados, fluxos, APIs, bancos de dados, frameworks e protocolos, mas o time deve conseguir explicar e justificar o que escolheu.
5. Submeter tudo antes do **code freeze**; nesse momento as submissões são bloqueadas.

Fonte: [Challenges — protocolo aplicável a todos os desafios](https://nextwave-hackathon-2026.vercel.app/challenges) e [Timeline](https://nextwave-hackathon-2026.vercel.app/schedule).

### Entregáveis e modelo publicado

| Artefato | Exigência explícita | Campo exposto pela interface oficial |
|---|---|---|
| Apresentação | Slides | URL dos slides |
| Demo | Ao vivo ou em vídeo | URL da demo (vídeo ou live) |
| Código | Repositório **público** no GitHub, com README | URL pública do repositório |
| Arquitetura | Diagrama de arquitetura | Upload em PDF ou PNG, até 25 MB |
| Decisões | Decision log com alternativas consideradas e justificativa da escolha | Flight Log exportável em Markdown para o repositório |

Os cinco itens são tratados como entregáveis: a página de avaliação avisa que ausências serão percebidas. O portal não informa template obrigatório, quantidade de slides, estrutura específica do README ou convenção de nome para o decision log.

A demo em vídeo é aceita como artefato, mas **não substitui o sistema funcionando ao vivo**: o julgamento inclui live demo e trial by fire, e um vídeo polido de algo que não roda ao vivo não pontua.

Fontes: [Challenges — deliverables](https://nextwave-hackathon-2026.vercel.app/challenges), [Challenge 01 — deliverables](https://nextwave-hackathon-2026.vercel.app/challenges/file-01) e [Evaluation Guidelines — how judging runs / what doesn't score](https://nextwave-hackathon-2026.vercel.app/judging).

### Como a submissão ocorre

- O acesso à área da equipe é feito com um código entregue no check-in.
- A interface oficial servida pelo portal identifica o **Payload** como a submissão oficial e avisa que tudo fica bloqueado no code freeze.
- Os campos expostos são: URL pública do repositório GitHub, URL dos slides, URL da demo (vídeo ou live) e upload do diagrama de arquitetura em PDF/PNG de até 25 MB.
- O **Flight Log** registra o decision log durante o evento e pode ser exportado em Markdown para o repositório. Cada entrada contém: decisão, opções consideradas, escolha feita e justificativa.
- O fluxo autenticado não foi executado neste levantamento. Assim, regras de validação, possibilidade de substituir arquivos e detalhes operacionais finais devem ser confirmados no Mission Control da equipe.

Fontes: [Crew Access](https://nextwave-hackathon-2026.vercel.app/login), interface Mission Control presente no HTML oficial servido pelo [Participant HQ](https://nextwave-hackathon-2026.vercel.app/) e [Timeline](https://nextwave-hackathon-2026.vercel.app/schedule).

## Challenge 01 — The Buyer Who Isn't Human

### Objetivo obrigatório

Construir o circuito completo de uma compra segura feita por um agente em nome de uma pessoa ou empresa:

1. **Criação do mandato:** o humano autoriza o agente, definindo o que pode comprar, quanto pode gastar, até quando e com qual meio de pagamento, sem entregar os dados brutos do cartão.
2. **Verificação pelo merchant:** antes de aceitar, o merchant confirma que o agente é legítimo, o mandato é válido e a compra respeita os limites.
3. **Compra ponta a ponta:** o agente descobre a opção, decide e paga; o humano recebe o registro do que foi comprado e do mandato usado.
4. **Casos difíceis tratados explicitamente:** compra fora do mandato, mandato expirado, mandato revogado ao vivo, agente impostor e disputa posterior.
5. **Auditabilidade:** toda decisão de compra deixa uma trilha compreensível para humano, merchant e auditor.

O enunciado também apresenta erro/alucinação de compra como parte do problema que a solução deve responder, embora não exija uma cena separada para isso na lista de resultados esperados.

Fonte: [Challenge 01 — problem e objective](https://nextwave-hackathon-2026.vercel.app/challenges/file-01).

### O que a demo precisa mostrar

- Um humano criando um mandato e o agente concluindo uma compra ponta a ponta dentro dele. A compra pode ser simulada.
- Uma tentativa fora do mandato — por excesso de valor, categoria proibida ou expiração — sendo rejeitada ou escalada para aprovação humana, **nunca aprovada silenciosamente**.
- Revogação ao vivo: após revogar o mandato, a tentativa seguinte falha.
- As visões das três partes: histórico do humano, verificação do merchant e trilha completa do auditor.
- O trial by fire sendo aprovado.

Fonte: [Challenge 01 — expected results](https://nextwave-hackathon-2026.vercel.app/challenges/file-01).

### Trial by fire específico

Os jurados podem operar o sistema, revogar o mandato e observar uma nova tentativa de compra, ou mudar um limite e verificar a reação. A resposta correta deve acontecer sem intervenção do time.

Consequência prática: revogação, alteração de limites e validação de compra precisam ser comportamentos reais do produto, não estados preparados apenas para a apresentação.

Fonte: [Challenge 01 — trial by fire](https://nextwave-hackathon-2026.vercel.app/challenges/file-01). A segunda frase é uma implicação de implementação, não uma exigência textual adicional.

### Opcionais e bônus

O enunciado diz que a solução **pode incluir**, sem se limitar a: aprovação humana para compras fora do mandato, mandatos por categoria ou recorrência e identidade do agente separada da identidade humana. São sugestões, não requisitos autônomos.

Há pontos extras explícitos para:

- fluxo completo de disputa, no qual o humano nega a compra e a trilha resolve quem tem razão;
- mandatos com condições ricas, como “se cair abaixo de US$ 150” ou “até três vezes por mês”, avaliadas corretamente;
- defesa contra agente adversarial tentando contornar o mandato por caminhos criativos.

Fonte: [Challenge 01 — objective e bonus points](https://nextwave-hackathon-2026.vercel.app/challenges/file-01).

### Minimal fictional case: somente exemplo

O caso de Marta, VuelaYa, passagem para Córdoba e limite de US$ 150 é **ilustrativo, não prescritivo**. A própria página permite inventar catálogo, preços, mandatos, protocolos e meios de pagamento. O que precisa ser preservado são os comportamentos obrigatórios descritos acima, não o domínio de viagens.

Fonte: [Challenge 01 — minimal fictional case](https://nextwave-hackathon-2026.vercel.app/challenges/file-01).

## Avaliação

### Princípios

1. **Profundidade acima de dificuldade:** escolher o desafio mais difícil não gera pontos por si só; escopo modesto resolvido profundamente vence ambição superficial.
2. **Funcionando acima de prometido:** os jurados avaliam o que roda ao vivo, não o que os slides prometem.
3. **Julgamento acima de espetáculo:** a defesa técnica pesa tanto quanto a demo; uma solução simples bem defendida pode superar uma demo espetacular que o time não consegue explicar.

Fonte: [Evaluation Guidelines — three principles](https://nextwave-hackathon-2026.vercel.app/judging).

### Critérios e pesos

O site **não publica pesos numéricos**. Os cinco critérios aparecem “aproximadamente em ordem de peso”, e nenhum decide sozinho:

1. **Funciona?** Execução ponta a ponta e reação correta ao trial by fire.
2. **Profundidade e julgamento:** arquitetura sólida, decisões explicáveis, alternativas rejeitadas e trade-offs reais no decision log.
3. **Resolve o problema real:** atende ao objetivo escrito e aos casos difíceis, em vez de ser um produto genérico próximo do tema.
4. **Originalidade:** apresenta abordagem, insight ou mecanismo não óbvio.
5. **Experiência e clareza:** utilidade para o humano, pitch claro, demo legível e repositório compreensível por quem não esteve presente.

Fonte: [Evaluation Guidelines — what the jury looks at](https://nextwave-hackathon-2026.vercel.app/judging).

### Dinâmica do julgamento

- Ordem por equipe: pitch curto → live demo → trial by fire → perguntas técnicas.
- A página de avaliação informa **10 minutos por equipe**.
- Os campeões de cada cidade fazem uma final de **15 minutos**: 10 de apresentação e 5 de perguntas.
- Jurados de Yuno e Nauta veem todos os projetos do painel, ranqueiam independentemente e depois deliberam em conjunto.

**Inconsistência oficial a confirmar:** a Timeline exibe “7 minutes per team”, enquanto Evaluation Guidelines informa “10 minutes per team”. Até a organização esclarecer, o planejamento seguro é preparar um roteiro principal de 7 minutos e material técnico para os 3 minutos restantes/perguntas.

Fontes: [Evaluation Guidelines — how judging runs](https://nextwave-hackathon-2026.vercel.app/judging) e [Timeline](https://nextwave-hackathon-2026.vercel.app/schedule).

### O que não pontua

- Quantidade de funcionalidades, slides, integrações ou linhas de código.
- Buzzwords ou citar frameworks sem justificar a decisão.
- Vídeo polido de algo que não funciona ao vivo.
- Construir mecanicamente “para a rubrica” e terminar superficial nos cinco critérios.

Fonte: [Evaluation Guidelines — what doesn't score](https://nextwave-hackathon-2026.vercel.app/judging).

## Cronograma oficial

Todos os horários são locais. São Paulo e Buenos Aires compartilham os mesmos horários publicados.

| Marco | Relativo | São Paulo / Buenos Aires | Bogotá | Cidade do México |
|---|---:|---:|---:|---:|
| Check-in / abertura das portas — sáb. 29/08 | T−01:30 | 11:00 | 09:00 | 08:00 |
| Abertura OpenAI | T−01:00 | 11:30 | 09:30 | 08:30 |
| Anúncio dos desafios | T−00:30 | 12:00 | 10:00 | 09:00 |
| Início do desenvolvimento | T-ZERO | 12:30 | 10:30 | 09:30 |
| Code freeze / submissões bloqueadas — dom. 30/08 | T+24:00 | 12:30 | 10:30 | 09:30 |
| Pitches | T+24:30 | 13:00–15:00 | 11:00–13:00 | 10:00–12:00 |
| Campeões por cidade | T+27:00 | 15:30 | 13:30 | 12:30 |
| Vencedores globais | T+29:00 | 17:30 | 15:30 | 14:30 |

Fonte: [Timeline](https://nextwave-hackathon-2026.vercel.app/schedule) e [Participant HQ](https://nextwave-hackathon-2026.vercel.app/).

## Pontos ainda não publicados ou que exigem confirmação

- Pesos numéricos de avaliação: não publicados.
- Limite de slides e template de apresentação: não publicados.
- Estrutura obrigatória do README: não publicada além da exigência de sua existência.
- Nome/local obrigatório do decision log no repositório: não publicado; o portal apenas indica exportação em Markdown para o repo.
- Validações e detalhes operacionais do formulário autenticado: não testados sem o código da equipe.
- Duração da primeira apresentação: conflito entre 7 minutos na Timeline e 10 minutos nas Evaluation Guidelines.

Essas lacunas não devem ser preenchidas por suposição; precisam ser verificadas com a organização ou dentro do Mission Control da equipe.
