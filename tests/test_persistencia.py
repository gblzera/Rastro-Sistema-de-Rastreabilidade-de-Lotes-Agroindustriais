import random

import pytest

from rastro.grafo import TipoVertice
from rastro.persistencia import Repositorio, criar_engine, url_do_banco
from rastro.servico import EntradaProducao, ServicoRastro
from rastro.sintetico import gerar_base


def _arestas(grafo):
    return sorted((a.origem, a.destino, a.tipo.value) for a in grafo.arestas())


def test_carga_em_massa_e_reconstrucao(repo):
    from rastro.grafo import GrafoRastro

    base = gerar_base(800, semente=3)
    repo.inserir_base(base)
    esperado = GrafoRastro()
    esperado.carregar(base.vertices, base.arestas)

    grafo = repo.carregar_grafo()
    assert grafo.num_vertices == esperado.num_vertices
    assert _arestas(grafo) == _arestas(esperado)
    leite = next(v for v in grafo.vertices() if v.nome == "Leite cru")
    assert leite.atributos["fornecedor"]
    assert leite.criado_em.tzinfo is not None

    with pytest.raises(RuntimeError):
        repo.inserir_base(base)


def test_cte_recursiva_concorda_com_bfs_em_memoria(repo):
    repo.inserir_base(gerar_base(600, semente=5))
    grafo = repo.carregar_grafo()
    rng = random.Random(1)
    ids = [v.id for v in grafo.vertices()]
    for vid in rng.sample(ids, 25):
        assert repo.descendentes_sql(vid) == set(grafo.recall(vid).niveis)
        assert repo.ascendentes_sql(vid) == set(grafo.origem(vid).niveis)


def test_sequencia_de_eventos_continua_apos_carga(servico):
    servico.repo.inserir_base(gerar_base(50))
    servico.iniciar()
    maior = max(ev["id"] for ev in servico.repo.listar_eventos(500))
    novo = servico.cadastrar(tipo=TipoVertice.INSUMO, nome="Leite cru")
    assert novo.evento_id == maior + 1


def test_falha_no_commit_desfaz_alteracoes_em_memoria(servico, monkeypatch):
    leite = servico.cadastrar(tipo=TipoVertice.INSUMO, nome="Leite cru")
    antes = (servico.grafo.num_vertices, servico.grafo.num_arestas)

    def falhar(*_args, **_kwargs):
        raise RuntimeError("banco indisponível")

    monkeypatch.setattr(servico.repo, "inserir_aresta", falhar)
    with pytest.raises(RuntimeError):
        servico.registrar_producao(
            entradas=[EntradaProducao(leite.id)], tipo=TipoVertice.INTERMEDIARIO, nome="Leite pasteurizado"
        )
    assert (servico.grafo.num_vertices, servico.grafo.num_arestas) == antes
    monkeypatch.undo()
    servico.iniciar()
    assert (servico.grafo.num_vertices, servico.grafo.num_arestas) == antes


def test_migracao_entre_bancos(repo, tmp_path):
    repo.inserir_base(gerar_base(200, semente=9))
    destino = Repositorio(criar_engine(f"sqlite:///{tmp_path / 'destino.db'}"))
    contagem = repo.copiar_para(destino)
    assert contagem["vertices"] == 212
    assert _arestas(destino.carregar_grafo()) == _arestas(repo.carregar_grafo())
    with pytest.raises(RuntimeError):
        repo.copiar_para(destino)


def test_url_do_banco_adapta_driver(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert url_do_banco() == "sqlite:///rastro.db"
    assert url_do_banco("postgres://u:s@h/db") == "postgresql+psycopg://u:s@h/db"
    assert url_do_banco("postgresql://u:s@h/db") == "postgresql+psycopg://u:s@h/db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///outro.db")
    assert url_do_banco() == "sqlite:///outro.db"


def test_servico_rejeita_cadastro_direto_de_intermediario(servico):
    from rastro.grafo import RegraViolada

    with pytest.raises(RegraViolada):
        servico.cadastrar(tipo=TipoVertice.INTERMEDIARIO, nome="Leite pasteurizado")
    with pytest.raises(RegraViolada):
        servico.registrar_producao(entradas=[], tipo=TipoVertice.PRODUTO_FINAL, nome="Nada")


def test_demo_do_terminal_roda(capsys):
    from rastro.cli import main

    assert main(["demo", "--lotes", "200"]) == 0
    saida = capsys.readouterr().out
    assert "RECALL" in saida and "Rejeitada" in saida
