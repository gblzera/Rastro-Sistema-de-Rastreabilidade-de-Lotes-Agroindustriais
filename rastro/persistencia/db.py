"""Conexão com o banco. SQLite no desenvolvimento, PostgreSQL em produção, via DATABASE_URL."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine, event

URL_PADRAO = "sqlite:///rastro.db"


def url_do_banco(url: str | None = None) -> str:
    """Resolve a URL do banco e a adapta ao driver psycopg 3.

    Provedores como Render e Neon entregam URLs no formato postgres:// ou postgresql://.
    """
    url = url or os.environ.get("DATABASE_URL") or URL_PADRAO
    for prefixo in ("postgres://", "postgresql://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg://" + url[len(prefixo):]
    return url


def criar_engine(url: str | None = None, **opcoes) -> Engine:
    url = url_do_banco(url)
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False}, **opcoes)

        @event.listens_for(engine, "connect")
        def _ativar_chaves_estrangeiras(conexao, _registro):
            cursor = conexao.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True, **opcoes)


def descrever(engine: Engine) -> str:
    """Nome do dialeto e URL sem senha, para logs e para a tela de status."""
    return f"{engine.dialect.name} ({engine.url.render_as_string(hide_password=True)})"
