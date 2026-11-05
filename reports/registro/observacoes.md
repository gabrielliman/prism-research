# Observações e limitações conhecidas

Fatos sobre o sistema ou o método que condicionam a leitura dos resultados, mas que não são decisões (essas ficam em `decisoes.md`) nem erros do sistema (esses ficam em `reports/erros.md`). Cada entrada diz de onde vem, o efeito, e o que fazer se for revista.

## O1 — Todas as execuções rodam sem CUDA graphs (2026-11-04)

**O que é:** todo servidor das nossas execuções sobe com `--disable-cuda-graph`, desde outubro (`polyaxon/run_examples.sh`). **Fica assim, por decisão do Gabriel (2026-11-04): não ativar.**

**De onde vem:**
- **Código:** o padrão do código é com CUDA graphs ligados (`disable_cuda_graph: bool = False`, `python/sglang/multi_model/multi_model_server_args.py:194`).
- **Repositório:** os três modos de exemplo do `README.md` do Prism, inclusive o "Full Prism", desligam CUDA graphs (linhas 131, 162 e 194). Os nossos flags copiam esses exemplos.
- **Artigo:** diz só que o kvcached é "fully compatible with CUDA graph optimizations commonly used in LLM serving frameworks" (§5.2, D4). Não diz se a avaliação usou CUDA graphs.

**Efeito medido e esperado:**
- **Decode mais lento.** Um passo de decode do 8B com lote 1 leva 14,9 ms sem CUDA graph e 8,7 ms com, cerca de 40% menos (sonda do nó, `reports/2026-10-30 Variação de desempenho do nó GPU do cluster.md`, seção 3).
- **Sensibilidade à CPU.** Sem CUDA graphs, cada passo de decode lança os kernels pela CPU. Por isso o TPOT é sensível à disputa de CPU no nó. É a causa provável:
  - do CV de 48% na `f2-iso` (D18);
  - da dispersão do P95 nas bases dedicadas (D21).
- **Saturação mais cedo.** A capacidade de computação por GPU é menor do que seria com CUDA graphs. No C5, um 8B sozinho a ~25 req/s já fica no limite e a fila não se desfaz (D21).
- **Não medido:** ligar CUDA graphs obrigaria cada ativação de modelo a capturar os grafos de novo. Isso aumentaria `Ĉ_at` e a memória por modelo. É o mais provável motivo de o repositório desligar.

**Como ler os resultados:**
- as latências absolutas (TPOT, TTFT, bases do S2/S2M) e a capacidade por GPU valem **para esta configuração**, não para o hardware;
- a comparação entre políticas é justa, porque todas rodam com a mesma configuração.

**Se for revista:**
- seria uma mudança de configuração do sistema;
- invalida a comparação com outubro, a F0 e a F1;
- obriga a medir de novo as bases (`latencia_ded.json`), o `Ĉ_at` e o `p̂`.

Um teste separado, que não muda a configuração principal, pode medir o custo de ativação e o TPOT com CUDA graphs. Ele só roda se o Gabriel pedir.

## O2 — A base do S2/S2M do C5 é dominada pela fila do próprio modelo (2026-11-04)

**O que é:** no C5 (`ovl_compute`), cada 8B recebe ~25 req/s. Na execução dedicada, isso já satura a GPU (ver O1).
- No `model_1`, a fila não se desfez: o TTFT mediano foi de 14,6 s, contra 63 ms no `model_2`.
- A base junta ficou em:
  - TTFT P50 0,87 s / P95 15,3 s;
  - TPOT P50 45 ms / P95 70 ms.
- Ela mede a fila e o decode com lote grande, não o tempo de atendimento sem fila.

**Decisão (Gabriel, 2026-11-04):** fica como está. O critério da base é o mesmo para todas as cargas (D20, D21), sem exceção por cenário.

**Como ler os resultados:**
- no C5, o SLO S2/S2M é muito frouxo no TTFT: `k_T = 2` com a base P95 dá ~30 s;
- por isso, o S2/S2M quase não discrimina as políticas pelo TTFT;
- os resultados do C5 devem ser lidos pelo S1, que é sempre reportado junto, e pela vista só TPOT;
- todo relatório que use o C5 com S2/S2M declara essa limitação.

## O3 — As linhas de base usam o SLO enviado, só na ordem de ativação (2026-11-04)

**O que é:** a política padrão (`simple_global.py`, passo 3) ordena os modelos inativos com fila pela proporção de requisições com orçamento de tempo esgotado (`remaining_time_budget = slo − espera`) nos últimos 3 s; a fila do GPU scheduler (`request_queue.py`) ordena por `chegada + slo − prefill`. Com `--slo-spec` (F6a.1), o SLO enviado muda por família e nível.

**Efeito:** com modelos idênticos (C1, T1: todos Llama-3.1-8B, base junta, D21) o SLO é o mesmo para todos os modelos, então a fila do GPU scheduler não muda de ordem. A ordem de ativação da A0.x pode mudar um pouco (a proporção de violadas depende do SLO). Por isso as linhas de base rodam com o S1 (1 s) enviado, como até aqui, e as curvas de outras famílias são calculadas depois (seção 5.4); a diferença de comportamento que um SLO enviado diferente causaria na A0.x não é medida. O abort por SLO (`--abort-exceed-slos`) está desligado em todas as execuções.
