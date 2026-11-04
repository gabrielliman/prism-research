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
