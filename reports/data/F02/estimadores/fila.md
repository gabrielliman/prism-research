# q̂_r: TTFT previsto na chegada × real (gerado por `polyaxon/estimators_eval.py queue`)

Requisições atendidas que chegaram com o modelo ativo e com requisições na frente (do mesmo modelo, chegadas antes e ainda sem 1º token). Erro absoluto do TTFT previsto (q̂ + p̂), em segundos, p50 / p90.

| Carga | n | sem fila na frente | TTFT real p50 / p90 | soma dos prefills | taxa observada (30 s) | híbrido (≥ 10 na janela) |
| --- | --- | --- | --- | --- | --- | --- |
| C1_ovl_mem | 12 | 97% | 0.27 / 0.63 | 0.19 / 0.54 | 11.94 / 19.75 | 0.19 / 0.54 |
| C2_ovl_phases | 242 | 81% | 3.70 / 33.97 | 3.58 / 33.77 | 18.33 / 234.23 | 5.85 / 35.06 |
| C3_ovl_mix | 91 | 78% | 18.87 / 39.96 | 18.79 / 39.79 | 19.84 / 100.19 | 18.79 / 39.79 |
| T1_ovl_trace_big | 277 | 68% | 12.53 / 86.71 | 12.47 / 85.92 | 16.80 / 59.71 | 7.76 / 50.59 |
| C5_ovl_compute | 5987 | 1% | 46.37 / 85.00 | 34.95 / 63.58 | 1.66 / 3.93 | 1.64 / 3.90 |
