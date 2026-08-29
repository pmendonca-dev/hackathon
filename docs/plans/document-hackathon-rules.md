# Plano: documentar as regras do hackathon

## Problema

As regras oficiais do NextWave Hackathon 2026 estão distribuídas entre páginas do portal do evento. O repositório precisa de uma referência curta, verificável e operacional para orientar produto, implementação, demonstração e submissão.

## Abordagem

1. Consultar apenas páginas oficiais do Participant HQ.
2. Separar fatos explícitos de interpretações e recomendações do time.
3. Consolidar formato da entrega, requisitos do desafio 01, critérios de avaliação, cronograma e checklist de submissão.
4. Citar a página oficial correspondente em cada seção.
5. Manter o documento principal curto e adequado para consulta durante o hackathon.

## Alternativas descartadas

- Copiar integralmente as páginas oficiais: ficaria extenso, duplicaria conteúdo e dificultaria identificar o que é obrigatório.
- Tratar o caso ficcional mínimo como especificação: o próprio desafio permite inventar domínio, catálogo, preços, protocolos e meios de pagamento.
- Documentar somente os cinco artefatos finais: isso omitiria os comportamentos que a demo e o teste ao vivo precisam comprovar.

## Escopo

- Regras públicas do evento e do desafio 01.
- Entregáveis, demonstração, critérios de avaliação, cronograma e checklist.
- Atualização do README para apontar para a documentação.

Fora de escopo: credenciais de equipe, conteúdo privado do Mission Control e decisões de arquitetura da solução ainda não tomadas.

## Verificação

- Conferir cada afirmação contra a página oficial citada.
- Validar links e estrutura Markdown.
- Executar `scripts/verify.ps1` se existir; caso contrário, registrar a ausência do portão.
- Revisar `git diff`, criar commit, publicar a branch e abrir PR.
