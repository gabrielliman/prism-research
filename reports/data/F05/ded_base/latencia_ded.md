# Base do SLO por modelo, carga própria em GPU dedicada (gerado por `polyaxon/iso_dedicated.py`)

| Carga | Nível | Modelo | Caminho | Requisições (ok / não atendidas / falhas) | TTFT p50 / **p95** (ms) | TPOT p50 / **p95** (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| ovl_bursty | rate0.2 | model_1 | Llama-3.1-8B-Instruct | 122 (122 / 0 / 0) | 40.7 / **728.0** | 10.1 / **26.2** |
| ovl_bursty | rate0.2 | model_2 | Llama-3.1-8B-Instruct | 66 (66 / 0 / 0) | 41.3 / **276.4** | 9.9 / **14.3** |
| ovl_bursty | rate0.2 | model_3 | Llama-3.1-8B-Instruct | 137 (137 / 0 / 0) | 39.4 / **229.5** | 9.9 / **15.5** |
| ovl_bursty | rate0.2 | model_4 | Llama-3.1-8B-Instruct | 125 (125 / 0 / 0) | 41.1 / **189.0** | 9.7 / **12.4** |
| ovl_bursty | rate0.2 | model_5 | Llama-3.1-8B-Instruct | 125 (125 / 0 / 0) | 39.8 / **156.7** | 9.5 / **11.5** |
| ovl_bursty | rate0.2 | model_6 | Llama-3.1-8B-Instruct | 93 (93 / 0 / 0) | 41.6 / **127.9** | 9.8 / **16.1** |
| ovl_bursty | rate0.2 | model_7 | Llama-3.1-8B-Instruct | 204 (204 / 0 / 0) | 46.0 / **335.1** | 10.8 / **23.9** |
| ovl_bursty | rate0.2 | model_8 | Llama-3.1-8B-Instruct | 115 (115 / 0 / 0) | 46.6 / **599.6** | 10.8 / **31.8** |
| ovl_bursty | rate0.2 | model_9 | Llama-3.1-8B-Instruct | 93 (93 / 0 / 0) | 43.7 / **130.4** | 9.9 / **14.9** |
| ovl_bursty | rate0.2 | model_10 | Llama-3.1-8B-Instruct | 139 (139 / 0 / 0) | 39.4 / **133.3** | 10.1 / **13.4** |
| ovl_diurnal | rate2 | model_1 | Llama-3.1-8B-Instruct | 790 (790 / 0 / 0) | 44.0 / **461.4** | 10.0 / **24.8** |
| ovl_diurnal | rate2 | model_2 | Llama-3.1-8B-Instruct | 422 (422 / 0 / 0) | 43.6 / **232.3** | 10.7 / **23.4** |
| ovl_diurnal | rate2 | model_3 | Llama-3.1-8B-Instruct | 255 (255 / 0 / 0) | 40.8 / **172.6** | 9.2 / **21.4** |
| ovl_diurnal | rate2 | model_4 | Llama-3.1-8B-Instruct | 205 (205 / 0 / 0) | 40.4 / **127.9** | 9.2 / **16.6** |
| ovl_diurnal | rate2 | model_5 | Llama-3.1-8B-Instruct | 181 (181 / 0 / 0) | 39.8 / **128.9** | 9.4 / **20.3** |
| ovl_diurnal | rate2 | model_6 | Llama-3.1-8B-Instruct | 124 (124 / 0 / 0) | 42.5 / **148.7** | 9.4 / **27.0** |
| ovl_diurnal | rate2 | model_7 | Llama-3.1-8B-Instruct | 105 (105 / 0 / 0) | 39.4 / **126.1** | 9.6 / **13.1** |
| ovl_diurnal | rate2 | model_8 | Llama-3.1-8B-Instruct | 97 (97 / 0 / 0) | 40.6 / **126.0** | 9.3 / **12.5** |
| ovl_diurnal | rate2 | model_9 | Llama-3.1-8B-Instruct | 86 (86 / 0 / 0) | 39.3 / **125.5** | 9.3 / **13.1** |
| ovl_diurnal | rate2 | model_10 | Llama-3.1-8B-Instruct | 86 (86 / 0 / 0) | 41.3 / **489.5** | 9.2 / **23.0** |
| ovl_sizes | rate0.2 | model_1 | Llama-3.2-3B-Instruct | 123 (123 / 0 / 0) | 25.4 / **68.2** | 8.1 / **9.8** |
| ovl_sizes | rate0.2 | model_2 | Llama-3.2-3B-Instruct | 113 (113 / 0 / 0) | 27.4 / **123.5** | 8.7 / **19.7** |
| ovl_sizes | rate0.2 | model_3 | Llama-3.1-8B-Instruct | 113 (113 / 0 / 0) | 39.9 / **121.7** | 9.0 / **12.1** |
| ovl_sizes | rate0.2 | model_4 | Llama-3.1-8B-Instruct | 127 (127 / 0 / 0) | 41.9 / **199.7** | 9.4 / **24.8** |
| ovl_sizes | rate0.2 | model_5 | Llama-3.1-8B-Instruct | 116 (116 / 0 / 0) | 41.9 / **126.0** | 9.4 / **11.8** |
| ovl_sizes | rate0.2 | model_6 | Qwen2.5-32B-Instruct | 107 (107 / 0 / 0) | 63.5 / **320.8** | 13.3 / **32.7** |
| ovl_sizes | rate0.2 | model_7 | Qwen2.5-32B-Instruct | 115 (115 / 0 / 0) | 67.4 / **288.3** | 13.1 / **16.2** |
| ovl_sizes | rate0.2 | model_8 | Qwen2.5-32B-Instruct | 113 (113 / 0 / 0) | 141.2 / **2595.5** | 24.8 / **46.7** |
| ovl_tr_azfn | ts1 | model_1 | Llama-3.1-8B-Instruct | 231 (231 / 0 / 0) | 45.9 / **356.5** | 10.4 / **25.0** |
| ovl_tr_azfn | ts1 | model_2 | Llama-3.1-8B-Instruct | 187 (187 / 0 / 0) | 40.1 / **136.6** | 9.9 / **15.5** |
| ovl_tr_azfn | ts1 | model_3 | Llama-3.1-8B-Instruct | 154 (154 / 0 / 0) | 44.0 / **148.5** | 9.9 / **23.6** |
| ovl_tr_azfn | ts1 | model_4 | Llama-3.1-8B-Instruct | 127 (127 / 0 / 0) | 45.2 / **1026.5** | 10.3 / **26.0** |
| ovl_tr_azfn | ts1 | model_5 | Llama-3.1-8B-Instruct | 112 (112 / 0 / 0) | 45.5 / **1409.5** | 10.2 / **25.8** |
| ovl_tr_azfn | ts1 | model_6 | Llama-3.1-8B-Instruct | 86 (86 / 0 / 0) | 285.7 / **1232.2** | 26.3 / **55.1** |
| ovl_tr_azfn | ts1 | model_7 | Llama-3.1-8B-Instruct | 70 (70 / 0 / 0) | 39.8 / **134.1** | 9.8 / **23.0** |
| ovl_tr_azfn | ts1 | model_8 | Llama-3.1-8B-Instruct | 60 (60 / 0 / 0) | 46.8 / **185.8** | 10.3 / **23.1** |
| ovl_tr_azfn | ts1 | model_9 | Llama-3.1-8B-Instruct | 60 (60 / 0 / 0) | 43.7 / **502.3** | 10.2 / **25.3** |
| ovl_tr_azfn | ts1 | model_10 | Llama-3.1-8B-Instruct | 48 (48 / 0 / 0) | 41.7 / **139.3** | 9.5 / **18.0** |
| ovl_tr_azfn | ts1 | model_11 | Llama-3.1-8B-Instruct | 36 (36 / 0 / 0) | 42.2 / **134.7** | 9.0 / **10.8** |
| ovl_tr_azfn | ts1 | model_12 | Llama-3.1-8B-Instruct | 29 (29 / 0 / 0) | 34.8 / **111.5** | 8.9 / **11.3** |
| ovl_tr_lmsys | ts1 | model_1 | Llama-3.1-8B-Instruct | 670 (670 / 0 / 0) | 20.8 / **31.5** | 9.0 / **10.4** |
| ovl_tr_lmsys | ts1 | model_2 | Llama-3.1-8B-Instruct | 111 (111 / 0 / 0) | 20.9 / **36.5** | 9.0 / **12.0** |
| ovl_tr_lmsys | ts1 | model_3 | Llama-3.1-8B-Instruct | 85 (85 / 0 / 0) | 20.7 / **46.6** | 8.3 / **14.8** |
| ovl_tr_lmsys | ts1 | model_4 | Llama-3.1-8B-Instruct | 49 (49 / 0 / 0) | 20.9 / **31.1** | 8.5 / **10.8** |
| ovl_tr_lmsys | ts1 | model_5 | Llama-3.1-8B-Instruct | 44 (44 / 0 / 0) | 22.4 / **34.9** | 8.4 / **12.0** |
| ovl_tr_lmsys | ts1 | model_6 | Llama-3.1-8B-Instruct | 42 (42 / 0 / 0) | 31.5 / **61.7** | 10.6 / **13.4** |
| ovl_tr_lmsys | ts1 | model_7 | Llama-3.1-8B-Instruct | 41 (41 / 0 / 0) | 28.5 / **53.1** | 11.0 / **14.2** |
| ovl_tr_lmsys | ts1 | model_8 | Llama-3.1-8B-Instruct | 36 (36 / 0 / 0) | 20.6 / **38.4** | 8.7 / **12.6** |
| ovl_tr_lmsys | ts1 | model_9 | Llama-3.1-8B-Instruct | 36 (36 / 0 / 0) | 22.7 / **73.6** | 8.4 / **11.5** |
| ovl_tr_lmsys | ts1 | model_10 | Llama-3.1-8B-Instruct | 32 (32 / 0 / 0) | 21.1 / **32.0** | 9.2 / **13.4** |
| ovl_tr_lmsys | ts1 | model_11 | Llama-3.1-8B-Instruct | 32 (32 / 0 / 0) | 19.9 / **34.4** | 8.3 / **11.5** |
| ovl_tr_lmsys | ts1 | model_12 | Llama-3.1-8B-Instruct | 23 (23 / 0 / 0) | 20.4 / **37.2** | 8.6 / **10.0** |
| ovl_zipf | rate2 | model_1 | Llama-3.1-8B-Instruct | 123 (123 / 0 / 0) | 44.2 / **426.5** | 9.7 / **15.5** |
| ovl_zipf | rate2 | model_2 | Llama-3.1-8B-Instruct | 383 (383 / 0 / 0) | 40.6 / **145.1** | 9.7 / **12.8** |
| ovl_zipf | rate2 | model_3 | Llama-3.1-8B-Instruct | 190 (190 / 0 / 0) | 40.9 / **128.7** | 9.4 / **19.0** |
| ovl_zipf | rate2 | model_4 | Llama-3.1-8B-Instruct | 142 (142 / 0 / 0) | 43.8 / **157.1** | 9.7 / **25.3** |
| ovl_zipf | rate2 | model_5 | Llama-3.1-8B-Instruct | 90 (90 / 0 / 0) | 43.0 / **375.6** | 9.9 / **30.2** |
| ovl_zipf | rate2 | model_6 | Llama-3.1-8B-Instruct | 73 (73 / 0 / 0) | 41.7 / **129.5** | 9.4 / **24.4** |
| ovl_zipf | rate2 | model_7 | Llama-3.1-8B-Instruct | 51 (51 / 0 / 0) | 39.1 / **125.1** | 9.3 / **24.6** |
| ovl_zipf | rate2 | model_8 | Llama-3.1-8B-Instruct | 51 (51 / 0 / 0) | 44.4 / **156.0** | 9.9 / **23.8** |
| ovl_zipf | rate2 | model_9 | Llama-3.1-8B-Instruct | 49 (49 / 0 / 0) | 40.7 / **127.5** | 10.0 / **24.1** |
| ovl_zipf | rate2 | model_10 | Llama-3.1-8B-Instruct | 41 (41 / 0 / 0) | 39.5 / **272.9** | 9.9 / **37.2** |

## Base do SLO (D21): requisições dos modelos idênticos da carga juntas

| Carga | Caminho | Modelos | Requisições atendidas | TTFT p50 / **p95** (ms) | TPOT p50 / **p95** (ms) |
| --- | --- | --- | --- | --- | --- |
| ovl_bursty | Llama-3.1-8B-Instruct | 10 | 1219 | 42.7 / **241.0** | 10.0 / **20.5** |
| ovl_diurnal | Llama-3.1-8B-Instruct | 10 | 2351 | 42.2 / **200.4** | 9.7 / **22.5** |
| ovl_sizes | Qwen2.5-32B-Instruct | 3 | 335 | 72.7 / **1228.3** | 14.2 / **39.6** |
| ovl_sizes | Llama-3.1-8B-Instruct | 3 | 356 | 41.5 / **136.3** | 9.3 / **17.0** |
| ovl_sizes | Llama-3.2-3B-Instruct | 2 | 236 | 26.3 / **80.4** | 8.3 / **16.5** |
| ovl_tr_azfn | Llama-3.1-8B-Instruct | 12 | 1200 | 44.4 / **710.4** | 10.2 / **29.6** |
| ovl_tr_lmsys | Llama-3.1-8B-Instruct | 12 | 1201 | 21.3 / **39.1** | 9.0 / **11.9** |
| ovl_zipf | Llama-3.1-8B-Instruct | 10 | 1193 | 42.0 / **155.1** | 9.7 / **22.7** |

## Dispersão entre modelos idênticos (por que a base junta as requisições, D21)

- ovl_bursty, Llama-3.1-8B-Instruct (10 modelos), p95: TTFT de 127.9 a 728.0 ms (CV 68.6%); TPOT de 11.5 a 31.8 ms (CV 36.1%)
- ovl_bursty, Llama-3.1-8B-Instruct (10 modelos), p50: TTFT de 39.4 a 46.6 ms (CV 5.9%); TPOT de 9.5 a 10.8 ms (CV 4.0%)
- ovl_diurnal, Llama-3.1-8B-Instruct (10 modelos), p95: TTFT de 125.5 a 489.5 ms (CV 63.0%); TPOT de 12.5 a 27.0 ms (CV 25.9%)
- ovl_diurnal, Llama-3.1-8B-Instruct (10 modelos), p50: TTFT de 39.3 a 44.0 ms (CV 3.9%); TPOT de 9.2 a 10.7 ms (CV 4.6%)
- ovl_sizes, Qwen2.5-32B-Instruct (3 modelos), p95: TTFT de 288.3 a 2595.5 ms (CV 101.1%); TPOT de 16.2 a 46.7 ms (CV 39.0%)
- ovl_sizes, Qwen2.5-32B-Instruct (3 modelos), p50: TTFT de 63.5 a 141.2 ms (CV 39.4%); TPOT de 13.1 a 24.8 ms (CV 32.0%)
- ovl_sizes, Llama-3.1-8B-Instruct (3 modelos), p95: TTFT de 121.7 a 199.7 ms (CV 24.0%); TPOT de 11.8 a 24.8 ms (CV 37.3%)
- ovl_sizes, Llama-3.1-8B-Instruct (3 modelos), p50: TTFT de 39.9 a 41.9 ms (CV 2.3%); TPOT de 9.0 a 9.4 ms (CV 2.0%)
- ovl_sizes, Llama-3.2-3B-Instruct (2 modelos), p95: TTFT de 68.2 a 123.5 ms (CV 28.9%); TPOT de 9.8 a 19.7 ms (CV 33.6%)
- ovl_sizes, Llama-3.2-3B-Instruct (2 modelos), p50: TTFT de 25.4 a 27.4 ms (CV 3.7%); TPOT de 8.1 a 8.7 ms (CV 3.6%)
- ovl_tr_azfn, Llama-3.1-8B-Instruct (12 modelos), p95: TTFT de 111.5 a 1409.5 ms (CV 100.1%); TPOT de 10.8 a 55.1 ms (CV 46.2%)
- ovl_tr_azfn, Llama-3.1-8B-Instruct (12 modelos), p50: TTFT de 34.8 a 285.7 ms (CV 106.8%); TPOT de 8.9 a 26.3 ms (CV 40.7%)
- ovl_tr_lmsys, Llama-3.1-8B-Instruct (12 modelos), p95: TTFT de 31.1 a 73.6 ms (CV 30.5%); TPOT de 10.0 a 14.8 ms (CV 11.8%)
- ovl_tr_lmsys, Llama-3.1-8B-Instruct (12 modelos), p50: TTFT de 19.9 a 31.5 ms (CV 15.5%); TPOT de 8.3 a 11.0 ms (CV 9.5%)
- ovl_zipf, Llama-3.1-8B-Instruct (10 modelos), p95: TTFT de 125.1 a 426.5 ms (CV 52.5%); TPOT de 12.8 a 37.2 ms (CV 27.9%)
- ovl_zipf, Llama-3.1-8B-Instruct (10 modelos), p50: TTFT de 39.1 a 44.4 ms (CV 4.4%); TPOT de 9.3 a 10.0 ms (CV 2.3%)
