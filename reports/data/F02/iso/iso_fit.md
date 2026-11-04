# Latências de referência e estimador de prefill (gerado por `polyaxon/iso_fit.py`)

## meta-llama/Llama-3.1-8B-Instruct (5 repetições, 0 requisições com falha)

- `TTFT_iso(L) = 14.7 ms + 27.02 µs·L`; erro relativo fora da amostra: mediana 8.5%, p90 24.9%
- `p̂(N) = 11.3 ms + 31.54 µs·N` (N = tokens de prompt no lote); erro relativo fora da amostra: mediana 13.0%, p90 30.1%
- `TPOT_iso` = 10.91 ms com 1 fluxo (CV entre repetições 48.2%), 12.62 ms com 8

| L (tokens) | n | TTFT mediano (ms) | ajuste (ms) |
| --- | --- | --- | --- |
| 64 | 50 | 19.5 | 16.5 |
| 128 | 50 | 19.2 | 18.2 |
| 256 | 50 | 19.7 | 21.6 |
| 512 | 50 | 28.2 | 28.6 |
| 1024 | 50 | 38.4 | 42.4 |
| 2048 | 50 | 66.6 | 70.1 |
| 4096 | 50 | 129.8 | 125.4 |

## meta-llama/Llama-3.2-3B-Instruct (5 repetições, 0 requisições com falha)

- `TTFT_iso(L) = 17.7 ms + 14.65 µs·L`; erro relativo fora da amostra: mediana 21.5%, p90 56.4%
- `p̂(N) = 14.5 ms + 19.88 µs·N` (N = tokens de prompt no lote); erro relativo fora da amostra: mediana 23.4%, p90 58.9%
- `TPOT_iso` = 12.36 ms com 1 fluxo (CV entre repetições 13.9%), 12.89 ms com 8

| L (tokens) | n | TTFT mediano (ms) | ajuste (ms) |
| --- | --- | --- | --- |
| 64 | 50 | 20.0 | 18.7 |
| 128 | 50 | 21.1 | 19.6 |
| 256 | 50 | 21.5 | 21.5 |
| 512 | 50 | 24.2 | 25.2 |
| 1024 | 50 | 29.7 | 32.7 |
| 2048 | 50 | 43.6 | 47.8 |
| 4096 | 50 | 86.5 | 77.8 |

