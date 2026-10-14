# Rastro — Sistema de Rastreabilidade de Lotes Agroindustriais

Projeto Integrador (CCO096) — IESB, 2026/2. Executor e gerente de projeto: Gabriel Henrique Kuhn Paz. Orientador: Roger Rocha Ferreira.

O Rastro registra a cadeia produtiva de uma agroindústria como um **grafo acíclico dirigido (DAG) construído em tempo de execução**. Lotes de insumo, intermediários e produtos finais são vértices; cada evento de produção cria arestas dos lotes de entrada para o lote produzido; cada expedição cria uma aresta do lote para o cliente que o recebeu. Sobre esse grafo, o sistema responde em microssegundos:

- **Recall**: um lote foi comprometido. O que foi produzido a partir dele e para onde foi enviado? (BFS descendente)
- **Auditoria de origem**: de quais lotes de insumo, e de quais fornecedores, veio este produto? (BFS ascendente)
- **Integridade**: a cada nova aresta, o sistema verifica se ela faria um lote virar ancestral de si mesmo e, se fizer, recusa a operação e mostra o ciclo.

## Como rodar

Requer Python 3.9 ou mais novo (o Python que já vem no macOS serve).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m rastro demo                 # prova de conceito do motor no terminal (CP1)
python -m rastro seed --lotes 200     # popula o banco (SQLite em rastro.db por padrão)
python -m rastro serve                # API + interface em http://127.0.0.1:8000
```

A documentação interativa da API fica em `http://127.0.0.1:8000/docs`.

### Com PostgreSQL

Defina `DATABASE_URL` (aceita os formatos `postgres://` e `postgresql://`):

```bash
export DATABASE_URL=postgresql://rastro:rastro@localhost/rastro
python -m rastro seed --lotes 200 --reset
python -m rastro serve
```

Para levar os dados do SQLite de desenvolvimento para o PostgreSQL:

```bash
python -m rastro migrar --de sqlite:///rastro.db --para postgresql://rastro:rastro@localhost/rastro
```

Com Docker, `docker compose up --build` sobe o PostgreSQL e a aplicação, já com 300 lotes sintéticos.

> O grafo vive em memória e é reconstruído a partir do banco quando a aplicação inicia. Por isso ela roda com **um único processo**, e um `seed --reset` feito com o servidor no ar só aparece depois de reiniciá-lo.

## Testes

```bash
python -m pytest                                    # SQLite
RASTRO_TEST_POSTGRES_URL=postgresql://rastro:rastro@localhost/rastro_teste python -m pytest   # + PostgreSQL
python -m rastro benchmark --sql postgresql://...   # testes de carga (ver docs/testes-de-carga.md)
```

O GitHub Actions roda a suíte contra SQLite e PostgreSQL 16 a cada push.

## Arquitetura

```mermaid
flowchart LR
  UI["Interface web<br/>(Cytoscape + dagre)"] -- JSON --> API["API FastAPI"]
  CLI["CLI<br/>demo · seed · benchmark"] --> SVC
  API --> SVC["ServicoRastro<br/>lock + transação"]
  SVC --> G["GrafoRastro<br/>DAG em memória"]
  SVC --> R["Repositorio<br/>SQLAlchemy"]
  R --> DB[("SQLite / PostgreSQL<br/>vertices · arestas · eventos")]
  R -- "reconstrução na inicialização" --> G
```

| Pasta | Conteúdo |
|---|---|
| `rastro/grafo/` | Motor: modelo, listas de adjacência, recall/origem (BFS), aciclicidade (Pearce-Kelly e DFS), Kahn |
| `rastro/persistencia/` | Tabelas (edge list), reconstrução do grafo, carga em massa, migração, CTE recursiva |
| `rastro/servico.py` | Operações de negócio; mantém grafo e banco consistentes |
| `rastro/api/` | Rotas HTTP e esquemas de validação |
| `rastro/sintetico.py` | Gerador da base sintética (receitas reais, fornecedores e clientes fictícios) |
| `rastro/benchmark.py` | Testes de carga |
| `web/` | Interface (HTML/CSS/JS sem build; bibliotecas em `web/vendor` para a demo funcionar offline) |
| `docs/` | Modelagem, testes de carga, manual de uso e acompanhamento dos checkpoints |

Detalhes do modelo e dos algoritmos estão em [docs/modelagem.md](docs/modelagem.md).

## API

| Método | Rota | O que faz |
|---|---|---|
| POST | `/api/insumos` | Recebimento de um lote de insumo |
| POST | `/api/destinos` | Cadastro de cliente/destino |
| POST | `/api/producoes` | Evento de produção: cria o lote de saída e uma aresta por entrada |
| POST | `/api/expedicoes` | Envio de um lote a um destino |
| POST | `/api/vinculos` | Vínculo entre lotes existentes (409 com o ciclo, se fecharia um) |
| GET | `/api/consultas/recall/{id}` | Fecho descendente: lotes, produtos e destinos afetados |
| GET | `/api/consultas/origem/{id}` | Fecho ascendente: cadeia de insumos e fornecedores |
| GET | `/api/vertices` · `/api/vertices/{id}` | Busca e detalhe de lotes |
| GET | `/api/grafo` · `/api/grafo/vizinhanca/{id}` | Grafo para visualização |
| GET | `/api/estatisticas` · `/api/eventos` · `/api/saude` | Indicadores, histórico e status |

## Andamento (EAP)

Veja [docs/checkpoints.md](docs/checkpoints.md) para o estado de cada pacote de trabalho e o roteiro de demonstração de cada checkpoint.

| Checkpoint | Data | Situação |
|---|---|---|
| CP1 — motor de grafos no terminal | 02/10 | Entregue (`python -m rastro demo`) |
| CP2 — motor integrado à API e à interface | 09/10 | Entregue |
| CP3 — aplicação minimamente operável | 16/10 | Entregue (PostgreSQL, visualização, base sintética) |
| CP4 — aplicação satisfatoriamente operável | 23/10 | Adiantado: destaque do subgrafo e testes de carga prontos |
| CP5 — aplicação completa e refinamento visual | 30/10 | Em andamento: manual, CI e arquivos de implantação prontos; falta publicar e refinar |
