# Plano de trabalho para o agente: políticas de residência orientadas a prazos no Prism

Especificação de trabalho do agente no repositório de pesquisa do Prism (fork de `github.com/Multi-LLM/prism-research`,
branch `scheduling-research`): **o que fazer, em que ordem, como registrar e quando parar**. A lista marcável está em
`TODO.md`; as decisões, com o histórico de cada mudança deste plano, em `reports/registro/decisoes.md` (D1–D58).

Versão limpa de 2026-11-10 (D58): as fases concluídas aparecem como resumo do que foi feito e alcançado (o detalhe está
nos relatórios de fase), e o texto que decisões posteriores contrariaram saiu. A versão anterior está no histórico do
git.

---

## 0. Regras de operação do agente

Estas regras valem para todas as fases e têm prioridade sobre qualquer instrução de uma fase específica.

### 0.1 Portões (gates) entre fases

1. **Nenhuma fase começa antes de o gate da fase anterior estar marcado como APROVADO** no relatório da fase (`reports/fases/FXX_*.md`, seção "Decisão do gate").
2. Um gate só pode ser aprovado quando **todos** os critérios de aceitação da fase estão satisfeitos e documentados com evidência (caminho de arquivo, id de execução, tabela ou figura).
3. Gates marcados com **[HUMANO]** exigem aprovação explícita do Gabriel. O agente prepara o relatório, marca o gate como `AGUARDANDO REVISÃO` e **para**.
4. Se um critério falhar, o agente **não** avança e **não** relaxa o critério por conta própria. Ele abre uma investigação (seção 0.3) ou, se o critério parecer mal definido, registra a dúvida e para. Um critério vale igual para todas as cargas: em vez de exceção por cenário, declara-se a limitação.

### 0.2 Validação de cada execução

Toda execução (um nível de carga de um cenário com uma política e uma semente) passa pelo validador `polyaxon/validate_run.py` antes de entrar em qualquer agregado. O validador classifica a execução como `VALIDA`, `INVALIDA_INFRA` ou `INVALIDA_SISTEMA` (verificações na seção 3).

- **Execuções inválidas nunca entram em médias, tabelas ou figuras.** Elas ficam listadas no registro com o motivo.
- **Reexecução (D50):** o agente refaz por conta própria um job inválido (K1, `INVALIDA_*`), sempre o job inteiro (comparações pareadas no mesmo job), e depois avisa o Gabriel com a causa, o motivo do validador e os IDs.
- Uma falha `INVALIDA_SISTEMA` que se repete, ou sem causa conhecida, abre investigação (seção 0.3) antes de nova tentativa.

### 0.3 Protocolo de investigação de execução com erro

Quando uma execução é `INVALIDA_SISTEMA`, ou quando um resultado válido é implausível (por exemplo, uma política nova melhora 10× sem explicação), o agente:

1. Congela os artefatos da execução (logs do servidor, do controlador, do gerador de carga, linha do tempo de memória, saída do `classify_errors.py`) em `reports/data/<fase>/<run_id>/`.
2. Reconstrói a linha do tempo: ações do controlador (ativações, despejos), estado de cada worker, memória da GPU, e as requisições afetadas (ids, horários, modelo).
3. Formula uma hipótese de causa e a testa com a menor execução que a reproduz (menos modelos, menor duração, mesma semente). Para travamentos, coleta as pilhas de todos os processos (`PRISM_STACK_DUMPS` ou `py-spy dump`).
4. Classifica a causa como: falha já conhecida (id em `reports/erros.md`), falha nova (novo id), erro de medição, erro de configuração do experimento, ou erro de infraestrutura.
5. Corrige (código, configuração ou medição), documenta a correção em `reports/erros.md` (causa, mudança, teste) e **reexecuta a configuração original** para confirmar.
6. Registra tudo no relatório da fase, na seção "Anomalias e investigações". Uma investigação aberta bloqueia o gate da fase.

### 0.4 Disciplina de código

- Toda política nova fica atrás de variável de ambiente `PRISM_*`. **O padrão de cada variável reproduz o comportamento atual.** Nenhuma política nova muda o comportamento quando desligada.
- A lógica de decisão de cada política é uma função pura que recebe um retrato do estado (modelos, memória, filas, requisições com prazos, tempos estimados) e devolve ações (`python/sglang/multi_model/scheduling/policy/`). O laço do controlador apenas monta o retrato e aplica as ações.
- Ciclo de vida das instâncias como um estado explícito com transições por evento (D45); temporizadores só como limite de segurança.
- O repositório do kvcached **não** é alterado.
- Um commit por passo lógico, com mensagem que cita o id da tarefa (ex.: `F14.3: cargas heterogêneas`).
- Nada de apagar dados de execuções anteriores. Dados novos vão para pastas novas.
- Antes de decidir uma política ou um comportamento novo: busca na literatura, registrada em `reports/registro/referencias.md` (R*), e desenho curto aprovado pelo Gabriel.

### 0.5 Registros obrigatórios

| Registro | Onde | Conteúdo |
| --- | --- | --- |
| Relatório da fase | `reports/fases/FXX_<slug>.md` | modelo na seção 0.7 |
| Registro de execuções | `reports/registro/execucoes.csv` | uma linha por execução (colunas na seção 3.3) |
| Registro de decisões | `reports/registro/decisoes.md` | toda escolha de projeto ou parâmetro, com data, alternativas, motivo e quem decidiu |
| Catálogo de cargas | `reports/registro/cargas.md` | uma entrada por carga (seção 5), com origem, licença, transformação, estatísticas e hash |
| Latência de referência | `reports/registro/latencia_ref.md`, `latencia_ded.json`, `c_rot.json` | bases dos SLOs e custo da troca |
| Referências | `reports/registro/referencias.md` | artigos que apoiam cada decisão (R*) |
| Erros | `reports/erros.md` | ids existentes e novos, situação de cada um |
| Estado do plano | `TODO.md` | caixas marcadas, data e link para a evidência |

### 0.6 Testes unitários das funções de decisão

Cada política tem testes em `tests/policy/` com estados construídos à mão que cobrem: o caso típico, os casos de borda (fila vazia, memória exatamente no limite, todos os modelos ociosos, nenhum modelo cabe), e os casos que motivaram a política (fome, impasse, troca de grupo). Os testes verificam a **decisão**, não o desempenho; nenhum teste simula a dinâmica de carga.

### 0.7 Modelo de relatório de fase

```markdown
# FXX — <título>
Data de início / fim:
Commits:
## Objetivo
## Hipóteses (o que esperamos observar e por quê)
## Mudanças de código (arquivo, função, variável de ambiente, padrão)
## Configurações executadas (suite .tsv, cenários, políticas, parâmetros, sementes; justificativa de relevância)
## Execuções (tabela: run_id, status do validador, observação)
## Resultados (tabelas e figuras com caminho; só execuções VALIDAS)
## Anomalias e investigações (cada uma com causa, correção e verificação)
## Critérios de aceitação (cada critério: OK/FALHOU + evidência)
## Decisão do gate: APROVADO | REPROVADO | AGUARDANDO REVISÃO
## Pendências que passam para fases seguintes
## Reprodução (scripts, comandos, variáveis de ambiente, IDs)
```

### 0.8 Infraestrutura

- Polyaxon (`kunumi/hpc4ai`), imagem do `install.md` (SGLang 0.3.4 do Prism + kvcached + Redis), uma H200 por job.
- **No máximo 3 jobs do Prism simultâneos no nó**, contando todas as sessões: com 4 jobs, 38% dos níveis tiveram erro do driver no kvcached; com 5 ou mais, 71–79% (`reports/2026-10-30 Variação de desempenho do nó GPU do cluster.md`; D40). C1 com 14–19 modelos roda sozinho no nó (D48). Um K1 interrompe o job (D48).
- **Comparar só execuções da mesma janela:** a velocidade do nó varia 10–30% entre dias. Toda comparação é pareada no mesmo job, com IC 95% por bootstrap (D8, D49).
- Download dos artefatos um job por vez; conferir o uuid do pod em `environment.txt`.
- Verificação de saúde do nó antes de cada nível (R2.4). Toda campanha registra o commit, a imagem e as variáveis de ambiente efetivas.

### 0.9 Relevância da carga antes de rodar

Antes de submeter qualquer execução, o agente justifica, para cada carga, **por que ela exercita o que está sendo mudado** (uma política de residência só se testa em carga com ativações e despejos) e verifica se já existem dados reaproveitáveis. Cargas que não exercitam a mudança ficam fora e são registradas como tal. A justificativa vai para o relatório, em "Configurações executadas". Antes da campanha, um smoke confirma que a política age (D53).

### 0.10 Resultados de políticas novas: sempre contra as anteriores (D32)

Em todo relatório e toda apresentação com resultados de uma política nova:
- comparar com as políticas que já temos, **rodadas no mesmo job**: as linhas de base A0.2+A1 (maior SLO total) e A0.4 (troca por throughput/GB, linha de base forte em justiça), e as políticas por prazo anteriores que respondem à mesma pergunta;
- as tabelas seguem o padrão do `CLAUDE.md` (D56) e mostram também o TTFT p50 e p90, a cauda de espera e a justiça entre modelos (seção 7);
- uma apresentação nunca mostra só a política nova isolada.

---

## 1. Estado atual (2026-11-10)

- **Objetivo das políticas (D52):** justiça entre modelos sem grande perda de SLO total, junto com TTFT típico e nenhuma espera absurda (seção 7).
- **Concluído:** F0–F5 e F6a, com gate aprovado; da F6, a correção da P16, a triagem F6.0 e a triagem F6.16 (resumos na seção 6.1).
- **F6.15 concluída e gate da F6 aprovado (D60, 2026-11-11):** vencedora A9.2; F6.17 pulada; F6.18 feita sobre os dados
  da F6.15. Relatório da fase escrito (F6.9, `reports/fases/F06_politicas_por_prazo.md`). **Próxima: F14** (D58).
- **Próximo passo (D58):** F14, modelos heterogêneos, testando adaptações das melhores políticas cientes do tamanho de cada modelo e do tempo de ativação (seção 6.3).
- **O que sabemos até aqui:**
  - despejo por ociosidade de 10 s com A1 (A0.2+A1): maior SLO total, mas deixa 2–5 modelos por carga com fome (20 de 96 pares modelo × job abaixo de 10% no prazo, esperas de até 623 s);
  - troca por throughput/GB sem preempção (A0.4): melhor cauda; nos prazos S6 `k_R` ≥ 1 quase tão justa quanto as variantes do VLT, com 10–17 pontos a mais de SLO total;
  - VLT ciente da residência (A9.2): a mais justa no prazo curto (S3 `k_A`=5: pior quarto +5,5, Jain +5,3 contra a A0.4; total −6,0, sem significância);
  - preempção global piora ou empata; fica só como decisão por troca (A9.4);
  - encerradas com resultado negativo: A9.1, A2.3, A3.1, A10.1;
  - o custo real de uma troca é dominado pela saída da vítima e pela espera do ciclo, não pela carga dos pesos: num 8B, ativação ~1,4 s, troca 6,4 s com preempção e 15,7 s sem (p90 65 s) (`c_rot.json`).
- **Cortado do plano (D55, D57):** controle de admissão e toda recusa de requisições (F7), arbitragem Moore-Hodgson (A6, A0.5), oráculo offline (F9), e as variantes A2.2, A3.2, A3.3, A4 original, A9.3, A10.2, A10.3. Os números de fase F7 e F9 ficam vagos.

---

## 2. Fases na ordem de execução

Os números das fases não mudam, para não quebrar as referências nos relatórios e no código.

| Fase | Título | Gate | Situação |
| --- | --- | --- | --- |
| F0 | Reconhecimento e reprodução da linha de base | [HUMANO] | APROVADO (D1, D2) |
| F1 | Robustez restante | automático | APROVADO (D7–D9) |
| F2 | Instrumentação, validador e estimadores | [HUMANO] | APROVADO (D19) |
| F6a | Primeira rodada das políticas por prazo (A2.1, A9.1) | [HUMANO] | APROVADO, negativo (D27) |
| F3 | Catálogo de cargas | [HUMANO] | APROVADO (D29) |
| F4 | Restrições estruturais (A1) | automático | APROVADO (D38) |
| F5 | Linhas de base na nova metodologia | [HUMANO] | APROVADO (D49) |
| F6 | Políticas por prazo e por atraso virtual: triagens e confirmação | [HUMANO] | concluída (gate D60; relatório `F06_politicas_por_prazo.md`) |
| **F14** | **Modelos heterogêneos: políticas cientes do tamanho e do tempo de ativação** | [HUMANO] | **próxima (D58)** |
| F12 | Redução do custo da troca (A13) | [HUMANO] | planejada (D55) |
| F13 | Política candidata: troca por throughput com garantia de justiça (A12) | [HUMANO] | planejada (D55) |
| F15 | Generalização das políticas finais | [HUMANO] | planejada (D55) |
| F8 | Prazos ponderados e classes de SLO (A7) | automático | planejada |
| F10 | Campanha final de avaliação | [HUMANO] | planejada |
| F11 | Consolidação para artigos e dissertação | [HUMANO] | planejada |

A ordem de F12, F13, F15 e F8 depois da F14 é revista no gate da F14, com os resultados dela. O artigo de resultados parciais foi adiado sem data (D49); a F10 sustenta o artigo final (EuroSys 2028, setembro de 2027, ou MLSys 2028, outubro de 2027).

---

## 3. Validador de execução e registro

### 3.1 Verificações do validador (`polyaxon/validate_run.py`)

Cada verificação produz `OK`, `FALHA` ou `N/A`, com o valor medido.

**Integridade do sistema**
- V1. Servidor vivo do início ao fim da carga e do prazo extra.
- V2. Zero mortes de worker, zero `abort()`, zero `OutOfMemoryError`, zero exceções não tratadas (via `classify_errors.py`).
- V3. Nenhum modelo preso em estado intermediário (`ativando`/`desativando`) por mais que um limite (3× o tempo máximo de ativação medido).
- V4. Nenhum worker entregue a dois modelos ao mesmo tempo.

**Conservação de requisições**
- V5. `enviadas = concluídas + expiradas` exatamente; toda requisição tem um estado final.
- V7. Toda requisição retirada (preempção, desativação) reaparece na fila e termina, ou está explicada.
- (O V6, sobre recusas, saiu com a D57.)

**Coerência das métricas**
- V8. Para toda requisição concluída: `chegada ≤ primeiro token ≤ término`; TTFT e TPOT não negativos; número de tokens de saída igual ao pedido.
- V9. Nenhum TTFT sobrescrito: o TTFT registrado é o do primeiro prefill.
- V10. Relógios coerentes entre gerador e servidor.

**Carga e regime**
- V11. Taxa de chegada efetiva dentro de ±5% da alvo, por modelo e no total (a parte por taxa não se aplica aos níveis dedicados, D41).
- V12. Em cenários de sobrecarga de memória: evidência de sobrecarga (memória da GPU ≥ 95% por parte da carga, ou eventos "não coube").
- V13. Memória física total nunca acima da capacidade; memória livre do controlador coerente com o `nvidia-smi` (mediana da diferença ≤ 2 GB, com as séries alinhadas em −2 a +2 s, D36, D51).

**Infraestrutura**
- V14. Verificação de saúde do nó antes e depois da execução.
- V15. Sem preempção do job pelo Polyaxon.

### 3.2 Verificações de campanha (`polyaxon/validate_campaign.py`)

- C-V1. Número de repetições válidas por configuração ≥ mínimo da fase (triagem: 2; confirmação: 5).
- C-V2. Coeficiente de variação entre repetições ≤ 15% para a fração no SLO. Falhou na F5 e foi aceito com a limitação (D49): as conclusões se apoiam nas diferenças pareadas no mesmo job, não nos valores absolutos.
- C-V3. Linhas de base reproduzidas: A0.2+A1 e A0.4 rodam em todo job, pareadas com as políticas novas.

### 3.3 Colunas de `reports/registro/execucoes.csv`

`run_id, data, fase, commit, imagem, cenario, carga_id, nivel, politica, parametros(json), politica_usa_slo, slo_familia, slo_nivel(json; vazio se a política não usa SLO), semente, repeticao, gpu, no, status_validador, verificacoes_falhas, motivo, repetida_de, caminho_artefatos`

---

## 4. Políticas

Notação: requisição `r` do modelo `m`, chegada `a_r`, prazo de primeiro token `d_r = a_r + S_m`, pesos do modelo `W_m`
(GB), custo de ativação `Ĉ_at(m)` (carga dos pesos), custo real da troca `Ĉ_rot(m)` (decisão → modelo que entra pronto,
inclui a saída da vítima e a espera do ciclo; `reports/registro/c_rot.json`), conjunto ativo `A(t)`.

**Observação 4.0 (confirmada na F2.6: 0 de 36.064 requisições).** Com prazos menores que a ativação, toda requisição que
chega a um modelo inativo já nasce violada; reagir à chegada não a salva. Por isso as políticas por prazo rodam com
prazos iguais ou acima do tempo de uma troca (S3 `k_A`=5, S6 `k_R` ≥ 1; seção 5.4), e as violações são separadas em
inevitáveis e evitáveis (seção 7).

**Desativação de uma vítima (D30, D52).** Não há drenagem com prazo. A escolha é só entre **não preemptar** (as
requisições ainda não iniciadas voltam para a fila; o lote em execução termina) e **preemptar** (o lote em execução
recomeça do prompt depois). Padrão de todas as políticas: sem preempção; a A9.4 decide por troca.

### 4.1 Políticas em uso

| Id | Política | Variáveis | Origem e situação |
| --- | --- | --- | --- |
| A0.1 | Ociosidade de 50 s (original do Prism) | `PRISM_IDLE_THRESHOLD=50` | congela em 69% dos níveis da F5; só referência histórica |
| A0.2+A1 | Ociosidade de 10 s + restrições estruturais | `PRISM_IDLE_THRESHOLD=10` + A1 | linha de base de maior SLO total |
| A0.4 | Troca por throughput/GB, sem preempção, + A1 | `PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0 PRISM_ACTIVATION_HEADROOM_GB=0` + A1 | linha de base forte em justiça e cauda (D37, D38) |
| A1 | Restrições estruturais: reserva mínima de KV (A1.1, `b`=4, soma o piso de 5% do kvcached), detector de impasse (A1.2, `Δ_imp`=30 s), residência mínima (A1.3, `T_min`=10 s) | `PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30 PRISM_MIN_RESIDENCY=10` | F4, D34; zero impasses com A1 |
| A2.1 | EDF entre modelos: ativa o modelo de menor folga, ignorando requisições já inviáveis | `PRISM_EVICTION=edf` | F6a/F6.0; em confirmação (com e sem preempção) |
| A9.2 | VLT ciente da residência: todo modelo medido pelo atraso das requisições em espera; ganho de quem entra `G_m = lag_m(agora + Ĉ_rot(m))`; custo de despejo `K_v` = atraso que a vítima acumula até voltar; troca só se `G_m > K_v` + margem; vítimas por menor `K_v` por GB (GreedyDual-Size, R8; Clockwork, R2) | `PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1 PRISM_LVF_MARGIN` | D50; a mais justa no prazo curto; em confirmação |
| A9.4 | A9.2 que decide preemptar a cada troca: preempta se as requisições salvas ≥ λ × as perdidas (Shepherd, R10) | `PRISM_LVF_PREEMPT=per_swap PRISM_LVF_PREEMPT_LAMBDA` | D52; com λ = 3 virou a A9.2; em confirmação com λ = 1 (D54) |

Parâmetros comuns do VLT: `PRISM_LVF_ALPHA` (3), `PRISM_LVF_BETA_F` (0,5), `PRISM_LVF_BETA_B` (0), `PRISM_LVF_BUDGET` (1
ativação por ciclo). Código: `policy/deadline.py`, `policy/structural.py`, `simple_global.py`; testes em `tests/policy/`.

### 4.2 Políticas a desenvolver

- **A14 — adaptações cientes do tamanho e do tempo de ativação (F14, D58).** As melhores políticas já existentes,
  modificadas para pesar o tamanho de cada modelo (`W_m`) e o seu custo de entrar (`Ĉ_at(m)`, `Ĉ_rot(m)` medidos por
  modelo). Hoje a A0.4 normaliza o throughput por GB mas ignora quanto tempo o modelo que entra fica sem servir durante a
  troca; a A9.2 usa `Ĉ_rot` extrapolado para 14B e 32B e mede o ganho de quem entra sem olhar quantos GB ele toma; o
  limiar de ociosidade e o `T_min` são iguais para um 1B e um 32B. Variantes a desenhar (literatura e desenho aprovados
  antes, seção 0.4):
  - **A14.1 Troca por throughput com custo de ativação** (sobre a A0.4): o ganho de quem entra é descontado do serviço
    perdido durante `Ĉ_rot(m)` e da memória que ele toma; a vítima é escolhida pelo serviço perdido por GB liberado
    somado ao custo de trazê-la de volta (GreedyDual-Size, R8).
  - **A14.2 VLT ciente do tamanho** (sobre a A9.2): `Ĉ_rot(m)` medido por modelo; ganho de quem entra normalizado pela
    memória que ele exige (um 32B que expulsa quatro modelos pequenos precisa compensar o atraso de todos eles).
  - **A14.3 EDF com folga pelo custo real** (sobre a A2.1): a folga usa `Ĉ_rot(m)` do próprio modelo, não um valor
    comum.
  - **A14.4 Ociosidade e residência mínima por custo** (sobre a A0.2+A1): limiar de ociosidade e `T_min` proporcionais ao
    custo de recarregar o modelo (manter mais tempo quem custa caro para voltar; keep-alive por modelo, R7; custo por
    tamanho, R8).
- **A13 — mecanismos de redução do custo da troca (F12, D55).** Decomposição do `Ĉ_rot` nos dados da F6.15
  (`swap_cost.py`: espera pelo ciclo, saída da vítima, liberação da memória/P11, fila do carregador, ativação); depois,
  na ordem que a decomposição indicar: A13.1 ativação no evento de memória liberada; A13.2 controlador orientado a
  evento (ciclo de 5 s só como limite de segurança); A13.3 saída parcial da vítima (termina as requisições que acabam
  dentro da folga de quem entra, preempta o resto); A13.4 cancelar a desativação de um modelo pedido de novo (hoje ele é
  recarregado noutro worker em 4–7% das desativações; o SwapServeLLM bloqueia a vítima, R3).
- **A12 — troca por throughput com garantia de justiça (F13, D55).** Parte da A0.4 e acrescenta uma garantia de justiça
  entre modelos, para ter o total da A0.4 com a justiça da A9.2: A12.1 limite de espera por modelo (acima de
  `k_J · Ĉ_rot(m)`, o modelo passa na frente do critério de throughput); A12.2 pontuação mista (throughput/GB + `w_J` ×
  atraso; `w_J` = 0 é a A0.4); A12.3 contador de serviço por modelo, no espírito do VTC (Sheng et al., OSDI'24).
- **A7 — prazos ponderados e classes (F8).** Classes **interativa** e **lote** por requisição (SLOs provisórios na D19:
  interativa S2 `k_T`=10, `k_D`=5; lote TTFT 60 s, sem TPOT; reconfirmar antes da F8) e pesos `w_m` por modelo e classe
  nas políticas finais. Para cada política, o par (SLO agregado, pior modelo).

---

## 5. Cargas e SLOs

Toda carga está em `reports/registro/cargas.md` (origem, licença, transformação, estatísticas, hash). Gerador:
`polyaxon/workloads.py` via `overload_load.py` (chegadas abertas, saída de tamanho exato, prazo extra de 300 s); traces
por `polyaxon/trace_adapt.py`. Tamanhos das cargas novas: pares (prompt, saída) do Azure LLM 2023, teto 4096/1024.

### 5.1 Intensidade

- **Sobrecarga de memória:** `ρ_mem = (Σ_{m com demanda} W_m) / M`; os cenários de residência têm `ρ_mem` claramente acima de 1.
- **Sobrecarga de computação:** taxa oferecida / vazão máxima medida da GPU para o mesmo conjunto residente.

### 5.2 Cargas aprovadas (D29)

| Id | Construção | O que estressa | Uso |
| --- | --- | --- | --- |
| C1 `ovl_mem` | 10 (ou 14) modelos, 6 cabem, tráfego contínuo em todos | fome sem ociosidade | F5, F6 |
| C2 `ovl_phases` | 2 grupos de 5 alternando a cada 150 s | troca de grupo | F5; F15 |
| C3 `ovl_mix` | 8×8B + 2×3B | tamanhos diferentes, impasse | F4, F5 |
| C4 `ovl_kv`, C5 `ovl_compute` | todos os modelos cabem | KV e computação (sem ativações) | controles da F5 |
| C6 `ovl_zipf` | popularidade Zipf com ranks que giram | mudança gradual de popularidade | F5, F6 |
| C7 `ovl_bursty` | chegadas IPP (10/20 s, CV 2,5) por modelo | rajadas assíncronas | F5; F15 |
| C8 `ovl_diurnal` | taxa total em rampa senoidal (1 "dia" = 20 min) | entrada e saída da sobrecarga | F5 |
| C9 `ovl_classes` | interativas + lote sobre C1 e C6 | classes (A7) | F8 |
| C10 `ovl_sizes` | 2×3B, 3×8B, 2×Qwen2.5-14B, 1×Qwen2.5-32B, mesma taxa | tamanhos diferentes | F4, F5; base da F14 |
| C11 `slo_sweep` | C1, C6, C7 sob as famílias da seção 5.4 | sensibilidade ao SLO | análise |
| T1 `ovl_trace_big` | trace do benchmark do Prism | popularidade real desigual | F5, F6 |
| T2 `ovl_tr_lmsys` | LMSYS-Chat-1M: 12 modelos mais usados, chegadas Poisson | popularidade real | F15 |
| T3 `ovl_tr_azfn` | Azure Functions, função → modelo por rank | chegadas reais | F5, F6 |
| T4 | Azure LLM inference | tamanhos e chegadas reais | baixa prioridade |

T5 BurstGPT ficou fora (sem rajadas na taxa alvo). Protocolo de adaptação de trace (obrigatório para traces novos):
origem, versão, licença e hash; extração por entidade; mapeamento para modelos por rank; escala de tempo preservando a
forma (CV das chegadas ±10%, ordem de popularidade); truncagem registrada; estatísticas antes e depois em `cargas.md`.

### 5.3 Modelos heterogêneos e pesos diferentes por modelo (F14, D55, D58)

**Referência: o artigo do Prism (R1, OSDI'26).** 58 modelos avaliados (Tabela 3): 43 de 1–3B (74%), 8 de 4–8B (14%), 3 de
9–30B (5%), 4 de 31–70B (7%); testes de uma GPU com 18 modelos de 1B a 8B; ativação medida em 1B, 3B, 8B, 14B e 70B
(Fig. 10: 0,7 s até 8B, 1,3 s no 14B). Modelos do trace da Novita (Fig. 1): Llama-3.2-1B, Llama-3.1-8B, Qwen2-7B,
Qwen2.5-7B, Mistral-Nemo (12B), DS-R1-Distill-Qwen-14B/32B, QwQ-32B, Llama-3.3-70B. Padrão observado (§3.1): **modelos
grandes de uso geral com tráfego contínuo; destilados menores em rajadas curtas e esparsas.**

**Lista inicial de modelos (confirmar no início da F14 e no smoke do SGLang 0.3.4):**

| Classe (Tabela 3 do Prism) | Modelos | Pesos BF16 (aprox.) | Situação |
| --- | --- | --- | --- |
| 1–3B | Llama-3.2-1B-Instruct, Llama-3.2-3B-Instruct | 2,5 GB, 6,5 GB | 3B já usado; 1B a baixar |
| 4–8B | Llama-3.1-8B-Instruct, Qwen2.5-7B-Instruct | 16 GB, 15 GB | 8B já usado; Qwen2.5-7B a baixar |
| 9–30B | Qwen2.5-14B-Instruct (no lugar do DS-R1-Distill-Qwen-14B, mesma arquitetura); Mistral-Nemo-Instruct-2407 (12B), se o SGLang 0.3.4 suportar | 29,5 GB, ~24 GB | 14B no cache (D29); Mistral-Nemo a verificar |
| 31–70B | Qwen2.5-32B-Instruct | 65,5 GB | no cache (D29) |
| fora | Llama-3.3-70B | ~140 GB | não cabe numa H200 em BF16 (o artigo usa TP 4/8): limitação declarada |

**Cargas: uma mistura de tamanhos × várias distribuições de popularidade (D58).** A mistura de tamanhos é a proporção da
Tabela 3 do Prism numa GPU (ex.: 12 modelos: 4×1B, 4×3B, 2×7–8B, 1×14B, 1×32B, `ρ_mem` ≥ 1,3; definição final, taxas e
`ρ_mem` no início da F14). Sobre ela variam dois fatores de popularidade, cada um apoiado num artigo:

1. **Concentração** (quanto do tráfego vai para os modelos mais pedidos), por lei de potência com expoente α:
   - uniforme (todos com a mesma taxa; o DeltaZip usa uniforme como controle);
   - α = 0,9 (MuxServe, R5: ~20% dos modelos recebem 50% das requisições);
   - α = 1,5 (DeltaZip, Zipf "skewed"; opcional);
   - α = 2,1 (MuxServe: os mesmos 20% recebem ~90%).
2. **Quem é popular** (a ordem dos ranks em relação ao tamanho):
   - **grandes populares** (ranks em ordem decrescente de tamanho): o padrão do trace da Novita no artigo do Prism (R1,
     §3.1), em que os modelos grandes de uso geral ficam ativos de forma contínua e os destilados menores aparecem em
     rajadas esparsas;
   - **pequenos populares** (ranks em ordem crescente de tamanho): o padrão do BurstGPT, em que o modelo menor e mais
     barato (ChatGPT) recebe a grande maioria das requisições da API contra o GPT-4 (4,81 M × 0,24 M traces na v3);
   - **ordem real**: a popularidade conjunta com o tamanho de um trace com modelos de tamanhos conhecidos (LMSYS-Chat-1M,
     que já temos, D29; T2), mapeada para as classes de tamanho por regra registrada.

| Id | Concentração | Quem é popular | Chegadas | O que estressa |
| --- | --- | --- | --- | --- |
| H-unif | uniforme | — | Poisson | efeito só do tamanho (`W_m`, `Ĉ_rot`) |
| H-G-α | α ∈ {0,9; 2,1} | grandes | Poisson; variante com os pequenos em rajadas (processo do C7), como no §3.1 do Prism | throughput/GB tira o grande, que é o mais pedido |
| H-P-α | α ∈ {0,9; 2,1} | pequenos | Poisson | grande raro e caro de trazer: fome do grande ou expulsão de muitos pequenos |
| H-real | a do trace | a do trace | do trace (opcional: T1/T3) | padrão real de popularidade × tamanho |

O α = 1,5 entra só se a triagem mostrar que o comportamento muda entre 0,9 e 2,1. O C10 continua como a versão
equilibrada (poucos modelos de cada tamanho, mesma taxa).

**Fontes a verificar no texto antes do desenho (F14.0):** os valores de α e as frações do MuxServe (R5, §5), o Zipf do
DeltaZip (arXiv 2312.05215), as contagens por modelo do BurstGPT (arXiv 2401.17644) e, se servir, a caracterização por
modelo do ServeGen (NSDI'26, arXiv 2505.09999). Os números acima vêm de uma busca; só entram em `referencias.md` depois
de lidos no artigo (regra do registro).

### 5.4 SLOs

O SLO é sempre um fator experimental, definido por uma **família** e um **nível**; nenhum script lê o SLO de uma
constante. Bases por modelo: carga do próprio modelo em GPU dedicada, como no artigo do Prism, juntando os modelos
idênticos (P95 e mediana; `latencia_ded.json`, D20, D21); custo da troca em `c_rot.json` (F5.0a). Toda execução que usa
essas bases cita `reports/registro/latencia_ref.md`.

| Id | TTFT de `r` | TPOT de `r` | Uso |
| --- | --- | --- | --- |
| S1 | 1 s | 100 ms | comparabilidade com outubro/2026; o TPOT de 100 ms é referência secundária |
| S1D | absoluto (1, 2, 5 s) | `k_D` × P95 dedicado, `k_D` ∈ {2, 5} | padrão das tabelas desde a F6.15 (D56) |
| S2 | `k_T` × P95 dedicado, `k_T` ∈ {2, 5, 10, 25} | `k_D` × P95, `k_D` ∈ {1,5; 2; 3; 5} | família principal; S2 `k_T`=10 é a referência estrita |
| S2M | `k_T` × mediana dedicada, `k_T` ∈ {5, 10, 25, 50} | `k_D` × mediana, `k_D` ∈ {3, 5, 10, 20} | variante pela mediana |
| S3 | `k_A` × `Ĉ_at(m)`, `k_A` ∈ {2, 5, 10, 25, 50} | `k_D` × P95 | prazo relativo à ativação |
| S4 | interativa / lote por requisição | interativa / sem limite | C9 e A7 |
| S6 / S6P | `k_R` × `Ĉ_rot(m)` sem / com preempção | `k_D` × P95 | prazo que cabe numa troca real |

**Níveis das políticas que usam o prazo (D49):** S3 `k_A` = 5 (~7 s num 8B) e S6 `k_R` ∈ {1, 2, 4} (~16, 31 e 63 s num
8B). Na F14, os prazos S3 e S6 de cada modelo saem do `Ĉ_at`/`Ĉ_rot` medido para ele.

**Economia de execuções:** políticas que não usam o SLO para decidir (A0.x, A1) produzem a mesma execução para qualquer
SLO; suas curvas são calculadas depois, sobre os mesmos registros. Políticas que usam o prazo (A2, A9, A12–A14 quando
dependem dele) rodam uma execução por nível.

**Como reportar:** fração no SLO por nível (curva), SLO mínimo atingível (menor nível com 90% e 99%), sempre nas três
vistas da seção 7.1, com a separação evitável × inevitável.

---

## 6. Fases

### 6.1 Fases concluídas: o que foi feito e alcançado

**F0 — Reconhecimento e reprodução (APROVADO, D1, D2; `reports/fases/F00_inventario.md`, `F00_reconhecimento.md`).**
Inventário do repositório (políticas, `PRISM_*`, scripts, logs, fluxo de uma execução). A arbitragem por folga
(Moore-Hodgson) do artigo do Prism **não existe** no código aberto. Reprodução de `ovl_phases` e `ovl_trace_big` aceita
(o critério estrito falhou por desvios pequenos); critério de reprodução por IC 95% da diferença pareada.

**F1 — Robustez (APROVADO, D7–D9; `F01_robustez.md`).** T1 é um impasse de memória da política (resolvido na F4 pela
A1). As 25 requisições "perdidas" foram explicadas por ciclos de preempção/recomputação, sem descarte (`PRISM_TRACE_RIDS`).
P11 (liberação de memória de 7–88 s) localizada no `trim()` do kvcached, que não é alterado: virou custo de troca a medir.
K1: 0 em 37 execuções com nó saudável; árbitro desligado (D5). P12: detecção da morte do model service. Regressão
avaliada só por A/B no mesmo período (D8).

**F2 — Instrumentação, validador e estimadores (APROVADO, D19; `F02_instrumentacao.md`).** Log de decisões do controlador
(`PRISM_DECISION_LOG`), logs por requisição, validador V1–V15 e de campanha, testado nos dados antigos (17/17 e 37/37).
Estimadores: `Ĉ_at = 0,463 + 0,0628·W_GB + 1,144·ativações à frente` (erro mediano 11,8%), prefill `p̂` (12–18%), `λ̂` por
EWMA. Observação 4.0 confirmada. Métricas com SLO parametrizado e três vistas (`slo_metrics.py`), base dedicada dos SLOs
(D20–D23), sobrecusto da instrumentação 0,0017%. CUDA graphs desligados, como no README do Prism (D22).

**F6a — Primeira rodada das políticas por prazo (APROVADO, negativo, D27; `F06a_prazo_primeira_rodada.md`).** EDF (A2.1)
e VLT do SuperInfer (A9.1) como funções puras com 28 testes; triagem de 74 níveis em C1 e T1: nenhuma passou o sinal de
8 pontos. A drenagem de 15 s na desativação foi removida do código (D30).

**F3 — Catálogo de cargas (APROVADO, D29; `F03_cargas.md`).** `workloads.py` e `trace_adapt.py`; cargas C6–C11, T2–T4 com
estatísticas e hash em `cargas.md`; 10 de 10 dry runs válidos; P14 (limite de arquivos abertos) corrigida.

**F4 — Restrições estruturais (APROVADO, D38; `F04_restricoes.md`).** A1.1–A1.3 implementadas e testadas (D34); campanha
de 35 jobs: zero impasses em 70 níveis com A1; A0.4 (troca por throughput sem folga fixa) escolhida como a variante da
troca por throughput (D37). P15 (alocação do prefill em Qwen2 grande) corrigida.

**F5 — Linhas de base na nova metodologia (APROVADO, D49; `F05_linhas_de_base.md`).** Antes da campanha: custo real da
troca (`swap_cost.py`, `c_rot.json`), famílias S6/S6P, classificação nova das violações, ociosidade da GPU
(`gpu_idle.py`), colunas de cauda nas tabelas, ciclo de vida explícito das instâncias (D45). Campanha de 270 níveis (5
configurações × 18 cargas × 3 repetições), todos válidos: A0.2+A1 tem o maior SLO, A0.4 a melhor cauda, A0.4p é a pior,
A0.1 congela. C-V2 falhou e foi aceito com as diferenças pareadas (D49). Níveis de prazo da F6 escolhidos (D49). Pendente
de baixa prioridade: figuras de CDF da F5.2c.

### 6.2 F6 — Políticas por prazo e por atraso virtual (em andamento)

**Feito.**
- **P16 corrigida (R2.6):** com preempção, a requisição no meio de um prefill em pedaços ficava "rodando" num modelo
  inativo e era respondida pelo modelo errado; 0 casos depois da correção (`f6-p16-1..5`).
- **F6.0, triagem sem drenagem (`F06_0_repeticao_sem_drenagem.md`, D50–D52; 160/160 válidos):** A2.1, A9.1 e A9.2 × {S3
  `k_A`=5, S6 `k_R`=1, 4} × {sem, com preempção} em C1 com 10 modelos, T1, C6 com 14 modelos e T3. Nenhuma política por
  prazo supera a A0.2+A1 em SLO total nos prazos curtos; todas reduzem o TTFT p90 em 40–80 s e a maior espera em
  200–380 s; a A0.2+A1 ganha deixando modelos com fome; a A9.2 é a mais justa; a preempção não ajuda. Resultado: objetivo
  passa a ser justiça sem grande perda de SLO, e preempção só por troca (D52).
- **F6.16, triagem das políticas novas (`F06_16_triagem_politicas_novas.md`, D53, D54; 88/88 válidos):** A9.4 (λ = 3) é a
  A9.2 na prática; A2.3 e A3.1 são menos justas que a A9.2; A10.1 é a A0.4. A A0.4 se firma como linha de base forte.
- **F6.15, confirmação com 5 repetições (`F06_15_confirmacao.md`, D54, D60; 20 jobs, 300/300 válidos):**
  - a A9.2 é mais justa que a A0.4 nos prazos de até 1 troca (S3 `k_A`=5: pior quarto +5,2\*, Jain +5,4\*, total
    −1,4 n.s.), com TTFT típico maior;
  - a A9.4 com λ = 1 não se distingue da A9.2;
  - com prazos de ≥ 2 trocas, a A0.4 é tão justa quanto as outras e tem 7–13 pontos a mais de total que as variantes do
    VLT;
  - a A2.1 tem cauda ~2× (filas "perdidas" vão para o fim);
  - a A2.1 com preempção é a mais justa no S6 `k_R`=4, mas tem as maiores esperas;
  - nenhuma violação é inevitável nos níveis S3/S6; 13–17% no S3 `k_A`=5 só seriam cumpridas com decisão antes da
    chegada (F6.18, tabela D).
  
  **Gate aprovado (D60): vencedora A9.2; F6.17 pulada.**

- **F6.9, relatório da fase (`reports/fases/F06_politicas_por_prazo.md`, 2026-11-11):** resumo das quatro rodadas,
  resultados negativos, correções e limitações. **F6 concluída.**

**Critérios de aceitação:** testes passando; linhas de base no mesmo job; para cada carga, diferença contra cada linha de
base com IC 95% pareado, nas três vistas, com a decomposição das violações e as métricas de justiça; toda diferença
grande (> 2×) explicada pelos logs de decisão. **Gate [HUMANO].**

### 6.3 F14 — Modelos heterogêneos: políticas cientes do tamanho e do tempo de ativação (próxima, D58)

**Pergunta.** Com modelos de 1B a 32B e distribuições de popularidade diferentes (uniforme, concentrada nos grandes,
concentrada nos pequenos, real), as melhores políticas que temos (A0.2+A1, A0.4, A9.2, A2.1, e a vencedora da F6.15)
continuam justas e com bom SLO? Adaptá-las para considerar o tamanho de cada
modelo e o seu tempo de ativação melhora a justiça (entre modelos e entre classes de tamanho) sem grande perda de SLO?

**Hipóteses.**
- H1: a A0.4 favorece os modelos pequenos (o throughput por GB de um 32B é baixo) e deixa os grandes com fome quando
  eles são os populares (H-G), tanto mais quanto maior o α.
- H2: a A9.2 sem `Ĉ_rot` medido por modelo erra o ganho dos grandes (extrapolado de 6 e 15 GB) e troca demais ou de menos.
- H3: com limiar de ociosidade e `T_min` iguais para todos, o grande é despejado e recarregado com o mesmo critério de
  um 1B, que custa uma fração do tempo para voltar.
- H4: as adaptações A14 reduzem a diferença de SLO e de espera entre classes de tamanho, sem perder SLO total além do
  limiar combinado com o Gabriel.

**Tarefas.**
- F14.0 Ler no texto as fontes das distribuições de popularidade (MuxServe, DeltaZip, BurstGPT, ServeGen; seção 5.3) e
  registrá-las em `referencias.md`; extrair do LMSYS-Chat-1M a popularidade por tamanho de modelo para a H-real.
  [HUMANO] Confirmar a lista de modelos e as cargas H (concentrações e ordens). Não há limiar fixo de "grande perda de
  SLO" (D60).
- F14.1 Baixar os modelos novos (Llama-3.2-1B, Qwen2.5-7B, Mistral-Nemo) com `polyaxon/hf_download.sh`; smoke de cada um
  no SGLang 0.3.4 (sobe, atende, desativa, reativa); o que não funcionar sai, com o motivo em `cargas.md`.
- F14.2 Base dedicada (`latencia_ded.json`) de cada modelo novo; `Ĉ_at` e `Ĉ_rot` por modelo, com e sem preempção,
  substituindo os valores extrapolados de 27,5 e 61 GB em `c_rot.json`.
- F14.3 Cargas H-unif, H-G-α, H-P-α e H-real em `workloads.py` (popularidade como parâmetro: α e ordem dos ranks por
  tamanho); `ρ_mem`, taxas e fração do tráfego por classe de tamanho em `cargas.md`; dry runs válidos.
- F14.4 Métricas por classe de tamanho (SLO nas três vistas, justiça, TTFT p50/p90, cauda, trocas) em `slo_metrics.py`,
  `f60_fairness.py` e no padrão das tabelas.
- F14.5 Linha de base heterogênea, 2 repetições: A0.2+A1, A0.4, A9.2, A2.1 e a vencedora da F6.15, sem adaptação, nas
  cargas H e no C10. Mostra quais tamanhos sofrem com cada política e confirma que as cargas exercitam a troca (seção
  0.9).
- F14.6 Literatura (custo por tamanho no cache e no keep-alive: GreedyDual-Size R8, keep-alive por modelo R7, e trabalhos
  de serving multi-modelo com modelos de tamanhos diferentes) em `referencias.md`; desenho das adaptações A14.1–A14.4
  (seção 4.2) para aprovação do Gabriel.
- F14.7 Implementação atrás de `PRISM_*` (padrão = atual), funções puras, testes (grande × pequenos na mesma memória,
  vítima grande ociosa × vários pequenos ocupados, tudo cabe, `T_min` por tamanho).
- F14.8 Triagem, 2 repetições: cada adaptação pareada com a sua versão sem adaptação e com A0.2+A1 e A0.4, no mesmo job,
  nas cargas H, nos prazos S3 `k_A`=5 e S6 `k_R` ∈ {1, 2, 4}; smoke antes para confirmar que as adaptações agem.
- F14.9 Confirmação, 5 repetições, do que passar na triagem.
- F14.10 Relatório `reports/fases/F14_modelos_heterogeneos.md`; o Gabriel decide a ordem das fases seguintes.

**Critérios de aceitação:** todos os modelos da lista final com base dedicada e `Ĉ_rot` medidos; dry runs válidos;
resultados por modelo e por classe de tamanho, nas três vistas, com justiça e IC 95% pareado; toda diferença grande
explicada pelos logs de decisão; limitações declaradas (70B fora, modelos substitutos). **Gate [HUMANO].**

### 6.4 F12 — Redução do custo da troca (A13)

**Tarefas:** F12.1 decomposição do custo da troca nos dados da F6.15 e da F14, por política e por tamanho; F12.2 desenho
de A13.1–A13.4 na ordem que a decomposição indicar (literatura, aprovação); F12.3 implementação atrás de `PRISM_*`, com
estados explícitos (D45) e testes; F12.4 triagem pareada (com × sem cada mecanismo) nas melhores políticas, 2
repetições, e confirmação de 5 do que entrar; F12.5 remedir `Ĉ_rot` (e decidir, com registro, se a base do S6 muda) e
relatório `F12_custo_da_troca.md`.

**Critérios:** `Ĉ_rot` (p50, p90) e decomposição, pareados, com IC 95%; efeito nas políticas pelo objetivo da seção 7;
nenhum nível inválido novo sem explicação. **Gate [HUMANO].**

### 6.5 F13 — Política candidata: troca por throughput com garantia de justiça (A12)

**Tarefas:** F13.1 literatura (VTC e justiça em serving multi-modelo e multi-inquilino) e desenho de A12.1–A12.3 para
aprovação; F13.2 implementação e testes (com as adaptações da F14 e os mecanismos da F12 aprovados); F13.3 triagem, 2
repetições, contra A0.2+A1, A0.4, A9.2 e a vencedora da F6.15, nas cargas da F6 e nas heterogêneas, em S3 `k_A`=5 e S6
`k_R` ∈ {1, 2, 4}; F13.4 confirmação, 5 repetições, e sensibilidade do parâmetro de justiça; F13.5 relatório
`F13_politica_candidata.md` e escolha da política candidata principal pelo Gabriel.

**Critérios:** os da F6, com o objetivo da seção 7. **Gate [HUMANO].**

### 6.6 F15 — Generalização das políticas finais

**Tarefas:** F15.1 escolher, com a justificativa da seção 0.9, cargas aprovadas que a F6 e a F14 não usaram (proposta:
C7, C2, T2; C8 opcional); F15.2 políticas finais contra A0.2+A1 e A0.4, 5 repetições pareadas; F15.3 relatório
`F15_generalizacao.md`, inclusive onde o resultado não se mantém, com o mecanismo.

**Critérios:** os da F6, por carga. **Gate [HUMANO].**

### 6.7 F8 — Prazos ponderados e classes (A7)

**Tarefas:** F8.0 reapresentar ao Gabriel os SLOs das classes (provisórios na D19) com os dados até aqui e esperar a
confirmação; F8.1 classes e pesos nas políticas finais; F8.2 campanha em C9 e C6 com proporções de classe variadas; F8.3
curvas (SLO agregado × pior modelo) por política, nas três vistas e por classe; F8.4 objetivo padrão (agregado, max-min
ou ponderado) decidido pelo Gabriel; relatório F08.

**Critérios:** curvas completas nas três vistas e por classe; objetivo registrado em `decisoes.md`. **Gate automático.**

### 6.8 F10 — Campanha final

**Tarefas:** congelar commit e imagem; matriz completa (cargas aprovadas, incluindo as heterogêneas, × políticas finais ×
níveis de sobrecarga × SLOs) com as repetições mínimas; tabelas e figuras regeneráveis por um comando a partir de
`execucoes.csv`; relatório final com conclusões, limitações e ameaças à validade.

**Critérios:** C-V1–C-V3; zero execuções inválidas sem explicação; toda figura e tabela nas três vistas e com justiça.
**Gate [HUMANO].**

### 6.9 F11 — Consolidação

Pacote de artefatos (código, configurações, cargas ou scripts de adaptação, dados agregados, scripts de figuras) e
rascunhos das seções de avaliação dos artigos e da dissertação. **Gate [HUMANO].**

---

## 7. Métricas (definições únicas para todo o projeto)

**Objetivo das políticas (D52, D33).** As políticas são avaliadas por quatro critérios, sempre juntos:
1. **Justiça entre modelos:** fração no prazo do pior quarto dos modelos, índice de Jain sobre as frações por modelo e
   TTFT p90 do pior modelo, só com modelos com ≥ 10 requisições (`polyaxon/f60_fairness.py`); na F14, também por classe
   de tamanho.
2. **Fração dentro do SLO** (três vistas, seção 7.1).
3. **TTFT típico:** p50 e p90 das concluídas, com as não atendidas reportadas à parte.
4. **Cauda de espera:** TTFT p99, TTFT máximo e fração de requisições com TTFT acima de 10× a mediana da própria
   execução, contando as não atendidas como espera até o fim do prazo extra; mais a pior espera pelo 1º token por modelo.

O objetivo é **alcançar justiça entre modelos sem grande perda de SLO total**. Uma melhora conseguida à custa de uma
cauda absurda (requisições esperando centenas de segundos) não conta como ganho. Quando um critério melhora e outro
piora, o relatório diz, com o mecanismo nos logs de decisão. Não há limiar fixo de "grande perda" (D60). Cada relatório
mostra a diferença de total com IC 95% pareado ao lado do ganho de justiça e das caudas, por prazo e por carga, e a
leitura é feita no gate.

**Definições.**
- **Fração dentro do SLO:** requisições com TTFT ≤ SLO de TTFT **e** TPOT ≤ SLO de TPOT, sobre **todas as enviadas** (as não atendidas até o fim do prazo extra contam como violações). Todo número reportado diz a família e o nível.
- **SLO mínimo atingível:** menor nível em que a política atende 90% (e 99%) das requisições.
- **Goodput:** requisições dentro do SLO por segundo.
- **Trocas:** ativações e despejos por minuto; trabalho descartado em preempções (tokens).
- **Perdas:** requisições sem resposta até o fim do prazo extra (devem ser zero).
- **Estatística:** IC 95% por bootstrap; comparações sempre pareadas no mesmo job.

### 7.1 Três vistas: combinado, só TTFT, só TPOT

Residência, ativação e fila afetam sobretudo o TTFT; pressão de KV e partilha da GPU, sobretudo o TPOT. Uma política pode
melhorar o combinado trocando um tipo de violação por outro. Por isso toda análise é feita em três vistas, lado a lado:

| Vista | Fração reportada | Distribuições |
| --- | --- | --- |
| Combinada | TTFT ≤ SLO_TTFT **e** TPOT ≤ SLO_TPOT | — |
| Só TTFT | TTFT ≤ SLO_TTFT | TTFT e TTFT normalizado pela base dedicada; p50/p90/p99 |
| Só TPOT | TPOT ≤ SLO_TPOT | TPOT e TPOT normalizado; p50/p90/p99 |

Regras:
- O denominador é o mesmo nas três vistas (todas as enviadas); as não atendidas contam como violação nas três.
- **Decomposição das violações** em quatro grupos disjuntos: atende ambos; viola só TTFT; viola só TPOT; viola ambos (as não atendidas reportadas à parte). A soma fecha em 100%.
- Na vista só TPOT, só entram requisições com pelo menos dois tokens; o número das demais é reportado.
- Por modelo (e, na F14, por classe de tamanho): as três vistas também, para não esconder um modelo que perde TPOT enquanto os outros ganham TTFT.
- O padrão das tabelas dos relatórios é o do `CLAUDE.md` (D56).

### 7.2 Violações inevitáveis e evitáveis (vista só TTFT; F5.0c, D43)

Para uma requisição que chegou a um modelo inativo:
- **inevitável pela ativação:** havia memória livre na chegada e `S_m < Ĉ_at(m)`;
- **inevitável pela rotação:** não havia memória livre e `S_m < Ĉ_rot(m)`;
- **evitável só com residência prévia:** `S_m` cobre a ativação ou a rotação, mas não a rotação + um ciclo do controlador;
- **evitável:** os demais casos, mais toda violação de requisição que chegou a modelo ativo.

Para o TPOT: a fração das violações que ocorrem durante uma troca (`viol_tpot_em_troca`).

### 7.3 Ociosidade da GPU (F5.0d, D44, D46)

- **Residência ociosa com demanda pendente:** GB·s de modelos residentes sem requisição em execução nem na fila, nos instantes em que algum modelo inativo tem fila, sobre o total de GB·s da GPU.
- **Ociosidade esperada pela carga:** `1 − min(1, Σ ρ_m)` do conjunto residente, com `ρ_m` pelo tempo de GPU ocupada por requisição na GPU dedicada; a diferença para a utilização observada (`gpu.csv`) separa a ociosidade da carga da ociosidade da política (`polyaxon/gpu_idle.py`).

---

## 8. Decisões pendentes do Gabriel (o agente prepara as opções e para)

1. (Decidido na D60: gate da F6 aprovado, vencedora A9.2, F6.17 pulada.)
2. Início da F14: lista final de modelos e cargas heterogêneas.
3. Durante a F14: desenho das adaptações A14 antes de implementar.
4. Gate da F14: ordem das fases seguintes (F12, F13, F15, F8).
5. F12: mecanismos de redução do custo da troca que ficam.
6. F13: política candidata principal e parâmetros.
7. Início da F15: cargas da generalização. Início da F8: SLOs das classes.
8. Após F8: objetivo padrão. Após F10: conclusões e limitações a declarar.
