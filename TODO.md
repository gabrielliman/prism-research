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

## F6a — Primeira rodada das políticas por prazo (A2.1, A9.1), adiantada · gate [HUMANO] · APROVADO, negativo (D27)
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
- [~] F5.2c (CDFs pendentes, baixa prioridade) Decomposição das violações (ambos / só TTFT / só TPOT / nenhum) e CDFs de TTFT e TPOT normalizados, por política e por modelo — decomposição em `niveis.csv` (colunas `*_1s`) e Tabela 2; quantis do TTFT/TPOT normalizados em `niveis.csv`; figuras de CDF ainda não feitas
- [x] F5.2b Escolher o subconjunto de níveis de SLO para as políticas por prazo (alto, meio da queda, baixo) e registrar em `decisoes.md` — D49: S6 k_R ∈ {1, 2, 4} e S3 k_A = 5 (S2 k_T = 10 como referência)
- [x] F5.3 C-V1 e C-V2 satisfeitos; relatório F05 com proposta de conteúdo do artigo parcial — C-V1 OK; C-V2 falhou, aceito com limitação (D49); sem artigo parcial por enquanto (D49); relatório `reports/fases/F05_linhas_de_base.md`

## F6 — Políticas por prazo e por atraso virtual: triagens e confirmação · gate [HUMANO] · escopo revisto na D55
- Objetivo (D52): justiça entre modelos sem grande perda de SLO (pior quarto, Jain, p90 do pior modelo + SLO total, TTFT p50/p90, cauda). Prioridades antigas da D31/D32 superadas (D52–D55).
- [x] F6.P16 (2026-11-09, R2.6 em `scheduler.py`, `tests/robustness/test_preempt_inflight.py`, jobs `f6-p16-1..5` em `reports/data/F06/p16/`; causa: a desativação com preempção descartava a requisição no meio de um prefill em pedaços, que ficava "rodando" no controlador e era respondida pelo modelo errado; verificado: 0 respostas de outro modelo e 0 presas com a correção, contra 9 e 2 sem) Investigar e corrigir a P16
- [x] F6.0 (2026-11-09: campanha 160/160 VALIDA, relatório `reports/fases/F06_0_repeticao_sem_drenagem.md` APROVADO, D52; D50) Triagem sem drenagem: A2.1, A9.1, A9.2 × {S3 `k_A`=5, S6 `k_R`=1, 4} × {sem, com preempção}, com A0.2+A1 e A0.4; C1 10 modelos, T1, C6 14 modelos, T3; 2 rep.
- [x] F6.1 (feito na F6a e na F6.0) A2.1 EDF entre modelos + testes
- [x] F6.10 (A9.1 na F6a; A9.2 em 2026-11-09, D50) A9.1 e A9.2 + testes
- [x] F6.14 (2026-11-10, F6.16, `preempt_choice` em `policy/deadline.py`, `tests/policy/test_f616.py`) A9.4: preemptar ou não a cada troca (λ); padrão sem preempção em todas as políticas (D52)
- [x] F6.3 / F6.4 / F6.13 (2026-11-10, só as variantes 1: A2.3, A3.1, A10.1; F6.16) Implementadas e triadas; **encerradas com resultado negativo** (D54)
- [x] F6.16 (2026-11-10, 88/88 VALIDA, relatório `reports/fases/F06_16_triagem_politicas_novas.md`, D54) Triagem: A9.4, A3.1, A10.1, A2.3 + A0.2+A1 e A0.4, 2 rep.
- [x] F6.15 (2026-11-11, 20 jobs, 300/300 VALIDA, relatório `reports/fases/F06_15_confirmacao.md`, D60) Confirmação, 5 rep.: A9.2 e A2.1 sem preempção, A9.4 com λ = 1, contra A0.2+A1 e A0.4, em S3 `k_A`=5 e S6 `k_R` ∈ {1, 2, 4}; A2.1 com preempção em S6 `k_R`=4; vencedora A9.2
- [x] F6.17 Sensibilidade da vencedora: **pulada** (D60; a F14 adapta a A9.2 ao tamanho dos modelos)
- [x] F6.18 (2026-11-11, `polyaxon/f615_decomp.py`, tabela D do relatório da F6.15) Decomposição evitável/inevitável nos níveis S3/S6
- [x] Gate da F6 aprovado (D60, 2026-11-11)
- [ ] F6.9 Relatório F06 (confirmação + resumo da F6, inclusive os negativos)
- [-] Cortados (D55): F6.2 A2.2; A3.2/A3.3; F6.5 A4 (virou a A12, F13); F6.6 ablação ampla (virou a F15); F6.7 sensibilidade de margem/`H`/`θ`/ciclo; F6.11 comparação com `fair`; F6.12 A9.3; A10.2/A10.3; F6.8 absorvido nos critérios de cada fase

## F14 — Modelos heterogêneos: políticas cientes do tamanho e do tempo de ativação · gate [HUMANO] · PRÓXIMA (D58)
- [ ] F14.0 Ler no texto as fontes das distribuições de popularidade (MuxServe α 0,9/2,1, DeltaZip Zipf 1,5, BurstGPT pequenos populares, Prism §3.1 grandes populares, ServeGen) e registrar em `referencias.md`; popularidade × tamanho do LMSYS-Chat-1M para a H-real; [HUMANO] lista de modelos, cargas H e limiar de "grande perda de SLO"
- [ ] F14.1 Baixar Llama-3.2-1B, Qwen2.5-7B, Mistral-Nemo (`hf_download.sh`); smoke de cada modelo no SGLang 0.3.4
- [ ] F14.2 Base dedicada (`latencia_ded.json`) e `Ĉ_at`/`Ĉ_rot` por modelo, com e sem preempção (substitui os extrapolados de 27,5 e 61 GB)
- [ ] F14.3 Cargas H-unif, H-G-α, H-P-α (α ∈ {0,9; 2,1}; 1,5 opcional), H-real em `workloads.py`; `cargas.md`; dry runs VALIDA
- [ ] F14.4 Métricas por classe de tamanho (`slo_metrics.py`, `f60_fairness.py`, padrão das tabelas)
- [ ] F14.5 Linha de base heterogênea, 2 rep.: A0.2+A1, A0.4, A9.2, A2.1 e a vencedora da F6.15, sem adaptação, nas cargas H e no C10
- [ ] F14.6 Literatura (custo por tamanho: R7, R8, serving multi-modelo heterogêneo) + desenho de A14.1–A14.4 para aprovação
- [ ] F14.7 Implementação atrás de `PRISM_*` + testes
- [ ] F14.8 Triagem, 2 rep.: cada adaptação pareada com a versão sem adaptação, A0.2+A1 e A0.4; S3 `k_A`=5, S6 `k_R` ∈ {1, 2, 4}; smoke antes
- [ ] F14.9 Confirmação, 5 rep., do que passar
- [ ] F14.10 Relatório F14; [HUMANO] ordem das fases seguintes

## F12 — Redução do custo da troca (A13) · gate [HUMANO] · depois da F14 (ordem revista no gate da F14)
- [ ] F12.1 Decomposição do custo da troca nos dados da F6.15 e da F14 (`swap_cost.py`), por política e tamanho; ordem de ataque
- [ ] F12.2 Literatura + desenho de A13.1–A13.4; aprovação do Gabriel
- [ ] F12.3 Implementação atrás de `PRISM_*`, estados explícitos (D45), testes
- [ ] F12.4 Triagem pareada (com × sem cada mecanismo) nas melhores políticas, 2 rep.; confirmação de 5 do que entrar
- [ ] F12.5 Remedir `Ĉ_rot` (decisão sobre a base do S6); relatório F12

## F13 — Política candidata: troca por throughput com garantia de justiça (A12) · gate [HUMANO]
- [ ] F13.1 Literatura (VTC e justiça em serving multi-modelo) + desenho de A12.1–A12.3
- [ ] F13.2 Implementação + testes (com as adaptações da F14 e os mecanismos da F12 aprovados)
- [ ] F13.3 Triagem, 2 rep., nas cargas da F6 e nas heterogêneas, contra A0.2+A1, A0.4, A9.2, vencedora da F6.15
- [ ] F13.4 Confirmação, 5 rep.; sensibilidade do parâmetro de justiça
- [ ] F13.5 Relatório F13; [HUMANO] política candidata principal

## F15 — Generalização das políticas finais · gate [HUMANO]
- [ ] F15.1 [HUMANO] Cargas não usadas na F6 nem na F14 (proposta: C7, C2, T2; C8 opcional), com justificativa da seção 0.9
- [ ] F15.2 Políticas finais contra A0.2+A1 e A0.4, 5 rep. pareadas
- [ ] F15.3 Relatório F15

## F7 — **CORTADA (D55, D57)**
## F9 — **CORTADA (D55)**

## F8 — Classes e pesos (A7) · gate automático
- [ ] F8.0 Antes de começar: reapresentar ao Gabriel os SLOs das classes (provisórios na D19: interativa S2 `k_T`=10, `k_D`=5; lote TTFT 60 s, sem TPOT) com os dados da F5–F13, e esperar a confirmação
- [ ] F8.1 Classes e pesos nas políticas finais (F13, F14)
- [ ] F8.2 Campanha em C9 e C6 com proporções de classe variadas
- [ ] F8.3 Curvas SLO agregado × pior modelo para cada política, nas três vistas e por classe
- [ ] F8.4 Objetivo padrão decidido pelo Gabriel e registrado; relatório F08

## F10 — Campanha final · gate [HUMANO]
- [ ] F10.1 Congelar commit e imagem
- [ ] F10.2 Matriz completa com repetições mínimas (inclui as cargas heterogêneas da F14)
- [ ] F10.3 Figuras e tabelas regeneráveis por um comando a partir de `execucoes.csv`, todas nas três vistas e com justiça
- [ ] F10.4 Relatório final com conclusões, limitações e ameaças à validade

## F11 — Consolidação · gate [HUMANO]
- [ ] F11.1 Pacote de artefatos
- [ ] F11.2 Rascunhos das seções de avaliação (artigos e dissertação)
