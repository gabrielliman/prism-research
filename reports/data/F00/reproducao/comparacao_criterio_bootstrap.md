Referência sem as rodadas: fix3

## ovl_phases/rate0.5/A0.1_phases  (referência: ovl_phases/rate0.5/original; 3 novas, 3 de referência)
| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] | p permutação (rotulações) | critério |
| --- | --- | --- | --- | --- | --- |
| SLO | 72.3 [71.2, 73.3] | 73.4 (73.3, 73.4, 73.4) | +1.1 [+0.1, +2.2] | 0.10 (20) | FALHOU |
| TTFT p90 (s) | 33.3 [32.3, 34.1] | 33.0 (33.5, 32.6, 32.8) | -0.4 [-1.3, +0.6] | 0.60 (20) | OK |
| TTFT p99 (s) | 54.2 [53.7, 55.0] | 53.4 (53.8, 53.5, 53.0) | -0.7 [-1.6, -0.1] | 0.20 (20) | (informativa) |
| pior espera pelo 1º token (s) | 58.5 [57.4, 59.1] | 58.4 (57.8, 59.0, 58.6) | -0.0 [-1.0, +1.0] | 1.00 (20) | OK |
| ativações | 15.0 [15.0, 15.0] | 15.0 (15.0, 15.0, 15.0) | +0.0 [+0.0, +0.0] | 1.00 (20) | (informativa) |
| perdas | 0.0 [0.0, 0.0] | 0.0 (0.0, 0.0, 0.0) | +0.0 [+0.0, +0.0] | 1.00 (20) | (informativa) |

## ovl_phases/rate0.5/A0.2_phases  (referência: ovl_phases/rate0.5/idle10; 3 novas, 2 de referência)
| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] | p permutação (rotulações) | critério |
| --- | --- | --- | --- | --- | --- |
| SLO | 89.7 [89.1, 90.4] | 90.7 (90.9, 90.3, 90.9) | +1.0 [+0.1, +1.8] | 0.20 (10) | FALHOU |
| TTFT p90 (s) | 1.1 [0.3, 1.8] | 0.5 (0.5, 0.6, 0.4) | -0.6 [-1.4, +0.3] | 0.50 (10) | OK |
| TTFT p99 (s) | 20.5 [20.4, 20.6] | 20.0 (19.5, 20.2, 20.2) | -0.5 [-1.0, -0.2] | 0.30 (10) | (informativa) |
| pior espera pelo 1º token (s) | 21.0 [20.8, 21.1] | 21.8 (20.8, 20.9, 23.6) | +0.8 [-0.3, +2.6] | 0.90 (10) | OK |
| ativações | 15.5 [15.0, 16.0] | 16.3 (16.0, 16.0, 17.0) | +0.8 [+0.0, +1.7] | 0.60 (10) | (informativa) |
| perdas | 0.0 [0.0, 0.0] | 0.0 (0.0, 0.0, 0.0) | +0.0 [+0.0, +0.0] | 1.00 (10) | (informativa) |

## ovl_trace_big/ts1/A0.3_trace12  (referência: ovl_trace_big/ts1/tp_P0D1; 3 novas, 2 de referência)
| métrica | referência: média [mín, máx] | nova: média (repetições) | diferença [IC 95% bootstrap] | p permutação (rotulações) | critério |
| --- | --- | --- | --- | --- | --- |
| SLO | 72.4 [71.7, 73.1] | 73.0 (74.4, 74.7, 70.0) | +0.6 [-2.4, +2.9] | 0.90 (10) | OK |
| TTFT p90 (s) | 28.3 [28.0, 28.7] | 26.9 (27.5, 26.6, 26.8) | -1.4 [-2.0, -0.8] | 0.10 (10) | FALHOU |
| TTFT p99 (s) | 67.9 [60.1, 75.7] | 66.1 (63.3, 65.4, 69.6) | -1.8 [-11.7, +8.1] | 0.80 (10) | (informativa) |
| pior espera pelo 1º token (s) | 51.0 [48.3, 53.7] | 58.7 (48.2, 48.3, 79.7) | +7.7 [-5.5, +28.7] | 1.00 (10) | OK |
| ativações | 66.5 [65.0, 68.0] | 66.0 (68.0, 67.0, 63.0) | -0.5 [-3.7, +2.7] | 0.90 (10) | (informativa) |
| perdas | 0.0 [0.0, 0.0] | 0.0 (0.0, 0.0, 0.0) | +0.0 [+0.0, +0.0] | 1.00 (10) | (informativa) |

Ordem por SLO em ovl_phases/rate0.5: igual à referência

Critério de reprodução: FALHOU em ovl_phases/rate0.5/A0.1_phases SLO; ovl_phases/rate0.5/A0.2_phases SLO; ovl_trace_big/ts1/A0.3_trace12 TTFT p90 (s)
