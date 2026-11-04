# Sobrecusto do log de decisões (gerado por `polyaxon/overhead.py`)

| job | linha | log | tok/s de saída | req/s atendidas | ciclos | tempo do ciclo, média / p99 (ms) | log (KB) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| f2-overhead | log_on_1 | sim | 5671 | 22.15 | 54 | 38.37 / 339.31 | 31 |
| f2-overhead | log_off_1 | não | 5735 | 22.40 | 53 | 27.51 / 325.18 | 0 |
| f2-overhead | log_on_2 | sim | 5801 | 22.66 | 52 | 14.79 / 98.47 | 30 |
| f2-overhead | log_off_2 | não | 5772 | 22.55 | 53 | 32.39 / 421.20 | 0 |
| f2-overhead | log_on_3 | sim | 6311 | 24.65 | 48 | 6.87 / 19.56 | 28 |
| f2-overhead | log_off_3 | não | 6679 | 26.09 | 46 | 5.15 / 10.50 | 0 |
| f2-smoke | A0.1_log_on | sim | 809 | 2.54 | 123 | 28.95 / 292.96 | 277 |
| f2-smoke | A0.1_log_off | não | 812 | 2.55 | 122 | 21.21 / 229.25 | 0 |

**f2-overhead, tempo do ciclo do controlador:** com log 20.59 ms, sem log 22.44 ms (diferença -1.85 ms por ciclo de 5 s = -0.0371% do tempo).
**f2-overhead, vazão:** efeito do log = +63 tok/s (+1.0%), IC 95% [-9.7%, +11.8%]; tendência ao longo do job +198 tok/s por nível.

**f2-smoke, tempo do ciclo do controlador:** com log 28.95 ms, sem log 21.21 ms (diferença +7.74 ms por ciclo de 5 s = +0.1548% do tempo).

per cycle: 0.083 ms, 2866 bytes; share of a 5 s cycle: 0.00166%
