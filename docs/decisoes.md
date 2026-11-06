# Decisões técnicas

Cada decisão, o motivo e a alternativa que ficou de fora. Os números vêm dos [testes de carga](testes-de-carga.md).

| Decisão | Por quê | O que descartamos |
|---|---|---|
| Grafo em memória, com listas de adjacência de saída e de entrada | Recall e origem custam o mesmo e levam microssegundos; guardar os dois sentidos gasta pouca memória (48 MB para 100 mil lotes) | Fazer as travessias no banco com `WITH RECURSIVE`: de 70 a 300 vezes mais lento |
| BFS para recall e origem | Entrega o nível de cada lote, que é a distância em etapas de produção, e é iterativa | DFS recursiva: não dá os níveis e pode estourar a pilha de recursão do Python |
| Ordem topológica dinâmica (Pearce e Kelly, 2006) | Toda produção nova é aceita em O(1); quando a ordem é violada, só a faixa afetada é examinada e reordenada | DFS antes de cada inserção: O(V + E) toda vez (cerca de 600 vezes mais lenta numa cadeia de 20 mil vértices) |
| Kahn ao reconstruir o grafo na subida | Valida o grafo inteiro de uma vez, em O(V + E); se houvesse ciclo no banco, a aplicação nem subiria | Checar ciclo aresta por aresta: O(E · (V + E)) |
| PostgreSQL guardando a lista de arestas | Durabilidade e transações; gratuito no Neon; SQLite no desenvolvimento trocando só a `DATABASE_URL` | Banco de grafos (Neo4j): custo, e a travessia viraria uma consulta pronta, escondendo os algoritmos que a disciplina avalia |
| Lock, transação e desfazer na memória | O grafo em memória e o banco nunca divergem, mesmo se o commit falhar (há teste para isso) | Gravar no banco e depois na memória sem proteção: uma falha no meio deixaria os dois diferentes |
| Um único processo no servidor | O grafo vive em memória, e um lock simples serializa as escritas; sobra para o porte do projeto | Vários processos exigiriam replicar o grafo entre eles (próximo passo) |
| Python e FastAPI | Rápido de escrever, valida as entradas sozinho e gera a documentação da API em `/docs`; roda no Python 3.9 do macOS | Uma API em Java ou Node: mais código para a mesma validação |
| Página sem etapa de build, com Cytoscape e bibliotecas no repositório | Menos peças; a demonstração funciona sem internet | Aplicação React com build: mais ferramentas para a mesma tela |
| Base sintética por receitas, com semente | Cadeia realista e relação N:N sem ligar tudo a tudo; a mesma semente recria o mesmo grafo | Dados reais de empresas, que o TAPDS excluiu, ou grafos aleatórios sem sentido de domínio |
| O F5 não muda o grafo; botão Gerar novo grafo | Num sistema de rastreabilidade, o registrado tem que persistir; gerar uma base nova é uma ação explícita | Sortear um grafo novo a cada carregamento da página |
| Render e Neon gratuitos | Orçamento zero, como o TAPDS fixou; cada envio à `main` publica sozinho | Servidor pago |
