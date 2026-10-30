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
