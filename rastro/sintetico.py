"""Gerador de bases sintéticas que simulam a operação de uma agroindústria.

A simulação avança em dias. Em cada dia a agroindústria recebe lotes de insumos dos
fornecedores, produz intermediários e produtos finais seguindo receitas fixas e expede os
produtos finais para clientes. Cada lote produzido consome lotes recentes (uma janela dos
últimos lotes de cada matéria-prima), o que reproduz a relação N:N da cadeia real — um lote
de leite cru vira vários lotes de queijo e iogurte, e cada lote de iogurte usa vários lotes de
leite — sem ligar tudo a tudo. A semente torna a base reproduzível.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .grafo.modelo import (
    PREFIXO_ID,
    Aresta,
    Evento,
    TipoAresta,
    TipoEvento,
    TipoVertice,
    Vertice,
)


@dataclass(frozen=True)
class MateriaPrima:
    nome: str
    unidade: str
    faixa_quantidade: tuple[float, float]
    fornecedores: tuple[str, ...]


@dataclass(frozen=True)
class Receita:
    produto: str
    tipo: TipoVertice
    unidade: str
    faixa_quantidade: tuple[float, float]
    entradas: tuple[str, ...]


# Nomes de fornecedores e clientes são fictícios.
INSUMOS: tuple[MateriaPrima, ...] = (
    MateriaPrima("Leite cru", "L", (2000, 8000), (
        "Fazenda Santa Luzia — Formosa/GO",
        "Fazenda Três Marias — Unaí/MG",
        "Sítio Boa Vista — Planaltina/DF",
    )),
    MateriaPrima("Trigo em grão", "kg", (5000, 20000), (
        "Cooperativa Vale do Paranã — Flores de Goiás/GO",
        "Fazenda Cerrado Alto — Luziânia/GO",
    )),
    MateriaPrima("Soja em grão", "kg", (8000, 30000), (
        "Fazenda Água Limpa — Cristalina/GO",
        "Fazenda Cerrado Alto — Luziânia/GO",
    )),
    MateriaPrima("Milho em grão", "kg", (8000, 30000), (
        "Fazenda Água Limpa — Cristalina/GO",
        "Cooperativa Vale do Paranã — Flores de Goiás/GO",
    )),
    MateriaPrima("Morango", "kg", (200, 900), (
        "Granja Recanto Verde — Brazlândia/DF",
        "Sítio Pé de Serra — Alexânia/GO",
    )),
    MateriaPrima("Cacau em pó", "kg", (100, 500), ("Cacaueira Sul da Bahia — Ilhéus/BA",)),
    MateriaPrima("Açúcar cristal", "kg", (1000, 5000), ("Usina Rio Claro — Goianésia/GO",)),
    MateriaPrima("Sal refinado", "kg", (200, 1000), ("Salineira Costa Branca — Mossoró/RN",)),
    MateriaPrima("Fermento biológico", "kg", (50, 200), ("Fermentos Planalto — Anápolis/GO",)),
    MateriaPrima("Embalagem plástica", "un", (5000, 20000), ("Plásticos Candango — Ceilândia/DF",)),
    MateriaPrima("Embalagem cartonada", "un", (5000, 20000), ("Embalagens Planalto — Anápolis/GO",)),
    MateriaPrima("Saco de ráfia", "un", (500, 2000), ("Embalagens Planalto — Anápolis/GO",)),
)

RECEITAS: tuple[Receita, ...] = (
    Receita("Leite pasteurizado", TipoVertice.INTERMEDIARIO, "L", (1500, 6000), ("Leite cru",)),
    Receita("Creme de leite", TipoVertice.INTERMEDIARIO, "kg", (100, 400), ("Leite cru",)),
    Receita("Farinha de trigo", TipoVertice.INTERMEDIARIO, "kg", (3000, 12000), ("Trigo em grão",)),
    Receita("Fubá", TipoVertice.INTERMEDIARIO, "kg", (3000, 12000), ("Milho em grão",)),
    Receita("Farelo de soja", TipoVertice.INTERMEDIARIO, "kg", (4000, 15000), ("Soja em grão",)),
    Receita("Óleo de soja", TipoVertice.INTERMEDIARIO, "L", (800, 3000), ("Soja em grão",)),
    Receita("Polpa de morango", TipoVertice.INTERMEDIARIO, "kg", (150, 700), ("Morango", "Açúcar cristal")),
    Receita("Massa base", TipoVertice.INTERMEDIARIO, "kg", (1000, 4000), (
        "Farinha de trigo", "Fermento biológico", "Sal refinado", "Óleo de soja",
    )),
    Receita("Queijo minas frescal", TipoVertice.PRODUTO_FINAL, "kg", (200, 800), (
        "Leite pasteurizado", "Sal refinado", "Embalagem plástica",
    )),
    Receita("Iogurte de morango", TipoVertice.PRODUTO_FINAL, "L", (500, 2000), (
        "Leite pasteurizado", "Polpa de morango", "Embalagem plástica",
    )),
    Receita("Manteiga", TipoVertice.PRODUTO_FINAL, "kg", (50, 300), (
        "Creme de leite", "Sal refinado", "Embalagem plástica",
    )),
    Receita("Achocolatado", TipoVertice.PRODUTO_FINAL, "L", (800, 3000), (
        "Leite pasteurizado", "Cacau em pó", "Açúcar cristal", "Embalagem cartonada",
    )),
    Receita("Pão de forma", TipoVertice.PRODUTO_FINAL, "un", (2000, 8000), ("Massa base", "Embalagem plástica")),
    Receita("Biscoito de milho", TipoVertice.PRODUTO_FINAL, "kg", (500, 2000), (
        "Fubá", "Açúcar cristal", "Óleo de soja", "Embalagem plástica",
    )),
    Receita("Ração para aves", TipoVertice.PRODUTO_FINAL, "kg", (3000, 12000), (
        "Fubá", "Farelo de soja", "Sal refinado", "Saco de ráfia",
    )),
)

DESTINOS: tuple[tuple[str, str], ...] = (
    ("Supermercado Central", "Asa Norte/DF"),
    ("Mercado Bom Preço", "Taguatinga/DF"),
    ("Atacado Planalto", "Anápolis/GO"),
    ("Distribuidora Cerrado", "Goiânia/GO"),
    ("Rede Pão Nosso", "Águas Claras/DF"),
    ("Empório da Serra", "Sobradinho/DF"),
    ("Hipermercado Alvorada", "Valparaíso de Goiás/GO"),
    ("Distribuidora Três Poderes", "Guará/DF"),
    ("Mercearia São José", "Ceilândia/DF"),
    ("Agropecuária Bom Pasto", "Formosa/GO"),
    ("Restaurante Universitário", "Asa Norte/DF"),
    ("Cozinha Industrial Candanga", "SIA/DF"),
)

_CIDADES_EXTRAS = (
    "Gama/DF", "Samambaia/DF", "Planaltina/DF", "Luziânia/GO", "Brazlândia/DF",
    "Recanto das Emas/DF", "Cristalina/GO", "Unaí/MG", "Santa Maria/DF", "Paranoá/DF",
)


@dataclass
class BaseSintetica:
    vertices: list[Vertice] = field(default_factory=list)
    arestas: list[Aresta] = field(default_factory=list)
    eventos: list[Evento] = field(default_factory=list)

    @property
    def num_lotes(self) -> int:
        return sum(1 for v in self.vertices if v.tipo.eh_lote)


def ordenar_receitas(receitas: tuple[Receita, ...] = RECEITAS) -> list[Receita]:
    """Ordena as receitas para que cada uma venha depois das que produzem suas entradas (Kahn)."""
    por_produto = {r.produto: r for r in receitas}
    dependentes: dict[str, list[str]] = defaultdict(list)
    grau = {r.produto: 0 for r in receitas}
    for receita in receitas:
        for entrada in receita.entradas:
            if entrada in por_produto:
                dependentes[entrada].append(receita.produto)
                grau[receita.produto] += 1
    fila = deque(produto for produto, g in grau.items() if g == 0)
    ordem: list[Receita] = []
    while fila:
        produto = fila.popleft()
        ordem.append(por_produto[produto])
        for dependente in dependentes[produto]:
            grau[dependente] -= 1
            if grau[dependente] == 0:
                fila.append(dependente)
    if len(ordem) != len(receitas):
        raise ValueError("As receitas formam um ciclo.")
    return ordem


def gerar_base(
    n_lotes: int = 300,
    n_destinos: int = 12,
    semente: int = 42,
    janela: int = 4,
    inicio: datetime | None = None,
    dias: int = 90,
) -> BaseSintetica:
    """Gera uma base com aproximadamente `n_lotes` lotes (destinos não entram na conta).

    `janela` é quantos lotes recentes de cada matéria-prima ficam disponíveis para consumo;
    `dias` é o horizonte aproximado da simulação (bases maiores têm mais lotes por dia).
    """
    if n_lotes < 1:
        raise ValueError("n_lotes deve ser positivo.")
    if n_destinos < 1:
        raise ValueError("n_destinos deve ser positivo.")

    rng = random.Random(semente)
    inicio = inicio or datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)
    base = BaseSintetica()
    contadores: dict[TipoVertice, int] = defaultdict(int)
    recentes: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=janela))
    proximo_evento = 1

    def novo_evento(tipo: TipoEvento, quando: datetime, descricao: str) -> Evento:
        nonlocal proximo_evento
        evento = Evento(proximo_evento, tipo, quando, descricao, "simulador")
        proximo_evento += 1
        base.eventos.append(evento)
        return evento

    def novo_id(tipo: TipoVertice) -> str:
        contadores[tipo] += 1
        return f"{PREFIXO_ID[tipo]}-{contadores[tipo]:06d}"

    # Destinos
    destinos: list[str] = []
    for i in range(n_destinos):
        if i < len(DESTINOS):
            nome, cidade = DESTINOS[i]
        else:
            nome, cidade = f"Cliente {i + 1:03d}", _CIDADES_EXTRAS[i % len(_CIDADES_EXTRAS)]
        evento = novo_evento(TipoEvento.CADASTRO, inicio, f"Cadastro do destino {nome}")
        vertice = Vertice(
            novo_id(TipoVertice.DESTINO), TipoVertice.DESTINO, nome,
            atributos={"cidade": cidade}, criado_em=inicio, evento_id=evento.id,
        )
        base.vertices.append(vertice)
        destinos.append(vertice.id)

    receitas = ordenar_receitas()
    lotes_por_ciclo = len(INSUMOS) + len(receitas)
    ciclos_por_dia = max(1, math.ceil(n_lotes / (lotes_por_ciclo * dias)))
    passo = timedelta(days=1) / ciclos_por_dia
    lotes = 0
    quando = inicio

    while lotes < n_lotes:
        # Recebimento dos insumos
        for materia in INSUMOS:
            if lotes >= n_lotes:
                break
            fornecedor = rng.choice(materia.fornecedores)
            evento = novo_evento(TipoEvento.CADASTRO, quando, f"Recebimento de {materia.nome}")
            vertice = Vertice(
                novo_id(TipoVertice.INSUMO), TipoVertice.INSUMO, materia.nome,
                quantidade=_quantidade(rng, materia.faixa_quantidade), unidade=materia.unidade,
                atributos={"fornecedor": fornecedor}, criado_em=quando, evento_id=evento.id,
            )
            base.vertices.append(vertice)
            recentes[materia.nome].append(vertice.id)
            lotes += 1

        # Produção: cada receita consome 1 ou 2 lotes recentes de cada entrada
        for receita in receitas:
            if lotes >= n_lotes:
                break
            momento = quando + passo / 2
            evento = novo_evento(TipoEvento.PRODUCAO, momento, f"Produção de {receita.produto}")
            vertice = Vertice(
                novo_id(receita.tipo), receita.tipo, receita.produto,
                quantidade=_quantidade(rng, receita.faixa_quantidade), unidade=receita.unidade,
                criado_em=momento, evento_id=evento.id,
            )
            base.vertices.append(vertice)
            for entrada in receita.entradas:
                disponiveis = recentes[entrada]
                escolhidos = rng.sample(list(disponiveis), k=min(len(disponiveis), rng.choice((1, 1, 2))))
                for lote_entrada in escolhidos:
                    base.arestas.append(Aresta(
                        lote_entrada, vertice.id, TipoAresta.COMPOSICAO,
                        quantidade=_quantidade(rng, (10, 500)), evento_id=evento.id,
                    ))
            recentes[receita.produto].append(vertice.id)
            lotes += 1

            # Expedição dos produtos finais para 1 a 3 destinos
            if receita.tipo is TipoVertice.PRODUTO_FINAL:
                envio = momento + passo / 4
                for destino in rng.sample(destinos, k=min(len(destinos), rng.randint(1, 3))):
                    evento_exp = novo_evento(TipoEvento.EXPEDICAO, envio, f"Expedição de {vertice.id}")
                    base.arestas.append(Aresta(
                        vertice.id, destino, TipoAresta.EXPEDICAO,
                        quantidade=round(vertice.quantidade * rng.uniform(0.2, 0.6), 1),
                        evento_id=evento_exp.id,
                    ))

        quando += passo

    return base


def _quantidade(rng: random.Random, faixa: tuple[float, float]) -> float:
    return round(rng.uniform(*faixa), 1)
