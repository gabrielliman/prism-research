Referência sem as rodadas: fix3

## ovl_phases/rate0.5/A0.1_phases  (referência: ovl_phases/rate0.5/original; 5 novas, 3 de referência)
| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] | p permutação (rotulações) | critério |
| --- | --- | --- | --- | --- | --- |
| SLO | 72.3 [71.2, 73.3] | 66.3 (73.6, 72.4, 65.9, 60.7, 58.7) | -6.0 [-11.3, -0.9] | 0.27 (56) | FALHOU |
| TTFT p90 (s) | 33.3 [32.3, 34.1] | 34.4 (31.0, 35.1, 37.6, 34.3, 33.8) | +1.1 [-1.0, +3.1] | 0.48 (56) | OK |
| TTFT p99 (s) | 54.2 [53.7, 55.0] | 57.2 (54.8, 54.4, 62.9, 54.0, 60.0) | +3.1 [+0.1, +6.4] | 0.21 (56) | (informativa) |
| pior espera pelo 1º token (s) | 58.5 [57.4, 59.1] | 61.7 (60.7, 57.4, 58.7, 60.0, 71.6) | +3.2 [-0.3, +8.3] | 0.54 (56) | OK |
| ativações | 15.0 [15.0, 15.0] | 15.0 (15.0, 15.0, 15.0, 15.0, 15.0) | +0.0 [+0.0, +0.0] | 1.00 (56) | (informativa) |
| perdas | 0.0 [0.0, 0.0] | 0.0 (0.0, 0.0, 0.0, 0.0, 0.0) | +0.0 [+0.0, +0.0] | 1.00 (56) | (informativa) |

## ovl_phases/rate0.5/A0.2_phases  (referência: ovl_phases/rate0.5/idle10; 5 novas, 2 de referência)
| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] | p permutação (rotulações) | critério |
| --- | --- | --- | --- | --- | --- |
| SLO | 89.7 [89.1, 90.4] | 81.8 (82.5, 80.2, 75.9, 85.7, 84.6) | -7.9 [-11.2, -5.1] | 0.10 (21) | FALHOU |
| TTFT p90 (s) | 1.1 [0.3, 1.8] | 7.1 (8.6, 10.3, 8.3, 3.8, 4.3) | +6.0 [+3.5, +8.5] | 0.05 (21) | FALHOU |
| TTFT p99 (s) | 20.5 [20.4, 20.6] | 23.6 (21.9, 26.0, 26.7, 21.7, 21.7) | +3.1 [+1.2, +5.0] | 0.10 (21) | (informativa) |
| pior espera pelo 1º token (s) | 21.0 [20.8, 21.1] | 25.3 (24.9, 30.3, 28.5, 21.2, 21.4) | +4.3 [+1.1, +7.5] | 0.14 (21) | FALHOU |
| ativações | 15.5 [15.0, 16.0] | 15.6 (16.0, 16.0, 15.0, 15.0, 16.0) | +0.1 [-0.6, +0.8] | 1.00 (21) | (informativa) |
| perdas | 0.0 [0.0, 0.0] | 0.0 (0.0, 0.0, 0.0, 0.0, 0.0) | +0.0 [+0.0, +0.0] | 1.00 (21) | (informativa) |

## ovl_trace_big/ts1/A0.3_trace12  (referência: ovl_trace_big/ts1/tp_P0D1; 5 novas, 2 de referência)
| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] | p permutação (rotulações) | critério |
| --- | --- | --- | --- | --- | --- |
| SLO | 72.4 [71.7, 73.1] | 63.6 (69.0, 58.2, 54.9, 64.3, 71.6) | -8.8 [-14.3, -3.3] | 0.14 (21) | FALHOU |
| TTFT p90 (s) | 28.3 [28.0, 28.7] | 37.4 (33.1, 35.6, 53.5, 32.3, 32.6) | +9.1 [+4.2, +17.2] | 0.24 (21) | FALHOU |
| TTFT p99 (s) | 67.9 [60.1, 75.7] | 101.1 (83.2, 93.3, 173.4, 86.5, 69.2) | +33.2 [+5.2, +71.5] | 0.38 (21) | (informativa) |
| pior espera pelo 1º token (s) | 51.0 [48.3, 53.7] | 64.2 (59.7, 80.4, 53.5, 70.8, 56.6) | +13.2 [+4.3, +23.2] | 0.19 (21) | FALHOU |
| ativações | 66.5 [65.0, 68.0] | 64.2 (64.0, 64.0, 64.0, 63.0, 66.0) | -2.3 [-4.4, -0.2] | 0.10 (21) | (informativa) |
| perdas | 0.0 [0.0, 0.0] | 0.0 (0.0, 0.0, 0.0, 0.0, 0.0) | +0.0 [+0.0, +0.0] | 1.00 (21) | (informativa) |

Ordem por SLO em ovl_phases/rate0.5: igual à referência

Critério de reprodução: FALHOU em ovl_phases/rate0.5/A0.1_phases SLO; ovl_phases/rate0.5/A0.2_phases SLO; ovl_phases/rate0.5/A0.2_phases TTFT p90 (s); ovl_phases/rate0.5/A0.2_phases pior espera pelo 1º token (s); ovl_trace_big/ts1/A0.3_trace12 SLO; ovl_trace_big/ts1/A0.3_trace12 TTFT p90 (s); ovl_trace_big/ts1/A0.3_trace12 pior espera pelo 1º token (s)
