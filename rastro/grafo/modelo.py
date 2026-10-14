"""Tipos do domínio: vértices (lotes e destinos) e arestas (composição e expedição)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TipoVertice(str, Enum):
    INSUMO = "insumo"
    INTERMEDIARIO = "intermediario"
    PRODUTO_FINAL = "produto_final"
    DESTINO = "destino"

    @property
    def eh_lote(self) -> bool:
        return self is not TipoVertice.DESTINO


class TipoAresta(str, Enum):
    # lote de entrada -> lote de saída de uma transformação
    COMPOSICAO = "composicao"
    # lote -> destino (cliente, distribuidor) para onde foi enviado
    EXPEDICAO = "expedicao"


def agora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Vertice:
    id: str
    tipo: TipoVertice
    nome: str
    quantidade: float | None = None
    unidade: str | None = None
    atributos: dict[str, Any] = field(default_factory=dict)
    criado_em: datetime = field(default_factory=agora)
    # evento que originou o vértice (cadastro ou produção)
    evento_id: int | None = None


@dataclass(frozen=True)
class Aresta:
    origem: str
    destino: str
    tipo: TipoAresta
    quantidade: float | None = None
    evento_id: int | None = None


def tipo_aresta_para(destino: Vertice) -> TipoAresta:
    """Uma aresta que chega em um destino é expedição; qualquer outra é composição."""
    return TipoAresta.EXPEDICAO if destino.tipo is TipoVertice.DESTINO else TipoAresta.COMPOSICAO


# Prefixo dos códigos gerados automaticamente (ex.: INS-000042)
PREFIXO_ID = {
    TipoVertice.INSUMO: "INS",
    TipoVertice.INTERMEDIARIO: "INT",
    TipoVertice.PRODUTO_FINAL: "PRD",
    TipoVertice.DESTINO: "DST",
}


class TipoEvento(str, Enum):
    CADASTRO = "cadastro"  # recebimento de insumo ou cadastro de destino
    PRODUCAO = "producao"  # transformação: lotes de entrada -> lote de saída
    EXPEDICAO = "expedicao"  # envio de um lote a um destino
    AJUSTE = "ajuste"  # vínculo registrado manualmente entre lotes já existentes


@dataclass
class Evento:
    id: int | None
    tipo: TipoEvento
    ocorrido_em: datetime = field(default_factory=agora)
    descricao: str | None = None
    responsavel: str | None = None
