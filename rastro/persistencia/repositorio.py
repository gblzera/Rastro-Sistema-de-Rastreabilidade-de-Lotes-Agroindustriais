"""Acesso ao banco: gravação de eventos, vértices e arestas e reconstrução do grafo."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import islice

from sqlalchemy import Engine, func, insert, select, text
from sqlalchemy.orm import Session, sessionmaker

from ..grafo import (
    Aresta,
    EstrategiaCiclo,
    Evento,
    GrafoRastro,
    TipoAresta,
    TipoVertice,
    Vertice,
)
from ..sintetico import BaseSintetica
from .tabelas import ArestaDB, Base, EventoDB, VerticeDB

_TAMANHO_LOTE_INSERCAO = 5000

_SQL_DESCENDENTES = text(
    """
    WITH RECURSIVE alcancados(id) AS (
        SELECT CAST(:raiz AS VARCHAR(40))
        UNION
        SELECT a.destino FROM arestas a JOIN alcancados r ON a.origem = r.id
    )
    SELECT id FROM alcancados
    """
)

_SQL_ASCENDENTES = text(
    """
    WITH RECURSIVE alcancados(id) AS (
        SELECT CAST(:raiz AS VARCHAR(40))
        UNION
        SELECT a.origem FROM arestas a JOIN alcancados r ON a.destino = r.id
    )
    SELECT id FROM alcancados
    """
)


class Repositorio:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._sessoes = sessionmaker(engine, expire_on_commit=False)

    # ----------------------------------------------------------------- esquema

    def criar_esquema(self) -> None:
        Base.metadata.create_all(self.engine)

    def apagar_esquema(self) -> None:
        Base.metadata.drop_all(self.engine)

    def esta_vazio(self) -> bool:
        with self._sessoes() as sessao:
            return not sessao.scalar(select(func.count()).select_from(VerticeDB))

    @contextmanager
    def transacao(self) -> Iterator[Session]:
        """Sessão com commit ao final do bloco e rollback em caso de exceção."""
        with self._sessoes.begin() as sessao:
            yield sessao

    # ---------------------------------------------------------------- leitura

    def carregar_grafo(
        self, estrategia: EstrategiaCiclo = EstrategiaCiclo.ORDEM_TOPOLOGICA
    ) -> GrafoRastro:
        """Reconstrói o grafo em memória a partir das tabelas vertices e arestas."""
        with self._sessoes() as sessao:
            linhas_v = sessao.execute(
                select(
                    VerticeDB.id, VerticeDB.tipo, VerticeDB.nome, VerticeDB.quantidade,
                    VerticeDB.unidade, VerticeDB.atributos, VerticeDB.criado_em, VerticeDB.evento_id,
                )
            ).all()
            linhas_a = sessao.execute(
                select(
                    ArestaDB.origem, ArestaDB.destino, ArestaDB.tipo,
                    ArestaDB.quantidade, ArestaDB.evento_id,
                )
            ).all()
        vertices = (
            Vertice(id_, TipoVertice(tipo), nome, qtd, unidade, atributos or {}, _utc(criado), evento)
            for id_, tipo, nome, qtd, unidade, atributos, criado, evento in linhas_v
        )
        arestas = (
            Aresta(origem, destino, TipoAresta(tipo), qtd, evento)
            for origem, destino, tipo, qtd, evento in linhas_a
        )
        grafo = GrafoRastro(estrategia)
        grafo.carregar(vertices, arestas)
        return grafo

    def listar_eventos(self, limite: int = 50) -> list[dict]:
        """Eventos mais recentes, com os vértices e arestas que cada um criou."""
        with self._sessoes() as sessao:
            eventos = sessao.scalars(
                select(EventoDB).order_by(EventoDB.ocorrido_em.desc(), EventoDB.id.desc()).limit(limite)
            ).all()
            ids = [e.id for e in eventos]
            vertices = sessao.execute(
                select(VerticeDB.evento_id, VerticeDB.id).where(VerticeDB.evento_id.in_(ids))
            ).all()
            arestas = sessao.execute(
                select(ArestaDB.evento_id, ArestaDB.origem, ArestaDB.destino).where(
                    ArestaDB.evento_id.in_(ids)
                )
            ).all()
        por_evento: dict[int, dict] = {
            e.id: {
                "id": e.id,
                "tipo": e.tipo,
                "ocorrido_em": _utc(e.ocorrido_em),
                "descricao": e.descricao,
                "responsavel": e.responsavel,
                "vertices": [],
                "arestas": [],
            }
            for e in eventos
        }
        for evento_id, vertice_id in vertices:
            por_evento[evento_id]["vertices"].append(vertice_id)
        for evento_id, origem, destino in arestas:
            por_evento[evento_id]["arestas"].append({"origem": origem, "destino": destino})
        return list(por_evento.values())

    def descendentes_sql(self, raiz: str) -> set[str]:
        """Recall direto no banco com CTE recursiva (usado para comparação nos testes de carga)."""
        with self.engine.connect() as conexao:
            return set(conexao.execute(_SQL_DESCENDENTES, {"raiz": raiz}).scalars())

    def ascendentes_sql(self, raiz: str) -> set[str]:
        with self.engine.connect() as conexao:
            return set(conexao.execute(_SQL_ASCENDENTES, {"raiz": raiz}).scalars())

    # ---------------------------------------------------------------- escrita

    def inserir_evento(self, sessao: Session, evento: Evento) -> int:
        linha = EventoDB(
            tipo=evento.tipo.value,
            ocorrido_em=evento.ocorrido_em,
            descricao=evento.descricao,
            responsavel=evento.responsavel,
        )
        sessao.add(linha)
        sessao.flush()
        return linha.id

    def inserir_vertice(self, sessao: Session, vertice: Vertice) -> None:
        sessao.add(VerticeDB(**_vertice_para_linha(vertice)))
        sessao.flush()

    def inserir_aresta(self, sessao: Session, aresta: Aresta) -> None:
        sessao.add(ArestaDB(**_aresta_para_linha(aresta)))

    def inserir_base(self, base: BaseSintetica) -> None:
        """Carga em massa de uma base sintética em um banco vazio (preserva os ids dos eventos)."""
        if not self.esta_vazio():
            raise RuntimeError("O banco já tem dados. Use --reset para recriá-lo.")
        with self.transacao() as sessao:
            linhas_eventos = (
                {
                    "id": e.id,
                    "tipo": e.tipo.value,
                    "ocorrido_em": e.ocorrido_em,
                    "descricao": e.descricao,
                    "responsavel": e.responsavel,
                }
                for e in base.eventos
            )
            for tabela, linhas in (
                (EventoDB, linhas_eventos),
                (VerticeDB, map(_vertice_para_linha, base.vertices)),
                (ArestaDB, map(_aresta_para_linha, base.arestas)),
            ):
                while bloco := list(islice(linhas, _TAMANHO_LOTE_INSERCAO)):
                    sessao.execute(insert(tabela), bloco)
            _ajustar_sequencia_eventos(sessao)

    def copiar_para(self, destino: "Repositorio") -> dict[str, int]:
        """Copia todas as linhas deste banco para outro (ex.: SQLite -> PostgreSQL)."""
        destino.criar_esquema()
        if not destino.esta_vazio():
            raise RuntimeError("O banco de destino já tem dados.")
        contagem: dict[str, int] = {}
        with self._sessoes() as origem, destino.transacao() as sessao_destino:
            for tabela in (EventoDB, VerticeDB, ArestaDB):
                colunas = [c.key for c in tabela.__table__.columns]
                resultado = origem.execute(select(*tabela.__table__.columns)).mappings()
                total = 0
                while bloco := [dict(linha) for linha in resultado.fetchmany(_TAMANHO_LOTE_INSERCAO)]:
                    for linha in bloco:
                        for coluna in colunas:
                            if isinstance(linha[coluna], datetime):
                                linha[coluna] = _utc(linha[coluna])
                    sessao_destino.execute(insert(tabela), bloco)
                    total += len(bloco)
                contagem[tabela.__tablename__] = total
            _ajustar_sequencia_eventos(sessao_destino)
        return contagem


def _vertice_para_linha(vertice: Vertice) -> dict:
    return {
        "id": vertice.id,
        "tipo": vertice.tipo.value,
        "nome": vertice.nome,
        "quantidade": vertice.quantidade,
        "unidade": vertice.unidade,
        "atributos": vertice.atributos,
        "criado_em": vertice.criado_em,
        "evento_id": vertice.evento_id,
    }


def _aresta_para_linha(aresta: Aresta) -> dict:
    return {
        "origem": aresta.origem,
        "destino": aresta.destino,
        "tipo": aresta.tipo.value,
        "quantidade": aresta.quantidade,
        "evento_id": aresta.evento_id,
    }


def _ajustar_sequencia_eventos(sessao: Session) -> None:
    """Acertos depois de uma carga em massa."""
    # Os ids dos eventos foram inseridos explicitamente; no PostgreSQL a sequence do SERIAL
    # precisa continuar a partir deles (no SQLite o autoincremento já faz isso).
    if sessao.get_bind().dialect.name == "postgresql":
        sessao.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('eventos', 'id'), "
                "COALESCE((SELECT MAX(id) FROM eventos), 0) + 1, false)"
            )
        )
    # Sem estatísticas atualizadas o planejador pode ignorar os índices nas consultas recursivas.
    for tabela in ("eventos", "vertices", "arestas"):
        sessao.execute(text(f"ANALYZE {tabela}"))


def _utc(momento: datetime) -> datetime:
    # o SQLite devolve datas sem fuso; tudo é gravado em UTC
    return momento.replace(tzinfo=timezone.utc) if momento.tzinfo is None else momento

