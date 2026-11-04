# Ĉ_at: custo de ativação e de desativação (gerado por `polyaxon/activation_cost.py fit reports/data/F02/cat/custos.csv`)

Modelo: `Ĉ_at = 0.463 + 0.0628·W_GB + 1.144·ahead` (s), ajustado pela mediana (regressão L1) em 6547 ativações de 66 jobs. `ahead` = ativações já em andamento no pedido (o model service carrega um modelo por vez).

Erro relativo fora da amostra (ajuste nos jobs pares, avaliação nos ímpares e vice-versa): mediana 11.8%, p90 71.4%.

## Ativação (pedido → sucesso no GPU scheduler), s

| Grupo | n | p50 | p90 | p99 | máx |
| --- | --- | --- | --- | --- | --- |
| W = 5.9 GB | 65 | 0.89 | 2.37 | 4.72 | 5.27 |
| W = 5.9 GB, ahead = 0 | 37 | 0.92 | 2.40 | 2.87 | 2.96 |
| W = 5.9 GB, ahead = 1 | 26 | 0.87 | 2.00 | 2.22 | 2.23 |
| W = 5.9 GB, ahead = 2 | 2 | 4.84 | 5.18 | 5.26 | 5.27 |
| W = 15.0 GB | 6482 | 1.43 | 3.55 | 8.34 | 61.28 |
| W = 15.0 GB, ahead = 0 | 5005 | 1.40 | 3.02 | 7.42 | 61.28 |
| W = 15.0 GB, ahead = 1 | 1350 | 2.56 | 4.14 | 9.57 | 36.93 |
| W = 15.0 GB, ahead = 2 | 113 | 2.88 | 6.64 | 11.43 | 25.14 |
| W = 15.0 GB, ahead = 3 | 9 | 4.36 | 6.94 | 8.15 | 8.29 |
| W = 15.0 GB, ahead = 4+ | 5 | 8.58 | 15.85 | 17.96 | 18.19 |

Erro relativo fora da amostra por grupo:

| Grupo | n | mediana | p90 |
| --- | --- | --- | --- |
| W = 5.9 GB, ahead = 0 | 37 | 11.4% | 65.0% |
| W = 5.9 GB, ahead = 1 | 26 | 127.0% | 161.8% |
| W = 5.9 GB, ahead = 2 | 2 | 36.0% | 40.5% |
| W = 15.0 GB, ahead = 0 | 5005 | 9.9% | 53.8% |
| W = 15.0 GB, ahead = 1 | 1350 | 37.4% | 101.6% |
| W = 15.0 GB, ahead = 2 | 113 | 42.8% | 192.1% |
| W = 15.0 GB, ahead = 3 | 9 | 26.3% | 103.5% |
| W = 15.0 GB, ahead = 4 | 5 | 51.3% | 62.7% |

## Ativação por memória livre vista pelo controlador (ahead = 0), s

| Memória livre | n | p50 | p90 | p99 | máx |
| --- | --- | --- | --- | --- | --- |
| (0, 20] GB | 51 | 1.30 | 2.66 | 4.05 | 4.99 |
| (20, 40] GB | 3403 | 1.38 | 2.56 | 5.92 | 41.27 |
| (40, 80] GB | 1520 | 2.17 | 3.88 | 8.08 | 61.28 |
| (80, 200] GB | 68 | 1.30 | 6.49 | 17.13 | 31.90 |

## Desativação, s

Pedido → sucesso no GPU scheduler (inclui a drenagem nas variantes com drenagem) e, quando o log tem a linha de custo do worker (código a partir da F1.7), só a liberação de memória no worker, onde está a cauda da P11.

| Grupo | n | p50 | p90 | p99 | máx |
| --- | --- | --- | --- | --- | --- |
| GPU scheduler, sem drenagem | 5153 | 0.65 | 5.56 | 24.01 | 53.70 |
| GPU scheduler, com drenagem | 1805 | 8.28 | 20.96 | 38.20 | 83.05 |
| liberação no worker (todas) | 6958 | 0.55 | 1.51 | 9.78 | 38.88 |
| liberação no worker, rodada codenew | 45 | 0.88 | 7.93 | 12.46 | 14.53 |
| liberação no worker, rodada codeold | 45 | 0.87 | 2.99 | 4.48 | 4.62 |
| liberação no worker, rodada f0 | 300 | 0.43 | 0.86 | 1.89 | 30.32 |
| liberação no worker, rodada f1b | 396 | 0.46 | 1.73 | 5.06 | 7.58 |
| liberação no worker, rodada f1code | 90 | 0.87 | 4.31 | 10.35 | 14.53 |
| liberação no worker, rodada f1loss | 1422 | 0.56 | 3.21 | 17.90 | 38.88 |
| liberação no worker, rodada f1repro | 488 | 0.59 | 4.05 | 16.23 | 30.07 |
| liberação no worker, rodada fix | 265 | 0.51 | 0.78 | 2.13 | 6.92 |
| liberação no worker, rodada fix2 | 1630 | 0.56 | 0.92 | 3.16 | 17.41 |
| liberação no worker, rodada fix5 | 2235 | 0.55 | 0.87 | 3.50 | 20.96 |
| liberação no worker, rodada headroom | 26 | 0.67 | 1.33 | 2.39 | 2.42 |
| liberação no worker, rodada headroom-f1 | 16 | 0.61 | 0.84 | 0.88 | 0.88 |

Liberação no worker > 5 s: 168 de 6958; > 10 s: 67.
