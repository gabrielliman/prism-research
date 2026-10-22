# Sobrecarga real no Prism, SGLang e vLLM (2026-10-21)

## Resumo

O teste anterior de sobrecarga (`reports/2026-10-21 Prism em sobrecarga.md`) não sobrecarregou a memória. Desta vez, montamos 4 cenários em que a sobrecarga é real e comprovada pelos dados: memória de pesos, rodízio de grupos, memória de KV e computação. Rodamos todos com o Prism nos dois backends (SGLang 0.3.4 original e vLLM 0.30), numa H200 por job.

| Cenário | O que sobrecarrega | SGLang | vLLM |
| --- | --- | --- | --- |
| `ovl_mem`: 10× 8B sempre ocupados | memória de pesos | **fome**: 3 modelos nunca atendidos (0,2 req/s por modelo); **queda do servidor** por falta de memória (0,5 req/s) | os mesmos 3 modelos ficam sem atendimento durante toda a carga e só entram depois que ela acaba (TTFT P99 de 338–358 s); sem queda |
| `ovl_phases`: 10× 8B em 2 grupos que se alternam | memória de pesos, com rodízio | tudo atendido; TTFT P99 53 s | tudo atendido; TTFT P99 51 s |
| `ovl_kv`: 4× 8B com textos longos | memória de KV | degrada sem falhas; vazão máxima 1,1 req/s | degrada sem falhas; vazão máxima 1,45 req/s |
| `ovl_compute`: 2× 8B, 20 a 100 req/s | computação | satura em ~25 req/s; a fila cresce sem limite | satura em ~28 req/s; idem |

Os testes revelam três limitações do plano de controle do Prism, que é o mesmo nos dois backends:

1. **Ele nunca despeja um modelo ocupado.** Só despeja modelos ociosos há mais de 50 s. Com todos os modelos recebendo tráfego, os que não couberam na GPU ficam sem atendimento enquanto a carga durar.
2. **Ele ativa modelos sem reservar memória para o KV.** A decisão olha só a memória livre naquele instante. No SGLang isso causa ativações que falham sem aviso e a queda do servidor. No vLLM, a ativação espera até haver memória.
3. **Ele não tem controle de admissão.** Acima da capacidade, nada é recusado e a latência cresce sem limite.

## Como os testes foram feitos

| Item | O que foi usado |
| --- | --- |
| Onde | Polyaxon, projeto `kunumi/hpc4ai`, fila `axia/default`, 1 NVIDIA H200 (139,7 GiB) por job |
| SGLang | imagem `gabrielliman/prism:sglang0.3.4-cu121` (o container do `install.md` + kvcached `prism/shm` + Redis 7.2.7) |
| vLLM | imagem `gabrielliman/prism:vllm0.30-kvcached0.1.6`, `--engine-backend vllm` |
| Servidor | flags do exemplo 3 do README: memória elástica (kvcached), GPU scheduler, controlador `simple-global`, model service, worker pool, `--max-mem-usage 67.28`. `--workers-per-gpu` igual ao número de modelos, para não cair no bug de 4 workers ([report anterior](2026-10-21%20Prism%20em%20sobrecarga.md#bug-com-4-workers)) |
| Modelo | `meta-llama/Llama-3.1-8B-Instruct` (15 GB de pesos) em N cópias (`model_1` … `model_N`) |
| Carga | `polyaxon/overload_load.py`: chegadas abertas (Poisson), popularidade uniforme, saída de tamanho exato (`ignore_eos`). Usa o mesmo cliente do `benchmark.py` |
| Passos | `ovl_mem`, `ovl_phases`, `ovl_kv`, `ovl_compute` em `polyaxon/run_examples.sh`; análise com `polyaxon/analyze_ovl.py` |

**Como cada nível é medido.** Cada nível sobe um servidor novo. A carga dura uma janela fixa, mais um prazo de esvaziamento. Requisições pendentes no fim do prazo contam como "não atendidas", sem travar o job. Durante o nível, o `nvidia-smi` registra a memória da GPU a cada segundo. Do log do controlador global saem as ativações, os despejos, as vezes em que um modelo "não coube" (`No suitable GPU found`) e a menor memória livre que ele viu.

**SLO.** TTFT ≤ 1 s e TPOT ≤ 100 ms. O TTFT é o que o servidor mede: do momento em que a requisição chega a ele até o fim do prefill.

**Como saber que a sobrecarga foi real.** Pela memória da GPU (perto de 140 GB) e pelos avisos de "não coube", no caso da memória. Pela vazão atendida parando abaixo da oferecida e pelo TTFT crescendo, no caso da computação. A utilização reportada pelo `nvidia-smi` não serve: ela marca 89% de GPU ocupada até com carga leve.

## Cenários e resultados

### `ovl_mem`: mais pesos do que cabem na GPU

10 cópias do 8B somam 151 GB de pesos, mais que os 139,7 GB da GPU. Seis começam ativas, e todos os 10 modelos recebem tráfego o tempo todo, então nenhum fica ocioso. Janela de 300 s, prazo de 300 s, prompts de 256–1.024 tokens e saídas de 128–512.

| Velocidade | Backend | Atendidas | Não atendidas | Falhas | TTFT mediano / P99 | SLO | GPU no pico | Ativações / despejos |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0,2 req/s por modelo | SGLang | 396 / 599 | **203** | 0 | 0,16 / 14,2 s | 60,8% | 139,7 GB | 4 / 7 |
| 0,2 | vLLM | 599 / 599 | 0 | 0 | 2,7 / 338 s | 45,9% | 135,5 GB | 4 / 9 |
| 0,5 | SGLang | 5 / 1.453 | 0 | **1.448** (servidor caiu) | — | 0,3% | 139,7 GB | 2 / 0 |
| 0,5 | vLLM | 1.453 / 1.453 | 0 | 0 | 95 / 358 s | 14,2% | 136,6 GB | 4 / 10 |

**Os modelos de fora não são atendidos enquanto a carga dura, nos dois backends.** A linha do tempo das ações do controlador e da primeira resposta de cada modelo (SGLang e vLLM, 0,2 req/s):

- Os modelos que couberam começam a responder nos primeiros 30 s. `model_7`, `model_9` e `model_10` não respondem nada durante os 300 s de carga.
- Os primeiros despejos só acontecem aos 341 s: 41 s depois do fim da carga, quando os modelos ficam 50 s ociosos.
- **No vLLM**, o `model_9` foi ativado já aos 5 s, mas só respondeu aos 345 s: a ativação esperou até haver memória. `model_7` e `model_10` foram ativados aos 347 e 352 s. A partir daí os três esvaziam a fila acumulada. Por isso tudo aparece como "atendido", mas com ~6 min de espera.
- **No SGLang**, eles nunca respondem, nem depois dos despejos.

A política explica a fome. `_check_idle_instance_eviction` (`scheduling/policy/simple_global.py:253`) só despeja modelos sem requisições há mais de `MODEL_IDLE_THRESHOLD = 50` s (linha 185). E `gen_actions` não tem nenhum outro caminho de despejo: um modelo com requisições e sem lugar fica "inativo com requisições" e registra `No suitable GPU found` a cada ciclo. Foram 136 a 143 avisos por nível no vLLM.

**SGLang: a ativação falha sem aviso.** O controlador ativou `model_9`, `model_7` e `model_10` aos 5, 15 e 25 s, porque a memória livre naquele instante (`simple_global.py:726`) parecia suficiente. Depois o KV dos modelos ativos cresceu, e o kvcached do worker não conseguiu reservar memória (`cuMemCreate ... out of memory`, 3 vezes). A partir daí:

- o GPU scheduler mantém os três em `activating` até o fim e continua enfileirando requisições para eles;
- o controlador global os trata como `ACTIVE`, com 0,00 GB de memória;
- como têm requisições na fila, nunca são despejados, e suas requisições nunca são atendidas.

**SGLang a 0,5 req/s: o servidor cai.** O controlador ativou mais 2 modelos aos 5 s, e a GPU subiu de 110 para 143 GB. O SGLang começou a retirar requisições (`Decode out of memory`), e um worker morreu com `torch.OutOfMemoryError` (24 MiB livres). O servidor inteiro caiu cerca de 12 s depois do início da carga, e as 1.448 requisições seguintes falharam com conexão recusada.

**vLLM: sem queda.** A ativação de um modelo que não cabe espera até haver memória e então conclui. O resultado é latência enorme, mas nenhuma perda.

### `ovl_phases`: rodízio de grupos

Os mesmos 10 modelos, divididos em 2 grupos de 5 que se alternam a cada 150 s. Enquanto um grupo recebe tráfego, o outro fica ocioso. Começam ativos os 5 do primeiro grupo. Janela de 600 s, 0,5 req/s por modelo.

| Backend | Atendidas | TTFT mediano / P99 | SLO | GPU no pico | Ativações / despejos / "não coube" |
| --- | --- | --- | --- | --- | --- |
| SGLang | 1.564 / 1.564 | 0,14 / 53,2 s | 73,3% | 134,9 GB | 15 / 15 / 86 |
| vLLM | 1.564 / 1.564 | 0,12 / 50,5 s | 75,5% | 139,1 GB | 15 / 15 / 66 |

Aqui o Prism faz o compartilhamento da GPU no tempo para o qual foi desenhado: 15 trocas em 10 min, nenhuma requisição perdida. O custo está na transição. Os modelos do grupo novo que não cabem esperam os do grupo antigo ficarem 50 s ociosos, e daí vem o TTFT P99 de ~50 s. Os dois backends ficam praticamente iguais, porque o custo está no controlador, não no engine.

### `ovl_kv`: o KV não cabe

4 cópias do 8B (60 GB de pesos), todas ativas, cada uma podendo usar até 40 GB de KV. Prompts de 2.048–4.096 tokens e saídas de 1.024–2.048, durante 180 s, com prazo de 600 s.

| Velocidade | Backend | Oferecido | Atendido | TTFT mediano / P99 | SLO | GPU no pico |
| --- | --- | --- | --- | --- | --- | --- |
| 0,25 req/s por modelo | SGLang | 1,02 req/s | 0,74 req/s | 0,34 / 0,54 s | 100% | 117,4 GB |
| 0,25 | vLLM | 1,02 req/s | 0,80 req/s | 0,32 / 0,90 s | 98,9% | 105,5 GB |
| 0,5 | SGLang | 1,87 req/s | 0,96 req/s | 18 / 94 s | 36,2% | 132,8 GB |
| 0,5 | vLLM | 1,87 req/s | 1,26 req/s | 0,41 / 42 s | 58,2% | 133,9 GB |
| 1 | SGLang | 3,99 req/s | 1,09 req/s | 178 / 423 s | 15,7% | 133,0 GB |
| 1 | vLLM | 3,99 req/s | 1,45 req/s | 99 / 258 s | 20,8% | 137,1 GB |

Nos dois backends o KV encheu a GPU (133–137 GB). O SGLang retirou requisições por falta de KV 17 e 29 vezes nos dois níveis mais altos. Ainda assim **nenhuma requisição falhou ou ficou sem resposta**: cada engine segura o próprio KV, e o excesso vira fila. Os despejos registrados aconteceram depois do fim da carga, com as filas vazias. O vLLM teve 33% mais vazão no nível mais alto.

### `ovl_compute`: mais requisições do que a GPU processa

2 cópias do 8B, prompts de 256–768 tokens e saídas de 128–384. Cada nível sustenta a carga por 120 s, com prazo de 300 s.

| Oferecido | SGLang: atendido | SGLang: TTFT mediano / P99 | SGLang: SLO | vLLM: atendido | vLLM: TTFT mediano / P99 | vLLM: SLO |
| --- | --- | --- | --- | --- | --- | --- |
| 20,5 req/s | 19,1 req/s | 0,07 / 0,15 s | 100% | 19,6 req/s | 0,06 / 1,2 s | 98,1% |
| 25,8 req/s | 23,3 req/s | 0,09 / 1,3 s | 96,6% | 24,5 req/s | 0,07 / 1,2 s | 98,6% |
| 50,3 req/s | 26,1 req/s | 46 / 94 s | 9,6% | 27,9 req/s | 43 / 90 s | 4,3% |
| 100,4 req/s | 25,0 req/s | 150 / 291 s | 1,1% | 28,6 req/s | 140 / 291 s | 2,1% |

A capacidade fica em ~25 req/s no SGLang (~6.400 tokens/s) e ~28 req/s no vLLM (~7.300 tokens/s). Acima dela, a vazão para e a fila cresce até o fim do prazo: a 100 req/s, 1.560 requisições (SGLang) e 38 (vLLM) ainda esperavam. Não houve falhas.

O Prism não recusa nada porque o controle de admissão do GPU scheduler está desligado: `admission_control` usa `net_available = float("inf")` (`scheduling/gpu/request_queue.py:137`), e o próprio comentário diz que a implementação não limita recursos.

### Ampliação dos testes de computação

*Em execução; esta seção será preenchida com os resultados.* São 7 testes, cada um nos dois backends (14 jobs):

| Teste | Pergunta | Como |
| --- | --- | --- |
| `fine` | Onde fica o joelho da curva? | 2× 8B, de 20 a 40 req/s em passos de ~2,5 |
| `sustained` | Ficar muito tempo acima da capacidade derruba o sistema? | 2× 8B, 37,5 req/s (~1,5× a capacidade) por 10 min |
| `models4`, `models6` | Dividir a GPU entre mais modelos ativos reduz a capacidade? | 4 e 6 modelos 8B ativos, 20, 30 e 40 req/s no total |
| `prefill` | E se a carga for de prefill? | prompts de 3.000–4.000 tokens, saídas de 16–64 |
| `decode` | E se a carga for de decode? | prompts de 32–128 tokens, saídas de 1.024–2.048 |
| `bursty` | Rajadas sobrecarregam mesmo com média abaixo da capacidade? | 15 e 20 req/s em média, com chegadas em rajadas (`--cv 4`) |

## O que isso representa

- **O Prism compartilha bem a GPU quando a carga se alterna** (`ovl_phases`): troca grupos sem perder requisições. O custo de cada troca (~50 s no P99) vem da regra de ociosidade, não da cópia dos pesos.
- **Ele não lida com demanda simultânea maior que a GPU** (`ovl_mem`). Sem despejar modelos ocupados, os modelos de fora não são atendidos enquanto a carga dura. Essa é a sobrecarga que o artigo motiva, e a política atual não a resolve.
- **No SGLang, a sobrecarga de memória derruba o sistema.** Ativações que falham ficam penduradas sem aviso, e um worker sem memória derruba o servidor inteiro. No vLLM, as ativações esperam pela memória, o que evita a queda, mas não a fome.
- **A sobrecarga de KV e a de computação viram fila**, nos dois backends: nada se perde, mas, sem controle de admissão, a latência cresce sem limite.
- **O vLLM é mais robusto e um pouco mais rápido em todos os cenários.** Parte disso é a geração do engine (2026 contra 2024), não o desenho do Prism.

**O que mudaria esse quadro no Prism:**
1. **Despejo de modelos ocupados** quando há modelos com requisições sem lugar, por exemplo pelo menor número de requisições ou pela menor folga de SLO, com preempção RECOMPUTE.
2. **Reserva de memória para KV nas ativações**, em vez de olhar só a memória livre no instante.
3. **Avisar o controlador quando uma ativação falha**, para ele tentar de novo ou desistir. É a mesma causa do bug dos 4 workers.
4. **Controle de admissão** no GPU scheduler, recusando ou adiando requisições acima da capacidade.

**Limitações.** Uma execução por cenário e backend; o report anterior mostrou que a variação entre execuções é grande. As cópias de um mesmo modelo representam modelos diferentes, o que não muda o uso de memória nem de computação. O SLO (1 s / 100 ms) é arbitrário, então os percentuais servem para comparar níveis e backends, não como meta absoluta. O teste na 4090 local mostrou um custo fixo de ~2,5 GB por worker do worker pool (contexto CUDA, reserva do kvcached e buffers), que também pesa na memória disponível.

## Problemas resolvidos no caminho

- **Gerador de carga:** a primeira rodada do `ovl_compute` teve milhares de falhas de conexão a 50 e 100 req/s. O gerador não aumentava o limite de arquivos abertos, como o `benchmark.py` faz com `set_ulimit`. Corrigido e refeito; os números acima são da rodada corrigida. A queda do SGLang no `ovl_mem` a 0,5 req/s não tem relação com isso: houve só ~5 req/s, e os logs do servidor mostram o `OutOfMemoryError`.
- **Medição de modelos novos:** o `profile_model_info.py` carrega o modelo pelo vLLM 0.6.3, que falha com Qwen2. Os passos agora usam `estimate_model_info.py`, que estima os mesmos valores a partir do checkpoint, sem GPU.

## Execuções

| Cenário | SGLang | vLLM |
| --- | --- | --- |
| `ovl_mem` | `5980af99` | `52b58015` |
| `ovl_phases` | `6af4c960` | `b3d7266e` |
| `ovl_kv` | `8917456e` | `b4b64489` |
| `ovl_compute` | `7e229f2b` (a primeira, `339e85e8`, teve o problema do gerador) | `b82b4409` |

Para rodar de novo:

```bash
# SGLang
PRISM_JOB_ENV="PRISM_STEPS=ovl_mem PRISM_TIMEOUT=2700" polyaxon/submit.sh
# vLLM
PRISM_IMAGE=gabrielliman/prism:vllm0.30-kvcached0.1.6 \
  PRISM_JOB_ENV="PRISM_BACKEND=vllm PRISM_STEPS=ovl_mem PRISM_TIMEOUT=2700" polyaxon/submit.sh
# outros passos: ovl_phases, ovl_kv, ovl_compute
# variáveis: PRISM_OVL_N, PRISM_OVL_ON, PRISM_OVL_RATES, PRISM_OVL_DURATION, PRISM_OVL_DRAIN, PRISM_OVL_LOAD, PRISM_OVL_MODEL
# análise:
python3 polyaxon/analyze_ovl.py <pasta outputs>
```
