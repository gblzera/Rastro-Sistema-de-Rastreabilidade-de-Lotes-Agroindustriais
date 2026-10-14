"""Motor do grafo de rastreabilidade: um DAG dinâmico mantido em memória.

Vértices são lotes (insumo, intermediário, produto final) e destinos; cada transformação
registrada cria arestas dirigidas dos lotes de entrada para o lote de saída, e cada expedição
cria uma aresta do lote para o destino. O grafo é guardado como duas listas de adjacência
(saída e entrada), o que permite travessias nos dois sentidos em O(V+E):

- recall  (fecho descendente): BFS pelas arestas de saída a partir do lote comprometido;
- origem  (fecho ascendente):  BFS pelas arestas de entrada a partir do produto auditado.

A aciclicidade é garantida a cada inserção de aresta. A estratégia padrão mantém uma ordem
topológica dinâmica (Pearce & Kelly, 2006): se a nova aresta respeita a ordem atual, a
inserção é O(1); caso contrário só a região afetada é explorada e reordenada. A estratégia
alternativa (busca em profundidade a cada inserção) fica disponível como referência e para
os testes de carga comparativos.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from .erros import (
    ArestaDuplicada,
    CicloDetectado,
    ErroGrafo,
    RegraViolada,
    VerticeDuplicado,
    VerticeInexistente,
)
from .modelo import Aresta, TipoAresta, TipoVertice, Vertice, tipo_aresta_para


class EstrategiaCiclo(str, Enum):
    ORDEM_TOPOLOGICA = "ordem_topologica"
    BUSCA_PROFUNDIDADE = "busca_profundidade"


@dataclass
class ResultadoTravessia:
    raiz: str
    direcao: Literal["descendente", "ascendente"]
    # vértice -> distância (em arestas) até a raiz, na ordem em que a BFS os visitou
    niveis: dict[str, int]
    # arestas do subgrafo alcançado
    arestas: list[Aresta]
    # vértices alcançados agrupados por tipo (a raiz está incluída)
    por_tipo: dict[TipoVertice, list[str]]

    @property
    def profundidade(self) -> int:
        return max(self.niveis.values(), default=0)

    @property
    def total_vertices(self) -> int:
        return len(self.niveis)

    def __contains__(self, vertice_id: object) -> bool:
        return vertice_id in self.niveis


class GrafoRastro:
    def __init__(self, estrategia: EstrategiaCiclo | str = EstrategiaCiclo.ORDEM_TOPOLOGICA):
        self.estrategia = EstrategiaCiclo(estrategia)
        self._vertices: dict[str, Vertice] = {}
        self._saida: dict[str, dict[str, Aresta]] = {}
        self._entrada: dict[str, dict[str, Aresta]] = {}
        # índice de cada vértice em uma ordem topológica válida (usado pela estratégia Pearce-Kelly)
        self._ordem: dict[str, int] = {}
        self._proxima_ordem = 0
        self._num_arestas = 0

    # ------------------------------------------------------------------ leitura

    def __len__(self) -> int:
        return len(self._vertices)

    def __contains__(self, vertice_id: object) -> bool:
        return vertice_id in self._vertices

    @property
    def num_vertices(self) -> int:
        return len(self._vertices)

    @property
    def num_arestas(self) -> int:
        return self._num_arestas

    def vertice(self, vertice_id: str) -> Vertice:
        try:
            return self._vertices[vertice_id]
        except KeyError:
            raise VerticeInexistente(vertice_id) from None

    def vertices(self, tipo: TipoVertice | None = None) -> Iterator[Vertice]:
        if tipo is None:
            yield from self._vertices.values()
        else:
            yield from (v for v in self._vertices.values() if v.tipo is tipo)

    def arestas(self) -> Iterator[Aresta]:
        for adjacentes in self._saida.values():
            yield from adjacentes.values()

    def aresta(self, origem: str, destino: str) -> Aresta | None:
        return self._saida.get(origem, {}).get(destino)

    def sucessores(self, vertice_id: str) -> list[str]:
        self.vertice(vertice_id)
        return list(self._saida[vertice_id])

    def predecessores(self, vertice_id: str) -> list[str]:
        self.vertice(vertice_id)
        return list(self._entrada[vertice_id])

    def arestas_saida(self, vertice_id: str) -> list[Aresta]:
        self.vertice(vertice_id)
        return list(self._saida[vertice_id].values())

    def arestas_entrada(self, vertice_id: str) -> list[Aresta]:
        self.vertice(vertice_id)
        return list(self._entrada[vertice_id].values())

    def grau_saida(self, vertice_id: str) -> int:
        self.vertice(vertice_id)
        return len(self._saida[vertice_id])

    def grau_entrada(self, vertice_id: str) -> int:
        self.vertice(vertice_id)
        return len(self._entrada[vertice_id])

    def indice_topologico(self, vertice_id: str) -> int:
        self.vertice(vertice_id)
        return self._ordem[vertice_id]

    # ------------------------------------------------------------------ escrita

    def adicionar_vertice(self, vertice: Vertice) -> Vertice:
        if vertice.id in self._vertices:
            raise VerticeDuplicado(vertice.id)
        self._vertices[vertice.id] = vertice
        self._saida[vertice.id] = {}
        self._entrada[vertice.id] = {}
        # um vértice novo não tem arestas, então o fim da ordem é sempre uma posição válida
        self._ordem[vertice.id] = self._proxima_ordem
        self._proxima_ordem += 1
        return vertice

    def remover_vertice(self, vertice_id: str) -> Vertice:
        vertice = self.vertice(vertice_id)
        for destino in list(self._saida[vertice_id]):
            self.remover_aresta(vertice_id, destino)
        for origem in list(self._entrada[vertice_id]):
            self.remover_aresta(origem, vertice_id)
        del self._vertices[vertice_id]
        del self._saida[vertice_id]
        del self._entrada[vertice_id]
        del self._ordem[vertice_id]
        return vertice

    def validar_regras(
        self, origem: str, destino: str, tipo: TipoAresta | str | None = None
    ) -> TipoAresta:
        """Valida as regras de domínio de uma aresta (sem a checagem de ciclo).

        Devolve o tipo de aresta adequado ao par de vértices.
        """
        v_origem = self.vertice(origem)
        v_destino = self.vertice(destino)
        if origem == destino:
            raise CicloDetectado([origem, origem])
        if destino in self._saida[origem]:
            raise ArestaDuplicada(origem, destino)
        if v_origem.tipo is TipoVertice.DESTINO:
            raise RegraViolada(f"'{origem}' é um destino e não pode originar arestas.")
        if v_destino.tipo is TipoVertice.INSUMO:
            raise RegraViolada(
                f"'{destino}' é um insumo: insumos abrem a cadeia e não são produzidos "
                "a partir de outros lotes."
            )
        esperado = tipo_aresta_para(v_destino)
        if tipo is not None and TipoAresta(tipo) is not esperado:
            raise RegraViolada(
                f"Uma aresta de '{origem}' para '{destino}' ({v_destino.tipo.value}) "
                f"deve ser do tipo '{esperado.value}', não '{TipoAresta(tipo).value}'."
            )
        return esperado

    def adicionar_aresta(
        self,
        origem: str,
        destino: str,
        *,
        tipo: TipoAresta | str | None = None,
        quantidade: float | None = None,
        evento_id: int | None = None,
    ) -> Aresta:
        tipo_aresta = self.validar_regras(origem, destino, tipo)
        if self.estrategia is EstrategiaCiclo.ORDEM_TOPOLOGICA:
            self._reordenar_para(origem, destino)
        else:
            ciclo = self.criaria_ciclo(origem, destino)
            if ciclo:
                raise CicloDetectado(ciclo)
        aresta = Aresta(origem, destino, tipo_aresta, quantidade, evento_id)
        self._ligar(aresta)
        return aresta

    def remover_aresta(self, origem: str, destino: str) -> Aresta:
        try:
            aresta = self._saida[origem].pop(destino)
        except KeyError:
            raise ErroGrafo(f"A aresta {origem} -> {destino} não existe.") from None
        del self._entrada[destino][origem]
        self._num_arestas -= 1
        # remover arestas nunca invalida uma ordem topológica, então _ordem continua válida
        return aresta

    def carregar(self, vertices: Iterable[Vertice], arestas: Iterable[Aresta]) -> None:
        """Reconstrói o grafo a partir de listas de vértices e arestas (a edge list do banco).

        Checar ciclo aresta a aresta custaria O(E·(V+E)) no pior caso; aqui as arestas são
        ligadas direto e o grafo inteiro é validado com uma única ordenação topológica
        (Kahn, O(V+E)), que também inicializa a ordem dinâmica.
        """
        if self._vertices:
            raise ErroGrafo("carregar() exige um grafo vazio.")
        try:
            for vertice in vertices:
                self.adicionar_vertice(vertice)
            for aresta in arestas:
                tipo = self.validar_regras(aresta.origem, aresta.destino, aresta.tipo)
                if aresta.tipo is not tipo:
                    aresta = Aresta(aresta.origem, aresta.destino, tipo, aresta.quantidade, aresta.evento_id)
                self._ligar(aresta)
            ordem = self.ordem_topologica()
        except ErroGrafo:
            self.__init__(self.estrategia)
            raise
        self._ordem = {vertice_id: i for i, vertice_id in enumerate(ordem)}
        self._proxima_ordem = len(ordem)

    def _ligar(self, aresta: Aresta) -> None:
        self._saida[aresta.origem][aresta.destino] = aresta
        self._entrada[aresta.destino][aresta.origem] = aresta
        self._num_arestas += 1

    # --------------------------------------------------------- aciclicidade

    def encontrar_caminho(self, origem: str, destino: str) -> list[str] | None:
        """Um caminho dirigido de `origem` até `destino` (DFS iterativa), ou None."""
        self.vertice(origem)
        self.vertice(destino)
        if origem == destino:
            return [origem]
        pais: dict[str, str | None] = {origem: None}
        pilha = [origem]
        while pilha:
            atual = pilha.pop()
            for vizinho in self._saida[atual]:
                if vizinho in pais:
                    continue
                pais[vizinho] = atual
                if vizinho == destino:
                    return _reconstruir(pais, destino)
                pilha.append(vizinho)
        return None

    def criaria_ciclo(self, origem: str, destino: str) -> list[str] | None:
        """Se a aresta origem -> destino fecharia um ciclo, devolve esse ciclo.

        Há ciclo exatamente quando `origem` já é alcançável a partir de `destino`.
        """
        caminho = self.encontrar_caminho(destino, origem)
        return [origem, *caminho] if caminho else None

    def _reordenar_para(self, x: str, y: str) -> None:
        """Pearce & Kelly: prepara a ordem topológica para receber a aresta x -> y.

        Se ord(x) < ord(y) nada muda. Senão, todo caminho de y até x passaria só por vértices
        com ordem em [ord(y), ord(x)]; buscamos nessa faixa para frente a partir de y (se
        chegarmos em x há ciclo) e para trás a partir de x, e redistribuímos entre os vértices
        visitados os mesmos índices que eles já ocupavam: primeiro os que chegam em x, depois
        os que saem de y.
        """
        ordem = self._ordem
        limite_inferior, limite_superior = ordem[y], ordem[x]
        if limite_inferior > limite_superior:
            return

        pais: dict[str, str | None] = {y: None}
        frente: list[str] = []
        pilha = [y]
        while pilha:
            atual = pilha.pop()
            frente.append(atual)
            for vizinho in self._saida[atual]:
                if vizinho == x:
                    raise CicloDetectado([x, *_reconstruir(pais, atual), x])
                if vizinho not in pais and ordem[vizinho] < limite_superior:
                    pais[vizinho] = atual
                    pilha.append(vizinho)

        visitados_tras = {x}
        tras: list[str] = []
        pilha = [x]
        while pilha:
            atual = pilha.pop()
            tras.append(atual)
            for vizinho in self._entrada[atual]:
                if vizinho not in visitados_tras and ordem[vizinho] > limite_inferior:
                    visitados_tras.add(vizinho)
                    pilha.append(vizinho)

        tras.sort(key=ordem.__getitem__)
        frente.sort(key=ordem.__getitem__)
        reordenados = tras + frente
        indices = sorted(ordem[v] for v in reordenados)
        for vertice_id, indice in zip(reordenados, indices):
            ordem[vertice_id] = indice

    def ordem_topologica(self) -> list[str]:
        """Ordenação topológica de Kahn. Levanta CicloDetectado se o grafo tiver ciclo."""
        grau = {vertice_id: len(entrada) for vertice_id, entrada in self._entrada.items()}
        fila = deque(vertice_id for vertice_id, g in grau.items() if g == 0)
        ordem: list[str] = []
        while fila:
            atual = fila.popleft()
            ordem.append(atual)
            for vizinho in self._saida[atual]:
                grau[vizinho] -= 1
                if grau[vizinho] == 0:
                    fila.append(vizinho)
        if len(ordem) != len(self._vertices):
            restantes = {vertice_id for vertice_id, g in grau.items() if g > 0}
            raise CicloDetectado(self._extrair_ciclo(restantes))
        return ordem

    def _extrair_ciclo(self, restantes: set[str]) -> list[str]:
        # Todo vértice que sobrou no Kahn tem um predecessor que também sobrou; andando para
        # trás por eles, algum vértice se repete e fecha o ciclo.
        caminho: list[str] = []
        posicao: dict[str, int] = {}
        atual = next(iter(restantes))
        while atual not in posicao:
            posicao[atual] = len(caminho)
            caminho.append(atual)
            atual = next(p for p in self._entrada[atual] if p in restantes)
        inicio = posicao[atual]
        return [atual, *reversed(caminho[inicio + 1 :]), atual]

    # ------------------------------------------------------------ consultas

    def recall(self, lote_id: str) -> ResultadoTravessia:
        """Tudo o que foi produzido a partir do lote e para onde foi enviado (fecho descendente)."""
        return self._travessia(lote_id, self._saida, "descendente")

    def origem(self, lote_id: str) -> ResultadoTravessia:
        """Toda a cadeia de insumos que compõe o lote (fecho ascendente)."""
        return self._travessia(lote_id, self._entrada, "ascendente")

    def _travessia(
        self,
        raiz: str,
        adjacencia: dict[str, dict[str, Aresta]],
        direcao: Literal["descendente", "ascendente"],
    ) -> ResultadoTravessia:
        self.vertice(raiz)
        niveis = {raiz: 0}
        arestas: list[Aresta] = []
        fila = deque([raiz])
        while fila:
            atual = fila.popleft()
            proximo_nivel = niveis[atual] + 1
            for vizinho, aresta in adjacencia[atual].items():
                arestas.append(aresta)
                if vizinho not in niveis:
                    niveis[vizinho] = proximo_nivel
                    fila.append(vizinho)
        por_tipo: dict[TipoVertice, list[str]] = {tipo: [] for tipo in TipoVertice}
        for vertice_id in niveis:
            por_tipo[self._vertices[vertice_id].tipo].append(vertice_id)
        return ResultadoTravessia(raiz, direcao, niveis, arestas, por_tipo)

    def vizinhanca(self, vertice_id: str, raio: int = 1) -> set[str]:
        """Vértices a até `raio` arestas de distância, ignorando o sentido (para visualização)."""
        self.vertice(vertice_id)
        niveis = {vertice_id: 0}
        fila = deque([vertice_id])
        while fila:
            atual = fila.popleft()
            if niveis[atual] == raio:
                continue
            for vizinho in (*self._saida[atual], *self._entrada[atual]):
                if vizinho not in niveis:
                    niveis[vizinho] = niveis[atual] + 1
                    fila.append(vizinho)
        return set(niveis)

    def arestas_entre(self, vertice_ids: set[str]) -> list[Aresta]:
        return [
            aresta
            for vertice_id in vertice_ids
            for vizinho, aresta in self._saida[vertice_id].items()
            if vizinho in vertice_ids
        ]

    def profundidade_maxima(self) -> int:
        """Comprimento (em arestas) da cadeia mais longa, por programação dinâmica na ordem topológica."""
        distancia: dict[str, int] = {}
        for vertice_id in self.ordem_topologica():
            distancia[vertice_id] = max(
                (distancia[p] + 1 for p in self._entrada[vertice_id]), default=0
            )
        return max(distancia.values(), default=0)

    def estatisticas(self) -> dict:
        vertices_por_tipo = Counter(v.tipo for v in self._vertices.values())
        arestas_por_tipo = Counter(a.tipo for a in self.arestas())
        return {
            "vertices": self.num_vertices,
            "arestas": self.num_arestas,
            "vertices_por_tipo": {t.value: vertices_por_tipo.get(t, 0) for t in TipoVertice},
            "arestas_por_tipo": {t.value: arestas_por_tipo.get(t, 0) for t in TipoAresta},
            "fontes": sum(1 for entrada in self._entrada.values() if not entrada),
            "sumidouros": sum(1 for saida in self._saida.values() if not saida),
            "profundidade_maxima": self.profundidade_maxima(),
        }


def _reconstruir(pais: dict[str, str | None], fim: str) -> list[str]:
    caminho: list[str] = []
    atual: str | None = fim
    while atual is not None:
        caminho.append(atual)
        atual = pais[atual]
    caminho.reverse()
    return caminho
