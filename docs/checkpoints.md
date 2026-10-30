# Acompanhamento dos checkpoints

Pacote 1.1.3 da EAP. Situação em 30/10/2026, data do Checkpoint 5.

## Pacotes de trabalho

| Código | Pacote | Checkpoint | Situação | Onde está |
|---|---|---|---|---|
| 1.1.1 | Termo de Abertura do Projeto | A1 (25/09) | Entregue | — |
| 1.1.2 | EAP e cronograma | A1 (25/09) | Entregue | — |
| 1.1.3 | Acompanhamento dos checkpoints | CP5 (30/10) | Concluído | este documento |
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
| 1.4.4 | Refinamento visual da rede | CP5 (30/10) | Concluído | `web/`: estágios com título, consultas isoladas e animadas por nível da BFS, foco ao passar o mouse, guia de uso |
| 1.5.1 | Testes automatizados | CP5 (30/10) | Concluído: 75 testes (91 execuções com PostgreSQL), CI em Python 3.9 e 3.12 | `tests/`, `.github/workflows/testes.yml` |
| 1.6.1 | Manual de uso | CP5 (30/10) | Concluído | [manual](manual.md) |
| 1.6.2 | Implantação da aplicação | CP5 (30/10) | Configuração validada; publicação depende das contas no Render e no Neon | `render.yaml`, [guia de implantação](implantacao.md), `docker-compose.yml` |
| 1.6.3 | Seminário com demonstração ao vivo | 03/11–20/11 | Roteiro pronto | roteiro abaixo |

CP1 e CP2 foram entregues com atraso em relação ao calendário (em 14/10). O CP3 foi entregue no prazo e recuperou o cronograma, os pacotes do CP4 foram adiantados e o CP5 foi concluído em 30/10, faltando só publicar a aplicação.

## Roteiros de demonstração

### CP1 — motor no terminal

```bash
python -m rastro demo
```

Gera a base sintética, faz o recall de um lote de leite cru (níveis da BFS, produtos a recolher e destinos a notificar), a auditoria de origem de um produto (árvore de insumos e fornecedores) e tenta um vínculo que fecharia ciclo, que é recusado com o caminho do ciclo.

### CP2 a CP5 e seminário — aplicação integrada

```bash
export DATABASE_URL=postgresql://rastro:rastro@localhost/rastro   # opcional; sem isso usa SQLite
python -m rastro seed --lotes 200 --reset
python -m rastro serve
```

1. Mostrar no topo o banco em uso e os indicadores da base; a rede organizada por estágios da cadeia. Passar o mouse num lote para mostrar suas ligações.
2. No guia de uso, clicar em **Recall de INS-000001**: o subgrafo aparece isolado e acende nível por nível, e o painel diz quantos produtos recolher e quais destinos avisar. Depois, **Ver na rede completa**.
3. **Origem** do pão de forma sugerido no guia: insumos e fornecedores.
4. **Tentar um vínculo proibido**: o sistema recusa e desenha o ciclo.
5. Registrar uma produção com duas entradas e mostrar o vértice novo na rede e na aba Eventos.
6. Reiniciar o servidor e mostrar que o grafo é reconstruído do banco.

### CP4 — testes de carga

```bash
python -m rastro benchmark --sql $DATABASE_URL
```

Discutir as tabelas de [testes-de-carga.md](testes-de-carga.md): crescimento linear da reconstrução, recall estável em microssegundos, CTE recursiva entre 70 e 300 vezes mais lenta e o pior caso da DFS na cadeia linear.

## Pendências

- **Publicar (1.6.2)**: seguir o [guia de implantação](implantacao.md). A configuração foi validada numa cópia limpa do repositório, com e sem PostgreSQL, rodando o mesmo comando que o Render usa.
- **Seminário (1.6.3)**: ensaiar o roteiro acima na versão publicada, com a versão local como plano B (funciona sem internet).
