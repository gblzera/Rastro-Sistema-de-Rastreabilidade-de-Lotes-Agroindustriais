"""API HTTP do Rastro (FastAPI) e servidor da interface web."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from .. import __version__
from ..grafo import (
    Aresta,
    ArestaDuplicada,
    CicloDetectado,
    ErroGrafo,
    Evento,
    GrafoRastro,
    RegraViolada,
    TipoVertice,
    Vertice,
    VerticeDuplicado,
    VerticeInexistente,
)
from ..persistencia import Repositorio, criar_engine, descrever
from ..servico import EntradaProducao, ServicoRastro
from . import esquemas as e

PASTA_WEB = Path(os.environ.get("RASTRO_WEB_DIR", Path(__file__).resolve().parents[2] / "web"))

_STATUS_POR_ERRO: list[tuple[type[ErroGrafo], int]] = [
    (VerticeInexistente, 404),
    (VerticeDuplicado, 409),
    (ArestaDuplicada, 409),
    (CicloDetectado, 409),
    (RegraViolada, 422),
]


def criar_app(servico: ServicoRastro | None = None, url_banco: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        s = servico or ServicoRastro(Repositorio(criar_engine(url_banco)))
        s.iniciar()
        app.state.servico = s
        yield
        s.repo.engine.dispose()

    app = FastAPI(
        title="Rastro API",
        version=__version__,
        description="Rastreabilidade de lotes agroindustriais modelada como um DAG dinâmico.",
        lifespan=ciclo_de_vida,
    )

    @app.exception_handler(ErroGrafo)
    async def _erro_grafo(_request: Request, erro: ErroGrafo):
        status = next((s for tipo, s in _STATUS_POR_ERRO if isinstance(erro, tipo)), 400)
        corpo = {"erro": type(erro).__name__, "detail": str(erro)}
        if isinstance(erro, CicloDetectado):
            corpo["ciclo"] = erro.ciclo
        return JSONResponse(corpo, status_code=status)

    @app.exception_handler(IntegrityError)
    async def _erro_integridade(_request: Request, erro: IntegrityError):
        return JSONResponse(
            {"erro": "IntegrityError", "detail": f"O banco rejeitou a operação: {erro.orig}"},
            status_code=409,
        )

    def obter_servico(request: Request) -> ServicoRastro:
        return request.app.state.servico

    Servico = Depends(obter_servico)

    # ------------------------------------------------------------- leitura

    @app.get("/api/saude", tags=["sistema"])
    def saude(servico: ServicoRastro = Servico):
        with servico.leitura() as g:
            return {
                "status": "ok",
                "versao": __version__,
                "banco": servico.repo.engine.dialect.name,
                "vertices": g.num_vertices,
                "arestas": g.num_arestas,
            }

    @app.get("/api/estatisticas", response_model=e.EstatisticasOut, tags=["consultas"])
    def estatisticas(servico: ServicoRastro = Servico):
        with servico.leitura() as g:
            return {
                **g.estatisticas(),
                "banco": descrever(servico.repo.engine),
                "estrategia_ciclo": g.estrategia.value,
                "tempo_carga_ms": round(servico.tempo_carga_ms, 2),
            }

    @app.get("/api/vertices", response_model=list[e.VerticeOut], tags=["lotes"])
    def listar_vertices(
        tipo: TipoVertice | None = None,
        q: str | None = Query(default=None, description="Busca no código, nome, fornecedor ou cidade"),
        limite: int = Query(default=50, ge=1, le=500),
        servico: ServicoRastro = Servico,
    ):
        termo = (q or "").strip().casefold()
        with servico.leitura() as g:
            candidatos = [
                v for v in g.vertices(tipo)
                if not termo or termo in _texto_busca(v)
            ]
            candidatos.sort(key=lambda v: (v.criado_em, v.id), reverse=True)
            return [_vertice(g, v) for v in candidatos[:limite]]

    @app.get("/api/vertices/{vertice_id}", response_model=e.VerticeDetalheOut, tags=["lotes"])
    def detalhar_vertice(vertice_id: str, servico: ServicoRastro = Servico):
        with servico.leitura() as g:
            v = g.vertice(vertice_id)
            return {
                **_vertice(g, v),
                "entradas": [_aresta(a) for a in g.arestas_entrada(vertice_id)],
                "saidas": [_aresta(a) for a in g.arestas_saida(vertice_id)],
            }

    @app.get("/api/consultas/{tipo}/{vertice_id}", response_model=e.ConsultaOut, tags=["consultas"])
    def consultar(
        tipo: Literal["recall", "origem"], vertice_id: str, servico: ServicoRastro = Servico
    ):
        """recall: tudo o que foi produzido a partir do lote e para onde foi (BFS descendente).
        origem: toda a cadeia de insumos que compõe o lote (BFS ascendente)."""
        consulta = servico.consultar(vertice_id, tipo)
        r = consulta.resultado
        with servico.leitura() as g:
            return {
                "raiz": r.raiz,
                "tipo": tipo,
                "direcao": r.direcao,
                "tempo_ms": round(consulta.tempo_ms, 4),
                "profundidade": r.profundidade,
                "total_vertices": r.total_vertices,
                "total_arestas": len(r.arestas),
                "resumo": r.por_tipo,
                "vertices": [
                    {**_vertice(g, g.vertice(vid)), "nivel": nivel} for vid, nivel in r.niveis.items()
                ],
                "arestas": [_aresta(a) for a in r.arestas],
            }

    @app.get("/api/grafo", response_model=e.GrafoOut, tags=["consultas"])
    def grafo_completo(
        limite: int = Query(default=1500, ge=1, le=20000), servico: ServicoRastro = Servico
    ):
        """O grafo para visualização. Acima do limite, mantém os destinos e os lotes mais recentes."""
        with servico.leitura() as g:
            if g.num_vertices <= limite:
                ids = {v.id for v in g.vertices()}
            else:
                destinos = [v.id for v in g.vertices(TipoVertice.DESTINO)][:limite]
                lotes = sorted(
                    (v for v in g.vertices() if v.tipo.eh_lote),
                    key=lambda v: (v.criado_em, v.id),
                    reverse=True,
                )[: limite - len(destinos)]
                ids = set(destinos) | {v.id for v in lotes}
            return _subgrafo(g, ids, truncado=len(ids) < g.num_vertices)

    @app.get("/api/grafo/vizinhanca/{vertice_id}", response_model=e.GrafoOut, tags=["consultas"])
    def vizinhanca(
        vertice_id: str,
        raio: int = Query(default=2, ge=1, le=10),
        servico: ServicoRastro = Servico,
    ):
        with servico.leitura() as g:
            ids = g.vizinhanca(vertice_id, raio)
            return _subgrafo(g, ids, truncado=len(ids) < g.num_vertices)

    @app.get("/api/eventos", response_model=list[e.EventoDetalheOut], tags=["eventos"])
    def listar_eventos(limite: int = Query(default=30, ge=1, le=500), servico: ServicoRastro = Servico):
        return servico.repo.listar_eventos(limite)

    # ------------------------------------------------------------- escrita

    @app.post("/api/insumos", response_model=e.VerticeOut, status_code=201, tags=["registro"])
    def receber_insumo(dados: e.InsumoIn, servico: ServicoRastro = Servico):
        atributos = dict(dados.atributos)
        if dados.fornecedor:
            atributos["fornecedor"] = dados.fornecedor
        v = servico.cadastrar(
            tipo=TipoVertice.INSUMO, id=dados.id, nome=dados.nome, quantidade=dados.quantidade,
            unidade=dados.unidade, atributos=atributos, **_registro(dados),
        )
        with servico.leitura() as g:
            return _vertice(g, v)

    @app.post("/api/destinos", response_model=e.VerticeOut, status_code=201, tags=["registro"])
    def cadastrar_destino(dados: e.DestinoIn, servico: ServicoRastro = Servico):
        atributos = dict(dados.atributos)
        if dados.cidade:
            atributos["cidade"] = dados.cidade
        v = servico.cadastrar(
            tipo=TipoVertice.DESTINO, id=dados.id, nome=dados.nome, atributos=atributos,
            **_registro(dados),
        )
        with servico.leitura() as g:
            return _vertice(g, v)

    @app.post("/api/producoes", response_model=e.ProducaoOut, status_code=201, tags=["registro"])
    def registrar_producao(dados: e.ProducaoIn, servico: ServicoRastro = Servico):
        """Transformação: cria o lote de saída e as arestas de composição a partir das entradas."""
        evento, v, arestas = servico.registrar_producao(
            entradas=[EntradaProducao(x.lote, x.quantidade) for x in dados.entradas],
            tipo=TipoVertice(dados.tipo), id=dados.id, nome=dados.nome,
            quantidade=dados.quantidade, unidade=dados.unidade, atributos=dados.atributos,
            **_registro(dados),
        )
        with servico.leitura() as g:
            return {"evento": _evento(evento), "lote": _vertice(g, v), "arestas": [_aresta(a) for a in arestas]}

    @app.post("/api/expedicoes", response_model=e.LigacaoOut, status_code=201, tags=["registro"])
    def registrar_expedicao(dados: e.ExpedicaoIn, servico: ServicoRastro = Servico):
        evento, aresta = servico.registrar_expedicao(
            lote=dados.lote, destino=dados.destino, quantidade=dados.quantidade, **_registro(dados)
        )
        return {"evento": _evento(evento), "aresta": _aresta(aresta)}

    @app.post("/api/vinculos", response_model=e.LigacaoOut, status_code=201, tags=["registro"])
    def registrar_vinculo(dados: e.VinculoIn, servico: ServicoRastro = Servico):
        """Registra que um lote também compôs outro lote já existente (rejeitado se criar ciclo)."""
        evento, aresta = servico.vincular(
            origem=dados.origem, destino=dados.destino, quantidade=dados.quantidade, **_registro(dados)
        )
        return {"evento": _evento(evento), "aresta": _aresta(aresta)}

    if PASTA_WEB.is_dir():
        app.mount("/", StaticFiles(directory=PASTA_WEB, html=True), name="web")

    return app


def _registro(dados: e._Registro) -> dict:
    return {"ocorrido_em": dados.ocorrido_em, "responsavel": dados.responsavel, "descricao": dados.descricao}


def _texto_busca(v: Vertice) -> str:
    extras = " ".join(str(valor) for valor in v.atributos.values())
    return f"{v.id} {v.nome} {extras}".casefold()


def _vertice(g: GrafoRastro, v: Vertice) -> dict:
    return {
        "id": v.id,
        "tipo": v.tipo,
        "nome": v.nome,
        "quantidade": v.quantidade,
        "unidade": v.unidade,
        "atributos": v.atributos,
        "criado_em": v.criado_em,
        "evento_id": v.evento_id,
        "grau_entrada": g.grau_entrada(v.id),
        "grau_saida": g.grau_saida(v.id),
    }


def _aresta(a: Aresta) -> dict:
    return {
        "origem": a.origem,
        "destino": a.destino,
        "tipo": a.tipo,
        "quantidade": a.quantidade,
        "evento_id": a.evento_id,
    }


def _evento(ev: Evento) -> dict:
    return {
        "id": ev.id,
        "tipo": ev.tipo.value,
        "ocorrido_em": ev.ocorrido_em,
        "descricao": ev.descricao,
        "responsavel": ev.responsavel,
    }


def _subgrafo(g: GrafoRastro, ids: set[str], truncado: bool) -> dict:
    return {
        "vertices": [_vertice(g, g.vertice(vid)) for vid in ids],
        "arestas": [_aresta(a) for a in g.arestas_entre(ids)],
        "total_vertices": g.num_vertices,
        "total_arestas": g.num_arestas,
        "truncado": truncado,
    }


app = criar_app()
