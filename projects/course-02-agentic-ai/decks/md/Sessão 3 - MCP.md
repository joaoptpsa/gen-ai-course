<!-- page 1 -->

# MCP: integração e governação

CURSO 2 / SESSÃO 3

## Correlacionar eventos e controlar o acesso a servidores externos

Agentic AI: Da Arquitetura à Implementação
Luís Noronha

<!-- page 2 -->

ANTES DA TEORIA

## 22 alertas, tickets e reclamações. Quantos incidentes?

### Analisar os registos e propor uma contagem

Justificar quais devem ficar juntos e quais devem ficar separados.

Folha de apoio:

```text
public/exercises/session-3-events.md
```

sem a solução.

Fonte:

```text
events/dev.yaml
```

do exercício.

<!-- page 3 -->

ENQUADRAMENTO

## O que vamos construir

| | |
| --- | --- |
| **Servidor incidents** | Agrupar eventos relacionados e explicar como usar as suas tools. |
| **Gatekeeper** | Controlar as tools disponíveis e as chamadas a servidores de outras equipas. |
| **Validação** | Testar as regras sem modelo e depois observar o agente nos casos fornecidos. |

<!-- page 4 -->

ARQUITETURA

## Quem faz o quê

> diagram: Aplicação do agente ⟷ HTTP ⟷ Backend FastMCP
> Componentes: aplicação do agente com Client MCP; backend FastMCP

- Aplicação do agente
  - Agente e regras da aplicação
  - Client MCP
- HTTP
- Backend FastMCP
  - Tools e lógica do serviço

### Na aplicação

Consulta o modelo, seleciona tools e verifica as chamadas.

### No backend

Disponibiliza tools, executa as funções e devolve resultados.

O client MCP faz parte da aplicação e trata da comunicação HTTP com o backend.

<!-- page 5 -->

IMPLEMENTAÇÃO EM PYTHON

## O que faz o FastMCP?

> diagram: fluxo de três componentes ligados por setas
> da esquerda para a direita

- Função Python
- `@server.tool`
- Tool exposta por MCP

| | |
| --- | --- |
| **FastMCP** | Gera o schema, valida os argumentos e trata da chamada e da resposta. |
| **O nosso código** | Implementa a operação e as regras sobre os efeitos que pode produzir. |

No exercício, `report_event` é a tool exposta; `correlate()` é uma função interna que ela chama.

<!-- page 6 -->

ESCOLHA DE INTEGRAÇÃO

## Quando compensa usar MCP?

| | TOOL DIRETA (FUNÇÃO) | SERVIDOR MCP |
| --- | --- | --- |
| **Acesso à tool** | Função registada diretamente no agente. | Tool descoberta e chamada por MCP. |
| **Quando compensa** | Uso interno de uma aplicação. | Várias aplicações ou equipas. |
| **Operação** | Menos peças para gerir. | Versões, acesso e disponibilidade do servidor. |

Em ambos os casos, o código pode chamar uma API/SDK, consultar uma base de dados ou executar lógica local.

<!-- page 7 -->

UMA CHAMADA COMPLETA

## Do catálogo à chamada e ao resultado

| | |
| --- | --- |
| **1 · Catálogo** | O backend anuncia `report_event` ; a aplicação disponibiliza a definição ao modelo. |
| **2 · Pedido** | O modelo propõe a chamada; a aplicação verifica-a e envia-a por HTTP através do client. |
| **3 · Execução** | O backend executa `report_event` , que chama `correlate()` e atualiza o incidente. |
| **4 · Resultado** | A aplicação recebe o incidente devolvido e apresenta o resultado ao modelo. |

O modelo usa o resultado para decidir o passo seguinte. Exemplo ilustrativo.

<!-- page 8 -->

INTERFACE PARA O MODELO

## O que o modelo recebe

Com tools diretas ou MCP, o modelo recebe uma definição da tool para decidir quando e como a usar.

| | |
| --- | --- |
| **Nome** | Identifica a operação que pode pedir. |
| **Descrição** | Explica quando usar a tool, o que faz e os seus limites. |
| **Schema** | Define os argumentos aceites e os seus tipos. |

Tool direta: a framework constrói a definição a partir da função registada. MCP: a aplicação obtém a definição do servidor e disponibiliza-a ao modelo.

<!-- page 9 -->

CORRELAÇÃO

## Quando juntar e quando separar alertas?

| | |
| --- | --- |
| **Tempo** | É a continuação de uma ocorrência ou um novo episódio? |
| **Texto e componente** | Que serviço e que sintoma descreve o evento, mesmo sem os nomear? |
| **Natureza do evento** | É um sinal de falha ou um pedido de serviço? |

A correlação é lógica do serviço, com tools diretas ou MCP. No exercício, corre no backend FastMCP quando se chama `report_event`. Os critérios também se aplicam a tickets e reclamações.

<!-- page 10 -->

TOPOLOGIA

## Uma pista para investigar uma causa comum

> diagram: Serviço A → Dependência partilhada ← Serviço B
> Componentes ligados por setas

- Serviço A
  - Erros observados
- Dependência partilhada
  - Hipótese a investigar
- Serviço B
  - Falhas observadas

### Cruzar as dependências com os sintomas e a sequência temporal

Estar ligado no grafo não prova uma causa comum. Exemplo ilustrativo.

<!-- page 11 -->

AVALIAÇÃO EM CÓDIGO

## Medir os erros de agrupamento

| MÉTRICA | PERGUNTA SOBRE PARES DE EVENTOS |
| --- | --- |
| **Precisão** | Dos pares que juntei, quantos pertencem ao mesmo grupo? |
| **Recall** | Dos pares que devia juntar, quantos consegui juntar? |
| **F1** | Como se equilibram a precisão e o recall? |

Testar também em eventos que não orientaram as regras. Uma boa pontuação não demonstra a causa do incidente.

<!-- page 12 -->

UM INCIDENTE, VÁRIAS FONTES

## Exercício 1

Objetivo: completar o servidor `incidents` para agrupar eventos relacionados.

| | |
| --- | --- |
| 1 · Correlacionar | Implementar `correlate()` com regras explícitas e justificadas. |
| 2 · Descrever | Explicar quando e como usar as duas tools do servidor. |
| 3 · Validar | Testar o agrupamento sem modelo e depois os dois casos com o agente. |

<!-- page 13 -->

FRONTEIRA DE CONFIANÇA

## Rug pull e shadowing

> diagram: fluxo de confiança com quatro componentes
> em ordem de leitura, da esquerda para a direita
> setas indicam a sequência

- Descrição externa: chega ao contexto
- O modelo lê: esse texto
- O modelo propõe: uma chamada
- A aplicação: permite ou bloqueia

| | | |
| --- | --- | --- |
| Rug pull | Aprovámos uma descrição. Depois, o servidor muda o texto e acrescenta instruções que não foram revistas. | Ex.: a consulta de métricas passa a recomendar um rollback automático. |
| Shadowing | A descrição de uma tool tenta dizer ao modelo como usar uma tool de outro servidor. | Ex.: o servidor de métricas manda o agente chamar rollback no servidor de deployments. |

O texto não executa nada por si: pode influenciar a chamada que o modelo propõe. Os dois mecanismos podem ocorrer juntos. Exemplos ilustrativos.

<!-- page 14 -->

CATÁLOGO E SELEÇÃO

## Aprovar o catálogo e escolher o necessário

| | |
| --- | --- |
| **Aprovar** | Registar no lockfile as descrições que foram revistas. |
| **Comparar** | Se a descrição mudar, exigir revisão antes de a voltar a expor. |
| **Selecionar** | Disponibilizar apenas as tools necessárias à tarefa. |

Comparar descrições não audita o código do servidor nem concede permissões de execução.

<!-- page 15 -->

POLÍTICA DA APLICAÇÃO

## Hooks do gatekeeper

| | | |
| --- | --- | --- |
| **approve_tool** | Esta definição deve chegar ao modelo? | Ex.: excluir uma tool que silencia alertas, porque este agente não precisa dela. |
| **check_call** | Esta chamada, com estes argumentos, pode avançar? | Ex.: permitir reiniciar uma instância; bloquear o reinício do serviço inteiro. |
| **after_call** | O resultado muda o que podemos fazer a seguir? | Ex.: guardar uma recusa de permissão para bloquear nova tentativa da mesma tool. |

São hooks da aplicação do agente, não do protocolo MCP. O controlo acontece na aplicação, antes e depois das chamadas ao backend.

<!-- page 16 -->

ACESSO REMOTO

## Ligação, permissões e recusas

| | |
| --- | --- |
| **Autenticação** | Quem está a fazer o pedido? |
| **Autorização** | O que permitem estas credenciais e scopes? |
| **Seleção** | Que capacidades fazem sentido para esta tarefa? |

Ex.: as credenciais permitem ler tickets, mas o backend recusa mudar o estado. Mostrar a tool ao modelo não dá essa permissão.

<!-- page 17 -->

CONTROLAR O ACESSO AOS SERVIDORES

## Exercício 2

Objetivo: controlar o que o agente vê e o que pode executar.

| | |
| --- | --- |
| **1 · Aprovar** | Rever o catálogo e fixar no lockfile as descrições aprovadas. |
| **2 · Limitar** | Selecionar as tools necessárias e bloquear chamadas perigosas. |
| **3 · Respeitar recusas** | Usar o resultado para impedir insistência após uma recusa de permissão. |

<!-- page 18 -->

FECHO

## Seleção, governação ou credenciais?

| SITUAÇÃO | ONDE INTERVIR |
| --- | --- |
| A tool existe, mas é irrelevante para esta tarefa. | Seleção de capacidades |
| A descrição mudou ou o servidor não foi revisto. | Governação do servidor |
| A chamada faz sentido, mas o acesso foi recusado. | Credenciais e scopes |

> Que evidência dos casos testados permite identificar onde intervir?
