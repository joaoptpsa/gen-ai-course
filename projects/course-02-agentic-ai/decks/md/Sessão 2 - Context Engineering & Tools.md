<!-- page 1 -->

# Context Engineering, Tools e Skills

CURSO 2 / SESSÃO 2

Selecionar evidência e controlar os efeitos das ações

Agentic AI: Da Arquitetura à Implementação
Luís Noronha

<!-- page 2 -->

ENQUADRAMENTO

## O agente recebe contexto a mais e repete ações

### Recebe contexto a mais

O agente que os alunos recebem no início do exercício (o *starter*) envia mais de 100 000 tokens logo no primeiro pedido.

Inclui todos os alertas, cerca de 5 000 linhas de log e todos os runbooks.

A causa do incidente está, muitas vezes, numa única linha.

### Repete ações com efeitos

Se o mesmo reinício for pedido duas vezes, a instância é reiniciada duas vezes.

Se o reinício for feito, mas a resposta se perder, o agente volta a pedi-lo.

Nos dois casos, há dois reinícios onde bastava um.

> Num incidente real, qual destes dois problemas tem consequências mais graves?

<!-- page 3 -->

ENQUADRAMENTO

## Onde as equipas falham hoje

| | |
| --- | --- |
| **Contexto longo** | Assume-se que o modelo usa bem todo o contexto. Na prática, o desempenho cai à medida que o contexto cresce. |
| **Tools que devolvem tudo** | O resultado de uma tool entra no contexto. Devolver todos os logs produz um prompt enorme. |
| **Catálogos que crescem** | Cada tool ligada entra no contexto, mesmo sem ser usada. 58 tools de 5 servidores MCP ocupam cerca de 55 mil tokens. |
| **Repetir sem verificar** | Quando uma ação não responde a tempo, assume-se que falhou e repete-se. Se já tinha sido feita, fica feita duas vezes. |

Fonte: Anthropic, "Introducing advanced tool use" (2025).

<!-- page 4 -->

ENQUADRAMENTO

## Objetivos da sessão

| | |
| --- | --- |
| **Selecionar evidência** | Decidir o que entra sempre no contexto, o que só entra quando é preciso e o que nunca entra. Tudo dentro de 40 mil tokens para a execução inteira. |
| **Desenhar tools que resumem** | Transformar milhares de linhas em poucos templates. Incluir só o runbook que se aplica. |
| **Tornar ações seguras** | Garantir que repetir uma ação não a executa duas vezes, e que só se age se a razão para agir ainda existe. |

Cada capacidade é testada no simulador com checks PASS/FAIL.

<!-- page 5 -->

CONTEXT ROT

## Mais contexto, pior uso da evidência

| | |
| --- | --- |
| **Tamanho** | Em 18 modelos, o desempenho cai quando o contexto cresce, mesmo em tarefas simples. |
| **Distratores** | Um texto parecido com a resposta, mas errado, já baixa o desempenho. Com quatro, baixa mais. |
| **Foco** | Em perguntas sobre conversas longas, dar só os cerca de 300 tokens relevantes dá melhores resultados do que dar cerca de 113 mil tokens. Em todos os modelos. |
| **Sem palavras em comum** | Quando a pista não usa as palavras da pergunta, 11 de 13 modelos perdem mais de metade do desempenho com 32 mil tokens de contexto. |

Fontes: Chroma, "Context Rot" (2025); Modarressi et al., "NoLiMa", ICML 2025. Em 2023, Liu et al. viram pior desempenho com a informação a meio do contexto (GPT-3.5-Turbo); nos modelos de 2025, a Chroma não encontrou esse efeito.

O alerta fala de HTTP 503 no gateway. A linha da causa vai conter essas palavras?

<!-- page 6 -->

CUSTO E CACHING

## Cada pedido ao modelo volta a enviar o contexto todo

> diagram: gráfico de barras empilhadas por pedido
> componentes: barras (pedido 1 a 4), linha tracejada de limite, legenda

- pedido 1
  - 100 mil
- pedido 2
  - 100 mil
  - conversa até esse pedido (sem valor indicado)
- pedido 3
  - 100 mil
  - conversa até esse pedido (sem valor indicado)
- pedido 4
  - 100 mil
  - conversa até esse pedido (sem valor indicado)
- limite do exercício para a execução inteira: 40 mil
- legenda
  - instruções, tools e primeira mensagem
  - conversa até esse pedido

**Porque cresce:** o modelo não guarda nada entre pedidos. Em cada passo, o agente volta a enviar as instruções, as tools e toda a conversa até ali.

**No exercício:** o agente que os alunos recebem no início (o *starter*) envia mais de 100 mil tokens logo no primeiro pedido. Com 8 pedidos, são pelo menos 800 mil.

**Prompt caching:** se o início do pedido for igual ao do pedido anterior, o fornecedor reaproveita esse trabalho. Fica mais barato e mais rápido, mas o modelo continua a ler tudo.

**Por isso:** pôr no início o que nunca muda (tools e instruções) e no fim o que muda (a conversa).

Fontes: README do exercício; documentação de prompt caching da Anthropic e da OpenAI. Os 8 pedidos são uma conta de exemplo, não uma medição.

<!-- page 7 -->

ESTRATÉGIAS DE CONTEXTO

## No início, o mínimo. O resto, quando for preciso

### Sempre no contexto

Entra em todos os pedidos. Por exemplo, o Claude Code inclui o `CLAUDE.md` no início.

Bom para o que é sempre preciso e pequeno.

### Só quando é preciso

Guardar só referências: caminhos de ficheiros, consultas, identificadores. Uma tool vai buscar o conteúdo quando o agente precisa dele.

É mais lento e exige tools capazes de encontrar a informação.

Política em três linhas: sempre no contexto, só quando é preciso, nunca. O que se omite tem de poder ser recuperado.

<!-- page 8 -->

RESUMO E COMPACTAÇÃO

## Um resumo pode apagar a exceção

### Fonte

“Falhas recorrentes após o patch. A instância secundária está em manutenção.”

### Resumo

“Falhas recorrentes após o patch.”

**Mecanismo:** um resumo guarda o que se repete. A exceção aparece uma vez, por isso é a primeira a desaparecer.

**Evidência:** a Anthropic avisa que resumir a conversa de forma agressiva (compactação) perde detalhes críticos. Recomenda dar prioridade a não perder informação.

**Mais seguro:** se for preciso reduzir, apagar primeiro os resultados antigos de tools, que já foram usados. E guardar sempre a referência à fonte.

Fonte: Anthropic, “Effective context engineering for AI agents” (2025). O exemplo é ilustrativo.

> Que decisão ficou mais arriscada depois deste resumo?

<!-- page 9 -->

INTERFACE AGENTE–COMPUTADOR

## O resultado de uma tool é contexto

| | |
| --- | --- |
| **Respostas curtas** | No exemplo da Anthropic, a resposta concisa de uma tool usou 72 tokens; a detalhada, 206. |
| **Cortar com aviso** | Limitar resultados grandes e dizer ao modelo que foram cortados. O Claude Code limita cada resposta de uma tool a 25 mil tokens. |
| **Erros úteis** | Dizer ao modelo como corrigir o pedido, não só o código do erro. |
| **Pesquisar, não ler tudo** | Em vez de `read_logs` (devolve tudo), `search_logs` (devolve só as linhas relevantes). |

O agente inicial do exercício faz o contrário: `read_logs` devolve até 100 000 linhas.

Fonte: Anthropic, “Writing effective tools for agents” (2025). Em 2024, o SWE-agent já mostrava que mudar só a interface muda o resultado (GPT-4 Turbo).

<!-- page 10 -->

CATÁLOGOS DE TOOLS

## Mais tools, pior escolha

| | |
| --- | --- |
| **Custo fixo** | Cada tool ligada entra no contexto, mesmo sem ser usada. 58 tools ocupam cerca de 55 mil tokens. E tools parecidas confundem-se. |
| **Pré-seleção (RAG-MCP)** | Antes de chamar o modelo, uma pesquisa escolhe as tools mais parecidas com a tarefa. O modelo só vê essas. A tool certa passou a ser escolhida em 43,1 % dos casos, contra 13,6 % com o catálogo inteiro. |
| **Pesquisa de tools** | O modelo começa sem as definições. Quando precisa de uma tool, pesquisa-a no catálogo e só essa entra no contexto. Nos testes da Anthropic, a escolha certa subiu de 49 % para 74 % (Opus 4). |
| **Namespacing** | Um prefixo por serviço distingue tools parecidas: `orders_search`, `members_search`. |

Fontes: Anthropic, "Introducing advanced tool use" (2025); Gan e Sun, "RAG-MCP" (2025).

<!-- page 11 -->

SKILLS E PROCEDIMENTOS

## O procedimento só entra no contexto quando se aplica

| | |
| --- | --- |
| **1 · Metadados** | Sempre no contexto: nome, descrição curta e a que versões se aplica ( `applies_to` ). |
| **2 · Instruções** | Os passos do procedimento. Só entram quando os metadados correspondem à tarefa. |
| **3 · Anexos** | Ficheiros e scripts de apoio. Só entram se os passos os pedirem. |

**No Meridian:** dois runbooks do gateway. O v1 (2.3.x) reinicia o serviço todo. O v2 (2.4.x) reinicia uma instância.

**Em produção:** a versão 2.4.0. Só o v2 se aplica.

**Consequência:** o runbook errado no contexto é pior do que nenhum. É uma instrução plausível e errada.

Uma tool executa uma ação. Uma skill descreve como e quando a fazer. O MCP liga tools de outros sistemas, mas não escolhe quais usar.

Fontes: Anthropic, "Equipping agents for the real world with Agent Skills" (2025); README do exercício.

<!-- page 12 -->

RESUMIR LOGS

## Agrupar as linhas por forma e mostrar primeiro as raras

Antes: milhares de linhas, quase todas com a mesma forma.

```text
INFO  order accepted id=O481920 member=NORDBANK side=buy
INFO  order accepted id=O519034 member=ATLAS-SEC side=sell
WARN  feature flag fast_path enabled for 25% of members
```

Depois: as partes que variam passam a `<*>`. Agrupa-se, conta-se, e as raras vão para o topo.

```text
    1×  WARN  feature flag fast_path enabled for <*>% of members
   37×  WARN  retry upstream=<*> attempt=<*>
4 812×  INFO  order accepted id=<*> member=<*> side=<*>
```

O modelo lê poucas dezenas de templates. Cada template raro leva uma linha original e a referência.

Ideia do Drain (He et al., ICWS 2017), simplificada. Exemplo ilustrativo, não é output do simulador.

<!-- page 13 -->

CASO REAL A

## Um agente de email, fevereiro de 2026

> Summer Yue, da Meta, pede ao seu agente OpenClaw: “Sugere o que arquivar ou apagar. Não ajas até eu dizer.”
>
> Numa caixa de teste pequena, funciona.
>
> Na caixa real, muito maior, o contexto é compactado. A instrução desaparece.
>
> **O agente começa a apagar emails. Os “stop” enviados do telemóvel não o param.**

Fonte: relato público de Summer Yue (fevereiro de 2026), resumido por Simon Willison.

> Como resolverias isto? Onde devia estar a regra “não ajas até eu dizer”?

<!-- page 14 -->

ENCONTRAR A AGULHA SEM LER O PALHEIRO

## Exercício 1

| | |
| --- | --- |
| **A · Política** | Decidir o que entra sempre no primeiro pedido, o que só entra quando é preciso e o que nunca entra. Máximo de 40 mil tokens para a execução inteira. |
| **B · Resumo de logos** | Agrupar as linhas em templates e pôr primeiro os raros. Cada template leva uma linha de exemplo e a sua referência no log. |
| **C · Runbook** | Incluir só o runbook que se aplica à versão em produção. |

A pista pode ser uma linha rara, noutro componente, entre milhares.

<!-- page 15 -->

VERIFICAR AS CONSEQUÊNCIAS

## A ação teve efeito?

Depois de chamar uma tool, o agente tem de confirmar o que mudou no sistema.

| O QUE SE SABE | O QUE O AGENTE VERIFICA |
| --- | --- |
| A execução foi confirmada. | Que efeito teve no alvo? Houve consequências indesejadas? |
| A ação foi recusada antes de executar. | Porque não foi aplicada? Ainda faz sentido agir? |
| Não chegou confirmação do resultado. | Consultar o registo da execução e o estado do alvo antes de decidir se repete. |

Uma instância reiniciada pode continuar com o mesmo problema. Confirmar a execução e verificar a recuperação são passos diferentes.

<!-- page 16 -->

PRÉ-CONDIÇÕES E DRY-RUN

## A razão para agir ainda existe?

### Compare-and-set

Entre o diagnóstico e a ação, o mundo muda.

Ler o estado no momento de agir. Agir só se ainda for o que justificou a ação.

No exercício: reiniciar só se a memória estiver acima de 90 % ou a instância parada. Senão, recusar e dizer porquê.

### Dry-run

Para ações de grande alcance, responder primeiro com o que se faria.

Quantas instâncias, que impacto, o que deixa de funcionar.

No exercício: `restart_service` sem confirmação devolve o âmbito. Reiniciar o serviço corta todas as sessões dos membros.

A instrução orienta o modelo. A verificação no código impede o efeito.

<!-- page 17 -->

CASO REAL B

## Replit, julho de 2025

> Jason Lemkin, da SaaStr, testa o agente de código da Replit durante 12 dias.
>
> Declara um “code freeze” e pede que nada mude sem a sua permissão.
>
> O agente apaga a base de dados de produção: registos de 1 206 executivos e 1 196 empresas.
>
> **Depois admite: “You told me to always ask permission. And I ignored all of it.”**

Fontes: The Register (22-07-2025); AI Incident Database, relatório 5593.

> Como resolverias isto? O que tinha de ser verdade no sistema para isto não ser possível?

<!-- page 18 -->

AÇÕES SEGURAS DE REPETIR

## Exercício 2

| | |
| --- | --- |
| **Confirmar o efeito** | Verificar se a ação já aconteceu e o que mudou no sistema, incluindo quando não chega resposta. |
| **Pré-condição** | Reiniciar uma instância só se a razão para isso ainda se verifica. |
| **Dry-run** | Sem confirmação explícita, o reinício do serviço inteiro só devolve o âmbito e o impacto. |

É o problema da Replit, agora no simulador: o efeito tem de ser seguro mesmo quando o modelo erra.

<!-- page 19 -->

PARA LEVAR

## Três ideias

| | |
| --- | --- |
| **Mais contexto não é melhor contexto** | Mais contexto e mais ruído pioram o uso da evidência. Selecionar o que entra, e manter uma forma de voltar à fonte. |
| **A tool decide o que o modelo vê** | Mudar só a interface muda o resultado. Devolver templates e o runbook certo, não dados em bruto. |
| **Uma ação exige confirmar os efeitos** | Verificar o que mudou no sistema antes de repetir ou dar a tarefa como concluída. |
