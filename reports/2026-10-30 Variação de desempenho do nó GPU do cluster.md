# Variação de desempenho do nó GPU do cluster Polyaxon (2026-10-30)

Para: equipe que gerencia o cluster (Polyaxon `kunumi/hpc4ai`, fila `axia/default`).
De: Gabriel (projeto Prism, servidor de múltiplos LLMs sobre SGLang + kvcached).
Período analisado: 2026-10-21 a 2026-10-30, com testes controlados em 2026-10-30. Horários em UTC.

## Resumo

1. **O mesmo job, com o mesmo código e as mesmas sementes, deu resultados diferentes conforme o momento.** A métrica principal, a fração de requisições dentro do SLO, caiu de 73% para 56–64% em parte das execuções. A tabela "Medições" abaixo dá os números de cada caso.
2. **A maior causa é a concorrência no nó, não o dia.**
   - Com 4 ou mais jobs nossos rodando ao mesmo tempo no nó, aparecem erros do driver CUDA nas chamadas de memória virtual (`cuMemCreate` / `cuMemSetAccess ... failed in CUDA driver (2): out of memory`).
   - Os erros vêm mesmo com memória livre na GPU, e as falhas em GPUs diferentes acontecem no mesmo segundo.
   - Com 1 a 3 jobs, isso é raro (2–3% dos níveis); com 5 ou mais, ocorre em 71–79% dos níveis. A tabela de concorrência está na seção 2.
3. **Reproduzimos o efeito de propósito em 2026-10-30.** O mesmo teste rodou duas vezes, com 20 minutos de diferença: 4 cópias simultâneas e depois 1 cópia sozinha.
   - As 4 cópias simultâneas falharam juntas às 13:40:43–13:40:46, em 4 GPUs diferentes.
   - A cópia sozinha rodou limpa e reproduziu exatamente o resultado de 29/10.
4. **Também houve um período de decode mais lento**, entre ~01:30 e ~06:00 de 30/10: 7–12% a mais por token, sem erros.
   - Já tinha passado às 13:30.
   - Não conseguimos atribuí-lo a nada com o que medimos; o monitoramento periódico (seção 3) está ativo.
5. **O que está estável:**
   - GPU: clock de 1980 MHz sem throttling, matmul bf16 de ~660 TFLOPS, HBM de 3,27 TB/s;
   - PCIe: host → GPU de 57,6 GB/s;
   - CPU: latência de lançamento de kernel de ~4 µs, inclusive com o nó carregado (load average 27–38).
6. **Pedidos à equipe do cluster** estão na seção 5:
   - logs do driver (`dmesg`, XID, `nvidia-bug-report`) nas janelas listadas;
   - versão do driver e limites do módulo `nvidia`/`nvidia-uvm`;
   - métricas do nó (DCGM/Prometheus);
   - política de CPU dos pods.

### Medições

Execuções do teste de referência, o mesmo cenário (10 modelos de 8B, carga de 600 s) com o mesmo código e as mesmas sementes:

| Momento (UTC) | Jobs simultâneos | SLO | Erros |
| --- | --- | --- | --- |
| 29/10, 20h | 3 | 73,4% | nenhum |
| 30/10, 13:30 | 4 cópias + 2 jobs de outra sessão | 56–64% | 2–5 erros de driver e 2–5 processos mortos por execução |
| 30/10, 13:53 | 1 | 73,5% | nenhum |

## 1. Ambiente

| Item | Valor | Fonte |
| --- | --- | --- |
| Nós da fila | **1**. O Polyaxon reporta "0/1 nodes are available: Insufficient nvidia.com/gpu" quando a fila enche | status dos runs |
| GPUs | 8 × NVIDIA H200, 143.771 MiB cada (barramentos 04, 23, 43, 64, 84, A3, C3, E4) | `nvidia-smi` nos jobs |
| Driver / CUDA | 550.163.01 / 12.4 | idem |
| CPU | 2 × AMD EPYC 9534, 64 núcleos cada (128 no total), 2 nós NUMA; a GPU 64, por exemplo, tem afinidade 0–63 | `lscpu`, `nvidia-smi topo -m` |
| Memória do host | 2,2 TB | `free -g` |
| Limites do pod | sem limite de CPU (`cpu.max: max`) nem de memória (`memory.max: max`); o pod enxerga as 128 CPUs | cgroup |
| Compartilhamento | o nó é usado também por outras equipes. Em 60 dos nossos 98 jobs a GPU demorou mais de 5 min para ser concedida (até 11 h, entre 27/10 e 28/10), com só 0–3 jobs nossos rodando: as outras GPUs estavam ocupadas fora do nosso projeto | `reports/data/2026-10-30-cluster/espera_gpu.csv` |

Como é a nossa carga:
- **Processos:** cada job ocupa 1 GPU e roda de 10 a 14 processos Python. Cada processo é um worker do SGLang.
- **Memória de KV:** cada worker usa o kvcached, que reserva 25 GB de espaço virtual e mapeia páginas físicas de 2 MB sob demanda pela API de memória virtual do CUDA (`cuMemCreate`, `cuMemMap`, `cuMemSetAccess`, `cuMemUnmap`, `cuMemRelease`).
- **Volume de mapeamentos:** um job faz dezenas de milhares de mapeamentos de 2 MB, e os modelos entram e saem da GPU o tempo todo (cópia de 16 GB de pesos do host para a GPU a cada troca).

## 2. Falhas do driver dependem de quantos jobs rodam no nó

**Sintoma.** Os processos morrem com mensagens do kvcached e do PyTorch como:

```
csrc/page.cpp:38 cuMemSetAccess(reinterpret_cast<CUdeviceptr>(vaddr), kPageSize, &accessDesc_, 1) failed in CUDA driver (2): out of memory
csrc/page.cpp:21 cuMemCreate(&handle_, kPageSize, &prop, 0) failed in CUDA driver (2): out of memory
RuntimeError: CUDA error: out of memory     (torch.UntypedStorage._new_shared_cuda, ao abrir um tensor CUDA compartilhado via IPC)
```

**Por que suspeitamos do nó e não da GPU:**
- **GPU vazia.** Em 30/10, das 00:36 às 01:04, o teste de partida que rodamos antes de cada execução falhou em **GPUs vazias** (0,0 GB usados), em 2 jobs diferentes. O teste sobe 10 processos que inicializam o kvcached; nenhum dos 10 conseguiu, com `cuMemSetAccess ... out of memory`. Nesse momento, outros 3 jobs nossos rodavam em outras GPUs do nó.
- **Falhas simultâneas.** Elas acontecem ao mesmo tempo em GPUs diferentes:

  | Janela (UTC) | Jobs com processos mortos no mesmo minuto |
  | --- | --- |
  | 27/10 12:47:38–12:47:46 | 3 jobs |
  | 27/10 13:26–13:26:52 | 3 |
  | 27/10 13:34:36–13:34:39 | 3 |
  | 27/10 13:55:25–13:55:28 | 3 |
  | 30/10 00:42:54 | 3 |
  | 30/10 13:40:43–13:40:46 (teste controlado) | 4 |

- **O mesmo código roda limpo com pouca concorrência**, no mesmo dia e na mesma hora (seção 2.2).

### 2.1 Frequência por número de jobs simultâneos

Figura: `reports/figs/2026-10-30-cluster/concorrencia.png`. Dados de 27/10 a 30/10, só com a versão do nosso código que já tinha as correções de robustez de memória; testes de limite de memória excluídos.

| Jobs Prism no nó ao mesmo tempo | Níveis com erro de driver | Níveis em que o processo de carga de pesos morreu |
| --- | --- | --- |
| 1 | 1 de 59 (2%) | 0 |
| 2 | 2 de 75 (3%) | 0 |
| 3 | 2 de 75 (3%) | 0 |
| 4 | 16 de 42 (38%) | 5 |
| 5 | 23 de 29 (79%) | 8 |
| 6 ou mais | 5 de 7 (71%) | 1 |

"Nível" é uma execução de ~10–15 min de um cenário. A contagem de jobs inclui só os nossos. Jobs de outras equipes no mesmo nó não são visíveis para nós e também podem contribuir. Com 4 jobs o resultado varia: em 28/10, das 13h às 14h, 4 jobs rodaram 18 níveis sem erro. Isso sugere que o gatilho é o volume de operações de memória virtual feitas ao mesmo tempo no nó, e não só o número de jobs.

### 2.2 Teste controlado (30/10)

| Execução | Início (UTC) | Jobs no nó | SLO | Ativação máx. de um modelo | Partida de 10 processos com kvcached | Erros de driver / processos mortos |
| --- | --- | --- | --- | --- | --- | --- |
| 4 cópias simultâneas do mesmo cenário | 13:29–13:30 | 4 + 2 de outra sessão nossa | 56,4–63,9% | 14,5–22,1 s | 72–83 s | 2–5 / 2–5 por execução, todos às 13:40:43–46 |
| a mesma, sozinha | 13:53 | 1 (+1 de outra sessão) | **73,5%** | 6,9 s | 49 s | 0 / 0 |
| referência, 29/10 | 20:09 | 3 | 73,3–73,4% | 7,0–11,1 s | 48–60 s | 0 / 0 |

O minuto 13:40 é o momento em que as 4 cópias, que seguem o mesmo roteiro, trocam ao mesmo tempo o grupo de modelos ativos. Isso gera uma rajada simultânea de alocações e mapeamentos de memória virtual nas 4 GPUs.

Durante o teste, rodamos sondas de desempenho em outras GPUs (13:33 e 13:38) com o load average do nó em 27–38. A latência de lançamento de kernel, o decode, o matmul e o PCIe ficaram iguais aos do nó ocioso (seção 3). A degradação não aparece em computação nem em transferência; aparece nas operações de memória virtual do driver.

## 3. Sondas padronizadas

Criamos um job curto (`polyaxon/cluster_probe.sh`, ~5 min, 1 GPU) com medidas fixas:
- latência de lançamento de kernel CUDA;
- um passo de decode de um modelo com a forma do Llama-3.1-8B, com e sem CUDA graph;
- matmul bf16, cópia HBM e cópias host↔GPU;
- cópia de memória do host;
- o mesmo teste de partida do kvcached (1 e 10 processos), a partir das sondas das 14:09.

Ele também amostra a cada 0,5 s o clock, a potência, a temperatura e os motivos de throttling da GPU, e guarda o load average do nó. Desde 30/10 13:24 roda uma série com uma sonda a cada 45 min, por 24 h.

Resultados até 13:40 (`reports/data/2026-10-30-cluster/sondas.csv`, figura `reports/figs/2026-10-30-cluster/sondas.png`):

| Sonda | GPU | Load average do nó | Lançamento (µs) | Decode lote 1 eager / CUDA graph (ms) | Decode lote 32 (ms) | Matmul (TFLOPS) | HBM (TB/s) | H2D pinned (GB/s) | SM clock |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 13:19, nó ocioso | 64 | 0,3 | 4,06 | 14,90 / 8,68 | 25,76 | 669 | 3,27 | 57,6 | 1980 MHz, sem throttling |
| 13:22, nó ocioso | 43 | 0,3 | 4,00 | 14,89 / 8,76 | 25,78 | 657 | 3,27 | 57,6 | 1980 MHz |
| 13:33, sob carga | 23 | 33 | 3,65 | 14,68 / 8,66 | 25,53 | 646 | — | 57,6 | 1980 MHz |
| 13:38, sob carga | A3 | 27–28 | 3,96 | 14,96 / 8,67 | 25,65 | 660 | — | 57,6 | 1980 MHz |

Fixar o processo nas CPUs do nó NUMA da GPU, em vez das do outro nó, muda o lançamento de kernel em ≤ 5% e o decode em < 1%. NUMA não explica a variação.

## 4. Período de decode mais lento (30/10, ~01:30–06:00), sem erros

Figura: `reports/figs/2026-10-30-cluster/mesmo_codigo.png`. Mesmo código e mesmas sementes, com execuções sem erro:

| Cenário | Tempo por token, mediana das execuções (29/10 20h → 30/10 01:30–06:00) | SLO, mediana |
| --- | --- | --- |
| 10 modelos, troca lenta | 41,5 → 46,4 ms (+12%) | 73,4 → 68,5% |
| 10 modelos, troca rápida | 41,5 → 45,5 ms (+10%) | 90,9 → 82,5% |
| 12 modelos, trace real | 47,6 → 50,7 ms (+7%) | 72,2 → 70,3% |

Às 13:53 do mesmo dia, o cenário 1 voltou a 41,6 ms e 73,5%.

Nesse período rodavam só 1–3 jobs nossos, sem erro de driver, mas outros jobs nossos esperavam até 40 min por GPU: o nó estava cheio de jobs de outras equipes. Ainda assim, o indicador "nó cheio" que conseguimos montar não separa os níveis lentos dos rápidos no conjunto dos dados. **Não sabemos a causa.** As sondas periódicas e as métricas do nó, se pudermos acessá-las, devem esclarecer.

Na escala de dias (figura `reports/figs/2026-10-30-cluster/historico.png`, 493 níveis), o tempo por token de execuções da mesma carga fica tipicamente dentro de ±10% da mediana. As falhas de driver se concentram em duas janelas, 27/10 das 12:20 às 16:30 e 30/10 das 00:30 às 01:10. Uma terceira, 30/10 às 13:40, foi provocada de propósito. O tempo de partida do kvcached (10 processos) variou de 22 a 115 s; o máximo, 115 s, caiu na janela de 30/10 00:30–01:10.

## 5. Hipóteses e pedidos

**Hipótese principal.** Algum recurso **do nó inteiro** usado pelas operações de memória virtual do CUDA (VMM) se esgota quando muitos processos em várias GPUs alocam e mapeiam páginas ao mesmo tempo. O driver devolve "out of memory" mesmo com a GPU vazia. Candidatos que não conseguimos verificar de dentro do pod:
- memória do kernel ou do driver usada para tabelas de páginas e handles;
- limites internos do módulo `nvidia` / `nvidia-uvm`;
- interação com processos de outras equipes no mesmo nó.

**Pedidos:**

1. **Logs do driver nas janelas** (UTC):
   - 27/10 12:20–16:30;
   - 30/10 00:30–01:10;
   - 30/10 13:39–13:42.

   Interessam `dmesg` (mensagens `NVRM`, `Xid`), `journalctl -k` e, se possível, um `nvidia-bug-report.sh` do nó.
2. **Versão e parâmetros do driver.** O nó usa 550.163.01. Gostaríamos de saber:
   - se há atualização prevista (R550 mais recente ou R570);
   - quais parâmetros os módulos usam (`/proc/driver/nvidia/params`, `modinfo nvidia-uvm`);
   - se o persistence mode está ligado.
3. **Métricas do nó.** Há exportador DCGM ou Prometheus com métricas por GPU e do host (memória do kernel, `slab`, CPU, eventos XID)? Se houver, pedimos acesso de leitura, ou um export das janelas acima.
4. **Outras cargas no nó.** Que jobs de outras equipes rodavam nas janelas acima? Elas usam memória virtual do CUDA, ou alocações e trocas de modelos intensas?
5. **Política de CPU e memória dos pods.** Hoje os pods não têm requests nem limites de CPU ou memória. Isso não apareceu como causa nos nossos testes, mas afeta a reprodutibilidade. Há como pedir CPUs dedicadas no nó NUMA da GPU (CPU manager / topology manager)?

**Do nosso lado:**
- deixaremos de rodar mais de 3 jobs Prism ao mesmo tempo no nó;
- vamos registrar o load average e o tempo de partida do kvcached em cada execução;
- vamos considerar inválidas as execuções com erro de driver;
- vamos comparar políticas só entre execuções rodadas no mesmo período.

## 6. Dados e como reproduzir

| Arquivo | Conteúdo |
| --- | --- |
| `reports/data/2026-10-30-cluster/niveis.csv` | um nível por linha: horário, SLO, tempo por token, ativação, cópia de pesos, partida do kvcached, erros de driver, processos mortos, jobs Prism no nó |
| `reports/data/2026-10-30-cluster/sondas.csv` | uma sonda por linha |
| `reports/data/2026-10-30-cluster/espera_gpu.csv` | tempo até a GPU ser concedida a cada job nosso e quantos dos nossos rodavam |
| `reports/data/2026-10-30-cluster/polyaxon_runs.json` | lista dos nossos runs no Polyaxon (21/10–30/10) |
| `reports/figs/2026-10-30-cluster/` | figuras citadas |

```bash
# sonda de desempenho (1 GPU, ~5 min)
PRISM_JOB_SUFFIX=-sonda PRISM_JOB_ENV="PROBE_REPS=3 PRISM_TIMEOUT=1800" polyaxon/submit.sh cluster_probe
# baixar um job (um por vez: downloads em paralelo do CLI misturaram conteúdo entre jobs)
polyaxon ops artifacts -p kunumi/hpc4ai -uid <uuid> -d outputs --path <dl>/<nome>-<uuid8> --no-untar
tar -xzf <dl>/<nome>-<uuid8>/outputs.tar.gz -C <dl>/<nome>-<uuid8>   # o arquivo tem bytes extras no fim; o tar avisa e extrai tudo
# indicadores por nível e por sonda, e figuras (pandas/matplotlib: /mnt/scratch/scheduler/opt-env/bin/python)
python3 polyaxon/cluster_history.py <dl> reports/data/2026-10-30-cluster/polyaxon_runs.json reports/data/2026-10-30-cluster/niveis.csv
python3 polyaxon/cluster_probe_summary.py <dl sondas> reports/data/2026-10-30-cluster/sondas.csv
python3 polyaxon/plot_cluster.py reports/data/2026-10-30-cluster/niveis.csv reports/data/2026-10-30-cluster/sondas.csv reports/figs/2026-10-30-cluster
# teste controlado de concorrência: 4 cópias simultâneas do cenário de referência; depois 1 sozinha
for r in 1 2 3 4; do PRISM_JOB_SUFFIX=-load-$r PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f1_codeab_suite.tsv" polyaxon/submit.sh; done
PRISM_JOB_SUFFIX=-conc-solo PRISM_JOB_ENV="PRISM_SUITE=polyaxon/configs/f1_codeab_suite.tsv" polyaxon/submit.sh
```

Jobs do teste controlado:
- 4 cópias simultâneas: `02044f2f`, `136ef1ea`, `367b3e1e`, `81dced42`;
- cópia sozinha: `7738ea98`;
- sondas: `fc1d01f5` (13:19), `2a4d26a8` (13:22), `be46f324` (13:33), `3735a789` (13:38).
