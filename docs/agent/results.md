# Where past results are

Everything is under `reports/` (in Portuguese) except the raw Polyaxon downloads, which are outside git.
Before re-running something, check whether a report already covers it.

| What | Where |
| --- | --- |
| Dated reports (one per study) | `reports/YYYY-MM-DD <título>.md` |
| Phase reports of the mission (F0, F1, …), each ending with its gate decision | `reports/fases/FXX_*.md` |
| Compact data behind each report (`extract_ovl.py` / `collect_reps.py` output, `metricas.csv`, `manifest.csv`) | `reports/data/<report date-slug>/` and `reports/data/FXX/` |
| Figures | `reports/figs/<report date-slug>/` and `reports/figs/FXX/` |
| Errors and how each was handled (Prism, kvcached, SGLang, still open) | `reports/erros.md` |
| Design and gate decisions D1, D2, … (who decided, when, why) | `reports/registro/decisoes.md` |
| Every validated run (run_id, commit, scenario, policy, params, validator status, artifact path) | `reports/registro/execucoes.csv` (`register_runs.py`) |
| Degraded node windows | `reports/registro/janelas_degradadas.csv` |
| Workload catalog C1–C5, T1 (definition, reference level, hash, stats) | `reports/registro/cargas.md` |
| SLO base latencies (S2/S2M: dedicated GPU, pooled P95/P50) and how they were measured | `reports/registro/latencia_ded.json`, `latencia_ref.json`, `latencia_ref.md` |
| Raw downloads (full server logs, `requests.json`, `decisions.jsonl`) | `/mnt/scratch/scheduler/prism-raw/<campaign>/<job>/outputs/…` (see its `README.md`) |

## Dated reports

Each report lists the scripts, commands and run IDs needed to reproduce it.

| Report | Data / figures |
| --- | --- |
| `2026-10-21 Reprodução dos exemplos do README.md` | (none) |
| `2026-10-21 Prism em sobrecarga.md` | (none) |
| `2026-10-21 Sobrecarga real no Prism (SGLang e vLLM).md` (+ notebook `2026-10-22 Sobrecarga real no Prism - gráficos.ipynb`, the source of the timeline chart) | `data/2026-10-21-sobrecarga-real/` |
| `2026-10-22 Correções de robustez de memória no Prism (SGLang).md`: **the Prism change log** (R-numbers, what is on by default, files changed) | `data/2026-10-22-robustez/`, `data/2026-10-22-custo/`, `figs/2026-10-22-{robustez,custo}/` |
| `2026-10-22 Janela de ociosidade e estratégias de troca no Prism (SGLang).md` (superseded by the 10-28 version) | `data/2026-10-22-{ociosidade,repeticoes}/`, `figs/2026-10-22-{ociosidade,repeticoes}/` |
| `2026-10-28 Janela de ociosidade e estratégias de troca no Prism, com as correções (SGLang).md` (+ `APRESENTAÇÃO` version) | `data/2026-10-28-ociosidade/`, `figs/2026-10-28-ociosidade/` |
| `2026-10-28 Limites de carga do Prism base e correções por erro (SGLang).md` | `data/2026-10-28-limites/`, `figs/2026-10-28-limites/` |
| `2026-10-29 Base para proposta - sobrecarga real, fragilidades e política de estadia no Prism.md` | reuses the above |
| `2026-10-30 Variação de desempenho do nó GPU do cluster.md` | `data/2026-10-30-cluster/`, `figs/2026-10-30-cluster/` |

## Phase reports (`reports/fases/`)

| File | Phase |
| --- | --- |
| `F00_inventario.md`, `F00_reconhecimento.md` | F0: inventory of problems and reproduction of the baseline. Data in `data/F00/` |
| `F01_robustez.md` | F1: remaining robustness (freeze T1, losses, P11, P12, code A/B). Data in `data/F01/`, figs in `figs/F01/` |
| `F02_instrumentacao.md` | F2: decision log, validator, estimators, SLO families and curves. Data in `data/F02/` (`validador/`, `cat/`, `curvas/`, `ded/`, `iso*/`, `sobrecusto/`, `estimadores/`, `codigo/`) |

For the current state of the mission, read the gate line at the end of the latest `reports/fases/` report and the
open items in `TODO.md`.

## Writing a new report

Offer it first and write it only after approval. Follow the rules in `CLAUDE.md` (dated filename and H1, in
Portuguese, reproduction commands and run IDs, table standard via `report_tables.py`). Put its data in
`reports/data/<YYYY-MM-DD-slug>/` and figures in `reports/figs/<YYYY-MM-DD-slug>/`. Include the 3-panel timeline
(`plot_suite.py`, or `linha_do_tempo` in the 10-22 notebook) for any scenario with model swaps. Use only levels the
validator marked VALIDA. Phase reports follow the template in `PLANO_AGENTE.md` §0.7.
