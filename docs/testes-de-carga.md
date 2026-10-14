# Testes de carga

Pacote 1.5.3 da EAP. Para reproduzir:

```bash
python -m rastro benchmark --tamanhos 1000,10000,50000,100000 --amostras 200 \
  --sql postgresql://rastro:rastro@localhost/rastro_bench
```

O comando gera bases sintéticas de porte crescente (semente 42), mede cada operação sobre 200 lotes sorteados e grava um CSV em `resultados/`. A opção `--sql` repete o recall no banco com CTE recursiva e confere se o resultado é igual ao da BFS.

Ambiente da execução abaixo (14/10/2026): Intel Xeon 2,8 GHz, 4 núcleos, Python 3.13, PostgreSQL 16 local.

## Consultas e reconstrução

| Lotes | Vértices | Arestas | Carga (ms) | Memória (MB) | Recall mediana (ms) | Recall p95 (ms) | Vértices no recall (mediana / pior) | Origem mediana (ms) | Recall via CTE no PostgreSQL (ms) |
|---|---|---|---|---|---|---|---|---|---|
| 1 000 | 1 012 | 2 231 | 3,5 | 0,4 | 0,0056 | 0,0163 | 8,5 / 36 | 0,0056 | 1,721 |
| 10 000 | 10 012 | 22 482 | 50,2 | 4,2 | 0,0107 | 0,0284 | 10 / 30 | 0,0101 | 1,000 |
| 50 000 | 50 012 | 112 595 | 472,7 | 24,3 | 0,0136 | 0,0389 | 9,5 / 34 | 0,0157 | 0,967 |
| 100 000 | 100 012 | 224 882 | 801,0 | 48,5 | 0,0136 | 0,0405 | 10 / 34 | 0,0166 | 1,297 |

- **Carga** é a reconstrução completa do grafo (inserção de vértices e arestas + validação por Kahn). Cresce linearmente, como esperado de O(V + E), e fica abaixo de 1 s com 100 mil lotes.
- **Recall e origem** custam O(V' + E') no subgrafo alcançado, não no grafo inteiro. Como um lote real afeta uma parte limitada da produção, o tempo fica na casa de 10 µs em todas as escalas.
- **CTE recursiva**: a mesma consulta feita no PostgreSQL leva de 1 a 1,7 ms, entre 70 e 300 vezes mais do que a BFS em memória, embora use os índices da edge list. A diferença vem de planejamento, ida e volta ao banco e execução iterativa da recursão. As estatísticas do banco pesam muito: medida logo após a carga em massa, antes de o PostgreSQL coletar estatísticas, a CTE levou 93 ms com 100 mil lotes; depois de `ANALYZE`, o plano usa o índice da chave primária (`Index Only Scan using arestas_pkey`) e cai para cerca de 1 ms. Por isso a carga em massa termina com `ANALYZE`.

## Verificação de aciclicidade (mediana por inserção, ms)

| Lotes | Rejeitada — Pearce-Kelly | Rejeitada — DFS | Aceita — Pearce-Kelly | Aceita — DFS |
|---|---|---|---|---|
| 1 000 | 0,0026 | 0,0026 | 0,0022 | 0,0030 |
| 10 000 | 0,0046 | 0,0037 | 0,0038 | 0,0051 |
| 50 000 | 0,0064 | 0,0047 | 0,0049 | 0,0064 |
| 100 000 | 0,0063 | 0,0051 | 0,0071 | 0,0076 |

"Rejeitada" tenta ligar um produto final a um de seus próprios ingredientes. "Aceita" liga pares sorteados de lotes que não formam ciclo. Na base agroindustrial a cadeia é rasa (até 4 elos), então as duas estratégias ficam na casa dos microssegundos.

## Pior caso da DFS: cadeia linear

| Vértices | Pearce-Kelly | DFS |
|---|---|---|
| 1 000 | 0,0022 | 0,0709 |
| 10 000 | 0,0035 | 1,1103 |
| 20 000 | 0,0039 | 2,4787 |

Numa cadeia v0 → v1 → … → vn, inserir vi → vj (i < j) é sempre válido, mas a DFS precisa percorrer tudo o que é alcançável a partir de vj para ter certeza. A ordem topológica dinâmica decide em O(1) porque `ord(vi) < ord(vj)`. A diferença cresce com o tamanho e chega a cerca de 600 vezes com 20 mil vértices. É por isso que ela é a estratégia padrão do motor.
