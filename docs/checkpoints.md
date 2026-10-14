# Acompanhamento dos checkpoints

Pacote 1.1.3 da EAP. Situação em 14/10/2026.

## Pacotes de trabalho

| Código | Pacote | Checkpoint | Situação | Onde está |
|---|---|---|---|---|
| 1.1.1 | Termo de Abertura do Projeto | A1 (25/09) | Entregue | — |
| 1.1.2 | EAP e cronograma | A1 (25/09) | Entregue | — |
| 1.1.3 | Acompanhamento dos checkpoints | CP5 (30/10) | Em andamento | este documento |
| 1.2.1 | Modelo do grafo | CP1 (02/10) | Concluído | `rastro/grafo/modelo.py` |
| 1.2.2 | Motor com verificação de aciclicidade | CP1 (02/10) | Concluído | `rastro/grafo/motor.py` |
| 1.2.3 | Consultas de recall e origem | CP1 (02/10) | Concluído | `rastro/grafo/motor.py`, `python -m rastro demo` |
| 1.2.4 | API HTTP | CP2 (09/10) | Concluído | `rastro/api/` |
| 1.3.1 | Modelagem da edge list | CP2 (09/10) | Concluído | `rastro/persistencia/tabelas.py`, [modelagem](modelagem.md) |
| 1.3.2 | Reconstrução do grafo em memória | CP2 (09/10) | Concluído | `Repositorio.carregar_grafo` |
| 1.4.1 | Registro de lotes e eventos | CP2 (09/10) | Concluído | `web/`, aba Registrar |
| 1.3.3 | Migração para PostgreSQL | CP3 (16/10) | Concluído | `DATABASE_URL`, `python -m rastro migrar` |
| 1.4.2 | Visualização da rede | CP3 (16/10) | Concluído | `web/app.js` |
| 1.5.2 | Base sintética de porte crescente | CP3 (16/10) | Concluído | `rastro/sintetico.py`, `python -m rastro seed` |
| 1.4.3 | Destaque do subgrafo nas consultas | CP4 (23/10) | Concluído (adiantado) | `web/app.js` |
| 1.5.3 | Testes de carga no grafo | CP4 (23/10) | Concluído (adiantado) | `rastro/benchmark.py`, [resultados](testes-de-carga.md) |
| 1.4.4 | Refinamento visual da rede | CP5 (30/10) | Em andamento | — |
| 1.5.1 | Testes automatizados | CP5 (30/10) | 74 testes (89 execuções com PostgreSQL); CI no GitHub Actions | `tests/`, `.github/workflows/testes.yml` |
| 1.6.1 | Manual de uso | CP5 (30/10) | Primeira versão | [manual](manual.md) |
| 1.6.2 | Implantação da aplicação | CP5 (30/10) | Arquivos prontos; falta publicar | `Dockerfile`, `render.yaml`, `docker-compose.yml` |
| 1.6.3 | Seminário com demonstração ao vivo | 03/11–20/11 | A preparar | roteiro abaixo |

CP1 e CP2 foram entregues com atraso em relação ao calendário; o CP3 recupera o cronograma e os pacotes do CP4 foram adiantados.

## Roteiros de demonstração

### CP1 — motor no terminal

```bash
python -m rastro demo
```

Gera a base sintética, faz o recall de um lote de leite cru (níveis da BFS, produtos a recolher e destinos a notificar), a auditoria de origem de um produto (árvore de insumos e fornecedores) e tenta um vínculo que fecharia ciclo, que é recusado com o caminho do ciclo.

### CP2 e CP3 — aplicação integrada

```bash
export DATABASE_URL=postgresql://rastro:rastro@localhost/rastro
python -m rastro seed --lotes 200 --reset
python -m rastro serve
```

1. Mostrar no topo que o banco é PostgreSQL e os indicadores da base.
2. Registrar um insumo, uma produção com duas entradas e uma expedição. Mostrar o novo vértice na rede e os eventos.
3. Recall de `INS-000001`: destaque na rede, destinos e produtos no painel, tempo no servidor.
4. Origem de um produto final: fornecedores envolvidos.
5. Vínculo `PRD-000002` → `INT-000001`: recusado, com o ciclo desenhado.
6. Reiniciar o servidor e mostrar que o grafo é reconstruído do banco.

### CP4 — testes de carga

```bash
python -m rastro benchmark --sql $DATABASE_URL
```

Discutir as tabelas de [testes-de-carga.md](testes-de-carga.md): crescimento linear da reconstrução, recall estável em microssegundos, CTE recursiva entre 70 e 300 vezes mais lenta e o pior caso da DFS na cadeia linear.

## Próximos passos

- **Implantação (1.6.2)**: criar o banco gratuito no Neon, criar o serviço no Render a partir do `render.yaml` e informar `DATABASE_URL`. O banco vazio é populado com 300 lotes na primeira subida (`RASTRO_SEED_SE_VAZIO`).
- **Refinamento visual (1.4.4)**: animação do avanço da BFS por níveis no recall, rótulos com o nome do produto no subgrafo isolado e ajustes de contraste.
- **Manual (1.6.1)**: revisar com capturas da versão publicada.
- **Seminário (1.6.3)**: ensaiar o roteiro do CP2/CP3 sobre a versão publicada, com a demo local como plano B (funciona sem internet).
