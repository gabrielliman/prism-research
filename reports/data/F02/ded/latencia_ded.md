# Base do SLO por modelo, carga própria em GPU dedicada (gerado por `polyaxon/iso_dedicated.py`)

| Carga | Nível | Modelo | Caminho | Requisições (ok / não atendidas / falhas) | TTFT p50 / **p95** (ms) | TPOT p50 / **p95** (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| ovl_compute | rate25 | model_1 | Llama-3.1-8B-Instruct | 3095 (3095 / 0 / 0) | 14577.3 / **15486.1** | 44.4 / **78.3** |
| ovl_compute | rate25 | model_2 | Llama-3.1-8B-Instruct | 2945 (2945 / 0 / 0) | 63.1 / **759.8** | 45.1 / **48.4** |
| ovl_kv | rate0.5 | model_1 | Llama-3.1-8B-Instruct | 92 (92 / 0 / 0) | 116.7 / **172.7** | 13.6 / **17.1** |
| ovl_kv | rate0.5 | model_2 | Llama-3.1-8B-Instruct | 87 (87 / 0 / 0) | 115.0 / **299.4** | 10.6 / **27.4** |
| ovl_kv | rate0.5 | model_3 | Llama-3.1-8B-Instruct | 80 (80 / 0 / 0) | 112.1 / **162.4** | 10.6 / **11.6** |
| ovl_kv | rate0.5 | model_4 | Llama-3.1-8B-Instruct | 78 (78 / 0 / 0) | 110.6 / **175.0** | 10.0 / **10.8** |
| ovl_mem | rate0.2 | model_1 | Llama-3.1-8B-Instruct | 65 (65 / 0 / 0) | 32.9 / **51.8** | 10.1 / **11.5** |
| ovl_mem | rate0.2 | model_2 | Llama-3.1-8B-Instruct | 52 (52 / 0 / 0) | 37.9 / **213.6** | 9.8 / **29.2** |
| ovl_mem | rate0.2 | model_3 | Llama-3.1-8B-Instruct | 58 (58 / 0 / 0) | 35.8 / **68.3** | 10.5 / **23.3** |
| ovl_mem | rate0.2 | model_4 | Llama-3.1-8B-Instruct | 47 (47 / 0 / 0) | 33.3 / **49.6** | 9.5 / **17.9** |
| ovl_mem | rate0.2 | model_5 | Llama-3.1-8B-Instruct | 59 (59 / 0 / 0) | 33.2 / **46.6** | 9.6 / **11.0** |
| ovl_mem | rate0.2 | model_6 | Llama-3.1-8B-Instruct | 60 (60 / 0 / 0) | 35.6 / **59.2** | 10.3 / **16.3** |
| ovl_mem | rate0.2 | model_7 | Llama-3.1-8B-Instruct | 70 (70 / 0 / 0) | 38.7 / **122.8** | 12.5 / **48.9** |
| ovl_mem | rate0.2 | model_8 | Llama-3.1-8B-Instruct | 55 (55 / 0 / 0) | 35.0 / **44.6** | 10.7 / **13.8** |
| ovl_mem | rate0.2 | model_9 | Llama-3.1-8B-Instruct | 65 (65 / 0 / 0) | 38.6 / **76.2** | 10.4 / **25.7** |
| ovl_mem | rate0.2 | model_10 | Llama-3.1-8B-Instruct | 68 (68 / 0 / 0) | 34.3 / **46.1** | 10.9 / **12.6** |
| ovl_mix | rate0.2 | model_1 | Llama-3.1-8B-Instruct | 65 (65 / 0 / 0) | 37.2 / **145.9** | 11.4 / **51.1** |
| ovl_mix | rate0.2 | model_2 | Llama-3.1-8B-Instruct | 52 (52 / 0 / 0) | 31.7 / **41.2** | 9.0 / **10.3** |
| ovl_mix | rate0.2 | model_3 | Llama-3.1-8B-Instruct | 58 (58 / 0 / 0) | 34.0 / **49.2** | 9.6 / **11.8** |
| ovl_mix | rate0.2 | model_4 | Llama-3.1-8B-Instruct | 47 (47 / 0 / 0) | 38.5 / **171.9** | 9.8 / **22.6** |
| ovl_mix | rate0.2 | model_5 | Llama-3.1-8B-Instruct | 59 (59 / 0 / 0) | 32.8 / **48.5** | 9.3 / **11.7** |
| ovl_mix | rate0.2 | model_6 | Llama-3.1-8B-Instruct | 60 (60 / 0 / 0) | 41.2 / **104.0** | 13.9 / **27.2** |
| ovl_mix | rate0.2 | model_7 | Llama-3.1-8B-Instruct | 70 (70 / 0 / 0) | 34.8 / **69.6** | 9.9 / **21.4** |
| ovl_mix | rate0.2 | model_8 | Llama-3.1-8B-Instruct | 55 (55 / 0 / 0) | 31.5 / **74.0** | 10.2 / **19.1** |
| ovl_mix | rate0.2 | model_9 | Llama-3.2-3B-Instruct | 43 (43 / 0 / 0) | 27.8 / **200.5** | 9.2 / **22.4** |
| ovl_mix | rate0.2 | model_10 | Llama-3.2-3B-Instruct | 40 (40 / 0 / 0) | 23.2 / **47.2** | 8.6 / **19.4** |
| ovl_phases | rate0.5 | model_1 | Llama-3.1-8B-Instruct | 151 (151 / 0 / 0) | 36.7 / **131.8** | 11.1 / **26.7** |
| ovl_phases | rate0.5 | model_2 | Llama-3.1-8B-Instruct | 145 (145 / 0 / 0) | 36.2 / **214.8** | 10.5 / **23.1** |
| ovl_phases | rate0.5 | model_3 | Llama-3.1-8B-Instruct | 161 (161 / 0 / 0) | 35.1 / **68.3** | 9.8 / **23.4** |
| ovl_phases | rate0.5 | model_4 | Llama-3.1-8B-Instruct | 142 (142 / 0 / 0) | 37.3 / **3098.9** | 10.2 / **34.4** |
| ovl_phases | rate0.5 | model_5 | Llama-3.1-8B-Instruct | 163 (163 / 0 / 0) | 36.4 / **59.0** | 11.2 / **15.7** |
| ovl_phases | rate0.5 | model_6 | Llama-3.1-8B-Instruct | 143 (143 / 0 / 0) | 38.5 / **94.9** | 11.7 / **15.8** |
| ovl_phases | rate0.5 | model_7 | Llama-3.1-8B-Instruct | 169 (169 / 0 / 0) | 36.8 / **78.4** | 11.0 / **24.9** |
| ovl_phases | rate0.5 | model_8 | Llama-3.1-8B-Instruct | 142 (142 / 0 / 0) | 38.1 / **267.2** | 9.6 / **35.8** |
| ovl_phases | rate0.5 | model_9 | Llama-3.1-8B-Instruct | 157 (157 / 0 / 0) | 36.2 / **95.4** | 9.9 / **24.6** |
| ovl_phases | rate0.5 | model_10 | Llama-3.1-8B-Instruct | 191 (191 / 0 / 0) | 39.0 / **71.8** | 12.0 / **27.3** |
| ovl_trace_big | ts1 | model_1 | Llama-3.1-8B-Instruct | 296 (296 / 0 / 0) | 26.8 / **72.0** | 10.8 / **24.4** |
| ovl_trace_big | ts1 | model_2 | Llama-3.1-8B-Instruct | 262 (262 / 0 / 0) | 24.6 / **61.1** | 10.6 / **23.3** |
| ovl_trace_big | ts1 | model_3 | Llama-3.1-8B-Instruct | 199 (199 / 0 / 0) | 25.6 / **93.3** | 9.9 / **27.9** |
| ovl_trace_big | ts1 | model_4 | Llama-3.1-8B-Instruct | 120 (120 / 0 / 0) | 27.7 / **52.6** | 11.1 / **20.6** |
| ovl_trace_big | ts1 | model_5 | Llama-3.1-8B-Instruct | 67 (67 / 0 / 0) | 26.2 / **54.1** | 10.7 / **19.7** |
| ovl_trace_big | ts1 | model_6 | Llama-3.1-8B-Instruct | 66 (66 / 0 / 0) | 24.3 / **51.1** | 10.6 / **20.2** |
| ovl_trace_big | ts1 | model_7 | Llama-3.1-8B-Instruct | 56 (56 / 0 / 0) | 22.5 / **38.3** | 8.8 / **13.7** |
| ovl_trace_big | ts1 | model_8 | Llama-3.1-8B-Instruct | 46 (46 / 0 / 0) | 22.5 / **47.5** | 9.2 / **16.8** |
| ovl_trace_big | ts1 | model_9 | Llama-3.1-8B-Instruct | 44 (44 / 0 / 0) | 23.9 / **97.4** | 9.5 / **23.5** |
| ovl_trace_big | ts1 | model_10 | Llama-3.1-8B-Instruct | 43 (43 / 0 / 0) | 27.7 / **180.7** | 9.8 / **39.5** |
| ovl_trace_big | ts1 | model_11 | Llama-3.1-8B-Instruct | 40 (40 / 0 / 0) | 25.2 / **54.5** | 9.3 / **24.2** |
| ovl_trace_big | ts1 | model_12 | Llama-3.1-8B-Instruct | 36 (36 / 0 / 0) | 21.0 / **40.4** | 9.1 / **10.7** |

## Base do SLO (D21): requisições dos modelos idênticos da carga juntas

| Carga | Caminho | Modelos | Requisições atendidas | TTFT p50 / **p95** (ms) | TPOT p50 / **p95** (ms) |
| --- | --- | --- | --- | --- | --- |
| ovl_compute | Llama-3.1-8B-Instruct | 2 | 6040 | 873.6 / **15260.1** | 44.7 / **69.9** |
| ovl_kv | Llama-3.1-8B-Instruct | 4 | 337 | 114.1 / **178.1** | 10.7 / **21.4** |
| ovl_mem | Llama-3.1-8B-Instruct | 10 | 599 | 35.3 / **69.8** | 10.4 / **25.7** |
| ovl_mix | Llama-3.1-8B-Instruct | 8 | 466 | 34.6 / **81.8** | 9.9 / **22.3** |
| ovl_mix | Llama-3.2-3B-Instruct | 2 | 83 | 24.7 / **100.0** | 8.7 / **22.0** |
| ovl_phases | Llama-3.1-8B-Instruct | 10 | 1564 | 37.0 / **124.4** | 10.7 / **25.9** |
| ovl_trace_big | Llama-3.1-8B-Instruct | 12 | 1275 | 25.1 / **64.3** | 10.4 / **24.1** |

## Dispersão entre modelos idênticos (por que a base junta as requisições, D21)

- ovl_compute, Llama-3.1-8B-Instruct (2 modelos), p95: TTFT de 759.8 a 15486.1 ms (CV 90.6%); TPOT de 48.4 a 78.3 ms (CV 23.6%)
- ovl_compute, Llama-3.1-8B-Instruct (2 modelos), p50: TTFT de 63.1 a 14577.3 ms (CV 99.1%); TPOT de 44.4 a 45.1 ms (CV 0.8%)
- ovl_kv, Llama-3.1-8B-Instruct (4 modelos), p95: TTFT de 162.4 a 299.4 ms (CV 27.8%); TPOT de 10.8 a 27.4 ms (CV 39.6%)
- ovl_kv, Llama-3.1-8B-Instruct (4 modelos), p50: TTFT de 110.6 a 116.7 ms (CV 2.1%); TPOT de 10.0 a 13.6 ms (CV 12.6%)
- ovl_mem, Llama-3.1-8B-Instruct (10 modelos), p95: TTFT de 44.6 a 213.6 ms (CV 64.8%); TPOT de 11.0 a 48.9 ms (CV 52.5%)
- ovl_mem, Llama-3.1-8B-Instruct (10 modelos), p50: TTFT de 32.9 a 38.7 ms (CV 5.9%); TPOT de 9.5 a 12.5 ms (CV 7.8%)
- ovl_mix, Llama-3.1-8B-Instruct (8 modelos), p95: TTFT de 41.2 a 171.9 ms (CV 51.5%); TPOT de 10.3 a 51.1 ms (CV 56.6%)
- ovl_mix, Llama-3.1-8B-Instruct (8 modelos), p50: TTFT de 31.5 a 41.2 ms (CV 9.2%); TPOT de 9.0 a 13.9 ms (CV 14.2%)
- ovl_mix, Llama-3.2-3B-Instruct (2 modelos), p95: TTFT de 47.2 a 200.5 ms (CV 61.9%); TPOT de 19.4 a 22.4 ms (CV 7.1%)
- ovl_mix, Llama-3.2-3B-Instruct (2 modelos), p50: TTFT de 23.2 a 27.8 ms (CV 9.1%); TPOT de 8.6 a 9.2 ms (CV 3.3%)
- ovl_phases, Llama-3.1-8B-Instruct (10 modelos), p95: TTFT de 59.0 a 3098.9 ms (CV 214.3%); TPOT de 15.7 a 35.8 ms (CV 24.8%)
- ovl_phases, Llama-3.1-8B-Instruct (10 modelos), p50: TTFT de 35.1 a 39.0 ms (CV 3.1%); TPOT de 9.6 a 12.0 ms (CV 7.3%)
- ovl_trace_big, Llama-3.1-8B-Instruct (12 modelos), p95: TTFT de 38.3 a 180.7 ms (CV 53.9%); TPOT de 10.7 a 39.5 ms (CV 31.8%)
- ovl_trace_big, Llama-3.1-8B-Instruct (12 modelos), p50: TTFT de 21.0 a 27.7 ms (CV 8.2%); TPOT de 8.8 a 11.1 ms (CV 7.5%)
