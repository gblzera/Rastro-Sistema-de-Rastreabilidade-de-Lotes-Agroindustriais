import os

import pytest
from fastapi.testclient import TestClient

from rastro.api import criar_app
from rastro.persistencia import Repositorio, criar_engine
from rastro.servico import ServicoRastro

# Para rodar também contra PostgreSQL:
#   RASTRO_TEST_POSTGRES_URL=postgresql://usuario:senha@localhost/rastro_teste pytest
URL_POSTGRES = os.environ.get("RASTRO_TEST_POSTGRES_URL")
BANCOS = ["sqlite"] + (["postgresql"] if URL_POSTGRES else [])


@pytest.fixture(params=BANCOS)
def url_banco(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'teste.db'}"
        return
    repo = Repositorio(criar_engine(URL_POSTGRES))
    repo.apagar_esquema()
    yield URL_POSTGRES
    repo.apagar_esquema()
    repo.engine.dispose()


@pytest.fixture
def repo(url_banco):
    repositorio = Repositorio(criar_engine(url_banco))
    repositorio.criar_esquema()
    yield repositorio
    repositorio.engine.dispose()


@pytest.fixture
def servico(repo):
    s = ServicoRastro(repo)
    s.iniciar()
    return s


@pytest.fixture
def cliente(url_banco):
    with TestClient(criar_app(url_banco=url_banco)) as c:
        yield c
