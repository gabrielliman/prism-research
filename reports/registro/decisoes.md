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
