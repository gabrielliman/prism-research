# Referências que apoiam decisões de política e comportamento

Cada entrada: referência, link, o trecho verificado (seção) e por que foi adicionada (qual decisão `D*` ou alternativa
`A*` ela sustenta ou contradiz). Só entra o que foi lido no texto do artigo; resumos de terceiros não bastam. Regra:
toda decisão de política/comportamento busca apoio na literatura de serving multi-modelo / escalonamento por SLO
antes de ser tomada, e cita as entradas daqui em `decisoes.md`.

| id | referência | usada em |
| --- | --- | --- |
| R1 | Prism (OSDI'26) | D45 (contexto); D46 item 3 |
| R2 | Clockwork (OSDI'20) | D45 itens 1–2; A9.2 (prioridade de carga) |
| R3 | SwapServeLLM (SC Workshops'25) | D45 item 3; A11 |
| R4 | SuperInfer (MLSys'26) | A9 (D4) |
| R5 | MuxServe (ICML'24) | D44 item 2; D46 item 2 |
| R6 | Aegaeon (SOSP'25) | D46 item 3; desenho da F6.0 (hipótese do S3, D49) |
| R7 | Serverless in the Wild (ATC'20) | D46 item 3; desenho da F6.16: A2.3 |
| R8 | GreedyDual-Size (USITS'97) | A9.2 (vítima pelo custo de voltar por GB) |
| R9 | QLM (SoCC'24) | desenho da F6.16: A3.1, A10.1 (troca e despejo guiados pela estimativa de espera contra o SLO) |
| R10 | Shepherd (NSDI'23) | desenho da F6.16: A9.4 (preemptar só se o ganho for λ vezes a perda) |

## R1 — Prism: Unleashing GPU Sharing for Cost-Efficient Multi-LLM Serving

Yu, Xing et al., OSDI 2026. arXiv 2505.04021 (v3): <https://arxiv.org/abs/2505.04021>

- **Verificado (v3, lido até ~75% do texto):** §6.1 reativa um modelo despejado "imediatamente" ao chegar requisição, na
  GPU de menor pressão de KV; despejo por ociosidade e pressão de recursos com limiar empírico. §6.1 (migração): "keeps
  the source instance active and continues serving requests until the target is ready". O artigo **não** descreve
  estados de transição (ativando/desativando) nem reserva de memória para o modelo que entra.
- **Por que foi adicionada:** é o sistema que estudamos. Mostra que o desenho publicado deixa implícito o intervalo entre
  decisão e carga/saída (lacuna que a D45 torna explícita) e que, na migração, o próprio Prism já espera um evento
  ("target is ready") em vez de um tempo fixo — o mesmo princípio que a D45 aplica à reserva de troca.

## R2 — Serving DNNs like Clockwork: Performance Predictability from the Bottom Up

Gujarati et al., OSDI 2020, pp. 443–462. <https://arxiv.org/abs/2006.02464>

- **Verificado:** §4.4: os workers expõem ações `LOAD`/`UNLOAD` ao controlador e "these actions also update the state
  that the controller tracks for the worker"; cada ação leva uma janela `earliest`/`latest` e é cancelada se não começar
  nela; os workers devolvem o resultado de cada ação (sucesso e tempo medido). §4.5: o controlador "tracks the
  outstanding actions and memory state at every worker" e só envia `INFER` quando o modelo está na GPU ou um `LOAD`
  vai terminar.
- **Por que foi adicionada:** sustenta a D45 itens 1–2 — o controlador central mantém o estado explícito de cada
  carga/descarga em andamento, atualizado pelo resultado reportado pelo worker (nossos eventos `model_activated` /
  `model_deactivated`), e prazos servem só como limite de segurança de uma ação (nosso `LIFECYCLE_TIMEOUT_S`), não como
  forma de inferir que ela terminou.

### R2 — adendo (2026-11-09, A9.2)

- **Verificado (PDF, §5.3, "Action scheduler"/LOAD):** a prioridade de carga de um modelo estima o trabalho não
  atendido, `p_m = d_m − Σ_g a_{m,g}·capacity_g/l_g` (`d_m` = tempo estimado das requisições pendentes); "a model that
  is not loaded on any GPUs has priority equal to its outstanding work; a model loaded on a GPU that sits mostly idle
  has negative priority"; a prioridade é atualizada, entre outros momentos, "when a request crosses the point where it
  can benefit from LOAD before its deadline"; "Clockwork uses a least-recently-used (LRU) eviction policy when
  selecting models to UNLOAD".
- **Por que foi adicionada:** sustenta o ganho `G_m` da A9.2 — ativos e inativos medidos pela mesma demanda, e só a
  demanda que ainda se beneficia depois da carga conta. A despejo do Clockwork é LRU, o mesmo defeito da A9.1 (vítima
  pelo tempo ativo); lá as cargas levam milissegundos, aqui 6–16 s, por isso a A9.2 pesa o custo da vítima (R8).

## R3 — Engine-Agnostic Model Hot-Swapping for Cost-Effective LLM Inference (SwapServeLLM)

Stoyanov, Spišaková et al., SC Workshops '25, pp. 114–125. DOI 10.1145/3731599.3767354.
<https://ora.ox.ac.uk/objects/uuid:f15d8679-07b3-467d-b27d-01e112c7b4b1>

- **Verificado:** §3.3–3.4: ao chegar requisição para um modelo parado, o scheduler pede ao task manager uma **reserva
  de memória**; o task manager mantém as reservas numa fila de prioridade e a reserva só é **concedida quando a memória
  fica de fato livre** depois dos swap-outs. §3.5: se a memória não basta, a política de preempção (fila mais curta,
  depois LRU) escolhe vítimas; após cada swap-out verifica a memória e concede a reserva quando ela basta, ou despeja a
  próxima vítima. Cada vítima é bloqueada para escrita durante o swap-out: nenhuma requisição nova vai para ela.
- **Por que foi adicionada:** sustenta a D45 item 3 — a reserva do modelo que entra dura até o evento (memória liberada
  / modelo ativado), não um tempo fixo. Também é relevante para a A11: o SwapServeLLM não reativa nem cancela uma vítima
  em saída (bloqueia novas requisições para ela durante o swap-out); é uma terceira alternativa a comparar com o
  comportamento atual (reativar noutro worker) e com o cancelamento.

## R4 — SuperInfer: SLO-Aware Rotary Scheduling and Memory Management for LLM Inference on Superchips

Yu et al., MLSys 2026 (`SuperInfer.pdf`).

- **Por que foi adicionada:** origem do Virtual Lag Time usado na A9 (incluída pelo Gabriel, D4); também inspira o limite
  de rotações em voo. Já citada no `PLANO_AGENTE.md` (A9); não reverificada nesta entrada.

## R5 — MuxServe: Flexible Spatial-Temporal Multiplexing for Multiple LLM Serving

Duan, Lu et al., ICML 2024 (PMLR 235). arXiv 2404.02015: <https://arxiv.org/abs/2404.02015>

- **Verificado (PDF do arXiv, 13 páginas, §3.1–3.3 lidas):** §3.2 e Algoritmo 2: para cada LLM, o MuxServe varia o
  número de SMs e escolhe a configuração que "meets the workload requirements while utilizing the fewest number of
  SMs" (`estimate_throughput(m, num_sm, p)` com `tpt ≥ W_m`, `W_m` = taxa de requisições do modelo). Os modelos com
  maior "computation requirement, which considers both the model scale and popularity" são colocados primeiro. §3.3:
  a medida de recurso de cada LLM é "normalized by request rates".
- **Por que foi adicionada:** sustenta a D44 item 2 (proposta do agente). A demanda de computação de um modelo é a
  fração da GPU de que a vazão **com lote** precisa para dar conta da taxa dele, não taxa × latência de cada
  requisição. Na nossa medida, isso é `λ_m` × segundos de GPU ocupada por requisição na GPU dedicada
  (`pool_gpu_s_por_req`), que já leva o lote em conta, e não `λ_m` × latência média (`pool_servico_medio_s`), que conta
  cada requisição de um lote como uma GPU inteira. Ressalva: o MuxServe mede pela vazão estimada por perfil de SMs; nós
  medimos pela utilização do `nvidia-smi`, que é mais grosseira (conta a GPU como ocupada se qualquer kernel roda).

### R1 — adendo (2026-11-07, métricas de ociosidade, D46 item 3)

- **Verificado (v3, §1 e §3.1–3.2):** no trace da Novita AI os modelos ficam "idle for over 70% of the time" e o
  compartilhamento espacial deixa "50% of GPU memory occupied but unused"; §3.2: muitos modelos com CV da taxa acima de
  1 e "40–100 idle intervals per hour".
- **Uso:** `ocio_por_modelo` (`polyaxon/gpu_idle.py`) é a fração do tempo sem requisição por modelo, a estatística do
  §3.1; `ocio_residente_total` / `ocio_residente_demanda` medem a memória "occupied but unused" por modelos parados.

## R6 — Aegaeon: Effective GPU Pooling for Concurrent LLM Serving on the Market

Xiang et al. (Alibaba Group e Universidade de Pequim), SOSP 2025. PDF: <https://ennanzhai.github.io/pub/sosp25-aegaeon.pdf>

- **Verificado (PDF, §1, §3.1, Apêndice A.1, §8):** §3.1 define o "active model count" `m`, "the number of models that
  have at least one request being served at a given time", e mostra (Teorema 3.1, prova no A.1) que, com chegadas de
  Poisson de taxa `λ` por modelo e tempo médio de serviço `T`, `E[m] = M·(1 − e^(−λT))`. Com `λ` = 0,037 e `T` = 16,79 s,
  46,55 de 100 modelos estão ativos em média, e um sistema que troca modelos por requisição precisa de ~`E[m]` GPUs
  reservadas; reservar menos causa bloqueio na cabeça da fila ("head-of-line blocking"). §8 reporta a utilização da
  GPU antes e depois da implantação (13,3–33,9% → 48,1%).
- **Por que foi adicionada:** dá a métrica `modelos_ativos_medio` (observado) contra `modelos_ativos_esperado`
  (`Σ_m (1 − e^(−λ_m T_m))`, a fórmula com taxa por modelo) e `modelos_residentes_medio`: quando cabem menos modelos do
  que os ativos, alguém espera troca. Mede o tamanho da sobrecarga de memória por política, ao lado do `ρ_mem`.

### R6 — adendo (2026-11-09, preempção com prazo curto; desenho da F6.0, hipótese do S3 da D49)

- **Verificado (PDF, §2 "Head-of-line blocking" e "Our approach", §4, §5):** trocar de modelo só na granularidade da
  requisição faz as requisições de outros modelos esperarem o fim das que estão rodando ("severe head-of-line (HOL)
  blocking ... prohibitively long TTFT and SLO violations for the waiting models"); a solução do Aegaeon "mitigates HOL
  blocking by preemptively scaling down active models and scaling up pending models". Mas isso só compensa com a troca
  barata: o §5 reduz o custo da troca em 97% (reuso de componentes, KV movido para a CPU em paralelo, sem recomputar),
  e o §4 agrupa prefills do mesmo modelo para evitar "excessive preemptive auto-scaling" sob carga alta.
- **Por que foi adicionada:** apoia a hipótese do Gabriel (D49) de que um prazo de TTFT menor que uma troca sem
  preempção (S3 `k_A` = 5) só é alcançável preemptando, e ao mesmo tempo mostra a condição que nós não temos: aqui a
  preempção recomputa o que estava rodando e a troca leva 13–17 s (F5.0a). Por isso a F6.0 mede a diferença com e sem
  preempção em cada nível de SLO, em vez de assumir o sinal; a F5 já mostrou a troca por throughput com preempção
  (A0.4p) pior que sem (A0.4) em todos os níveis.

## R7 — Serverless in the Wild: Characterizing and Optimizing the Serverless Workload at a Large Cloud Provider

Shahrad et al., USENIX ATC 2020. arXiv 2003.03423: <https://arxiv.org/abs/2003.03423>

- **Verificado (PDF, §5.1 e Figura 15):** o simulador soma o "wasted memory time for the application, i.e. the time
  when the application's image was kept in memory without actually executing any functions"; as políticas de
  keep-alive são comparadas numa curva de Pareto entre partidas a frio ("cold starts") e tempo de memória desperdiçada
  (Fig. 15).
- **Por que foi adicionada:** `ocio_residente_total` é esse tempo de memória desperdiçada (GB·s de modelos carregados
  sem requisição, sobre os GB·s da GPU), e a forma de comparar políticas sugerida é a mesma: SLO ou trocas por minuto
  contra memória desperdiçada, por política (o limiar de ociosidade da A0.1/A0.2 é um keep-alive fixo). Diferença: no
  FaaS a memória ociosa custa dinheiro; aqui ela custa SLO de quem espera, por isso `ocio_residente_demanda` (só
  quando há fila) continua como a métrica principal.

### R7 — adendo (2026-11-10, A2.3)

- **Verificado (PDF, §4.2 "Hybrid Histogram Policy"):** por aplicação, um histograma dos tempos ociosos (ITs) entre
  invocações; "We use the head to select the pre-warming window for the application, and the tail to select the
  keep-alive window", com cabeça e cauda "by default [at] the 5th- and 99th-percentiles of the IT distribution" e "a 10%
  'margin'"; quando o histograma não é representativo (poucos ITs ou comportamento mudando), volta a um keep-alive
  padrão; previsão por série temporal (ARIMA) quando a maioria dos ITs cai fora do histograma.
- **Por que foi adicionada:** sustenta a A2.3 (residência preditiva): decidir quanto manter um modelo carregado pelo
  padrão de chegadas do próprio modelo, e não por um limiar fixo (os 10 s da A0.2). Diferença: lá a carga é barata e a
  memória sobra; aqui a decisão só importa sob disputa de memória, por isso a A2.3 entra no custo de despejo, não como
  pré-aquecimento.

## R8 — Cost-Aware WWW Proxy Caching Algorithms (GreedyDual-Size)

Cao e Irani, USENIX USITS 1997, pp. 193–206.
<https://www.usenix.org/publications/library/proceedings/usits97/full_papers/cao/cao_html/node8.html>

- **Verificado (seção 4, "GreedyDual-Size Algorithm", e a Figura 5):** o GreedyDual original dá a cada página `H` =
  "the cost of bringing the page into the cache", despeja a de menor `H` e restaura `H` num acesso; o GreedyDual-Size
  usa `H = L + c(p)/s(p)` (custo por tamanho) e despeja a de menor `H`, com `L` subindo para o `H` despejado.
- **Por que foi adicionada:** sustenta a escolha de vítima da A9.2: despejar primeiro o modelo cujo retorno custa
  menos por GB liberado (`K_v / GB`); um modelo sem nada para fazer custa 0 e sai primeiro. Diferença declarada: não
  usamos o envelhecimento `L`, porque `K_v` já cresce com o atraso das requisições do modelo.

## R9 — Queue Management for SLO-Oriented Large Language Model Serving (QLM)

Patke et al., ACM SoCC 2024. <https://arxiv.org/abs/2407.00047> (versão HTML v2 lida).

- **Verificado (§2.4, §3.1, §5, §6, §7):** um estimador de espera (RWT) estima "the waiting time ... by dividing the total
  number of output tokens for the pending requests" e um limite superior do tempo de conclusão; "Request eviction is
  invoked when the RWT estimator detects an SLO violation" e as requisições em execução voltam à fila global (o KV vai
  para a CPU); grupos de requisições do mesmo modelo e SLO numa fila virtual por instância, reordenados por um programa
  linear para maximizar o SLO, com penalidade "the difference between the waiting time and the SLO value"; o modelo da
  cabeça da fila fica na GPU e o custo de troca entra como "swap times associated with transferring model weights into
  GPU memory". Não há regra explícita de quando trocar além da ordem da fila.
- **Por que foi adicionada:** apoia A3.1 e A10.1: decidir troca e despejo pela espera estimada contra o prazo de cada
  requisição, contando o custo real da troca. Diferença: o QLM ordena grupos por um LP; nós usamos regras gulosas por
  ciclo (5 s) com o custo medido da troca.

## R10 — SHEPHERD: Serving DNNs in the Wild

Zhang, Tang, Khandelwal e Stoica, USENIX NSDI 2023, pp. 787–808. <https://www.usenix.org/conference/nsdi23/presentation/zhang-hong>

- **Verificado (PDF, §3.1, §5, Theorem 5.1, Theorem 5.2):** "preempting a scheduled batch requires carefully weighing the
  utility brought by the scheduled batch of requests against the utility of the new batch"; regra do FLEX: "If the
  generated batch is λ times larger than currently running batch, the current batch is preempted"; as requisições
  preemptadas que ainda cumprem o SLO voltam à fila; "the preempted work does not contribute to system goodput"; o λ
  ótimo para a razão competitiva é "λ ≈ 3.03"; Theorem 5.1: nenhum algoritmo determinístico sem preempção tem razão
  competitiva constante.
- **Por que foi adicionada:** sustenta a regra de preemptar por troca da A9.4: preemptar só quando o que se salva com a
  preempção é λ vezes o que se perde (as requisições em execução da vítima, que recomeçam do prompt), com λ = 3 como
  padrão.
