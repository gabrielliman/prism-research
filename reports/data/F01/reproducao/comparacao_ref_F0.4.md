
## ovl_phases/rate0.5/A0.1_phases  (referência: ovl_phases/rate0.5/A0.1_phases; 5 novas, 3 de referência)
| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] | p permutação (rotulações) | critério |
| --- | --- | --- | --- | --- | --- |
| SLO | 73.4 [73.3, 73.4] | 66.3 (73.6, 72.4, 65.9, 60.7, 58.7) | -7.1 [-12.4, -1.8] | 0.18 (56) | FALHOU |
| TTFT p90 (s) | 33.0 [32.6, 33.5] | 34.4 (31.0, 35.1, 37.6, 34.3, 33.8) | +1.4 [-0.5, +3.3] | 0.39 (56) | OK |
| TTFT p99 (s) | 53.4 [53.0, 53.8] | 57.2 (54.8, 54.4, 62.9, 54.0, 60.0) | +3.8 [+0.9, +7.2] | 0.12 (56) | (informativa) |
| pior espera pelo 1º token (s) | 58.4 [57.8, 59.0] | 61.7 (60.7, 57.4, 58.7, 60.0, 71.6) | +3.2 [-0.2, +8.4] | 0.52 (56) | OK |
| ativações | 15.0 [15.0, 15.0] | 15.0 (15.0, 15.0, 15.0, 15.0, 15.0) | +0.0 [+0.0, +0.0] | 1.00 (56) | (informativa) |
| perdas | 0.0 [0.0, 0.0] | 0.0 (0.0, 0.0, 0.0, 0.0, 0.0) | +0.0 [+0.0, +0.0] | 1.00 (56) | (informativa) |

## ovl_phases/rate0.5/A0.2_phases  (referência: ovl_phases/rate0.5/A0.2_phases; 5 novas, 3 de referência)
| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] | p permutação (rotulações) | critério |
| --- | --- | --- | --- | --- | --- |
| SLO | 90.7 [90.3, 90.9] | 81.8 (82.5, 80.2, 75.9, 85.7, 84.6) | -8.9 [-12.2, -6.1] | 0.04 (56) | FALHOU |
| TTFT p90 (s) | 0.5 [0.4, 0.6] | 7.1 (8.6, 10.3, 8.3, 3.8, 4.3) | +6.6 [+4.4, +8.8] | 0.04 (56) | FALHOU |
| TTFT p99 (s) | 20.0 [19.5, 20.2] | 23.6 (21.9, 26.0, 26.7, 21.7, 21.7) | +3.6 [+1.7, +5.7] | 0.07 (56) | (informativa) |
| pior espera pelo 1º token (s) | 21.8 [20.8, 23.6] | 25.3 (24.9, 30.3, 28.5, 21.2, 21.4) | +3.5 [+0.1, +6.9] | 0.21 (56) | FALHOU |
| ativações | 16.3 [16.0, 17.0] | 15.6 (16.0, 16.0, 15.0, 15.0, 16.0) | -0.7 [-1.5, -0.2] | 0.27 (56) | (informativa) |
| perdas | 0.0 [0.0, 0.0] | 0.0 (0.0, 0.0, 0.0, 0.0, 0.0) | +0.0 [+0.0, +0.0] | 1.00 (56) | (informativa) |

## ovl_trace_big/ts1/A0.3_trace12  (referência: ovl_trace_big/ts1/A0.3_trace12; 5 novas, 3 de referência)
| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] | p permutação (rotulações) | critério |
| --- | --- | --- | --- | --- | --- |
| SLO | 73.0 [70.0, 74.7] | 63.6 (69.0, 58.2, 54.9, 64.3, 71.6) | -9.4 [-15.6, -3.5] | 0.09 (56) | FALHOU |
| TTFT p90 (s) | 26.9 [26.6, 27.5] | 37.4 (33.1, 35.6, 53.5, 32.3, 32.6) | +10.5 [+5.6, +18.6] | 0.07 (56) | FALHOU |
| TTFT p99 (s) | 66.1 [63.3, 69.6] | 101.1 (83.2, 93.3, 173.4, 86.5, 69.2) | +35.0 [+10.7, +73.2] | 0.16 (56) | (informativa) |
| pior espera pelo 1º token (s) | 58.7 [48.2, 79.7] | 64.2 (59.7, 80.4, 53.5, 70.8, 56.6) | +5.4 [-14.3, +22.2] | 0.59 (56) | OK |
| ativações | 66.0 [63.0, 68.0] | 64.2 (64.0, 64.0, 64.0, 63.0, 66.0) | -1.8 [-4.0, +1.0] | 0.32 (56) | (informativa) |
| perdas | 0.0 [0.0, 0.0] | 0.0 (0.0, 0.0, 0.0, 0.0, 0.0) | +0.0 [+0.0, +0.0] | 1.00 (56) | (informativa) |

Ordem por SLO em ovl_phases/rate0.5: igual à referência

Critério de reprodução: FALHOU em ovl_phases/rate0.5/A0.1_phases SLO; ovl_phases/rate0.5/A0.2_phases SLO; ovl_phases/rate0.5/A0.2_phases TTFT p90 (s); ovl_phases/rate0.5/A0.2_phases pior espera pelo 1º token (s); ovl_trace_big/ts1/A0.3_trace12 SLO; ovl_trace_big/ts1/A0.3_trace12 TTFT p90 (s)
