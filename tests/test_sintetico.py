from collections import Counter

from rastro.grafo import GrafoRastro, TipoAresta, TipoVertice
from rastro.sintetico import RECEITAS, gerar_base, ordenar_receitas


def _assinatura(base):
    return [v.id for v in base.vertices], [(a.origem, a.destino) for a in base.arestas]


def test_base_e_reproduzivel_pela_semente():
    assert _assinatura(gerar_base(200, semente=7)) == _assinatura(gerar_base(200, semente=7))
    assert _assinatura(gerar_base(200, semente=7)) != _assinatura(gerar_base(200, semente=8))


def test_quantidade_de_lotes_e_destinos():
    base = gerar_base(n_lotes=250, n_destinos=20)
    tipos = Counter(v.tipo for v in base.vertices)
    assert base.num_lotes == 250
    assert tipos[TipoVertice.DESTINO] == 20


def test_base_carrega_como_dag_valido():
    base = gerar_base(n_lotes=1500)
    g = GrafoRastro()
    g.carregar(base.vertices, base.arestas)  # valida regras e aciclicidade
    assert g.num_arestas == len(base.arestas)
    for vertice in g.vertices():
        if vertice.tipo in (TipoVertice.INTERMEDIARIO, TipoVertice.PRODUTO_FINAL):
            assert g.grau_entrada(vertice.id) >= 1, vertice.id
        if vertice.tipo is TipoVertice.PRODUTO_FINAL:
            assert any(a.tipo is TipoAresta.EXPEDICAO for a in g.arestas_saida(vertice.id))


def test_cada_aresta_pertence_a_um_evento():
    base = gerar_base(n_lotes=300)
    ids_eventos = {e.id for e in base.eventos}
    assert all(a.evento_id in ids_eventos for a in base.arestas)
    assert all(v.evento_id in ids_eventos for v in base.vertices)


def test_receitas_ordenadas_por_dependencia():
    ordem = [r.produto for r in ordenar_receitas()]
    for receita in RECEITAS:
        for entrada in receita.entradas:
            if entrada in ordem:
                assert ordem.index(entrada) < ordem.index(receita.produto)
