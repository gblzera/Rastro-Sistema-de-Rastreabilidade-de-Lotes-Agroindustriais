"""Esquemas de entrada e saída da API (validação com Pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..grafo import TipoAresta, TipoVertice

Quantidade = Field(default=None, ge=0)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Registro(_Base):
    ocorrido_em: Optional[datetime] = Field(default=None, description="Padrão: agora")
    responsavel: Optional[str] = Field(default=None, max_length=120)
    descricao: Optional[str] = Field(default=None, max_length=500)


class InsumoIn(_Registro):
    id: Optional[str] = Field(default=None, description="Código do lote; gerado se omitido (INS-000001)")
    nome: str = Field(min_length=1, max_length=200, examples=["Leite cru"])
    quantidade: Optional[float] = Quantidade
    unidade: Optional[str] = Field(default=None, max_length=20, examples=["L"])
    fornecedor: Optional[str] = Field(default=None, max_length=200)
    atributos: dict[str, Any] = Field(default_factory=dict)


class DestinoIn(_Registro):
    id: Optional[str] = None
    nome: str = Field(min_length=1, max_length=200, examples=["Supermercado Central"])
    cidade: Optional[str] = Field(default=None, max_length=120, examples=["Asa Norte/DF"])
    atributos: dict[str, Any] = Field(default_factory=dict)


class EntradaIn(_Base):
    lote: str = Field(min_length=1, max_length=40)
    quantidade: Optional[float] = Quantidade


class ProducaoIn(_Registro):
    entradas: list[EntradaIn] = Field(min_length=1)
    tipo: Literal["intermediario", "produto_final"]
    id: Optional[str] = None
    nome: str = Field(min_length=1, max_length=200, examples=["Queijo minas frescal"])
    quantidade: Optional[float] = Quantidade
    unidade: Optional[str] = Field(default=None, max_length=20)
    atributos: dict[str, Any] = Field(default_factory=dict)


class ExpedicaoIn(_Registro):
    lote: str = Field(min_length=1, max_length=40)
    destino: str = Field(min_length=1, max_length=40)
    quantidade: Optional[float] = Quantidade


class VinculoIn(_Registro):
    origem: str = Field(min_length=1, max_length=40)
    destino: str = Field(min_length=1, max_length=40)
    quantidade: Optional[float] = Quantidade


class VerticeOut(BaseModel):
    id: str
    tipo: TipoVertice
    nome: str
    quantidade: Optional[float]
    unidade: Optional[str]
    atributos: dict[str, Any]
    criado_em: datetime
    evento_id: Optional[int]
    grau_entrada: int
    grau_saida: int


class ArestaOut(BaseModel):
    origem: str
    destino: str
    tipo: TipoAresta
    quantidade: Optional[float]
    evento_id: Optional[int]


class VerticeDetalheOut(VerticeOut):
    entradas: list[ArestaOut]
    saidas: list[ArestaOut]


class EventoOut(BaseModel):
    id: int
    tipo: str
    ocorrido_em: datetime
    descricao: Optional[str]
    responsavel: Optional[str]


class ProducaoOut(BaseModel):
    evento: EventoOut
    lote: VerticeOut
    arestas: list[ArestaOut]


class LigacaoOut(BaseModel):
    evento: EventoOut
    aresta: ArestaOut


class VerticeConsultaOut(VerticeOut):
    nivel: int


class ConsultaOut(BaseModel):
    raiz: str
    tipo: Literal["recall", "origem"]
    direcao: Literal["descendente", "ascendente"]
    tempo_ms: float
    profundidade: int
    total_vertices: int
    total_arestas: int
    resumo: dict[TipoVertice, list[str]]
    vertices: list[VerticeConsultaOut]
    arestas: list[ArestaOut]


class GrafoOut(BaseModel):
    vertices: list[VerticeOut]
    arestas: list[ArestaOut]
    total_vertices: int
    total_arestas: int
    truncado: bool


class EstatisticasOut(BaseModel):
    vertices: int
    arestas: int
    vertices_por_tipo: dict[str, int]
    arestas_por_tipo: dict[str, int]
    fontes: int
    sumidouros: int
    profundidade_maxima: int
    banco: str
    estrategia_ciclo: str
    tempo_carga_ms: float


class EventoDetalheOut(EventoOut):
    vertices: list[str]
    arestas: list[dict[str, str]]
