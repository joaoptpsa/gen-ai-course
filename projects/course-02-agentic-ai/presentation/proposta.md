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
  section.dense img[alt~="diagram"] { max-height: 280px; }
  section.dense .compact { font-size: 18px; line-height: 1.3; }
---

<div class="kicker">Ciclo de execução · Meridian Exchange</div>

# A execução normal: investigar, mitigar, verificar

![diagram](diagrams/flow.png)

<div class="compact">

- **Quando ativa:** chega um alerta, ticket ou reclamação; é a execução normal, em tempo real, desencadeada por cada incidente.
- **Permissões em código:** apenas a remediação atua, com aprovação por papel nas ações críticas.
- **Handoffs estruturados:** outputs validados entre agentes para preservar evidências e restrições.
- **Verificação real:** o revisor lê diretamente o simulador e reporta ao orquestrador, que aciona uma nova tentativa se a recuperação falhar.

</div>

<!--
~50 s. Este é o ciclo de execução normal: responde a um sinal de incidente, em tempo real, desencadeado por cada incidente. Explicar a separação de responsabilidades: o orquestrador coordena três especialistas. Rede e base de dados funcionam apenas em modo de leitura e devolvem diagnósticos estruturados. Apenas a remediação pode atuar sobre o simulador, mediante aprovação por papel (on-call ou incident-manager) nas ações críticas. Os handoffs entre agentes são validados em código para não perder evidências nem restrições. No final, o orquestrador pede ao revisor para confirmar o estado real do simulador e, se a recuperação falhar, aciona mais uma tentativa de remediação.
-->

---

<!-- _class: dense -->

<div class="kicker">Ciclo de melhoria · entre execuções</div>

# Um ciclo de melhoria, um juiz intocável

![diagram](diagrams/loops.png)

<div class="compact">

- **Quando ativa:** entre execuções, alimentado pelos traces OpenTelemetry de cada corrida; não intervém na execução normal em tempo real.
- **Salvaguarda:** checks, avaliador e revisor ficam fora do ciclo; a equipa não altera os critérios que a avaliam.

</div>

<div class="compact">

**Avaliação:** 60 casos (31 das aulas + 29 adaptados de postmortems públicos), em treino (38), validação (8) e teste reservado (14), sem misturar famílias de incidentes. Os checks validam efeitos, aprovações e recuperação sustentada no simulador, não só o texto do relatório. Todas as versões correm nos mesmos casos, com o mesmo estado inicial e memória congelada, em múltiplas repetições.

</div>

<!--
~85 s (total ~2m15s, com margem para perguntas). Este é o ciclo de melhoria: só ativa entre execuções, a partir dos traces de cada corrida, e nunca mexe na execução normal em tempo real do slide anterior. É um único ciclo, com três facetas alimentadas pelos mesmos traces. Um agente crítico analisa os traces e aponta o agente ou handoff responsável por cada falha. A faceta de versões altera um agente de cada vez e só promove a nova versão se o treino melhorar sem regressão na validação. A faceta de lições mantém uma memória por papel, atualizada após cada incidente e consultada antes de atuar. A faceta de novos casos parte de falhas reais, passa por revisão humana e entra só no treino. A salvaguarda é que checks, avaliador e revisor ficam fora do ciclo: a equipa melhora a resolução, nunca o critério de avaliação. Medimos isso com 60 casos, 31 das aulas e 29 de postmortems públicos, divididos por famílias em treino, validação e teste intacto até ao fim. Os checks leem o estado real do simulador e todas as versões correm nas mesmas condições, com repetições para controlar a variabilidade. Para abrir o Q&A: que falhas de coordenação entre agentes consideram mais relevantes incluir nos casos de avaliação?
-->
