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
- [ ] F2.1 Logs estruturados do controlador (retrato de estado + ações + motivo) e das requisições (prazo, classe, estado final)
- [ ] F2.2 `validate_run.py` (V1–V15) e `validate_campaign.py` (C-V1–C-V3)
- [ ] F2.2a Teste retroativo do validador nos dados de 28/10 (falhas conhecidas detectadas; execuções limpas aprovadas)
- [ ] F2.3 Estimador `Ĉ_at(m)` (tamanho + memória livre + ativações concorrentes), erro registrado
- [ ] F2.4 Estimador de prefill `p̂_r`, erro registrado
- [ ] F2.5 Estimadores `q̂_r` e `λ̂_m` (EWMA duas janelas), erro de previsão no horizonte `H`
- [ ] F2.6 Confirmar/refutar a observação 4.0 (SLO de 1 s × custo de ativação) com dados
- [ ] F2.7 Criar `execucoes.csv`, `decisoes.md`, `cargas.md`
- [ ] F2.8 Medir sobrecusto da instrumentação (≤ 2%)
- [ ] F2.10 Latência de referência por modelo: `TTFT_iso(m, L)` e `TPOT_iso(m)` (seção 5.4)
- [ ] F2.11 Métricas com SLO parametrizado (família + nível) e três vistas (combinada, só TTFT, só TPOT) + decomposição das violações; regressão: S1 reproduz os números de 28/10
- [ ] F2.12 Curvas S2 (`k_T` × `k_D`) e S3 retroativas nos dados de 28/10, nas três vistas
- [ ] F2.9 Relatório F02 com opções de família principal de SLO, níveis `k_T`/`k_D`/`k_A` e SLOs por classe, para decisão do Gabriel

## F3 — Catálogo de cargas · gate [HUMANO]
- [ ] F3.1 `overload_load.py`: leitura de trace, classes de SLO, recusa como estado final, sementes
- [ ] F3.2 C6 `zipf_drift`
- [ ] F3.3 C7 `bursty`
- [ ] F3.4 C8 `diurnal`
- [ ] F3.5 C9 `slo_classes`
- [ ] F3.6 C10 `sizes_mix` (verificar suporte dos modelos no SGLang 0.3.4)
- [ ] F3.7 C11 `slo_sweep` (famílias S2 e S3 da seção 5.4)
- [ ] F3.8 T2 LMSYS-Chat-1M (licença, popularidade real, chegadas sintéticas)
- [ ] F3.9 T3 Azure Functions (licença, mapeamento função → modelo)
- [ ] F3.10 T4 Azure LLM inference e T5 BurstGPT (se houver tempo)
- [ ] F3.11 Estatísticas antes/depois de cada transformação no `cargas.md`
- [ ] F3.12 Dry run de cada carga validado (V8, V11, V12)
- [ ] F3.13 Relatório F03 com a proposta de conjunto de cargas

## F4 — Restrições estruturais (A1) · gate automático
- [ ] F4.1 A1.1 reserva mínima de KV na ativação + testes unitários
- [ ] F4.2 A1.2 detector de impasse + testes unitários
- [ ] F4.3 A1.3 histerese mínima de residência + testes unitários
- [ ] F4.4 Campanha: C3, C1 (8 e 14 modelos), C2, T1 × {A0.1, A0.3} × {sem, com A1}, 5 repetições
- [ ] F4.5 Zero impasses; sem piora significativa nos cenários sem impasse
- [ ] F4.6 Parâmetros `b`, `Δ_imp`, `T_min` registrados; relatório F04

## F5 — Linhas de base na nova metodologia · gate [HUMANO]
- [ ] F5.1 A0.1–A0.5 (+A1) em todas as cargas aprovadas, níveis de `ρ_mem` definidos, 5 repetições
- [ ] F5.2 Tabelas e figuras de referência (SLO total, evitáveis/inevitáveis, pior modelo, trocas, perdas)
- [ ] F5.2a Curvas de todas as famílias de SLO calculadas pós-execução; SLO mínimo atingível (90% e 99%) por política e carga, nas três vistas
- [ ] F5.2c Decomposição das violações (ambos / só TTFT / só TPOT / nenhum) e CDFs de TTFT e TPOT normalizados, por política e por modelo
- [ ] F5.2b Escolher o subconjunto de níveis de SLO para as políticas por prazo (alto, meio da queda, baixo) e registrar em `decisoes.md`
- [ ] F5.3 C-V1 e C-V2 satisfeitos; relatório F05 com proposta de conteúdo do artigo parcial

## F6 — Ativação e despejo por folga (A2–A4) e por atraso virtual (A9) · gate [HUMANO]
- [ ] F6.1 A2.1 EDF entre modelos + testes
- [ ] F6.2 A2.2 menor folga com antecipação (+ variação do ciclo do controlador) + testes
- [ ] F6.3 A2.3 residência preditiva (`λ̂`, horizonte `H`) + testes
- [ ] F6.4 A3.1–A3.3 despejo por perda esperada, drenar × preemptar + testes
- [ ] F6.5 A4 política combinada
- [ ] F6.6 Ablação em C1, C2, C3, C6, C7, C11, T1 contra A0.1 e a melhor linha de base, 5 repetições
- [ ] F6.7 Sensibilidade de margem, `H`, `θ`, ciclo; escolha registrada
- [ ] F6.8 IC 95% pareado por semente para cada comparação, nas três vistas (combinada, só TTFT, só TPOT); explicação mecânica de toda diferença > 2× e de toda troca de violação de TTFT por TPOT (ou o inverso)
- [ ] F6.10 A9.1 LVF entre modelos (VLT do SuperInfer) e A9.2 LVF com custo de ativação + testes (`tests/policy/`)
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
