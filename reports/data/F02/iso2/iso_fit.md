# Latências de referência e estimador de prefill (gerado por `polyaxon/iso_fit.py`)

## meta-llama/Llama-3.1-8B-Instruct (5 repetições, 0 requisições com falha)

- `TTFT_iso(L) = 19.1 ms + 27.64 µs·L`; erro relativo fora da amostra: mediana 10.6%, p90 32.7%
- `p̂(N) = 12.3 ms + 33.42 µs·N` (N = tokens de prompt no lote); erro relativo fora da amostra: mediana 12.4%, p90 37.3%
- `TPOT_iso` = 12.15 ms com 1 fluxo (CV entre repetições 7.8%), 14.72 ms com 8

| L (tokens) | n | TTFT mediano (ms) | ajuste (ms) |
| --- | --- | --- | --- |
| 64 | 50 | 24.4 | 20.9 |
| 128 | 50 | 25.4 | 22.7 |
| 256 | 50 | 26.5 | 26.2 |
| 512 | 50 | 28.3 | 33.3 |
| 1024 | 50 | 45.0 | 47.4 |
| 2048 | 50 | 73.2 | 75.8 |
| 4096 | 50 | 133.3 | 132.4 |

## meta-llama/Llama-3.2-3B-Instruct (5 repetições, 0 requisições com falha)

- `TTFT_iso(L) = 16.9 ms + 12.52 µs·L`; erro relativo fora da amostra: mediana 13.2%, p90 32.4%
- `p̂(N) = 11.8 ms + 17.08 µs·N` (N = tokens de prompt no lote); erro relativo fora da amostra: mediana 18.0%, p90 38.6%
- `TPOT_iso` = 9.91 ms com 1 fluxo (CV entre repetições 8.0%), 9.99 ms com 8

| L (tokens) | n | TTFT mediano (ms) | ajuste (ms) |
| --- | --- | --- | --- |
| 64 | 50 | 20.6 | 17.7 |
| 128 | 50 | 20.7 | 18.5 |
| 256 | 50 | 20.2 | 20.1 |
| 512 | 50 | 19.5 | 23.3 |
| 1024 | 50 | 26.6 | 29.7 |
| 2048 | 50 | 39.5 | 42.5 |
| 4096 | 50 | 70.1 | 68.2 |

