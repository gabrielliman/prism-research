# TODO — políticas de residência orientadas a prazos no Prism

Leia `PLANO_AGENTE.md` antes de começar. Regras principais:
- Não avance de fase sem o gate da fase anterior marcado como **APROVADO** no relatório da fase.
- Gates **[HUMANO]**: prepare o relatório, marque `AGUARDANDO REVISÃO` e pare.
- Execução inválida não entra em agregado; não repita às cegas (seção 0.2 e 0.3 do plano).
- Ao marcar uma caixa, acrescente a data e o caminho da evidência: `- [x] F0.1 ... (2026-11-03, reports/fases/F00_inventario.md)`.

## F0 — Reconhecimento e reprodução · gate [HUMANO]
- [x] F0.1 Inventário do repositório (políticas, `PRISM_*`, scripts, formato dos logs, fluxo de uma execução) (2026-10-29, reports/fases/F00_inventario.md; falta a revisão)
- [x] F0.2 Verificar se a arbitragem por folga (Moore-Hodgson) do artigo existe e está ativa no código aberto (2026-10-29, reports/fases/F00_inventario.md seção 4: não existe)
- [x] F0.3 Estado das pendências: T1 (14 modelos), folga de KV no `ovl_mix`, 25 perdas, K1 (2026-10-29, reports/fases/F00_reconhecimento.md; nova pendência P11)
- [x] F0.4 Reproduzir `ovl_phases` (A0.1, A0.2) e `ovl_trace_big` (A0.3), 3 repetições (2026-10-30, reports/data/F00/reproducao/comparacao.md; critério estrito falhou em desvios pequenos, reprodução aceita pelo Gabriel: reports/registro/decisoes.md D1, D2)
- [x] F0.5 Relatório `reports/fases/F00_*.md` com critérios e decisão do gate (2026-10-30, reports/fases/F00_reconhecimento.md; gate APROVADO)

## F1 — Robustez restante · gate automático
- [x] F1.1 T1 com 14 modelos: reprodução mínima + `py-spy dump` + causa + correção ou encaminhamento para F4 (2026-10-30, reports/erros.md T1: impasse de memória da política, pilhas via `PRISM_STACK_DUMPS` em vez de py-spy; encaminhado para F4 A1.1/A1.2)
- [x] F1.2 25 requisições perdidas: instrumentar retirada/reinserção no Redis, causa, correção, 10 repetições sem perdas (2026-10-30, `PRISM_TRACE_RIDS` + polyaxon/trace_rids.py; 10 repetições limpas, 55 não atendidas, todas explicadas: 54 em ciclo de preempção/recomputação, 1 à espera de modelo nunca reativado; nenhuma descartada; correção é de política, encaminhada para F4/F6)
- [x] F1.3 Folga de KV no `ovl_mix` (A0.4), 5 repetições (2026-10-30, reports/data/F01/folga_ovl_mix/; 5/5 limpas e idênticas: SLO 76%, pior espera 342 s por fome de `model_6`/`model_7`)
- [x] F1.4 K1: frequência com nó saudável e degradado; decisão sobre o árbitro registrada (2026-10-30, 0 em 37 execuções fora da janela degradada, 5 em 6 dentro; árbitro continua desligado: reports/registro/decisoes.md D5)
- [x] F1.5 Repetir F0.4 após as correções (sem regressão) (2026-10-30, reports/data/F01/reproducao/ e reports/data/F01/ab_codigo/; contra as referências de outro dia falhou por cluster mais lento; A/B de código no mesmo período sem regressão; aceito pelo Gabriel: decisoes.md D7, D8)
- [x] F1.7 P11: desativação de ~30 s sem trabalho pendente (`deactivate()`), causa e correção ou encaminhamento (2026-10-30, reports/erros.md P11: unmap do kvcached em `trim()`, > 10 s em 18 de 986 desativações em execuções limpas (até 30 s), até 88 s com nó degradado; kvcached não alterado; custo a medir na F2.3)
- [x] F1.6 `erros.md` atualizado; relatório F01 (2026-10-30, reports/fases/F01_robustez.md; gate APROVADO)
- [x] F1.8 P12: detecção da morte do model service (2026-10-30, decisoes.md D9; verificado em `f1-p12b-on/off`; tests/robustness/test_model_service_alive.py)

## F2 — Instrumentação, validador e estimadores · gate [HUMANO]
- [x] F2.1 Logs estruturados do controlador (retrato de estado + ações + motivo) e das requisições (prazo, classe, estado final) (2026-11-04, `decision_log.py` + `PRISM_DECISION_LOG`, `overload_load.py`; tests/controller/test_decision_log.py; reports/fases/F02_instrumentacao.md)
- [x] F2.2 `validate_run.py` (V1–V15) e `validate_campaign.py` (C-V1–C-V3) (2026-11-04, polyaxon/; V6 N/A até a F7; decisões D10, D11, D16)
- [x] F2.2a Teste retroativo do validador nos dados de 28/10 (falhas conhecidas detectadas; execuções limpas aprovadas) (2026-11-04, reports/data/F02/validador/retro.csv: 17/17 e 37/37)
- [x] F2.3 Estimador `Ĉ_at(m)` (tamanho + memória livre + ativações concorrentes), erro registrado (2026-11-04, reports/data/F02/cat/: erro mediano 11,8%; D12)
- [x] F2.4 Estimador de prefill `p̂_r`, erro registrado (2026-11-04, reports/data/F02/iso2/iso_fit.md: 12,4% / 18,0%; D18)
- [x] F2.5 Estimadores `q̂_r` e `λ̂_m` (EWMA duas janelas), erro de previsão no horizonte `H` (2026-11-04, estimators.py, reports/data/F02/estimadores/; D15, D17)
- [x] F2.6 Confirmar/refutar a observação 4.0 (SLO de 1 s × custo de ativação) com dados (2026-11-04, confirmada: 0 de 36.064; reports/data/F02/observacao_4_0.md)
- [x] F2.7 Criar `execucoes.csv`, `decisoes.md`, `cargas.md` (2026-11-04, reports/registro/; register_runs.py, workload_stats.py)
- [x] F2.8 Medir sobrecusto da instrumentação (≤ 2%) (2026-11-04, medida direta 0,0017%; vazão ponta a ponta inconclusiva, decisão no gate; reports/data/F02/sobrecusto/)
- [x] F2.10 Latência de referência por modelo: `TTFT_iso(m, L)` e `TPOT_iso(m)` (seção 5.4) (2026-11-04, reports/registro/latencia_ref.json, job f2-iso2)
  - base do S2 refeita pelo artigo do Prism (D20) e agregada juntando modelos idênticos, S2 = P95 e S2M = P50 (D21): reports/registro/latencia_ded.json, jobs f2-ded-{a,b,c}
  - [x] [HUMANO] novos níveis de `k_T`/`k_D` sobre as curvas refeitas (2026-11-04, D23: S2 k_T {2,5,10,25} k_D {1,5,2,3,5}; S2M k_T {5,10,25,50} k_D {3,5,10,20}) (C5 fica como está, D21/O2; CUDA graphs desligados, D22/O1)
- [x] F2.11 Métricas com SLO parametrizado (família + nível) e três vistas (combinada, só TTFT, só TPOT) + decomposição das violações; regressão: S1 reproduz os números de 28/10 (2026-11-04, slo_metrics.py; 182 níveis idênticos; D13, D14)
- [x] F2.12 Curvas S2 (`k_T` × `k_D`) e S3 retroativas nos dados de 28/10, nas três vistas (2026-11-04, reports/data/F02/curvas/; refeitas com S2/S2M da D21)
- [x] F2.9 Relatório F02 com opções de família principal de SLO, níveis `k_T`/`k_D`/`k_A` e SLOs por classe, para decisão do Gabriel (2026-11-04, reports/fases/F02_instrumentacao.md; gate APROVADO em 2026-11-04, D19)

## F6a — Primeira rodada das políticas por prazo (A2.1, A9.1), adiantada · gate [HUMANO] · PRIORIDADE ATUAL (D24)
- [x] F6a.1 (2026-11-04, `overload_load.py --slo-spec`, `PRISM_OVL_SLO_SPEC`; D25) `overload_load.py --slo-spec`: prazo por requisição (S2/S2M/S3 com `latencia_ded.json`) enviado ao servidor; métricas com a mesma especificação
- [x] F6a.2 (2026-11-04, `policy/deadline.py`; D25) `scheduling/policy/deadline.py`: `edf_select` (A2.1) e `lvf_select` (A9.1), funções puras; `simple_global.py` monta o retrato; `PRISM_EVICTION=edf|lvf`, A1.1 (`PRISM_KV_RESERVE_REQS`) e A1.3 (`PRISM_MIN_RESIDENCY`), padrões inalterados
- [x] F6a.3 (2026-11-04, `tests/policy/test_deadline.py`, 28 testes; 45 no total com controller/robustness) Testes em `tests/policy/` (tudo cabe, fome C1, troca C2, impasse C3, fila inviável, rotativo com α, orçamento, `T_min`, memória no limite)
- [x] F6a.4 (2026-11-04, campo `policy` do `decisions.jsonl`) Decisões das duas políticas no log de decisões (folga / VLT por modelo)
- [x] F6a.5 (2026-11-04, job `d8eed798`, 2/2 VALIDA, `reports/data/F06a/validador/smoke.csv`; 15 rotações EDF, 16 LVF) Smoke test: A2.1 e A9.1 no C1, validados
- [x] F6a.6 (2026-11-05: 74 níveis, 73 VALIDA; P13 corrigida, D26; `reports/data/F06a/triagem/`) Triagem: C1 0,2 e T1 ts1, 2 rep., ≤ 3 jobs; A0.1, A0.2, A0.3, `fair` (de novo, pareadas) + A2.1 e A9.1 × {S2 kT=10, S2 kT=25, S3 kA=5} + ciclo 1 s no melhor nível (48 níveis)
- [x] F6a.7 [HUMANO] (2026-11-05, D27: opção 1, sem confirmação) Gabriel escolhe o que vai para a confirmação
- [-] F6a.8 (não executada, D27: nada passou na triagem) Confirmação: 5 rep. pareadas contra A0.1 e a melhor linha de base, + C2 como controle; IC 95% nas três vistas
- [x] F6a.9 (2026-11-05, `reports/fases/F06a_prazo_primeira_rodada.md`, APROVADO) Relatório F06a; gate [HUMANO]
- [x] F6a.10 (2026-11-05, D30, branch `apresentacao-prazo`; código trazido para a F4 na D35) Drenagem com prazo removida do código (`PRISM_SWAP_DRAIN`, `drain_timeout`); desativação = preemptar ou não; variáveis antigas dão erro; 46 testes passam. A0.3 redefinida sem drenagem

## F3 — Catálogo de cargas · gate [HUMANO]
- [x] F3.1 `overload_load.py`: leitura de trace, classes de SLO, recusa como estado final, sementes (2026-11-05, `polyaxon/workloads.py`, `tests/workloads/`; C1–C5 com o mesmo hash)
- [x] F3.2 C6 `zipf_drift` (2026-11-05, `ovl_zipf`; dry run VALIDA, com T1)
- [x] F3.3 C7 `bursty` (2026-11-05, `ovl_bursty`, IPP 10/20 s, CV 2,5, D28; dry run VALIDA, com T1)
- [x] F3.4 C8 `diurnal` (2026-11-05, `ovl_diurnal`; dry run VALIDA, com T1)
- [x] F3.5 C9 `slo_classes` (2026-11-05, `ovl_classes` sobre C1 e C6, S4 em `slo_metrics.py`; dry runs VALIDA)
- [x] F3.6 C10 `sizes_mix` (verificar suporte dos modelos no SGLang 0.3.4) (2026-11-05, Qwen2.5-14B/32B no cache do cluster, job `1f15aae8`, D29; P14 `Too many open files` corrigida no harness; dry run `f722128d` VALIDA, com T1)
- [x] F3.7 C11 `slo_sweep` (famílias S2 e S3 da seção 5.4) (2026-11-05, definição em `cargas.md`; falta a base dedicada das cargas novas)
- [x] F3.8 T2 LMSYS-Chat-1M (licença, popularidade real, chegadas sintéticas) (2026-11-05, termos aceitos pelo Gabriel, D29; `trace_adapt.py lmsys`, trace fora do git; dry run `2cfa2343` VALIDA, 1201/1201)
- [x] F3.9 T3 Azure Functions (licença, mapeamento função → modelo) (2026-11-05, CC-BY-4.0, `trace_adapt.py azfn`; dry run VALIDA, com T1)
- [x] F3.10 T4 Azure LLM inference e T5 BurstGPT (se houver tempo) (2026-11-05, CC-BY-4.0; T4 VALIDA com T1; T5 VALIDA, mas sem rajadas na taxa alvo: proposto fora)
- [x] F3.11 Estatísticas antes/depois de cada transformação no `cargas.md` (2026-11-05, `polyaxon/traces/*.stats.json`, `workload_check.py`; leitura do critério: dúvida da D28)
- [x] F3.12 Dry run de cada carga validado (V8, V11, V12) (2026-11-05, jobs `9d3f7e73`, `e40d0408`, `e24c4752`: 8/8 VALIDA; depois `2cfa2343` (T2) e `f722128d` (C10): 10 de 10 cargas VALIDA; T1 em 7 de 10, reports/fases/F03_cargas.md)
- [x] F3.13 Relatório F03 com a proposta de conjunto de cargas (2026-11-05, reports/fases/F03_cargas.md; gate APROVADO em 2026-11-05, D29)

## F4 — Restrições estruturais (A1) · gate automático
- [x] F4.1 A1.1 reserva mínima de KV na ativação + testes unitários (2026-11-05, `policy/structural.py` + `_activation_need_gb` em toda estratégia, soma o piso de 5% do kvcached; `tests/policy/test_structural.py`; D34)
- [x] F4.2 A1.2 detector de impasse + testes unitários (2026-11-05, `PRISM_DEADLOCK_S`, relógio pelos `served_tokens`, vítima pelo critério da A0.3, com preempção; `tests/policy/test_structural.py`; D34)
- [x] F4.3 A1.3 histerese mínima de residência + testes unitários (2026-11-05, `PRISM_MIN_RESIDENCY` em todo caminho de despejo; `tests/policy/test_structural.py`; D34)
- [x] F4.3b Smoke: C6 (A0.1, A0.3) e C1 com 14 modelos, com A1 (2026-11-05, job `cbb45bf8`, 3/3 VALIDA, T1 0/0/34 s; C6 atende 1193/1193 nas duas; C1n14 57%, sem congelar, 2 disparos da A1.2, fome da A0.1 nos modelos 12–14; `reports/data/F04/validador/smoke.csv`)
- [x] F4.4 Campanha: C3, C1 (8 e 14 modelos), C2, T1 × {A0.1, A0.3} × {sem, com A1}, 5 repetições (+ C6, C7, C8, T3, C10 × 2, escopo do Gabriel) (2026-11-06, 35 jobs, 134/140 VALIDA; 6 do C10 por P15, reexecução `f4-c10-1b/2b` em andamento; `reports/data/F04/campanha/`)
- [x] F4.5 Zero impasses; sem piora significativa nos cenários sem impasse — impasse = T1 ≥ 100 s, 0 de 70 níveis com A1 (C10 refeito com P15, 8/8 VALIDA); leitura (b) (D37): OK para A0.1 + A1; A0.3 + A1 folga 3 GB falha no C7; A0.4 (folga 0) OK em T3/C3/C7/C6 (verificação da folga, 24/24 VALIDA), não testada nas outras 6 cargas; aprovado com a lacuna declarada (D38)
- [x] F4.6 Parâmetros `b`, `Δ_imp`, `T_min` registrados; relatório F04 — D34, D37; `reports/fases/F04_restricoes.md`; gate APROVADO (D38, 2026-11-06)

## F5 — Linhas de base na nova metodologia · gate [HUMANO] · APROVADO (D49, 2026-11-09)
- [x] F5.0a (D32, vinha da F6b) `polyaxon/swap_cost.py`: custo real da troca (decisão → vítima fora → pedido de ativação → modelo pronto), decisão ligada à ativação pelo `decisions.jsonl`, dados da F6a e de 28/10; `Ĉ_rot(m)` com e sem preempção; comparação com `ê_r` (só análise)
- [x] F5.0b Família S6 (`k_R · Ĉ_rot`) no `slo_metrics.py` e no `overload_load.py --slo-spec` — duas bases (D42): `S6` sem preempção (testada primeiro), `S6P` com preempção
- [x] F5.0c Violações inevitáveis pela ativação × pela rotação × evitáveis só com residência prévia × evitáveis (`slo_metrics.py`), com a classificação antiga ao lado — D43; + `viol_tpot_em_troca`
- [x] F5.0d Métrica de ociosidade da GPU: residência ociosa com demanda pendente; ociosidade esperada pela carga (`ρ_m` de `latencia_ded.json`) × observada (`gpu.csv`) — `polyaxon/gpu_idle.py`, D44; `ρ_m` pelo tempo de GPU ocupada (D46)
- [x] F5.0e `report_tables.py`: TTFT p50 e p90 e cauda de espera (p99, máximo, fração > 10× a mediana; D33) nas tabelas, ao lado das três vistas de SLO
- [x] F5.0f Log de decisões: reserva de memória vencida sem ativação, e quem ficou com a memória (D30)
- [x] F5.1 A0.1–A0.5 (+A1), com A0.3 e A0.3p (sem e com preempção) e a melhor ociosidade de valor arbitrário (seção 0.10), em todas as cargas aprovadas, níveis de `ρ_mem` definidos, 5 repetições — escopo da D39/D46: 5 configurações (A0.1, A0.1+A1, A0.2+A1, A0.4, A0.4p) × 18 cargas × 3 repetições = 270 níveis, todos VALIDA (2026-11-08, `reports/data/F05/camp/`; D47, D48)
- [x] F5.2 Tabelas e figuras de referência (SLO total, TTFT p50/p90, evitáveis/inevitáveis pela classificação nova, ociosidade da GPU, pior modelo, trocas, perdas) — `polyaxon/f5_analysis.py`, `f5_report_tables.py`, `f5_figs.py`; `reports/data/F05/campanha/`, `reports/figs/F05/` (2026-11-09)
- [x] F5.2a Curvas de todas as famílias de SLO calculadas pós-execução; SLO mínimo atingível (90% e 99%) por política e carga, nas três vistas — `curvas_niveis.csv`, Tabela 5 (2026-11-09)
- [~] F5.2c Decomposição das violações (ambos / só TTFT / só TPOT / nenhum) e CDFs de TTFT e TPOT normalizados, por política e por modelo — decomposição em `niveis.csv` (colunas `*_1s`) e Tabela 2; quantis do TTFT/TPOT normalizados em `niveis.csv`; figuras de CDF ainda não feitas
- [x] F5.2b Escolher o subconjunto de níveis de SLO para as políticas por prazo (alto, meio da queda, baixo) e registrar em `decisoes.md` — D49: S6 k_R ∈ {1, 2, 4} e S3 k_A = 5 (S2 k_T = 10 como referência)
- [x] F5.3 C-V1 e C-V2 satisfeitos; relatório F05 com proposta de conteúdo do artigo parcial — C-V1 OK; C-V2 falhou, aceito com limitação (D49); sem artigo parcial por enquanto (D49); relatório `reports/fases/F05_linhas_de_base.md`

## F6 — Ativação e despejo por folga (A2–A4) e por atraso virtual (A9) · gate [HUMANO]
- Prioridades (D31, D32, `PLANO_AGENTE.md` seção F6): custo real da troca → A3.1 → A10 (throughput × prazo × fila) → A2.3 → A4 → classes de prazo (F8) → A9.2; ciclo 1 s e A5 fora de prioridade; pior modelo só como observação; objetivo SLO + TTFT p50/p90 + nenhuma espera absurda (D33); SLOs ≥ tempo de rotação (S3 kA=5, S6 kR ∈ {1, 2})
- [x] F6.P16 (2026-11-09, R2.6 em `scheduler.py`, `tests/robustness/test_preempt_inflight.py`, jobs `f6-p16-1..5` em `reports/data/F06/p16/`; causa: a desativação com preempção descartava a requisição no meio de um prefill em pedaços, que ficava "rodando" no controlador e era respondida pelo modelo errado; verificado: 0 respostas de outro modelo e 0 presas com a correção, contra 9 e 2 sem) Investigar e corrigir a P16 (`reports/erros.md`: com preempção, requisições ficam "rodando" num modelo inativo no espelho do controlador): nível curto da A0.4p com `PRISM_TRACE_RIDS=1`; causa; correção; teste unitário; verificação
- [x] F6.0 (2026-11-09: campanha 160/160 VALIDA, relatório `reports/fases/F06_0_repeticao_sem_drenagem.md` APROVADO, D52; D31, D32, D49, D50; primeira tarefa da F6) Triagem das políticas por prazo sem drenagem, com A1 e as linhas de base da F5: C1 com 10 modelos, T1, C6 com 14 modelos e T3, 2 rep. (8 jobs × 20 níveis = 160, `polyaxon/f6_0_suites.sh`, driver `f4_driver_start.sh f60`, sem orçamento de workers); por job A0.2+A1 e A0.4 (referência pareada) + A2.1 (EDF), A9.1 (VLT) e A9.2 (VLT ciente da residência, nova, D50) × {S3 `k_A`=5, S6 `k_R`=1, S6 `k_R`=4} × {sem, com preempção}; hipótese do S3 (D49): diferença com − sem preempção no S3 contra a mesma no S6 `k_R`=4, pareada no job; smoke `f60_smoke_suite.tsv` antes; relatório `reports/fases/F06_0_repeticao_sem_drenagem.md`; gate [HUMANO]
- [ ] F6.14 (D52) A9.4 VLT residência com preemptar ou não por troca + testes; padrão sem preempção em todas as políticas
- [ ] F6.15 (D52) Confirmação: A9.2, A2.1 (sem preempção) e A9.4 contra A0.2+A1 e A0.4 em S3 `k_A`=5 e S6 `k_R`=1; A2.1 com preempção em S6 `k_R`=4; objetivo justiça sem grande perda de SLO
- [x] F6.1 (feito na F6a e na F6.0) A2.1 EDF entre modelos + testes
- [ ] F6.2 A2.2 menor folga com antecipação (+ variação do ciclo do controlador) + testes
- [ ] F6.3 A2.3 residência preditiva (`λ̂`, horizonte `H`) + testes
- [ ] F6.4 A3.1–A3.3 despejo por perda esperada, preemptar × não preemptar (D30: sem drenagem com prazo) + testes
- [ ] F6.13 (D32) A10.1–A10.3 troca por valor (throughput × prazo × fila), `PRISM_EVICTION=value` + testes; entra na ablação e na sensibilidade dos pesos
- [ ] F6.5 A4 política combinada
- [ ] F6.6 Ablação em C1, C2, C3, C6, C7, C11, T1 contra A0.1 e a melhor linha de base, 5 repetições
- [ ] F6.7 Sensibilidade de margem, `H`, `θ`, ciclo; escolha registrada
- [ ] F6.8 IC 95% pareado por semente para cada comparação, nas três vistas (combinada, só TTFT, só TPOT); explicação mecânica de toda diferença > 2× e de toda troca de violação de TTFT por TPOT (ou o inverso)
- [x] F6.10 (A9.1 na F6a; A9.2 em 2026-11-09, D50) A9.1 LVF entre modelos (VLT do SuperInfer) e A9.2 LVF com custo de ativação + testes (`tests/policy/`)
- [ ] F6.11 A9 na campanha de ablação da F6.6 (mesmas cargas e repetições), contra `fair`, A0.1, a melhor linha de base e A2/A4; sensibilidade de `α`, `β_F`, `β_B` e do orçamento de rotação
- [ ] F6.12 (opcional, decidir pelo resultado da F6.11) A9.3 LVF entre requisições dentro do worker, com preempção por recomputação
- [ ] F6.9 Relatório F06

## F7 — Admissão e arbitragem com custo de ativação (A5, A6) · gate [HUMANO]
- [ ] F7.1 A5.1 recusa na chegada
- [ ] F7.2 A5.2 recusa por envelhecimento
- [ ] F7.3 A5.3 rebaixamento para lote
- [ ] F7.4 A0.5 (se não existir) e A6 Moore-Hodgson com custo de ativação + testes
- [ ] F7.5 Medida de recusas "erradas"
- [ ] F7.6 Campanha em C1, C4, C5, C7, C9, T1, com resultados nas três vistas; relatório F07

## F8 — Classes e pesos (A7) · gate automático
- [ ] F8.0 Antes de começar: reapresentar ao Gabriel os SLOs das classes (provisórios na D19: interativa S2 `k_T`=10, `k_D`=5; lote TTFT 60 s, sem TPOT) com os dados da F5–F7, e esperar a confirmação
- [ ] F8.1 Classes e pesos em A2, A3, A5
- [ ] F8.2 Campanha em C9 e C6 com proporções de classe variadas
- [ ] F8.3 Curvas SLO agregado × pior modelo para cada política, nas três vistas e por classe
- [ ] F8.4 Objetivo padrão decidido pelo Gabriel e registrado; relatório F08

## F9 — Oráculo offline (A8) · gate [HUMANO] · pode rodar em paralelo após F3
- [ ] F9.1 Formulação ILP e implementação (HiGHS ou CP-SAT)
- [ ] F9.2 Validação por enumeração em instâncias minúsculas
- [ ] F9.3 Solução nos traces curtos; gap e tempo registrados
- [ ] F9.4 Política `oracle_replay` e execução real do plano ótimo
- [ ] F9.5 Erro do modelo (ILP × execução real) e lacuna das políticas online; relatório F09

## F10 — Campanha final · gate [HUMANO]
- [ ] F10.1 Congelar commit e imagem
- [ ] F10.2 Matriz completa com repetições mínimas
- [ ] F10.3 Figuras e tabelas regeneráveis por um comando a partir de `execucoes.csv`, todas nas três vistas
- [ ] F10.4 Relatório final com conclusões, limitações e ameaças à validade

## F11 — Consolidação · gate [HUMANO]
- [ ] F11.1 Pacote de artefatos
- [ ] F11.2 Rascunhos das seções de avaliação (artigos e dissertação)
