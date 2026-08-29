# Regras do NextWave Hackathon 2026

Referência operacional do time para o **desafio 01 — The Buyer Who Isn't Human**. Em caso de mudança ou conflito, prevalecem o [Participant HQ](https://nextwave-hackathon-2026.vercel.app/) e as orientações da organização.

## Resumo executivo

- Equipe de 4 pessoas, 24 horas de desenvolvimento e exatamente 1 dos 4 desafios.
- A escolha do desafio é final.
- Dados, fluxos, APIs, bancos, frameworks e protocolos podem ser inventados, desde que o time defenda as escolhas.
- O que vale é o sistema funcionando ao vivo, com profundidade e decisões justificadas.
- Os jurados alterarão entradas ou regras sem ensaio; o sistema deve reagir sem intervenção manual do time.
- Toda a submissão é bloqueada no **code freeze, T+24:00**.

Fontes: [desafios](https://nextwave-hackathon-2026.vercel.app/challenges), [cronograma](https://nextwave-hackathon-2026.vercel.app/schedule) e [avaliação](https://nextwave-hackathon-2026.vercel.app/judging).

## O que deve ser entregue

| Entregável | Formato oficial | Exigência prática |
| --- | --- | --- |
| Apresentação | URL dos slides | Deve sustentar problema, solução, decisões e demonstração. |
| Demo | URL de vídeo ou experiência ao vivo | Vídeo é aceito como artefato, mas não substitui o sistema executável durante a avaliação. |
| Código | URL HTTPS de repositório público no GitHub | Deve conter README legível por quem não participou do projeto. |
| Arquitetura | Upload em PDF ou PNG, até 25 MB | Deve permitir explicar componentes, confiança, fluxos e decisões relevantes. |
| Decision log | Flight Log do portal, exportável em `.md` para o repositório | Registrar decisão, alternativas, escolha e justificativa enquanto o trabalho acontece. |

Esses itens formam o **payload oficial** no Mission Control e ficam bloqueados no code freeze. Entregáveis ausentes são considerados pelos jurados.

Os campos e formatos acima aparecem na interface oficial servida pelo portal. O fluxo autenticado não foi executado; validações adicionais devem ser conferidas assim que o código da equipe estiver disponível.

Fontes: [Participant HQ](https://nextwave-hackathon-2026.vercel.app/), [desafio 01](https://nextwave-hackathon-2026.vercel.app/challenges/file-01) e [avaliação](https://nextwave-hackathon-2026.vercel.app/judging).

## Modelo da avaliação

A apresentação de cada equipe segue esta sequência:

1. Pitch curto.
2. Demo ao vivo.
3. **Trial by fire** com alteração não ensaiada feita pelos jurados.
4. Defesa técnica e perguntas.

O painel completo avalia cada projeto. Os jurados ranqueiam individualmente e depois deliberam em conjunto.

### Tempo

Há uma divergência nas páginas oficiais:

- o [cronograma](https://nextwave-hackathon-2026.vercel.app/schedule) informa **7 minutos por equipe** para pitches;
- a página de [avaliação](https://nextwave-hackathon-2026.vercel.app/judging) informa **10 minutos por equipe** para pitch, demo, trial by fire e perguntas.

Até confirmação da organização, a decisão operacional é preparar o conteúdo controlado pelo time para caber em **7 minutos** e reservar os 3 minutos restantes para intervenção dos jurados e perguntas.

Campeões de cada cidade fazem uma final de 15 minutos: 10 de apresentação e 5 de perguntas.

## Como o júri decide

Os cinco critérios aparecem aproximadamente nesta ordem de peso, sem pontuação numérica publicada:

1. **Funciona?** Fluxo ponta a ponta e resposta correta ao trial by fire.
2. **Profundidade e julgamento.** Arquitetura sólida, alternativas reais e trade-offs defensáveis.
3. **Resolve o problema real.** Atende ao objetivo e aos casos difíceis do desafio, não apenas a um produto adjacente.
4. **Originalidade.** Traz mecanismo, abordagem ou insight não óbvio.
5. **Experiência e clareza.** É utilizável, demonstrável e compreensível em pitch, demo e repositório.

Não pontuam por si só: quantidade de funcionalidades, slides, integrações ou linhas de código; buzzwords; vídeo polido de algo que não funciona ao vivo; ou cobertura superficial de cada item da rubrica.

Fonte: [Evaluation guidelines](https://nextwave-hackathon-2026.vercel.app/judging).

## Desafio 01: requisitos obrigatórios

Precisamos construir o circuito completo de uma compra segura feita por um agente em nome de uma pessoa ou empresa.

### O sistema deve permitir

- O humano criar um **mandato verificável** que defina o que pode ser comprado, limites, validade e meio de pagamento, sem expor o cartão bruto ao agente.
- O merchant verificar, antes de aceitar a compra, a legitimidade do agente, a validade do mandato e a aderência da compra aos limites.
- O agente descobrir, decidir e pagar de ponta a ponta; a integração de pagamento pode ser simulada.
- O humano receber o registro do que foi comprado e sob qual mandato.
- Humano, merchant e auditor consultarem uma trilha de auditoria legível.
- O sistema tratar explicitamente compra fora do mandato, mandato expirado, revogação em tempo real, agente impostor e disputa posterior.

### A demo deve comprovar

- Criação do mandato e compra ponta a ponta autorizada.
- Tentativa fora do mandato recusada ou escalada para aprovação humana, nunca aprovada silenciosamente.
- Revogação ao vivo: mandato revogado e tentativa seguinte rejeitada.
- Visão do humano, verificação do merchant e trilha completa do auditor.
- Reação correta ao trial by fire sem o time alterar o sistema manualmente.

Fonte: [desafio 01](https://nextwave-hackathon-2026.vercel.app/challenges/file-01).

## O que é livre, exemplo ou bônus

### Livre

- Domínio de negócio, catálogo, preços, dados, APIs, bancos, protocolos e meios de pagamento.
- Tecnologias e frameworks, desde que suas escolhas sejam explicáveis.
- Escalonar uma tentativa fora do mandato para aprovação humana em vez de apenas rejeitá-la.
- Mandatos por categoria ou recorrência e identidade do agente separada da identidade humana são extensões sugeridas, não obrigações autônomas.

### Apenas exemplo

O **Minimal fictional case** de Marta, VuelaYa e uma passagem para Córdoba ilustra o comportamento esperado. Ele não define o produto que devemos construir. Devemos preservar as invariantes — mandato, verificação, limites, revogação e auditoria — e podemos escolher outro domínio.

### Bônus

- Fluxo completo de disputa capaz de decidir, pela trilha auditável, quem tem razão.
- Mandatos com condições ricas, como preço-alvo ou frequência máxima mensal.
- Defesa contra agente adversarial tentando contornar o mandato por caminhos criativos.

> Interpretação conservadora: a disputa precisa estar ao menos modelada e explicada porque aparece no objetivo obrigatório; implementar seu fluxo completo é bônus.

## Cronograma

Todos os horários são locais a cada cidade; `T±` é relativo ao início da codificação.

| Marco | Relativo | São Paulo |
| --- | ---: | ---: |
| Check-in | T-01:30 | Sáb. 29/08, 11:00 |
| Abertura OpenAI | T-01:00 | 11:30 |
| Divulgação dos desafios | T-00:30 | 12:00 |
| Início da codificação | T-ZERO | 12:30 |
| Code freeze e bloqueio da submissão | T+24:00 | Dom. 30/08, 12:30 |
| Início dos pitches | T+24:30 | 13:00 |
| Campeões das cidades | T+27:00 | 15:30 |
| Vencedores globais | T+29:00 | 17:30 |

Fonte: [Timeline](https://nextwave-hackathon-2026.vercel.app/schedule).

## Checklist de pronto

Antes do code freeze:

- [ ] Repositório público e README revisado por alguém que não implementou a solução.
- [ ] URL dos slides cadastrada no Mission Control.
- [ ] URL da demo cadastrada e acessível sem credenciais pessoais do apresentador.
- [ ] Diagrama PDF/PNG abaixo de 25 MB enviado.
- [ ] Decision log atualizado e exportado em Markdown para o repositório.
- [ ] Fluxo autorizado ponta a ponta executado em ambiente limpo.
- [ ] Compra fora do mandato falha de modo seguro.
- [ ] Mudança de limite afeta imediatamente a próxima decisão.
- [ ] Revogação afeta imediatamente a próxima tentativa.
- [ ] Visões de humano, merchant e auditor estão demonstráveis.
- [ ] Time consegue explicar alternativas rejeitadas e trade-offs.
- [ ] Apresentação ensaiada para a janela conservadora de 7 minutos.
- [ ] Trial by fire ensaiado com entradas que o apresentador não conhece previamente.

## Questões a confirmar com a organização

- A divisão exata entre os 7 minutos indicados no cronograma e o slot de 10 minutos descrito na avaliação.
- Se haverá alguma exigência adicional no Mission Control visível apenas após autenticação da equipe.
