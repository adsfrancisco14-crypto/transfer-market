
/* ==========================================================
   TRANSFER MARKET — TRANSFER RADAR
   VERSÃO 5.0
   ========================================================== */

(() => {
  "use strict";

  const CONFIG = {
    rumoursUrl: "./candidatos.json",
    officialUrl: "./oficiais.json",
    refreshInterval: 60 * 1000,
    maxRumours: 500,
    maxOfficials: 500
  };

  const elements = {
    search: document.getElementById("search"),
    status: document.getElementById("status-filter"),
    league: document.getElementById("league-filter"),
    rumourFeed: document.getElementById("rumour-feed"),
    emptyState: document.getElementById("empty-state"),
    resultCount: document.getElementById("result-count"),
    todayLabel: document.getElementById("today-label")
  };

  let rumores = [];
  let oficiais = [];

  let ultimaAtualizacao = null;

  // ========================================================
  // FUNÇÕES GERAIS
  // ========================================================

  function texto(valor) {
    return String(valor ?? "").trim();
  }

  function escapar(valor) {
    return texto(valor)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function obterData(valor) {
    if (!valor) return null;

    const data = new Date(valor);

    return Number.isNaN(data.getTime()) ? null : data;
  }

  function formatarData(valor) {
    const data = obterData(valor);

    if (!data) return "Data não disponível";

    return new Intl.DateTimeFormat("pt-PT", {
      day: "2-digit",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(data);
  }

  function normalizar(valor) {
    return texto(valor)
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  }

  function obterUrl(valor) {
    try {
      const url = new URL(texto(valor));

      if (!["http:", "https:"].includes(url.protocol)) {
        return "";
      }

      return url.href;
    } catch {
      return "";
    }
  }

  function ordenarPorData(lista) {
    return [...lista].sort((a, b) => {
      const dataA = obterData(a.date)?.getTime() || 0;
      const dataB = obterData(b.date)?.getTime() || 0;

      return dataB - dataA;
    });
  }

  // ========================================================
  // LIGAS
  // ========================================================

  const LIGAS = {
    inglaterra: "Inglaterra",
    premierleague: "Inglaterra",
    espanha: "Espanha",
    laliga: "Espanha",
    italia: "Itália",
    seriea: "Itália",
    alemanha: "Alemanha",
    bundesliga: "Alemanha",
    franca: "França",
    ligue1: "França",
    portugal: "Portugal",
    primeiraliga: "Portugal"
  };

  function obterLiga(item) {
    const valor = normalizar(
      item.league ||
      item.country ||
      item.competition ||
      item.region ||
      ""
    ).replace(/[^a-z0-9]/g, "");

    if (LIGAS[valor]) {
      return LIGAS[valor];
    }

    const clubes = normalizar(
      [
        item.currentClub,
        item.destination,
        item.oldClub,
        item.newClub,
        ...(Array.isArray(item.detectedClubs)
          ? item.detectedClubs
          : [])
      ].join(" ")
    );

    const equipas = [
      {
        liga: "Portugal",
        nomes: [
          "benfica", "porto", "sporting",
          "braga", "vitoria guimaraes",
          "gil vicente", "moreirense",
          "santa clara", "famalicao",
          "estoril", "casa pia", "rio ave",
          "nacional", "arouca", "farense",
          "boavista", "avs"
        ]
      },
      {
        liga: "Inglaterra",
        nomes: [
          "manchester city", "manchester united",
          "liverpool", "arsenal", "chelsea",
          "tottenham", "newcastle",
          "aston villa", "everton",
          "west ham", "brighton",
          "nottingham forest", "fulham",
          "crystal palace", "wolves",
          "brentford", "bournemouth",
          "leeds united", "sunderland", "burnley"
        ]
      },
      {
        liga: "Espanha",
        nomes: [
          "real madrid", "barcelona",
          "atletico madrid", "sevilla",
          "valencia", "villarreal",
          "real sociedad", "athletic bilbao",
          "girona", "getafe", "osasuna",
          "celta vigo", "mallorca"
        ]
      },
      {
        liga: "Itália",
        nomes: [
          "juventus", "inter milan",
          "ac milan", "napoli",
          "roma", "lazio", "atalanta",
          "fiorentina", "bologna",
          "torino", "genoa"
        ]
      },
      {
        liga: "Alemanha",
        nomes: [
          "bayern munich", "borussia dortmund",
          "bayer leverkusen", "rb leipzig",
          "eintracht frankfurt",
          "stuttgart", "wolfsburg",
          "freiburg", "hoffenheim"
        ]
      },
      {
        liga: "França",
        nomes: [
          "paris saint germain", "psg",
          "marseille", "monaco",
          "lyon", "lille", "nice",
          "lens", "rennes", "strasbourg"
        ]
      }
    ];

    for (const grupo of equipas) {
      if (grupo.nomes.some(nome => clubes.includes(nome))) {
        return grupo.liga;
      }
    }

    return texto(item.league || item.country || "Europa");
  }

  // ========================================================
  // NORMALIZAR RUMORES
  // ========================================================

  function normalizarRumor(item) {
    if (!item || typeof item !== "object") return null;

    const url = obterUrl(item.url);

    if (!url) return null;

    const titulo = texto(item.title);

    if (!titulo) return null;

    return {
      ...item,
      title: titulo,
      summary: texto(item.summary),
      originalTitle: texto(item.originalTitle),
      originalSummary: texto(item.originalSummary),
      source: texto(item.source) || "Fonte não identificada",
      url,
      date: texto(item.date),
      status: texto(item.editorStatus || item.status || "Por verificar"),
      relevance: Number(item.relevance ?? item.transferRelevance ?? 0),
      league: obterLiga(item)
    };
  }

  // ========================================================
  // NORMALIZAR TRANSFERÊNCIAS OFICIAIS
  // ========================================================

  function normalizarOficial(item) {
    if (!item || typeof item !== "object") return null;

    const url = obterUrl(
      item.officialUrl ||
      item.announcementUrl ||
      item.url
    );

    if (!url) return null;

    const jogador = texto(
      item.player ||
      item.playerName
    );

    const clubeAntigo = texto(
      item.oldClub ||
      item.from ||
      item.previousClub
    );

    const clubeNovo = texto(
      item.newClub ||
      item.to ||
      item.destination
    );

    if (!jogador || (!clubeAntigo && !clubeNovo)) {
      return null;
    }

    return {
      ...item,
      player: jogador,
      oldClub: clubeAntigo || "Não indicado",
      newClub: clubeNovo || "Não indicado",
      transferType: texto(item.transferType || item.type || "Transferência"),
      fee: texto(item.fee || item.amount || ""),
      date: texto(item.date || item.announcementDate),
      league: obterLiga(item),
      url,
      source: texto(item.source || "Anúncio oficial"),
      verified: item.verified === true ||
        item.official === true ||
        item.verification === "official"
    };
  }

  // ========================================================
  // SECÇÃO DE TRANSFERÊNCIAS OFICIAIS
  // ========================================================

  function prepararSecaoOficial() {
    let secao = document.getElementById("official-section");

    if (secao) {
      return secao;
    }

    secao = document.createElement("section");
    secao.id = "official-section";
    secao.className = "official-section";

    secao.innerHTML = `
      <div class="section-heading">
        <h2>Transferências oficiais</h2>
        <p>Movimentações confirmadas oficialmente</p>
      </div>

      <div id="official-feed" class="official-feed"></div>

      <p id="official-empty" class="empty-state">
        Ainda não existem transferências oficiais registadas.
      </p>
    `;

    const feed = elements.rumourFeed;

    if (feed && feed.parentElement) {
      feed.parentElement.insertBefore(secao, feed);
    } else {
      document.body.appendChild(secao);
    }

    return secao;
  }

  // ========================================================
  // FILTROS
  // ========================================================

  function obterFiltros() {
    return {
      pesquisa: normalizar(elements.search?.value || ""),
      estado: texto(elements.status?.value || "all"),
      liga: texto(elements.league?.value || "all")
    };
  }

  function correspondeFiltro(item, filtros) {
    const conteudo = normalizar([
      item.title,
      item.summary,
      item.player,
      item.currentClub,
      item.destination,
      item.oldClub,
      item.newClub,
      item.source
    ].join(" "));

    if (
      filtros.pesquisa &&
      !conteudo.includes(filtros.pesquisa)
    ) {
      return false;
    }

    if (
      filtros.estado &&
      filtros.estado !== "all" &&
      normalizar(item.status) !== normalizar(filtros.estado)
    ) {
      return false;
    }

    if (
      filtros.liga &&
      filtros.liga !== "all" &&
      normalizar(item.league) !== normalizar(filtros.liga)
    ) {
      return false;
    }

    return true;
  }

  // ========================================================
  // CRIAR CARTÃO DE RUMOR
  // ========================================================

  function criarCartaoRumor(item) {
    const card = document.createElement("article");

    card.className = "rumour-card";

    const titulo = escapar(item.title);
    const resumo = escapar(item.summary);
    const fonte = escapar(item.source);
    const data = escapar(formatarData(item.date));
    const estado = escapar(item.status);
    const liga = escapar(item.league);

    const jogador = escapar(item.player);
    const clube = escapar(item.currentClub);
    const destino = escapar(item.destination);

    const link = obterUrl(item.url);

    card.innerHTML = `
      <div class="card-top">
        <span class="card-league">${liga}</span>
        <span class="card-status">${estado}</span>
      </div>

      <h3>${titulo}</h3>

      ${resumo ? `<p class="card-summary">${resumo}</p>` : ""}

      ${jogador ? `
        <p class="card-player">
          <strong>Jogador:</strong> ${jogador}
        </p>
      ` : ""}

      ${clube ? `
        <p class="card-club">
          <strong>Clube atual:</strong> ${clube}
        </p>
      ` : ""}

      ${destino ? `
        <p class="card-destination">
          <strong>Destino:</strong> ${destino}
        </p>
      ` : ""}

      <div class="card-footer">
        <span>${fonte}</span>
        <span>${data}</span>
      </div>

      <div class="card-actions">
        <a href="${escapar(link)}"
           target="_blank"
           rel="noopener noreferrer">
          Ver notícia original ↗
        </a>
      </div>
    `;

    return card;
  }

  // ========================================================
  // CRIAR CARTÃO OFICIAL
  // ========================================================

  function criarCartaoOficial(item) {
    const card = document.createElement("article");

    card.className = "official-card";

    const jogador = escapar(item.player);
    const antigo = escapar(item.oldClub);
    const novo = escapar(item.newClub);
    const tipo = escapar(item.transferType);
    const liga = escapar(item.league);
    const data = escapar(formatarData(item.date));

    const link = obterUrl(item.url);

    card.innerHTML = `
      <div class="official-card-top">
        <span class="card-league">${liga}</span>
        <span class="official-label">Confirmada</span>
      </div>

      <h3>${jogador}</h3>

      <div class="official-movement">
        <div>
          <span>Clube anterior</span>
          <strong>${antigo}</strong>
        </div>

        <span class="movement-arrow">→</span>

        <div>
          <span>Novo clube</span>
          <strong>${novo}</strong>
        </div>
      </div>

      <p><strong>Tipo:</strong> ${tipo}</p>

      ${item.fee ? `
        <p><strong>Valor:</strong> ${escapar(item.fee)}</p>
      ` : `
        <p><strong>Valor:</strong> Não divulgado oficialmente</p>
      `}

      <div class="card-footer">
        <span>${data}</span>
      </div>

      <div class="card-actions">
        <a href="${escapar(link)}"
           target="_blank"
           rel="noopener noreferrer">
          Ver anúncio oficial ↗
        </a>
      </div>
    `;

    return card;
  }

  // ========================================================
  // MOSTRAR RUMORES
  // ========================================================

  function mostrarRumores() {
    if (!elements.rumourFeed) return;

    const filtros = obterFiltros();

    const filtrados = ordenarPorData(rumores)
      .filter(item => correspondeFiltro(item, filtros));

    elements.rumourFeed.replaceChildren();

    filtrados.forEach(item => {
      elements.rumourFeed.appendChild(
        criarCartaoRumor(item)
      );
    });

    if (elements.emptyState) {
      elements.emptyState.hidden = filtrados.length > 0;
    }

    if (elements.resultCount) {
      elements.resultCount.textContent =
        `${filtrados.length} ${filtrados.length === 1 ? "resultado" : "resultados"}`;
    }

    return filtrados.length;
  }

  // ========================================================
  // MOSTRAR OFICIAIS
  // ========================================================

  function mostrarOficiais() {
    prepararSecaoOficial();

    const feed = document.getElementById("official-feed");
    const vazio = document.getElementById("official-empty");

    if (!feed) return;

    const filtros = obterFiltros();

    const filtrados = ordenarPorData(oficiais)
      .filter(item => correspondeFiltro(item, filtros));

    feed.replaceChildren();

    filtrados.forEach(item => {
      feed.appendChild(
        criarCartaoOficial(item)
      );
    });

    if (vazio) {
      vazio.hidden = filtrados.length > 0;
    }
  }

  // ========================================================
  // RENDERIZAR TUDO
  // ========================================================

  function renderizar() {
    mostrarRumores();
    mostrarOficiais();

    if (elements.todayLabel) {
      elements.todayLabel.textContent =
        new Intl.DateTimeFormat("pt-PT", {
          day: "2-digit",
          month: "long",
          year: "numeric"
        }).format(new Date());
    }
  }

  // ========================================================
  // CARREGAR JSON
  // ========================================================

  async function carregarJSON(url) {
    const separador = url.includes("?") ? "&" : "?";

    const resposta = await fetch(
      `${url}${separador}_=${Date.now()}`,
      {
        cache: "no-store"
      }
    );

    if (!resposta.ok) {
      throw new Error(
        `Erro HTTP ${resposta.status}: ${url}`
      );
    }

    return resposta.json();
  }

  // ========================================================
  // ATUALIZAR DADOS
  // ========================================================

  async function atualizarDados() {
    try {
      const resultados = await Promise.allSettled([
        carregarJSON(CONFIG.rumoursUrl),
        carregarJSON(CONFIG.officialUrl)
      ]);

      if (resultados[0].status === "fulfilled") {
        const dados = resultados[0].value;

        if (Array.isArray(dados)) {
          rumores = dados
            .map(normalizarRumor)
            .filter(Boolean)
            .slice(0, CONFIG.maxRumours);
        } else {
          console.error("candidatos.json não contém uma lista.");
        }
      } else {
        console.error(
          "Erro ao carregar rumores:",
          resultados[0].reason
        );
      }

      if (resultados[1].status === "fulfilled") {
        const dados = resultados[1].value;

        if (Array.isArray(dados)) {
          oficiais = dados
            .map(normalizarOficial)
            .filter(Boolean)
            .filter(item => item.verified)
            .slice(0, CONFIG.maxOfficials);
        } else {
          console.error("oficiais.json não contém uma lista.");
        }
      } else {
        console.warn(
          "Não foi possível carregar oficiais.json:",
          resultados[1].reason
        );

        oficiais = [];
      }

      renderizar();

      ultimaAtualizacao = new Date();

      document.dispatchEvent(
        new CustomEvent("transferMarketUpdated", {
          detail: {
            rumours: rumores.length,
            officials: oficiais.length,
            updatedAt: ultimaAtualizacao
          }
        })
      );

    } catch (erro) {
      console.error(
        "Erro ao atualizar TRANSFER MARKET:",
        erro
      );
    }
  }

  // ========================================================
  // EVENTOS DOS FILTROS
  // ========================================================

  function configurarFiltros() {
    elements.search?.addEventListener(
      "input",
      renderizar
    );

    elements.status?.addEventListener(
      "change",
      renderizar
    );

    elements.league?.addEventListener(
      "change",
      renderizar
    );
  }

  // ========================================================
  // INICIALIZAÇÃO
  // ========================================================

  function iniciar() {
    configurarFiltros();

    prepararSecaoOficial();

    atualizarDados();

    setInterval(
      atualizarDados,
      CONFIG.refreshInterval
    );

    console.log(
      "TRANSFER MARKET RADAR V5.0 iniciado."
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      iniciar
    );
  } else {
    iniciar();
  }

})();
