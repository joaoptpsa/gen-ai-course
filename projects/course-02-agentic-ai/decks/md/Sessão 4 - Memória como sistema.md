<!-- page 1 -->

*CURSO 2 / SESSÃO 4*

# Memória como sistema de dados

## Escrever, ler e esquecer com regras

Agentic AI: Da Arquitetura à Implementação
Luís Noronha

<!-- page 2 -->

*ENQUADRAMENTO*

# O que muda quando o agente guarda informação

## Sem memória persistente

A execução seguinte não recebe as conclusões anteriores.

É preciso voltar a investigar, mesmo quando já houve um incidente semelhante.

## Com uma memória sem regras

Qualquer nota fica guardada, com confiança total e sem prazo.

Uma conclusão antiga pode ser usada mesmo depois de o sistema ter mudado.

> Que informação deve passar para a execução seguinte, e como deve ser verificada?

<!-- page 3 -->

*PROBLEMA DE TRABALHO*

# Quatro falhas no uso da memória

| | |
|---|---|
| **Guardar sem validade** | “A instância usa 92 % da memória RAM” fica guardado como se fosse um estado permanente. |
| **Perder a origem** | Uma frase de um ticket recebe a mesma confiança que uma observação verificada pela equipa. |
| **Não confirmar o presente** | Uma nota antiga substitui a consulta das métricas atuais. |
| **Não apagar de facto** | Uma nota removida continua a surgir na pesquisa, apesar da resposta “apagado”. |

<!-- page 4 -->

*ENQUADRAMENTO*

# Objetivos da sessão

| | |
|---|---|
| **Escrever com critérios** | Decidir o que guardar, com que origem, confiança e prazo de validade. |
| **Recuperar com contexto** | Selecionar memórias relevantes e mostrar quando foram escritas e o que mudou desde então. |
| **Verificar a continuidade** | Preparar a passagem de turno, confirmar o apagamento e comparar execuções com e sem memória. |

<!-- page 5 -->

*MEMÓRIA E CONTEXTO*

# Guardar informação não é manter tudo no prompt

## Contexto deste pedido

Instruções, tools e informação enviada ao modelo nesta chamada.

Só aparece num pedido futuro se a aplicação voltar a incluí-lo.

## Memória entre execuções

Registos persistidos pela aplicação em ficheiros ou numa base de dados.

Antes de outro pedido, a aplicação recupera os registos relevantes e inclui-os no contexto.

Exemplo: a ferramenta de memória da Anthropic usa ficheiros geridos pela aplicação. Fonte: Anthropic, “Managing context” (2025).

<!-- page 6 -->

*EVIDÊNCIA*

# O benefício da memória depende da tarefa

|  |  |
|---|---|
| **Anthropic (2025)** | Numa avaliação interna de pesquisa, memória e remoção de conteúdo antigo do contexto melhoraram o resultado em 39 %. Só a remoção: 29 %. |
| **Mem0 (2025)** | Em LOCOMO, um teste sobre conversas longas, os autores reportam mais de 90 % de redução nos tokens e 91 % na latência p95, face ao histórico completo. |
| **No projeto** | Comparar as mesmas tarefas com e sem memória: resultado, passos, tokens e erros causados por informação antiga. |

Mem0: ferramenta que guarda e recupera informação entre conversas. p95: tempo abaixo do qual ficam 95 % das respostas.
Fontes: Anthropic, “Managing context” (2025); Chhikara et al., “Mem0”, arXiv 2504.19413 (2025).

<!-- page 7 -->

*ESCREVER*

# Que informação acompanha cada memória?

| CAMPO | O QUE REGISTAR | EXEMPLO NO EXERCÍCIO |
|---|---|---|
| Origem | Quem afirmou e qual a evidência. | Pessoa da equipa, métrica, ticket ou conclusão do agente. |
| Confiança | Quanto crédito atribuir à nota. | Uma observação verificada tem mais peso do que um palpite. |
| Validade | Até quando se aplica e quando reavaliar. | Estado recente; lição associada a uma versão do software. |
| Equipa | Quem pode recuperar ou apagar o registo. | A equipa proprietária da memória. |
| Conteúdo | O que é útil e o que deve ser removido. | Guardar a lição; excluir contactos pessoais e segredos. |

<!-- page 8 -->

*ORIGEM E EVIDÊNCIA*

# A origem da nota também precisa de ser verificada

**Nota candidata:** "O consumo de memória RAM da instância 2 aumenta continuamente."

| ORIGEM CITADA | COMO TRATAR A NOTA | O QUE CONFIRMAR |
|---|---|---|
| Engenheiro de serviço | Relato da equipa. | Identidade e evidência que sustenta a observação. |
| Métricas ou logs | Observação de uma fonte técnica. | Instância, momento e medição citada. |
| Conclusão do agente | Hipótese, se não houver evidência. | Que dados permitem confirmá-la. |
| Ticket ou e-mail | Texto escrito por terceiros. | Origem e evidência, antes de o promover a lição. |

Um pedido para "guardar isto" não torna a informação verdadeira nem autoriza uma ação.

<!-- page 9 -->

*VALIDADE*

# Distinguir uma medição de uma lição reutilizável

## Medição de um momento

“A instância 2 do gateway usa 92 % da memória RAM.”

Pode mudar a seguir a uma ação. É preciso consultar as métricas atuais.

## Lição sobre uma versão

“Na versão 2.4.0, uma fuga de memória afeta uma instância. Reiniciá-la alivia temporariamente o consumo.”

Pode orientar outra investigação, enquanto a versão e as condições se mantiverem.

Definir validade e reavaliar após mudanças. Se a informação já existir numa fonte fiável, guardar a referência evita duplicações.

<!-- page 10 -->

*ATUALIZAR A MEMÓRIA*

# O que fazer quando chega uma nota nova

**Memória já guardada:** “O gateway está na versão 2.4.0 e tem uma fuga de memória. Reiniciar a instância afetada reduz temporariamente o consumo.”

| INFORMAÇÃO QUE CHEGA AGORA | DECISÃO | O QUE MUDA NA MEMÓRIA |
|---|---|---|
| “Confirmada a fuga na versão 2.4.0; reiniciar alivia o consumo.” | Ignorar | Não criar uma cópia: a informação já estava guardada. |
| “Na versão 2.4.0, a fuga agrava-se entre as 14h30 e as 15h00.” | Atualizar | Manter a nota e acrescentar o horário. |
| “Foi instalada a versão 2.4.1, que corrige a fuga de memória.” | Substituir | Guardar a correção e marcar a nota antiga como desatualizada. |
| “A corretora NORDBANK envia mais ordens antes da abertura.” | Acrescentar | Criar outra memória: é um assunto diferente. |

Comparar cada nota nova com esta memória. As linhas são cenários independentes.

<!-- page 11 -->

*DEMONSTRAÇÃO DE INVESTIGAÇÃO*

# Gemini: uma instrução fica guardada para depois

> Num teste de 2025, um documento contém instruções escondidas para guardar informação falsa na memória.
>
> O utilizador pede um resumo. A resposta induz a continuação da conversa com certas palavras.
>
> Quando o utilizador responde, o Gemini guarda a informação escolhida pelo investigador.
>
> **O registo pode acompanhar conversas futuras, já separado do documento de origem.**

Fonte: Johann Rehberger, "Hacking Gemini's Memory..." (10-02-2025).

> Que verificação impediria uma instrução do documento de se tornar uma memória de confiança?

<!-- page 12 -->

*ESCRITA DA MEMÓRIA*

# Exercício 1

**Objetivo:** guardar apenas informação útil, com origem e validade explícitas.

| | |
|---|---|
| **1 · Selecionar** | Identificar a origem da nota e decidir o que guardar, com que confiança e validade. |
| **2 · Atualizar** | Distinguir repetição, detalhe adicional, correção e assunto novo; clarificar a descrição da tool de escrita. |
| **3 · Verificar** | Testar as regras de escrita e o comportamento do agente perante um pedido para guardar informação não fiável. |

<!-- page 13 -->

*LER*

# A memória diz onde olhar, não o que é verdade agora

> diagram: três componentes em sequência, ligados por setas
> memória → estado atual → decisão

- memória
  - uma pista com data e autor
- estado atual
  - métricas, alterações, tickets
- decisão

## Nota de há três semanas

“O alerta de lentidão durante o backup das 2h00 é esperado. Não é preciso investigar.”

## O que mudou desde então

Na semana passada, a base de dados duplicou de tamanho. Hoje, o backup das 2h00 bloqueia as escritas.

A nota estava certa quando foi escrita. O que a torna perigosa é o que mudou depois.

<!-- page 14 -->

*RECUPERAR*

# Que memórias chegam ao modelo?

| | |
|---|---|
| **Filtrar** | Aplicar as regras de equipa e validade antes de apresentar os registos ao modelo. |
| **Ordenar** | No exercício, priorizar origem mais confiável e depois recência; limitar a quantidade devolvida. |
| **Contextualizar** | Mostrar o conteúdo com origem, idade e confiança: “nota da equipa escrita antes da alteração de configuração”. |
| **Sinalizar mudanças** | Apresentar alterações relevantes posteriores e notas que se contradizem. |

A aplicação aplica os filtros. O modelo recebe apenas as memórias que passaram essas verificações.

<!-- page 15 -->

*PESQUISA NO HISTÓRICO*

# Qual dos incidentes anteriores é relevante?

**Agora:** o gateway devolve erros HTTP 503 após uma alteração de configuração. A latência mantém-se normal.

## Só componente e data

Recupera o incidente mais recente do gateway: fuga de memória e latência alta.

Nesse caso, reiniciar uma instância ajudou. Os sintomas de hoje são diferentes.

## Componente e sintomas

Recupera um caso com erros 503 após alteração de rotas e latência normal.

Nesse caso, reverteu-se a alteração. É uma pista para verificar a configuração atual.

Recuperar um caso semelhante não confirma a causa. Verificar o estado atual antes de repetir a solução.

<!-- page 16 -->

*MEMÓRIA ENVENENADA*

# Uma nota falsa pode influenciar outra execução

| | |
|---|---|
| **Entrada** | Um atacante influencia uma conversa, um ticket ou outro conteúdo que o agente pode guardar. |
| **Persistência** | A informação falsa fica armazenada como memória e reaparece num pedido posterior. |
| **Controlo** | Preservar origem, validar a escrita e confirmar no estado atual qualquer decisão baseada nessa memória. |

MINJA estudou este mecanismo em agentes com memória; os resultados dependem dos sistemas testados.
Fontes: Dong et al., "MINJA", arXiv 2503.03704 (2025); OWASP, ASI06 (2025).

<!-- page 17 -->

*RECUPERAÇÃO DA MEMÓRIA*

# Exercício 2

**Objetivo:** usar o histórico como apoio à investigação, mantendo a verificação do presente.

| | |
|---|---|
| **1 · Selecionar** | Filtrar memórias por equipa e validade e ordenar os registos relevantes. |
| **2 · Contextualizar** | Mostrar origem, idade, confiança, alterações posteriores e conflitos entre notas. |
| **3 · Investigar** | Procurar incidentes por sintomas e orientar o agente a confirmar métricas e alterações antes de agir. |

<!-- page 18 -->

*DISCUSSÃO DO EXERCÍCIO 2*

# Como avaliar a recuperação de memórias

|   |   |
|---|---|
| **Visibilidade** | O modelo recebe informação suficiente para perceber a origem e a idade de cada nota? |
| **Isolamento** | Alguma memória de outra equipa ou fora de validade atravessa o filtro? |
| **Conflitos** | As métricas e alterações atuais permitem distinguir notas que já não se aplicam? |
| **Semelhança** | O caso antigo tem sintomas úteis para investigar, ou apenas o mesmo nome de componente? |

<!-- page 19 -->

*PASSAGEM DE TURNO*

# O que a execução seguinte precisa de saber

| Situação encontrada | Incidente, hipótese ou causa confirmada e evidência consultada. |
|---|---|
| Ações e efeitos | O que foi executado e o resultado observado: “a instância 2 foi reiniciada e a latência baixou”. |
| Trabalho em aberto | O que falta resolver, aprovar ou confirmar e quem está envolvido. |
| Próximas verificações | O que precisa de nova leitura: por exemplo, qual a instância com consumo de memória elevado agora. |

No exercício, a nota tem validade limitada e a nova passagem de turno substitui a anterior do mesmo incidente.

<!-- page 20 -->

*PROCEDIMENTOS*

# Uma proposta só se torna procedimento após revisão

> diagram: fluxo de quatro etapas
> ligadas por setas, da esquerda para a direita
> (ordem de leitura)

- incidentes anteriores: evidência repetida
- proposta: ainda não aprovada
- revisão humana: papel autorizado
- procedimento: origem registada

|  |  |
|---|---|
| **Antes da revisão** | A proposta fica identificada como proposta; não deve ser usada como uma regra operacional aprovada. |
| **Regra do exercício** | Exigir incidentes distintos e aprovação do engenheiro de serviço ou gestor de incidente da mesma equipa. |
| **Depois da revisão** | Registar quem aprovou e a proposta de origem. A aprovação não dispensa verificar o estado antes de agir. |

<!-- page 21 -->

*CONTINUIDADE ENTRE EXECUÇÕES*

# Exercício 3

**Objetivo:** preparar a execução seguinte sem copiar decisões antigas para um estado novo.

| | |
|---|---|
| **1 · Passar contexto** | Guardar uma nota de turno útil e verificar o apagamento de memórias a pedido. |
| **2 · Rever propostas** | Separar a proposta do agente da aprovação humana de um procedimento. |
| **3 · Comparar** | Executar os dois dias e comparar o segundo com e sem memória: resultado, passos e tokens. |

<!-- page 22 -->

*DISCUSSÃO DO EXERCÍCIO 3*

# Que evidência demonstra uma continuidade útil?

| | |
|---|---|
| **Estado atual** | A execução seguinte confirma as métricas ou repete a ação sobre a instância do dia anterior? |
| **Valor da memória** | A comparação com e sem memória mostra benefício, custo adicional ou decisões erradas? |
| **Revisão humana** | Uma proposta pode tornar-se procedimento sem aprovação válida? |
| **Apagamento real** | A memória removida deixa de aparecer, mantendo apenas o registo da operação? |

<!-- page 23 -->

*FECHO*

# Guardar, recuperar e verificar

| | |
|---|---|
| **Guardar** | Escolher conteúdo, origem, confiança e validade; tratar correções e repetições. |
| **Recuperar** | Aplicar filtros e apresentar as memórias com contexto suficiente para as interpretar. |
| **Verificar** | Confirmar o estado atual, medir o efeito da memória e testar se o apagamento aconteceu. |
