# Registro de decisões

Toda escolha de projeto ou parâmetro, com data, alternativas, motivo e quem decidiu (seção 0.5 do `PLANO_AGENTE.md`).

## D1 — Reprodução da F0.4 aceita (2026-10-30, Gabriel)

- **Contexto:** a F0.4 falhou no critério estrito (média nova dentro do [mín, máx] da referência) por desvios de 0,1–0,4 ponto, quase todos no sentido "melhor" e explicados pelas repetições `fix3` (nó degradado) da referência; a exceção é o r3 do A0.3, causado pela P11 (`reports/fases/F00_reconhecimento.md`).
- **Alternativas:** aceitar; rodar mais 2 repetições de cada configuração antes de decidir.
- **Decisão:** aceitar a reprodução. Gate da F0 APROVADO.

## D2 — Critério de reprodução e de C-V3 (2026-10-30, Gabriel, sobre proposta do agente)

- **Contexto:** com 3 repetições de referência, uma nova execução da mesma distribuição cai fora do [mín, máx] com probabilidade 2/(n+1) = 50% por métrica, então o critério estrito rejeita metade das reproduções perfeitas.
- **Alternativas:** [mín, máx] (critério anterior); IC 95% por bootstrap da diferença de médias; teste de permutação com α = 0,05.
- **Decisão:** a reprodução é aceita quando o **IC 95% por bootstrap da diferença de médias (nova − referência) contém 0** no SLO, no TTFT p90 e na pior espera pelo 1º token. As demais métricas são informativas. As repetições da rodada `fix3` de 28/10 (nó degradado) saem da referência. Implementação: `polyaxon/compare_reference.py --exclude-round fix3` (10.000 reamostragens, semente 0); o p exato do teste de permutação é impresso só como informação.
- **Observação do agente ao aplicar (2026-10-30):** nos dados da F0.4 o critério novo falha em 3 das 9 comparações, com diferenças pequenas e todas no sentido "melhor": SLO do A0.1 +1,1 ponto [IC +0,1; +2,2], SLO do A0.2 +1,0 [+0,1; +1,8], TTFT p90 do A0.3 −1,4 s [−2,0; −0,8] (`reports/data/F00/reproducao/comparacao_criterio_bootstrap.md`). Com 2–3 repetições de cada lado, o bootstrap subestima a variância (fator (n−1)/n e só 3–10 médias distintas por lado), então tende a rejeitar diferenças pequenas; o teste de permutação não consegue rejeitar nada nesse tamanho (p mínimo de 0,10 com 3 × 3 e de 0,10–0,20 com 3 × 2). Os dois só ganham sentido com ≥ 5 repetições de cada lado, que é o mínimo de C-V1. A aceitação da F0.4 (D1) não muda.
- **Proposta pendente para a F1.5 (a confirmar pelo Gabriel antes da F1.5):** 5 repetições novas e, como referência, as 3 repetições da F0.4 (mesmo código e nó saudável), em vez das de 28/10 sem `fix3` (2–3 repetições por configuração).

## D3 — P11 passa para a F1 (2026-10-30, Gabriel)

- **Decisão:** a P11 (desativação de ~30 s sem trabalho pendente) não bloqueia a F0; é investigada na F1 como tarefa F1.7, junto com o T1 de 14 modelos.

## D4 — Virtual Lag Time (SuperInfer) entra no plano como A9 (2026-10-30, Gabriel pediu a avaliação; análise do agente)

- **Pedido:** avaliar o Virtual Lag Time (VLT) e o Largest-VLT-First (LVF) do SuperInfer (Yu et al., MLSys 2026, `SuperInfer.pdf`, seção 4.2) e, se fizer sentido para o Prism, implementar e testar.
- **Avaliação:** interessa no nível de **modelo** (controlador global), onde o LVF é uma generalização direta da política `fair` que já existe (`simple_global.py:425`: rodízio do modelo ativo há mais tempo quando outro espera `PRISM_FAIR_QUANTUM` s), trocando o quantum fixo por atraso relativo ao SLO e acrescentando a verificação de disputa e o orçamento de rotação. Ele dá uma alternativa **sem estimadores** e **olhando para trás** (atraso já acumulado) às políticas por folga A2/A3, que olham para a frente e precisam de `Ĉ_at`, `p̂_r` e `λ̂_m`. No nível de requisição o ganho esperado é pequeno: na fila do GPU scheduler, com SLO único, ordenar por VLT equivale a FCFS (e a EDF com classes, que a prioridade atual já aproxima); dentro do worker, o SGLang 0.3.4 só preempta por recomputação, sem a troca de KV de 200 GB/s que sustenta o resultado do artigo. Detalhes na seção A9 do plano.
- **Alternativas:** não incluir; incluir só no nível de requisição; incluir no nível de modelo (escolhida), com o nível de requisição como variante opcional.
- **Decisão do agente:** nova família A9 no plano, implementada e avaliada na F6 contra `fair`, A0.1, a melhor linha de base de F5 e A2/A4. Não antecipa nenhuma fase (precisa dos logs de decisão da F2, da histerese A1.3 da F4 e da referência da F5). O Gabriel pode pedir para antecipar.
- **Nota de leitura do artigo:** a definição diz que `S_B` e `S_F` são os SLOs de TTFT e de TBT, nessa ordem, mas o uso mostra o contrário: a espera de uma requisição nova é tolerada por `β_F·S_F` e a de uma rotacionada por `β_B·S_B`, e a seção 5.3.2 diz que aumentar `β_F` piora o TTFT p99. Lemos `F` = primeiro token (TTFT) e `B` = entre tokens (TBT).

## D5 — Árbitro entre processos continua desligado (2026-10-30, agente, F1.4)

- **Dados:** K1 (`cuMemSetAccess`/`cuMemCreate`/`cuMemMap` recusado pelo driver) em 0 de 37 execuções fora da janela degradada de 2026-10-30 (00:31–00:54Z) e em 5 das 6 execuções dentro dela; nenhuma na F0.
- **Alternativas:** ligar `PRISM_MEMORY_ARBITER=1` (com os ajustes em `kvcached_patches.py`); manter desligado.
- **Decisão:** manter desligado. O K1 aparece só com nó degradado, e o árbitro muda a forma como os motores dividem a memória mesmo sem falha, o que afastaria o Prism avaliado do publicado. O validador (F2.2) marca como inválida a execução com K1.

## D6 — Rodada `f1-trace` classificada como INVALIDA_INFRA (2026-10-30, agente, F1)

- **Dados:** as 6 execuções dos jobs `f1-trace-1..3` (00:31–01:10Z, 3 GPUs diferentes) tiveram K1, morte do model service (P12) ou workers mortos; os jobs `f1-freeze-1/2`, iniciados logo depois (00:58Z), falharam a verificação de partida do kvcached com a GPU vazia; o A/B `f1-ab-1..3` (mesmo código, com e sem a instrumentação, 01:23–02:40Z) teve 6 de 6 execuções limpas e sem perdas; nenhuma das 37 execuções fora da janela teve K1 ou morte do model service.
- **Decisão:** a rodada é inválida por infraestrutura (janela de nó degradado); não entra em nenhum agregado. **Atualização (2026-10-30, a partir da análise do cluster do Gabriel, `reports/2026-10-30 Variação de desempenho do nó GPU do cluster.md`):** a fila `axia/default` é um único nó de 8 H200 compartilhado, e erros de driver do kvcached e mortes do model service aparecem em 71–79% dos níveis com 5 ou mais jobs nossos no nó, contra 2–3% com até 3. A janela coincide com 5 jobs desta fase rodando juntos (`f1-trace-1..3` e `f1-freeze-1/2`): a causa provável é a nossa própria concorrência. A partir daqui, no máximo 3 jobs ao mesmo tempo. Usada só como evidência da P11 e da P12 com nó degradado. A verificação de saúde por execução não detectou a janela em 5 das 6 execuções: o validador da F2.2 deve olhar a janela de tempo e os sinais dentro da execução (K1, morte do model service). A P11 acima de 10 s não serve como sinal: ocorre também em execuções limpas (18 de 986 desativações na F1.5).


## D7 — F1.5 aceita com base no A/B de código no mesmo período (2026-10-30, Gabriel)

- **Contexto:** a repetição da F0.4 falhou contra as duas referências (SLO −7 a −9 pontos). O A/B do código `2ac0098` contra o código atual, rodado ao mesmo tempo, passou no critério D2 (`reports/data/F01/ab_codigo/`). A causa é o cluster mais lento em 30/10.
- **Decisão:** F1.5 aceita; sem regressão de código.

## D8 — Critério de "sem regressão" pareado no mesmo período (2026-10-30, Gabriel)

- **Decisão:** a verificação de regressão, e toda comparação entre políticas (C-V3), usa execuções pareadas no mesmo período: o código ou a política de referência roda junto com o novo, com os jobs submetidos intercalados. Nunca se compara com uma campanha de outro dia. O teste continua sendo o D2 (IC 95% por bootstrap da diferença de médias contendo 0, no SLO, no TTFT p90 e na pior espera). Isso substitui a proposta pendente do D2 sobre a referência da F1.5.

## D9 — Detecção da morte do model service implementada já (2026-10-30, Gabriel)

- **Decisão:** implementar na F1, ligada por padrão como a P2 (`PRISM_DETECT_DEAD_MODEL_SERVICE=1`; `0` volta ao comportamento antigo). Ela só muda o comportamento quando o model service falha.
- **Implementação:**
  - o model service grava o PID e sobrevive a um pedido que não consegue receber;
  - o worker espera a resposta em fatias de 1 s e falha a ativação na hora se o serviço morreu, ou após 300 s sem resposta;
  - a ativação é revertida e respondida com `success=False`, pelo mesmo caminho da `ActivationOutOfMemory`, em vez de o worker morrer.
- **Verificação:** com o model service morto a 120 s, em jobs rodados no mesmo período:

  | Versão | Jobs | Workers mortos | Atendidas depois da morte |
  | --- | --- | --- | --- |
  | Só a falha rápida | `f1-p12-on` | 0 | 55 |
  | Final (falha rápida + aviso ao controlador) | `f1-p12b-on` | 0 | 605 |
  | Sem a correção | `f1-p12-off`, `f1-p12b-off` | 11 | 177–182 |

  Na primeira versão, o controlador despejava modelos para ativações que só podiam falhar e esvaziava a GPU. Por isso a versão final acrescentou o aviso ao controlador (`model_service_lost`), que congela ativações e despejos.

## D10 — V11 mede o gerador, não a carga (2026-11-04, agente, F2.2; aprovada pelo Gabriel em 2026-11-04)

- **Contexto:** a seção 3.1 pede taxa efetiva "dentro de ±5% da alvo, por modelo e no total". A carga é gerada com semente fixa, então o desvio por modelo entre a taxa sorteada e a alvo é propriedade da carga, não da execução, e com Poisson ele passa de 5% por construção: no `ovl_mem` 0,2 req/s, 60 requisições por modelo têm desvio-padrão de ~13% (o `model_4` tem 7,8% das requisições, contra 10% esperados). Aplicado ao pé da letra, o V11 invalidaria todas as execuções existentes.
- **Alternativas:** (a) ±5% por modelo e total sobre a carga sorteada; (b) V11 = o gerador enviou no horário (atraso de envio p99 ≤ 1 s e taxa total efetiva dentro de ±5%), e a fidelidade da carga à especificação (taxas, CV, popularidade) é verificada uma vez por carga no catálogo (F3, critério "taxas ±5%, CV ±10%"); (c) tolerância por modelo de 3σ de Poisson.
- **Decisão do agente:** (b), implementada em `validate_run.py` (usa o horário de envio gravado pelo gerador a partir da F2.1; N/A antes). Aprovada pelo Gabriel em 2026-11-04.

## D11 — Classificação INFRA só com evidência externa; janelas degradadas e relógio dos logs (2026-11-04, agente, F2.2; aprovada pelo Gabriel em 2026-11-04)

- **Regra:** INVALIDA_INFRA quando o V14 (verificação de saúde antes ou depois do nível, ou sobreposição com uma janela de `reports/registro/janelas_degradadas.csv`) ou o V15 falham. K1 e morte do model service são registrados como `sinal_infra`, mas fora de uma janela conhecida a execução é INVALIDA_SISTEMA: antes da R2.1 o próprio controlador causava K1 (P1), então o K1 sozinho não prova nó degradado. Isso obriga a investigação da seção 0.3 em vez de uma repetição automática.
- **Relógio:** os logs do servidor usam a hora local do contêiner (UTC−7 em outubro de 2026, horário de verão do Pacífico; UTC−8 depois de 1/11), e o `environment.txt` e o `run.log` usam UTC. O validador deduz o fuso de cada job pela diferença entre os dois. Sem isso, a primeira versão marcou 18 níveis da `fix5` como "na janela degradada", erradamente.
- **Janelas registradas:** 27/10 12:20–16:30, 30/10 00:30–01:10 e 30/10 13:39–13:42 (UTC), do relatório do cluster e da D6.

## D12 — Estimador de custo de ativação (2026-11-04, agente, F2.3)

- **Modelo:** `Ĉ_at = a + b·W_GB + c·ahead` (`ahead` = ativações já em andamento; o model service carrega um modelo por vez), ajustado por regressão pela mediana (L1) em 6.547 ativações de 66 jobs limpos. Mínimos quadrados davam erro mediano fora da amostra de 41,6%, porque a cauda pesada puxa o ajuste para a média; a regressão L1 dá 11,8% (critério da F2: ≤ 20%). Com uma ou mais ativações na frente, o erro fica em 37–51%. Usar o tempo restante estimado das ativações na frente não melhorou (35%).
- **Limitação:** só há dois tamanhos de modelo (6 e 15 GB), então a extrapolação para 14B/32B (C10) não está validada: a medir na F3.

## D13 — Comparação com o SLO usa ≤ (2026-11-04, agente, F2.11)

- A seção 7 define "TTFT ≤ SLO"; o gerador de outubro usava "<". Com o "≤", o cálculo novo (`slo_metrics.py`) reproduz exatamente os números de outubro em 182 níveis (28/10, F0, F1): diferença máxima de 6,5e-13 no TTFT p90 e zero nas frações.

## D14 — Violação inevitável (2026-11-04, agente, F2.11)

- "Chegou a modelo inativo" = o modelo estava desativado no instante da chegada (estado pelos eventos do GPU scheduler); "ativando" conta como ativo para essa regra, porque a ativação já em curso pode terminar antes do prazo. Inevitável se, além disso, `SLO_TTFT_r < Ĉ_at(m)` com `ahead = 0` (o custo mínimo).

## D15 — Estimador de taxa λ̂ (2026-11-04, agente, F2.5)

- EWMA com janela curta de 10 s e longa de 60 s; segue a curta quando ela passa de 2× a longa (rajada) **ou cai abaixo da metade** (pausa). A troca só na subida deixava o erro do `ovl_phases` em 68% (H = 15 s); com a troca nos dois sentidos, 50%. Nas cargas estacionárias a troca simétrica custa 1–3 pontos. Os parâmetros voltam na sensibilidade da F6.

## D16 — V12 só quando há modelos fora da GPU no início; logs brutos persistidos (2026-11-04, agente, F2.2)

- O V12 (evidência de sobrecarga de memória) se aplica aos cenários de memória cuja configuração tem modelos que começam desativados; os níveis de controle com todos os modelos residentes (ex.: `n06` dos limites) ficam N/A.
- Os downloads brutos (logs do servidor), que estavam só em `/tmp` (tmpfs, perdido num reboot), foram copiados para `/mnt/scratch/scheduler/prism-raw/` (README na pasta), fora do git.

## D17 — Estimador de fila q̂_r híbrido (2026-11-04, agente, F2.5)

- **Dados (28/10 e C5 de 21/10, requisições com fila na frente e modelo ativo, `reports/data/F02/estimadores/`):** a soma dos prefills das requisições na frente (`p̂` da F2.4) erra 35,6 s na mediana sob sobrecarga de computação (C5, `ovl_compute`), porque ignora o decode e a partilha da GPU; a taxa observada de primeiros tokens do modelo nos últimos 30 s erra até 18 s na mediana quando há poucas conclusões (C1–T1).
- **Alternativas:** só a soma; só a taxa observada; híbrido.
- **Decisão:** híbrido (`estimators.queue_time_hybrid`): taxa observada quando há ≥ 10 primeiros tokens na janela, soma dos prefills nos outros casos. Erro mediano: C1 0,20 s, C2 5,85 s, C3 18,8 s, T1 7,8 s, C5 1,6 s. As esperas longas de C3 e T1 com o modelo "ativo" vêm de falta de KV e retiradas (impasse T1), que nenhum dos dois vê: fica como limitação para a F4/F6.

## D18 — Latências de referência da rodada isolada (2026-11-04, agente, F2.10/F2.4)

- **Dados:** na primeira rodada (`f2-iso`, junto com `f2-overhead` e `f2-smoke` no mesmo nó), o TPOT com 1 fluxo variou até 3× entre repetições (CV 48% no 8B) e o erro do `p̂` do 3B ficou em 23,4% (> 20%). Sem CUDA graphs (`--disable-cuda-graph`, como em todas as execuções), o decode com lote pequeno é limitado pela CPU, então é sensível a processos concorrentes. Repetida sozinha (`f2-iso2`, job `23d61305`): CV do TPOT 8%, erro do `p̂` 12,4% (8B) e 18,0% (3B), dentro do critério; load average do nó 100–140 nas duas rodadas (outras equipes), então a diferença vem dos nossos jobs simultâneos.
- **Decisão:** `reports/registro/latencia_ref.json` = rodada `f2-iso2`; a primeira fica como evidência (`reports/data/F02/iso/`). Medidas de latência de referência rodam sozinhas no nó (sem outro job nosso).

## D19 — Gate da F2: família de SLO, níveis, classes, estimadores e sobrecusto (2026-11-04, Gabriel, gate F2)

Opções e dados em `reports/fases/F02_instrumentacao.md` (seção "Decisão do gate").

1. **Família principal de SLO:** S2 (`k_T·TTFT_iso`, `k_D·TPOT_iso`). O S1 (1 s / 100 ms) é sempre reportado ao lado, para comparar com outubro; o S3 é família secundária, para a observação 4.0. Ao aprovar, o Gabriel pediu que o cálculo de `TTFT_iso` e `TPOT_iso` ficasse explícito nos relatórios: está em `reports/registro/latencia_ref.md`, que todo relatório com S2 cita.
2. **Níveis (opção A):** `k_T ∈ {5, 10, 25, 50, 100}`, `k_D ∈ {3, 5, 10, 20}` e `k_A ∈ {2, 5, 10, 25, 50}`, no lugar dos iniciais da seção 5.4. Motivo: com os iniciais, as curvas de `k_D` e `k_A` não têm nenhum ponto acima de 90%, e a regra de escolha dos 3 níveis das políticas por prazo não tem como ser aplicada. O TPOT sob carga é ~4× o `TPOT_iso`, e o cold start leva de 5 a 18 s no p10, contra um `Ĉ_at` de 1,4 s. Com `k_T = 2`, todas as políticas ficam em ~0%. A grade do `slo_curves.py` já cobre estes níveis.
3. **SLOs das classes (F8):** adotada a proposta, **provisória**:
   - interativa: S2 com `k_T = 10` e `k_D = 5`;
   - lote: TTFT absoluto de 60 s, sem limite de TPOT.

   **Antes de começar a F8, o agente reapresenta a proposta ao Gabriel** com os dados da F5–F7, inclusive a alternativa de lote em S3 com `k_A = 50`, e espera a confirmação.
4. **Limites dos estimadores (opção A):** ficam os 20% de erro mediano para `Ĉ_at` e `p̂`. Dois casos entram como limitações declaradas, e não como critérios:
   - `Ĉ_at` com outra ativação na frente (37–51%);
   - `q̂` em impasse (modelo ativo sem KV).

   As fases seguintes reportam o erro dos estimadores junto com o resultado das políticas que os usam.
5. **Sobrecusto do log, F2.8 (opção A):** a medida direta é aceita como evidência do critério de ≤ 2%: 0,083 ms por ciclo de 5 s, no processo do controlador. A vazão ponta a ponta (+1,0%, IC [−9,7%; +11,8%]) fica registrada como inconclusiva por causa da deriva do nó. Não se roda a campanha intercalada.

## D20 — Base do S2 pela estratégia do artigo do Prism (2026-11-04, Gabriel; detalhes de execução do agente, F2.10)

- **Motivo:** o Gabriel pediu que a base do S2 seguisse o artigo do Prism (§7.1, "Metrics"): "we first ran its workload on dedicated GPUs to measure its P95 TTFT and TPOT latencies. [...] We then scaled these base values by a factor". O `TTFT_iso`/`TPOT_iso` da D18 vinha de sondas sintéticas, uma requisição por vez (lote 1). Era um piso que nenhuma carga alcança: sob carga, o TPOT ficava ~4× acima.
- **Decisão (Gabriel):** a base de cada modelo é o P95 do TTFT e o P95 do TPOT da **própria carga do modelo**, servida sozinha numa GPU dedicada. O S2 passa a ser `SLO_TTFT = k_T · TTFT_base(m, carga)` e `SLO_TPOT = k_D · TPOT_base(m, carga)`, sem depender do tamanho do prompt, como no artigo. A versão completa foi escolhida: todos os modelos de todas as cargas C1–C5 e T1, 48 execuções, até 3 jobs simultâneos.
- **Detalhes do agente:**
  1. **Nível medido:** só o nível de referência de cada carga (`cargas.md`). A base fica fixa entre os níveis de taxa da carga; medida em cada taxa, ela afrouxaria o SLO à medida que a carga sobe. O artigo não diz como trata isso.
  2. **Como a carga é reproduzida:** o gerador monta a carga inteira com a mesma semente e o mesmo nível e envia só as requisições do modelo (`overload_load.py --only-model`). As chegadas e os tamanhos são idênticos aos da carga original.
  3. **Servidor dedicado:**
     - os mesmos flags das cargas, com um só modelo residente, 1 worker e o pool de KV da carga;
     - `PRISM_IDLE_THRESHOLD=1000000`, para que o modelo nunca seja retirado entre chegadas;
     - um servidor novo por modelo (`run_examples.sh` `PRISM_OVL_DEDICATED`).
  4. **As sondas da D18 continuam** como estimador de prefill `p̂` (F2.4), mas deixam de ser a base do SLO.
  5. **Concorrência:** a D18 pedia medidas de referência sozinhas no nó, mas o Gabriel autorizou até 3 jobs simultâneos. O controle de contaminação é a dispersão da base entre modelos idênticos (mesmo 8B, chegadas da mesma distribuição) da mesma carga e entre jobs.
- **Efeito na D19:** a família (S2) continua. Os níveis de `k_T` e `k_D` ficam **suspensos** até as curvas da F2.12 serem refeitas com a base nova, e voltam ao Gabriel.
- **Jobs:**
  - `f2-ded-a` (`dd623724`): C2, C4 e C5;
  - `f2-ded-b` (`6318bd87`): T1;
  - `f2-ded-c` (`daabe342`): C1 e C3.

  Suítes em `polyaxon/configs/f2_ded_{a,b,c}_suite.tsv`; código em `reports/data/F02/codigo/ded_submetido_sobre_cb7c666.patch`.

## D21 — Base do S2 juntando os modelos idênticos da carga; S2M com a mediana (2026-11-04, Gabriel)

- **Motivo:** as 48 execuções dedicadas da D20 terminaram válidas (`reports/data/F02/validador/f2-ded.csv`), mas o P95 por modelo não serve como base:
  - modelos idênticos da mesma carga divergem muito. No C1, por exemplo, o P95 do TPOT vai de 11 a 49 ms e o do TTFT de 45 a 214 ms; a dispersão do P95 entre modelos idênticos vai de 25% a 214% nas cargas;
  - as requisições lentas vêm em episódios de 10–30 s (TPOT de 50–100 ms, TTFT de até 9,6 s), sem retirada, falta de memória ou erro nos logs do servidor, ao longo das 2,5 h com os 3 jobs no nó;
  - a causa mais provável é a disputa de CPU entre os jobs (o decode sem CUDA graphs depende da CPU), como na `f2-iso` (D18). Não há como provar: o load average do nó não foi registrado;
  - as medianas são estáveis: CV entre modelos idênticos de 2–14% (o TPOT mediano fica em 9–12 ms, perto dos 12,2 ms das sondas sozinhas da D18).
- **Decisão (Gabriel):** "vamos usar o que já temos, use também a mediana que é estável". Não há nova rodada.
  - **S2:** a base é o P95 do TTFT e do TPOT das requisições atendidas de **todos os modelos idênticos** (mesmo `model_path`) da carga, juntas (`pool_ttft_p95`, `pool_tpot_p95`). Os episódios lentos ficam na base, diluídos entre os modelos: o S2 mede "quantas vezes o P95 da carga em GPU dedicada, sob o ruído deste nó".
  - **S2M (nova):** a mesma junção, com a mediana (`pool_ttft_p50`, `pool_tpot_p50`). É a estatística que não depende do ruído.
  - Os dois são calculados por `polyaxon/slo_metrics.py`; as bases estão em `reports/registro/latencia_ded.json` (`polyaxon/iso_dedicated.py`, tabela em `reports/data/F02/ded/latencia_ded.md`).
- **Ressalva do C5 (`ovl_compute`):** cada 8B recebe ~25 req/s (prompt ~510, saída ~256 tokens), o que sozinho numa GPU fica no limite da capacidade. No `model_1` (25,8 req/s) a fila se formou e não se desfez (TTFT mediano de 14,6 s); no `model_2` (24,6 req/s), não (63 ms). A base junta dá TTFT P50 de 0,87 s e P95 de 15,3 s, e TPOT de 45 / 70 ms: é a fila do próprio modelo, não a latência de serviço. **Decisão (Gabriel, 2026-11-04): fica como está.** O critério é o mesmo para todas as cargas, sem exceções por cenário ("precisamos utilizar os mesmos critérios para os diferentes cenários, se não fica uma bagunça cheia de exceções"). A limitação está em `observacoes.md`, O2: no C5, o S2/S2M é frouxo no TTFT, e a leitura vai pelo S1 e pela vista só TPOT.
- **Efeito:** as curvas da F2.12 foram refeitas com S2 e S2M (`reports/data/F02/curvas/`). Os níveis de `k_T`/`k_D` continuam suspensos (D20) e voltam ao Gabriel com essas curvas.

## D22 — CUDA graphs continuam desligados (2026-11-04, Gabriel)

- **Contexto:**
  - todas as execuções usam `--disable-cuda-graph`, copiado dos exemplos do `README.md` do Prism;
  - o padrão do código é ligado, e o artigo não diz como foi a avaliação.
- **Decisão (Gabriel):** não ativar. Os efeitos ficam anotados como limitação, em `observacoes.md` O1:
  - decode ~40% mais lento com lote 1;
  - TPOT sensível à disputa de CPU;
  - saturação mais cedo no C5.

## D23 — Níveis de `k_T`/`k_D` sobre as bases da D21 (2026-11-04, Gabriel)

- **Contexto:**
  - os níveis da D19 tinham sido escolhidos sobre a base antiga das sondas (lote 1) e foram suspensos pela D20;
  - com as bases da D21, as curvas refeitas (`reports/data/F02/curvas/`) ficam planas acima de `k_T ≈ 10–25` (S2) ou `25–50` (S2M);
  - o TPOT passa de 90% em `k_D = 3` (S2) ou `k_D = 10` (S2M).
- **Decisão (Gabriel, aceitando a proposta do agente):**
  - **S2** (base P95): `k_T ∈ {2, 5, 10, 25}`, `k_D ∈ {1,5; 2; 3; 5}`;
  - **S2M** (base P50): `k_T ∈ {5, 10, 25, 50}`, `k_D ∈ {3, 5, 10, 20}`;
  - **S3:** `k_A ∈ {2, 5, 10, 25, 50}`, mantido da D19, com o `k_D` do S2.
- **Efeito:**
  - `polyaxon/slo_curves.py` marca esses níveis em cinza (`APPROVED`);
  - a grade calculada continua mais larga, para mostrar onde as curvas ficam planas;
  - os SLOs das classes da F8 continuam provisórios (D19, TODO F8.0). O interativo (S2, `k_T = 10`, `k_D = 5`) está dentro dos níveis do S2.

## D24 — Primeira rodada das políticas por prazo antes da F3 (F6a) (2026-11-04, Gabriel)

- **Decisão:** antes da F3, uma fase nova, a F6a (`PLANO_AGENTE.md`, seção 6), com as duas políticas por prazo mais simples:
  - A2.1, EDF entre modelos;
  - A9.1, LVF/Virtual Lag Time.

  Ela tem prioridade sobre as outras tarefas. É um desvio da ordem F3 → F4 → F5 → F6, pedido pelo Gabriel.
- **Escolhas do Gabriel:**
  1. Começar pelo mais simples, A2.1 e A9.1. A2.2, A2.3, A3, A4 e A9.2 ficam para a F6.
  2. A1.1 (reserva de KV) e A1.3 (`T_min`) entram junto, como opções. A A1.2 fica para a F4.
  3. Níveis de SLO das execuções das políticas novas: S2 `k_T` = 10, S2 `k_T` = 25 e S3 `k_A` = 5.
  4. Ciclo do controlador: 5 s e 1 s.
  5. A5 e A6 ficam fora.
- **Cargas (agente; o Gabriel pediu critério):**
  - **triagem:** só C1 e T1, porque têm disputa por residência;
  - **confirmação:** C2, como controle;
  - **fora:** C3 (impasse; é A1.1/F4), C4 e C5 (zero ativações).

  Nova regra do plano (seção 0.9): antes de submeter, justificar por que cada carga exercita a mudança.
- **Linhas de base:**
  - já existiam execuções de 28/10 e da F1 para C1 e T1, mas o Gabriel aprovou rodá-las de novo na triagem, pareadas na mesma janela;
  - motivos: deriva do nó, código posterior à F1, e falta de `fair` no T1;
  - a triagem tem 2 repetições, e a confirmação, 5.
- **Concorrência:**
  - o Gabriel chegou a propor 8 jobs simultâneos;
  - com os dados de 30/10 (≥ 5 jobs → 71–79% dos níveis com erro do driver), voltou para **3**;
  - a seção 0.8 do plano, que dizia "hoje 6", foi corrigida para 3.

## D25 — Desenho e parâmetros da A2.1 e da A9.1 na F6a (2026-11-04, agente; para revisão do Gabriel no gate da triagem)

- **Código:** `python/sglang/multi_model/scheduling/policy/deadline.py` (`edf_select`, `lvf_select`, funções puras); `simple_global.py` monta o retrato (`_deadline_snapshot`) e substitui os passos 3/3b só com `PRISM_EVICTION=edf|lvf`. O despejo por ociosidade (passo 1, `PRISM_IDLE_THRESHOLD`) continua rodando. Testes: `tests/policy/test_deadline.py`.
- **Escolhas de desenho que o plano deixava em aberto:**
  1. **A2.1 também escolhe vítimas.** O plano descreve só "quem entra"; sem despejo, no C1 (sem ociosidade) a A2.1 seria idêntica à A0.1. Regra EDF entre modelos: um modelo inativo com requisição viável pode tirar um ativo cuja urgência é mais tardia (modelos sem requisição viável na fila contam como +∞). Um modelo só com requisições perdidas só pode tirar um modelo sem nenhuma requisição (nem na fila, nem rodando). Ordem das vítimas: sem requisição viável primeiro (entre elas, sem trabalho rodando, depois o ativo há mais tempo), depois o prazo mais tardio.
  2. **Ordem de entrada da A2.1:** viáveis por folga crescente; depois os só com filas perdidas, pela requisição mais antiga (evita fome entre filas perdidas).
  3. **`ê_r`** = `Ĉ_at(m)` (se inativo; F2.3, com as ativações pendentes como `ahead`) + prefill das requisições à frente + o próprio prefill (`p̂` do 8B, F2.10). Coeficientes por variável de ambiente (`PRISM_CAT_A/B/C`, `PRISM_PREFILL_A/B`), padrões = `cat_model.json` e `latencia_ref.json`.
  4. **Orçamento de rotação** (`PRISM_EDF_BUDGET`, `PRISM_LVF_BUDGET` = 1): conta rotações **em andamento** (vítimas despejadas, modelo que entra ainda não ativo), não por ciclo. Com o ciclo de 1 s, "por ciclo" deixaria iniciar várias rotações antes de a primeira terminar. Ativações em memória já livre não contam (como no artigo: `B_xfer` é o que se libera além da memória livre).
  5. **Ativação em dois ciclos**, como `pressure`/`fair`/`throughput`: a vítima sai no ciclo `t`, o modelo que entra é ativado num ciclo seguinte, quando a memória é medida livre; ele tem prioridade na memória liberada (reserva de 15 s + o tempo de drenagem). Custo: até um ciclo a mais por rotação (por isso o fator ciclo de 1 s).
  6. **A9.1:** `S_TPOT` não é conhecido pelo controlador; com `β_B = 0` (artigo) o termo não depende dele.
- **Parâmetros da triagem:**
  - vítimas drenadas, sem preempção (`PRISM_SWAP_PREEMPT=0 PRISM_SWAP_DRAIN=1`, 15 s), e folga de ativação de 3 GB, iguais à A0.3 (P0D1) e ao `fair`, para que a diferença seja só o critério de escolha;
  - **A1.3** `T_min` = 10 s (`PRISM_MIN_RESIDENCY`): ~7× o `Ĉ_at` mediano do 8B (1,4 s) e acima do p99 (8,3 s);
  - **A1.1 desligada** (`PRISM_KV_RESERVE_REQS=0`): C1 e T1 não têm impasse; com `b ≤ 8` a reserva (≤ 0,94 GB para o 8B) nem passaria do 1 GB de KV que a R2.1 já exige. Fica para a F4 (C3);
  - A2.1: piso de folga 0 s; A9.1: `α = 3`, `β_F = 0,5`, `β_B = 0` (artigo).
- **Prazos efetivos (F6a.1, `overload_load.py --slo-spec`):** C1: S2 `k_T=10` → 0,70 s, `k_T=25` → 1,75 s, S3 `k_A=5` → 7,0 s; T1: 0,64 s / 1,61 s / 7,0 s. Com `Ĉ_at ≈ 1,4 s`, no S2 `k_T=25` a folga de uma requisição de modelo inativo é de 0,2–0,35 s na chegada: na prática, só o S3 `k_A=5` deixa folga para a A2.1 agir sobre modelos inativos (observação 4.0).

## D26 — Duas correções no meio da triagem da F6a e reexecução pareada da A2.1 (2026-11-05, agente)

- **Achado (investigação do nível INVALIDA_SISTEMA `edf_S3k5`, C1 r2, job `1390b57c`; seção 0.3):**
  1. **P13** (nova, `reports/erros.md`): uma desativação sem preempção girava para sempre quando a última requisição era retraída por *decode OOM* e não cabia de novo. Corrigida em `scheduler.py` (padrão ligado, `PRISM_DEACTIVATE_EVICT_STUCK=0` desliga).
  2. **Desvio da A2.1 em relação à D25 (item 5):** a reserva só punha o modelo reservado na frente dentro da sua classe (viáveis / perdidos). Um modelo só com filas perdidas, para o qual uma vítima tinha sido despejada, perdia a memória liberada para um modelo com requisição viável, às vezes a própria vítima (o `model_5` esperou ~300 s; o `model_3` foi despejado e reativado). Corrigido em `deadline.py`: os reservados entram primeiro, sem olhar a classe (teste `test_reserved_lost_model_beats_viable_victim`).
- **Efeito sobre os dados:** a A9.1 (LVF) e as linhas de base não passam pelo código da reserva da A2.1; a P13 só muda o caminho que antes travava. Todos os níveis EDF da etapa 1 ficam como **EDF v1**, só para diagnóstico.
- **Decisão:**
  - o job `t1-2` (`2376c727`), recém-iniciado, foi parado;
  - a A2.1 corrigida (**EDF v2**) roda de novo no C1 em 2 jobs (`f6a_tri_c1_edf2_suite.tsv`: A0.1, A0.2 e os 3 níveis EDF; jobs `940e60ed`, `f9c41c00`), pareada com A0.1 e A0.2 (melhor linha de base do C1 na etapa 1);
  - o T1 r2 roda a suíte completa com o código corrigido. O T1 r1 (`1460d2fb`, código v1) é completado por um job com A0.1, a melhor linha de base do T1 e os 3 níveis EDF v2;
  - os diffs de código ficam em `reports/data/F06a/codigo/` (v1 = v2 sem as duas correções).
- **Custo:** +10 níveis no C1 e +5 no T1 em relação aos 48 da matriz da D24.

## D27 — Gate da F6a: fechada com resultado negativo, sem confirmação (2026-11-05, Gabriel)

- **Contexto:** na triagem (`reports/fases/F06a_prazo_primeira_rodada.md`), nenhuma configuração da A2.1 ou da A9.1 superou a melhor linha de base do mesmo job por mais de ~8 pontos (sinal da D24). A melhor, a EDF v2 com S2 no T1, empatou no combinado (−1,3 e −2,9 pontos) e melhorou o pior modelo (+8,6 e +20,5). A LVF e o ciclo de 1 s perderam em todos os casos.
- **Alternativas apresentadas:** (1) fechar sem confirmação; (2) confirmar a EDF v2 com S2 `k_T` = 10 e 25 no T1, 5 repetições, mais o C2; (3) a opção 2 só com `k_T` = 25.
- **Decisão (Gabriel, seguindo a recomendação do agente):** opção 1. A F6a.8 não é executada. A próxima fase é a F3. O item de regressão que falhou em parte (deriva do A0.1 entre jobs) é aceito como deriva do nó.
- **Para a F6:**
  - A3 (perda esperada da vítima), porque a A2.1 com prazo folgado despeja modelos ocupados;
  - A9.2 (LVF com custo de ativação e vítima pelo valor), porque a A9.1 escolhe vítimas só pela residência;
  - o ciclo de 1 s só com histerese maior;
  - a justiça (pior modelo) como objetivo possível da A7/F8.

## D28 — Construção das cargas da F3 e registros pendentes da F6a (2026-11-05, agente; para revisão do Gabriel no gate da F3)

- **Registros da F6a:**
  - os CSVs do validador da F6a (`reports/data/F06a/validador/*.csv`) e os `niveis.csv`/`pareado.csv` da triagem não existiam mais em lugar nenhum: são gitignored e ficaram no worktree da F6a. Foram refeitos a partir dos dados brutos (`prism-raw/F6a*`) com o mesmo `validate_run.py` e o mesmo `f6a_triage.py`. O `resumo.md` refeito é idêntico, byte a byte, ao do commit `9d1768d`;
  - total refeito: **73 níveis, 72 VALIDA, 1 INVALIDA_SISTEMA** (`1390b57c/edf_S3k5`, V3, P13). A tabela de execuções do relatório F06a soma o mesmo (73). O texto do relatório diz "74 níveis, 73 VALIDA": é um erro de contagem do texto, não de dados;
  - `execucoes.csv`: 73 linhas da F6a. Commit `f290003` para os jobs v2 (o diff salvo `v2_e04db5e.diff` está contido em `e04db5e..f290003`); `f290003-D26` para os jobs v1 (smoke, `tri_c1-1`, `tri_c1-2`, `tri_t1-1`), que rodaram o `f290003` **sem** as duas correções da D26 (código nunca commitado);
  - `register_runs.py` passa a marcar `politica_usa_slo` = 1 e a família/nível do `PRISM_OVL_SLO_SPEC` para `PRISM_EVICTION=edf|lvf`. Antes estava fixo em 0, o que valia só até a F5;
  - `collect_reps.py` passa a descartar os níveis que o validador não marca como VALIDA (seção 0.2), com a lista em `descartados.csv`. `PRISM_COLLECT_CRITERION=legacy` reproduz o critério antigo, para os relatórios de antes da F2;
  - **para não perder de novo:** o script de commit força (`git add -f`) os CSVs de registro e do validador.
- **Tamanhos das cargas sintéticas novas:** pares (prompt, saída) do trace de conversas do Azure LLM 2023 (CC-BY-4.0), sorteados juntos, com teto de 4096/1024 tokens. Alternativas: T1 (prompts curtos demais, p50 40; adaptadores de LoRA), ShareGPT/LMSYS (licença, acesso condicionado), uniformes como C1 (a seção 5.2 pede não inventar tamanhos). O C9 sobre C1 mantém os uniformes, para comparar com o C1.
- **Parâmetros das sintéticas:** C6 Zipf α = 1, deriva de 60 s por troca adjacente; C7 ligado 10 s / desligado 20 s (CV 2,5; com 20/40 s o CV numa janela de 600 s fica 10% abaixo do teórico, ver `cargas.md`); C8 amplitude 0,8, "dia" de 1200 s, Zipf(1) fixo; C9 fração de lote 0,3, TTFT de lote 60 s, sem TPOT (D19, provisório); C10 2 × 3B, 3 × 8B, 2 × 14B, 1 × 32B, 0,2 req/s cada.
- **Regras de entidade dos traces (seção 5.3, item 3):** T3 = 12 funções HTTP em ranks espaçados em log com razão 8 entre a mais e a menos popular, sem afinamento; T4/T5 = janelas consecutivas do serviço único como entidades, escala de tempo para a taxa alvo. Alternativa rejeitada para T4/T5: repartir o fluxo único por sorteio entre os modelos, o que afina o processo e puxa o CV para 1.
- **Dúvida sobre o critério de aceitação (não resolvida pelo agente; seção 0.1, item 4):**
  - a F3 pede "taxas ±5%, CV ±10%, popularidade preservada";
  - num único nível curto, o ruído de amostragem já passa disso. Exemplos: C1 tem fração por modelo de 7,8% a 11,7% contra 10%, e CV por modelo de 0,84 a 1,19; no C9, a fração de lote ficou 0,279 contra 0,3;
  - o agente reporta as duas leituras: **realizado** (o nível, uma semente) e **processo** (média de 20 sementes, o que o gerador promete). Todas as cargas passam na leitura de processo; a leitura realizada falha em C6 (ordem de ranks vizinhos da cauda), C8 (razão pico/vale) e C9 (fração de lote) por ruído;
  - o Gabriel decide qual leitura o critério usa.

## D29 — Respostas do Gabriel às decisões do gate da F3 (2026-11-05, Gabriel; gate APROVADO)

1. **Conjunto de cargas:** aceita a proposta do relatório F03:
   - núcleo: C1, C2, C3, T1, C6, C7, C8, C9 (sobre C1 e sobre C6), T3;
   - controles: C4, C5;
   - análise: C11;
   - T4 com baixa prioridade; T5 fora como carga de memória.
2. **C10:** baixar Qwen2.5-14B-Instruct e Qwen2.5-32B-Instruct para o cache do cluster. O agente tinha escrito que o cluster não tem internet. **Errado:** o cluster tem acesso; a imagem é que força `HF_HUB_OFFLINE=1` (`docker/prism/Dockerfile:35`).
   - Download feito por um job sem GPU, `polyaxon/hf_download.sh` / `hf_download.yaml`, job `1f15aae8`. O modo offline só é desligado dentro desse script; os passos `ovl_*` continuam offline.
3. **T2:** o Gabriel aceitou os termos do LMSYS-Chat-1M no Hugging Face e passou um token de leitura.
   - O token está só em `~/.cache/huggingface/token` (modo 600) da máquina local, nunca no repositório nem no job. Os modelos Qwen não pedem token.
   - Dados em `/mnt/scratch/scheduler/datasets/lmsys_chat_1m/`.
   - Regra da T2 (agente): os 12 modelos com mais conversas, em ordem → `model_1..12`. Contagem por modelo = fração real × 2 req/s × 600 s; chegadas de Poisson sintéticas (o conjunto não tem tempos). Tamanhos do 1º turno de cada modelo, tokenizados com o tokenizador do Llama-3.1-8B.
   - Trace derivado em `polyaxon/traces/T2_lmsys.*`, no `.gitignore` (redistribuição proibida).
   - `pyarrow`, que só a leitura do parquet usa, ficou numa pasta temporária fora dos ambientes (o `opt-env` não foi alterado).
4. **Tamanhos realistas × T1:** opção (a). Manter os tamanhos do Azure LLM e usar C6, C7, C8 e T3 como teste da F4 (zero impasses, F4.5).
5. **Leitura do critério de estatísticas:** pelo **processo**, a média de 20 sementes (`workload_check.py`, leitura "process"). Os valores realizados de cada nível continuam reportados ao lado, como informação. O critério da F3 (taxas ±5%, CV ±10%, popularidade preservada) vale para o gerador, não para o ruído de amostragem de um nível de 600 s. A regra vale igual para todas as cargas, nesta fase e nas próximas.
6. **T1 no validador:** continua informativo; níveis com T1 ficam VALIDA. Motivo: a F1.1 mostrou que o T1 é um impasse criado pela política, com os workers ociosos e sem falha de código. O resultado é válido e mede o comportamento ruim da política.
   - Ressalva (agente): a seção 0.2 lista "travamento" como INVALIDA_SISTEMA. Vale para travamento de código (worker preso, driver), não para o T1.
   - Para distinguir os dois, o T1 exige GPU cheia, 0% de uso e workers no ramo ocioso. Um travamento com outra assinatura (sobretudo nas políticas novas da F4 em diante) ainda é investigado como INVALIDA_SISTEMA.
   - Todo relatório traz o tempo congelado T1 por nível.

## D30 — Drenagem com prazo removida: a desativação de uma vítima é só preemptar ou não (2026-11-05, Gabriel)

- **Contexto:** ao preparar a apresentação da F6a, os logs da triagem (trace real, `T1` ts1, S3 `k_A`=5, job `21f31370`; `polyaxon/apresentacao_prazo_figs.py`) mostraram:
  - a drenagem de 15 s (`PRISM_SWAP_DRAIN=1`) chegava quase sempre ao teto: mediana de 15,0 s e p90 de 15,5 s (52 rotações EDF, 40 LVF). Durante a drenagem o worker continuava servindo a fila de espera, inclusive com novos prefills;
  - da decisão de rotação até a vítima sair: mediana de 22,7 s e p90 de 88 s (EDF); 16,5 s e 55 s (LVF). Da decisão até o modelo que entra ficar pronto: 16,8 s e 12,6 s (mediana), contra o `Ĉ_at` de ~1,4 s que a A2.1 usa;
  - com prazos de 0,7–7 s, a drenagem protege a vítima à custa de quem entra: a requisição que motivou a troca já está perdida quando a memória é liberada.
- **Origem da drenagem:** desenho de 22/10 (troca por throughput, 15 s fixos, nunca variados). Em 28/10, com o critério por throughput e sem prazos, a drenagem empatou ou ganhou um pouco da variante sem drenagem (P0D0); o resultado continua válido para aquela pergunta, não para políticas por prazo.
- **Decisão (Gabriel):** tirar a drenagem com prazo, inclusive do código. A desativação de uma vítima passa a ter só duas opções:
  - **não preemptar** (`PRISM_SWAP_PREEMPT=0`, padrão): as requisições aceitas e não iniciadas voltam na hora para a fila do modelo; o lote em execução (KV já na memória) termina, sem limite de tempo;
  - **preemptar** (`PRISM_SWAP_PREEMPT=1`): o lote em execução também é retirado e recomputado depois.
- **Código** (branch `apresentacao-prazo`, sem commit):
  - `scheduler.py`: removido o bloco de drenagem de `handle_deactivate_request` e o parâmetro `deadline` de `_run_to_completion_normal`;
  - `io_struct.py` (`DeactivateReqInput`) e `action.py` (`DeactivateAction`): removido `drain_timeout`;
  - `simple_global.py`: removidos `PRISM_SWAP_DRAIN` e `PRISM_SWAP_DRAIN_TIMEOUT`; se uma suíte ainda definir um deles com valor ≠ 0, o controlador aborta com erro (para nenhuma suíte antiga rodar outra configuração sem perceber). A reserva de memória do modelo que entra na EDF/LVF passa de 15 s + 15 s de drenagem para 15 s (`SWAP_RESERVATION`);
  - testes: `tests/policy/test_deadline.py` (rotação sem drenagem; variáveis antigas dão erro) e `tests/robustness/test_deactivate_evict_stuck.py`. 46 testes passam.
  - `extract_ovl.py` e `activation_cost.py` continuam lendo o evento `drain` dos logs antigos.
- **Efeitos:**
  - **A0.3** passa a ser a troca por throughput **sem preempção e sem drenagem** (o antigo P0D0). As execuções da A0.3 anteriores à D30 (F0.4, F6a e 28/10) não se comparam com as novas;
  - as suítes antigas com `PRISM_SWAP_DRAIN=1` (`polyaxon/configs/`, gitignored: F0.4, F6a, 28/10) não rodam mais; para reproduzi-las, usar o commit anterior à D30;
  - os resultados da F6a continuam válidos como estão (rodaram com drenagem, como diz o relatório); a apresentação de 2026-11-05 registra isso;
  - na A3 e na A9.2, o custo da troca inclui o tempo para a vítima terminar o lote em execução (zero com preempção), e a decisão "preemptar ou não" pode ser tomada por troca (A3, `PLANO_AGENTE.md`).
- **Pendente:**
  - medir o tempo de saída da vítima sem drenagem;
  - verificar se a reserva de 15 s basta: se a vítima demorar mais para terminar o lote, o modelo que entra perde a prioridade na memória, que é o desvio corrigido na D26;
  - nenhuma execução nova foi feita.
- **Numeração:** a D28 e a D29 estão no worktree da F3 (`f3-cargas`), ainda sem commit; esta decisão é a D30 para não colidir.

## D31 — Próximos passos depois da F6a: F6b (custo da troca e repetição sem drenagem) e prioridades da F6 (2026-11-05, Gabriel)

- **Contexto:** na preparação da apresentação da F6a (`reports/2026-11-05 APRESENTAÇÃO Políticas por prazo no Prism, primeira rodada (SGLang).md`), o agente propôs os próximos passos com a evidência de cada um, e o Gabriel aprovou. Achados usados:
  - uma troca real leva 16,8 s (EDF) e 12,6 s (VLT) da decisão até o modelo que entra ficar pronto, na mediana; só a ativação, ~4–5 s sob carga, contra o `Ĉ_at` de ~1,4 s (preliminar: 1 execução, ligação decisão → ativação pelo próximo evento);
  - a drenagem de 15 s chegava quase sempre ao teto, e por isso foi removida (D30).
- **Decisão (Gabriel):**
  1. **Nova fase F6b** (`PLANO_AGENTE.md`, seção 6):
     - medir o custo real da troca nos dados existentes, ligando decisão e ativação pelo log de decisões;
     - instrumentar a reserva de memória;
     - **repetir a triagem da F6a sem drenagem** (C1 e T1, 2 repetições, mesmas linhas de base e níveis de SLO, sem o ciclo de 1 s);
     - o braço com preempção fica como pergunta ao Gabriel antes de submeter;
     - gate [HUMANO].
  2. **Prioridades da F6**, cada uma ligada a uma lição da F6a: custo real da troca → A3.1 (perda esperada) → A2.3 (residência preditiva, com a A0.2 como barra) → A4 → classes de prazo (A7/F8) → A9.2 (prioridade menor).
  3. **O ciclo de 1 s e a A5 ficam fora de prioridade.**
  4. **O pior modelo (justiça) é observação, não objetivo das políticas.** Revisa o último item da D27 ("a justiça como objetivo possível da A7/F8").
- **Ordem da F6b em relação à F3 (gate em aberto) e à F4:** não definida; o Gabriel decide.
- **Limitação declarada:** o braço "com drenagem" não pode mais rodar (código removido, D30). A comparação F6a × F6b é feita só pela diferença pareada contra a melhor linha de base de ociosidade do mesmo job (A0.1/A0.2 não mudaram), nunca pelos valores absolutos (regra 3).
- **Numeração:** D28 e D29 estão no worktree da F3, sem commit.

## D32 — F6b dissolvida em F5/F6, preempção nas políticas por prazo, família A10, métricas novas e SLOs maiores (2026-11-05, Gabriel)

- **Contexto:** revisão dos próximos passos da D31, pedida pelo Gabriel. Onde encaixar cada item no plano foi escolha do agente, com o Gabriel tendo dito "onde você achar melhor".
- **Decisões do Gabriel e onde entraram:**
  1. **Testar as políticas por prazo também com preempção.** A repetição da triagem da F6a sem drenagem passa a ter os dois braços, sem e com preempção, e entra na **F6**, como primeira tarefa (F6.0). Não é mais uma fase própria: a F6b sai da tabela de fases. Matriz: C1 e T1, 2 repetições, 17 níveis por job (A0.1, A0.2, A0.3, A0.3p, `fair` + A2.1 e A9.1 × 3 níveis de SLO × {P0, P1}), 4 jobs.
  2. **Políticas que combinam throughput, prazo e tamanho da fila.** Nova família **A10** (seção 4 do plano): A10.1 (filtro por prazo, escolha por throughput), A10.2 (pontuação ponderada), A10.3 (fila ponderada pela folga). Entra na F6 como F6.13 e como prioridade 3, em paralelo à A3.
  3. **Análise de violações inevitáveis levando em conta a rotação.** Seção 7 do plano: inevitável pela ativação (havia memória livre) × inevitável pela rotação (era preciso tirar alguém, prazo < `Ĉ_rot`) × evitável só com residência prévia × evitável. Implementação na **F5.0**, porque a campanha de linhas de base precisa dela, com a classificação antiga ao lado.
  4. **Métrica de ociosidade da GPU, baseada nos modelos em execução e na carga deles.** Seção 7: residência ociosa com demanda pendente (GB·s de modelos sem trabalho enquanto outro espera) e ociosidade esperada pela carga (`ρ_m` = taxa × tempo de serviço dedicado) × observada (`nvidia-smi`). Implementação na F5.0.
  5. **Apresentações e relatórios sempre comparam com as políticas anteriores:** a melhor ociosidade de valor arbitrário e a troca por throughput sem e com preempção (A0.3 e a nova linha de base **A0.3p**), com TTFT p50 e p90 nas tabelas. Nova regra 0.10 do plano.
  6. **Objetivo duplo: SLO e TTFT.** Uma política é descrita como melhor quando melhora a fração dentro do SLO ou o TTFT p50/p90 sem piorar o outro (seção 7 e seção 7.1, que antes exigiam só a vista combinada). Interpretação do agente para "tornando mais justo nossa versão": uma avaliação mais justa das nossas políticas, que não olhe só o atingimento de SLO. Confirmar com o Gabriel se a intenção era outra.
  7. **SLOs maiores, em sobrecarga, com base no tempo de rotação.**
     - nova família **S6**: `SLO_TTFT = k_R · Ĉ_rot(m)`, com `Ĉ_rot` medido na F5.0;
     - proposta para as execuções das políticas por prazo: S3 `k_A` = 5 (continuidade com a F6a) e S6 `k_R` ∈ {1, 2}, a confirmar depois da F5.0;
     - o S2 `k_T` = 10 continua só nas métricas (reavaliação depois da execução).
- **Também passa para a F5.0 (antes era a F6b):** a medição do custo real da troca (`polyaxon/swap_cost.py`, só análise) e o registro de reservas de memória vencidas. Motivo: a família S6 e a classificação nova de violações dependem de `Ĉ_rot`.
- **Ordem:** F5.0 antes da campanha da F5; F6.0 como primeira tarefa da F6. As dependências de fase não mudam (F4 → F5 → F6).
- **Mudança de critério registrada:** a regra "melhor = melhora a vista combinada" da seção 7.1 passa a ser o objetivo duplo. A mudança é do Gabriel; o agente não alterou nenhum outro critério de aceitação.

## D33 — Objetivo inclui a cauda de espera: nenhuma requisição esperando absurdamente mais que as outras (2026-11-05, Gabriel)

- **Contexto:** sobre o item 6 da D32 ("tornando mais justo nossa versão"), o Gabriel confirmou a leitura do agente (avaliar também pelo TTFT, não só pelo SLO) e acrescentou: não pode haver requisições esperando absurdamente mais que outras. Os níveis de S6 propostos (`k_R` ∈ {1, 2}) também foram aceitos como proposta, a fechar depois da F5.0.
- **Decisão:** o objetivo das políticas (seção 7 do plano) passa a ter três critérios, sempre juntos:
  1. fração dentro do SLO (três vistas);
  2. TTFT típico (p50, p90);
  3. **cauda de espera**: TTFT p99, TTFT máximo e fração de requisições com TTFT acima de 10× a mediana da execução, contando as não atendidas como espera até o fim do prazo extra; mais a pior espera pelo 1º token por modelo.
- **Regra:** uma melhora no SLO ou no TTFT típico conseguida à custa de uma cauda absurda não conta como ganho, e isso é dito explicitamente.
- **Distinção:** o critério 3 é sobre **requisições**. A justiça entre **modelos** (fração no SLO do pior modelo) continua só como observação (D31).
- **Onde entrou:** seção 7 e 7.1, regra 0.10 (tabelas), F5.0 (`report_tables.py`), F6.0 (métricas e sinal), seção A10 (avaliação), `TODO.md` (F5.0e, prioridades da F6).
- **Escolha do agente:** o limiar de "absurdo" de 10× a mediana. É ajustável no gate da F5, com os dados da campanha.

## D34 — Desenho da A1 e parâmetros `b`, `Δ_imp`, `T_min` (2026-11-05, agente, F4.1–F4.3; gate automático)

Numeração: D30–D33 vieram do worktree `apresentacao-prazo` (juntadas a este registro em 2026-11-06, no início da F5); a F4 começa em D34.

- **A1.1 soma o piso do kvcached.** O kvcached nunca mapeia KV nos últimos 5% da GPU (`GPU_UTILIZATION = 0.95`, `kvcached/slab_allocator.py:_physical_free_size`; 7,2 GB numa H200). A conta do controlador (R2.1) não vê esse piso e ativa com `W + 1 GB`, ou seja, pode encher a GPU de pesos até ~1 GB livre, abaixo do piso: nenhum modelo recebe página de KV, e é o T1 (F1.1 já tinha concluído que "a A1.1 deve somar a reserva do kvcached"). Regra: ativar `m` só se `livre − ativações pendentes ≥ W_m + folga + max(KV de ativação, K_min(m)) + 0,05·GPU`. O piso só entra com a A1.1 ligada (`PRISM_KV_FLOOR_FRAC`, padrão 0,05); com `PRISM_KV_RESERVE_REQS=0` a regra é a de antes. A regra vale para toda estratégia (A0.1 `idle`, A0.3 `throughput`, `edf`/`lvf`); na F6a a A1.1 só existia no `edf`/`lvf` e estava desligada (D25), então nenhuma execução anterior muda de sentido.
- **`b = 4`** (`PRISM_KV_RESERVE_REQS`): mediana do lote em execução por modelo residente com fila, nos níveis da A0.1 sem impasse (C1: 3–6; T1: 2–9; `reports/data/F04/calib/calib_niveis.tsv`, `polyaxon/f4_calib.py`). Com os tamanhos do Azure (prompt + saída ~1250 tokens) e o 8B (128 KiB/token), `K_min` ≈ 0,6 GB < 1 GB: o termo que pesa é o piso. Alternativas: `b = 8` (p75), `b = p90` (16–26, ~2,4–4 GB a mais por ativação, que tira residência de todos os modelos sem motivo medido).
- **A1.2 pelo contador de tokens.** O detector olha a soma dos `served_tokens` (as engines informam a cada 1 s), não as conclusões: nos níveis sem impasse há trechos de até 281 s sem nenhuma conclusão (saídas longas, ciclos de retirada), mas a GPU nunca fica parada. O relógio só corre enquanto algum modelo ativo tem fila de espera e não há ativação nem desativação em andamento (nem ação da estratégia no mesmo ciclo). Vítima: o ativo de menor valor por GB pelo critério da A0.3 (`_keep_value`, o mesmo código), com residência ≥ `T_min`; empate: o ativo há mais tempo. Desativação com preempção (as requisições dele não progridem). Cada disparo vai para o log de decisões (`notes: deadlock`, com o estado de todos os candidatos) e para o log de texto (`Reason: deadlock break for <modelo>` → `evict_deadlock` no `events.csv`).
- **`Δ_imp = 30 s`** (`PRISM_DEADLOCK_S`): nos 74 níveis VALIDA sem impasse, o trecho mais longo com GPU > 100 GB, 0% de uso e requisição pendente é 13 s; nos 7 com impasse, 433–1120 s. 30 s é > 2× o maior trecho normal e dispara em 30–35 s (ciclo de 5 s). Alternativas: 15 s (perto do normal), 60 s (perde 1 min de carga por impasse).
- **`T_min = 10 s`** (`PRISM_MIN_RESIDENCY`), o valor da D25: acima do p99 do `Ĉ_at` do 8B (8,3 s). Vale para todo caminho de despejo (ociosidade, pressão, `fair`, troca por throughput com `max(PRISM_SWAP_MIN_RESIDENCY, T_min)`, `edf`/`lvf`, detector).
- **O que conta como impasse no critério F4.5 (proposta para revisão do Gabriel):** nível com T1 congelado ≥ 60 s (métrica `t1_frozen_s` do validador). A distribuição observada é bimodal (≤ 13 s × ≥ 433 s), então o limiar não decide nenhum caso real. Não muda a classificação VALIDA do validador (D29, item 6).
- **"Com A1"** = as três juntas (A1.1 + A1.2 + A1.3), como a F4.4 pede ("sem, com A1").

## D35 — Base de código da F4: código da D30 trazido para este worktree (2026-11-05, agente)

- A F4 compara A0.1 e A0.3 com e sem A1, e desde a D30 a A0.3 é a troca por throughput **sem** drenagem. O código da D30 (remoção da drenagem: `scheduler.py`, `io_struct.py`, `action.py`, `simple_global.py`, testes e docs) estava só no worktree `apresentacao-prazo`, sem commit.
- O agente aplicou aqui só a parte de código e docs da D30 (diferença do worktree contra o commit `9d1768d`; 18 trechos, aplica sem conflito). Plano, TODO e decisões D30–D33 ficam no outro worktree, que ainda estava sendo editado.
- Consequência: quando os dois ramos forem juntados, os trechos da D30 são idênticos dos dois lados.

## D36 — Correção de medição do V13 e P15 (2026-11-06, agente, F4)

- **V13:** o validador comparava a linha `GPU 0, mem X` do log (memória **disponível**: livre − ativações pendentes,
  R2.1) com a memória livre do `nvidia-smi`. Com ativações pendentes por muito tempo, a diferença é a memória
  prometida, não erro de medição (`f4-c1n14-3` A0.3_A1: 16,6 GB contra 0,68 GB com a memória livre de fato).
  Correção: soma de volta o `pending_gb` do ciclo do log de decisões (pareado por tempo). O limite (2 GB) não muda.
  Revalidação: F4 inteira, F3 e F6a; só aquele nível muda (INVALIDA_SISTEMA → VALIDA). Alternativa rejeitada: manter o
  nível como inválido, o que descartaria uma execução sem falha.
- **P15:** workspace do flashinfer de 512 MB para `Qwen2ForCausalLM` (`PRISM_FLASHINFER_WS_QWEN2_MB`, 0 = antigo),
  como as versões seguintes do SGLang; só o C10 usa Qwen. Reexecução dos dois jobs do C10.
- **Ressalvas que vão ao Gabriel (gate da F4):** critério de impasse T1 ≥ 60 s (D34); leitura do critério "sem piora
  nos cenários sem impasse" (por carga de controle × por braço), porque a A0.3 + A1 piora o T3 (folga de 3 GB +
  piso de 7,2 GB somados; relatório F04, anomalia 4).

## D37 — Respostas do Gabriel às três questões do gate da F4 (2026-11-06, Gabriel)

1. **Impasse = T1 ≥ 100 s** (tempo congelado do validador: GPU > 100 GB, 0% de uso, com requisição que fica sem
   resposta já esperando). Substitui a proposta de 60 s da D34. Um travamento que o detector A1.2 quebra em ~30 s
   (C1 com 14 modelos: T1 de 30–34 s) não conta como impasse; nenhum dos 46 níveis com A1 chega perto de 100 s, e os
   impasses sem A1 têm 433–1120 s.
2. **Critério "sem piora nos cenários sem impasse": leitura (b)**, por braço: todo braço que não travou entra, o que
   inclui a A0.3 em todas as cargas. (O Gabriel respondeu "use your suggestion"; o agente não tinha recomendado uma
   leitura explicitamente e entendeu a (b), a que testa o custo real, junto com a correção da folga do item 3. Se a
   intenção era a (a), o gate muda.)
3. **Folga da A0.3 com A1 (A0.4):** recomendação do agente aceita: com A1 ligada, a folga de ativação passa a 0 (o piso
   do kvcached da A1.1 faz o papel dela), ou seja, **A0.4 = A0.3 + A1 com `PRISM_ACTIVATION_HEADROOM_GB=0`**, sujeito à
   verificação pareada: T3, C3, C7 e C6 × {A0.3; A0.3 + A1 com folga 3; A0.3 + A1 com folga 0} × 2 repetições
   (`polyaxon/f4_folga_suites.sh`, driver `bash polyaxon/f4_driver_start.sh folga`, 8 jobs).

## D38 — Gate da F4 aprovado com a lacuna da A0.4 declarada (2026-11-06, Gabriel)

- O Gabriel aprovou o gate da F4 ("commit and go to the next stage") na opção (i) do relatório F04: a A0.4
  (A0.3 + A1 com folga 0) foi verificada em T3, C3, C7 e C6; nas outras seis cargas (C1n8, C1n14, C2, T1, C8, C10)
  ela não foi rodada na F4 e entra na campanha da F5, que roda a A0.4 em todas as cargas.
- Valem para a F5 em diante: A1 ligada em toda política (`PRISM_KV_RESERVE_REQS=4 PRISM_DEADLOCK_S=30
  PRISM_MIN_RESIDENCY=10`), impasse = T1 ≥ 100 s (D37), A0.4 = `PRISM_EVICTION=throughput PRISM_SWAP_PREEMPT=0
  PRISM_ACTIVATION_HEADROOM_GB=0` + A1. Os padrões do código continuam os do Prism publicado (regra 0.4); a A0.1 sem
  A1 continua como referência.

## D39 — Escopo da campanha da F5 e base do S6 (2026-11-06, Gabriel)

1. **Configurações (5):** A0.1 sem A1 (referência do travamento); A0.1 + A1; A0.2 + A1 (limiar de 10 s); A0.4
   (troca por throughput sem preempção, `PRISM_ACTIVATION_HEADROOM_GB=0` + A1); A0.4p (idem com preempção). A0.3 com
   folga fixa de 3 GB fica fora. Em todas as configurações com A1, a reserva de KV é a dinâmica da A1.1 (piso do
   kvcached + KV de `b` requisições); "folga 0" quer dizer só sem a folga **fixa** de 3 GB (D37).
2. **Cargas:** opção (B): varredura de `ρ_mem` 1,07 / 1,5 / 2,0 no C1 e no C6; as outras cargas no nível aprovado;
   **3 repetições**. O critério C-V1 da seção 3.2 (padrão 5) passa a 3 na F5 por decisão do Gabriel.
3. **Base do S6:** testar as duas, primeiro a **sem preempção** (C_rot medido com a vítima terminando o lote: 8B
   p50 15,7 s), depois a com preempção (6,4 s).
4. **Antes de tudo:** confirmar se o nó ainda dá erro de driver do kvcached com 8 jobs simultâneos (regra 2 do
   CLAUDE.md: no máximo 3, por causa de 30/10). Se não der, a campanha pode usar mais jobs. O teste é a única exceção
   autorizada à regra até o resultado.
5. **Adendo (Gabriel, mesmo dia):** se o teste de concorrência mostrar que 8 jobs simultâneos rodam sem erro de
   driver e sem distorcer as métricas, a F5 volta a **5 repetições** (C-V1 = 5, o padrão do plano). Com 3 jobs, fica
   em 3 repetições.

## D40 — Teste de concorrência: 8 jobs simultâneos continuam inviáveis; F5 com 3 jobs e 3 repetições (2026-11-06, agente, sobre a D39)

- **Teste** (`polyaxon/f5_conc_test.sh`, `reports/data/F05/conc/`): 8 jobs iguais ao mesmo tempo (C1 `ovl_mem` 0,2
  com A0.4 e com A0.1 + A1; 17:30–18:40 UTC), depois 3 jobs com a mesma suíte (18:40–19:06 UTC).
- **Erros:** com 8 jobs, 5 de 16 níveis (31%) caíram no erro de driver do kvcached (`cuMemSetAccess ... out of
  memory`): 2 nem subiram (3 tentativas cada, jobs `f5-conc8-7/8`) e 3 deram K1 no meio da execução. Com 3 jobs, 0 de 6.
  Mesmo quadro de 30/10 (38% com 4 jobs).
- **Distorção nos níveis válidos:** TPOT médio +40% (A0.4: 59 → 83 ms; A0.1 + A1: 76 → 109 ms, com níveis de até
  252 ms), TTFT p50 de 0,9 para 21 s na A0.1 + A1, SLO combinado da A0.4 de 25,5% para 15,8%. Mesmo sem erro, o nó
  com 8 jobs mede outra coisa.
- **Consequência:** a regra 2 do CLAUDE.md (no máximo 3 jobs do Prism) continua; pelo adendo da D39, a F5 fica com
  **3 repetições** (C-V1 = 3).

## D41 — V11: parte da taxa não se aplica aos níveis dedicados (2026-11-07, Gabriel, opção (a))

- Num nível dedicado (`<nível>_ded_<modelo>`, base do S2/S2M) o gerador envia só as requisições de um modelo; com
  popularidade que deriva (C6), rajadas (C7), curva diurna (C8) ou trace (T3, T2), a última requisição desse modelo
  chega bem antes do fim da janela, e a comparação "taxa até o último envio × taxa na janela" (±5%) falha sem que nada
  tenha dado errado (atraso de envio p99 ≤ 0,07 s nos 10 níveis afetados).
- `validate_run.py`: nos níveis dedicados, o V11 fica só com o atraso de envio (p99 ≤ 1 s); a parte da taxa é N/A,
  como o V12 já era. Nos níveis normais nada muda.
- Revalidação: 62 de 62 níveis dedicados da F5 VALIDA (antes 52). A mudança só pode transformar FALHA em OK em níveis
  dedicados; os 48 dedicados da F2 já eram todos VALIDA.

## D42 — Duas bases do S6: `S6` sem preempção (testada primeiro) e `S6P` com preempção (2026-11-07, agente, sobre a D39 item 3)

- **`S6`** (`SLO_TTFT = k_R · Ĉ_rot(m)`): `Ĉ_rot(m)` = mediana medida das rotações em que a vítima termina o lote (modo
  `finish` do `polyaxon/swap_cost.py`), pelo tamanho do modelo que entra: 3B 15,8 s, 8B 15,7 s, 14B 30,4 s, 32B 73,7 s
  (n = 35 / 4196 / 69 / 9). É a base que a D39 manda testar primeiro.
- **`S6P`**: a base da F5.0b, com preempção: `Ĉ_rot(m)` = 5,0 s (saída com preempção + espera pelo ciclo) + `Ĉ_at(m)`
  (8B 6,4 s).
- TPOT nas duas: `k_D` × base do S2. As duas bases ficam em `reports/registro/c_rot.json` (chave `sem_preempcao` e
  `overhead_s`); um tamanho de modelo sem medição sem preempção dá erro, não um valor inventado.
- Nenhuma execução nem relatório usou o nome `S6` antes desta mudança (só o commit 506decf), então a troca de
  significado não afeta resultados. Teste: `tests/metrics/test_slo_metrics.py`.

## D43 — Classificação nova das violações de TTFT (F5.0c): escolhas de medição (2026-11-07, agente)

- Implementada em `polyaxon/slo_metrics.py` (`classify_ttft_miss`; colunas `viol_ttft_inev_ativacao`,
  `viol_ttft_inev_rotacao`, `viol_ttft_evit_residencia`, `viol_ttft_evit`; a antiga `viol_ttft_inevitavel/evitavel` fica
  ao lado). Os quatro grupos são disjuntos e somam as violações de TTFT (verificado em 16 níveis da F4).
- **Memória livre na chegada:** a última leitura do controlador (`free_mem` no `events.csv`, uma por ciclo) comparada
  com pesos + 1 GB de KV de ativação. É um limite inferior da necessidade real (a A1.1 soma o piso do kvcached e o KV de
  `b` requisições): "cabe" sai generoso, o custo menor (`Ĉ_at`) é usado mais vezes, e os grupos inevitáveis ficam, se
  muito, pequenos demais.
- **`Ĉ_rot` da classificação:** a base com preempção (S6P, a rotação mais rápida que o sistema faz hoje), para todas as
  configurações, mesmo as sem preempção: "inevitável" quer dizer que nenhuma política evitaria.
- **Um ciclo:** espaçamento mediano das leituras `free_mem` do nível (5 s, `PRISM_SCHEDULE_INTERVAL`).
- **TPOT (seção 7.1):** `viol_tpot_em_troca` = violações de TPOT cuja decodificação se sobrepõe a uma transição de
  modelo (`act_req` → `act_ok`, despejo → `deact_ok`), sobre as requisições da vista só TPOT. O limite de memória livre
  da seção 7.1 fica para quando houver um valor proposto.

## D44 — Ociosidade da GPU (F5.0d) e base dos modelos extras da varredura de `ρ_mem` (2026-11-07, agente; item 2 a confirmar com o Gabriel)

1. **Implementação:** `polyaxon/gpu_idle.py` (`level`, `table`), teste `tests/metrics/test_gpu_idle.py`. Colunas:
   `ocio_residente_demanda` (GB·s de modelos ativos sem requisição no sistema, só nos instantes em que um modelo não
   ativo tem requisição, sobre os GB·s da GPU; só pesos), `frac_tempo_demanda`, `ocio_esperada`, `ocio_observada`
   (1 − utilização do `gpu.csv`), `ocio_politica` = observada − esperada, `trocas_min`. Janela = duração da carga.
2. **`ρ_m` com duas definições de tempo de serviço (a confirmar).** A da seção 7, `ρ_m = λ_m · E[S]` com `E[S]` = latência
   média na GPU dedicada (`pool_servico_medio_s`), conta cada requisição de um lote como uma GPU inteira (lei de
   Little: é o número médio no sistema, não a ocupação). No C1, cada 8B a 0,2 req/s dá `ρ` ≈ 0,79, dois residentes já
   passam de 1, e `ocio_esperada` sai ≈ 0 em todo nível sobrecarregado. Por isso há uma segunda coluna,
   `ocio_esperada_gpu` / `ocio_politica_gpu`, com `E[S]` = segundos de GPU ocupada por requisição na GPU dedicada
   (utilização do `nvidia-smi` integrada no nível dedicado ÷ requisições atendidas, `pool_gpu_s_por_req`), que leva o
   lote em conta (8B do C1: `ρ` ≈ 0,28). As duas ficam nas tabelas até o Gabriel escolher; a proposta do agente é a
   segunda. Apoio na literatura (busca feita depois da regra de 2026-11-07): MuxServe (R5, §3.2, Algoritmo 2)
   mede a necessidade de computação de um modelo pela fração da GPU cuja vazão com lote cobre a taxa dele.
3. **`latencia_ded.json` ganhou quatro campos** (`servico_medio_s`, `pool_servico_medio_s`, `gpu_s_por_req`,
   `pool_gpu_s_por_req`; `polyaxon/iso_dedicated.py`). Regerado dos mesmos 10 jobs dedicados (`f2-ded-{a,b,c}`,
   `f5-ded-{c10,c6,c7,c8a,c8b,t2,t3}`): todos os campos antigos idênticos (0 diferenças), só os novos acrescentados.
4. **Modelos sem nível dedicado** (modelos 11–19 da varredura de `ρ_mem` 1,5 e 2,0, `PRISM_OVL_N` 14 e 19): usam a
   entrada de um modelo idêntico (mesmo `model_path`) da carga. As bases do S2/S2M (`pool_*`) já são as mesmas para todos
   os idênticos (D21), então nada muda para os modelos 1–10. O `λ_m` vem sempre do próprio nível, não do dedicado.

## D45 — Ciclo de vida explícito das instâncias no controlador e fim da reserva de troca por evento (2026-11-07, Gabriel; implementação do agente)

Origem: auditoria das máquinas de estado implícitas do `f3-cargas` contra o Prism original. Com o worker pool,
`/activate` e `/deactivate` respondem assim que o GPU scheduler recebe o pedido, então o controlador marcava o modelo
`ACTIVE`/`INACTIVE` no envio, e o "carregando" e o "saindo" viviam espalhados (ativações pendentes com prazo de 120 s,
`active_since`, reservas por relógio, contadores no GPU scheduler).

1. **Estados explícitos** (`state.py` `ModelState`, que já declarava `ACTIVATING`/`DEACTIVATING` sem usá-los):
   `ACTIVATING` do envio da ativação até o evento `model_activated` do GPU scheduler; `DEACTIVATING` do envio da
   desativação até o evento novo `model_deactivated` (só para desativações não superadas); `model_lost` leva a
   `INACTIVE`; transição sem evento por 120 s é dada como concluída. O GPU scheduler passou a mandar `model_activated`
   também quando o modelo já estava servido (antes a ativação ficava pendente até os 120 s).
2. **Mesma visão para as políticas:** `ACTIVATING` conta como ativo e `DEACTIVATING` como inativo
   (`ModelInstanceState.serving`), como antes. O limite de rotações em voo (EDF/LVF) continua contando só "vítimas
   despejadas e ativação ainda não enviada"; um modelo carregando não conta. O detector de impasse (A1.2) conta
   `ACTIVATING` como transição (já contava as ativações pendentes) e **não** conta `DEACTIVATING`. O log de decisões
   mantém `state` com a visão de dois estados (o `f4_calib.py` depende dele) e ganha `lifecycle` com o estado exato.
3. **Mudanças de comportamento aceitas:**
   - **Residência** (A1.3, `PRISM_SWAP_MIN_RESIDENCY`, `fair`) conta a partir do carregamento, não da decisão: um modelo
     carregando não pode ser despejado por esses critérios.
   - **Reserva de troca** (`PRISM_SWAP_RESERVATION_END`, padrão `event`): termina quando o modelo para quem as vítimas
     saíram é ativado, ou quando ele não tem mais requisições esperando (nota `reservation_dropped`), ou após
     `PRISM_SWAP_RESERVATION_MAX_S` (120 s, nota `reservation_lapsed`); enquanto dura, não se faz nova troca para ele
     (throughput e EDF/LVF). Motivo: sem preempção a vítima leva 20,1 s (p50, 8B; p90 47 s) para sair (F5.0a), mais que
     os 15 s fixos, então a reserva acabava antes de a memória ficar livre, outro modelo podia pegá-la, e o limite de
     uma rotação em voo deixava de valer. `timer` restaura os 15 s anteriores. Com preempção a vítima sai em ~0,6 s e
     nada muda na prática.
4. **Mantido sem mudança (pedido do Gabriel):** um modelo que volta a ser pedido enquanto sai continua podendo ser
   reativado noutro worker. Cancelar a desativação fica como opção de política a avaliar (A11 no `PLANO_AGENTE.md`).
5. **Comparabilidade:** as configurações sem preempção (`PRISM_SWAP_PREEMPT=0`, ex. A0.3 e metade das suítes da F5.1)
   rodadas com este código não são comparáveis com execuções anteriores; comparar só dentro da mesma janela (regra 3).
   Para reproduzir o comportamento anterior: `PRISM_SWAP_RESERVATION_END=timer` (a residência a partir do carregamento
   não tem chave).
6. **Literatura** (`reports/registro/referencias.md`): estado explícito de cargas/descargas atualizado pelo resultado
   reportado pelo worker, com prazo só como limite de segurança — Clockwork (R2, §4.4–4.5); reserva de memória do
   modelo que entra concedida/encerrada por evento (memória realmente liberada), não por tempo — SwapServeLLM (R3,
   §3.3–3.5); o Prism publicado não descreve estados de transição nem reserva, mas na migração espera "target is
   ready" (R1, §6.1).
7. **Código e testes:** `state.py`, `action.py`, `controller_global.py`, `gpu/gpu_scheduler.py`, `constants.py`,
   `decision_log.py`, `policy/simple_global.py`; `tests/controller/test_lifecycle.py` (13 testes) e a suíte existente
   (125 testes) passam.

## D46 — Campanha da F5 com 18 cargas (270 níveis) e `ρ_m` pelo tempo de GPU ocupada (2026-11-07, Gabriel)

1. **Cargas:** fica o conjunto gerado por `polyaxon/f5_suites.sh` (18 cargas × 5 configurações × 3 repetições = 270
   níveis, 54 jobs; a estimativa anterior de ~255 contava 17). Inclui C9 sobre C1 e sobre C6 como cargas separadas e a
   varredura de `ρ_mem` com 10/14/19 modelos no C1 (taxa por modelo fixa) e no C6 (taxa total fixa). Campanha iniciada
   às 13:36 UTC (`bash polyaxon/f4_driver_start.sh f5`; estado `reports/data/F05/camp/jobs.tsv`).
2. **Ociosidade esperada (fecha a D44 item 2):** a definição oficial de `ρ_m` usa como tempo de serviço os segundos de
   GPU ocupada por requisição na GPU dedicada (`pool_gpu_s_por_req`), que leva o lote em conta (apoio: R5 MuxServe).
   `polyaxon/gpu_idle.py`: `ocio_esperada` / `ocio_politica` / `rho_total` passam a ser esta definição; a do plano
   (latência média) fica como referência em `ocio_esperada_lat` / `ocio_politica_lat` / `rho_total_lat`.
3. **Pedido do Gabriel:** buscar outros artigos com métricas desse tipo (ociosidade, utilização, memória presa por
   modelos parados) para usar nas análises; resultado em `reports/registro/referencias.md`.
   Feito (agente, mesmo dia): lidos Aegaeon (R6), Serverless in the Wild (R7) e o Prism de novo (R1, adendo); o
   QLM (SoCC'24) e o WarmServe (arXiv 2512.09472) foram lidos e não definem métrica utilizável (só citam
   "utilização"). Métricas novas em `polyaxon/gpu_idle.py`: `ocio_residente_total` (tempo de memória desperdiçada,
   R7), `modelos_ativos_medio` / `modelos_ativos_esperado` / `modelos_residentes_medio` (contagem de modelos ativos,
   R6), `ocio_por_modelo` (R1).

## D47 — Orçamento de workers do kvcached no nó, além do limite de 3 jobs (2026-11-07, Gabriel, opção 1)

- **Fato:** na 1ª onda da campanha da F5 (13:36–14:57 UTC), 3 jobs do Prism ao mesmo tempo (C1 com 10, 14 e 19 modelos
  = 43 workers do kvcached no nó, um por modelo) deram K1 (`cuMemSetAccess ... out of memory` do driver CUDA): no
  `f5-c1n19-1`, 0 de 5 níveis válidos (A0.1 não subiu em 3 tentativas, os outros 4 INVALIDA_SISTEMA); no `f5-c1n14-1`,
  3 de 5 (A0.4 não subiu, A0.4p K1). O mesmo conjunto de 19 modelos, sozinho no nó (smokes `f5-smoke-1/2`), deu 6/6
  VALIDA; na F4, 3 jobs com até ~36 workers no total (C1 com 14 modelos ao lado de cargas de 10–12) rodaram limpos.
  Nenhum outro job do Prism estava no nó.
- **Leitura (hipótese, não provada):** o limite é o total de workers (processos com contexto CUDA e mapeamentos de
  memória virtual do kvcached) no nó, não o número de jobs.
- **Decisão (Gabriel):** `polyaxon/f4_driver.py` ganha `F4_MAX_WORKERS` (36 na campanha da F5,
  `polyaxon/f4_driver_start.sh f5`): um job só entra se a soma dos workers dos jobs ativos mais os dele cabe; fila
  estritamente em ordem (o 1º da fila espera, nada passa à frente). Os jobs `f5-c1n14-1` e `f5-c1n19-1` são refeitos
  inteiros como `-1b` (as 5 configurações na mesma janela, regra 3), no topo da fila. A ordem da fila dos jobs ainda
  não enviados põe cada carga de 19 modelos antes das menores (C5, C4, C10). Teste: `tests/controller/test_driver_budget.py`.
- **A verificar:** se a onda atual (C1 10 + C6 10 + C6 14 = 34 workers) e os jobs de 19 modelos com o orçamento ficam
  sem K1; se não, a hipótese está errada e o orçamento não resolve (ver as outras causas possíveis no relatório da F5).

## D48 — C1 com 14 e 19 modelos sozinho no nó e job interrompido no primeiro erro do driver CUDA (2026-11-07, Gabriel)

- **Fato (contra a hipótese da D47):** com o orçamento de 36 workers, a onda de 18:28–19:53 UTC (C1 com 14 + C1 com 19 +
  C5 = 35 workers) deu K1 de novo: `f5-c1n14-1b` 2/5 VALIDA, `f5-c1n19-1b` 1/5, e o vizinho `f5-c5-1` 1/5 (4
  INVALIDA_INFRA: a checagem de saúde depois do nível falhou). Já o C6 com 19 modelos ao lado de 14 outros workers (33)
  deu 5/5, e todas as outras cargas da 1ª repetição deram 5/5. Nos dois jobs do C1, a única configuração válida nos dois
  foi a A0.1 (sem A1, que trava e quase não troca de modelo); as que mais trocam (A0.4, A0.4p) falharam nos dois.
- **Leitura (hipótese):** o que quebra o driver é a taxa de mapeamentos de memória do kvcached no nó (C1 com todos os
  modelos sempre com tráfego troca 9–10 modelos por minuto), ou handles que vazam a cada `cuMemRelease` que falha, não o
  número de processos. Dois jobs assim estragam o nó para todos.
- **Decisão (Gabriel):**
  1. C1 com 14 e 19 modelos roda sozinho no nó (`F4_EXCLUSIVE='_C1n1[49]_'` no `polyaxon/f4_driver.py`: espera o nó
     vazio, e nada entra enquanto roda). Os 6 jobs (`f5-c1n14-1c`, `f5-c1n19-1c`, repetições 2 e 3) vão juntos no fim da
     fila. O orçamento de 36 workers da D47 continua para o resto. Refeito também `f5-c5-1` (`-1b`).
  2. **Erro do driver CUDA interrompe o job na hora** (`polyaxon/run_examples.sh`, `PRISM_K1_ABORT=1` padrão): um vigia
     procura o padrão do K1 do validador (`cuMem... out of memory`) no `server.log` a cada 5 s; ao achar, escreve
     `K1_ABORT`, tira o retrato dos mapas de memória, mata o servidor e o gerador de carga; nenhum nível começa depois,
     as tentativas de subida param, e a suíte sai com código 86 depois dessa configuração. O padrão não aparece em
     nenhum dos 40 níveis dos 8 jobs válidos. O job interrompido precisa ser refeito inteiro (regra 3).
- **A verificar:** se o C1 com 14 e 19 modelos sozinho fica sem K1 num job inteiro (o smoke sozinho, de 120 s, ficou).
  Se não ficar, o problema é dentro de um job (vazamento ou taxa de trocas) e a correção é no kvcached, não na fila.
- **Resultado (2026-11-09, agente):** campanha da F5.1 concluída às 23:57 UTC de 08/11: as 54 combinações carga ×
  repetição têm um job 5/5 VALIDA (270 níveis válidos; 61 jobs ao todo, 7 substituídos por refeitos: `f5-c1n10-1`,
  `f5-c1n14-1`, `f5-c1n14-1b`, `f5-c1n19-1`, `f5-c1n19-1b`, `f5-c5-1`, `f5-t3-1`). Os 6 jobs do C1 com 14 e 19 modelos
  sozinhos no nó deram 6/6 VALIDA (30 níveis) e levaram ~55–60 min cada, contra ~80 min com vizinhos. Depois da D48 houve
  um único K1 (`f5-t3-1`, na subida, 00:34 UTC de 08/11, ao lado de dois jobs de 10 modelos), interrompido em ~2 min.
  O `map_trace.log` desse K1 descarta o `vm.max_map_count` (maior processo com 2739 mapeamentos, limite 65530; o mesmo
  T3 válido na repetição 2 tinha 2752). A leitura que fica: o C1 com 14–19 modelos só quebra o driver quando roda ao
  lado de outro job que troca muito; sozinho, não.

## D49 — Gate da F5 aprovado; sem artigo parcial por enquanto; níveis de SLO da F6; P16 antes da F6.0 (2026-11-09, Gabriel)

1. **C-V2 (CV ≤ 15% entre repetições) falhou** (10 de 90 células, mediana 0,37; relatório F05): opção (c), aceito com a
   limitação declarada. As conclusões da F5 e das fases seguintes se apoiam nas diferenças pareadas no mesmo job, com
   IC 95% por bootstrap, não nos valores absolutos. Gate da F5 **APROVADO**.
2. **Artigo de resultados parciais: não fazer por enquanto.** O foco é conseguir bons resultados (F6 em diante). O item
   da F5.3 ("proposta de conteúdo do artigo parcial") e o ponto de decisão 4 do plano ficam adiados, sem data.
3. **Níveis de SLO das políticas por prazo (F5.2b):** aceita a proposta do agente: S6 `k_R` ∈ {1, 2, 4} (prazo de 1, 2 e
   4 rotações reais sem preempção; 8B ≈ 16, 31 e 63 s) e S3 `k_A` = 5 (continuidade com a F6a); S2 `k_T` = 10 continua
   nas tabelas como referência estrita, calculada depois da execução. **Hipótese do Gabriel, a testar na F6.0:** o S3
   `k_A` = 5 (prazo de ~7 s para um 8B) só faz sentido com preempção, porque sem preempção uma rotação real leva ~16 s
   (a vítima termina o lote) e o prazo vence antes. A F6.0 já roda com e sem preempção; a comparação do S3 `k_A` = 5
   entre os dois braços responde a hipótese.
4. **P16 primeiro:** investigar e corrigir a P16 (preempção deixa requisições "rodando" num modelo já inativo) antes da
   F6.0: um nível curto da A0.4p com `PRISM_TRACE_RIDS=1`, correção, teste unitário e verificação de que as entradas
   presas somem.
5. **Próxima sessão:** a F6 começa numa sessão nova (pedido do Gabriel), a partir do commit que registra esta decisão.

## D50 — F6.0: T3 entra, nova variante A9.2 do VLT ciente da residência (2026-11-09, Gabriel)

1. **T3 (trace Azure Functions) entra na F6.0** como quarta carga, ao lado de C1 com 10 modelos, T1 e C6 com 14
   modelos (pedido do Gabriel). Relevância pela F5: melhor linha de base 66% (S3 `k_A` = 5) e 71% (S6 `k_R` = 1) só
   TTFT, 29–54% das violações evitáveis.
2. **Nova política A9.2 na F6.0** (pedido do Gabriel: "o VLT não olhava se o modelo estava ativo ou não"): mesma medida
   de atraso para modelos ativos e inativos, com o tempo real da troca `Ĉ_rot` (F5.0a); ganho `G_m` do modelo que entra,
   custo `K_v` da vítima (inclui as requisições rodando que recomeçam com preempção), troca só se `G_m > K_v + margem`,
   vítimas pelo menor custo por GB. Desenho no `PLANO_AGENTE.md` (A9.2), apoio na literatura em R2 (Clockwork, adendo)
   e R8 (GreedyDual-Size). Código `policy/deadline.py` `_lvf_cost_aware`, `PRISM_EVICTION=lvf PRISM_LVF_COST_AWARE=1`,
   19 testes. Roda nos mesmos 4 níveis de SLO × {sem, com preempção}.
3. **Escopo (Gabriel, 2026-11-09, aceitando as recomendações do agente):** linhas de base A0.2+A1 e A0.4 em todo job
   como referência pareada (regra 3; A0.4p fora: código mudou com a P16, já é a pior na F5, e a pergunta do S3 compara
   cada política com e sem preempção no mesmo job); S6 `k_R` = 2 fora (níveis: S3 `k_A` = 5, S6 `k_R` = 1 e 4); **2
   repetições** (limitação declarada: IC por bootstrap sobre 2 pares é fraco; as conclusões da F6.0 são de triagem).
   Por job: 2 linhas de base + 3 políticas (A2.1, A9.1, A9.2) × 3 níveis × {sem, com preempção} = 20 níveis; 4 cargas
   × 2 repetições = 8 jobs, 160 níveis (`polyaxon/f6_0_suites.sh`, fila `polyaxon/configs/f60_queue.tsv`).
4. **Sem orçamento de workers na F6.0** (levantado pelo Gabriel; o agente concorda): o limite de 36 da D47 era hipótese e
   a D48 a contradisse (K1 com 35 workers; C6 com 19 modelos + 14 = 33 limpo; o K1 depois da D48 tinha ~32). O que
   quebra o driver é o C1 com 14–19 modelos ao lado de outro job que troca muito, e esse continua sozinho no nó. Na F6.0
   só a combinação C6 14 + T1 12 + T3 12 = 38 passaria de 36; ficam o limite de 3 jobs e a interrupção no K1.
   `f4_driver_start.sh f60` usa `F4_MAX_WORKERS=0`. Ganho: ~1,5–2 h (estimativa ~13–17 h em vez de ~15–19 h).
5. **Go (Gabriel, 2026-11-09):** smoke `f60_smoke_suite.tsv`, depois `bash polyaxon/f4_driver_start.sh f60`.
6. **Reexecuções sem perguntar (Gabriel, 2026-11-09):** a partir da F6.0, o agente refaz por conta própria um job
   inválido (K1, INVALIDA_*), sempre inteiro (regra 3), e depois avisa e reporta os erros (causa, motivo do validador,
   IDs). Substitui o "sem reexecução automática: o Gabriel decide" da F5.

## D51 — V13 alinha as séries de memória antes de comparar (2026-11-09, Gabriel)

- **Fato (P17):** no `f60-c1n10-1` (`9dea206c`), `edf_S6k1_p1` e `lvf_S3k5_p1` reprovaram só no V13 (mediana de
  |memória livre do controlador − nvidia-smi| = 2,18 GB > 2 GB). Causa: as duas séries estão 1–2 s defasadas e, nos
  níveis que trocam a cada poucos segundos, ~metade dos pares cai no meio de uma troca. Com o `gpu.csv` deslocado em
  +1 s, todos os braços com preempção dão 0,68 GB, a diferença constante de quase todos os níveis.
- **Decisão (Gabriel, "can do the alignment"):** V13 testa deslocamentos de −2 a +2 s (`V13_LAGS_S`) e usa o de menor
  mediana; registra o deslocamento (`lag_s`) e a mediana sem alinhamento. Tolerância (2 GB) e a verificação de memória
  acima do total inalteradas. Como o deslocamento 0 está incluído, nenhum nível antes válido passa a inválido.
- **Efeito:** `f60-c1n10-1` revalidado, 20/20 VALIDA, sem reexecução. Os jobs seguintes já usam o V13 alinhado.

## D52 — Gate da F6.0: objetivo é justiça sem grande perda de SLO; preempção só por troca; confirmação (2026-11-10, Gabriel)

1. **Objetivo (muda a D31 sobre justiça):** "alcançar justiça entre modelos sem grandes perdas de SLO". O pior modelo
   deixa de ser só observação: as políticas são julgadas pela justiça (pior quarto dos modelos, índice de Jain, p90 do
   pior modelo) junto com o SLO total e a cauda de espera (D33). Motivo: a F6.0 mostrou que a A0.2+A1 tem o maior SLO
   total deixando 20 de 96 pares modelo × job abaixo de 10% no prazo.
2. **Preempção:** não roda mais como chave global. Padrão de todas as políticas: sem preempção. Nova variante do VLT
   (**A9.4**) que decide preemptar ou não **a cada troca** (pela perda das requisições em execução da vítima, que a A9.2
   já mede). Preempção que guarda o KV (mudança no SGLang) fica fora por ora.
3. **Confirmação (aceita a proposta do agente, mais a A9.4):** A9.2 e A2.1 sem preempção, A9.4, contra A0.2+A1 e A0.4,
   nos níveis S3 `k_A`=5 e S6 `k_R`=1; A2.1 com preempção só no S6 `k_R`=4. Repetições e cargas a definir com o agente
   (o plano pede 5).
4. **Gate da F6.0: APROVADO** com as mudanças acima. Antes de implementar a A9.4 ou rodar qualquer coisa, o agente
   apresenta o que falta do plano.

## D53 — Triagem das políticas novas antes da confirmação (2026-11-10, Gabriel)

- Para gastar menos GPU, implementar várias políticas antes de rodar: A9.4 (VLT residência com preemptar ou não por
  troca, D52), A3.1 (despejo por perda esperada), A10.1 (troca por valor: filtro por prazo, escolha por throughput) e
  A2.3 (residência preditiva).
- **Primeiro uma triagem:** só as políticas novas e as linhas de base (A0.2+A1, A0.4), **2 repetições**, para ver quais
  interessam; com a análise, a confirmação de 5 repetições (F6.15) é montada depois.
- Antes de implementar: busca na literatura de cada política (registrada em `referencias.md`) e desenho curto para
  aprovação do Gabriel.
- **Desenhos aceitos (Gabriel, 2026-11-10):** A9.4 (preemptar por troca se salvas ≥ 3 × perdidas, R10 Shepherd), A3.1
  (ganho − perda em requisições viáveis > 0, vítimas por perda/GB), A10.1 (troca por throughput só para modelos com
  requisição viável depois de uma troca real), A2.3 (custo de despejo da A9.2 + chegada esperada durante a ausência,
  R7). **A A9.2 sem preempção entra como referência.** Por job: A0.2+A1, A0.4 e 5 políticas × {S3 `k_A`=5, S6 `k_R`=1}
  = 12 níveis; 4 cargas × 2 repetições = 8 jobs (`polyaxon/f6_16_suites.sh`, `f4_driver_start.sh f616`). Testes:
  `tests/policy/test_f616.py` (16), 175 no total.
- **Níveis por política (Gabriel, 2026-11-10, opção 1):** o smoke `f616-smoke` (`807890d9`, 4/4 VALIDA) mostrou que
  A3.1 e A10.1 nunca trocam no S3 `k_A`=5 nem no S6 `k_R`=1: só trocam por requisições viáveis depois de uma troca
  real (~15,7 s num 8B), e nenhuma é. Passam a rodar no S6 `k_R`=4 (~63 s), com um nível da A9.2 ali como referência;
  A9.4 e A2.3 seguem no S3 `k_A`=5 e no S6 `k_R`=1. Por job: 11 níveis. Antes da campanha, smoke 2 (A9.4 no S6
  `k_R`=1, A3.1 e A10.1 no S6 `k_R`=4) para confirmar que agem.

## D54 — Resultado da triagem F6.16 e escopo da confirmação (2026-11-10, Gabriel)

- Triagem (`reports/fases/F06_16_triagem_politicas_novas.md`, 88/88 VALIDA): nenhuma política nova melhora as que já
  tínhamos; A9.4 com λ = 3 é a A9.2 na prática (preemptou 13 de 343 trocas com vítima ocupada), A2.3 e A3.1 são menos
  justas que a A9.2, A10.1 é a A0.4 no S6 `k_R`=4.
- **Confirmação F6.15, 5 repetições:** A9.2 e A2.1 sem preempção, e **A9.4 com λ = 1** (preemptar se salvas ≥ perdidas),
  contra A0.2+A1 e A0.4, nos prazos S3 `k_A`=5, S6 `k_R`=1, **S6 `k_R`=2** (acrescentado pelo Gabriel) e S6 `k_R`=4;
  A2.1 com preempção no S6 `k_R`=4 (D52). Saem A2.3, A3.1 e A10.1. Objetivo: justiça sem grande perda de SLO (D52).

## D56 — SLO de TPOT como no artigo do Prism no padrão das tabelas (2026-11-10, Gabriel)

- **Pedido (Gabriel):** usar o mesmo cálculo de SLO de TPOT do artigo do Prism.
- **O artigo (R1, verificado no texto OSDI'26 `Prism.pdf` e no arXiv v3):**
  - §7.1: "To establish SLOs for each model, we first ran its workload on dedicated GPUs to measure its P95 TTFT and
    TPOT latencies. This process produced [...] TPOT SLOs from 5.2ms to 50.9ms. We then scaled these base values by a
    factor";
  - §2: TPOT é a latência média entre tokens da requisição (a mesma definição nossa);
  - as escalas de TTFT e TPOT são separadas: §7.4, "SLO scale is 5 and TPOT SLO scale is 2.0"; a Fig. 9b varia a "TPOT
    SLO Scale" de 2,0 a 4,0;
  - o artigo reporta atendimento de TTFT e de TPOT separados, sem SLO combinado.
- **Estado anterior:** os níveis S2/S3/S6 já usavam o TPOT do artigo (`k_D · P95` dedicado, D20; base juntando os
  modelos idênticos, D21; `k_D = 5`, D23). Só o padrão das tabelas (CLAUDE.md regra 7) usava TPOT absoluto de 100 ms e
  combinado 1 s + 100 ms.
- **Decisão (Gabriel aprovou a proposta do agente; `k_D = 2` acrescentado pelo agente por ser o valor do artigo):**
  - família nova **S1D** em `polyaxon/slo_metrics.py`: TTFT absoluto, TPOT = `k_D · pool_tpot_p95(c, m)`;
  - padrão das tabelas a partir da F6.15: só TTFT 1/2/5 s; só TPOT `k_D = 2` e `k_D = 5`; combinado 1 s + 5×P95; o
    TPOT 100 ms fica como referência secundária;
  - a base continua juntando os modelos idênticos (D21), e não o P95 por modelo do artigo (ruído do nó);
  - fases anteriores (relatórios aprovados) não são refeitas.
- **Achado:** com 10–14 modelos por GPU e sem CUDA graphs, o TPOT servido fica 7–9× a mediana dedicada (p10 51–54 ms,
  mediana 73–92 ms nos 3 primeiros jobs da F6.15). O `k_D = 2` (~50 ms) fica abaixo de quase tudo: 4–16% atendem em
  todas as configurações. A coluna informativa é a de `k_D = 5`. Limitação registrada em `latencia_ref.md`.
- **Arquivos:** `polyaxon/slo_metrics.py` (S1D), `polyaxon/f60_analysis.py` (referências `S1Dk2`, `S1Dk5`),
  `polyaxon/f615_compare.py` (`tabela_padrao.md`), `tests/metrics/test_slo_metrics.py`, CLAUDE.md regra 7,
  `docs/agent/glossary.md`, `reports/registro/latencia_ref.md`, `referencias.md` (R1).
