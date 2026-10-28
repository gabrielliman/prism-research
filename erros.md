# Problemas de memória no Prism, kvcached e SGLang, e como lidamos com cada um (2026-10-28)

## Do próprio Prism

| \# | Problema | Efeito | Como lidamos | Situação |
| :---- | :---- | :---- | :---- | :---- |
| 1 | **Contagem dupla de memória livre no controlador.** Ele decidia novas ativações sem descontar as que ainda estavam carregando: 35% das 1.579 ativações foram decididas com outra em andamento, e 22% já não cabiam | Foi a principal causa das mortes de workers: 31 de 42 aconteceram durante a ativação | **R2.1:** o controlador desconta da memória livre os pesos \+ 1 GB de KV de cada ativação pendente, até o GPU scheduler avisar que ela terminou. | Resolvido. Na rodada fix2, já não houve nenhuma morte durante a ativação |
| 2 | **Workers mortos não eram detectados** | O modelo continuava "ativo", e as requisições iam para um processo morto até o fim do prazo | Detecção de workers mortos, inclusive zumbis via `/proc` (`PRISM_DETECT_DEAD_WORKERS`). O GPU scheduler avisa o controlador por Redis (`model_lost`), e o controlador marca o modelo como inativo e o reativa em outro worker | Resolvido, ligado por padrão |
| 3 | **Ativação sem memória falhava em silêncio ou derrubava o servidor** | Modelo preso em "ativando", ou `torch` OOM derrubando tudo | A ativação é desfeita e responde `success=False` (`ActivationOutOfMemory`), e o controlador é avisado | Resolvido; só age quando há falha |
| 4 | **O worker pool entregava um worker morto como livre** (visto no rodízio) | As requisições dos modelos ativados nele falhavam | Coberto pela detecção de mortes (\#2), mais um aviso quando falta worker livre | Resolvido |
| 5 | **Corrida entre desativar e reativar o mesmo modelo.** A confirmação atrasada da desativação antiga chegava depois da reativação | O modelo ficava marcado como inativo e passava fome até o fim: 137 requisições perdidas num `ovl_phases`, 37 no `ovl_mix` | **R2.3:** o GPU scheduler conta as desativações pendentes de cada modelo e ignora a confirmação que foi superada por uma reativação | Resolvido. Foram 97 ocorrências ignoradas nos 139 níveis; conferido num caso real |
| 6 | **Na preempção (RECOMPUTE), as requisições retiradas ficavam na fila local do worker**, e o worker podia ser reaproveitado para outro modelo | Requisições perdidas | Elas voltam para a fila do modelo no Redis e recomeçam do prompt | Resolvido, junto com a troca por throughput |
| 10 | **O model service carrega um modelo por vez**, então uma ativação pode levar até 20 s | A memória "some" durante a ativação | Não mudamos o model service; a R2.1 cobre esse intervalo na conta de memória | Contornado |

## Do kvcached

| \# | Problema | Efeito | Como lidamos | Situação |
| :---- | :---- | :---- | :---- | :---- |
| 1 | **`abort()` quando o driver recusa uma página** (`cuMemCreate`/`cuMemSetAccess` out of memory), na ativação ou quando o KV cresce (falhas 1 e 2\) | O worker morre na hora | O repositório do kvcached não foi alterado. Na configuração padrão, evitamos a situação (R2.1) e detectamos a morte quando ela acontece (detecção de workers mortos). Ajustes aplicados em tempo de execução pelo Prism (`kvcached_patches.py`: a alocação recusada retorna `None`) existem, mas só na variante com o árbitro, que está desligada | Mitigado |

## Do SGLang (mudanças aprovadas na Rodada 2\)

| \# | Problema | Efeito | Como lidamos | Situação |
| :---- | :---- | :---- | :---- | :---- |
| 1 | **Falha 3: falta de KV no prefill** leva a `tree_cache.pretty_print()`, que levanta `NotImplementedError` porque o radix cache está desligado | O worker cai | **R2.2:** nova exceção `PrefillKVFull`. O batch é alocado antes de o estado mudar; se faltar KV, a requisição volta para a fila e o prefill é tentado de novo depois de 50 ms | Resolvido. Zero `pretty_print` depois disso, com 5 prefills adiados nos 139 níveis |
| 2 | **Uma exceção num worker derruba todos** (`kill_parent_process`) | Uma falha local vira queda do servidor | **R2.2:** com o worker pool, só aquele worker sai (`os._exit(1)`), e a detecção de mortes do Prism reativa o modelo | Resolvido |
| 3 | **`torch.OutOfMemoryError` ao copiar os pesos** derrubava o servidor (falha 4\) | Queda total | Desfazer a ativação (Prism) \+ R2.1 | Resolvido |