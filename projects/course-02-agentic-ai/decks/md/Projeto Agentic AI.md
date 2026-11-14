<!-- page 1 -->

*CURSO 2 / PROJETO*

# Projeto

## Proposta comum, requisitos mínimos e avaliação

Agentic AI: Da Arquitetura à Implementação
Luís Noronha

<!-- page 2 -->

*ESCOLHA DO PROJETO*

# Proposta comum ou projeto próprio

## Proposta comum

Sistema de resposta a incidentes da Meridian Exchange.

Simulador, fontes e casos fornecidos para concentrar o trabalho nos agentes.

## Projeto próprio ou continuação

Outro problema ou evolução de um projeto existente.

O âmbito deve demonstrar os mesmos requisitos e um nível de complexidade equivalente.

A escolha do tema mantém-se em aberto. Os requisitos mínimos e os critérios de avaliação são comuns.

<!-- page 3 -->

*PROPOSTA COMUM · CENÁRIO*

# Meridian Exchange

> diagram: Gateway de ordens → Motor de negociação; Dados de mercado → Motor de negociação
> Motor de negociação → Liquidação → Base de dados de referência
> Gateway de ordens → Base de dados de referência

- Gateway de ordens
- Base de dados de referência
- Dados de mercado
- Motor de negociação
- Liquidação

Investigar incidentes, executar mitigações autorizadas e confirmar a recuperação com evidência.

Bolsa fictícia num simulador em Python. Alertas, tickets e reclamações podem descrever o mesmo problema. Ações em componentes críticos exigem aprovação.

<!-- page 4 -->

*PROGRESSÃO*

# Um projeto que ganha responsabilidades

| MARCO | CAPACIDADES ACRESCENTADAS | EVIDÊNCIA |
|---|---|---|
| First-Line Incident Agent<br>sessões 1–3 | Investigar, usar tools/MCP e agir dentro de limites. | Fontes consultadas, decisões e efeitos verificados. |
| Production On-Call Agent<br>sessões 4–6 | Memória entre execuções, segurança e avaliação repetida. | Memórias corrigidas, permissões respeitadas e regressões medidas. |
| 24/7 Incident Response Center<br>sessões 7–9 | Correções técnicas, coordenação multiagente e retoma. | Trabalho integrado e recuperação sem repetir efeitos. |

Os marcos evoluem o mesmo sistema. Num projeto próprio, a progressão deve demonstrar capacidades equivalentes.

<!-- page 5 -->

*ÂMBITO DO TRABALHO*

# Base fornecida e trabalho a desenvolver

| BASE DA PROPOSTA COMUM | TRABALHO A DESENVOLVER |
|---|---|
| Simulador, fontes e cenários de incidente. | Harness, contexto e interfaces de tools. |
| Runbooks, tools e servidores MCP de base. | Políticas de memória, permissões e aprovação. |
| Executor e casos iniciais de avaliação. | Agentes, contratos de tarefa e coordenação. |
| Infraestrutura de suporte preparada ao longo do curso. | Integração, retoma e casos novos de avaliação. |

Adaptar o código e os padrões das aulas. Uma interface simples é suficiente; o foco está no comportamento dos agentes.

<!-- page 6 -->

*REQUISITOS MÍNIMOS · CAPACIDADES*

# O que o sistema final deve incluir

| | |
|---|---|
| **Fluxo principal** | Funciona de ponta a ponta, do pedido ao resultado verificado, com contexto selecionado. Resposta controlada quando falta informação, o output é inválido ou um serviço falha. |
| **Tools e MCP** | Tools com contratos claros e uma integração MCP funcional, com seleção das capacidades expostas. Outputs estruturados validados em código antes de serem usados no passo seguinte. |
| **Memória** | Estado entre execuções com origem, validade, correção e isolamento definidos. |
| **Coordenação** | Orquestrador e pelo menos dois especialistas com responsabilidades distintas e resultados integrados. |

<!-- page 7 -->

*REQUISITOS MÍNIMOS · EXECUÇÃO*

# Ações controladas e execução recuperável

|  |  |
| --- | --- |
| **Efeitos verificáveis** | Executar uma ação, mesmo simulada, e confirmar a consequência antes de concluir ou repetir. |
| **Permissões** | Aplicar limites em código, proteger dados e pedir aprovação nas ações que a exigem. |
| **Retoma** | Persistir o estado do trabalho e retomar após interrupção, revalidando permissões e efeitos já produzidos. |
| **Dados e ambiente** | Dados sintéticos aceites; preparar dados locais para testar falhas de serviços externos. Chaves só em `.env`, nunca no repositório. |

<!-- page 8 -->

*PROJETO PRÓPRIO · EQUIVALÊNCIA*

# Como evoluir um projeto do Curso 1

| DIMENSÃO | EXEMPLO: EVOLUÇÃO DE UM ASSISTENTE DE COMPLIANCE |
|---|---|
| Decisão e ação | Investigar evidência e abrir uma tarefa de correção com a aprovação necessária. |
| Coordenação | Separar recolha, revisão e remediação, com contratos e verificação do resultado conjunto. |
| Estado e retoma | Guardar decisões e aprovações; retomar após interrupção com a versão atual do documento. |
| Avaliação | Testar evidência em falta, instruções adversariais, recusas e recuperação, mantendo os casos anteriores. |

<!-- page 9 -->

*AVALIAÇÃO E DEMONSTRAÇÃO*

# Critérios e evidência a demonstrar

| CRITÉRIO | EVIDÊNCIA NA DEMONSTRAÇÃO E NOS CASOS |
|---|---|
| Conclusão da tarefa | Caso com várias fontes e resultado verificado; resposta controlada perante informação em falta ou falhas. |
| Controlo e segurança | Ação autorizada com efeito confirmado; ação indevida recusada; dados e aprovações respeitados. |
| Coordenação e retoma | Resultados integrados, falha entre especialistas detetada e interrupção recuperada sem repetir efeitos indevidos. |
| Evolução fundamentada | Baseline e versões comparadas nos mesmos casos e estado inicial; casos novos, regressões e limites identificados. |
| Clareza da engenharia | Execução a partir do README num clone limpo; decisões de arquitetura sustentadas por traces e resultados. |

<!-- page 10 -->

*APRESENTAÇÃO E ENTREGA*

# O que entregar

| | |
|---|---|
| **Proposta** | Problema, utilizador, fluxo e diagrama; num projeto próprio, correspondência com os requisitos. |
| **Repositório** | Código, dependências declaradas e lock, `.env.example` sem segredos e versões dos marcos. |
| **README** | Setup e execução, arquitetura, políticas, decisões, limitações e demo. Assistentes de IA permitidos, com uso declarado. |
| **Casos e resultados** | Entradas, resultados esperados e obtidos; comparações e traces, com versão, modelo e limites registados. |

Entrega final até 30 de novembro, às 23h59. Testes unitários e métricas construídas de raiz não são exigidas.
