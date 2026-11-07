# Referências que apoiam decisões de política e comportamento

Cada entrada: referência, link, o trecho verificado (seção) e por que foi adicionada (qual decisão `D*` ou alternativa
`A*` ela sustenta ou contradiz). Só entra o que foi lido no texto do artigo; resumos de terceiros não bastam. Regra:
toda decisão de política/comportamento busca apoio na literatura de serving multi-modelo / escalonamento por SLO
antes de ser tomada, e cita as entradas daqui em `decisoes.md`.

| id | referência | usada em |
| --- | --- | --- |
| R1 | Prism (OSDI'26) | D45 (contexto); D46 item 3 |
| R2 | Clockwork (OSDI'20) | D45 itens 1–2 |
| R3 | SwapServeLLM (SC Workshops'25) | D45 item 3; A11 |
| R4 | SuperInfer (MLSys'26) | A9 (D4) |
| R5 | MuxServe (ICML'24) | D44 item 2; D46 item 2 |
| R6 | Aegaeon (SOSP'25) | D46 item 3 |
| R7 | Serverless in the Wild (ATC'20) | D46 item 3 |

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
