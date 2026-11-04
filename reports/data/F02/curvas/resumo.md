# Curvas de SLO das políticas sem prazo (gerado por `polyaxon/slo_curves.py`)

Médias sobre as repetições válidas. S2: SLO de TTFT = k_T·TTFT_base(m), de TPOT = k_D·TPOT_base(m), com a base P95 da carga do modelo em GPU dedicada (D20, D21); S2M: o mesmo com a base P50; S3: SLO de TTFT = k_A·Ĉ_at(m). Frações sobre todas as enviadas.

## S2: ovl_mem rate0.2

SLO mínimo atingível em k_T (S2, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| rodízio | 3 | — / — | — / — | 3.0 / 3.0 |
| folga de KV | 3 | — / — | — / — | 3.0 / 5.0 |
| limiar 1 s | 3 | — / — | — / — | 3.0 / 5.0 |
| A0.2 limiar 10 s | 3 | — / — | — / — | 3.0 / 10.0 |
| A0.1 original (50 s) | 5 | — / — | — / — | 3.0 / 5.0 |
| A0.3 troca P0D1 | 2 | — / — | — / — | 3.0 / 5.0 |
| troca P1D0 | 3 | — / — | — / — | 3.0 / 3.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: A0.1 original (50 s) (17%) > folga de KV (17%) > A0.2 limiar 10 s (15%) > rodízio (13%) > limiar 1 s (9%) > troca P1D0 (8%) > A0.3 troca P0D1 (7%)
- k_T = 5: folga de KV (63%) > A0.1 original (50 s) (62%) > A0.2 limiar 10 s (51%) > rodízio (40%) > limiar 1 s (36%) > A0.3 troca P0D1 (22%) > troca P1D0 (15%)
- k_T = 10: A0.1 original (50 s) (65%) > folga de KV (64%) > A0.2 limiar 10 s (53%) > rodízio (41%) > limiar 1 s (37%) > A0.3 troca P0D1 (24%) > troca P1D0 (16%)
- k_T = 25: A0.1 original (50 s) (66%) > folga de KV (66%) > A0.2 limiar 10 s (54%) > rodízio (44%) > limiar 1 s (39%) > A0.3 troca P0D1 (26%) > troca P1D0 (18%)
- k_T = 50: folga de KV (66%) > A0.1 original (50 s) (66%) > A0.2 limiar 10 s (55%) > rodízio (46%) > limiar 1 s (42%) > A0.3 troca P0D1 (30%) > troca P1D0 (21%)
- k_T = 100: folga de KV (66%) > A0.1 original (50 s) (66%) > A0.2 limiar 10 s (58%) > rodízio (50%) > limiar 1 s (47%) > A0.3 troca P0D1 (36%) > troca P1D0 (27%)

A ordem muda 3 vez(es) entre níveis consecutivos de k_T.

## S2: ovl_mem rate0.5

SLO mínimo atingível em k_T (S2, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| limiar 1 s | 2 | — / — | — / — | 5.0 / 5.0 |
| A0.2 limiar 10 s | 3 | — / — | — / — | 5.0 / 5.0 |
| A0.1 original (50 s) | 3 | — / — | — / — | 5.0 / 5.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: A0.2 limiar 10 s (11%) > A0.1 original (50 s) (7%) > limiar 1 s (5%)
- k_T = 5: A0.2 limiar 10 s (28%) > A0.1 original (50 s) (19%) > limiar 1 s (17%)
- k_T = 10: A0.2 limiar 10 s (29%) > A0.1 original (50 s) (20%) > limiar 1 s (17%)
- k_T = 25: A0.2 limiar 10 s (31%) > A0.1 original (50 s) (22%) > limiar 1 s (19%)
- k_T = 50: A0.2 limiar 10 s (33%) > A0.1 original (50 s) (24%) > limiar 1 s (23%)
- k_T = 100: A0.2 limiar 10 s (38%) > A0.1 original (50 s) (28%) > limiar 1 s (27%)

A ordem muda 0 vez(es) entre níveis consecutivos de k_T.

## S2: ovl_mix rate0.2

SLO mínimo atingível em k_T (S2, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| A0.1 original (50 s) | 2 | — / — | — / — | — / — |
| A0.3 troca P0D1 | 2 | — / — | — / — | 3.0 / 5.0 |
| troca P1D0 | 3 | — / — | — / — | 3.0 / 3.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: troca P1D0 (28%) > A0.3 troca P0D1 (27%) > A0.1 original (50 s) (2%)
- k_T = 5: A0.3 troca P0D1 (52%) > troca P1D0 (44%) > A0.1 original (50 s) (2%)
- k_T = 10: A0.3 troca P0D1 (53%) > troca P1D0 (45%) > A0.1 original (50 s) (2%)
- k_T = 25: A0.3 troca P0D1 (55%) > troca P1D0 (48%) > A0.1 original (50 s) (2%)
- k_T = 50: A0.3 troca P0D1 (57%) > troca P1D0 (50%) > A0.1 original (50 s) (2%)
- k_T = 100: A0.3 troca P0D1 (64%) > troca P1D0 (58%) > A0.1 original (50 s) (2%)

A ordem muda 1 vez(es) entre níveis consecutivos de k_T.

## S2: ovl_phases rate0.5

SLO mínimo atingível em k_T (S2, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| limiar 1 s | 3 | 25.0 / — | 25.0 / — | 2.0 / 5.0 |
| A0.2 limiar 10 s | 3 | 25.0 / — | 25.0 / — | 2.0 / 5.0 |
| A0.1 original (50 s) | 4 | — / — | — / — | 3.0 / 5.0 |
| pressão | 3 | 100.0 / — | 100.0 / — | 2.0 / 5.0 |
| A0.3 troca P0D1 | 3 | 100.0 / — | 100.0 / — | 2.0 / 3.0 |
| troca P1D0 | 3 | 100.0 / — | 100.0 / — | 3.0 / 3.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: limiar 1 s (86%) > A0.2 limiar 10 s (84%) > troca P1D0 (77%) > A0.3 troca P0D1 (76%) > pressão (73%) > A0.1 original (50 s) (67%)
- k_T = 5: limiar 1 s (88%) > A0.2 limiar 10 s (88%) > troca P1D0 (81%) > A0.3 troca P0D1 (79%) > pressão (76%) > A0.1 original (50 s) (71%)
- k_T = 10: limiar 1 s (89%) > A0.2 limiar 10 s (89%) > troca P1D0 (82%) > A0.3 troca P0D1 (80%) > pressão (77%) > A0.1 original (50 s) (72%)
- k_T = 25: limiar 1 s (91%) > A0.2 limiar 10 s (90%) > troca P1D0 (85%) > A0.3 troca P0D1 (83%) > pressão (80%) > A0.1 original (50 s) (74%)
- k_T = 50: limiar 1 s (93%) > A0.2 limiar 10 s (92%) > troca P1D0 (89%) > A0.3 troca P0D1 (86%) > pressão (84%) > A0.1 original (50 s) (76%)
- k_T = 100: limiar 1 s (97%) > A0.2 limiar 10 s (96%) > troca P1D0 (94%) > A0.3 troca P0D1 (92%) > pressão (90%) > A0.1 original (50 s) (80%)

A ordem muda 0 vez(es) entre níveis consecutivos de k_T.

## S2: ovl_trace_big ts0.5

SLO mínimo atingível em k_T (S2, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| limiar 1 s | 3 | — / — | — / — | 3.0 / 10.0 |
| A0.2 limiar 10 s | 2 | — / — | — / — | 3.0 / 10.0 |
| A0.1 original (50 s) | 3 | — / — | — / — | 3.0 / 10.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: A0.1 original (50 s) (43%) > limiar 1 s (41%) > A0.2 limiar 10 s (39%)
- k_T = 5: limiar 1 s (62%) > A0.1 original (50 s) (60%) > A0.2 limiar 10 s (54%)
- k_T = 10: limiar 1 s (62%) > A0.1 original (50 s) (62%) > A0.2 limiar 10 s (55%)
- k_T = 25: A0.1 original (50 s) (63%) > limiar 1 s (63%) > A0.2 limiar 10 s (57%)
- k_T = 50: limiar 1 s (65%) > A0.1 original (50 s) (64%) > A0.2 limiar 10 s (58%)
- k_T = 100: limiar 1 s (65%) > A0.1 original (50 s) (64%) > A0.2 limiar 10 s (59%)

A ordem muda 3 vez(es) entre níveis consecutivos de k_T.

## S2: ovl_trace_big ts1

SLO mínimo atingível em k_T (S2, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| limiar 1 s | 2 | — / — | — / — | 3.0 / 5.0 |
| A0.2 limiar 10 s | 3 | — / — | — / — | 3.0 / 10.0 |
| A0.1 original (50 s) | 4 | — / — | — / — | 3.0 / 5.0 |
| A0.3 troca P0D1 | 2 | — / — | — / — | 3.0 / 5.0 |
| troca P1D0 | 3 | — / — | — / — | 3.0 / 5.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: A0.1 original (50 s) (65%) > A0.2 limiar 10 s (61%) > A0.3 troca P0D1 (58%) > limiar 1 s (53%) > troca P1D0 (46%)
- k_T = 5: A0.1 original (50 s) (79%) > limiar 1 s (78%) > A0.2 limiar 10 s (76%) > A0.3 troca P0D1 (72%) > troca P1D0 (54%)
- k_T = 10: A0.1 original (50 s) (81%) > limiar 1 s (79%) > A0.2 limiar 10 s (78%) > A0.3 troca P0D1 (73%) > troca P1D0 (55%)
- k_T = 25: A0.1 original (50 s) (81%) > limiar 1 s (80%) > A0.2 limiar 10 s (80%) > A0.3 troca P0D1 (74%) > troca P1D0 (56%)
- k_T = 50: limiar 1 s (83%) > A0.1 original (50 s) (82%) > A0.2 limiar 10 s (81%) > A0.3 troca P0D1 (75%) > troca P1D0 (58%)
- k_T = 100: limiar 1 s (85%) > A0.2 limiar 10 s (83%) > A0.1 original (50 s) (82%) > A0.3 troca P0D1 (77%) > troca P1D0 (61%)

A ordem muda 3 vez(es) entre níveis consecutivos de k_T.

## S2M: ovl_mem rate0.2

SLO mínimo atingível em k_T (S2M, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| rodízio | 3 | — / — | — / — | 10.0 / 10.0 |
| folga de KV | 3 | — / — | — / — | 10.0 / 20.0 |
| limiar 1 s | 3 | — / — | — / — | 10.0 / 20.0 |
| A0.2 limiar 10 s | 3 | — / — | — / — | 10.0 / 20.0 |
| A0.1 original (50 s) | 5 | — / — | — / — | 10.0 / 10.0 |
| A0.3 troca P0D1 | 2 | — / — | — / — | 10.0 / 10.0 |
| troca P1D0 | 3 | — / — | — / — | 10.0 / 10.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: A0.1 original (50 s) (1%) > A0.2 limiar 10 s (0%) > limiar 1 s (0%) > A0.3 troca P0D1 (0%) > folga de KV (0%) > troca P1D0 (0%) > rodízio (0%)
- k_T = 5: A0.1 original (50 s) (41%) > folga de KV (40%) > A0.2 limiar 10 s (33%) > rodízio (27%) > limiar 1 s (23%) > A0.3 troca P0D1 (15%) > troca P1D0 (12%)
- k_T = 10: A0.1 original (50 s) (62%) > folga de KV (61%) > A0.2 limiar 10 s (50%) > rodízio (40%) > limiar 1 s (36%) > A0.3 troca P0D1 (22%) > troca P1D0 (15%)
- k_T = 25: A0.1 original (50 s) (64%) > folga de KV (63%) > A0.2 limiar 10 s (51%) > rodízio (42%) > limiar 1 s (36%) > A0.3 troca P0D1 (24%) > troca P1D0 (16%)
- k_T = 50: A0.1 original (50 s) (65%) > folga de KV (63%) > A0.2 limiar 10 s (52%) > rodízio (44%) > limiar 1 s (38%) > A0.3 troca P0D1 (26%) > troca P1D0 (18%)
- k_T = 100: A0.1 original (50 s) (65%) > folga de KV (64%) > A0.2 limiar 10 s (53%) > rodízio (46%) > limiar 1 s (41%) > A0.3 troca P0D1 (30%) > troca P1D0 (21%)

A ordem muda 1 vez(es) entre níveis consecutivos de k_T.

## S2M: ovl_mem rate0.5

SLO mínimo atingível em k_T (S2M, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| limiar 1 s | 2 | — / — | — / — | 10.0 / 20.0 |
| A0.2 limiar 10 s | 3 | — / — | — / — | 10.0 / 10.0 |
| A0.1 original (50 s) | 3 | — / — | — / — | 10.0 / 20.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: A0.2 limiar 10 s (0%) > A0.1 original (50 s) (0%) > limiar 1 s (0%)
- k_T = 5: A0.2 limiar 10 s (20%) > A0.1 original (50 s) (13%) > limiar 1 s (11%)
- k_T = 10: A0.2 limiar 10 s (28%) > A0.1 original (50 s) (19%) > limiar 1 s (16%)
- k_T = 25: A0.2 limiar 10 s (29%) > A0.1 original (50 s) (20%) > limiar 1 s (17%)
- k_T = 50: A0.2 limiar 10 s (31%) > A0.1 original (50 s) (22%) > limiar 1 s (19%)
- k_T = 100: A0.2 limiar 10 s (34%) > A0.1 original (50 s) (24%) > limiar 1 s (22%)

A ordem muda 0 vez(es) entre níveis consecutivos de k_T.

## S2M: ovl_mix rate0.2

SLO mínimo atingível em k_T (S2M, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| A0.1 original (50 s) | 2 | — / — | — / — | — / — |
| A0.3 troca P0D1 | 2 | — / — | — / — | 10.0 / 10.0 |
| troca P1D0 | 3 | — / — | — / — | 10.0 / 10.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: troca P1D0 (1%) > A0.3 troca P0D1 (0%) > A0.1 original (50 s) (0%)
- k_T = 5: troca P1D0 (26%) > A0.3 troca P0D1 (25%) > A0.1 original (50 s) (1%)
- k_T = 10: A0.3 troca P0D1 (50%) > troca P1D0 (44%) > A0.1 original (50 s) (2%)
- k_T = 25: A0.3 troca P0D1 (53%) > troca P1D0 (45%) > A0.1 original (50 s) (2%)
- k_T = 50: A0.3 troca P0D1 (54%) > troca P1D0 (47%) > A0.1 original (50 s) (2%)
- k_T = 100: A0.3 troca P0D1 (56%) > troca P1D0 (49%) > A0.1 original (50 s) (2%)

A ordem muda 1 vez(es) entre níveis consecutivos de k_T.

## S2M: ovl_phases rate0.5

SLO mínimo atingível em k_T (S2M, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| limiar 1 s | 3 | 100.0 / — | 50.0 / — | 5.0 / 20.0 |
| A0.2 limiar 10 s | 3 | — / — | 100.0 / — | 5.0 / 20.0 |
| A0.1 original (50 s) | 4 | — / — | — / — | 10.0 / 10.0 |
| pressão | 3 | — / — | — / — | 5.0 / 10.0 |
| A0.3 troca P0D1 | 3 | — / — | — / — | 5.0 / 10.0 |
| troca P1D0 | 3 | — / — | — / — | 5.0 / 10.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: A0.1 original (50 s) (3%) > A0.2 limiar 10 s (2%) > A0.3 troca P0D1 (2%) > troca P1D0 (2%) > pressão (1%) > limiar 1 s (1%)
- k_T = 5: limiar 1 s (81%) > A0.2 limiar 10 s (78%) > A0.3 troca P0D1 (73%) > troca P1D0 (72%) > pressão (70%) > A0.1 original (50 s) (63%)
- k_T = 10: limiar 1 s (86%) > A0.2 limiar 10 s (86%) > troca P1D0 (79%) > A0.3 troca P0D1 (78%) > pressão (74%) > A0.1 original (50 s) (70%)
- k_T = 25: limiar 1 s (87%) > A0.2 limiar 10 s (87%) > troca P1D0 (81%) > A0.3 troca P0D1 (79%) > pressão (76%) > A0.1 original (50 s) (71%)
- k_T = 50: limiar 1 s (89%) > A0.2 limiar 10 s (88%) > troca P1D0 (83%) > A0.3 troca P0D1 (81%) > pressão (78%) > A0.1 original (50 s) (73%)
- k_T = 100: limiar 1 s (90%) > A0.2 limiar 10 s (89%) > troca P1D0 (86%) > A0.3 troca P0D1 (83%) > pressão (81%) > A0.1 original (50 s) (74%)

A ordem muda 2 vez(es) entre níveis consecutivos de k_T.

## S2M: ovl_trace_big ts0.5

SLO mínimo atingível em k_T (S2M, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| limiar 1 s | 3 | — / — | — / — | 10.0 / 20.0 |
| A0.2 limiar 10 s | 2 | — / — | — / — | 10.0 / 20.0 |
| A0.1 original (50 s) | 3 | — / — | — / — | 10.0 / 20.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: A0.1 original (50 s) (1%) > A0.2 limiar 10 s (1%) > limiar 1 s (1%)
- k_T = 5: A0.1 original (50 s) (41%) > limiar 1 s (39%) > A0.2 limiar 10 s (37%)
- k_T = 10: limiar 1 s (60%) > A0.1 original (50 s) (59%) > A0.2 limiar 10 s (52%)
- k_T = 25: limiar 1 s (62%) > A0.1 original (50 s) (60%) > A0.2 limiar 10 s (54%)
- k_T = 50: limiar 1 s (63%) > A0.1 original (50 s) (61%) > A0.2 limiar 10 s (55%)
- k_T = 100: limiar 1 s (64%) > A0.1 original (50 s) (62%) > A0.2 limiar 10 s (56%)

A ordem muda 2 vez(es) entre níveis consecutivos de k_T.

## S2M: ovl_trace_big ts1

SLO mínimo atingível em k_T (S2M, k_D = 10 na vista combinada), 90% / 99%:

| política | repetições | combinada | só TTFT | só TPOT (em k_D) |
| --- | --- | --- | --- | --- |
| limiar 1 s | 2 | — / — | — / — | 10.0 / 10.0 |
| A0.2 limiar 10 s | 3 | — / — | — / — | 10.0 / 20.0 |
| A0.1 original (50 s) | 4 | — / — | — / — | 10.0 / 20.0 |
| A0.3 troca P0D1 | 2 | — / — | — / — | 10.0 / 10.0 |
| troca P1D0 | 3 | — / — | — / — | 10.0 / 10.0 |

Melhor política na vista combinada (k_D = 10) a cada k_T, e ordem entre as políticas:

- k_T = 2: A0.1 original (50 s) (5%) > A0.2 limiar 10 s (4%) > troca P1D0 (3%) > A0.3 troca P0D1 (3%) > limiar 1 s (2%)
- k_T = 5: A0.1 original (50 s) (63%) > A0.2 limiar 10 s (59%) > A0.3 troca P0D1 (56%) > limiar 1 s (51%) > troca P1D0 (45%)
- k_T = 10: A0.1 original (50 s) (77%) > limiar 1 s (76%) > A0.2 limiar 10 s (75%) > A0.3 troca P0D1 (71%) > troca P1D0 (54%)
- k_T = 25: A0.1 original (50 s) (80%) > limiar 1 s (79%) > A0.2 limiar 10 s (77%) > A0.3 troca P0D1 (72%) > troca P1D0 (55%)
- k_T = 50: A0.1 original (50 s) (80%) > limiar 1 s (79%) > A0.2 limiar 10 s (78%) > A0.3 troca P0D1 (72%) > troca P1D0 (55%)
- k_T = 100: limiar 1 s (82%) > A0.1 original (50 s) (80%) > A0.2 limiar 10 s (79%) > A0.3 troca P0D1 (73%) > troca P1D0 (57%)

A ordem muda 3 vez(es) entre níveis consecutivos de k_T.

