"""Serviço da aplicação: coordena o grafo em memória e o banco.

Toda escrita acontece dentro de uma transação do banco e sob um lock. O grafo em memória é
alterado dentro da transação — é ele que valida as regras e a aciclicidade — e, se qualquer
passo falhar (inclusive o commit), as alterações em memória são desfeitas. Assim o grafo em
memória e a edge list do banco nunca divergem.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from .grafo import (
    PREFIXO_ID,
    Aresta,
    EstrategiaCiclo,
    Evento,
    GrafoRastro,
    RegraViolada,
    ResultadoTravessia,
    TipoAresta,
    TipoEvento,
    TipoVertice,
    Vertice,
    VerticeDuplicado,
)
from .grafo.modelo import agora
from .persistencia import Repositorio

_PADRAO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


@dataclass
class Consulta:
    resultado: ResultadoTravessia
    tempo_ms: float


@dataclass
class EntradaProducao:
    lote: str
    quantidade: float | None = None


class ServicoRastro:
    def __init__(
        self,
        repositorio: Repositorio,
        estrategia: EstrategiaCiclo = EstrategiaCiclo.ORDEM_TOPOLOGICA,
    ):
        self.repo = repositorio
        self.grafo = GrafoRastro(estrategia)
        self._lock = threading.RLock()
        self._contadores: dict[str, int] = {}
        self.tempo_carga_ms = 0.0

    def iniciar(self) -> None:
        """Cria o esquema, se preciso, e reconstrói o grafo a partir do banco."""
        self.repo.criar_esquema()
        with self._lock:
            inicio = time.perf_counter()
            self.grafo = self.repo.carregar_grafo(self.grafo.estrategia)
            self.tempo_carga_ms = (time.perf_counter() - inicio) * 1000
            self._contadores.clear()
            for vertice in self.grafo.vertices():
                prefixo, _, numero = vertice.id.partition("-")
                if numero.isdigit():
                    self._contadores[prefixo] = max(self._contadores.get(prefixo, 0), int(numero))

    # ---------------------------------------------------------------- escrita

    def cadastrar(
        self,
        *,
        tipo: TipoVertice,
        nome: str,
        id: str | None = None,
        quantidade: float | None = None,
        unidade: str | None = None,
        atributos: dict[str, Any] | None = None,
        ocorrido_em: datetime | None = None,
        responsavel: str | None = None,
        descricao: str | None = None,
    ) -> Vertice:
        """Recebimento de um lote de insumo ou cadastro de um destino."""
        tipo = TipoVertice(tipo)
        if tipo not in (TipoVertice.INSUMO, TipoVertice.DESTINO):
            raise RegraViolada(
                "Só insumos e destinos são cadastrados diretamente; intermediários e produtos "
                "finais nascem de um evento de produção."
            )
        padrao = f"Recebimento de {nome}" if tipo is TipoVertice.INSUMO else f"Cadastro do destino {nome}"
        with self._operacao() as (sessao, desfazer):
            evento = self._novo_evento(sessao, TipoEvento.CADASTRO, ocorrido_em, descricao or padrao, responsavel)
            vertice = self._novo_vertice(
                sessao, desfazer, evento, id, tipo, nome, quantidade, unidade, atributos
            )
        return vertice

    def registrar_producao(
        self,
        *,
        entradas: list[EntradaProducao],
        tipo: TipoVertice,
        nome: str,
        id: str | None = None,
        quantidade: float | None = None,
        unidade: str | None = None,
        atributos: dict[str, Any] | None = None,
        ocorrido_em: datetime | None = None,
        responsavel: str | None = None,
        descricao: str | None = None,
    ) -> tuple[Evento, Vertice, list[Aresta]]:
        """Transformação: cria o lote de saída e uma aresta de cada lote de entrada até ele."""
        tipo = TipoVertice(tipo)
        if tipo not in (TipoVertice.INTERMEDIARIO, TipoVertice.PRODUTO_FINAL):
            raise RegraViolada("O lote produzido deve ser um intermediário ou um produto final.")
        if not entradas:
            raise RegraViolada("Uma produção precisa de pelo menos um lote de entrada.")
        lotes = [e.lote for e in entradas]
        if len(set(lotes)) != len(lotes):
            raise RegraViolada("O mesmo lote de entrada foi informado mais de uma vez.")

        with self._operacao() as (sessao, desfazer):
            evento = self._novo_evento(
                sessao, TipoEvento.PRODUCAO, ocorrido_em, descricao or f"Produção de {nome}", responsavel
            )
            vertice = self._novo_vertice(
                sessao, desfazer, evento, id, tipo, nome, quantidade, unidade, atributos
            )
            arestas = [
                self._nova_aresta(
                    sessao, desfazer, evento, entrada.lote, vertice.id,
                    TipoAresta.COMPOSICAO, entrada.quantidade,
                )
                for entrada in entradas
            ]
        return evento, vertice, arestas

    def registrar_expedicao(
        self,
        *,
        lote: str,
        destino: str,
        quantidade: float | None = None,
        ocorrido_em: datetime | None = None,
        responsavel: str | None = None,
        descricao: str | None = None,
    ) -> tuple[Evento, Aresta]:
        with self._operacao() as (sessao, desfazer):
            evento = self._novo_evento(
                sessao, TipoEvento.EXPEDICAO, ocorrido_em,
                descricao or f"Expedição de {lote} para {destino}", responsavel,
            )
            aresta = self._nova_aresta(
                sessao, desfazer, evento, lote, destino, TipoAresta.EXPEDICAO, quantidade
            )
        return evento, aresta

    def vincular(
        self,
        *,
        origem: str,
        destino: str,
        quantidade: float | None = None,
        ocorrido_em: datetime | None = None,
        responsavel: str | None = None,
        descricao: str | None = None,
    ) -> tuple[Evento, Aresta]:
        """Registra que `origem` também compôs o lote já existente `destino` (ajuste manual).

        É aqui que a verificação de aciclicidade realmente trabalha: o lote de destino já
        existe e pode ser ancestral da origem.
        """
        with self._operacao() as (sessao, desfazer):
            evento = self._novo_evento(
                sessao, TipoEvento.AJUSTE, ocorrido_em,
                descricao or f"Vínculo de {origem} em {destino}", responsavel,
            )
            aresta = self._nova_aresta(
                sessao, desfazer, evento, origem, destino, TipoAresta.COMPOSICAO, quantidade
            )
        return evento, aresta

    # --------------------------------------------------------------- consultas

    def consultar(self, vertice_id: str, direcao: Literal["recall", "origem"]) -> Consulta:
        with self._lock:
            inicio = time.perf_counter()
            if direcao == "recall":
                resultado = self.grafo.recall(vertice_id)
            else:
                resultado = self.grafo.origem(vertice_id)
            return Consulta(resultado, (time.perf_counter() - inicio) * 1000)

    @contextmanager
    def leitura(self) -> Iterator[GrafoRastro]:
        """Acesso ao grafo protegido contra escritas concorrentes."""
        with self._lock:
            yield self.grafo

    # ------------------------------------------------------------- auxiliares

    @contextmanager
    def _operacao(self) -> Iterator[tuple[Session, list[Callable[[], object]]]]:
        desfazer: list[Callable[[], object]] = []
        with self._lock:
            try:
                with self.repo.transacao() as sessao:
                    yield sessao, desfazer
            except BaseException:
                for acao in reversed(desfazer):
                    acao()
                raise

    def _novo_evento(
        self,
        sessao: Session,
        tipo: TipoEvento,
        ocorrido_em: datetime | None,
        descricao: str,
        responsavel: str | None,
    ) -> Evento:
        evento = Evento(None, tipo, ocorrido_em or agora(), descricao, responsavel)
        evento.id = self.repo.inserir_evento(sessao, evento)
        return evento

    def _novo_vertice(
        self,
        sessao: Session,
        desfazer: list,
        evento: Evento,
        id: str | None,
        tipo: TipoVertice,
        nome: str,
        quantidade: float | None,
        unidade: str | None,
        atributos: dict[str, Any] | None,
    ) -> Vertice:
        if id is not None:
            id = id.strip()
            if not _PADRAO_ID.match(id):
                raise RegraViolada(
                    "Código inválido: use até 40 letras, números, '.', '_' ou '-', "
                    "começando por letra ou número."
                )
            if id in self.grafo:
                raise VerticeDuplicado(id)
        vertice = Vertice(
            id or self._proximo_id(tipo), tipo, nome.strip(), quantidade, unidade,
            dict(atributos or {}), evento.ocorrido_em, evento.id,
        )
        self.grafo.adicionar_vertice(vertice)
        desfazer.append(lambda: self.grafo.remover_vertice(vertice.id))
        self.repo.inserir_vertice(sessao, vertice)
        return vertice

    def _nova_aresta(
        self,
        sessao: Session,
        desfazer: list,
        evento: Evento,
        origem: str,
        destino: str,
        tipo: TipoAresta,
        quantidade: float | None,
    ) -> Aresta:
        aresta = self.grafo.adicionar_aresta(
            origem, destino, tipo=tipo, quantidade=quantidade, evento_id=evento.id
        )
        desfazer.append(lambda: self.grafo.remover_aresta(origem, destino))
        self.repo.inserir_aresta(sessao, aresta)
        return aresta

    def _proximo_id(self, tipo: TipoVertice) -> str:
        prefixo = PREFIXO_ID[tipo]
        numero = self._contadores.get(prefixo, 0)
        while True:
            numero += 1
            candidato = f"{prefixo}-{numero:06d}"
            if candidato not in self.grafo:
                self._contadores[prefixo] = numero
                return candidato
