---
marp: true
lang: pt-PT
title: Equipa de incidentes que se melhora a si própria
paginate: true
style: |
  section { font-size: 26px; padding: 56px 64px; }
  h1 { font-size: 40px; margin-bottom: 0.3em; }
  .kicker { font-size: 16px; letter-spacing: 0.12em; color: #777; text-transform: uppercase; }
  img[alt~="diagram"] { display: block; margin: 0 auto; max-height: 360px; }
  .small { font-size: 20px; color: #555; }
---

<div class="kicker">Curso 2 · Projeto · Meridian Exchange</div>

# Uma equipa de incidentes que aprende com os próprios erros

- **Utilizador:** o engenheiro de serviço (on-call) de uma bolsa fictícia, a Meridian Exchange.
- **Problema:** alertas, tickets e reclamações descrevem o mesmo incidente por palavras diferentes; mitigar um componente crítico exige aprovação; um erro pára a negociação.
- **Objetivo:** investigar, mitigar só com aprovação e **confirmar a recuperação com evidência**.
- **Aposta do projeto:** a equipa melhora entre execuções, medida sempre nos mesmos casos.

<!--
~30 s. Quem é o utilizador e porque é difícil: várias fontes, ações perigosas, aprovação obrigatória.
A aposta: não chega resolver um incidente, a equipa tem de melhorar de forma medida.
-->

---

<div class="kicker">Arquitetura e fluxo · equipa da sessão 7</div>

# Orquestrador, três especialistas e um revisor

![diagram](diagrams/flow.png)

<div class="small">

Fixo em código, nunca alterável pela equipa: permissões, contratos de handoff (Pydantic) e o acesso do revisor ao estado real. A fazer: aprovação por papel (o simulador já a exige).

</div>

<!--
~50 s. Rede e base de dados só leem. A remediação é a única que age e cada ação passa por aprovação.
O revisor não confia no relatório: lê o estado real e, se o incidente não acabou, devolve-o à remediação uma vez. Os handoffs são tipados e validados em código.
-->

---

<div class="kicker">Ideia central · desenho, por construir</div>

# Três formas de melhorar, um único juiz

![diagram](diagrams/loops.png)

<div class="small">

O ciclo nunca toca no juiz: checks, avaliador e revisor ficam fixos. Teste reservado até ao fim.

</div>

<!--
~60 s. O crítico lê os traces OpenTelemetry e culpa um agente ou um handoff concreto.
Só muda um agente de cada vez. Os checks, o avaliador e o revisor ficam fora do alcance do ciclo:
se o ciclo pudesse mexer no juiz, aprendia a passar sem resolver.
-->

---

<div class="kicker">Avaliação e estado</div>

# 60 casos, julgados pelo estado do simulador

- **31 casos das aulas + 29 adaptados de postmortems públicos** (CrowdStrike, Cloudflare, AWS S3, CME…).
- Os checks verificam **efeitos, aprovações e recuperação sustentada**, não só o texto do relatório.
- **Feito:** simulador, workbench (`run`, `compare`, `requirements`), casos e desenho da equipa.
- **Até 30 nov:** equipa no workbench → traces e crítico → ciclo de versões → lições → casos novos.

<div class="small">

Limites: os checks dos 29 casos novos são provisórios até haver soluções do formador; o conjunto de teste é pequeno, por isso cada comparação corre com repetições e mostra a variação.

</div>

<!--
~40 s. Ser honesto: a infraestrutura de avaliação está pronta, a equipa ainda não corre no workbench.
Pergunta à turma: que falhas de coordenação deviam entrar como casos?
-->
