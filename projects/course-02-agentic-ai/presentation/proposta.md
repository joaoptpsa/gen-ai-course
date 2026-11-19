---
marp: true
lang: pt-PT
title: Uma equipa de incidentes que aprende com os erros
paginate: true
style: |
  section { font-size: 26px; padding: 42px 56px; line-height: 1.4; }
  h1 { font-size: 38px; margin-top: 0.15em; margin-bottom: 0.4em; line-height: 1.2; }
  ul { margin-top: 0.3em; }
  li { margin-bottom: 0.45em; }
  .kicker { font-size: 16px; letter-spacing: 0.12em; color: #777; text-transform: uppercase; }
  img[alt~="diagram"] { display: block; margin: 0.2em auto 0.4em; max-height: 360px; }
  .compact { font-size: 20px; color: #444; line-height: 1.35; }
  .compact li { margin-bottom: 0.25em; }
---

<div class="kicker">Curso 2 · Projeto · Meridian Exchange</div>

# Uma equipa de incidentes que aprende com os erros

- **Utilizador:** engenheiro de prevenção (on-call) na Meridian Exchange.
- **Problema:** alertas, tickets e reclamações descrevem o mesmo incidente de formas diferentes; ações críticas exigem aprovação e um erro pode parar a negociação.
- **Objetivo:** investigar o incidente, mitigar apenas com autorização e confirmar a recuperação com evidência real.
- **Proposta:** uma equipa multiagente que melhora de forma mensurável entre execuções, sempre sobre os mesmos casos.

<!--
~25 s. Apresentar o utilizador e o contexto: um engenheiro de prevenção na Meridian Exchange que recebe sinais dispersos sob pressão e lida com ações de alto risco em que um erro pode parar a negociação. A nossa proposta é uma equipa multiagente que não se limita a resolver um incidente isolado, mas que melhora de forma mensurável entre execuções sobre os mesmos casos.
-->

---

<div class="kicker">Arquitetura e fluxo</div>

# Orquestrador, três especialistas e um revisor

![diagram](diagrams/flow.png)

<div class="compact">

- **Permissões em código:** apenas a remediação atua, com aprovação por papel nas ações críticas.
- **Handoffs estruturados:** outputs validados entre agentes para preservar evidências e restrições.
- **Verificação real:** o revisor lê diretamente o simulador e reporta ao orquestrador, que aciona uma nova tentativa se a recuperação falhar.

</div>

<!--
~45 s. Explicar a separação de responsabilidades: o orquestrador coordena três especialistas. Rede e base de dados funcionam apenas em modo de leitura e devolvem diagnósticos estruturados. Apenas a remediação pode atuar sobre o simulador, mediante aprovação por papel (on-call ou incident-manager) nas ações críticas. Os handoffs entre agentes são validados em código para não perder evidências nem restrições. No final, o orquestrador pede ao revisor para confirmar o estado real do simulador e, se a recuperação falhar, aciona mais uma tentativa de remediação.
-->

---

<div class="kicker">Proposta central</div>

# Três ciclos de melhoria, um juiz intocável

![diagram](diagrams/loops.png)

<div class="compact">

**Salvaguarda:** checks, avaliador e revisor ficam fora dos ciclos; a equipa não altera os critérios que a avaliam.

</div>

<!--
~50 s. A melhoria contínua assenta em três ciclos alimentados pelas execuções e pelos traces OpenTelemetry. Um agente crítico analisa os traces e aponta o agente ou handoff responsável por cada falha. Primeiro ciclo: versões, em que alteramos um agente de cada vez e só promovemos a nova versão se o treino melhorar sem regressão na validação. Segundo ciclo: lições, uma memória por papel atualizada após cada incidente e consultada antes de atuar. Terceiro ciclo: novos casos gerados a partir de falhas reais, sujeitos a revisão humana e adicionados apenas ao conjunto de treino. A salvaguarda central é que checks, avaliador e revisor ficam fora destes ciclos, garantindo que a equipa melhora a resolução e nunca o critério de avaliação.
-->

---

<div class="kicker">Avaliação</div>

# 60 casos, avaliados pelo estado do simulador

- **Conjunto de casos:** 31 casos das aulas e 29 adaptados de postmortems públicos (CrowdStrike, Cloudflare, AWS S3, CME…).
- **Separação rigorosa:** treino (38), validação (8) e teste reservado para a avaliação final (14), sem mistura de famílias de incidentes.
- **Critérios objetivos:** os checks validam efeitos, aprovações e recuperação sustentada no simulador, e não apenas o texto do relatório.
- **Comparação justa:** todas as versões correm sobre os mesmos casos, com o mesmo estado inicial e memória congelada, em múltiplas repetições.

<!--
~35 s (total ~2m35s, com margem para perguntas). Explicar como medimos o progresso de forma rigorosa: 60 casos que combinam os 31 cenários das aulas com 29 incidentes adaptados de postmortems públicos conhecidos. Dividimos os casos por famílias de incidentes entre treino, validação e um conjunto de teste mantido intacto para a avaliação final. Os checks verificam o estado real do simulador (efeitos, aprovações e recuperação sustentada) e todas as versões são comparadas nas mesmas condições, com múltiplas repetições para controlar a variabilidade. Para abrir o Q&A: que falhas de coordenação entre agentes consideram mais relevantes incluir nos casos de avaliação?
-->
