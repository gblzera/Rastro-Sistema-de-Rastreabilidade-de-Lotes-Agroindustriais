"""Esquema relacional: o grafo é guardado como uma lista de arestas (edge list).

- vertices: cada lote (insumo, intermediário, produto final) ou destino;
- arestas:  a edge list propriamente dita, uma linha por relação origem -> destino;
- eventos:  o registro de produção que originou vértices e arestas (trilha de auditoria).

As travessias não são feitas em SQL: na inicialização a aplicação lê as duas tabelas e
reconstrói o grafo em memória (ver Repositorio.carregar_grafo).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..grafo.modelo import TipoAresta, TipoEvento, TipoVertice

JSONVariante = JSON().with_variant(JSONB(), "postgresql")


def _valores(enum) -> str:
    return ", ".join(f"'{membro.value}'" for membro in enum)


class Base(DeclarativeBase):
    pass


class EventoDB(Base):
    __tablename__ = "eventos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    ocorrido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    responsavel: Mapped[str | None] = mapped_column(String(120))

    __table_args__ = (
        CheckConstraint(f"tipo IN ({_valores(TipoEvento)})", name="ck_eventos_tipo"),
        Index("ix_eventos_ocorrido_em", "ocorrido_em"),
    )


class VerticeDB(Base):
    __tablename__ = "vertices"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    quantidade: Mapped[float | None] = mapped_column(Float)
    unidade: Mapped[str | None] = mapped_column(String(20))
    atributos: Mapped[dict[str, Any]] = mapped_column(JSONVariante, nullable=False, default=dict)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evento_id: Mapped[int | None] = mapped_column(ForeignKey("eventos.id"))

    __table_args__ = (
        CheckConstraint(f"tipo IN ({_valores(TipoVertice)})", name="ck_vertices_tipo"),
        Index("ix_vertices_tipo", "tipo"),
    )


class ArestaDB(Base):
    __tablename__ = "arestas"

    origem: Mapped[str] = mapped_column(ForeignKey("vertices.id"), primary_key=True)
    destino: Mapped[str] = mapped_column(ForeignKey("vertices.id"), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    quantidade: Mapped[float | None] = mapped_column(Float)
    evento_id: Mapped[int | None] = mapped_column(ForeignKey("eventos.id"))

    __table_args__ = (
        CheckConstraint(f"tipo IN ({_valores(TipoAresta)})", name="ck_arestas_tipo"),
        CheckConstraint("origem <> destino", name="ck_arestas_sem_laco"),
        # a chave primária (origem, destino) já atende a travessia descendente;
        # este índice atende a ascendente (auditoria de origem)
        Index("ix_arestas_destino", "destino"),
    )
