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
    aresta: cor("--c-aresta"),
    recall: cor("--c-recall"),
    origem: cor("--c-origem"),
    bg: cor("--bg"),
  };
  return [
    {
      selector: "node",
      style: {
        "background-color": (n) => c[n.data("tipo")],
        shape: (n) => FORMA[n.data("tipo")],
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
    {
      selector: "edge",
      style: {
        width: 1,
        "line-color": c.aresta,
        "target-arrow-color": c.aresta,
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.6,
        "curve-style": "bezier",
      },
    },
    { selector: 'edge[tipo = "expedicao"]', style: { "line-style": "dashed" } },
    { selector: ".apagado", style: { opacity: 0.1 } },
    { selector: "node.realce-recall", style: { "border-width": 2, "border-color": c.recall } },
    { selector: "edge.realce-recall", style: { width: 2, "line-color": c.recall, "target-arrow-color": c.recall } },
    { selector: "node.realce-origem", style: { "border-width": 2, "border-color": c.origem } },
    { selector: "edge.realce-origem", style: { width: 2, "line-color": c.origem, "target-arrow-color": c.origem } },
    { selector: "node.raiz", style: { width: 32, height: 24, "border-width": 4, "font-size": 10, "font-weight": "bold" } },
    { selector: "node.ciclo", style: { "border-width": 3, "border-style": "dashed", "border-color": c.recall } },
    { selector: "edge.ciclo", style: { width: 3, "line-color": c.recall, "target-arrow-color": c.recall } },
    {
      selector: "edge.tentativa",
      style: {
        width: 3,
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
  const atualizarEstilo = () => estado.cy.style(estiloRede());
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", atualizarEstilo);
  new MutationObserver(atualizarEstilo).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
}

function elementos(vertices, arestas) {
  return [
    ...vertices.map((v) => ({ group: "nodes", data: { id: v.id, tipo: v.tipo, nome: v.nome, criado: v.criado_em } })),
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
  cy.batch(() => {
    cy.elements().remove();
    cy.add(elementos(vertices, arestas));
  });
  if (vertices.length > LIMITE_DAGRE) {
    cy.layout({ name: "preset", positions: posicoesEmBlocos(vertices, arestas), fit: true, padding: 30, animate: false }).run();
  } else {
    cy.layout({ name: "dagre", rankDir: "LR", nodeSep: 22, edgeSep: 6, rankSep: 140, fit: true, padding: 40, animate: false }).run();
  }
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
  const blocos = estagios.filter(Boolean);
  for (const bloco of blocos) bloco.sort((a, b) => (a.criado_em < b.criado_em ? -1 : a.criado_em > b.criado_em ? 1 : a.id < b.id ? -1 : 1));

  const celulaX = 60;
  const celulaY = 26;
  const vao = 150;
  const caixa = $("#rede").getBoundingClientRect();
  const proporcao = Math.max(0.6, (caixa.width || 1000) / (caixa.height || 700));
  const maior = Math.max(...blocos.map((b) => b.length));
  let linhas = maior;
  let melhor = Infinity;
  for (let r = 1; r <= maior; r++) {
    const largura = blocos.reduce((soma, b) => soma + Math.ceil(b.length / r) * celulaX, 0) + vao * (blocos.length - 1);
    const erro = Math.abs(Math.log(largura / (r * celulaY) / proporcao));
    if (erro < melhor) [melhor, linhas] = [erro, r];
  }

  const posicoes = {};
  let x = 0;
  for (const bloco of blocos) {
    const colunas = Math.ceil(bloco.length / linhas);
    const linhasBloco = Math.ceil(bloco.length / colunas);
    const deslocY = ((linhas - linhasBloco) * celulaY) / 2;
    bloco.forEach((v, i) => {
      posicoes[v.id] = { x: x + Math.floor(i / linhasBloco) * celulaX, y: deslocY + (i % linhasBloco) * celulaY };
    });
    x += colunas * celulaX + vao;
  }
  return posicoes;
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

// Enquadra a coleção sem passar de um zoom confortável (subgrafos pequenos não viram close-up).
function enquadrar(colecao, zoomMaximo = 1.4) {
  const cy = estado.cy;
  const alvo = colecao && colecao.nonempty() ? colecao : cy.elements();
  if (alvo.empty()) return;
  const caixa = alvo.boundingBox();
  const margem = 60;
  const zoom = Math.max(
    cy.minZoom(),
    Math.min(zoomMaximo, (cy.width() - 2 * margem) / Math.max(caixa.w, 1), (cy.height() - 2 * margem) / Math.max(caixa.h, 1))
  );
  const pan = { x: cy.width() / 2 - zoom * (caixa.x1 + caixa.w / 2), y: cy.height() / 2 - zoom * (caixa.y1 + caixa.h / 2) };
  cy.animate({ zoom, pan }, { duration: semMovimento() ? 0 : 350 });
}

function subgrafoNaRede(vertices, arestas) {
  const cy = estado.cy;
  let colecao = cy.collection();
  for (const v of vertices) colecao = colecao.union(cy.getElementById(v.id));
  for (const a of arestas) colecao = colecao.union(cy.getElementById(`${a.origem}->${a.destino}`));
  return colecao;
}

function limparClasses() {
  estado.cy.remove(".tentativa");
  estado.cy.elements().removeClass("apagado realce-recall realce-origem raiz ciclo");
}

function esconderBotoesDestaque() {
  estado.consulta = null;
  $("#btn-limpar").hidden = true;
  $("#btn-isolar").hidden = true;
}

function destacarConsulta(consulta) {
  const cy = estado.cy;
  const faltando = consulta.vertices.some((v) => cy.getElementById(v.id).empty());
  if (faltando && !estado.isolado) {
    isolarConsulta(consulta);
    return;
  }
  const classe = consulta.tipo === "recall" ? "realce-recall" : "realce-origem";
  const sub = subgrafoNaRede(consulta.vertices, consulta.arestas);
  cy.batch(() => {
    limparClasses();
    if (!estado.isolado) cy.elements().addClass("apagado");
    sub.removeClass("apagado").addClass(classe);
    cy.getElementById(consulta.raiz).addClass("raiz");
  });
  enquadrar(sub);
  const nome = consulta.tipo === "recall" ? "Recall" : "Origem";
  mostrarFaixa(
    `${nome} de ${consulta.raiz}: ${consulta.total_vertices} vértices e ${consulta.total_arestas} arestas ` +
      `em ${fmtMs(consulta.tempo_ms)}${estado.isolado ? " — subgrafo isolado" : ""}`,
    consulta.tipo
  );
  $("#btn-limpar").hidden = false;
  $("#btn-isolar").hidden = false;
  $("#btn-isolar").textContent = estado.isolado ? "Voltar à rede" : "Isolar subgrafo";
}

function isolarConsulta(consulta) {
  estado.isolado = true;
  desenhar(consulta.vertices, consulta.arestas);
  destacarConsulta(consulta);
}

async function limparDestaque() {
  esconderBotoesDestaque();
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
  if (estado.isolado) {
    await carregarRede();
    destacarConsulta(estado.consulta);
  } else {
    isolarConsulta(estado.consulta);
  }
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
    destacarConsulta(consulta);
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

  const lotes = consulta.vertices.filter((v) => v.tipo !== "destino").length;
  const resumo = recall
    ? `O recolhimento atinge ${lotes} ${lotes === 1 ? "lote" : "lotes"} e ${consulta.resumo.destino.length} destinos.`
    : `A cadeia envolve ${consulta.resumo.insumo.length} lotes de insumo.`;

  const fornecedores = [...new Set(doTipo("insumo").map((v) => v.atributos?.fornecedor).filter(Boolean))].sort();

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
    h("p", { class: "ajuda" }, resumo),
    ...blocos.filter(Boolean)
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
    await Promise.all([carregarRede(), carregarIndicadores(), carregarDestinos()]);
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
  $("#exemplo-recall").addEventListener("click", () => consultar("recall", "INS-000001"));
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
    await Promise.all([carregarRede(), carregarIndicadores(), carregarDestinos(), preencherLista($("#lista-vertices"), "")]);
  } catch (erro) {
    mostrarFaixa(`Não foi possível falar com a API: ${erro.message}`, "recall");
  }
}

iniciar();
