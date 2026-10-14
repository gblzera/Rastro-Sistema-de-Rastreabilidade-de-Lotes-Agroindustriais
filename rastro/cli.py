"""Linha de comando do Rastro.

    python -m rastro demo                 prova de conceito do motor no terminal (CP1)
    python -m rastro seed --lotes 300     popula o banco com uma base sintética
    python -m rastro serve                sobe a API e a interface web
    python -m rastro recall INS-000001    recall de um lote gravado no banco
    python -m rastro origem PRD-000001    auditoria de origem de um lote gravado no banco
    python -m rastro migrar --de URL --para URL   copia os dados entre bancos
    python -m rastro benchmark            testes de carga sobre o grafo
"""

from __future__ import annotations

import argparse
import sys
import time

from .grafo import CicloDetectado, GrafoRastro, ResultadoTravessia, TipoVertice
from .sintetico import gerar_base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rastro", description="Rastro — rastreabilidade de lotes com DAG.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("demo", help="prova de conceito do motor de grafos no terminal")
    p.add_argument("--lotes", type=int, default=300)
    p.add_argument("--destinos", type=int, default=12)
    p.add_argument("--semente", type=int, default=42)
    p.add_argument("--lote", help="lote a usar no recall (padrão: o insumo de maior impacto)")
    p.set_defaults(funcao=_demo)

    p = sub.add_parser("seed", help="popula o banco com uma base sintética")
    p.add_argument("--lotes", type=int, default=300)
    p.add_argument("--destinos", type=int, default=12)
    p.add_argument("--semente", type=int, default=42)
    p.add_argument("--reset", action="store_true", help="apaga e recria as tabelas antes")
    p.add_argument("--banco", help="URL do banco (padrão: DATABASE_URL ou sqlite:///rastro.db)")
    p.set_defaults(funcao=_seed)

    p = sub.add_parser("serve", help="sobe a API e a interface web")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=8000)
    p.add_argument("--banco")
    p.add_argument("--reload", action="store_true")
    p.set_defaults(funcao=_serve)

    for nome, ajuda in (("recall", "lotes e destinos afetados por um lote"), ("origem", "cadeia de origem de um lote")):
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("lote")
        p.add_argument("--banco")
        p.set_defaults(funcao=_consulta, direcao=nome)

    p = sub.add_parser("migrar", help="copia todos os dados de um banco para outro")
    p.add_argument("--de", required=True, dest="origem", help="URL do banco de origem")
    p.add_argument("--para", required=True, dest="destino", help="URL do banco de destino (vazio)")
    p.set_defaults(funcao=_migrar)

    p = sub.add_parser("benchmark", help="testes de carga sobre o grafo")
    p.add_argument("--tamanhos", default="1000,10000,50000,100000")
    p.add_argument("--amostras", type=int, default=200)
    p.add_argument("--semente", type=int, default=42)
    p.add_argument("--sql", metavar="URL", help="compara também com CTE recursiva neste banco")
    p.add_argument("--saida", default="resultados", help="pasta para o CSV de resultados")
    p.set_defaults(funcao=_benchmark)

    args = parser.parse_args(argv)
    return args.funcao(args) or 0


# ------------------------------------------------------------------------ demo


def _demo(args) -> int:
    print("Rastro — prova de conceito do motor de grafos (Checkpoint 1)")
    print("=" * 64)

    inicio = time.perf_counter()
    base = gerar_base(args.lotes, args.destinos, args.semente)
    grafo = GrafoRastro()
    grafo.carregar(base.vertices, base.arestas)
    ms = (time.perf_counter() - inicio) * 1000
    est = grafo.estatisticas()
    por_tipo = est["vertices_por_tipo"]
    print(
        f"Base sintética (semente {args.semente}): {por_tipo['insumo']} lotes de insumo, "
        f"{por_tipo['intermediario']} intermediários, {por_tipo['produto_final']} produtos finais, "
        f"{por_tipo['destino']} destinos"
    )
    print(
        f"Grafo: {est['vertices']} vértices, {est['arestas']} arestas, cadeia mais longa com "
        f"{est['profundidade_maxima']} arestas — gerado e validado (Kahn) em {ms:.1f} ms"
    )

    # 1. Recall
    if args.lote:
        lote = args.lote
    else:
        candidatos = [v.id for v in grafo.vertices(TipoVertice.INSUMO) if v.nome == "Leite cru"]
        candidatos = candidatos or [v.id for v in grafo.vertices(TipoVertice.INSUMO)]
        lote = max(candidatos[:40], key=lambda c: len(grafo.recall(c).por_tipo[TipoVertice.PRODUTO_FINAL]))
    vertice = grafo.vertice(lote)
    print(f"\n[1] RECALL — o lote {lote} ({_rotulo(vertice)}) foi comprometido")
    resultado, tempo = _medir(lambda: grafo.recall(lote))
    print(f"    BFS descendente: {resultado.total_vertices} vértices alcançados em {tempo:.3f} ms")
    _imprimir_niveis(grafo, resultado)
    produtos = resultado.por_tipo[TipoVertice.PRODUTO_FINAL]
    destinos = resultado.por_tipo[TipoVertice.DESTINO]
    print(f"    Produtos finais a recolher ({len(produtos)}): " + ", ".join(produtos))
    print(f"    Destinos a notificar ({len(destinos)}):")
    for d in destinos:
        dv = grafo.vertice(d)
        print(f"      - {d} {dv.nome} ({dv.atributos.get('cidade', '')})")
    total_lotes = sum(1 for v in grafo.vertices() if v.tipo.eh_lote)
    afetados = sum(1 for v in resultado.niveis if grafo.vertice(v).tipo.eh_lote)
    print(f"    Recolhimento restrito a {afetados} de {total_lotes} lotes ({100 * afetados / total_lotes:.1f}%).")

    # 2. Origem
    produto = produtos[0] if produtos else next(grafo.vertices(TipoVertice.PRODUTO_FINAL)).id
    print(f"\n[2] AUDITORIA DE ORIGEM — de onde veio o lote {produto} ({grafo.vertice(produto).nome})?")
    origem, tempo = _medir(lambda: grafo.origem(produto))
    print(f"    BFS ascendente (travessia reversa): {origem.total_vertices} vértices em {tempo:.3f} ms")
    _imprimir_arvore_origem(grafo, produto)
    insumos = origem.por_tipo[TipoVertice.INSUMO]
    fornecedores = sorted({grafo.vertice(i).atributos.get("fornecedor", "?") for i in insumos})
    print(f"    {len(insumos)} lotes de insumo, de {len(fornecedores)} fornecedores: " + "; ".join(fornecedores))

    # 3. Aciclicidade
    print("\n[3] VERIFICAÇÃO DE ACICLICIDADE a cada inserção de aresta")
    ingrediente = next(
        (p for p in grafo.predecessores(produto) if grafo.vertice(p).tipo is TipoVertice.INTERMEDIARIO),
        None,
    )
    if ingrediente:
        print(f"    Tentativa: registrar que {produto} compôs {ingrediente}, que é ingrediente dele mesmo")
        try:
            grafo.adicionar_aresta(produto, ingrediente)
            print("    ERRO: a aresta foi aceita!")
            return 1
        except CicloDetectado as erro:
            print(f"    Rejeitada — {erro}")
    # vínculo válido: o produto também consumiu outro lote de um insumo que ele já usa
    alvo = next(v.id for v in grafo.vertices(TipoVertice.PRODUTO_FINAL) if v.id not in origem.niveis)
    ja_usados = grafo.origem(alvo).niveis
    nomes = {grafo.vertice(p).nome for p in grafo.predecessores(alvo) if grafo.vertice(p).tipo is TipoVertice.INSUMO}
    novo = next(
        (v.id for v in grafo.vertices(TipoVertice.INSUMO) if v.nome in nomes and v.id not in ja_usados),
        next(v.id for v in grafo.vertices(TipoVertice.INSUMO) if v.id not in ja_usados),
    )
    _, tempo = _medir(lambda: grafo.adicionar_aresta(novo, alvo))
    print(
        f"    Tentativa válida: outro lote de {grafo.vertice(novo).nome} ({novo}) também compôs {alvo} "
        f"— aceita em {tempo:.3f} ms"
    )
    grafo.ordem_topologica()

    print("\nTudo certo: o motor registra, consulta e protege o DAG. Veja também `python -m rastro benchmark`.")
    return 0


def _medir(funcao):
    inicio = time.perf_counter()
    resultado = funcao()
    return resultado, (time.perf_counter() - inicio) * 1000


def _rotulo(vertice) -> str:
    extra = vertice.atributos.get("fornecedor") or vertice.atributos.get("cidade")
    return f"{vertice.nome} — {extra}" if extra else vertice.nome


def _imprimir_niveis(grafo: GrafoRastro, resultado: ResultadoTravessia, limite: int = 8) -> None:
    por_nivel: dict[int, list[str]] = {}
    for vid, nivel in resultado.niveis.items():
        if nivel:
            por_nivel.setdefault(nivel, []).append(vid)
    for nivel, ids in sorted(por_nivel.items()):
        nomes = [f"{i} {grafo.vertice(i).nome}" for i in ids[:limite]]
        resto = f" (+{len(ids) - limite})" if len(ids) > limite else ""
        print(f"      nível {nivel}: " + ", ".join(nomes) + resto)


def _imprimir_arvore_origem(grafo: GrafoRastro, raiz: str) -> None:
    vistos: set[str] = set()

    def visitar(vid: str, prefixo: str, ultimo: bool, topo: bool) -> None:
        v = grafo.vertice(vid)
        ramo = "" if topo else ("└── " if ultimo else "├── ")
        repetido = vid in vistos
        sufixo = " (já listado acima)" if repetido else ""
        print(f"      {prefixo}{ramo}{vid} {_rotulo(v)}{sufixo}")
        if repetido:
            return
        vistos.add(vid)
        filhos = grafo.predecessores(vid)
        novo_prefixo = prefixo if topo else prefixo + ("    " if ultimo else "│   ")
        for i, filho in enumerate(filhos):
            visitar(filho, novo_prefixo, i == len(filhos) - 1, False)

    visitar(raiz, "", True, True)


# --------------------------------------------------------------- banco de dados


def _servico(url: str | None):
    from .persistencia import Repositorio, criar_engine
    from .servico import ServicoRastro

    servico = ServicoRastro(Repositorio(criar_engine(url)))
    servico.iniciar()
    return servico


def _seed(args) -> int:
    from .persistencia import Repositorio, criar_engine, descrever

    engine = criar_engine(args.banco)
    repo = Repositorio(engine)
    if args.reset:
        repo.apagar_esquema()
    repo.criar_esquema()
    if not repo.esta_vazio():
        print("O banco já tem dados. Use --reset para recriá-lo.", file=sys.stderr)
        return 1
    base = gerar_base(args.lotes, args.destinos, args.semente)
    inicio = time.perf_counter()
    repo.inserir_base(base)
    print(
        f"Base gravada em {descrever(engine)}: {len(base.vertices)} vértices, "
        f"{len(base.arestas)} arestas, {len(base.eventos)} eventos "
        f"({time.perf_counter() - inicio:.1f} s)"
    )
    return 0


def _consulta(args) -> int:
    from .grafo import ErroGrafo

    servico = _servico(args.banco)
    try:
        consulta = servico.consultar(args.lote, args.direcao)
    except ErroGrafo as erro:
        print(erro, file=sys.stderr)
        return 1
    grafo, resultado = servico.grafo, consulta.resultado
    print(f"{args.direcao} de {args.lote}: {resultado.total_vertices} vértices em {consulta.tempo_ms:.3f} ms")
    _imprimir_niveis(grafo, resultado, limite=20)
    for tipo in TipoVertice:
        ids = resultado.por_tipo[tipo]
        if ids:
            print(f"  {tipo.value} ({len(ids)}): " + ", ".join(ids))
    return 0


def _serve(args) -> int:
    import os

    import uvicorn

    if args.banco:
        os.environ["DATABASE_URL"] = args.banco
    uvicorn.run("rastro.api.app:app", host=args.host, port=args.porta, reload=args.reload)
    return 0


def _migrar(args) -> int:
    from .persistencia import Repositorio, criar_engine, descrever

    origem = Repositorio(criar_engine(args.origem))
    destino = Repositorio(criar_engine(args.destino))
    print(f"Copiando {descrever(origem.engine)} -> {descrever(destino.engine)}")
    contagem = origem.copiar_para(destino)
    for tabela, total in contagem.items():
        print(f"  {tabela}: {total} linhas")
    # garante que o destino reconstrói um DAG válido com os mesmos números
    grafo_origem, grafo_destino = origem.carregar_grafo(), destino.carregar_grafo()
    if (grafo_origem.num_vertices, grafo_origem.num_arestas) != (grafo_destino.num_vertices, grafo_destino.num_arestas):
        print("ERRO: o grafo reconstruído no destino difere da origem.", file=sys.stderr)
        return 1
    print(f"Grafo reconstruído no destino: {grafo_destino.num_vertices} vértices, {grafo_destino.num_arestas} arestas. OK.")
    return 0


def _benchmark(args) -> int:
    from .benchmark import executar

    tamanhos = [int(t) for t in args.tamanhos.split(",") if t.strip()]
    executar(tamanhos, amostras=args.amostras, semente=args.semente, url_sql=args.sql, pasta=args.saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
