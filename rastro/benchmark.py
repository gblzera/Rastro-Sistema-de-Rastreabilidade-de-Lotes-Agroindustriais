"""Testes de carga sobre o grafo (pacote 1.5.3 da EAP).

Para cada tamanho de base sintética mede:
- geração e reconstrução do grafo (Kahn) e memória ocupada;
- recall e auditoria de origem sobre lotes sorteados (mediana, p95 e pior caso);
- verificação de aciclicidade: inserções rejeitadas (que fechariam ciclo) e aceitas, comparando
  a ordem topológica dinâmica (Pearce-Kelly) com a busca em profundidade a cada inserção;
- opcionalmente, o mesmo recall feito no banco com CTE recursiva.

Um segundo cenário, a cadeia linear, mostra o pior caso da DFS: cada inserção aceita no fim
da cadeia obriga a busca a percorrer todos os vértices, enquanto a ordem topológica decide
em O(1).
"""

from __future__ import annotations

import csv
import random
import statistics
import time
import tracemalloc
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .grafo import CicloDetectado, EstrategiaCiclo, GrafoRastro, TipoVertice, Vertice
from .sintetico import gerar_base


def _ms(funcao: Callable[[], object]) -> float:
    inicio = time.perf_counter()
    funcao()
    return (time.perf_counter() - inicio) * 1000


def _p95(valores: list[float]) -> float:
    if len(valores) < 2:
        return valores[0] if valores else 0.0
    return statistics.quantiles(valores, n=20, method="inclusive")[-1]


def _carregar(base, estrategia: EstrategiaCiclo) -> GrafoRastro:
    grafo = GrafoRastro(estrategia)
    grafo.carregar(base.vertices, base.arestas)
    return grafo


def medir_tamanho(n_lotes: int, amostras: int, semente: int, url_sql: str | None = None) -> dict:
    rng = random.Random(semente)
    inicio = time.perf_counter()
    base = gerar_base(n_lotes, semente=semente)
    t_geracao = time.perf_counter() - inicio

    tracemalloc.start()
    grafo = _carregar(base, EstrategiaCiclo.ORDEM_TOPOLOGICA)
    memoria = tracemalloc.get_traced_memory()[0] / 2**20
    tracemalloc.stop()
    del grafo
    t_carga = _ms(lambda: _carregar(base, EstrategiaCiclo.ORDEM_TOPOLOGICA))
    pk = _carregar(base, EstrategiaCiclo.ORDEM_TOPOLOGICA)
    dfs = _carregar(base, EstrategiaCiclo.BUSCA_PROFUNDIDADE)

    insumos = [v.id for v in pk.vertices(TipoVertice.INSUMO)]
    produtos = [v.id for v in pk.vertices(TipoVertice.PRODUTO_FINAL)]
    amostra_insumos = rng.sample(insumos, min(amostras, len(insumos)))
    amostra_produtos = rng.sample(produtos, min(amostras, len(produtos)))

    t_recall, tam_recall = [], []
    for lote in amostra_insumos:
        t_recall.append(_ms(lambda: tam_recall.append(pk.recall(lote).total_vertices)))
    t_origem = [_ms(lambda: pk.origem(p)) for p in amostra_produtos]
    pior = max(amostra_insumos, key=lambda lote: pk.recall(lote).total_vertices)

    # Inserções rejeitadas: produto final -> um de seus ancestrais (sempre fecha ciclo)
    pares_ciclo = []
    for p in amostra_produtos:
        ancestrais = [a for a in pk.origem(p).niveis if a != p and pk.vertice(a).tipo is not TipoVertice.INSUMO]
        if ancestrais:
            pares_ciclo.append((p, rng.choice(ancestrais)))
    rejeicao = {}
    for nome, grafo in (("pk", pk), ("dfs", dfs)):
        tempos = []
        for origem, destino in pares_ciclo:
            def tentar(g=grafo, o=origem, d=destino):
                try:
                    g.adicionar_aresta(o, d)
                except CicloDetectado:
                    return
                raise AssertionError(f"aresta {o}->{d} deveria fechar ciclo")
            tempos.append(_ms(tentar))
        rejeicao[nome] = tempos

    # Inserções aceitas: lote qualquer -> intermediário/produto sem caminho de volta
    alvos = [v.id for v in pk.vertices() if v.tipo in (TipoVertice.INTERMEDIARIO, TipoVertice.PRODUTO_FINAL)]
    lotes = [v.id for v in pk.vertices() if v.tipo.eh_lote]
    pares_validos = []
    while len(pares_validos) < min(amostras, 200):
        origem, destino = rng.choice(lotes), rng.choice(alvos)
        if origem != destino and pk.aresta(origem, destino) is None and pk.encontrar_caminho(destino, origem) is None:
            pares_validos.append((origem, destino))
    aceite = {}
    for nome, grafo in (("pk", pk), ("dfs", dfs)):
        tempos = []
        for origem, destino in pares_validos:
            tempos.append(_ms(lambda g=grafo, o=origem, d=destino: g.adicionar_aresta(o, d)))
            grafo.remover_aresta(origem, destino)
        aceite[nome] = tempos

    linha = {
        "lotes": n_lotes,
        "vertices": pk.num_vertices,
        "arestas": pk.num_arestas,
        "geracao_s": round(t_geracao, 2),
        "carga_ms": round(t_carga, 1),
        "memoria_mb": round(memoria, 1),
        "recall_mediana_ms": round(statistics.median(t_recall), 4),
        "recall_p95_ms": round(_p95(t_recall), 4),
        "recall_mediana_vertices": statistics.median(tam_recall),
        "recall_pior_vertices": pk.recall(pior).total_vertices,
        "recall_pior_ms": round(_ms(lambda: pk.recall(pior)), 4),
        "origem_mediana_ms": round(statistics.median(t_origem), 4),
        "origem_p95_ms": round(_p95(t_origem), 4),
        "ciclo_rejeitado_pk_ms": round(statistics.median(rejeicao["pk"]), 4),
        "ciclo_rejeitado_dfs_ms": round(statistics.median(rejeicao["dfs"]), 4),
        "insercao_aceita_pk_ms": round(statistics.median(aceite["pk"]), 4),
        "insercao_aceita_dfs_ms": round(statistics.median(aceite["dfs"]), 4),
    }

    if url_sql:
        from .persistencia import Repositorio, criar_engine

        repo = Repositorio(criar_engine(url_sql))
        repo.apagar_esquema()
        repo.criar_esquema()
        repo.inserir_base(base)
        amostra_sql = amostra_insumos[: min(50, len(amostra_insumos))]
        repo.descendentes_sql(amostra_sql[0])  # aquece conexão e cache
        tempos_sql = []
        for lote in amostra_sql:
            esperado = set(pk.recall(lote).niveis)
            inicio = time.perf_counter()
            obtido = repo.descendentes_sql(lote)
            tempos_sql.append((time.perf_counter() - inicio) * 1000)
            assert obtido == esperado, f"CTE e BFS divergem para {lote}"
        linha["recall_sql_mediana_ms"] = round(statistics.median(tempos_sql), 3)
        linha["recall_sql_banco"] = repo.engine.dialect.name
        repo.engine.dispose()

    return linha


def medir_cadeia_linear(n: int, insercoes: int = 200) -> dict:
    """Pior caso da DFS: uma cadeia v0 -> v1 -> ... -> vn e inserções vi -> vj com i < j."""
    resultado = {"vertices": n}
    rng = random.Random(n)
    pares = []
    while len(pares) < insercoes:
        i, j = sorted(rng.sample(range(n), 2))
        if j - i > 1:
            pares.append((f"c{i}", f"c{j}"))
    for estrategia in EstrategiaCiclo:
        grafo = GrafoRastro(estrategia)
        grafo.adicionar_vertice(Vertice("c0", TipoVertice.INSUMO, "c0"))
        for k in range(1, n):
            grafo.adicionar_vertice(Vertice(f"c{k}", TipoVertice.INTERMEDIARIO, f"c{k}"))
            grafo.adicionar_aresta(f"c{k - 1}", f"c{k}")
        tempos = []
        for origem, destino in pares:
            if grafo.aresta(origem, destino) is None:
                tempos.append(_ms(lambda g=grafo, o=origem, d=destino: g.adicionar_aresta(o, d)))
        resultado[f"{estrategia.value}_ms"] = round(statistics.median(tempos), 4)
    return resultado


def executar(
    tamanhos: list[int],
    amostras: int = 200,
    semente: int = 42,
    url_sql: str | None = None,
    pasta: str = "resultados",
) -> list[dict]:
    print(f"Testes de carga do Rastro — {amostras} amostras por métrica, semente {semente}\n")
    linhas = []
    for n in tamanhos:
        print(f"  medindo base com {n} lotes...", flush=True)
        linhas.append(medir_tamanho(n, amostras, semente, url_sql))

    cadeias = []
    for n in sorted({min(t, 20000) for t in tamanhos}):
        print(f"  medindo cadeia linear com {n} vértices...", flush=True)
        cadeias.append(medir_cadeia_linear(n))

    destino = Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    arquivo = destino / f"benchmark-{carimbo}.csv"
    with arquivo.open("w", newline="", encoding="utf-8") as saida:
        escritor = csv.DictWriter(saida, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)

    print("\n" + tabela_markdown(linhas, cadeias))
    print(f"\nCSV salvo em {arquivo}")
    return linhas


def tabela_markdown(linhas: list[dict], cadeias: list[dict]) -> str:
    sql = "recall_sql_mediana_ms" in linhas[0]
    cab = ["Lotes", "Vértices", "Arestas", "Carga (ms)", "Memória (MB)", "Recall mediana (ms)",
           "Recall p95 (ms)", "Vértices no recall (mediana / pior)", "Origem mediana (ms)"]
    if sql:
        cab.append(f"Recall via CTE no {linhas[0]['recall_sql_banco']} (ms)")
    partes = ["### Consultas e reconstrução", "", "| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    for l in linhas:
        valores = [l["lotes"], l["vertices"], l["arestas"], l["carga_ms"], l["memoria_mb"],
                   l["recall_mediana_ms"], l["recall_p95_ms"],
                   f"{l['recall_mediana_vertices']:g} / {l['recall_pior_vertices']}", l["origem_mediana_ms"]]
        if sql:
            valores.append(l["recall_sql_mediana_ms"])
        partes.append("| " + " | ".join(str(v) for v in valores) + " |")

    partes += ["", "### Verificação de aciclicidade (mediana por inserção, ms)", "",
               "| Lotes | Rejeitada — Pearce-Kelly | Rejeitada — DFS | Aceita — Pearce-Kelly | Aceita — DFS |",
               "|---|---|---|---|---|"]
    for l in linhas:
        partes.append(
            f"| {l['lotes']} | {l['ciclo_rejeitado_pk_ms']} | {l['ciclo_rejeitado_dfs_ms']} | "
            f"{l['insercao_aceita_pk_ms']} | {l['insercao_aceita_dfs_ms']} |"
        )
    partes += ["", "### Pior caso da DFS: cadeia linear (inserção aceita, mediana em ms)", "",
               "| Vértices | Pearce-Kelly | DFS |", "|---|---|---|"]
    for c in cadeias:
        partes.append(f"| {c['vertices']} | {c['ordem_topologica_ms']} | {c['busca_profundidade_ms']} |")
    return "\n".join(partes)
