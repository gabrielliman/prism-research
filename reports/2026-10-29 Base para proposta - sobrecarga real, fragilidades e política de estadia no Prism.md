# Base para proposta: sobrecarga real, fragilidades e política de estadia de modelos no Prism (2026-10-29)

Este texto reúne o que foi feito neste repositório sobre o Prism, para servir de referência na escrita de uma proposta de trabalho separada. Ele resume os relatórios de `reports/` e aponta onde está cada evidência. Os números vêm desses relatórios; nada aqui é medição nova.

## 1. Em uma frase

O Prism foi avaliado, no artigo e no benchmark que o acompanha, num regime em que a GPU nunca fica sem memória. Quando o colocamos em **sobrecarga real**, com mais modelos com demanda do que cabem na GPU, ele **quebra**, por falhas de robustez no gerenciamento de memória, e **deixa modelos com fome**, por limitações da política que decide quais modelos ficam na GPU. Nós corrigimos a primeira parte e começamos a explorar a segunda. A proposta é tratar a **política de estadia de modelos** como o problema central daqui em diante.

## 2. Contexto: o que o Prism faz

O Prism serve vários LLMs numa mesma GPU, compartilhando a memória entre eles:

- **Memória elástica (kvcached):** cada modelo reserva um espaço virtual de KV e só ocupa memória física quando precisa.
- **Worker pool:** um processo por modelo, que pode ser ativado (pesos copiados para a GPU) ou desativado (pesos liberados).
- **GPU scheduler e controlador global (`simple-global`):** a cada ciclo de 5 s, o controlador lê a memória livre da GPU e decide quais modelos ativar e quais despejar.

A regra de estadia do Prism é simples:

- um modelo inativo com requisições é **ativado se os pesos dele cabem** na memória livre naquele instante;
- um modelo ativo é **despejado só depois de 50 s sem nenhuma requisição** (`MODEL_IDLE_THRESHOLD`).

Não há outro caminho de despejo, nenhuma reserva de memória para o KV depois da ativação e nenhum controle de admissão.

## 3. Ponto de partida: o benchmark original não sobrecarregava

Rodamos o exemplo 3 do README (Prism completo) com o trace real do benchmark, 8 modelos, acelerado de 1× a 10× ([Prism em sobrecarga, 21/10](2026-10-21%20Prism%20em%20sobrecarga.md)). Todas as 754 requisições foram atendidas em todos os níveis, mas:

- **A memória nunca faltou.** O `--max-mem-usage 67,28 GB` do README limita cada modelo, não a GPU. A GPU sempre teve pelo menos 37 GB livres, e todos os despejos foram por ociosidade.
- **A carga só saturou a 10×.** Até 4×, a variação entre execuções idênticas era maior que o efeito da carga.

Conclusão: o cenário de avaliação **não exercitava o que o Prism promete resolver**, que é servir mais modelos do que cabem na GPU.

## 4. Como passamos a sobrecarregar de verdade

Montamos cenários em que a sobrecarga é comprovada pelos dados (memória da GPU perto de 140 GB, avisos de "não coube" do controlador, vazão abaixo da oferecida). Todos usam cópias do Llama-3.1-8B (15 GB de pesos) numa H200 (139,7 GB):

| Cenário | Montagem | O que estressa |
| --- | --- | --- |
| `ovl_mem` | 10 modelos, 6 cabem; todos recebem tráfego o tempo todo | mais demanda do que memória; nenhum modelo fica ocioso |
| `ovl_phases` | 10 modelos em 2 grupos de 5 que se alternam a cada 150 s | troca de conjunto de modelos ativos |
| `ovl_trace_big` | 12 modelos, um adaptador do trace real do Prism por modelo | popularidade desigual (296 a 36 requisições por modelo) |
| `ovl_mix` | 8 × 8B + 2 × 3B | modelos de tamanhos diferentes |
| `ovl_kv` | 4 modelos, todos ativos, prompts e saídas longos | crescimento do KV, sem trocas |
| `ovl_compute` | 2 modelos, 20 a 100 req/s | computação |

**Metodologia comum** (detalhes em cada relatório):
- Polyaxon (`kunumi/hpc4ai`), 1 H200 por job, imagem do `install.md` (SGLang 0.3.4 do Prism + kvcached + Redis).
- Gerador de carga próprio (`polyaxon/overload_load.py`): chegadas abertas, saída de tamanho exato, prazo extra de 300 s depois da carga. O que não responde no prazo conta como **não atendida**.
- SLO: TTFT < 1 s **e** TPOT < 100 ms, sobre todas as requisições enviadas. Medimos também a **pior espera pelo 1º token** de cada modelo, que é o que revela a fome.
- Cada nível sobe um servidor novo; repetições (em geral 3) para separar efeito de ruído.
- Linhas do tempo por execução: memória da GPU, ações do controlador e quando cada modelo está ativo e responde.

## 5. O que a sobrecarga revelou

As fragilidades se dividem em dois grupos, com causas e soluções diferentes.

### 5.1 Fragilidades de robustez: o sistema quebra

Comparamos o **Prism base** (sem nenhuma mudança nossa) com a versão corrigida, na mesma varredura de carga ([Limites de carga, 28/10](2026-10-28%20Limites%20de%20carga%20do%20Prism%20base%20e%20correções%20por%20erro%20(SGLang).md)):

- **O Prism base quebra assim que precisa trocar modelos, já na menor carga testada.** No `ovl_mem`, as 12 de 12 execuções da base perderam requisições, de 0,05 a 0,8 req/s por modelo: em 10 o servidor caiu, nas outras 2 workers morreram em silêncio. Foram atendidas 0–72% das requisições.
- **A falha não cresce com a carga; é disparada pelas ativações.** Basta dois modelos inativos receberem requisições perto um do outro.
- **O único regime seguro da base é sem trocas:** quando todos os modelos cabem e estão ativos.

A cadeia de falhas, com os identificadores usados em [`erros.md`](../erros.md):

| id | Fragilidade | Efeito |
| --- | --- | --- |
| P1 | O controlador decide uma segunda ativação enquanto a primeira ainda carrega e conta duas vezes a mesma memória livre (35% das ativações foram decididas assim; 22% já não cabiam) | gatilho de quase todas as outras falhas |
| P10 | O model service carrega um modelo por vez (ativação de 1,5 s a 21 s) | alarga a janela do P1 |
| P3/S3 | `torch.OutOfMemoryError` ao copiar os pesos | derruba o servidor |
| S2 | Qualquer exceção num worker chama `kill_parent_process`, que, com o worker pool, é o servidor inteiro | uma falha local vira queda total (10.318 requisições perdidas na varredura) |
| K1 | O kvcached chama `abort()` quando o driver recusa uma página | o worker morre sem traceback |
| P2/P4 | Ninguém detecta o worker morto; o modelo fica "ativando" para sempre, e o worker morto pode ser entregue a outro modelo | até 1.023 requisições presas num nível |
| S1 | Falta de KV no prefill leva a `pretty_print()`, que não existe sem radix cache | o worker cai |
| P5 | Corrida desativar/reativar: a confirmação atrasada de uma desativação antiga marca o modelo como inativo | o modelo passa fome até o fim (137 perdidas num `ovl_phases`) |
| P6 | Requisições retiradas na preempção ficam na fila local de um worker que pode ser reaproveitado | requisições perdidas |
| S4 | Requisição retirada no decode que termina no novo prefill sai sem horário de término, e o TTFT é sobrescrito | erro de medição |

P5 e P6 só aparecem quando a política troca modelos com mais frequência, o que mostra que **robustez e política estão ligadas**: qualquer política de estadia mais agressiva que a original depende dessas correções.

### 5.2 Fragilidades da política de estadia: o sistema não quebra, mas não serve

Mesmo sem nenhuma falha de robustez, a regra "ativa se os pesos cabem, despeja só depois de 50 s ocioso" falha de três formas ([Janela de ociosidade e estratégias de troca, 28/10](2026-10-28%20Janela%20de%20ociosidade%20e%20estratégias%20de%20troca%20no%20Prism,%20com%20as%20correções%20(SGLang).md)):

1. **Fome: um modelo ocupado nunca sai.** Se todos os ativos recebem tráfego contínuo, ninguém fica 50 s ocioso e os inativos esperam a carga acabar. "100% atendidas" esconde isso:
   - `ovl_mem` a 0,2 req/s: pior espera pelo 1º token de **352 s** numa carga de 300 s;
   - `ovl_trace_big`: **649 s** numa carga de 600 s, nas 5 repetições; 4 modelos com fome por quase toda a carga.
2. **Transição lenta: o grupo que sai ocupa a memória por 50 s a mais.** No `ovl_phases`, o grupo novo espera em média 38 s em cada troca (pior caso 62 s), com TTFT p90 de 34 s e SLO de 71%.
3. **Travamento (T1): ativar só pelos pesos pode deixar a GPU sem KV para ninguém.** No `ovl_mix`, a política original atende **2,6%** das requisições nas 3 repetições, mesmo com todas as correções; com 8 modelos no `ovl_mem`, **2%**. A explicação (29/10): o controlador vê 16,8 GB livres, ativa mais um 8B de 15 GB e sobra menos de 1 GB de KV para 9 modelos. Ninguém termina, ninguém fica ocioso, ninguém é despejado. É um impasse que a regra atual não tem como desfazer.

Há ainda uma limitação de desenho que não exploramos: **não há controle de admissão.** Acima da capacidade, nada é recusado e a latência cresce sem limite (`ovl_kv`, `ovl_compute`).

## 6. O que já corrigimos

Todas as correções estão neste repositório e documentadas, com causa, mudança e teste, no [relatório de mudanças](2026-10-22%20Correções%20de%20robustez%20de%20memória%20no%20Prism%20(SGLang).md). O repositório do kvcached não foi alterado.

| Mudança | O que faz | Resolve |
| --- | --- | --- |
| Rodada 1 | ativação que falha é desfeita e reportada (`ActivationOutOfMemory`); detecção de workers mortos (inclusive zumbis) com reativação em outro worker; aviso quando falta worker livre | P3/S3, P2/P4 |
| R2.1 | o controlador desconta da memória livre as ativações ainda em andamento (pesos + 1 GB de KV) até o GPU scheduler confirmar | P1 (e, com ela, a maior parte de K1 e P3) |
| R2.2 | no SGLang: prefill sem KV espera e tenta de novo (`PrefillKVFull`); uma exceção derruba só aquele worker | S1, S2 |
| R2.3 | o GPU scheduler ignora a confirmação de desativação superada por uma reativação | P5 |
| R2.4 | infraestrutura de teste: repetição da inicialização e verificação de saúde do nó antes de cada nível | testes confiáveis num nó compartilhado |
| R2.5 | no SGLang: TTFT do primeiro prefill e término correto de requisição retirada (local, não commitada) | S4 |
| Troca por throughput | requisições retiradas na desativação voltam à fila do Redis | P6 |

Também existe uma variante com um árbitro de memória entre processos e ajustes no kvcached aplicados em tempo de execução. Ela elimina o K1, mas custa até 16% do tempo dos workers, e fica desligada por padrão.

**Resultado.** Na mesma varredura em que a base quebrou 12 de 12 vezes, a versão corrigida teve **0 falhas de memória em 18 níveis** (zero mortes de worker, zero quedas, zero aborts) e atendeu 100% do `ovl_mem` em todas as taxas. Nos 150 níveis do estudo de políticas, também não houve perdas por falha, exceto um caso em investigação (seção 8).

**O que as correções não resolvem:** o travamento T1. Ele não é uma falha de código; é consequência da regra de ativação.

## 7. Primeira exploração da política de estadia

Com o sistema estável, comparamos alternativas à regra original, cada uma com 3 repetições ([relatório de 28/10](2026-10-28%20Janela%20de%20ociosidade%20e%20estratégias%20de%20troca%20no%20Prism,%20com%20as%20correções%20(SGLang).md)):

| Família | Ideia | Onde ajuda | Onde falha |
| --- | --- | --- | --- |
| Limiar de ociosidade curto (0,1 a 25 s) | despejar antes dos 50 s | `ovl_phases`: SLO de 71% para 87–91%, p90 de 34 s para 1–4 s; qualquer limiar até 10 s dá quase o mesmo | não resolve a fome quando ninguém fica ocioso (`ovl_mem` 0,5 req/s, trace 2×); ~1 despejo indevido por execução |
| Despejo sob pressão | se alguém não cabe, despejar quem está ocioso há ≥ 2 s | troca de grupos (SLO 76%) | menos que o limiar curto |
| Ociosidade adaptativa | limiar de cada modelo pelo seu próprio ritmo de chegada | fome no trace (649 s para 59 s) | igual a um limiar fixo de 10–25 s |
| Rodízio anti-fome | tirar o modelo ativo há mais tempo se alguém espera ≥ 30 s | — | não resolve a fome (escolhe mal quem entra) e derruba o SLO para 42% |
| Folga de KV na ativação | exigir 3 GB além dos pesos para ativar | candidata contra o T1 | **em teste** no `ovl_mix` (29/10) |
| **Troca por throughput por GB** | tirar o ativo de menor valor (tokens servidos por GB) quando a demanda envelhecida de um inativo o supera; variantes com preempção (P) e drenagem (D) | **acaba com a fome em todos os cenários com pressão** (pior espera de 30–57 s, contra 352 s, "nunca" e 649 s); é a única que funciona no `ovl_mix` (~100% contra 2,6%); melhor cauda no trace (p99 de 71 s contra 425 s) | no `ovl_mem`, o SLO cai de 62% para 17–25%: a espera é dividida entre todos; preempção sem drenagem recomputa centenas de requisições e é a pior variante sob pressão contínua |

**O que aprendemos:**

- **Nenhuma regra vence em todos os cenários.** O limiar curto é o melhor para troca de grupos; a troca por throughput é a única que resolve fome e impasse.
- **Há um conflito real entre justiça e SLO.** Com mais demanda do que memória, acabar com a fome distribui a espera e baixa o SLO agregado. A política precisa de um objetivo explícito (SLO total, pior caso por modelo, ou uma combinação).
- **Os mecanismos são complementares.** O limiar curto tira o grupo antigo assim que ele fica ocioso; a troca resolve os casos em que ninguém fica ocioso; a folga de KV evita o impasse.
- **O custo de uma troca precisa entrar na decisão.** Cada volta é uma partida a frio de alguns segundos, e a preempção joga fora trabalho já feito. Políticas que trocam demais (limiar de 1 s no `ovl_mem`, P1D0 no trace) perdem SLO por isso.
- **Robustez é pré-requisito.** Antes da R2.1 e da R2.3, os limiares curtos e as trocas perdiam centenas de requisições por falhas, e a comparação entre políticas não era possível.

## 8. O que fica em aberto

| Item | Situação |
| --- | --- |
| T1, travamento | causa explicada para o `ovl_mix` e para 8 modelos; com 14 modelos ainda não; teste da folga de KV em andamento |
| K1 com o nó degradado | mitigado, não eliminado; só a variante com árbitro o elimina, com custo |
| 25 requisições perdidas numa execução com preempção sem drenagem (trace) | 1 de 3 execuções, sem causa identificada; suspeita no caminho de devolução ao Redis |
| Controle de admissão | não explorado |

## 9. Direção proposta para o trabalho separado

**Objetivo.** Projetar e avaliar uma política de estadia de modelos para o Prism que funcione sob sobrecarga real: sem fome, sem impasse e com o melhor SLO possível dado o custo de trocar.

**Perguntas de pesquisa.**
1. Qual objetivo a política deve otimizar quando há mais demanda do que memória: SLO agregado, pior espera por modelo, ou uma combinação ponderada?
2. Como estimar o valor de manter um modelo na GPU (tráfego recente, fila, ritmo de chegada) contra o custo de uma troca (partida a frio, trabalho preemptado)?
3. Quanto KV é preciso reservar na ativação para evitar o impasse sem desperdiçar memória?
4. Quando é melhor drenar, preemptar ou recusar requisições (controle de admissão)?

**Plano em etapas.**
1. **Fechar a robustez restante:** confirmar a causa do T1 (com `py-spy` num travamento), resolver as 25 perdas da preempção e avaliar o árbitro sem lock na leitura (a causa do custo de 16%).
2. **Política unificada:** combinar limiar curto (ou adaptativo) para quem fica ocioso, troca por valor/GB para quem não fica, folga de KV obrigatória e detecção de impasse (nenhum ativo progride → despejar).
3. **Custo da troca no modelo de decisão:** medir partida a frio e trabalho preemptado e usá-los como penalidade, com histerese para evitar trocas em excesso.
4. **Controle de admissão:** recusar ou adiar requisições quando a fila de um modelo já garante violação do SLO.
5. **Avaliação:** os cenários da seção 4, mais cargas com mudanças graduais de popularidade e com modelos de tamanhos variados; comparação sempre contra a política original e contra as estratégias já testadas, com as mesmas métricas (SLO, cauda, pior espera por modelo, perdas, trocas).

**Contribuições esperadas.**
- Uma metodologia de sobrecarga real para sistemas multi-LLM, com cenários que o benchmark original não cobre.
- O inventário de fragilidades do Prism sob sobrecarga e as correções, já implementadas e medidas.
- Uma política de estadia que resolve fome e impasse, com a análise do conflito entre justiça e SLO.

## 10. Limitações a declarar na proposta

- **Um único nó compartilhado** no cluster: jobs simultâneos disputam o mesmo hardware, e houve janelas de nó degradado (por isso a verificação de saúde e o limite de 6 jobs).
- **Uma GPU (H200) por execução e uma versão do engine** (o SGLang 0.3.4 do Prism); nada foi testado com várias GPUs.
- **Poucas repetições** (2–3 por configuração, 1 na versão corrigida da varredura de limites); algumas diferenças entre políticas estão dentro do ruído.
- **Modelos repetidos:** a maior parte dos cenários usa cópias do mesmo 8B; tamanhos misturados só no `ovl_mix`.

## Referências neste repositório

| O quê | Onde |
| --- | --- |
| Primeiro teste de sobrecarga (benchmark original) | [2026-10-21 Prism em sobrecarga](2026-10-21%20Prism%20em%20sobrecarga.md) |
| Primeiros cenários de sobrecarga real | [2026-10-21 Sobrecarga real no Prism](2026-10-21%20Sobrecarga%20real%20no%20Prism%20(SGLang%20e%20vLLM).md) (seções do SGLang) |
| Correções de robustez e histórico de mudanças | [2026-10-22 Correções de robustez de memória no Prism](2026-10-22%20Correções%20de%20robustez%20de%20memória%20no%20Prism%20(SGLang).md) |
| Limiares e estratégias de troca, com as correções (150 níveis) | [2026-10-28 Janela de ociosidade e estratégias de troca](2026-10-28%20Janela%20de%20ociosidade%20e%20estratégias%20de%20troca%20no%20Prism,%20com%20as%20correções%20(SGLang).md) |
| Base contra corrigida, erro por erro | [2026-10-28 Limites de carga do Prism base](2026-10-28%20Limites%20de%20carga%20do%20Prism%20base%20e%20correções%20por%20erro%20(SGLang).md) |
| Lista de problemas e situação de cada um | [`erros.md`](../erros.md) |
| Cenários de carga e execução | `polyaxon/run_examples.sh`, `polyaxon/overload_load.py`, `polyaxon/configs/*_suite.tsv`, `polyaxon/submit.sh` |
| Políticas | `python/sglang/multi_model/scheduling/policy/simple_global.py` (`PRISM_EVICTION`, `PRISM_IDLE_THRESHOLD`, `PRISM_ACTIVATION_HEADROOM_GB`) |
| Análise | `polyaxon/collect_reps.py`, `polyaxon/classify_errors.py`, `polyaxon/report_tables.py`, `polyaxon/plot_suite.py`, `polyaxon/plot_limits.py` |
| Dados e figuras | `reports/data/2026-10-28-ociosidade/`, `reports/data/2026-10-28-limites/`, `reports/figs/` |
