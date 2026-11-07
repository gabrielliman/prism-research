# Referências que apoiam decisões de política e comportamento

Cada entrada: referência, link, o trecho verificado (seção) e por que foi adicionada (qual decisão `D*` ou alternativa
`A*` ela sustenta ou contradiz). Só entra o que foi lido no texto do artigo; resumos de terceiros não bastam. Regra:
toda decisão de política/comportamento busca apoio na literatura de serving multi-modelo / escalonamento por SLO
antes de ser tomada, e cita as entradas daqui em `decisoes.md`.

| id | referência | usada em |
| --- | --- | --- |
| R1 | Prism (OSDI'26) | D45 (contexto) |
| R2 | Clockwork (OSDI'20) | D45 itens 1–2 |
| R3 | SwapServeLLM (SC Workshops'25) | D45 item 3; A11 |
| R4 | SuperInfer (MLSys'26) | A9 (D4) |

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
