<!-- page 1 -->

*CURSO 2 / SESSÃO 1*

# Agent Harnesses e PydanticAI

## Investigar, corrigir e confirmar a recuperação com evidência

Agentic AI: Da Arquitetura à Implementação
Luís Noronha

<!-- page 2 -->

*DO CURSO 1 AO CURSO 2*

# O mesmo modelo, outro comportamento

## O que já construíram

Um loop: pedido → tool → resultado → resposta.

Funciona bem quando o pedido é simples e curto.

## O que muda agora

O agente investiga sistemas e decide quando o trabalho acabou.

Quando falha, a causa está quase sempre à volta do modelo, não no modelo.

> Se o agente falha, o que mudarias primeiro: o modelo ou o que o rodeia?

<!-- page 3 -->

*CONCEITO*

# O harness à volta do modelo

## Código e configuração que organizam o trabalho do agente

|   |   |
|---|---|
| **Entrada** | Instruções, pedido e informação disponível. |
| **Execução** | Tools, resultados, estado e limites do processamento. |
| **Conclusão** | Output esperado e verificações para aceitar o trabalho. |

<!-- page 4 -->

*RESPONSABILIDADES*

# Modelo, harness e runtime

| CAMADA | NESTE INCIDENTE | RESPONSABILIDADE |
|---|---|---|
| Modelo | Propõe consultar métricas ou um runbook | Escolher o próximo pedido a partir do contexto |
| Harness | Entrega resultados e organiza a continuação | Preparar contexto e tratar os resultados |
| Runtime | Executa a função e aplica limites | Controlar o que pode realmente acontecer |

Uma instrução orienta o modelo. O código aplica uma restrição.

<!-- page 5 -->

*DECISÕES DE ARQUITETURA*

# O que o harness controla

| DECISÃO | O QUE A APLICAÇÃO CONFIGURA |
|---|---|
| Contexto e estado | Que instruções, dados e resultados chegam ao modelo em cada passo |
| Ações disponíveis | Que tools expõe e como o código executa cada pedido |
| Limites e feedback | Quando interrompe a execução e como devolve erros para correção |
| Aceitação do resultado | Que evidência verifica antes de aceitar a conclusão |

O modelo propõe ações e uma conclusão. O harness controla a execução e a aceitação do resultado.

<!-- page 6 -->

*ECOSSISTEMA*

# Ferramentas para construir agentes

| FRAMEWORK | O QUE OFERECE | ONDE AJUDA |
|---|---|---|
| PydanticAI | Agentes Python com tools, dependencies e output tipado | Integrar serviços e validar contratos de dados |
| LangChain | Agentes configuráveis e integrações com modelos e tools | Compor capacidades e adaptar o loop |
| OpenAI Agents SDK | Loop de agente com tools, handoffs e tracing | Delegar entre agentes e inspecionar a execução |
| Strands Agents | Loop com tools e modelos configuráveis | Usar Bedrock ou outros fornecedores |

Nesta sessão, PydanticAI torna explícitas as dependências e a validação. A aplicação define o sucesso.

<!-- page 7 -->

*FRAMEWORK*

# O papel do PydanticAI

## A framework coordena

- Chamadas ao modelo e às tools registadas.
- Validação de argumentos e do output configurado.

## A aplicação define

- O significado das tools e os clientes que utilizam.
- Permissões e critérios de recuperação.

Pydantic valida dados. PydanticAI acrescenta coordenação de agentes.

<!-- page 8 -->

*CONFIGURAÇÃO*

# As peças de um Agent

```python
agent = Agent(
    model,
    deps_type=IncidentDeps,
    output_type=IncidentReport,
    instructions=incident_instructions,
)
```

Modelo, dependências, output e instruções têm funções diferentes.

<!-- page 9 -->

*DEPENDENCIES*

# O cliente Python fica fora do prompt

## Disponível ao código

```python
def read_alert(
    ctx: RunContext[IncidentDeps],
    alert_id: str,
) -> dict:
    tools = ctx.deps.tools
    return tools.read_alert(alert_id)
```

## Disponível ao modelo

Nome, descrição e argumentos da tool.

O resultado devolvido depois da chamada.

O cliente `ctx.deps.tools` fica no código Python.

<!-- page 10 -->

*CENÁRIO DO CURSO*

# Meridian Exchange

> diagram: Gateway de ordens → Motor de negociação; Dados de mercado → Motor de negociação
> Motor de negociação → Liquidação → Base de dados de referência
> Gateway de ordens → Base de dados de referência

- Gateway de ordens
- Dados de mercado
- Motor de negociação
- Liquidação
- Base de dados de referência

Bolsa fictícia num simulador local. O agente investiga, executa uma correção e verifica a recuperação.

<!-- page 11 -->

*INVESTIGAR*

# Exercício 1

| | |
|---|---|
| **Métricas** | Criar uma tool para observar o estado por instância. |
| **Runbooks** | Criar tools para descobrir e ler os procedimentos relevantes. |
| **Testar** | Verificar os casos e explicar o que mudou no agente. |

Objetivo: dar capacidade de investigação a um agente que só lê alertas.

<!-- page 12 -->

*BASE EXECUTÁVEL*

# O ponto de partida no repositório

| | |
|---|---|
| `starter/harness.py` | Agent com instruções, relatório tipado e uma tool: `read_alert`. |
| `cases/` | Seis incidentes que o runner executa no simulador. |
| `checks/` | Critérios públicos que produzem PASS ou FAIL em cada caso. |

No exercício 1, investiga. No exercício 2, corrige e verifica.

<!-- page 13 -->

*CASO INICIAL*

# O agente não identifica a instância

INC-2041 / S01-GATEWAY-LATENCY

## O gateway de ordens está lento

O alerta indica o componente.
Precisamos de localizar a instância afetada.

## Configuração do starter

```text
Tool registada:
read_alert(alert_id)

Output: IncidentReport
status, diagnosis, evidence
```

> Que capacidade falta para localizar o problema?

<!-- page 14 -->

*VOTAÇÃO*

# Porque falta a instância no diagnóstico?

| | |
|---|---|
| **A** | O modelo precisa de mais capacidade. |
| **B** | As instruções precisam de mais detalhe. |
| **C** | Falta uma tool que permita observar as instâncias. |
| **D** | O agente esgotou o limite de execução. |

Votar, comparar com o trace e justificar com evidência.

<!-- page 15 -->

*DEBRIEF · TOOLS*

# A interface determina o que o agente descobre

|  |  |
|---|---|
| **Nome e descrição** | Que informação a tool expõe e quando a usar. |
| **Argumentos** | Componente, janela de leituras e detalhe por instância. |
| **Resultado** | Dados, referência de origem ou erro com indicação de nova tentativa. |

A tool fica disponível ao modelo depois de registada no Agent.

<!-- page 16 -->

*OUTPUT TIPADO*

# Um relatório válido precisa de evidência

```json
{
  "incident_id": "INC-2046",
  "status": "resolved",
  "diagnosis": "Alerta fechado.",
  "proposed_mitigation": null,
  "evidence": []
}
```

## Estrutura válida

Este objeto respeita o `IncidentReport` do starter.

## Conclusão por verificar

O schema aceita a forma. A aplicação ainda precisa de verificar a recuperação.

<!-- page 17 -->

*VERIFICAÇÃO EM CÓDIGO*

# Output validators verificam a conclusão

| | |
|---|---|
| **Relatório candidato** | `output_type` valida a estrutura dos dados. |
| **Verificação** | `output_validator` consulta dados e aplica as regras da aplicação. |
| **Feedback** | `ModelRetry` devolve o motivo da rejeição ao modelo. |
| **Nova tentativa** | O agente pode corrigir o relatório dentro do limite de tentativas. |

<!-- page 18 -->

*CORRIGIR E VERIFICAR*

# Exercício 2

| | |
|---|---|
| **Corrigir** | Dar ao agente a capacidade de reiniciar uma instância. |
| **Verificar** | Aceitar «resolved» apenas com recuperação confirmada nas métricas. |
| **Testar** | Distinguir recuperação, alertas antigos e falhas que continuam. |

Executar uma ação não prova que o problema ficou resolvido.

<!-- page 19 -->

*COMPARAÇÃO*

# Uma alteração com uma hipótese explícita

| ANTES DE COMPARAR | DECISÃO |
|---|---|
| Hipótese | Que comportamento deve mudar? |
| Alteração | Que componente do harness vai mudar? |
| Condições | Mesmo estado inicial, dados e limites |
| Evidência | Resultado e ações observadas |

<!-- page 20 -->

*PARA LEVAR*

# Três ideias desta sessão

| Harness | O comportamento do agente depende do que rodeia o modelo, não só do modelo. |
|---|---|
| Evidência | Um output válido no schema não prova que a tarefa foi feita. |
| Comparação | Uma alteração só conta com uma hipótese, as mesmas condições e um caso novo. |
