from fastapi.testclient import TestClient

from rastro.api import criar_app
from rastro.persistencia import Repositorio, criar_engine
from rastro.sintetico import gerar_base


def _post(cliente, rota, corpo, status=201):
    resposta = cliente.post(rota, json=corpo)
    assert resposta.status_code == status, resposta.text
    return resposta.json()


def _cadeia_basica(cliente):
    """leite -> pasteurizado -> queijo (+ sal) -> mercado"""
    leite = _post(cliente, "/api/insumos", {"nome": "Leite cru", "quantidade": 5000, "unidade": "L",
                                            "fornecedor": "Fazenda Santa Luzia"})
    sal = _post(cliente, "/api/insumos", {"nome": "Sal refinado", "quantidade": 300, "unidade": "kg"})
    mercado = _post(cliente, "/api/destinos", {"nome": "Supermercado Central", "cidade": "Asa Norte/DF"})
    pasteurizado = _post(cliente, "/api/producoes", {
        "tipo": "intermediario", "nome": "Leite pasteurizado",
        "entradas": [{"lote": leite["id"], "quantidade": 4800}],
    })["lote"]
    queijo = _post(cliente, "/api/producoes", {
        "tipo": "produto_final", "nome": "Queijo minas frescal", "quantidade": 400, "unidade": "kg",
        "entradas": [{"lote": pasteurizado["id"]}, {"lote": sal["id"], "quantidade": 8}],
    })["lote"]
    _post(cliente, "/api/expedicoes", {"lote": queijo["id"], "destino": mercado["id"], "quantidade": 150})
    return {"leite": leite, "sal": sal, "mercado": mercado, "pasteurizado": pasteurizado, "queijo": queijo}


def test_fluxo_completo_de_registro_e_consultas(cliente):
    c = _cadeia_basica(cliente)
    assert c["leite"]["id"] == "INS-000001"
    assert c["leite"]["atributos"] == {"fornecedor": "Fazenda Santa Luzia"}
    assert c["queijo"]["grau_entrada"] == 2

    recall = cliente.get(f"/api/consultas/recall/{c['leite']['id']}").json()
    assert recall["direcao"] == "descendente"
    assert recall["resumo"]["produto_final"] == [c["queijo"]["id"]]
    assert recall["resumo"]["destino"] == [c["mercado"]["id"]]
    assert recall["total_vertices"] == 4
    assert {v["id"]: v["nivel"] for v in recall["vertices"]}[c["mercado"]["id"]] == 3
    assert c["sal"]["id"] not in {v["id"] for v in recall["vertices"]}

    origem = cliente.get(f"/api/consultas/origem/{c['queijo']['id']}").json()
    assert set(origem["resumo"]["insumo"]) == {c["leite"]["id"], c["sal"]["id"]}
    assert origem["total_arestas"] == 3

    detalhe = cliente.get(f"/api/vertices/{c['queijo']['id']}").json()
    assert {a["origem"] for a in detalhe["entradas"]} == {c["pasteurizado"]["id"], c["sal"]["id"]}
    assert detalhe["saidas"][0]["tipo"] == "expedicao"

    estat = cliente.get("/api/estatisticas").json()
    assert estat["vertices"] == 5 and estat["arestas"] == 4
    assert estat["profundidade_maxima"] == 3


def test_vinculo_que_criaria_ciclo_e_rejeitado(cliente, url_banco):
    c = _cadeia_basica(cliente)
    soro = _post(cliente, "/api/producoes", {
        "tipo": "intermediario", "nome": "Soro de leite", "entradas": [{"lote": c["queijo"]["id"]}],
    })["lote"]
    resposta = cliente.post("/api/vinculos", json={"origem": soro["id"], "destino": c["pasteurizado"]["id"]})
    assert resposta.status_code == 409
    corpo = resposta.json()
    assert corpo["erro"] == "CicloDetectado"
    assert corpo["ciclo"] == [soro["id"], c["pasteurizado"]["id"], c["queijo"]["id"], soro["id"]]

    # nada foi gravado: nem em memória, nem no banco
    assert cliente.get("/api/estatisticas").json()["arestas"] == 5
    grafo_banco = Repositorio(criar_engine(url_banco)).carregar_grafo()
    assert grafo_banco.aresta(soro["id"], c["pasteurizado"]["id"]) is None

    # um vínculo válido é aceito
    sal2 = _post(cliente, "/api/insumos", {"nome": "Sal refinado"})
    ok = _post(cliente, "/api/vinculos", {"origem": sal2["id"], "destino": c["queijo"]["id"]})
    assert ok["evento"]["tipo"] == "ajuste"
    assert ok["aresta"]["tipo"] == "composicao"


def test_producao_com_entrada_inexistente_nao_deixa_rastro(cliente):
    _cadeia_basica(cliente)
    antes = cliente.get("/api/estatisticas").json()
    resposta = cliente.post("/api/producoes", json={
        "tipo": "produto_final", "id": "PRD-TESTE", "nome": "Manteiga",
        "entradas": [{"lote": "INS-000001"}, {"lote": "NAO-EXISTE"}],
    })
    assert resposta.status_code == 404
    assert cliente.get("/api/vertices/PRD-TESTE").status_code == 404
    depois = cliente.get("/api/estatisticas").json()
    assert (depois["vertices"], depois["arestas"]) == (antes["vertices"], antes["arestas"])
    assert all(ev["descricao"] != "Produção de Manteiga" for ev in cliente.get("/api/eventos").json())


def test_erros_de_validacao(cliente):
    c = _cadeia_basica(cliente)
    # sem entradas
    assert cliente.post("/api/producoes", json={"tipo": "intermediario", "nome": "X", "entradas": []}).status_code == 422
    # expedição para algo que não é destino
    r = cliente.post("/api/expedicoes", json={"lote": c["queijo"]["id"], "destino": c["pasteurizado"]["id"]})
    assert r.status_code == 422 and r.json()["erro"] == "RegraViolada"
    # aresta repetida
    r = cliente.post("/api/expedicoes", json={"lote": c["queijo"]["id"], "destino": c["mercado"]["id"]})
    assert r.status_code == 409
    # código duplicado e código inválido
    assert cliente.post("/api/insumos", json={"id": c["sal"]["id"], "nome": "Sal"}).status_code == 409
    assert cliente.post("/api/insumos", json={"id": "com espaço", "nome": "Sal"}).status_code == 422
    # consultas de vértice inexistente
    assert cliente.get("/api/consultas/recall/NAO-EXISTE").status_code == 404
    assert cliente.get("/api/consultas/outra/INS-000001").status_code == 422
    # quantidade negativa
    assert cliente.post("/api/insumos", json={"nome": "Sal", "quantidade": -1}).status_code == 422


def test_grafo_e_reconstruido_ao_reiniciar(url_banco):
    with TestClient(criar_app(url_banco=url_banco)) as cliente:
        c = _cadeia_basica(cliente)
        grafo_antes = cliente.get("/api/grafo").json()
    with TestClient(criar_app(url_banco=url_banco)) as cliente:
        grafo_depois = cliente.get("/api/grafo").json()
        assert {v["id"] for v in grafo_depois["vertices"]} == {v["id"] for v in grafo_antes["vertices"]}
        assert sorted((a["origem"], a["destino"]) for a in grafo_depois["arestas"]) == sorted(
            (a["origem"], a["destino"]) for a in grafo_antes["arestas"]
        )
        # a numeração automática continua de onde parou
        novo = _post(cliente, "/api/insumos", {"nome": "Leite cru"})
        assert novo["id"] == "INS-000003"
        recall = cliente.get(f"/api/consultas/recall/{c['leite']['id']}").json()
        assert recall["total_vertices"] == 4


def test_grafo_truncado_mantem_destinos_e_busca(url_banco):
    repo = Repositorio(criar_engine(url_banco))
    repo.criar_esquema()
    repo.inserir_base(gerar_base(300, n_destinos=12))
    with TestClient(criar_app(url_banco=url_banco)) as cliente:
        g = cliente.get("/api/grafo", params={"limite": 50}).json()
        assert g["truncado"] is True
        assert len(g["vertices"]) == 50
        assert sum(1 for v in g["vertices"] if v["tipo"] == "destino") == 12
        ids = {v["id"] for v in g["vertices"]}
        assert all(a["origem"] in ids and a["destino"] in ids for a in g["arestas"])

        viz = cliente.get("/api/grafo/vizinhanca/PRD-000001", params={"raio": 1}).json()
        assert "PRD-000001" in {v["id"] for v in viz["vertices"]}

        achados = cliente.get("/api/vertices", params={"q": "leite cru", "limite": 5}).json()
        assert len(achados) == 5 and all(v["nome"] == "Leite cru" for v in achados)
        destinos = cliente.get("/api/vertices", params={"tipo": "destino", "q": "asa norte"}).json()
        assert {v["nome"] for v in destinos} == {"Supermercado Central", "Restaurante Universitário"}

        eventos = cliente.get("/api/eventos", params={"limite": 5}).json()
        assert len(eventos) == 5


def test_eventos_registram_o_que_cada_operacao_criou(cliente):
    c = _cadeia_basica(cliente)
    eventos = cliente.get("/api/eventos").json()
    producao_queijo = next(ev for ev in eventos if ev["vertices"] == [c["queijo"]["id"]])
    assert producao_queijo["tipo"] == "producao"
    assert {a["origem"] for a in producao_queijo["arestas"]} == {c["pasteurizado"]["id"], c["sal"]["id"]}


def test_interface_web_e_servida(cliente):
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert "Rastro" in resposta.text
