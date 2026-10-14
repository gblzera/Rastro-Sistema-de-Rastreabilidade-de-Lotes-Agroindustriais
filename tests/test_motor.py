import random

import pytest

from rastro.grafo import (
    ArestaDuplicada,
    CicloDetectado,
    ErroGrafo,
    EstrategiaCiclo,
    GrafoRastro,
    RegraViolada,
    TipoAresta,
    TipoVertice,
    Vertice,
    VerticeDuplicado,
    VerticeInexistente,
)

ESTRATEGIAS = list(EstrategiaCiclo)

INS, INT, PRD, DST = (
    TipoVertice.INSUMO,
    TipoVertice.INTERMEDIARIO,
    TipoVertice.PRODUTO_FINAL,
    TipoVertice.DESTINO,
)


def v(vid, tipo):
    return Vertice(vid, tipo, vid)


@pytest.fixture(params=ESTRATEGIAS, ids=lambda e: e.value)
def grafo(request):
    """Leite cru -> leite pasteurizado -> queijo (+ sal) -> mercado / restaurante."""
    g = GrafoRastro(request.param)
    for vid, tipo in [
        ("leite", INS), ("sal", INS), ("pasteurizado", INT),
        ("queijo", PRD), ("iogurte", PRD), ("mercado", DST), ("restaurante", DST),
    ]:
        g.adicionar_vertice(v(vid, tipo))
    g.adicionar_aresta("leite", "pasteurizado")
    g.adicionar_aresta("pasteurizado", "queijo")
    g.adicionar_aresta("sal", "queijo")
    g.adicionar_aresta("pasteurizado", "iogurte")
    g.adicionar_aresta("queijo", "mercado")
    g.adicionar_aresta("iogurte", "restaurante")
    return g


def test_tipo_da_aresta_e_inferido(grafo):
    assert grafo.aresta("leite", "pasteurizado").tipo is TipoAresta.COMPOSICAO
    assert grafo.aresta("queijo", "mercado").tipo is TipoAresta.EXPEDICAO
    assert grafo.num_arestas == 6


def test_recall_alcanca_todos_os_produtos_e_destinos(grafo):
    r = grafo.recall("leite")
    assert r.niveis == {
        "leite": 0, "pasteurizado": 1, "queijo": 2, "iogurte": 2, "mercado": 3, "restaurante": 3,
    }
    assert set(r.por_tipo[PRD]) == {"queijo", "iogurte"}
    assert set(r.por_tipo[DST]) == {"mercado", "restaurante"}
    assert "sal" not in r
    assert r.profundidade == 3
    assert len(r.arestas) == 5


def test_recall_de_insumo_compartilhado_e_restrito(grafo):
    r = grafo.recall("sal")
    assert set(r.niveis) == {"sal", "queijo", "mercado"}


def test_origem_reconstroi_a_cadeia(grafo):
    r = grafo.origem("mercado")
    assert set(r.niveis) == {"mercado", "queijo", "pasteurizado", "sal", "leite"}
    assert set(r.por_tipo[INS]) == {"leite", "sal"}
    assert r.direcao == "ascendente"


def test_insercao_que_fecharia_ciclo_e_rejeitada_com_o_caminho(grafo):
    grafo.adicionar_vertice(v("soro", INT))
    grafo.adicionar_aresta("queijo", "soro")
    with pytest.raises(CicloDetectado) as erro:
        grafo.adicionar_aresta("soro", "pasteurizado")
    assert erro.value.ciclo == ["soro", "pasteurizado", "queijo", "soro"]
    # nada mudou
    assert grafo.aresta("soro", "pasteurizado") is None
    assert grafo.num_arestas == 7


def test_laco_e_ciclo(grafo):
    with pytest.raises(CicloDetectado) as erro:
        grafo.adicionar_aresta("pasteurizado", "pasteurizado")
    assert erro.value.ciclo == ["pasteurizado", "pasteurizado"]


@pytest.mark.parametrize(
    ("origem", "destino", "tipo", "erro"),
    [
        ("mercado", "queijo", None, RegraViolada),  # destino não origina arestas
        ("pasteurizado", "sal", None, RegraViolada),  # insumo não é produzido
        ("queijo", "restaurante", TipoAresta.COMPOSICAO, RegraViolada),
        ("leite", "queijo", TipoAresta.EXPEDICAO, RegraViolada),
        ("leite", "pasteurizado", None, ArestaDuplicada),
        ("leite", "fantasma", None, VerticeInexistente),
    ],
)
def test_regras_de_dominio(grafo, origem, destino, tipo, erro):
    with pytest.raises(erro):
        grafo.adicionar_aresta(origem, destino, tipo=tipo)


def test_vertice_duplicado(grafo):
    with pytest.raises(VerticeDuplicado):
        grafo.adicionar_vertice(v("leite", INS))


def test_remover_aresta_e_vertice(grafo):
    grafo.remover_aresta("sal", "queijo")
    assert grafo.recall("sal").total_vertices == 1
    grafo.remover_vertice("pasteurizado")
    assert "pasteurizado" not in grafo
    assert grafo.sucessores("leite") == []
    assert grafo.num_arestas == 2
    with pytest.raises(ErroGrafo):
        grafo.remover_aresta("leite", "pasteurizado")


def test_ordem_topologica_e_profundidade(grafo):
    ordem = grafo.ordem_topologica()
    posicao = {vid: i for i, vid in enumerate(ordem)}
    assert all(posicao[a.origem] < posicao[a.destino] for a in grafo.arestas())
    assert grafo.profundidade_maxima() == 3


def test_vizinhanca_ignora_sentido(grafo):
    assert grafo.vizinhanca("queijo", raio=1) == {"queijo", "pasteurizado", "sal", "mercado"}
    assert "leite" in grafo.vizinhanca("queijo", raio=2)


def test_estatisticas(grafo):
    e = grafo.estatisticas()
    assert e["vertices"] == 7
    assert e["arestas_por_tipo"] == {"composicao": 4, "expedicao": 2}
    assert e["fontes"] == 2
    assert e["sumidouros"] == 2


@pytest.mark.parametrize("estrategia", ESTRATEGIAS, ids=lambda e: e.value)
def test_carregar_detecta_ciclo_e_deixa_grafo_vazio(estrategia):
    g = GrafoRastro(estrategia)
    vertices = [v("a", INT), v("b", INT), v("c", INT), v("d", INT)]
    from rastro.grafo import Aresta

    arestas = [
        Aresta("a", "b", TipoAresta.COMPOSICAO),
        Aresta("b", "c", TipoAresta.COMPOSICAO),
        Aresta("c", "a", TipoAresta.COMPOSICAO),
        Aresta("c", "d", TipoAresta.COMPOSICAO),
    ]
    with pytest.raises(CicloDetectado) as erro:
        g.carregar(vertices, arestas)
    ciclo = erro.value.ciclo
    assert ciclo[0] == ciclo[-1]
    assert set(ciclo) == {"a", "b", "c"}
    assert len(g) == 0 and g.num_arestas == 0


def test_carregar_inicializa_ordem_dinamica():
    from rastro.grafo import Aresta

    g = GrafoRastro()
    # vértices fora de ordem topológica na lista de entrada
    g.carregar(
        [v("c", PRD), v("b", INT), v("a", INS)],
        [Aresta("a", "b", TipoAresta.COMPOSICAO), Aresta("b", "c", TipoAresta.COMPOSICAO)],
    )
    assert g.indice_topologico("a") < g.indice_topologico("b") < g.indice_topologico("c")
    with pytest.raises(CicloDetectado):
        g.adicionar_aresta("c", "b")


def _alcanca(adj, origem, destino):
    pilha, vistos = [origem], {origem}
    while pilha:
        atual = pilha.pop()
        if atual == destino:
            return True
        for w in adj.get(atual, ()):
            if w not in vistos:
                vistos.add(w)
                pilha.append(w)
    return False


@pytest.mark.parametrize("semente", range(15))
def test_estrategias_concordam_com_forca_bruta(semente):
    """Inserções aleatórias: as duas estratégias aceitam/rejeitam exatamente as mesmas arestas,
    e a ordem mantida pelo Pearce-Kelly continua sendo uma ordem topológica válida."""
    rng = random.Random(semente)
    n = 40
    grafos = [GrafoRastro(e) for e in ESTRATEGIAS]
    for g in grafos:
        for i in range(n):
            g.adicionar_vertice(v(f"v{i}", INT))
    adj: dict[str, set[str]] = {}
    for _ in range(400):
        a, b = f"v{rng.randrange(n)}", f"v{rng.randrange(n)}"
        if a == b or b in adj.get(a, ()):
            continue
        esperado_ciclo = _alcanca(adj, b, a)
        for g in grafos:
            if esperado_ciclo:
                with pytest.raises(CicloDetectado) as erro:
                    g.adicionar_aresta(a, b)
                ciclo = erro.value.ciclo
                assert ciclo[0] == ciclo[-1] == a and ciclo[1] == b
                # o ciclo devolvido usa arestas que existem de fato
                assert all(nxt in adj.get(cur, ()) for cur, nxt in zip(ciclo[1:], ciclo[2:]))
            else:
                g.adicionar_aresta(a, b)
        if not esperado_ciclo:
            adj.setdefault(a, set()).add(b)

    pk = grafos[0]
    assert pk.estrategia is EstrategiaCiclo.ORDEM_TOPOLOGICA
    indices = [pk.indice_topologico(f"v{i}") for i in range(n)]
    assert len(set(indices)) == n
    assert all(pk.indice_topologico(a.origem) < pk.indice_topologico(a.destino) for a in pk.arestas())
    assert sorted(map(str, grafos[0].arestas())) == sorted(map(str, grafos[1].arestas()))
