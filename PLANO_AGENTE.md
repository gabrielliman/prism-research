# Plano de trabalho para o agente: políticas de residência orientadas a prazos no Prism

Este documento é a especificação de trabalho para um agente que vai operar no repositório de pesquisa do Prism (fork de `github.com/Multi-LLM/prism-research`). Ele descreve **o que fazer, em que ordem, como registrar e quando parar**. A lista de tarefas marcável está em `TODO.md`, que referencia as seções daqui pelos identificadores (F0, F1, …, A1, A2, …, C1, C2, …).

O texto parte do estado descrito em `reports/2026-10-29 Base para proposta` (correções de robustez R1–R2.5 aplicadas, cenários `ovl_*`, políticas sem prazo já comparadas) e da proposta de dissertação (políticas orientadas a prazos, controle de admissão, oráculo offline, avaliação em sobrecarga real com cargas sintéticas e traces reais).

---

## 0. Regras de operação do agente

Estas regras valem para todas as fases e têm prioridade sobre qualquer instrução de uma fase específica.

### 0.1 Portões (gates) entre fases

1. **Nenhuma fase começa antes de o gate da fase anterior estar marcado como APROVADO** no relatório da fase (`reports/fases/FXX_*.md`, seção "Decisão do gate").
2. Um gate só pode ser aprovado quando **todos** os critérios de aceitação da fase estão satisfeitos e documentados com evidência (caminho de arquivo, id de execução, tabela ou figura).
3. Gates marcados com **[HUMANO]** exigem aprovação explícita do Gabriel. O agente prepara o relatório, marca o gate como `AGUARDANDO REVISÃO` e **para**.
4. Se um critério falhar, o agente **não** avança e **não** relaxa o critério por conta própria. Ele abre uma investigação (seção 0.3) ou, se o critério parecer mal definido, registra a dúvida e para.

### 0.2 Validação de cada execução

Toda execução (um nível de carga de um cenário com uma política e uma semente) passa pelo validador `polyaxon/validate_run.py` (criado em F2) antes de entrar em qualquer agregado. O validador classifica a execução como `VALIDA`, `INVALIDA_INFRA` ou `INVALIDA_SISTEMA`. As verificações estão na seção 3.

- **Execuções inválidas nunca entram em médias, tabelas ou figuras.** Elas ficam listadas no registro com o motivo.
- **Não é permitido repetir uma execução às cegas.** Repetir só é permitido depois de classificar a causa:
  - `INVALIDA_INFRA` com evidência (nó degradado na verificação de saúde, job preemptado pelo Polyaxon, erro de rede do registro de imagens): no máximo **uma** repetição automática, registrada como tal.
  - `INVALIDA_SISTEMA` (worker morto, queda do servidor, requisições perdidas sem explicação, OOM, abort, travamento, métrica incoerente): investigação obrigatória antes de qualquer repetição.

### 0.3 Protocolo de investigação de execução com erro

Quando uma execução é `INVALIDA_SISTEMA`, ou quando um resultado válido é implausível (por exemplo, uma política nova melhora 10× sem explicação), o agente:

1. Congela os artefatos da execução (logs do servidor, do controlador, do gerador de carga, linha do tempo de memória, saída do `classify_errors.py`) em `reports/data/<fase>/<run_id>/`.
2. Reconstrói a linha do tempo: ações do controlador (ativações, despejos, recusas), estado de cada worker, memória da GPU, e as requisições afetadas (ids, horários, modelo).
3. Formula uma hipótese de causa e a testa com a menor execução que a reproduz (menos modelos, menor duração, mesma semente). Para travamentos, coleta `py-spy dump` de todos os processos durante o travamento.
4. Classifica a causa como: falha já conhecida (id em `erros.md`), falha nova (novo id em `erros.md`), erro de medição, erro de configuração do experimento, ou erro de infraestrutura.
5. Corrige (código, configuração ou medição), documenta a correção em `erros.md` (causa, mudança, teste) e **reexecuta a configuração original** para confirmar.
6. Registra tudo no relatório da fase, na seção "Anomalias e investigações". Uma investigação aberta bloqueia o gate da fase.

### 0.4 Disciplina de código

- Toda política nova fica atrás de variável de ambiente `PRISM_*`. **O padrão de cada variável reproduz o comportamento atual.** Nenhuma política nova muda o comportamento quando desligada.
- A lógica de decisão de cada política é uma função pura que recebe um retrato do estado (modelos, memória, filas, requisições com prazos, tempos estimados) e devolve ações. Isso permite testes unitários com estados construídos à mão (seção 0.6). O laço do controlador apenas monta o retrato e aplica as ações.
- O repositório do kvcached **não** é alterado, como até aqui.
- Um commit por passo lógico, com mensagem que cita o id da tarefa (ex.: `F4.2: reserva mínima de KV na ativação`).
- Nada de apagar dados de execuções anteriores. Dados novos vão para pastas novas.

### 0.5 Registros obrigatórios

| Registro | Onde | Conteúdo |
| --- | --- | --- |
| Relatório da fase | `reports/fases/FXX_<slug>.md` | modelo na seção 0.7 |
| Registro de execuções | `reports/registro/execucoes.csv` | uma linha por execução (colunas na seção 3.3) |
| Registro de decisões | `reports/registro/decisoes.md` | toda escolha de projeto ou parâmetro, com data, alternativas consideradas, motivo e quem decidiu (agente ou Gabriel) |
| Catálogo de cargas | `reports/registro/cargas.md` | uma entrada por carga (seção 5), com origem, licença, transformação, estatísticas e hash dos arquivos |
| Erros | `erros.md` | ids existentes e novos, situação de cada um |
| Estado do plano | `TODO.md` | caixas marcadas, data e link para a evidência |

### 0.6 Testes unitários das funções de decisão

Cada política tem testes em `tests/policy/` com estados construídos à mão que cobrem: o caso típico, os casos de borda (fila vazia, memória exatamente no limite, todos os modelos ociosos, nenhum modelo cabe), e os casos que motivaram a política (fome, impasse, troca de grupo). Os testes verificam a **decisão**, não o desempenho. Não se trata de um simulador: nenhum teste reproduz a dinâmica de carga ao longo do tempo.

### 0.7 Modelo de relatório de fase

```markdown
# FXX — <título>
Data de início / fim:
Commits:
## Objetivo
## Hipóteses (o que esperamos observar e por quê)
## Mudanças de código (arquivo, função, variável de ambiente, padrão)
## Configurações executadas (suite .tsv, cenários, políticas, parâmetros, sementes)
## Execuções (tabela: run_id, status do validador, observação)
## Resultados (tabelas e figuras com caminho; só execuções VALIDAS)
## Anomalias e investigações (cada uma com causa, correção e verificação)
## Critérios de aceitação (cada critério: OK/FALHOU + evidência)
## Decisão do gate: APROVADO | REPROVADO | AGUARDANDO REVISÃO
## Pendências que passam para fases seguintes
```

### 0.8 Infraestrutura

- Polyaxon (`kunumi/hpc4ai`), imagem do `install.md` (SGLang 0.3.4 do Prism + kvcached + Redis), uma H200 por job, até 8 H200 disponíveis.
- **No máximo 3 jobs do Prism simultâneos no nó**, contando todas as sessões. Em 30/10, com 4 jobs, 38% dos níveis tiveram erro do driver no kvcached, e com 5 ou mais, 71–79% (`reports/2026-10-30 Variação de desempenho do nó GPU do cluster.md`). Mesmo com 3 jobs, a disputa de CPU distorce a cauda do TPOT (D21).
- Manter a verificação de saúde do nó antes de cada nível (R2.4). Se jobs simultâneos interferirem entre si (detectado pelo validador), reduzir o paralelismo e registrar a decisão.
- Toda campanha registra a versão do código (hash do commit), a imagem e as variáveis de ambiente efetivas.

### 0.9 Relevância da carga antes de rodar

Antes de submeter qualquer execução ao Polyaxon, o agente justifica, para cada carga, **por que ela exercita o que está sendo mudado**. Por exemplo, uma política de residência só se testa em carga com disputa por residência, ou seja, com ativações e despejos. Também verifica se já existem dados reaproveitáveis.

- Cargas que não exercitam a mudança ficam fora e são registradas como tal.
- Execuções de linha de base reaproveitáveis não são refeitas sem motivo. Os motivos válidos são deriva do nó, código diferente ou pareamento exigido pela comparação.
- A justificativa vai para o relatório da fase, na seção "Configurações executadas".

### 0.10 Resultados de políticas novas: sempre contra as anteriores (D32)

Em todo relatório e toda apresentação com resultados de uma política nova:
- **comparar com as políticas que já temos, rodadas na mesma janela**, e não só com a A0.1:
  - a melhor ociosidade de valor arbitrário (a A0.2 ou o melhor limiar da varredura mais recente);
  - a troca por throughput/GB **sem e com preempção** (A0.3 e A0.3p);
  - as políticas novas anteriores (ex.: EDF e VLT da F6a), quando a pergunta for a mesma;
- as tabelas mostram, além da fração dentro do SLO (três vistas, seção 7.1), o **TTFT p50 e p90** e a **cauda de espera** (TTFT p99, máximo e fração acima de 10× a mediana; seção 7, D33);
- uma apresentação nunca mostra só a política nova isolada.

---

## 1. Ponto de partida (o que já existe)

O agente deve confirmar cada item em F0 em vez de assumir.

- **Correções de robustez:** R1 (ativação que falha é desfeita; detecção de workers mortos), R2.1 (desconto de ativações em andamento), R2.2 (`PrefillKVFull`; exceção derruba só o worker), R2.3 (confirmação de desativação superada), R2.4 (infra de teste), R2.5 (TTFT e término de requisições retiradas), devolução ao Redis na troca por throughput (P6).
- **Políticas sem prazo** em `python/sglang/multi_model/scheduling/policy/simple_global.py`, controladas por `PRISM_EVICTION`, `PRISM_IDLE_THRESHOLD`, `PRISM_ACTIVATION_HEADROOM_GB`: limiar de ociosidade, despejo sob pressão, ociosidade adaptativa, rodízio anti-fome, folga de KV na ativação, troca por throughput por GB (variantes P e D).
- **Cenários:** `ovl_mem`, `ovl_phases`, `ovl_trace_big`, `ovl_mix`, `ovl_kv`, `ovl_compute` (`polyaxon/configs/*_suite.tsv`), gerador `polyaxon/overload_load.py`.
- **Análise:** `collect_reps.py`, `classify_errors.py`, `report_tables.py`, `plot_suite.py`, `plot_limits.py`.
- **Pendências conhecidas:** T1 com 14 modelos (causa não confirmada), teste da folga de KV no `ovl_mix` em andamento, 25 requisições perdidas em 1 de 3 execuções com preempção sem drenagem (suspeita no caminho de devolução ao Redis), K1 com nó degradado mitigado mas não eliminado, ausência de controle de admissão.
- **Questão aberta importante:** o artigo do Prism (OSDI'26) descreve uma arbitragem de requisições por folga (Moore-Hodgson) numa fila compartilhada por GPU. Não sabemos se ela existe e está ativa no código aberto que usamos. F0 responde isso.

---

## 2. Visão geral das fases

| Fase | Título | Depende de | Gate | Período alvo |
| --- | --- | --- | --- | --- |
| F0 | Reconhecimento e reprodução da linha de base | — | [HUMANO] | nov/2026 |
| F1 | Fechar a robustez restante | F0 | automático | nov/2026 |
| F2 | Instrumentação, validador e estimadores | F1 | [HUMANO] | nov–dez/2026 |
| **F6a** | **Primeira rodada das políticas por prazo (A2.1, A9.1), adiantada (D24)** | F2 | [HUMANO] | **nov/2026 (prioridade atual)** |
| F3 | Catálogo de cargas | F2, F6a | [HUMANO] | dez/2026–jan/2027 |
| F4 | Restrições estruturais (A1) | F3 | automático | jan/2027 |
| F5 | Campanha de linhas de base sob a nova metodologia | F4 | [HUMANO] | jan–fev/2027 |
| F6 | Ativação e despejo por folga (A2, A3, A4) e por atraso virtual (A9) | F5 | [HUMANO] | mar–jun/2027 |
| F7 | Controle de admissão e arbitragem com custo de ativação (A5, A6) | F6 | [HUMANO] | mai–ago/2027 |
| F8 | Prazos ponderados e classes de SLO (A7) | F6 | automático | jun–ago/2027 |
| F9 | Oráculo offline (A8) | F2, F3 | [HUMANO] | jan–abr/2027 (em paralelo) |
| F10 | Campanha final de avaliação | F6–F9 | [HUMANO] | jul–set/2027 |
| F11 | Consolidação para artigos e dissertação | F10 | [HUMANO] | set/2027 em diante |

**Reordenação de 2026-11-04 (D24, Gabriel):**
- antes da F3, entra a F6a, uma primeira rodada das duas políticas por prazo mais simples, só com as cargas atuais;
- as tarefas da F6a passam na frente de qualquer outra;
- o restante da F6 (A2.2, A2.3, A3, A4, A9.2) continua depois da F5, como antes;
- a F3 começa depois do gate da F6a.

**Depois da F6a (D30, D31, Gabriel, 2026-11-05):**
- a drenagem de 15 s foi removida (D30); a desativação de uma vítima é só preemptar ou não;
- a F6 ganha uma ordem de prioridade (seção F6, "Prioridades").

**Revisão de 2026-11-05 (D32, Gabriel):** a F6b (D31) deixa de ser uma fase própria e vem depois da F4:
- a medição do custo real da troca e as métricas novas (violações inevitáveis pela rotação, ociosidade da GPU, TTFT p50/p90 como objetivo, família de SLO pela rotação) entram na **F5** (F5.0), porque a campanha de linhas de base precisa delas;
- a repetição da triagem da F6a sem drenagem, **com e sem preempção**, entra na **F6** (F6.0);
- entra a família de políticas A10 (throughput × prazo × fila) na F6.

Marcos externos: F0–F5 sustentam o artigo de resultados parciais (metodologia de sobrecarga + fragilidades + linhas de base), com submissão prevista para fevereiro de 2027 (EuroMLSys) ou maio–junho de 2027 (SBAC-PAD). F10 sustenta o artigo final (EuroSys 2028, setembro de 2027, ou MLSys 2028, outubro de 2027).

---

## 3. Validador de execução e registro (construído em F2, usado em todas as fases seguintes)

### 3.1 Verificações do validador

Cada verificação produz `OK`, `FALHA` ou `N/A`, com o valor medido.

**Integridade do sistema**
- V1. Servidor vivo do início ao fim da carga e do prazo extra.
- V2. Zero mortes de worker, zero `abort()`, zero `OutOfMemoryError`, zero exceções não tratadas (via `classify_errors.py`).
- V3. Nenhum modelo preso em estado intermediário (`ativando`/`desativando`) por mais que um limite (ex.: 3× o tempo máximo de ativação medido).
- V4. Nenhum worker entregue a dois modelos ao mesmo tempo.

**Conservação de requisições**
- V5. `enviadas = concluídas + recusadas + expiradas` exatamente; toda requisição tem um estado final.
- V6. Toda requisição recusada tem um motivo registrado pela política (só a partir de F7).
- V7. Toda requisição retirada (preempção, desativação) reaparece na fila e termina, ou está explicada.

**Coerência das métricas**
- V8. Para toda requisição concluída: `chegada ≤ primeiro token ≤ término`; TTFT e TPOT não negativos; número de tokens de saída igual ao pedido (o gerador fixa o tamanho exato).
- V9. Nenhum TTFT sobrescrito (S4): o TTFT registrado é o do primeiro prefill.
- V10. Relógios coerentes entre gerador e servidor (diferença máxima tolerada registrada).

**Carga e regime**
- V11. Taxa de chegada efetiva dentro de ±5% da alvo, por modelo e no total.
- V12. Para cenários de sobrecarga de memória: evidência de sobrecarga (memória da GPU ≥ 95% por pelo menos X% da carga, ou eventos "não coube"). Sem evidência, a execução é `INVALIDA_SISTEMA` para aquele cenário (o cenário não exercitou o que deveria).
- V13. Memória física total nunca acima da capacidade; soma das reservas do controlador coerente com a memória medida (tolerância registrada).

**Infraestrutura**
- V14. Verificação de saúde do nó antes e depois da execução.
- V15. Sem preempção do job pelo Polyaxon.

### 3.2 Verificações de campanha (sobre um conjunto de execuções válidas)

- C-V1. Número de repetições válidas por configuração ≥ mínimo da fase (padrão: 5).
- C-V2. Coeficiente de variação das métricas principais entre repetições abaixo de um limite (padrão: 15% para fração de SLO; registrar exceções e investigar se acima).
- C-V3. Linha de base reproduzida: a política original e a melhor política sem prazo, rodadas na mesma campanha, ficam dentro do intervalo de confiança dos valores de referência de F5. Critério (decisão D2 de 2026-10-30): o IC 95% por bootstrap da diferença de médias (nova − referência) contém 0 no SLO, no TTFT p90 e na pior espera pelo 1º token (`polyaxon/compare_reference.py`). A referência roda no mesmo período, pareada com a nova (decisão D8 de 2026-10-30: a velocidade do cluster varia entre dias, 7–9 pontos de SLO entre 29/10 e 30/10).

### 3.3 Colunas de `reports/registro/execucoes.csv`

`run_id, data, fase, commit, imagem, cenario, carga_id, nivel, politica, parametros(json), politica_usa_slo, slo_familia, slo_nivel(json; vazio se a política não usa SLO), semente, repeticao, gpu, no, status_validador, verificacoes_falhas, motivo, repetida_de, caminho_artefatos`

---

## 4. Algoritmos

Notação comum, igual à da proposta: requisição `r` do modelo `m`, chegada `a_r`, prazo de primeiro token `d_r = a_r + S_m`, tempo estimado até o primeiro token `ê_r(t) = q̂_r + p̂_r + 1[m ∉ A(t)]·C_at(m)`, folga `s_r(t) = d_r − t − ê_r(t)`, conjunto ativo `A(t)`, restrição `Σ_{m∈A}(W_m + K_min(m)) ≤ M`.

### 4.0 Observação de projeto que condiciona tudo (verificar em F2)

Com o SLO atual (TTFT < 1 s) e ativações de 1,5 s a 21 s, **toda requisição que chega a um modelo inativo já nasce violada**: `s_r < 0` no instante da chegada. Nesse regime, uma política por prazo não consegue "salvar" requisições de modelos inativos reagindo à chegada. O que ela pode fazer é:

1. **decidir residência de forma preditiva**, mantendo na GPU os modelos com maior número esperado de chegadas no horizonte próximo (o custo de não ter `m` residente é a taxa de chegada de `m` vezes o horizonte);
2. **agir sobre classes de SLO mais folgadas** (`S_m > C_at(m)`), para as quais a ativação sob demanda é viável e a folga tem conteúdo;
3. **recusar cedo** o que é inviável, liberando recursos para o que ainda é viável.

Consequências para o plano:
- Toda avaliação separa **violações inevitáveis** (requisição chegou a modelo inativo com `S_m < C_at(m)`) de **violações evitáveis**. A métrica principal das políticas é sobre as evitáveis e o total.
- O SLO de TTFT é um **fator experimental**, não uma constante: varrer `S_m` relativo a `C_at(m)` (ex.: 0,5×, 1×, 2×, 5×).
- A família A2 inclui uma variante preditiva desde o início.

O agente deve confirmar essa observação com os dados de F2 (medir `C_at` real por tamanho de modelo) e registrá-la em `decisoes.md`.

### A0. Linhas de base (já existentes, só reconfigurar)

| Id | Política | Parâmetros |
| --- | --- | --- |
| A0.1 | Original do Prism | `PRISM_IDLE_THRESHOLD=50` |
| A0.2 | Limiar curto | `PRISM_IDLE_THRESHOLD=10` |
| A0.3 | Troca por throughput/GB, sem preempção | `PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=3`. Até a D30 era a variante com drenagem de 15 s (P0D1): execuções da A0.3 anteriores à D30 não se comparam com as novas |
| A0.3p | Troca por throughput/GB, com preempção | `PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=1 PRISM_ACTIVATION_HEADROOM_GB=3` (D32: entra em toda comparação junto com a A0.3) |
| A0.4 | A0.3 + A1, sem a folga fixa | `PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=0` + A1 (`PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10`). Escolhido na F4 (D37, D38): com a A1, a folga de 3 GB se soma ao piso do kvcached sem função; verificada em T3, C3, C7, C6 |
| A0.5 | Arbitragem Moore-Hodgson do Prism | só se F0 confirmar que existe no código aberto |

**Desativação de uma vítima (D30, vale para toda política que tira modelos ocupados).** A drenagem com prazo (`PRISM_SWAP_DRAIN`, 15 s) foi removida do código. A escolha é só entre:
- **não preemptar** (`PRISM_SWAP_PREEMPT=0`): as requisições aceitas e ainda não iniciadas voltam na hora para a fila do modelo, e o lote que já está em execução (KV na memória) termina, sem limite de tempo;
- **preemptar** (`PRISM_SWAP_PREEMPT=1`): o lote em execução também é retirado e recomeça do prompt depois (recomputação).

Motivo: nos logs da F6a, a drenagem chegava quase sempre ao teto de 15 s (a fila de espera alimentava novos prefills), e a vítima levava 22,7 s (mediana) para sair, incompatível com prazos de 0,7–7 s. O tempo para a vítima sair passa a ser o da requisição mais longa do lote em execução, e entra no custo da troca de toda política por prazo.

### A1. Restrições estruturais (F4)

**Motivação:** eliminar o impasse T1 independentemente da política de escolha.

- **A1.1 Reserva mínima de KV na ativação.** Ativar `m` só se `memória_livre − ativações_em_andamento ≥ W_m + K_min(m)`. `K_min(m)` = memória de KV para atender um lote mínimo útil de `m` (ex.: `b` requisições com o tamanho médio de prompt + saída da carga). Parâmetro `b` explícito; padrão escolhido em F4 a partir de medidas.
- **A1.2 Detector de impasse.** Se, por `Δ_imp` segundos, nenhum modelo ativo concluiu prefill nem gerou tokens e há requisições em fila, despejar o modelo ativo de menor valor (critério de A0.3 até F6; depois, o critério de A3). Registrar cada disparo com o estado completo.
- **A1.3 Histerese mínima de residência.** Um modelo recém-ativado não pode ser despejado antes de `T_min` segundos (evita trocas em ciclo). `T_min` derivado do custo de ativação medido.

**Critérios de aceitação (F4):** zero impasses em `ovl_mix` e `ovl_mem` com 8 e 14 modelos (5 repetições cada), com A0.1 e A0.3; nenhuma piora estatisticamente significativa nos cenários sem impasse; testes unitários cobrindo os estados do impasse observados.

### A2. Ativação por menor folga (F6)

**Motivação:** escolher **quem entra** pela urgência, não pela ordem de chegada nem pelo volume.

- **A2.1 EDF entre modelos (reativo).** Urgência `u_m = min_{r∈Q_m} s_r(t)` para cada modelo inativo com fila. Ativar em ordem crescente de `u_m`, enquanto couber (com A1.1). Requisições com `s_r` abaixo de um piso (inviáveis) não contam para a urgência, para não privilegiar filas já perdidas.
- **A2.2 Menor folga com antecipação.** Disparar a troca quando `u_m ≤ C_at(m) + margem`, mesmo que ainda caiba esperar um ciclo, porque o ciclo do controlador (5 s) é maior que muitas folgas. Avaliar também reduzir o ciclo do controlador (fator experimental: 5 s, 1 s, orientado a evento).
- **A2.3 Residência preditiva.** Para cada modelo, estimar a taxa de chegada `λ̂_m` (EWMA sobre janelas curtas e longas, com detecção de rajada) e calcular o número esperado de chegadas no horizonte `H` (ex.: `H = max C_at`). O valor de manter `m` residente é `λ̂_m · H · w_m`; o de ativar `m` inclui a fila atual viável. Esta variante é a resposta à observação 4.0 para SLOs estritos.

**Parâmetros:** piso de folga, margem, horizonte `H`, janelas do EWMA, ciclo do controlador. Todos registrados em `decisoes.md` com a justificativa.

### A3. Despejo por perda esperada de prazos (F6)

**Motivação:** escolher **quem sai** pelo prejuízo em prazos, não por ociosidade.

- Para cada modelo ativo `j`, perda esperada de despejá-lo: `L_j = (requisições de j em andamento que não terminariam antes do prazo se preemptadas, ou trabalho descartado) + λ̂_j · C_at(j) · w_j` (chegadas que perderiam o prazo enquanto `j` não volta) + custo de reativação se `j` tiver fila.
- Para cada candidato a entrar `i`, ganho esperado: `G_i = (requisições viáveis na fila de i) + λ̂_i · H · w_i`.
- **Troca** quando `G_i − Σ_{j∈V} L_j > θ`, em que `V` é o menor conjunto de vítimas que libera `W_i + K_min(i)`; escolha de `V` gulosa por `L_j / (W_j + KV_j)` (perda por GB liberado). `θ` é a histerese.
- **Preemptar ou não (D30):** não preemptar se as requisições em execução de `j` terminam (tokens restantes × TPOT) dentro da folga de `i`; preemptar caso contrário, com devolução ao Redis (P6). Variante a avaliar: decidir por requisição (terminar as que cabem na folga, preemptar o resto).
- Variantes: A3.1 só fila atual (sem `λ̂`); A3.2 com `λ̂`; A3.3 com escolha de vítimas ótima por mochila pequena (número de modelos é pequeno, enumeração exata é barata).

### A4. Política combinada (F6)

A2 decide a ordem de entrada, A3 decide as vítimas e se a troca compensa, A1 garante as restrições. O limiar de ociosidade continua como caminho de despejo barato para modelos sem fila e com `λ̂` baixo (o limiar curto foi o melhor para troca de grupos). Esta é a política candidata principal da dissertação.

### A5. Controle de admissão por viabilidade (F7)

**Motivação:** acima da capacidade, recusar cedo o inviável em vez de deixar a latência crescer sem limite.

- **A5.1 Recusa na chegada:** recusar `r` se `s_r(a_r) < −τ` mesmo no melhor caso (modelo ativo, sem fila). Responder com código de recusa explícito e motivo.
- **A5.2 Recusa por envelhecimento:** a cada ciclo, recusar requisições em fila cuja folga ficou abaixo de `−τ` (o prazo já passou por margem).
- **A5.3 Rebaixamento:** em vez de recusar, mover para a classe de lote (se F8 estiver ativo).
- **Métricas próprias:** taxa de recusa, recusas "erradas" (requisições recusadas que, no registro de capacidade, teriam terminado no prazo; estimado pós-execução), goodput.

### A6. Arbitragem por Moore-Hodgson com custo de ativação (F7)

Estender o algoritmo 2 do Prism (seleção de requisições por prazo que minimiza o número de atrasos) para considerar requisições de modelos inativos, com o custo de ativação como tempo de preparação do primeiro item de cada modelo. Escopo: um nó, uma GPU, fila compartilhada. Se F0 mostrar que o código aberto não tem a arbitragem original, implementá-la primeiro como A0.5 (e avaliá-la isoladamente) antes de estendê-la.

### A7. Prazos ponderados e classes de SLO (F8)

- Classes: **interativa** (TTFT estrito, ex. 1 s; TPOT 100 ms) e **lote** (TTFT folgado, ex. 30 s ou 60 s; a definir com o Gabriel). Cada requisição carrega a classe.
- Pesos `w_m` por modelo e por classe entram em A2, A3 e A5.
- Objetivos comparados: (i) fração total dentro do prazo; (ii) pior fração por modelo (max-min); (iii) soma ponderada. O agente produz, para cada política, o par (SLO agregado, pior modelo), que é o compromisso justiça × SLO observado nos testes preliminares.

### A8. Oráculo offline (F9)

**Objetivo:** limitante para a distância das políticas online ao ótimo, e uma política "clarividente" executável.

- **Discretização:** fatias de `δ` segundos (começar com 1 s; testar 0,5 s em instâncias pequenas). Durações de ativação em fatias: `a_m = ⌈C_at(m)/δ⌉`.
- **Variáveis:** `y[m,k] ∈ {0,1}` (m residente e servindo na fatia k), `z[m,k] ∈ {0,1}` (início de ativação de m em k), `x[m,k] ∈ Z≥0` (requisições de m cujo prefill começa em k).
- **Restrições:**
  - memória: `Σ_m (W_m + K_min(m))·(y[m,k] + Σ_{k'=k−a_m+1..k} z[m,k']) ≤ M` (modelos carregando ocupam memória);
  - residência: `y[m,k] ≤ y[m,k−1] + z[m,k−a_m]`;
  - capacidade de prefill: `Σ_m p̄_m · x[m,k] ≤ P_GPU·δ` e `x[m,k] ≤ U·y[m,k]`;
  - disponibilidade: `Σ_{k'≤k} x[m,k'] ≤ chegadas acumuladas de m até k` (só serve quem já chegou);
  - cada requisição conta como no prazo se servida até `⌊(a_r + S_m)/δ⌋` (contagem agregada por modelo e fatia de chegada, para manter o problema pequeno).
- **Objetivo:** maximizar requisições servidas no prazo (ponderadas por `w`).
- **Solver:** HiGHS (via `highspy` ou PuLP) ou OR-Tools CP-SAT; registrar limite de tempo e gap.
- **Validade:** o modelo simplifica o decode e a interferência de computação, então o valor é um limitante aproximado. Validar em instâncias minúsculas (2–3 modelos, 30 s) por enumeração exaustiva das sequências de residência.
- **Repetição real do plano ótimo:** exportar `y[m,k]` e executá-lo no sistema real como política `PRISM_EVICTION=oracle_replay` (lê o plano de um arquivo). A diferença entre o valor do ILP e o resultado real mede o erro do modelo; a diferença entre o oráculo executado e as políticas online mede a lacuna de otimalidade.
- **Escala alvo:** traces curtos (5–10 min, até 12 modelos). Registrar tempo de solução por instância.

### A9. Rotação por atraso virtual: Virtual Lag Time do SuperInfer (F6)

**Origem:** Yu et al., *SuperInfer: SLO-Aware Rotary Scheduling and Memory Management for LLM Inference on Superchips*, MLSys 2026, seção 4.2 (`SuperInfer.pdf`). Incluída a pedido do Gabriel em 2026-10-30 (`decisoes.md`, D4).

**O que o artigo faz.** Cada requisição está em espera, em execução ou "rotativa" (pausada, com o KV na CPU). O atraso virtual é

```
VLT(r) = α · ReLU(t − t_último_token − β_B · S_TBT)   rotativa
         ReLU(t − a_r − β_F · S_TTFT)                 em espera
         −(t − t_início_execução)                     em execução
```

O LVF, a cada iteração: (1) se tudo cabe na HBM, FCFS; (2) ordena todas as requisições por VLT decrescente; (3) a partir do topo, prioriza as de VLT ≥ 0 até gastar a memória livre mais o orçamento de transferência `B_xfer`; (4) a partir do fim, preempta as de VLT < 0 (as que estão rodando há mais tempo) até liberar o que falta. Parâmetros do artigo: `α = 3`, `β_B = 0`, `β_F = 0,5`. O ganho medido (até +74,7 pontos de TTFT dentro do SLO) depende de rotacionar KV a ~200 GB/s pelo NVLink-C2C do GH200. (No artigo, a definição troca os índices de `S_B` e `S_F`; o uso e a seção 5.3.2 mostram que `F` é o primeiro token e `B` o tempo entre tokens.)

**Mapeamento para o Prism.**

| SuperInfer | Prism, nível de modelo (controlador global) |
| --- | --- |
| requisição | modelo `m` |
| em espera | modelo inativo com fila: `VLT_m = max_{r∈Q_m} ReLU(t − a_r − β_F·S_m)` |
| rotativa (KV na CPU) | modelo despejado com requisições interrompidas (preemptadas e devolvidas ao Redis, P6): `VLT_m = α·ReLU(t − t_preempção − β_B·S_TPOT)` |
| em execução | modelo ativo: `VLT_m = −(t − t_ativação)`; variante: o maior atraso da fila do próprio modelo, se positivo |
| HBM livre | memória livre da GPU menos ativações em andamento (R2.1) |
| `B_xfer` | orçamento de ativações por ciclo (o model service carrega um modelo por vez) |
| verificação de disputa | se todos os modelos com fila cabem, ativar sem despejar (comportamento atual) |

**Por que interessa.** A política `fair` que já existe (`simple_global.py:425`) é um LVF rudimentar: quando um modelo espera `PRISM_FAIR_QUANTUM` s, sai o ativo há mais tempo. O VLT troca o quantum fixo pelo atraso relativo ao SLO de cada requisição e acrescenta o peso das requisições interrompidas (`α`), o orçamento de rotação e a verificação de disputa. Comparado com A2/A3, o VLT **olha para trás** (atraso já acumulado) e **não precisa de estimadores** (`Ĉ_at`, `p̂_r`, `λ̂_m`). A comparação "atraso primeiro" (A9) × "folga primeiro" (A2) é uma pergunta em si: A9 tende a minimizar o pior atraso (pior modelo, fome; ex.: os 342 s de espera do `model_6` com só a folga de KV, F0.3); A2.1 descarta de propósito as filas já perdidas para salvar as viáveis (observação 4.0).

**Riscos.** (i) No Prism uma rotação custa uma ativação de 1,5 s a 21 s, contra milissegundos no GH200; sem histerese, o LVF pode trocar em ciclo (por isso A1.3 e o orçamento). (ii) A vítima é escolhida só pelo tempo de residência, sem olhar quanto o modelo está servindo (o critério de A0.3). (iii) Com o SLO de 1 s, quase todo modelo inativo com fila tem VLT > 0 logo depois da chegada, então o VLT vira "o mais antigo primeiro" entre modelos; o `β_F` passa a ser o parâmetro que decide.

**Variantes.**
- **A9.1 LVF entre modelos (fiel ao artigo).** Mapeamento da tabela acima; vítima = modelo ativo há mais tempo (VLT mais negativo), só se tiver residência ≥ `T_min` (A1.3); no máximo `B_rot` ativações iniciadas por ciclo.
- **A9.2 LVF com custo de ativação.** Igual à A9.1, mas um modelo inativo só entra se `VLT_m` superar o custo da troca (`Ĉ_at(m)` mais o tempo para as vítimas terminarem o lote em execução, ou zero com preempção; D30) por uma margem; a vítima é escolhida pelo menor (VLT da vítima) × GB liberado. Usa `Ĉ_at` da F2.
- **A9.3 LVF entre requisições dentro do worker (opcional).** Troca a fila FCFS do `scheduler.py` por LVF com preempção proativa por recomputação. Só se A9.1/A9.2 mostrarem ganho e se a carga tiver sobrecarga de computação (C4, C5), porque o SGLang 0.3.4 não troca KV para a CPU.
- Não incluímos o LVF na fila do GPU scheduler (`request_queue.py`): com SLO único, ordenar por VLT é FCFS; com classes, é EDF sobre `a_r + β_F·S`, que a prioridade atual já aproxima.

**Implementação.** `PRISM_EVICTION=lvf` (padrão continua `idle`), com `PRISM_LVF_ALPHA` (3), `PRISM_LVF_BETA_F` (0,5), `PRISM_LVF_BETA_B` (0), `PRISM_LVF_BUDGET` (1 ativação por ciclo) e `PRISM_LVF_COST_AWARE` (0 = A9.1, 1 = A9.2). A decisão é uma função pura `lvf_select(estado, agora, parâmetros) → (vítimas, ativações)` com testes em `tests/policy/` (seção 0.6), incluindo: tudo cabe (nenhuma rotação), fome de C1, troca de grupo de C2, impasse de C3, modelo rotativo com `α` alto vencendo um em espera, orçamento esgotado e vítima com residência abaixo de `T_min`. Os dados por requisição já existem no controlador (`model_queue_tracker.py`: `arrival_time`, `start_running_time`, `preempted_time`).

**Avaliação (F6.10–F6.12).** Na campanha de ablação da F6 (mesmas cargas, níveis de SLO e repetições), contra `fair` (o antecessor de quantum fixo), A0.1, a melhor linha de base da F5 e A2/A4. Sensibilidade: `α ∈ {1, 3}`, `β_F ∈ {0; 0,5; 2}`, `β_B ∈ {−0,5; 0}`, `B_rot ∈ {1, 2}`. Métricas nas três vistas da seção 7.1, mais o pior modelo e o número de trocas. **Critério de interesse:** A9 entra na política candidata (A4) só se ganhar da melhor linha de base com IC 95% pareado que exclui 0 em pelo menos uma vista sem piorar outra; caso contrário, o resultado negativo é reportado e explicado pelos logs de decisão.

### A10. Troca por valor: throughput, prazo e tamanho da fila (F6, D32)

**Motivação.** As políticas da F6a olharam só para o prazo, e a troca por throughput/GB (A0.3) só para o throughput. Na F6a, a EDF tirou modelos ocupados porque não pesava o que eles serviam, e a A0.3 não sabe se alguma requisição ainda pode ser salva. A A10 junta os dois critérios e acrescenta o tamanho da fila, que mede a pressão acumulada de cada modelo.

**Retrato por modelo** (o mesmo das funções de `deadline.py`, mais o throughput servido que a A0.3 já mede):
- `V_m`: requisições viáveis na fila (folga ≥ 0, com o custo real da troca medido na F5.0, não só `Ĉ_at`);
- `Q_m`: tamanho da fila (requisições e tokens de prompt + saída pedida);
- `X_m`: throughput servido nos últimos 30 s (tokens/s), por GB ocupado;
- `R_m`: requisições em execução e o tempo restante delas (tokens restantes × TPOT).

**Variantes.**
- **A10.1 Filtro por prazo, escolha por throughput.** Só entra quem tem `V_m > 0`. Entre esses, a escolha e as vítimas seguem a A0.3 (demanda × throughput por GB), com a vítima precisando ter `X_j` menor que a demanda de quem entra pela margem `PRISM_SWAP_MARGIN`.
- **A10.2 Pontuação ponderada.** Valor de entrar `G_i = w_V·V_i + w_Q·Q_i/Q̄`, valor de ficar `L_j = w_X·X_j/X̄ + w_R·R_j + w_V·V_j`, com termos normalizados pela média dos modelos; troca se `G_i − Σ L_j > θ`. Pesos por variável de ambiente; sensibilidade na F6.5.
- **A10.3 Pressão de fila com prazo.** Como a A10.2, mas `Q` entra como fila ponderada pela folga (`Σ_r 1/max(folga_r, ε)`), para que uma fila grande e urgente pese mais que uma fila grande e folgada.

**Relação com A3 e A4.** A A3 é o caso em que só o prazo conta na perda; a A10 acrescenta o throughput e a fila. Se a A10.2 com `w_X = w_Q = 0` se reduzir à A3.1, as duas compartilham o código (verificar na implementação).

**Implementação.** `PRISM_EVICTION=value`, `PRISM_VALUE_VARIANT` (1, 2, 3) e os pesos; função pura `value_select(retrato, params)` em `policy/deadline.py` ou num módulo novo, com testes em `tests/policy/` (fome do C1, vítima ocupada × ociosa, fila grande e folgada × pequena e urgente, tudo cabe).

**Avaliação.** Na campanha da F6, contra a melhor ociosidade, a A0.3 e a A0.3p, a A3 e a A4, nas três vistas, no TTFT p50/p90 e na cauda de espera (objetivo da seção 7).

### A11. Cancelar a desativação de um modelo que voltou a ser pedido (opção a avaliar, D45)

**Situação.** Sem preempção, a vítima de uma troca leva ~20 s (p50; p90 47 s, 8B) para terminar o lote e sair (F5.0a). Nesse intervalo ela pode receber requisições de novo e a política a reativa noutro worker: os pesos são carregados outra vez enquanto a cópia antiga ainda ocupa a GPU. Nos logs brutos isso aconteceu em 3,8–6,9% das desativações (F4 820/11 824, F5 46/968, triagem da F6a 181/4 796; linha `Ignoring the late deactivation` do GPU scheduler).

**Hoje (mantido pela D45).** O controlador marca o modelo `DEACTIVATING` e a política o trata como inativo: pode reativá-lo noutro worker. A D45 só tornou esse estado explícito, sem mudar o comportamento.

**Opção.** Em vez de reativar noutro worker, cancelar a desativação em curso: a vítima fica com os pesos e o lote, sem recarga (economiza `Ĉ_at`). Custos: a memória não é liberada, então a troca que a despejou se desfaz e o modelo para quem ela saiu não entra; e o engine precisa de suporte (durante a desativação o worker fica em `_run_to_completion_normal` sem ler mensagens; seria preciso checar um pedido de cancelamento entre lotes e pular a liberação dos pesos).

**Avaliar** como opção de política (ligável por variável de ambiente), pareada com a mesma política sem ela, nas cargas em que a reativação de vítimas é frequente; métricas: recargas evitadas, TTFT p50/p90 do modelo reativado e do que esperava a memória.

---

## 5. Cargas

Toda carga entra em `reports/registro/cargas.md` com: id, origem, licença, transformação aplicada (com o script e os parâmetros), estatísticas resultantes (taxa por modelo, CV das chegadas, distribuição de tamanhos de prompt e saída, popularidade) e hash dos arquivos gerados. O gerador continua sendo `overload_load.py` (chegadas abertas, saída de tamanho exato, prazo extra de 300 s), estendido para ler traces e classes de SLO.

### 5.1 Definições de intensidade

- **Sobrecarga de memória:** `ρ_mem = (Σ_{m com demanda} W_m) / M`. `ρ_mem > 1` significa que os modelos com demanda não cabem juntos.
- **Sobrecarga de computação:** taxa oferecida / vazão máxima medida da GPU para o mesmo conjunto de modelos residentes.
- Toda varredura especifica os dois. Os cenários de sobrecarga de memória devem ter `ρ_mem` claramente acima de 1 (ex.: 1,5, 2, 3).

### 5.2 Cargas sintéticas

| Id | Status | Construção | O que estressa |
| --- | --- | --- | --- |
| C1 `ovl_mem` | existe | 10 modelos, 6 cabem, tráfego contínuo em todos | fome sem ociosidade |
| C2 `ovl_phases` | existe | 2 grupos de 5 alternando a cada 150 s | troca de grupo |
| C3 `ovl_mix` | existe | 8×8B + 2×3B | tamanhos diferentes, impasse |
| C4 `ovl_kv` | existe | 4 modelos ativos, prompts e saídas longos | crescimento de KV |
| C5 `ovl_compute` | existe | 2 modelos, 20–100 req/s | computação |
| C6 `zipf_drift` | nova | N modelos com popularidade Zipf(α); a ordem dos ranks gira gradualmente (ex.: troca de um par de ranks a cada T s) | mudança gradual de popularidade, residência preditiva |
| C7 `bursty` | nova | chegadas por processo modulado (MMPP de 2 estados ou Gamma com CV 2–4) por modelo, rajadas independentes | rajadas assíncronas como as do artigo do Prism |
| C8 `diurnal` | nova | taxa total segue uma rampa senoidal comprimida (ex.: 1 "dia" = 20 min), popularidade fixa | entrada e saída gradual da sobrecarga |
| C9 `slo_classes` | nova | mistura de requisições interativas e de lote (proporção como fator), sobre C1 e C6 | A7 e admissão |
| C10 `sizes_mix` | nova | modelos de 3B, 8B, 14B e ~32B (verificar suporte no SGLang 0.3.4 e memória: um 32B em BF16 ocupa ~64 GB) | heterogeneidade de `W_m` e `C_at` |
| C11 `slo_sweep` | nova | C1, C6 e C7 sob as famílias de SLO da seção 5.4 (escalonado pela latência isolada e relativo ao custo de ativação) | observação 4.0 e sensibilidade ao SLO |

Requisitos para todas as sintéticas: semente fixa e registrada; tamanhos de prompt e saída amostrados de uma distribuição registrada (padrão: a distribuição do trace do Prism ou de um conjunto público de conversas, para não inventar tamanhos); duração e aquecimento declarados.

### 5.3 Traces reais

| Id | Fonte | Uso | Observações para o agente |
| --- | --- | --- | --- |
| T1 | Trace do benchmark do Prism (já usado em `ovl_trace_big`) | principal, desde já | já mapeado: um adaptador por modelo |
| T2 | LMSYS-Chat-1M (conversas com o campo do modelo usado) | popularidade real entre dezenas de modelos e tamanhos de prompt reais | verificar licença e termos de uso; não há tempos de chegada reais, então chegadas são sintéticas e a popularidade é real |
| T3 | Azure Functions traces (usados em trabalhos de serving multi-modelo como AlpaServe) | padrões de chegada reais, por função, mapeados para modelos | mapeamento função → modelo por rank de popularidade; verificar licença |
| T4 | Azure LLM inference traces (2023/2024) | tempos de chegada e tamanhos reais de requisições de LLM | traces de serviço único: usar para tamanhos e chegadas, dividir entre modelos por uma regra registrada |
| T5 | BurstGPT | rajadas reais de uso de LLM | verificar quantos modelos distintos aparecem e a licença |
| T6 | Outros (ex.: ServeGen, Mooncake) | futuros | só incluir após verificar disponibilidade pública e licença |

**Protocolo de adaptação de trace (obrigatório para T2–T6):**
1. Baixar e registrar origem, versão, data, licença e hash.
2. Extrair por "entidade" (modelo ou função): tempos de chegada, tamanhos de prompt e saída.
3. Mapear entidades para os modelos do experimento por rank de popularidade (regra registrada).
4. Escalar o tempo para atingir o `ρ_mem` e a carga de computação alvo, preservando a forma (CV das chegadas, correlação entre entidades). Registrar o fator de escala.
5. Truncar prompts e saídas a limites suportados, registrando a fração truncada.
6. Gerar estatísticas antes e depois da transformação e anexá-las ao catálogo. A transformação não pode mudar o CV das chegadas em mais de 10% nem a ordem de popularidade.

---

### 5.4 SLOs variáveis

O SLO fixo usado até aqui (TTFT < 1 s e TPOT < 100 ms para todos os modelos e requisições) tem três problemas: trata igual um modelo de 3B e um de 32B, cujas latências mínimas são muito diferentes; ignora que o TTFT cresce com o tamanho do prompt; e dá um único ponto de comparação, quando a ordem entre políticas pode mudar conforme o SLO aperta ou afrouxa. A partir de F2, **o SLO é sempre um fator experimental, definido por uma família e um nível**, e o resultado principal de cada comparação é uma curva, não um número.

**Latência de referência (medida em F2).** Para cada modelo `m`, sozinho na GPU, residente e com carga baixa:
- `TTFT_iso(m, L)`: TTFT em função do tamanho do prompt `L`, ajustado como `α_m + β_m·L`;
- `TPOT_iso(m)`: TPOT com lote pequeno (ex.: 1 e 8 requisições), registrando os dois.

**Famílias de SLO.**

| Id | Família | TTFT de `r` | TPOT de `r` | Para que serve |
| --- | --- | --- | --- | --- |
| S1 | Absoluto fixo | 1 s | 100 ms | comparabilidade com os resultados de outubro/2026 |
| S2 | Escalonado pela latência isolada | `k_T · TTFT_iso(m, L_r)` | `k_D · TPOT_iso(m)` | SLO justo entre tamanhos de modelo e de prompt; é a família principal |
| S3 | Relativo ao custo de ativação | `k_A · Ĉ_at(m)` | `k_D · TPOT_iso(m)` | observação 4.0: quando a ativação sob demanda passa a caber no prazo |
| S4 | Classes por requisição | interativa: S2 com `k_T` baixo; lote: S2 com `k_T` alto ou absoluto folgado | interativa: `k_D` baixo; lote: sem limite de TPOT | carga C9 e política A7 |
| S6 | Relativo ao tempo de rotação (D32) | `k_R · Ĉ_rot(m)`, em que `Ĉ_rot` é o tempo real de uma troca (decisão → modelo que entra pronto, mediana medida na F5.0 por tamanho de modelo) | `k_D` × base do S2 | prazos que cabem numa troca real: em sobrecarga, reagir à chegada só serve se o prazo cobre a rotação |
| S5 | Heterogêneo por modelo | `k_T` sorteado ou definido por modelo (ex.: modelos pequenos estritos, grandes folgados) | idem com `k_D` | provedores com SLOs diferentes por modelo |

**Revisão depois do gate da F2 (D20–D23):**
- **Base do S2:** não é mais `TTFT_iso`/`TPOT_iso`. É a carga do próprio modelo em GPU dedicada, como no artigo do Prism, juntando os modelos idênticos da carga: S2 sobre o P95 e S2M sobre a mediana (`reports/registro/latencia_ref.md`). O S2 não depende mais de `L_r`.
- **Níveis aprovados:**
  - S2: `k_T ∈ {2, 5, 10, 25}`, `k_D ∈ {1,5; 2; 3; 5}`;
  - S2M: `k_T ∈ {5, 10, 25, 50}`, `k_D ∈ {3, 5, 10, 20}`;
  - S3: `k_A ∈ {2, 5, 10, 25, 50}`.
- As tabelas e os níveis iniciais abaixo ficam como registro do plano original.

**SLOs maiores para as políticas por prazo (D32).** Estamos em sobrecarga, e na F6a os prazos de 0,6–1,75 s ficaram abaixo até da ativação. A partir da F6, as execuções das políticas que usam o prazo rodam com níveis **iguais ou acima do tempo de rotação**:
- proposta (confirmar com o Gabriel depois da F5.0): S3 `k_A` = 5 (continuidade com a F6a) e S6 `k_R` ∈ {1, 2};
- o S2 `k_T` = 10 continua nas métricas (reavaliação depois da execução, sem custo) como referência estrita, não como nível de execução das políticas por prazo.

**Níveis iniciais** (ajustáveis no gate de F2, com o motivo registrado): `k_T ∈ {2, 5, 10, 25, 50}`, `k_D ∈ {1,5; 2; 3; 5}`, `k_A ∈ {0,5; 1; 2; 5}`. TTFT e TPOT variam **separadamente** (uma grade, não uma diagonal), porque estressam mecanismos diferentes: o TTFT depende de residência e fila, o TPOT depende da pressão de KV e da partilha de computação entre modelos residentes.

**Regra de economia de execuções (importante).**
- Políticas que **não usam o SLO** para decidir (A0.1–A0.4, A1) produzem a mesma execução para qualquer SLO. Para elas, a curva inteira é calculada **depois** da execução, reavaliando os mesmos registros de requisição com cada família e nível. Uma execução, todas as curvas.
- Políticas que **usam o SLO** (A0.5, A2–A7) mudam de comportamento com ele. Cada nível de SLO é uma execução separada. Para conter o custo, elas rodam num subconjunto de níveis (ex.: 3 por família), escolhido a partir das curvas das linhas de base: um nível em que as linhas de base atendem bem (> 90%), um no meio da queda e um em que quase tudo viola.
- O script de análise recebe a definição de SLO como parâmetro e nunca a lê de uma constante. A definição usada em cada número reportado aparece na tabela ou figura.

**Como reportar.**
- Curva de **fração dentro do SLO × nível** (`k_T`, `k_D` ou `k_A`), por política e por carga, como nos trabalhos de serving multi-modelo que usam "SLO scale".
- **SLO mínimo atingível:** o menor nível em que a política atende 90% (e 99%) das requisições. É o resumo de uma curva num número, bom para tabelas.
- Toda curva e todo resumo aparecem nas **três vistas** definidas na seção 7.1 (SLO combinado, só TTFT, só TPOT), com a decomposição das violações.
- Sempre com a separação entre violações evitáveis e inevitáveis (seção 7), que depende do nível de SLO.

## 6. Fases em detalhe

### F0 — Reconhecimento e reprodução da linha de base

**Tarefas**
- F0.1 Inventariar o repositório: políticas existentes, variáveis `PRISM_*` e seus padrões, scripts de execução e análise, formato dos logs. Produzir `reports/fases/F00_inventario.md` com a árvore relevante e o fluxo de uma execução de ponta a ponta.
- F0.2 Verificar se a arbitragem por folga (Moore-Hodgson, fila compartilhada por GPU) do artigo existe no código aberto e se está ativa no caminho usado. Responder com trechos de código e caminhos.
- F0.3 Verificar o estado das pendências da seção 1 (T1, folga de KV no `ovl_mix`, 25 perdas, K1) a partir dos relatórios e de `erros.md`.
- F0.4 Reproduzir duas configurações de referência dos relatórios de 28/10 (sugestão: `ovl_phases` com A0.1 e A0.2; `ovl_trace_big` com A0.3), 3 repetições cada.

**Critérios de aceitação**
- Inventário completo e revisado.
- Resposta documentada sobre a arbitragem por folga.
- Reprodução dentro da variação entre repetições dos relatórios originais (mesma ordem entre políticas, métricas principais dentro do intervalo observado). Se não reproduzir, investigar antes de qualquer outra coisa.

**Gate [HUMANO].**

### F1 — Fechar a robustez restante

**Tarefas**
- F1.1 T1 com 14 modelos: reproduzir o travamento com a menor configuração possível, coletar `py-spy dump` de todos os processos durante o travamento, identificar a causa, corrigir ou documentar como consequência da política (a ser resolvida em F4).
- F1.2 25 requisições perdidas (preempção sem drenagem, trace): reproduzir com a mesma semente; instrumentar o caminho de devolução ao Redis (log de cada retirada e de cada reinserção com id); identificar a causa e corrigir.
- F1.3 Concluir o teste da folga de KV no `ovl_mix` (A0.4) com 5 repetições.
- F1.4 K1: medir de novo a frequência com nó saudável e com nó degradado; decidir (com registro) se o árbitro entre processos fica desligado. Não é bloqueante se a frequência com nó saudável for zero.
- F1.7 P11 (incluída no gate da F0, `decisoes.md` D3): desativação de ~30 s sem trabalho pendente em `WorkerPoolModelRunner.deactivate()`; identificar a causa e corrigir ou documentar.

**Critérios de aceitação**
- Causa de cada pendência identificada e registrada em `erros.md`.
- Zero perdas não explicadas em 10 repetições da configuração que antes perdia requisições.
- Nenhuma regressão: a campanha de F0.4 repetida após as correções continua dentro da referência.

**Gate automático** (se algum item não fechar, o agente para e reporta).

### F2 — Instrumentação, validador e estimadores

**Tarefas**
- F2.1 Logs estruturados (JSON por linha) do controlador: a cada ciclo, o retrato de estado usado na decisão (memória, modelos e estados, filas, folgas quando houver) e as ações com o motivo. Logs de requisição com prazo, classe e estado final.
- F2.2 Implementar `validate_run.py` com V1–V15 e `validate_campaign.py` com C-V1–C-V3. Rodar retroativamente sobre os dados de 28/10 e conferir que as execuções com falhas conhecidas da base são marcadas como inválidas com o motivo certo (teste do validador).
- F2.3 Estimador de custo de ativação `Ĉ_at(m)`: medir em função do tamanho do modelo e da memória livre (incluindo ativações concorrentes); modelo simples (linear em GB + constante) com erro registrado.
- F2.4 Estimador de prefill `p̂_r`: ms por token por modelo, em função do tamanho do lote; erro registrado.
- F2.5 Estimador de fila `q̂_r` e de taxa `λ̂_m` (EWMA com duas janelas). Avaliar o erro de previsão de chegadas no horizonte `H` nos traces.
- F2.6 Confirmar ou refutar a observação 4.0 com os valores medidos de `Ĉ_at`.
- F2.10 Medir a latência de referência de cada modelo usado nas cargas (`TTFT_iso(m, L)` e `TPOT_iso(m)`, seção 5.4), com 5 repetições, e registrar os ajustes e os erros.
- F2.11 Reescrever o cálculo de métricas para receber a definição de SLO (família e nível) como parâmetro e produzir sempre as três vistas da seção 7.1 e a decomposição das violações; recalcular os resultados de 28/10 com S1 e conferir que os números batem com os relatórios (teste de regressão da análise).
- F2.12 Gerar as curvas S2 (grade `k_T` × `k_D`) e S3 retroativamente para os dados de 28/10 das políticas que não usam SLO, como primeira visão de quanto a ordem entre políticas depende do SLO.
- F2.7 Criar o registro de execuções, de decisões e de cargas (seção 0.5).

**Critérios de aceitação**
- Validador acerta 100% das falhas conhecidas nos dados antigos (nenhuma execução com falha conhecida passa como válida) e não acusa falha nas execuções sabidamente limpas.
- Erro mediano de `Ĉ_at` ≤ 20% e de `p̂` ≤ 20% (limites ajustáveis com justificativa registrada).
- Sobrecusto da instrumentação ≤ 2% na vazão (medido com e sem logs).

**Gate [HUMANO]** (o Gabriel decide, a partir da observação 4.0 e das curvas de F2.12: a família principal de SLO, os níveis de `k_T`, `k_D` e `k_A`, e os SLOs das classes interativa e de lote).

### F6a — Primeira rodada das políticas por prazo (A2.1 e A9.1), adiantada (D24)

**Objetivo:** responder cedo à pergunta central da F6, com as duas políticas mais simples e só as cargas atuais: escolher quem entra na GPU pela folga, ou pelo atraso acumulado, melhora o SLO em relação às linhas de base?
- **A2.1** é "folga primeiro" (EDF entre modelos).
- **A9.1** é "atraso primeiro" (Virtual Lag Time do SuperInfer). Não usa estimadores.

**Escopo (decidido com o Gabriel em 2026-11-04):**
- **Entram:**
  - A2.1 e A9.1;
  - A1.1 (reserva mínima de KV) e A1.3 (residência mínima `T_min`), como opções que as duas usam;
  - o ciclo do controlador como fator: 5 s (padrão) e 1 s (`PRISM_SCHEDULE_INTERVAL`).
- **Ficam fora:**
  - A1.2 (detector de impasse), que fica para a F4;
  - A2.2, A2.3, A3, A4 e A9.2, que ficam para a F6;
  - A5 e A6, que ficam para a F7;
  - cargas novas, que ficam para a F3.

**Tarefas**
- **F6a.1 Prazo por requisição no gerador.**
  - `overload_load.py --slo-spec <família:nível>` calcula o `slo_ttft`/`slo_tpot` de cada requisição pela mesma regra do `slo_metrics.py`, com as bases de `latencia_ded.json`, e envia o prazo ao servidor;
  - as métricas usam a mesma especificação;
  - o padrão (`--slo-ttft 1`) não muda.
- **F6a.2 Funções puras de decisão.**
  - ficam em `python/sglang/multi_model/scheduling/policy/deadline.py`, no formato `edf_select(...)` e `lvf_select(...)` → `(vítimas, ativações)`;
  - o `simple_global.py` monta o retrato do estado e aplica as ações, o que adianta a refatoração pendente da F0;
  - variáveis:
    - `PRISM_EVICTION=edf | lvf`, com o padrão `idle` inalterado;
    - `PRISM_EDF_FLOOR`, o piso de folga;
    - `PRISM_LVF_ALPHA` (3), `PRISM_LVF_BETA_F` (0,5), `PRISM_LVF_BETA_B` (0) e `PRISM_LVF_BUDGET` (1);
    - `PRISM_KV_RESERVE_REQS` (`b` da A1.1; 0 = desligado);
    - `PRISM_MIN_RESIDENCY` (`T_min` da A1.3; 0 = desligado);
  - os parâmetros escolhidos vão para `decisoes.md`.
- **F6a.3 Testes unitários** em `tests/policy/` (seção 0.6), cobrindo:
  - tudo cabe, então nenhuma troca;
  - fome do C1, troca de grupo do C2 e impasse do C3;
  - fila inviável ignorada pela A2.1;
  - modelo rotativo com `α` alto vencendo um em espera;
  - orçamento de ativações esgotado;
  - vítima com residência abaixo de `T_min`;
  - memória exatamente no limite.
- **F6a.4 Logs:** toda decisão das duas políticas vai para o log de decisões da F2, com a folga ou o VLT de cada modelo.
- **F6a.5 Smoke test:** 1 nível de A2.1 e 1 de A9.1 no C1, validados pelo validador.
- **F6a.6 Triagem** (seção 0.9: só cargas com disputa por residência). Ver a tabela abaixo.
- **F6a.7 Confirmação**, só para o que passar na triagem:
  - 5 repetições pareadas na mesma janela, contra A0.1 e a melhor linha de base da triagem;
  - mais o C2 como controle, para verificar que nada piora num caso que o limiar curto já resolve.
- **F6a.8 Relatório** `reports/fases/F06a_prazo_primeira_rodada.md`.

**Cargas da triagem e por quê** (ativações por execução em outubro, com A0.1 / A0.3):

| Carga | Entra? | Motivo |
| --- | --- | --- |
| C1 `ovl_mem` 0,2 | sim | É fome sem ociosidade (4 / 38 ativações). O limiar nunca despeja, e rodar por throughput piora de 64% para 24%. Pergunta: uma rotação guiada por prazo é melhor que não rodar? |
| T1 `ovl_trace_big` ts1 | sim | É o trace real do Prism, com popularidade desigual (12 / 65 ativações). As linhas de base empatam em 78–80%, e é aqui que "folga primeiro" × "atraso primeiro" deve se diferenciar. |
| C2 `ovl_phases` 0,5 | só na confirmação | Problema previsível, já resolvido pelo limiar curto (87%). Serve de controle de não piora. |
| C3 `ovl_mix` | não | Impasse estrutural: quem resolve é a A1.1, não a política de prazo. Misturaria os efeitos e fica para a F4. |
| C4 `ovl_kv`, C5 `ovl_compute` | não | Zero ativações: todos os modelos cabem, e uma política de residência não tem o que decidir. |

**Matriz da triagem:** C1 e T1, 2 repetições, no máximo 3 jobs simultâneos.

| Grupo | Configurações | Níveis de SLO | Níveis de carga |
| --- | --- | --- | --- |
| Linhas de base, rodadas de novo para parear na mesma janela | A0.1, A0.2, A0.3, `fair` | uma execução vale para todas as famílias | 4 × 2 cargas × 2 rep. = 16 |
| Novas | A2.1, A9.1 | S2 `k_T` = 10 (estrito), S2 `k_T` = 25 (folgado), S3 `k_A` = 5. O `k_D` só entra nas métricas, porque as políticas decidem pelo TTFT | 2 × 3 × 2 × 2 = 24 |
| Ciclo de 1 s | A2.1, A9.1 no melhor nível de SLO de cada uma | — | 2 × 2 × 2 = 8 |

São 48 níveis no total.
- Os prazos de TTFT do 8B no S2 com `k_T = 10` (0,6–1,2 s) ficam abaixo de `Ĉ_at` (~1,4 s). No S2 com `k_T = 25` (1,6–3,1 s) e no S3 com `k_A = 5`, ficam acima. Assim a triagem cobre os dois lados da observação 4.0.
- **Sinal na triagem:** diferença maior que ~8 pontos na vista combinada ou na só TTFT, em relação à melhor linha de base da mesma campanha. Esse é o tamanho da deriva entre períodos.
- **Regressão:** o A0.1 da triagem é comparado com 28/10 e com a F1, dentro dessa deriva. Com o padrão `idle`, o código novo não é executado.

**Critérios de aceitação**
- Testes unitários passando.
- Smoke test e níveis da triagem válidos pelo validador.
- Resultados nas três vistas da seção 7.1, com a decomposição das violações e a separação evitável × inevitável.
- Toda diferença grande explicada pelos logs de decisão.
- Na confirmação, o IC 95% pareado por semente, como na F6.

**Gate [HUMANO]** depois da triagem (o Gabriel decide o que vai para a confirmação) e depois da confirmação.

### F3 — Catálogo de cargas

**Tarefas**
- F3.1 Estender `overload_load.py`: leitura de trace, classes de SLO por requisição, recusas como estado final, sementes.
- F3.2 Implementar C6–C11 (seção 5.2).
- F3.3 Adaptar T2–T5 pelo protocolo da seção 5.3 (começar por T2 e T3; T4 e T5 se houver tempo).
- F3.4 Para cada carga: execução curta de verificação ("dry run") com A0.1, só para validar o gerador (V11, V8) e a evidência de sobrecarga (V12).

**Critérios de aceitação**
- Cada carga com entrada completa em `cargas.md`.
- Estatísticas geradas batem com a especificação (taxas ±5%, CV ±10%, popularidade preservada).
- Dry runs válidos pelo validador.

**Gate [HUMANO]** (o Gabriel aprova o conjunto de cargas da campanha).

### F4 — Restrições estruturais (A1)

**Tarefas:** implementar A1.1–A1.3 com testes unitários; campanha nos cenários com impasse (C3, C1 com 8 e 14 modelos) e de controle (C2, T1), políticas A0.1 e A0.3 com e sem A1, 5 repetições.

**Critérios de aceitação:** os da seção A1; escolha de `b`, `Δ_imp` e `T_min` registrada.

**Gate automático.**

### F5 — Campanha de linhas de base sob a nova metodologia

As linhas de base não usam o SLO, então cada execução desta campanha gera as curvas completas de todas as famílias da seção 5.4 sem execuções extras. Os níveis escolhidos para as políticas por prazo (F6–F8) saem destas curvas.


**F5.0 Medições e métricas antes da campanha (D32; vinham da F6b, D31).** Só análise e código de métricas, sem job novo:
- **custo real da troca:** script `polyaxon/swap_cost.py` decompõe cada rotação (decisão → vítima fora → pedido de ativação → modelo pronto, mais a espera pelo ciclo e pela fila do carregador), ligando decisão e ativação pelo `decisions.jsonl`, nos dados da F6a e de 28/10. Resultado: `Ĉ_rot(m)` por tamanho de modelo, com e sem preempção, e a comparação com `ê_r`;
- **família S6** no `slo_metrics.py` e no `overload_load.py --slo-spec`;
- **violações inevitáveis pela ativação × pela rotação × evitáveis só com residência prévia** (seção 7) no `slo_metrics.py`;
- **ociosidade da GPU** (seção 7), a partir de `events.csv`, `requests.csv`, `gpu.csv` e `latencia_ded.json`;
- **tabelas com TTFT p50 e p90 e a cauda de espera** (p99, máximo, fração acima de 10× a mediana; não atendidas contadas até o fim do prazo extra) em `polyaxon/report_tables.py`;
- **log de decisões:** registrar quando a reserva de memória de um modelo vence sem ele ter sido ativado, e quem ficou com a memória (D30).

**Tarefas:** rodar A0.1–A0.5 (+A1), incluindo a A0.3 e a A0.3p e a melhor ociosidade de valor arbitrário (seção 0.10), em todas as cargas aprovadas em F3, com os níveis de `ρ_mem` definidos, 5 repetições; produzir as tabelas e figuras de referência (SLO total, TTFT p50/p90, violações evitáveis e inevitáveis pela classificação nova, ociosidade da GPU, pior espera por modelo, trocas, perdas). Esta campanha é a referência de C-V3 para as fases seguintes e o núcleo do artigo de resultados parciais.

**Critérios de aceitação:** C-V1–C-V2 satisfeitos; todas as execuções válidas ou explicadas; tabelas, curvas e decomposição de violações nas três vistas da seção 7.1.

**Gate [HUMANO].**

### F6 — Ativação e despejo por folga (A2, A3, A4) e por atraso virtual (A9)

**Prioridades (D31, D32, depois da F6a e da apresentação de 2026-11-05).** Cada item ataca uma lição da F6a:
1. **Custo real da troca** (medido na F5.0; reduções escolhidas no gate da F6.0: ativação no mesmo ciclo em que a memória é liberada, controlador orientado a evento, `ê_r` com o custo medido). Nenhum critério salva prazos de segundos se uma troca leva 13–17 s. É pré-requisito dos outros.
2. **A3, despejo por perda esperada** (começar pela A3.1, sem `λ̂`). Ataca a A2.1 com prazo folgado, que tirou modelos ocupados. A decisão "preemptar ou não" (D30) faz parte da troca. Expectativa declarada: com prazos curtos, tende a "não trocar" e empatar com as linhas de base de ociosidade; o ganho, se vier, vem dos prazos folgados.
3. **A10, throughput × prazo × fila** (seção A10, D32), em paralelo à A3, porque usa o mesmo retrato e ataca o mesmo defeito (vítimas ocupadas) pelo lado do throughput.
4. **A2.3, residência preditiva.** É a única resposta da observação 4.0 para prazos menores que a ativação. A barra é a A0.2 (o limiar curto já é um preditor rudimentar), não só a A0.1. O ganho esperado está em cargas com popularidade desigual e rajadas (T1, C6, C7), não no C1.
5. **A4, política combinada:** a A2.3 decide quem deveria estar residente, a A3 decide se a troca compensa, e o despejo por ociosidade continua como caminho barato.
6. **Prazos diferentes na mesma carga** (classes interativa + lote, A7/F8). Com um único tipo de prazo, ordenar por prazo tem pouco efeito; com classes, o lote dá a folga que a A2 precisa.
7. **A9.2, VLT com custo de troca:** prioridade menor, porque com custo de troca e vítima pelo valor fica parecida com a A3. Vale como variante depois do resultado da A3.

Fora de prioridade: o ciclo de 1 s (só com histerese maior) e a A5 (recusa conta como violação na métrica atual; ganho só indireto). O pior modelo (justiça) é acompanhado como **observação** nas métricas, não como objetivo das políticas (D31).

**Tarefas**
- (A2.1 e A9.1, com A1.1 e A1.3, vêm da F6a.)
- **F6.0 Repetição da triagem da F6a sem drenagem, com e sem preempção (D31, D32).** Primeira tarefa da F6.
  - **Perguntas:** sem a drenagem de 15 s (D30), EDF e VLT ainda perdem para as linhas de base? A preempção (a vítima sai na hora, e o que estava rodando recomeça depois) ajuda ou atrapalha as políticas por prazo?
  - **Hipóteses:** (H1) sem drenagem, a vítima sai em 5–10 s em vez de 22,7 s, e as violações evitáveis caem; (H2) a EDF com prazo folgado continua perdendo, porque não pesa a perda da vítima; (H3) com preempção, quem entra espera menos, mas o trabalho descartado cresce, e o saldo depende do prazo; (H4) a reserva de memória de 15 s às vezes vence antes de a vítima sair (log da F5.0).
  - **Cargas:** C1 `ovl_mem` 0,2 e T1 `ovl_trace_big` ts1, as mesmas da F6a, porque a mudança só aparece onde há rotação de modelos ocupados (seção 0.9).
  - **Matriz por job (17 níveis):**
    - linhas de base (seção 0.10): A0.1, A0.2, A0.3, A0.3p e `fair`;
    - A2.1 e A9.1 × 3 níveis de SLO (seção 5.4, "SLOs maiores": S3 `k_A` = 5 e S6 `k_R` ∈ {1, 2}) × {sem preempção, com preempção};
    - 2 cargas × 2 repetições = 4 jobs, no máximo 3 simultâneos;
    - sem ciclo de 1 s.
  - **Parâmetros:** os da F6a (D25), sem drenagem: `T_min` = 10 s, orçamento de 1 rotação, folga de 3 GB, A1.1 desligada.
  - **Comparação com a F6a:** só pela diferença pareada contra a melhor ociosidade do mesmo job (A0.1/A0.2 não mudaram), nunca pelos valores absolutos (regra 3; o braço com drenagem não existe mais). A A0.3 e o `fair` não se comparam com os da F6a.
  - **Métricas:** as da seção 7, com o objetivo da seção 7 (SLO, TTFT p50/p90 e cauda de espera), a classificação nova de violações, a ociosidade da GPU e, por rotação, decisão → vítima fora e decisão → modelo que entra pronto.
  - **Sinal e gate [HUMANO]:** > ~8 pontos sobre a melhor linha de base do mesmo job, ou melhora clara no TTFT p50/p90 sem piorar o SLO nem a cauda de espera. O Gabriel decide o que vai para a confirmação (5 repetições, IC 95%), quais reduções do custo da troca implementar e se a ordem das prioridades muda. Relatório `reports/fases/F06_0_repeticao_sem_drenagem.md`.
- F6.1 Implementar A2.1, A2.2, A2.3 com testes unitários (incluindo os estados de fome de C1 e de troca de grupo de C2).
- F6.2 Implementar A3.1–A3.3 com testes unitários (incluindo escolha de vítimas e preemptar × não preemptar, D30).
- F6.3 Implementar A4 combinando A1, A2 e A3.
- F6.4 Campanha de ablação: cada componente isolado e a combinação, contra A0.1 e a melhor linha de base de F5, nas cargas C1, C2, C3, C6, C7, C11 e T1; 5 repetições; para as políticas por prazo, uma execução por nível de SLO do subconjunto escolhido em F5 (seção 5.4).
- F6.5 Varredura de sensibilidade dos parâmetros principais (margem, `H`, `θ`, ciclo do controlador), registrando a escolha final e o motivo.
- F6.10–F6.12 A9 (seção A9): implementar A9.1 e A9.2 com testes; incluí-las na campanha de ablação e na varredura de sensibilidade; A9.3 só se A9.1/A9.2 mostrarem ganho.
- F6.13 A10 (seção A10): implementar A10.1–A10.3 com testes; incluí-las na campanha de ablação (F6.4) e na sensibilidade dos pesos (F6.5).

**Critérios de aceitação**
- Testes unitários passando.
- Linhas de base reproduzidas na mesma campanha (C-V3).
- Resultado reportado honestamente, inclusive se a política não ganhar: para cada carga, diferença em relação à melhor linha de base com intervalo de confiança de 95% (bootstrap pareado por semente), **nas três vistas da seção 7.1** (combinada, só TTFT, só TPOT) e com a decomposição das violações.
- Toda melhoria ou piora grande (> 2× numa métrica) tem explicação mecânica a partir dos logs de decisão.

**Gate [HUMANO].**

### F7 — Admissão e arbitragem com custo de ativação (A5, A6)

**Tarefas:** implementar A5.1–A5.3 e A6 (ou A0.5 primeiro, se não existir); medir recusas "erradas"; campanha em C1, C4, C5, C7, C9 e T1 com sobrecarga de computação e de memória.

**Critérios de aceitação:** V6 sempre OK; latência limitada sob sobrecarga de computação (cauda de TTFT e de TPOT das admitidas dentro de um múltiplo declarado do SLO); recusas "erradas" reportadas; resultados nas três vistas da seção 7.1.

**Gate [HUMANO].**

### F8 — Prazos ponderados e classes (A7)

**Tarefas:** classes e pesos em A2, A3 e A5; campanha em C9 e C6 com proporções de classe variadas; curvas (SLO agregado × pior modelo) para cada política.

**Critérios de aceitação:** curvas completas para todas as políticas, nas três vistas da seção 7.1 e por classe; escolha do objetivo padrão registrada em `decisoes.md` (decisão do Gabriel).

**Gate automático.**

### F9 — Oráculo offline (A8)

Pode começar logo após F3, em paralelo a F4–F8, porque só depende dos estimadores e das cargas.

**Tarefas:** formulação, validação por enumeração em instâncias minúsculas, solução nos traces curtos, política `oracle_replay`, execução real do plano ótimo.

**Critérios de aceitação:** ILP igual à enumeração nas instâncias minúsculas; gap e tempo de solução registrados; diferença entre valor do ILP e execução real do plano quantificada e explicada.

**Gate [HUMANO].**

### F10 — Campanha final

**Tarefas:** matriz completa (cargas aprovadas × políticas finais × níveis de sobrecarga × SLOs) com o mínimo de repetições; congelamento do commit e da imagem; tabelas e figuras finais geradas por script a partir de `execucoes.csv`; relatório com as conclusões, limitações e ameaças à validade.

**Critérios de aceitação:** C-V1–C-V3; zero execuções inválidas sem explicação; todas as figuras regeneráveis por um único comando; toda figura e tabela de resultado existe nas três vistas da seção 7.1.

**Gate [HUMANO].**

### F11 — Consolidação

Pacote de artefatos (código, configurações, cargas ou scripts de adaptação, dados agregados, scripts de figuras) e rascunhos das seções de avaliação dos artigos e da dissertação.

---

## 7. Métricas (definições únicas para todo o projeto)

- **Fração dentro do SLO:** requisições com TTFT ≤ SLO de TTFT da requisição **e** TPOT ≤ SLO de TPOT da requisição, sobre **todas as enviadas** (recusadas e expiradas contam como violações). Os dois SLOs vêm da família e do nível declarados (seção 5.4); todo número reportado diz qual foi.
- **SLO mínimo atingível:** menor nível de SLO em que a política atende 90% (e 99%) das requisições.

### 7.1 Três vistas obrigatórias: combinado, TTFT e TPOT

O SLO combinado (TTFT **e** TPOT) é a métrica principal, mas ele esconde qual das duas latências está falhando, e as políticas mexem em mecanismos diferentes: residência, ativação e fila afetam sobretudo o TTFT; pressão de KV, número de modelos residentes e partilha da GPU afetam sobretudo o TPOT. Uma política pode melhorar o combinado trocando um tipo de violação por outro. Por isso, **toda análise de política e de resultado é feita em três vistas**, sempre lado a lado:

| Vista | Fração reportada | Curva de SLO | Distribuições |
| --- | --- | --- | --- |
| Combinada | TTFT ≤ SLO_TTFT **e** TPOT ≤ SLO_TPOT | por nível da família (grade `k_T` × `k_D` quando aplicável) | — |
| Só TTFT | TTFT ≤ SLO_TTFT, ignorando o TPOT | por `k_T` (ou `k_A`) | CDF do TTFT e do TTFT normalizado (`TTFT / TTFT_iso`) por política; p50/p90/p99 |
| Só TPOT | TPOT ≤ SLO_TPOT, ignorando o TTFT | por `k_D` | CDF do TPOT e do TPOT normalizado (`TPOT / TPOT_iso`); p50/p90/p99 |

Regras:
- Nas vistas só TTFT e só TPOT, o denominador é o mesmo da combinada (todas as enviadas). Recusadas e expiradas contam como violação nas duas.
- **Decomposição das violações** em quatro grupos disjuntos para cada execução e política: atende ambos; viola só TTFT; viola só TPOT; viola ambos (incluindo recusadas e expiradas, reportadas à parte). A soma fecha em 100%.
- A separação entre violações evitáveis e inevitáveis (acima) vale para a vista só TTFT. Para o TPOT, reportar a fração das violações que ocorrem enquanto há troca de modelo em andamento ou memória livre abaixo de um limite, para ligar a violação a uma causa.
- Na vista só TPOT, considerar apenas requisições que geraram pelo menos dois tokens; as demais ficam fora do cálculo e o número delas é reportado.
- Toda comparação entre políticas (IC 95% pareado por semente) é feita nas três vistas e no TTFT p50/p90. Uma política é descrita como melhor quando melhora a vista combinada ou o TTFT p50/p90 sem piorar o outro nem a cauda de espera (objetivo da seção 7, D32/D33); se ela piorar uma das vistas separadas, isso é dito explicitamente, com o mecanismo encontrado nos logs de decisão.
- O "SLO mínimo atingível" é reportado nas três vistas.
- Por modelo: as três vistas também por modelo, para não esconder um modelo que perde TPOT enquanto os demais ganham TTFT.
- **Violações inevitáveis / evitáveis (revisto na D32, implementado na F5.0).** Para uma requisição que chegou a um modelo inativo:
  - **inevitável pela ativação:** havia memória livre para o modelo na chegada e `S_m < Ĉ_at(m)`;
  - **inevitável pela rotação:** não havia memória livre, então era preciso tirar alguém, e `S_m < Ĉ_rot(m)` (o tempo real de uma troca: espera pelo ciclo, saída da vítima, fila do carregador e ativação, medido na F5.0);
  - **evitável só com residência prévia:** `S_m` cobre a ativação ou a rotação, mas só se a decisão tivesse sido tomada antes da chegada (ex.: menor que `Ĉ_rot` + um ciclo);
  - **evitável:** os demais casos, mais toda violação de requisição que chegou a modelo ativo;
  - recusadas por A5.1 com `s_r(a_r) < −τ` sem nenhuma fila continuam como inevitáveis.
  A classificação antiga (só `Ĉ_at`) é reportada ao lado na F5, para continuidade com a F6a.
- **Ociosidade da GPU (D32, implementado na F5.0).** Mede quanto da GPU fica parado com modelos que não estão servindo, considerando os modelos em execução e a carga deles:
  - **residência ociosa com demanda pendente:** GB·s de modelos residentes sem requisição em execução nem na fila, nos instantes em que algum modelo inativo tem fila, dividido pelo total de GB·s da GPU. É memória que poderia estar com quem espera;
  - **ociosidade esperada pela carga:** para cada modelo, a carga oferecida `ρ_m = λ_m · E[tempo de serviço]` (taxa de chegada da carga × tempo de serviço medido na GPU dedicada, `latencia_ded.json`). Para o conjunto residente em cada instante, `1 − min(1, Σ ρ_m)` é a ociosidade que a própria carga impõe; a diferença para a ociosidade observada (utilização do `nvidia-smi`, `gpu.csv`) separa ociosidade da carga de ociosidade da política;
  - reportada por política e por carga, ao lado das trocas por minuto.
- **Objetivo (D32, D33): fração dentro do SLO, TTFT típico e nenhuma espera absurda.** As políticas são avaliadas por três critérios, sempre juntos:
  1. a fração dentro do SLO (três vistas);
  2. o **TTFT típico**: p50 e p90 das concluídas, com as não atendidas reportadas à parte;
  3. a **cauda de espera**: nenhuma requisição deve esperar absurdamente mais que as outras. Medida pelo TTFT p99, pelo TTFT máximo e pela fração de requisições com TTFT acima de 10× a mediana da própria execução, todas contando as não atendidas como espera até o fim do prazo extra; mais a pior espera pelo 1º token por modelo, que já existia.
  Uma política que melhora o critério 1 ou o 2 sem piorar os outros conta como ganho. **Uma melhora no SLO ou no TTFT típico conseguida à custa de uma cauda absurda (ex.: algumas requisições esperando centenas de segundos) não conta como ganho**, e isso é dito explicitamente. Se um critério melhora e outro piora, isso também é dito, com o mecanismo nos logs de decisão. Diferente da justiça entre modelos (pior modelo), que continua só como observação, o critério 3 é sobre requisições.
- **Goodput:** requisições dentro do SLO por segundo.
- **Pior espera pelo 1º token por modelo** e **fração dentro do SLO do pior modelo** (justiça).
- **Cauda:** p50, p90, p99 de TTFT das concluídas.
- **Trocas:** ativações e despejos por minuto; trabalho descartado em preempções (tokens).
- **Recusas:** taxa e recusas "erradas" (A5).
- **Perdas:** expiradas sem resposta (devem ser zero fora de recusas explícitas).
- **Estatística:** média e IC 95% por bootstrap sobre repetições; comparações pareadas por semente.

---

## 8. Pontos de decisão do Gabriel (o agente prepara as opções e para)

1. Após F0: confirmação de que a reprodução é aceitável.
2. Após F2: família principal de SLO; níveis de `k_T`, `k_D` e `k_A`; SLOs das classes interativa e de lote; limites de erro dos estimadores.
3. Após F3: conjunto de cargas da campanha.
4. Após F5: o que entra no artigo de resultados parciais.
5. Após F6 e F7: política candidata principal e parâmetros.
6. Após F8: objetivo padrão (agregado, max-min ou ponderado).
7. Após F9 e F10: conclusões e limitações a declarar.
