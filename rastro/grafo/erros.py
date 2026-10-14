"""Erros do motor de grafos. Todos herdam de ErroGrafo para facilitar o tratamento na API."""

from __future__ import annotations


class ErroGrafo(Exception):
    pass


class VerticeInexistente(ErroGrafo):
    def __init__(self, vertice_id: str):
        super().__init__(f"Vértice '{vertice_id}' não existe.")
        self.vertice_id = vertice_id


class VerticeDuplicado(ErroGrafo):
    def __init__(self, vertice_id: str):
        super().__init__(f"Já existe um vértice com id '{vertice_id}'.")
        self.vertice_id = vertice_id


class ArestaDuplicada(ErroGrafo):
    def __init__(self, origem: str, destino: str):
        super().__init__(f"A aresta {origem} -> {destino} já existe.")
        self.origem = origem
        self.destino = destino


class RegraViolada(ErroGrafo):
    """Aresta que não faz sentido no domínio (ex.: destino como origem de uma composição)."""


class CicloDetectado(ErroGrafo):
    """Inserir a aresta faria um lote ser ancestral de si mesmo.

    `ciclo` é a sequência de vértices que fecharia o ciclo, começando e terminando
    no mesmo vértice: [origem, destino, ..., origem].
    """

    def __init__(self, ciclo: list[str]):
        caminho = " -> ".join(ciclo)
        super().__init__(f"A aresta criaria um ciclo: {caminho}.")
        self.ciclo = ciclo
