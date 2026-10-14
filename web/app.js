/* Rastro — interface web. Conversa com a API em /api e desenha o DAG com Cytoscape + dagre. */

const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
const $$ = (seletor, raiz = document) => [...raiz.querySelectorAll(seletor)];

const NOME_TIPO = {
  insumo: "Insumo",
  intermediario: "Intermediário",
  produto_final: "Produto final",
  destino: "Destino",
};
const FORMA = {
  insumo: "barrel",
  intermediario: "round-rectangle",
  produto_final: "cut-rectangle",
  destino: "round-pentagon",
};
const ROTA_REGISTRO = {
  "form-insumo": "/api/insumos",
  "form-producao": "/api/producoes",
  "form-expedicao": "/api/expedicoes",
  "form-destino": "/api/destinos",
  "form-vinculo": "/api/vinculos",
};

const fmtNumero = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const fmtData = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });
const semMovimento = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const estado = {
  cy: null,
  consulta: null,
  isolado: false,
  truncado: false,
  totalVertices: 0,
};

// ------------------------------------------------------------------ utilidades

function h(tag, atributos = {}, ...filhos) {
  const el = document.createElement(tag);
  for (const [chave, valor] of Object.entries(atributos)) {
    if (valor === false || valor == null) continue;
    if (chave === "class") el.className = valor;
    else if (chave.startsWith("on")) el.addEventListener(chave.slice(2), valor);
    else el.setAttribute(chave, valor === true ? "" : valor);
  }
  for (const filho of filhos.flat(Infinity)) {
    if (filho == null || filho === false) continue;
    el.append(filho instanceof Node ? filho : document.createTextNode(String(filho)));
  }
  return el;
}

function etiqueta(id, tipo) {
  return h("span", { class: `etiqueta t-${tipo}` }, id);
}

function extraDe(v) {
  return v.atributos?.fornecedor || v.atributos?.cidade || "";
}

function fmtMs(ms) {
  return ms < 1 ? `${fmtNumero.format(ms * 1000)} µs` : `${fmtNumero.format(ms)} ms`;
}

class ErroApi extends Error {
  constructor(status, corpo) {
    let mensagem = `Erro ${status}`;
    if (typeof corpo?.detail === "string") mensagem = corpo.detail;
    else if (Array.isArray(corpo?.detail)) {
      mensagem = corpo.detail.map((e) => `${e.loc.slice(1).join(".") || "corpo"}: ${e.msg}`).join("; ");
    }
    super(mensagem);
    this.status = status;
    this.corpo = corpo;
  }
}

async function api(caminho, { corpo, ...opcoes } = {}) {
  const resposta = await fetch(caminho, {
    headers: { "Content-Type": "application/json" },
    ...opcoes,
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const dados = await resposta.json().catch(() => null);
  if (!resposta.ok) throw new ErroApi(resposta.status, dados);
  return dados;
}

let temporizadorToast;
function avisar(mensagem) {
  const toast = $("#toast");
  toast.textContent = mensagem;
  toast.hidden = false;
  clearTimeout(temporizadorToast);
  temporizadorToast = setTimeout(() => (toast.hidden = true), 3500);
}

// ------------------------------------------------------------------ rede (Cytoscape)

function cor(token) {
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim();
}

function estiloRede() {
  const c = {
    insumo: cor("--c-insumo"),
    intermediario: cor("--c-intermediario"),
    produto_final: cor("--c-produto"),
    destino: cor("--c-destino"),
    ink: cor("--ink"),
    ink2: cor("--ink-2"),
    ink3: cor("--ink-3"),
    aresta: cor("--c-aresta"),
    recall: cor("--c-recall"),
    origem: cor("--c-origem"),
    bg: cor("--bg"),
  };
  // A ordem importa: no Cytoscape, uma regra posterior sobrescreve as anteriores.
  return [
    {
      selector: "node",
      style: {
        "background-color": (n) => c[n.data("tipo")] || c.bg,
        shape: (n) => FORMA[n.data("tipo")] || "rectangle",
        width: 22,
        height: 15,
        label: "data(id)",
        "font-family": "IBM Plex Mono, ui-monospace, monospace",
        "font-size": 8,
        color: c.ink,
        "text-valign": "bottom",
        "text-margin-y": 3,
        "text-background-color": c.bg,
        "text-background-opacity": 0.75,
        "text-background-padding": 1,
        "min-zoomed-font-size": 7,
        "border-color": c.ink,
        "border-width": 0,
      },
    },
    { selector: 'node[tipo = "destino"]', style: { width: 26, height: 22 } },
    // subgrafos pequenos (consultas, vizinhança): nós maiores com código e nome
    {
      selector: "node.detalhado",
      style: {
        width: 30,
        height: 20,
        label: "data(rotulo2)",
        "text-wrap": "wrap",
        "text-max-width": 140,
        "font-size": 10,
        "text-margin-y": 4,
        "min-zoomed-font-size": 0,
      },
    },
    { selector: 'node.detalhado[tipo = "destino"]', style: { width: 32, height: 26 } },
    {
      selector: "node.rotulo-coluna",
      style: {
        "background-opacity": 0,
        "border-width": 0,
        width: 1,
        height: 1,
        label: "data(rotulo)",
        "text-valign": "center",
        "font-family": "Barlow Semi Condensed, Arial Narrow, sans-serif",
        "font-size": 15,
        "font-weight": 600,
        color: c.ink3,
        "text-transform": "uppercase",
        "text-background-opacity": 0,
        "min-zoomed-font-size": 0,
        events: "no",
      },
    },
    {
      selector: "edge",
      style: {
        width: 1,
        opacity: 0.5,
        "line-color": c.aresta,
        "target-arrow-color": c.aresta,
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.6,
        "curve-style": "bezier",
      },
    },
    { selector: 'edge[tipo = "expedicao"]', style: { "line-style": "dashed" } },
    { selector: ".apagado", style: { opacity: 0.08 } },
    { selector: "node.realce-recall", style: { "border-width": 2.5, "border-color": c.recall } },
    { selector: "edge.realce-recall", style: { width: 2.2, opacity: 1, "line-color": c.recall, "target-arrow-color": c.recall } },
    { selector: "node.realce-origem", style: { "border-width": 2.5, "border-color": c.origem } },
    { selector: "edge.realce-origem", style: { width: 2.2, opacity: 1, "line-color": c.origem, "target-arrow-color": c.origem } },
    { selector: "node.raiz", style: { width: 34, height: 26, "border-width": 4, "font-weight": "bold" } },
    // níveis da BFS que ainda não "acenderam" na animação
    { selector: ".pendente", style: { opacity: 0.12 } },
    { selector: "node.ciclo", style: { "border-width": 3, "border-style": "dashed", "border-color": c.recall } },
    { selector: "edge.ciclo", style: { width: 3, opacity: 1, "line-color": c.recall, "target-arrow-color": c.recall } },
    {
      selector: "edge.tentativa",
      style: {
        width: 3,
        opacity: 1,
        "line-style": "dashed",
        "line-color": c.recall,
        "target-arrow-color": c.recall,
        "target-arrow-shape": "tee",
        "curve-style": "unbundled-bezier",
        "control-point-distances": 60,
        label: "data(rotulo)",
        "font-size": 9,
        color: c.recall,
        "text-background-color": c.bg,
        "text-background-opacity": 1,
      },
    },
    // foco ao passar o mouse: o lote, seus vizinhos diretos e as arestas entre eles
    { selector: ".hover-apagado", style: { opacity: 0.07 } },
    { selector: ".hover-vizinho", style: { opacity: 1 } },
    { selector: "edge.hover-aresta", style: { width: 2, "line-color": c.ink2, "target-arrow-color": c.ink2 } },
    { selector: "node.hover-foco", style: { "border-width": 3, "border-color": c.ink } },
    { selector: "node.rotulo-coluna", style: { opacity: 1 } },
    { selector: "node:selected", style: { "overlay-color": c.ink, "overlay-opacity": 0.18, "overlay-padding": 5 } },
  ];
}

function iniciarRede() {
  estado.cy = cytoscape({
    container: $("#rede"),
    style: estiloRede(),
    minZoom: 0.03,
    maxZoom: 4,
    boxSelectionEnabled: false,
  });
  estado.cy.on("tap", "node", (evento) => selecionar(evento.target.id()));
  estado.cy.on("tap", (evento) => {
    if (evento.target === estado.cy) fecharDetalhe();
  });
  estado.cy.on("mouseover", "node.no", (evento) => focarHover(evento.target));
  estado.cy.on("mouseout", "node.no", limparHover);
  estado.cy.on("viewport", () => ($("#dica-rede").hidden = true));
  const atualizarEstilo = () => estado.cy.style(estiloRede());
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", atualizarEstilo);
  new MutationObserver(atualizarEstilo).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
}

function elementos(vertices, arestas, detalhado) {
  return [
    ...vertices.map((v) => ({
      group: "nodes",
      classes: detalhado ? "no detalhado" : "no",
      data: { id: v.id, tipo: v.tipo, nome: v.nome, extra: extraDe(v), rotulo2: `${v.id}\n${v.nome}` },
    })),
    ...arestas.map((a) => ({
      group: "edges",
      data: { id: `${a.origem}->${a.destino}`, source: a.origem, target: a.destino, tipo: a.tipo },
    })),
  ];
}

// Acima deste tamanho a rede usa o layout em blocos; abaixo, o dagre (camadas) fica legível.
const LIMITE_DAGRE = 120;

function desenhar(vertices, arestas) {
  const cy = estado.cy;
  const visaoGeral = vertices.length > LIMITE_DAGRE;
  const blocos = visaoGeral ? posicoesEmBlocos(vertices, arestas) : null;
  limparHover();
  cy.batch(() => {
    cy.elements().remove();
    cy.add(elementos(vertices, arestas, !visaoGeral));
    if (blocos) {
      cy.add(blocos.rotulos.map((r) => ({
        group: "nodes", classes: "rotulo-coluna", data: { id: r.id, rotulo: r.texto },
        position: { x: r.x, y: r.y }, selectable: false, grabbable: false,
      })));
    }
  });
  if (blocos) {
    cy.layout({ name: "preset", positions: blocos.posicoes, fit: false, animate: false }).run();
  } else {
    cy.layout({ name: "dagre", rankDir: "LR", nodeSep: 34, edgeSep: 8, rankSep: 170, fit: false, animate: false }).run();
  }
  enquadrar(cy.elements(), { zoomMaximo: 1.5, animar: false });
}

function focarHover(no) {
  const cy = estado.cy;
  cy.batch(() => {
    no.addClass("hover-foco");
    // explorando a rede, acende só o lote e seus vizinhos; com uma consulta na tela, não mexe nela
    if (!estado.consulta) {
      const vizinhanca = no.closedNeighborhood();
      cy.elements().not(vizinhanca).not(".rotulo-coluna").addClass("hover-apagado");
      vizinhanca.addClass("hover-vizinho");
      vizinhanca.edges().addClass("hover-aresta");
    }
  });
  const d = no.data();
  const qtd = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
  const dica = $("#dica-rede");
  dica.replaceChildren(
    ...[
      h("span", { class: "pilula" }, NOME_TIPO[d.tipo]),
      h("strong", {}, etiqueta(d.id, d.tipo), " ", d.nome),
      d.extra ? h("span", {}, d.extra) : null,
      h("span", { class: "sub" },
        `${qtd(no.indegree(false), "entrada", "entradas")} e ${qtd(no.outdegree(false), "saída", "saídas")} nesta vista · clique para detalhes`),
    ].filter(Boolean)
  );
  const p = no.renderedPosition();
  dica.style.left = `${Math.max(8, Math.min(p.x + 20, cy.width() - 270))}px`;
  dica.style.top = `${Math.max(8, Math.min(p.y - 12, cy.height() - 110))}px`;
  dica.hidden = false;
}

function limparHover() {
  if (!estado.cy) return;
  estado.cy.elements().removeClass("hover-apagado hover-vizinho hover-aresta hover-foco");
  $("#dica-rede").hidden = true;
}

/* Layout da visão geral: uma coluna-bloco por estágio da cadeia (profundidade a partir dos
   insumos, com todos os destinos no último bloco). Dentro do bloco os lotes seguem a ordem de
   registro, de cima para baixo e depois na sub-coluna seguinte. O número de linhas é escolhido
   para que o desenho tenha a proporção da tela. */
function posicoesEmBlocos(vertices, arestas) {
  const entradas = new Map(vertices.map((v) => [v.id, []]));
  const saidas = new Map(vertices.map((v) => [v.id, []]));
  for (const a of arestas) {
    entradas.get(a.destino)?.push(a.origem);
    saidas.get(a.origem)?.push(a.destino);
  }
  // profundidade = caminho mais longo a partir de uma fonte (Kahn sobre o subgrafo carregado)
  const grau = new Map(vertices.map((v) => [v.id, entradas.get(v.id).length]));
  const fila = vertices.filter((v) => grau.get(v.id) === 0).map((v) => v.id);
  const profundidade = new Map(fila.map((id) => [id, 0]));
  for (let i = 0; i < fila.length; i++) {
    const atual = fila[i];
    for (const prox of saidas.get(atual)) {
      profundidade.set(prox, Math.max(profundidade.get(prox) ?? 0, profundidade.get(atual) + 1));
      grau.set(prox, grau.get(prox) - 1);
      if (grau.get(prox) === 0) fila.push(prox);
    }
  }
  const tipoDe = new Map(vertices.map((v) => [v.id, v.tipo]));
  const maxLote = Math.max(0, ...vertices.filter((v) => v.tipo !== "destino").map((v) => profundidade.get(v.id) ?? 0));
  const estagios = [];
  for (const v of vertices) {
    const e = tipoDe.get(v.id) === "destino" ? maxLote + 1 : profundidade.get(v.id) ?? 0;
    (estagios[e] ||= []).push(v);
  }
  const nomeEstagio = (e) => (e === 0 ? "Insumos" : e === maxLote + 1 ? "Destinos" : `${e}ª transformação`);
  const blocos = estagios.map((itens, e) => itens && { e, itens }).filter(Boolean);
  for (const { itens } of blocos) itens.sort((a, b) => (a.criado_em < b.criado_em ? -1 : a.criado_em > b.criado_em ? 1 : a.id < b.id ? -1 : 1));

  const celulaX = 60;
  const celulaY = 26;
  const vao = 150;
  const caixa = $("#rede").getBoundingClientRect();
  const proporcao = Math.max(0.6, (caixa.width || 1000) / (caixa.height || 700));
  const maior = Math.max(...blocos.map((b) => b.itens.length));
  let linhas = maior;
  let melhor = Infinity;
  for (let r = 1; r <= maior; r++) {
    const largura = blocos.reduce((soma, b) => soma + Math.ceil(b.itens.length / r) * celulaX, 0) + vao * (blocos.length - 1);
    const erro = Math.abs(Math.log(largura / (r * celulaY) / proporcao));
    if (erro < melhor) [melhor, linhas] = [erro, r];
  }

  const posicoes = {};
  const rotulos = [];
  let x = 0;
  for (const { e, itens } of blocos) {
    const colunas = Math.ceil(itens.length / linhas);
    const linhasBloco = Math.ceil(itens.length / colunas);
    const deslocY = ((linhas - linhasBloco) * celulaY) / 2;
    itens.forEach((v, i) => {
      posicoes[v.id] = { x: x + Math.floor(i / linhasBloco) * celulaX, y: deslocY + (i % linhasBloco) * celulaY };
    });
    rotulos.push({ id: `__estagio-${e}`, texto: nomeEstagio(e), x: x + ((colunas - 1) * celulaX) / 2, y: -50 });
    x += colunas * celulaX + vao;
  }
  for (const r of rotulos) posicoes[r.id] = { x: r.x, y: r.y };
  return { posicoes, rotulos };
}

async function carregarRede() {
  const dados = await api("/api/grafo?limite=1500");
  estado.truncado = dados.truncado;
  estado.totalVertices = dados.total_vertices;
  estado.isolado = false;
  desenhar(dados.vertices, dados.arestas);
  if (!dados.total_vertices) {
    mostrarFaixa("O banco está vazio. Registre um insumo ou rode python -m rastro seed.");
  } else if (dados.truncado) {
    mostrarFaixa(
      `Mostrando ${fmtNumero.format(dados.vertices.length)} de ${fmtNumero.format(dados.total_vertices)} vértices ` +
        "(destinos e lotes mais recentes). Consultas e a busca abrem qualquer parte da rede."
    );
  } else {
    esconderFaixa();
  }
}

function mostrarFaixa(texto, tipo = "") {
  const faixa = $("#faixa-estado");
  faixa.className = `faixa-estado ${tipo}`;
  faixa.textContent = texto;
  faixa.hidden = false;
}

function esconderFaixa() {
  $("#faixa-estado").hidden = true;
}

// Enquadra a coleção sem passar de um zoom confortável (subgrafos pequenos não viram close-up)
// e deixando livres a barra de busca e a faixa de status no topo e a legenda embaixo.
function enquadrar(colecao, { zoomMaximo = 1.4, animar = true } = {}) {
  const cy = estado.cy;
  const alvo = colecao && colecao.nonempty() ? colecao : cy.elements();
  if (alvo.empty()) return;
  const caixa = alvo.boundingBox();
  const margem = { topo: 112, base: 64, lado: 40 };
  const largura = cy.width() - 2 * margem.lado;
  const altura = cy.height() - margem.topo - margem.base;
  const zoom = Math.max(
    cy.minZoom(),
    Math.min(zoomMaximo, largura / Math.max(caixa.w, 1), altura / Math.max(caixa.h, 1))
  );
  const pan = {
    x: margem.lado + largura / 2 - zoom * (caixa.x1 + caixa.w / 2),
    y: margem.topo + altura / 2 - zoom * (caixa.y1 + caixa.h / 2),
  };
  if (animar && !semMovimento()) cy.animate({ zoom, pan }, { duration: 350 });
  else cy.viewport({ zoom, pan });
}

function subgrafoNaRede(vertices, arestas) {
  const cy = estado.cy;
  let colecao = cy.collection();
  for (const v of vertices) colecao = colecao.union(cy.getElementById(v.id));
  for (const a of arestas) colecao = colecao.union(cy.getElementById(`${a.origem}->${a.destino}`));
  return colecao;
}

let temporizadoresNivel = [];

function limparClasses() {
  temporizadoresNivel.forEach(clearTimeout);
  temporizadoresNivel = [];
  estado.cy.remove(".tentativa");
  estado.cy.elements().removeClass("apagado realce-recall realce-origem raiz ciclo pendente");
}

function esconderBotoesDestaque() {
  estado.consulta = null;
  $("#btn-limpar").hidden = true;
  $("#btn-isolar").hidden = true;
}

// Consultas pequenas aparecem isoladas (legíveis); as grandes, destacadas na rede inteira.
const LIMITE_ISOLADO = 120;

async function mostrarConsulta(consulta, onde = consulta.vertices.length <= LIMITE_ISOLADO ? "isolado" : "rede") {
  const faltando = () => consulta.vertices.some((v) => estado.cy.getElementById(v.id).empty());
  if (onde === "rede" && (estado.isolado || faltando())) await carregarRede();
  if (onde === "isolado" || faltando()) {
    estado.isolado = true;
    desenhar(consulta.vertices, consulta.arestas);
  }
  destacarConsulta(consulta);
}

function destacarConsulta(consulta) {
  const cy = estado.cy;
  const recall = consulta.tipo === "recall";
  const classe = recall ? "realce-recall" : "realce-origem";
  // agrupa vértices e arestas pelo nível da BFS; uma aresta acende junto com a ponta mais distante
  const nivelDe = new Map(consulta.vertices.map((v) => [v.id, v.nivel]));
  const porNivel = [];
  const guardar = (nivel, el) => {
    if (el.nonempty()) (porNivel[nivel] ||= cy.collection()).merge(el);
  };
  for (const v of consulta.vertices) guardar(v.nivel, cy.getElementById(v.id));
  for (const a of consulta.arestas) {
    guardar(Math.max(nivelDe.get(a.origem), nivelDe.get(a.destino)), cy.getElementById(`${a.origem}->${a.destino}`));
  }
  const sub = porNivel.reduce((acc, c) => (c ? acc.union(c) : acc), cy.collection());
  cy.batch(() => {
    limparClasses();
    if (!estado.isolado) cy.elements().addClass("apagado");
    sub.removeClass("apagado").addClass(classe);
    cy.getElementById(consulta.raiz).addClass("raiz");
    porNivel.forEach((c, n) => n > 0 && c && c.addClass("pendente"));
  });
  const intervalo = semMovimento() ? 0 : 700;
  porNivel.forEach((c, n) => {
    if (n > 0 && c) temporizadoresNivel.push(setTimeout(() => c.removeClass("pendente"), n * intervalo));
  });
  enquadrar(sub);
  mostrarFaixa(
    `${recall ? "Recall" : "Origem"} de ${consulta.raiz}: ${consulta.total_vertices} vértices em ${fmtMs(consulta.tempo_ms)}. ` +
      "Os níveis acendem na ordem em que a busca em largura os encontra.",
    consulta.tipo
  );
  $("#btn-limpar").hidden = false;
  $("#btn-isolar").hidden = false;
  $("#btn-isolar").textContent = estado.isolado ? "Ver na rede completa" : "Isolar subgrafo";
}

async function limparDestaque() {
  esconderBotoesDestaque();
  renderIntro();
  if (estado.isolado) await carregarRede();
  else {
    limparClasses();
    if (estado.truncado) await carregarRede();
    else esconderFaixa();
    enquadrar();
  }
}

async function alternarIsolamento() {
  if (!estado.consulta) return;
  await mostrarConsulta(estado.consulta, estado.isolado ? "rede" : "isolado");
}

function destacarCiclo(ciclo) {
  const cy = estado.cy;
  limparClasses();
  let colecao = cy.collection();
  ciclo.forEach((id, i) => {
    colecao = colecao.union(cy.getElementById(id));
    if (i > 0) colecao = colecao.union(cy.getElementById(`${ciclo[i - 1]}->${id}`));
  });
  if (colecao.empty()) return;
  cy.elements().addClass("apagado");
  colecao.removeClass("apagado").addClass("ciclo");
  // a aresta recusada não existe no grafo; ela é desenhada só para mostrar onde fecharia o ciclo
  cy.add({
    group: "edges",
    classes: "tentativa",
    data: { id: "tentativa", source: ciclo[0], target: ciclo[1], rotulo: "recusada" },
  });
  enquadrar(colecao);
  mostrarFaixa(`Vínculo recusado: fecharia o ciclo ${ciclo.join(" → ")}`, "recall");
  $("#btn-limpar").hidden = false;
}

// ------------------------------------------------------------------ consultas

async function consultar(tipo, id) {
  id = (id || "").trim();
  if (!id) return;
  try {
    const consulta = await api(`/api/consultas/${tipo}/${encodeURIComponent(id)}`);
    estado.consulta = consulta;
    mostrarAba("consultar");
    $("#consulta-lote").value = consulta.raiz;
    renderResultado(consulta);
    await mostrarConsulta(consulta);
  } catch (erro) {
    avisar(erro.message);
  }
}

function itemLista(v, sub) {
  return h(
    "li",
    {},
    h(
      "button",
      { type: "button", onclick: () => focar(v.id) },
      etiqueta(v.id, v.tipo),
      h("span", {}, v.nome),
      sub ? h("span", { class: "sub" }, sub) : null
    )
  );
}

function grupo(titulo, itens, montarSub) {
  if (!itens.length) return null;
  return h(
    "section",
    { class: "grupo" },
    h("h3", {}, titulo, h("span", { class: "contagem" }, String(itens.length))),
    h("ul", { class: "lista" }, itens.map((v) => itemLista(v, montarSub(v))))
  );
}

function renderResultado(consulta) {
  const porId = new Map(consulta.vertices.map((v) => [v.id, v]));
  const doTipo = (tipo) => consulta.resumo[tipo].map((id) => porId.get(id));
  const nivel = (v) => (v.nivel ? `nível ${v.nivel}` : "lote consultado");
  const comExtra = (v) => [extraDe(v), nivel(v)].filter(Boolean).join(" · ");
  const raiz = porId.get(consulta.raiz);
  const recall = consulta.tipo === "recall";

  const fornecedores = [...new Set(doTipo("insumo").map((v) => v.atributos?.fornecedor).filter(Boolean))].sort();
  const qtd = (tipo) => consulta.resumo[tipo].length;
  const descricaoRaiz = `${raiz.id} (${raiz.nome}${extraDe(raiz) ? `, ${extraDe(raiz)}` : ""})`;
  let resumo;
  if (recall) {
    resumo = qtd("produto_final") || qtd("destino")
      ? `Se ${descricaoRaiz} estiver comprometido, é preciso recolher ${contar(qtd("produto_final"), "produto_final")} e avisar ${contar(qtd("destino"), "destino")}.`
      : `${descricaoRaiz} ainda não chegou a nenhum produto final nem a nenhum destino: não há o que recolher.`;
  } else if (raiz.tipo === "destino") {
    resumo = `${raiz.nome} recebeu ${contar(qtd("produto_final"), "produto_final")}, feitos a partir de ${contar(qtd("insumo"), "insumo")} de ${fornecedores.length} fornecedores.`;
  } else if (raiz.tipo === "insumo") {
    resumo = `${descricaoRaiz} é um insumo: ele abre a cadeia, então a origem é o próprio fornecedor.`;
  } else {
    resumo = `${descricaoRaiz} foi feito a partir de ${contar(qtd("insumo"), "insumo")}, vindos de ${fornecedores.length} fornecedores.`;
  }

  const niveis = [];
  for (const v of consulta.vertices) (niveis[v.nivel] ||= []).push(v);
  const linhasNivel = niveis.map((vs, n) => {
    if (n === 0) return h("li", {}, h("strong", {}, "Nível 0"), `${raiz.id}, o lote consultado`);
    const contagem = {};
    for (const v of vs) contagem[v.tipo] = (contagem[v.tipo] || 0) + 1;
    return h("li", {}, h("strong", {}, `Nível ${n}`), Object.entries(contagem).map(([t, q]) => contar(q, t)).join(", "));
  });

  const blocos = recall
    ? [
        grupo("Destinos a notificar", doTipo("destino"), (v) => v.atributos?.cidade || ""),
        grupo("Produtos finais a recolher", doTipo("produto_final"), comExtra),
        grupo("Intermediários afetados", doTipo("intermediario"), comExtra),
        grupo("Insumos", doTipo("insumo"), comExtra),
      ]
    : [
        grupo("Insumos de origem", doTipo("insumo"), comExtra),
        fornecedores.length
          ? h(
              "section",
              { class: "grupo" },
              h("h3", {}, "Fornecedores envolvidos", h("span", { class: "contagem" }, String(fornecedores.length))),
              h("ul", { class: "lista" }, fornecedores.map((f) => h("li", { class: "sub" }, f)))
            )
          : null,
        grupo("Intermediários", doTipo("intermediario"), comExtra),
        grupo("Produtos finais", doTipo("produto_final"), comExtra),
      ];

  $("#resultado").replaceChildren(
    h(
      "header",
      {},
      h("h2", {}, recall ? "Recall de " : "Origem de ", etiqueta(raiz.id, raiz.tipo), " ", raiz.nome),
      h(
        "div",
        { class: "metricas" },
        h("span", {}, `${consulta.total_vertices} vértices`),
        h("span", {}, `${consulta.total_arestas} arestas`),
        h("span", {}, `profundidade ${consulta.profundidade}`),
        h("span", {}, `${fmtMs(consulta.tempo_ms)} no servidor`)
      )
    ),
    h("p", { class: "resumo-consulta" }, resumo),
    h(
      "section",
      { class: "grupo" },
      h("h3", {}, recall ? "Como a busca chegou lá" : "Como a busca voltou até a origem"),
      h("ol", { class: "niveis" }, linhasNivel)
    ),
    ...blocos.filter(Boolean)
  );
}

const PLURAL = {
  insumo: ["lote de insumo", "lotes de insumo"],
  intermediario: ["intermediário", "intermediários"],
  produto_final: ["produto final", "produtos finais"],
  destino: ["destino", "destinos"],
};
function contar(n, tipo) {
  return `${n} ${PLURAL[tipo][n === 1 ? 0 : 1]}`;
}

// ------------------------------------------------------------------ guia de uso

let exemplos = null;

async function carregarExemplos() {
  exemplos = await api("/api/exemplos");
  if (!estado.consulta) renderIntro();
}

function botaoExemplo(classe, titulo, detalhe, acao) {
  return h("button", { class: `exemplo ${classe}`, type: "button", onclick: acao }, h("strong", {}, titulo), h("span", {}, detalhe));
}

function renderIntro() {
  const botoes = [];
  if (exemplos?.recall) {
    const r = exemplos.recall;
    botoes.push(botaoExemplo("ex-recall", `Recall de ${r.id}`,
      `${r.nome}${r.extra ? ` de ${r.extra}` : ""}. Chegou a ${contar(exemplos.recall_produtos, "produto_final")}.`,
      () => consultar("recall", r.id)));
  }
  if (exemplos?.origem) {
    const o = exemplos.origem;
    botoes.push(botaoExemplo("ex-origem", `Origem de ${o.id}`, `${o.nome}: de onde veio cada ingrediente.`, () => consultar("origem", o.id)));
  }
  if (exemplos?.ciclo) {
    const { origem, destino } = exemplos.ciclo;
    botoes.push(botaoExemplo("ex-ciclo", "Tentar um vínculo proibido",
      `${origem.id} → ${destino.id}: ${origem.nome} passaria a ser ingrediente de ${destino.nome}, um dos seus próprios ingredientes.`,
      () => prepararVinculo(origem.id, destino.id)));
  }
  $("#resultado").replaceChildren(
    h("h2", {}, "Como usar"),
    h(
      "ol",
      { class: "passos-uso" },
      h("li", {}, h("strong", {}, "Escolha um lote:"), " clique nele na rede ou digite no campo acima o código, o produto ou o fornecedor."),
      h("li", {}, h("strong", {}, "Recall"), " mostra o que foi feito com o lote e para quem foi vendido. ", h("strong", {}, "Origem"), " mostra de onde ele veio."),
      h("li", {}, "O resultado aparece isolado e acende nível por nível, na ordem da busca em largura. ", h("strong", {}, "Ver na rede completa"), " mostra o mesmo caminho no meio da cadeia inteira.")
    ),
    botoes.length
      ? h("section", { class: "grupo" }, h("span", { class: "rotulo" }, "Experimente"), h("div", { class: "exemplos" }, botoes))
      : h("p", { class: "vazio" }, "O banco está vazio. Registre um insumo na aba Registrar ou rode python -m rastro seed."),
    h("p", { class: "ajuda" }, "Dica: passe o mouse sobre um lote na rede para ver o que ele é e acender só as ligações dele.")
  );
}

function prepararVinculo(origem, destino) {
  mostrarAba("registrar");
  mostrarFormulario("form-vinculo");
  $("#vinculo-origem").value = origem;
  $("#vinculo-destino").value = destino;
  $("#retorno-registro").replaceChildren(
    h(
      "div",
      { class: "aviso info" },
      h("strong", {}, "Campos preenchidos"),
      `Registrar este vínculo diria que ${origem} entrou na produção de ${destino}. Só que ${destino} já é ingrediente de ${origem}. Aperte Registrar vínculo e veja o sistema recusar e mostrar o ciclo.`
    )
  );
}

// ------------------------------------------------------------------ detalhe do vértice

async function focar(id) {
  const no = estado.cy.getElementById(id);
  if (no.nonempty()) {
    estado.cy.elements().unselect();
    no.select();
    estado.cy.animate({ center: { eles: no }, zoom: Math.max(estado.cy.zoom(), 1.2) }, { duration: semMovimento() ? 0 : 300 });
  }
  await selecionar(id);
}

async function selecionar(id) {
  let v;
  try {
    v = await api(`/api/vertices/${encodeURIComponent(id)}`);
  } catch (erro) {
    avisar(erro.message);
    return;
  }
  const atributos = Object.entries(v.atributos || {});
  const fatos = [
    v.quantidade != null ? ["Quantidade", `${fmtNumero.format(v.quantidade)} ${v.unidade || ""}`] : null,
    ["Registrado em", fmtData.format(new Date(v.criado_em))],
    ...atributos.map(([chave, valor]) => [chave[0].toUpperCase() + chave.slice(1), String(valor)]),
    v.evento_id ? ["Evento", `#${v.evento_id}`] : null,
  ].filter(Boolean);

  const chips = (arestas, lado) =>
    arestas.length
      ? h(
          "div",
          { class: "chips" },
          arestas.map((a) => h("button", { class: "chip mono", type: "button", onclick: () => focar(a[lado]) }, a[lado]))
        )
      : h("p", { class: "vazio" }, "nenhuma");

  const ehDestino = v.tipo === "destino";
  const painel = $("#detalhe");
  painel.replaceChildren(
    h("button", { class: "fechar", type: "button", "aria-label": "Fechar", onclick: fecharDetalhe }, "×"),
    h("span", { class: "pilula" }, NOME_TIPO[v.tipo]),
    h("h2", {}, etiqueta(v.id, v.tipo), " ", v.nome),
    h("dl", { class: "fatos" }, fatos.map(([dt, dd]) => [h("dt", {}, dt), h("dd", {}, dd)])),
    h("div", { class: "grupo" }, h("span", { class: "rotulo" }, `Entradas (${v.entradas.length})`), chips(v.entradas, "origem")),
    h("div", { class: "grupo" }, h("span", { class: "rotulo" }, `Saídas (${v.saidas.length})`), chips(v.saidas, "destino")),
    h(
      "div",
      { class: "botoes" },
      h("button", { class: "btn btn-recall", type: "button", disabled: ehDestino, onclick: () => consultar("recall", v.id) }, "Recall"),
      h("button", { class: "btn btn-origem", type: "button", onclick: () => consultar("origem", v.id) }, ehDestino ? "O que recebeu" : "Origem"),
      h("button", { class: "btn", type: "button", onclick: () => abrirVizinhanca(v.id) }, "Vizinhança"),
      ehDestino ? null : h("button", { class: "btn", type: "button", onclick: () => usarComoEntrada(v.id) }, "Usar em produção")
    )
  );
  painel.hidden = false;
}

function fecharDetalhe() {
  $("#detalhe").hidden = true;
  estado.cy.elements().unselect();
}

async function abrirVizinhanca(id) {
  try {
    const dados = await api(`/api/grafo/vizinhanca/${encodeURIComponent(id)}?raio=2`);
    estado.consulta = null;
    estado.isolado = true;
    desenhar(dados.vertices, dados.arestas);
    estado.cy.getElementById(id).addClass("raiz").select();
    mostrarFaixa(`Vizinhança de ${id} (até 2 ligações, em qualquer sentido): ${dados.vertices.length} vértices`);
    $("#btn-limpar").hidden = false;
    $("#btn-isolar").hidden = true;
  } catch (erro) {
    avisar(erro.message);
  }
}

// ------------------------------------------------------------------ registro

function novaEntrada(lote = "") {
  const linha = h(
    "div",
    { class: "entrada" },
    h("input", { name: "entrada-lote", list: "lista-vertices", placeholder: "Lote de entrada", value: lote, "aria-label": "Lote de entrada" }),
    h("input", { name: "entrada-quantidade", type: "number", min: "0", step: "any", placeholder: "Qtd.", "aria-label": "Quantidade consumida" }),
    h("button", { type: "button", "aria-label": "Remover entrada", onclick: () => linha.remove() }, "×")
  );
  $("#entradas").append(linha);
  return linha;
}

function usarComoEntrada(id) {
  mostrarAba("registrar");
  mostrarFormulario("form-producao");
  const vazia = $$("#entradas input[name=entrada-lote]").find((i) => !i.value);
  if (vazia) vazia.value = id;
  else novaEntrada(id);
  avisar(`${id} adicionado às entradas da produção.`);
}

function lerFormulario(form) {
  const dados = {};
  for (const campo of form.querySelectorAll("input[name], select[name]")) {
    if (campo.name.startsWith("entrada-")) continue;
    const valor = campo.value.trim();
    if (!valor) continue;
    dados[campo.name] = campo.type === "number" ? Number(valor) : valor;
  }
  if (form.id === "form-producao") {
    dados.entradas = $$("#entradas .entrada")
      .map((linha) => {
        const lote = $("input[name=entrada-lote]", linha).value.trim();
        const qtd = $("input[name=entrada-quantidade]", linha).value.trim();
        return lote ? { lote, ...(qtd ? { quantidade: Number(qtd) } : {}) } : null;
      })
      .filter(Boolean);
  }
  return dados;
}

async function registrar(evento) {
  evento.preventDefault();
  const form = evento.currentTarget;
  const retorno = $("#retorno-registro");
  const botao = form.querySelector("button[type=submit]");
  botao.disabled = true;
  try {
    const resposta = await api(ROTA_REGISTRO[form.id], { method: "POST", corpo: lerFormulario(form) });
    const criado = resposta.lote || resposta.aresta || resposta;
    const descricao = criado.id
      ? `${NOME_TIPO[criado.tipo]} ${criado.id} registrado.`
      : `Aresta ${criado.origem} → ${criado.destino} registrada (evento #${resposta.evento.id}).`;
    retorno.replaceChildren(h("div", { class: "aviso ok" }, h("strong", {}, "Registrado"), descricao));
    form.reset();
    esconderBotoesDestaque();
    if (form.id === "form-producao") {
      $("#entradas").replaceChildren();
      novaEntrada();
    }
    await Promise.all([carregarRede(), carregarIndicadores(), carregarDestinos(), carregarExemplos()]);
    focar(criado.id || criado.destino);
    if (!$("#painel-eventos").hidden) carregarEventos();
  } catch (erro) {
    const ciclo = erro.corpo?.ciclo;
    retorno.replaceChildren(
      h(
        "div",
        { class: "aviso" },
        h("strong", {}, ciclo ? "Vínculo recusado: criaria um ciclo" : "Não foi possível registrar"),
        erro.message,
        ciclo
          ? h(
              "div",
              { class: "ciclo" },
              ciclo.flatMap((id, i) => [i ? h("span", { class: "seta" }, "→") : null, h("span", { class: "mono" }, id)])
            )
          : null
      )
    );
    if (ciclo) destacarCiclo(ciclo);
  } finally {
    botao.disabled = false;
  }
}

function mostrarFormulario(id) {
  for (const botao of $$(".segmentos button")) botao.setAttribute("aria-pressed", String(botao.dataset.form === id));
  for (const form of $$(".form-registro")) form.hidden = form.id !== id;
  $("#retorno-registro").replaceChildren();
}

// ------------------------------------------------------------------ abas, indicadores, eventos

function mostrarAba(nome) {
  for (const aba of $$(".abas button")) {
    const ativa = aba.id === `aba-${nome}`;
    aba.setAttribute("aria-selected", String(ativa));
    $(`#${aba.getAttribute("aria-controls")}`).hidden = !ativa;
  }
  if (nome === "eventos") carregarEventos();
}

async function carregarIndicadores() {
  const e = await api("/api/estatisticas");
  const t = e.vertices_por_tipo;
  $("#ind-lotes").textContent = fmtNumero.format(t.insumo + t.intermediario + t.produto_final);
  $("#ind-destinos").textContent = fmtNumero.format(t.destino);
  $("#ind-arestas").textContent = fmtNumero.format(e.arestas);
  $("#ind-profundidade").textContent = `${e.profundidade_maxima} ${e.profundidade_maxima === 1 ? "elo" : "elos"}`;
  const banco = e.banco.split(" ")[0];
  $("#ind-banco").textContent = banco === "postgresql" ? "PostgreSQL" : banco === "sqlite" ? "SQLite" : banco;
}

async function carregarEventos() {
  const eventos = await api("/api/eventos?limite=40");
  const lista = $("#lista-eventos");
  if (!eventos.length) {
    lista.replaceChildren(h("li", { class: "vazio" }, "Nenhum evento registrado."));
    return;
  }
  lista.replaceChildren(
    ...eventos.map((ev) => {
      const ids = ev.vertices.length ? ev.vertices : ev.arestas.map((a) => a.destino);
      return h(
        "li",
        {},
        h(
          "div",
          { class: "cabeca" },
          h("span", { class: `pilula ${ev.tipo}` }, ev.tipo),
          h("span", { class: "mono" }, `#${ev.id}`),
          h("span", {}, fmtData.format(new Date(ev.ocorrido_em))),
          ev.responsavel ? h("span", {}, ev.responsavel) : null
        ),
        h("span", {}, ev.descricao || ""),
        h(
          "div",
          { class: "chips" },
          ev.arestas.length && !ev.vertices.length
            ? ev.arestas.map((a) => h("button", { class: "chip mono", type: "button", onclick: () => focar(a.origem) }, `${a.origem} → ${a.destino}`))
            : ids.map((id) => h("button", { class: "chip mono", type: "button", onclick: () => focar(id) }, id))
        )
      );
    })
  );
}

// ------------------------------------------------------------------ autocompletar

async function preencherLista(lista, termo, tipo) {
  const params = new URLSearchParams({ limite: "15" });
  if (termo) params.set("q", termo);
  if (tipo) params.set("tipo", tipo);
  const vertices = await api(`/api/vertices?${params}`);
  lista.replaceChildren(
    ...vertices.map((v) => h("option", { value: v.id, label: [v.nome, extraDe(v)].filter(Boolean).join(" · ") }))
  );
}

async function carregarDestinos() {
  await preencherLista($("#lista-destinos"), "", "destino");
}

function ativarAutocompletar() {
  let temporizador;
  document.addEventListener("input", (evento) => {
    const campo = evento.target;
    if (!(campo instanceof HTMLInputElement)) return;
    const idLista = campo.getAttribute("list");
    if (idLista !== "lista-vertices" && idLista !== "lista-destinos") return;
    clearTimeout(temporizador);
    temporizador = setTimeout(() => {
      preencherLista($(`#${idLista}`), campo.value.trim(), idLista === "lista-destinos" ? "destino" : null).catch(() => {});
    }, 180);
  });
}

// ------------------------------------------------------------------ início

function ligarEventos() {
  for (const aba of $$(".abas button")) aba.addEventListener("click", () => mostrarAba(aba.id.replace("aba-", "")));
  for (const botao of $$(".segmentos button")) botao.addEventListener("click", () => mostrarFormulario(botao.dataset.form));
  for (const form of $$(".form-registro")) form.addEventListener("submit", registrar);

  $("#form-consulta").addEventListener("submit", (evento) => {
    evento.preventDefault();
    const tipo = evento.submitter?.dataset.tipo || "recall";
    consultar(tipo, $("#consulta-lote").value);
  });
  $("#adicionar-entrada").addEventListener("click", () => novaEntrada().querySelector("input").focus());
  $("#btn-limpar").addEventListener("click", limparDestaque);
  $("#btn-isolar").addEventListener("click", alternarIsolamento);
  $("#btn-ajustar").addEventListener("click", () => enquadrar());
  $("#busca-rede").addEventListener("change", async (evento) => {
    const id = evento.target.value.trim();
    if (!id) return;
    if (estado.cy.getElementById(id).empty()) await abrirVizinhanca(id);
    focar(id);
  });
}

async function iniciar() {
  iniciarRede();
  ligarEventos();
  ativarAutocompletar();
  novaEntrada();
  try {
    await Promise.all([carregarRede(), carregarIndicadores(), carregarDestinos(), carregarExemplos(), preencherLista($("#lista-vertices"), "")]);
  } catch (erro) {
    mostrarFaixa(`Não foi possível falar com a API: ${erro.message}`, "recall");
  }
}

window.rastro = estado; // depuração: window.rastro.cy no console do navegador
iniciar();
