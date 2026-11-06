
/* ==========================================================
   TRANSFER MARKET — TRANSFER RADAR
   Versão 2.0 | Motor principal do radar de transferências
   Compatível com:
   - rumores.html
   - rumores.json (na raiz do repositório)
   - script.js
   ========================================================== */

(() => {
  "use strict";

  /* ----------------------------------------------------------
     1. CONFIGURAÇÃO
     ---------------------------------------------------------- */

  const CONFIG = {
    dataUrl: "./rumores.json",
    refreshInterval: 5 * 60 * 1000,
    language: "pt-PT",
    maxSummaryLength: 500,
    statuses: [
      "Interesse",
      "Rumor",
      "Negociações",
      "Acordo próximo",
      "Confirmada"
    ],
    leagues: [
      "Inglaterra",
      "Espanha",
      "Itália",
      "Alemanha",
      "França",
      "Portugal",
      "Europa"
    ]
  };

  const STATUS_INFO = {
    "Interesse": {
      label: "Interesse",
      description: "Interesse reportado, sem negociações confirmadas.",
      priority: 1
    },
    "Rumor": {
      label: "Rumor",
      description: "Informação ainda por confirmar.",
      priority: 2
    },
    "Negociações": {
      label: "Em negociações",
      description: "Existem indicações de conversações entre as partes.",
      priority: 3
    },
    "Acordo próximo": {
      label: "Acordo próximo",
      description: "Há indicações de que um acordo poderá estar perto.",
      priority: 4
    },
    "Confirmada": {
      label: "Confirmada",
      description: "Transferência oficialmente confirmada.",
      priority: 5
    }
  };

  const CREDIBILITY_INFO = {
    "Muito elevada": {
      label: "Muito elevada",
      level: 5
    },
    "Elevada": {
      label: "Elevada",
      level: 4
    },
    "Média": {
      label: "Média",
      level: 3
    },
    "Baixa": {
      label: "Baixa",
      level: 2
    },
    "Por avaliar": {
      label: "Por avaliar",
      level: 0
    }
  };

  /* ----------------------------------------------------------
     2. ELEMENTOS HTML
     ---------------------------------------------------------- */

  const elements = {
    feed: document.getElementById("rumour-feed"),
    search: document.getElementById("search"),
    status: document.getElementById("status-filter"),
    league: document.getElementById("league-filter"),
    count: document.getElementById("result-count"),
    empty: document.getElementById("empty-state"),
    today: document.getElementById("today-label"),
    clear: document.getElementById("clear-filters"),
    demoAlert: document.querySelector(".demo-alert")
  };

  /* ----------------------------------------------------------
     3. ESTADO DA APLICAÇÃO
     ---------------------------------------------------------- */

  let allItems = [];
  let filteredItems = [];
  let currentSort = "newest";
  let isLoading = false;
  let lastUpdated = null;

  /* ----------------------------------------------------------
     4. FUNÇÕES GERAIS
     ---------------------------------------------------------- */

  function normalize(value) {
    return String(value ?? "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase(CONFIG.language)
      .trim();
  }

  function safeText(value, fallback = "Informação indisponível") {
    if (typeof value !== "string" && typeof value !== "number") {
      return fallback;
    }

    const result = String(value).trim();
    return result || fallback;
  }

  function createElement(tag, className, text) {
    const element = document.createElement(tag);

    if (className) {
      element.className = className;
    }

    if (text !== undefined && text !== null) {
      element.textContent = String(text);
    }

    return element;
  }

  function formatDate(value) {
    if (!value) return "Data não indicada";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return String(value);
    }

    return new Intl.DateTimeFormat(CONFIG.language, {
      day: "2-digit",
      month: "short",
      year: "numeric"
    }).format(date);
  }

  function formatToday() {
    if (!elements.today) return;

    elements.today.textContent = new Intl.DateTimeFormat(
      CONFIG.language,
      {
        dateStyle: "long"
      }
    ).format(new Date());
  }

  function safeUrl(value) {
    if (!value || typeof value !== "string") return null;

    try {
      const url = new URL(value);

      if (url.protocol !== "https:" && url.protocol !== "http:") {
        return null;
      }

      return url.href;
    } catch {
      return null;
    }
  }

  function getStatusClass(status) {
    return normalize(status).replace(/\s+/g, "-");
  }

  function getStatusInfo(status) {
    return STATUS_INFO[status] || {
      label: status || "Por classificar",
      description: "Estado da informação não especificado.",
      priority: 0
    };
  }

  function getCredibility(item) {
    const value = safeText(item.credibility, "Por avaliar");

    return CREDIBILITY_INFO[value] || {
      label: value,
      level: 0
    };
  }

  /* ----------------------------------------------------------
     5. VALIDAÇÃO DOS DADOS
     ---------------------------------------------------------- */

  function validateItem(item, index) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return null;
    }

    const player = safeText(item.player, "");

    if (!player) {
      console.warn(
        `TRANSFER MARKET: notícia ${index + 1} ignorada: falta o jogador.`
      );
      return null;
    }

    return {
      id: safeText(item.id, `transfer-${index + 1}`),
      player,
      currentClub: safeText(item.currentClub, "Clube não indicado"),
      destination: safeText(item.destination, "Destino não indicado"),
      status: safeText(item.status, "Rumor"),
      league: safeText(item.league, "Europa"),
      summary: safeText(item.summary, "Sem descrição disponível.")
        .slice(0, CONFIG.maxSummaryLength),
      source: safeText(item.source, "Fonte não indicada"),
      date: safeText(item.date, ""),
      url: safeUrl(item.url),
      credibility: safeText(item.credibility, "Por avaliar"),
      confidenceReason: safeText(item.confidenceReason, ""),
      fee: safeText(item.fee, ""),
      contract: safeText(item.contract, ""),
      tags: Array.isArray(item.tags)
        ? item.tags.filter(tag => typeof tag === "string").slice(0, 8)
        : [],
      official: item.official === true
    };
  }

  function validateData(data) {
    if (!Array.isArray(data)) {
      throw new Error("O ficheiro rumores.json não contém uma lista válida.");
    }

    const validItems = data
      .map((item, index) => validateItem(item, index))
      .filter(Boolean);

    return validItems;
  }

  /* ----------------------------------------------------------
     6. ESTATÍSTICAS
     ---------------------------------------------------------- */

  function calculateStatistics(items) {
    return {
      total: items.length,
      interest: items.filter(item => item.status === "Interesse").length,
      rumours: items.filter(item => item.status === "Rumor").length,
      negotiations: items.filter(item => item.status === "Negociações").length,
      close: items.filter(item => item.status === "Acordo próximo").length,
      confirmed: items.filter(item => item.status === "Confirmada").length
    };
  }

  function createStatisticsPanel() {
    if (!elements.feed) return null;

    let panel = document.getElementById("radar-statistics");

    if (panel) return panel;

    panel = createElement("section", "radar-statistics");
    panel.id = "radar-statistics";
    panel.setAttribute("aria-label", "Estatísticas do mercado");

    const feedSection = elements.feed.closest(".feed-section");

    if (feedSection) {
      const top = feedSection.querySelector(".feed-top");

      if (top) {
        top.insertAdjacentElement("afterend", panel);
      } else {
        feedSection.insertBefore(panel, elements.feed);
      }
    }

    return panel;
  }

  function renderStatistics(items) {
    const panel = createStatisticsPanel();
    if (!panel) return;

    const stats = calculateStatistics(items);

    const cards = [
      ["Total de movimentos", stats.total, "total"],
      ["Rumores", stats.rumours, "rumour"],
      ["Negociações", stats.negotiations, "negotiation"],
      ["Acordos próximos", stats.close, "close"],
      ["Confirmadas", stats.confirmed, "confirmed"]
    ];

    panel.replaceChildren();

    cards.forEach(([label, value, type]) => {
      const card = createElement("div", `stat-card stat-${type}`);
      const number = createElement("strong", "stat-number", value);
      const title = createElement("span", "stat-label", label);

      card.append(number, title);
      panel.append(card);
    });
  }

  /* ----------------------------------------------------------
     7. CARTÕES DE TRANSFERÊNCIA
     ---------------------------------------------------------- */

  function createMetaItem(label, value, className = "") {
    if (!value) return null;

    const wrapper = createElement(
      "div",
      `meta-item ${className}`.trim()
    );

    const heading = createElement("span", "meta-label", label);
    const content = createElement("span", "meta-value", value);

    wrapper.append(heading, content);

    return wrapper;
  }

  function createSourceLink(url) {
    if (!url) return null;

    const link = createElement("a", "source-link", "Ver fonte original ↗");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute("aria-label", "Abrir a fonte original num novo separador");

    return link;
  }

  function createTag(tag) {
    return createElement("span", "rumour-tag", tag);
  }

  function createRumourCard(item) {
    const card = createElement(
      "article",
      `rumour-card status-border-${getStatusClass(item.status)}`
    );

    card.dataset.status = item.status;
    card.dataset.league = item.league;

    const main = createElement("div", "rumour-main");

    /* Cabeçalho do cartão */
    const header = createElement("div", "rumour-card-header");

    const playerArea = createElement("div", "player-area");
    const player = createElement("h3", "player-name", item.player);
    const league = createElement("span", "league-label", item.league);

    playerArea.append(player, league);

    const badge = createElement(
      "span",
      `status status-${getStatusClass(item.status)}`,
      getStatusInfo(item.status).label
    );

    badge.title = getStatusInfo(item.status).description;

    header.append(playerArea, badge);

    /* Percurso da transferência */
    const route = createElement("div", "transfer-route");

    const origin = createElement("span", "route-club", item.currentClub);
    const arrow = createElement("span", "route-arrow", "→");
    const destination = createElement(
      "span",
      "route-club route-destination",
      item.destination
    );

    route.append(origin, arrow, destination);

    /* Descrição */
    const summary = createElement("p", "rumour-summary", item.summary);

    /* Informação adicional */
    const meta = createElement("div", "rumour-meta");

    const date = createMetaItem("Publicado", formatDate(item.date));
    const source = createMetaItem("Fonte", item.source);
    const fee = createMetaItem("Valor", item.fee);
    const contract = createMetaItem("Contrato", item.contract);

    [date, source, fee, contract].forEach(element => {
      if (element) meta.append(element);
    });

    /* Credibilidade */
    const credibility = getCredibility(item);
    const credibilityArea = createElement("div", "credibility-area");

    const credibilityLabel = createElement(
      "span",
      "credibility-label",
      `Credibilidade: ${credibility.label}`
    );

    const credibilityBar = createElement("span", "credibility-bar");
    credibilityBar.setAttribute("role", "img");
    credibilityBar.setAttribute(
      "aria-label",
      `Nível de credibilidade: ${credibility.label}`
    );

    const credibilityFill = createElement("span", "credibility-fill");
    credibilityFill.style.width = `${(credibility.level / 5) * 100}%`;

    credibilityBar.append(credibilityFill);
    credibilityArea.append(credibilityLabel, credibilityBar);

    if (item.confidenceReason) {
      const reason = createElement(
        "p",
        "credibility-reason",
        item.confidenceReason
      );
      credibilityArea.append(reason);
    }

    /* Etiquetas */
    const tags = createElement("div", "rumour-tags");

    item.tags.forEach(tag => {
      tags.append(createTag(tag));
    });

    /* Rodapé */
    const footer = createElement("div", "rumour-card-footer");

    const statusDescription = createElement(
      "span",
      "status-description",
      getStatusInfo(item.status).description
    );

    footer.append(statusDescription);

    const sourceLink = createSourceLink(item.url);

    if (sourceLink) {
      footer.append(sourceLink);
    }

    main.append(
      header,
      route,
      summary,
      meta,
      credibilityArea
    );

    if (item.tags.length > 0) {
      main.append(tags);
    }

    card.append(main, footer);

    return card;
  }

  /* ----------------------------------------------------------
     8. RENDERIZAÇÃO
     ---------------------------------------------------------- */

  function render(items) {
    if (!elements.feed) return;

    const fragment = document.createDocumentFragment();

    items.forEach(item => {
      fragment.append(createRumourCard(item));
    });

    elements.feed.replaceChildren(fragment);

    if (elements.count) {
      elements.count.textContent =
        `${items.length} ${items.length === 1 ? "resultado" : "resultados"}`;
    }

    if (elements.empty) {
      elements.empty.hidden = items.length !== 0;
    }

    renderStatistics(allItems);

    if (elements.demoAlert) {
      const hasRealData = allItems.some(item =>
        item.url && item.source !== "Exemplo — substituir por fonte real"
      );

      elements.demoAlert.hidden = hasRealData;
    }
  }

  /* ----------------------------------------------------------
     9. PESQUISA
     ---------------------------------------------------------- */

  function matchesSearch(item, term) {
    if (!term) return true;

    const searchable = [
      item.player,
      item.currentClub,
      item.destination,
      item.summary,
      item.source,
      item.status,
      item.league,
      item.credibility,
      item.fee,
      item.contract,
      ...item.tags
    ].join(" ");

    return normalize(searchable).includes(normalize(term));
  }

  /* ----------------------------------------------------------
     10. FILTROS
     ---------------------------------------------------------- */

  function applyFilters() {
    const term = elements.search ? elements.search.value.trim() : "";
    const status = elements.status ? elements.status.value : "all";
    const league = elements.league ? elements.league.value : "all";

    filteredItems = allItems.filter(item => {
      const searchMatch = matchesSearch(item, term);

      const statusMatch =
        status === "all" || item.status === status;

      const leagueMatch =
        league === "all" || item.league === league;

      return searchMatch && statusMatch && leagueMatch;
    });

    sortItems(filteredItems);
    render(filteredItems);
  }

  /* ----------------------------------------------------------
     11. ORDENAÇÃO
     ---------------------------------------------------------- */

  function getDateValue(item) {
    const date = new Date(item.date);

    return Number.isNaN(date.getTime())
      ? 0
      : date.getTime();
  }

  function sortItems(items) {
    items.sort((a, b) => {
      switch (currentSort) {
        case "oldest":
          return getDateValue(a) - getDateValue(b);

        case "player":
          return a.player.localeCompare(b.player, CONFIG.language);

        case "status":
          return getStatusInfo(b.status).priority -
            getStatusInfo(a.status).priority;

        case "credibility":
          return getCredibility(b).level -
            getCredibility(a).level;

        case "newest":
        default:
          return getDateValue(b) - getDateValue(a);
      }
    });
  }

  function createSortControl() {
    const feedSection = elements.feed?.closest(".feed-section");

    if (!feedSection || document.getElementById("radar-sort")) return;

    const top = feedSection.querySelector(".feed-top");
    if (!top) return;

    const wrapper = createElement("div", "radar-sort-wrapper");

    const label = createElement("label", "", "Ordenar por");
    label.htmlFor = "radar-sort";

    const select = createElement("select", "radar-sort");
    select.id = "radar-sort";

    const options = [
      ["newest", "Mais recentes"],
      ["oldest", "Mais antigas"],
      ["player", "Nome do jogador"],
      ["status", "Estado da transferência"],
      ["credibility", "Credibilidade"]
    ];

    options.forEach(([value, text]) => {
      const option = createElement("option", "", text);
      option.value = value;
      select.append(option);
    });

    select.addEventListener("change", () => {
      currentSort = select.value;
      applyFilters();
    });

    wrapper.append(label, select);
    top.insertAdjacentElement("afterend", wrapper);
  }

  /* ----------------------------------------------------------
     12. LIMPAR FILTROS
     ---------------------------------------------------------- */

  function clearFilters() {
    if (elements.search) elements.search.value = "";
    if (elements.status) elements.status.value = "all";
    if (elements.league) elements.league.value = "all";

    currentSort = "newest";

    const sort = document.getElementById("radar-sort");
    if (sort) sort.value = "newest";

    applyFilters();
  }

  /* ----------------------------------------------------------
     13. ESTADOS DE CARREGAMENTO E ERRO
     ---------------------------------------------------------- */

  function showLoading() {
    if (elements.count) {
      elements.count.textContent = "A carregar notícias…";
    }

    if (elements.feed) {
      elements.feed.setAttribute("aria-busy", "true");
    }

    isLoading = true;
  }

  function hideLoading() {
    if (elements.feed) {
      elements.feed.setAttribute("aria-busy", "false");
    }

    isLoading = false;
  }

  function showError(message) {
    if (elements.count) {
      elements.count.textContent = "Erro ao carregar";
    }

    if (elements.feed) {
      elements.feed.replaceChildren();

      const error = createElement("div", "radar-error");
      const title = createElement("strong", "", "Não foi possível carregar o radar.");
      const description = createElement("p", "", message);
      const retry = createElement("button", "btn btn-outline", "Tentar novamente");

      retry.type = "button";
      retry.addEventListener("click", loadData);

      error.append(title, description, retry);
      elements.feed.append(error);
    }

    if (elements.empty) {
      elements.empty.hidden = true;
    }

    console.error("TRANSFER MARKET:", message);
  }

  /* ----------------------------------------------------------
     14. CARREGAMENTO DOS DADOS
     ---------------------------------------------------------- */

  async function loadData() {
    if (isLoading) return;

    showLoading();

    try {
      const response = await fetch(CONFIG.dataUrl, {
        cache: "no-store"
      });

      if (!response.ok) {
        throw new Error(
          `Erro HTTP ${response.status}: não foi possível encontrar rumores.json.`
        );
      }

      const data = await response.json();

      allItems = validateData(data);
      lastUpdated = new Date();

      createSortControl();
      applyFilters();

      if (allItems.length === 0) {
        showError(
          "O ficheiro existe, mas ainda não contém notícias válidas."
        );
      }

    } catch (error) {
      showError(
        error instanceof Error
          ? error.message
          : "Ocorreu um erro desconhecido."
      );
    } finally {
      hideLoading();
    }
  }

  /* ----------------------------------------------------------
     15. ATUALIZAÇÃO AUTOMÁTICA
     ---------------------------------------------------------- */

  function startAutoRefresh() {
    window.setInterval(() => {
      if (document.visibilityState === "visible") {
        loadData();
      }
    }, CONFIG.refreshInterval);
  }

  /* ----------------------------------------------------------
     16. EVENTOS
     ---------------------------------------------------------- */

  function bindEvents() {
    if (elements.search) {
      elements.search.addEventListener("input", applyFilters);
    }

    if (elements.status) {
      elements.status.addEventListener("change", applyFilters);
    }

    if (elements.league) {
      elements.league.addEventListener("change", applyFilters);
    }

    if (elements.clear) {
      elements.clear.addEventListener("click", clearFilters);
    }

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && lastUpdated) {
        const elapsed = Date.now() - lastUpdated.getTime();

        if (elapsed > CONFIG.refreshInterval) {
          loadData();
        }
      }
    });
  }

  /* ----------------------------------------------------------
     17. INICIALIZAÇÃO
     ---------------------------------------------------------- */

  function init() {
    formatToday();
    bindEvents();
    loadData();
    startAutoRefresh();

    console.info("TRANSFER MARKET — Transfer Radar iniciado.");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
