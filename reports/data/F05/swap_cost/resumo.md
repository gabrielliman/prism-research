# F5.0a — custo real da rotação (decisão → modelo que entra pronto)

Gerado por `polyaxon/swap_cost.py`. Tempos em s, p50 / p90. `saída` = decisão → última vítima fora; `ciclo` = vítima fora → controlador decide ativar; `fila` = decisão de ativar → pedido no GPU scheduler; `carga` = pedido → pronto; `C_rot` = decisão → pronto (só rotações `ok`). `lapsed`: a ativação não veio em 120 s. Níveis VALIDA usados: 289; inválidos descartados: 28.

| modo de saída | pesos (GB) | rotações | ok / lapsed / vítima presa | saída | ciclo | fila | carga | C_rot | Ĉ_at | C_rot / Ĉ_at (p50) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| drain | 5,9 | 3 | 3 / 0 / 0 | 0,7 / 3,0 | 4,3 / 4,3 | 0,0 / 0,0 | 0,8 / 1,0 | 5,8 / 6,0 | 0,8 / 0,8 | 7,0 |
| drain | 15,0 | 2031 | 2016 / 15 / 0 | 12,0 / 28,0 | 1,9 / 5,3 | 0,0 / 0,0 | 1,7 / 5,2 | 9,5 / 28,6 | 1,4 / 2,5 | 6,1 |
| finish | 5,9 | 35 | 35 / 0 / 0 | 21,1 / 43,5 | -5,5 / 9,0 | 0,0 / 0,0 | 3,5 / 6,7 | 15,8 / 45,1 | 0,8 / 2,0 | 15,9 |
| finish | 15,0 | 4494 | 4196 / 298 / 0 | 20,1 / 47,0 | 1,0 / 28,0 | 0,0 / 0,0 | 3,3 / 8,8 | 15,7 / 64,8 | 1,4 / 1,4 | 10,7 |
| finish | 27,5 | 70 | 69 / 1 / 0 | 21,1 / 42,1 | 2,5 / 32,8 | 0,0 / 0,0 | 6,1 / 15,7 | 30,4 / 68,4 | 2,2 / 3,3 | 13,3 |
| finish | 61,0 | 32 | 9 / 23 / 0 | 30,5 / 58,9 | 36,1 / 70,8 | 0,0 / 0,0 | 7,1 / 7,7 | 73,7 / 110,8 | 4,3 / 5,4 | 15,8 |
| preempt | 5,9 | 3 | 3 / 0 / 0 | 0,8 / 1,1 | 4,2 / 4,4 | 0,0 / 0,0 | 1,9 / 2,0 | 6,9 / 7,0 | 0,8 / 0,8 | 8,3 |
| preempt | 15,0 | 725 | 709 / 16 / 0 | 0,6 / 1,1 | 4,4 / 4,6 | 0,0 / 0,0 | 1,4 / 2,8 | 6,5 / 7,9 | 1,4 / 1,4 | 4,6 |
| preempt | 27,5 | 1 | 0 / 1 / 0 | 2,5 / 2,5 | – / – | – / – | – / – | – / – | – / – | – |

**Base do S6** (`c_rot.json`, chave `s6`): Ĉ_rot(m) = saída com preempção + espera pelo ciclo (medianas sobre 712 rotações com preempção: 5,0 s) + Ĉ_at(m) sem ativações à frente (F2.3).

| pesos (GB) | Ĉ_at (s) | Ĉ_rot (s) | C_rot medido com preempção, p50 (s) | n |
| --- | --- | --- | --- | --- |
| 5,9 | 0,8 | 5,9 | 6,9 | 3 |
| 15,0 | 1,4 | 6,4 | 6,5 | 709 |
| 27,5 | 2,2 | 7,2 | – | 0 |
| 61,0 | 4,3 | 9,3 | – | 0 |
