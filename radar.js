
/* ==========================================================
   TRANSFER MARKET — TRANSFER RADAR
   Versão 4.0 — Notícias reais
   Fonte principal: candidatos.json
   Atualização automática: 1 minuto
   ========================================================== */

(() => {
  "use strict";

  const CONFIG = {
    dataUrl: "./candidatos.json",
    refreshInterval: 60 * 1000,
    language: "pt-PT"
  };

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

  let allItems = [];
  let currentSort = "newest";
  let loading = false;
  let lastUpdated = null;

  function normalize(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  function createElement(tag, className, value) {
    const element = document.createElement(tag);

    if (className) element.className = className;
    if (value !== undefined) element.textContent = value;

    return element;
  }

  function safeUrl(value) {
    try {
      const url = new URL(value);

      if (!["https:", "http:"].includes(url.protocol)) {
        return null;
      }

      return url.href;
    } catch {
      return null;
    }
  }

  function formatDate(value) {
    if (!value) return "Data não indicada";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return "Data não indicada";
    }

    return new Intl.DateTimeFormat("pt-PT", {
      day: "2-digit",
      month: "long",
      year: "numeric"
    }).format(date);
  }

  function getDateValue(item) {
    const date = new Date(item.date);
    return Number.isNaN(date.getTime()) ? 0 : date.getTime();
  }

  function validateData(data) {
    if (!Array.isArray(data)) {
      throw new Error("O ficheiro candidatos.json não contém uma lista válida.");
    }

    return data
      .filter(item => item && typeof item === "object")
      .map((item, index) => ({
        id: item.id || `noticia-${index}`,
        title: item.title || item.player || "Notícia de futebol",
        summary: item.summary || "Não existe resumo disponível para este artigo.",
        source: item.source || "Fonte não indicada",
        url: safeUrl(item.url),
        date: item.date || "",
        status: item.status || "Por verificar",
        league: item.league || "Europa",
        player: item.player || "",
        currentClub: item.currentClub || "",
        destination: item.destination || "",
        detectedClubs: Array.isArray(item.detectedClubs)
          ? item.detectedClubs
          : [],
        relevance: Number(item.transferRelevance) || 0,
        verification: item.verification || "Artigo recolhido automaticamente. Ainda não foi verificado."
      }))
      .filter(item => item.url && item.source);
  }

  function addPendingStatusOption() {
    if (!elements.status) return;

    const exists = [...elements.status.options]
      .some(option => option.value === "Por verificar");

    if (!exists) {
      const option = document.createElement("option");
      option.value = "Por verificar";
      option.textContent = "Por verificar";
      elements.status.append(option);
    }
  }

  function createSortControl() {
    const section = elements.feed?.closest(".feed-section");
    const top = section?.querySelector(".feed-top");

    if (!top || document.getElementById("radar-sort")) return;

    const wrapper = createElement("div", "radar-sort-wrapper");
    const label = createElement("label", "", "Ordenar por");

    label.htmlFor = "radar-sort";

    const select = createElement("select", "radar-sort");
    select.id = "radar-sort";

    [
      ["newest", "Mais recentes"],
      ["oldest", "Mais antigas"],
      ["relevance", "Relevância"]
    ].forEach(([value, name]) => {
      const option = createElement("option", "", name);
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

  function createMeta(label, value) {
    const wrapper = createElement("div", "meta-item");
    wrapper.append(
      createElement("span", "meta-label", label),
      createElement("span", "meta-value", value)
    );
    return wrapper;
  }

  function createCard(item) {
    const card = createElement("article", "rumour-card");
    card.dataset.status = item.status;
    card.dataset.league = item.league;

    const main = createElement("div", "rumour-main");
    const header = createElement("div", "rumour-card-header");
    const titleArea = createElement("div", "player-area");

    titleArea.append(
      createElement("h3", "player-name", item.title),
      createElement("span", "league-label", item.league)
    );

    const badge = createElement("span", "status status-por-verificar", item.status);
    header.append(titleArea, badge);

    const summary = createElement("p", "rumour-summary", item.summary);

    const meta = createElement("div", "rumour-meta");
    meta.append(
      createMeta("Publicado", formatDate(item.date)),
      createMeta("Fonte", item.source)
    );

    if (item.detectedClubs.length) {
      meta.append(
        createMeta("Clubes mencionados", item.detectedClubs.join(", "))
      );
    }

    const verification = createElement(
      "p",
      "credibility-reason",
      item.verification
    );

    const relevance = createElement(
      "p",
      "credibility-label",
      `Relevância automática: ${item.relevance}/10`
    );

    const footer = createElement("div", "rumour-card-footer");

    footer.append(
      createElement(
        "span",
        "status-description",
        "Informação recolhida automaticamente — por verificar."
      )
    );

    const link = createElement("a", "source-link", "Ver fonte original ↗");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    footer.append(link);

    main.append(header, summary, meta, verification, relevance);
    card.append(main, footer);

    return card;
  }

  function render(items) {
    if (!elements.feed) return;

    const fragment = document.createDocumentFragment();

    items.forEach(item => fragment.append(createCard(item)));

    elements.feed.replaceChildren(fragment);

    if (elements.count) {
      elements.count.textContent =
        `${items.length} ${items.length === 1 ? "resultado" : "resultados"}`;
    }

    if (elements.empty) {
      elements.empty.hidden = items.length !== 0;
    }

    if (elements.demoAlert) {
      elements.demoAlert.hidden = true;
    }
  }

  function matchesSearch(item, term) {
    if (!term) return true;

    const content = [
      item.title,
      item.summary,
      item.source,
      item.status,
      item.league,
      item.player,
      ...item.detectedClubs
    ].join(" ");

    return normalize(content).includes(normalize(term));
  }

  function sortItems(items) {
    items.sort((a, b) => {
      if (currentSort === "oldest") {
        return getDateValue(a) - getDateValue(b);
      }

      if (currentSort === "relevance") {
        return b.relevance - a.relevance;
      }

      return getDateValue(b) - getDateValue(a);
    });
  }

  function applyFilters() {
    const term = elements.search?.value || "";
    const status = elements.status?.value || "all";
    const league = elements.league?.value || "all";

    const filtered = allItems.filter(item => {
      const searchMatch = matchesSearch(item, term);
      const statusMatch = status === "all" || item.status === status;
      const leagueMatch = league === "all" || item.league === league;

      return searchMatch && statusMatch && leagueMatch;
    });

    sortItems(filtered);
    render(filtered);
  }

  function clearFilters() {
    if (elements.search) elements.search.value = "";
    if (elements.status) elements.status.value = "all";
    if (elements.league) elements.league.value = "all";

    currentSort = "newest";

    const sort = document.getElementById("radar-sort");
    if (sort) sort.value = "newest";

    applyFilters();
  }

  async function loadData() {
    if (loading) return;

    loading = true;

    try {
      const response = await fetch(
        `${CONFIG.dataUrl}?t=${Date.now()}`,
        { cache: "no-store" }
      );

      if (!response.ok) {
        throw new Error(`Erro HTTP ${response.status}`);
      }

      const data = await response.json();

      allItems = validateData(data);

      addPendingStatusOption();
      createSortControl();
      applyFilters();

      lastUpdated = new Date();

      console.info(
        "TRANSFER MARKET: notícias carregadas:",
        allItems.length
      );

    } catch (error) {
      console.error("Erro no Transfer Radar:", error);

      if (elements.count) {
        elements.count.textContent = "Erro ao carregar notícias";
      }

      if (elements.feed) {
        elements.feed.replaceChildren(
          createElement(
            "p",
            "radar-error",
            "Não foi possível carregar as notícias. Tenta novamente mais tarde."
          )
        );
      }
    } finally {
      loading = false;
    }
  }

  function bindEvents() {
    elements.search?.addEventListener("input", applyFilters);
    elements.status?.addEventListener("change", applyFilters);
    elements.league?.addEventListener("change", applyFilters);
    elements.clear?.addEventListener("click", clearFilters);

    document.addEventListener("visibilitychange", () => {
      if (
        document.visibilityState === "visible" &&
        lastUpdated &&
        Date.now() - lastUpdated.getTime() >= CONFIG.refreshInterval
      ) {
        loadData();
      }
    });
  }

  function init() {
    if (elements.today) {
      elements.today.textContent = new Intl.DateTimeFormat(
        "pt-PT",
        { dateStyle: "long" }
      ).format(new Date());
    }

    bindEvents();
    loadData();

    window.setInterval(() => {
      if (document.visibilityState === "visible") {
        loadData();
      }
    }, CONFIG.refreshInterval);

    console.info("TRANSFER MARKET — Radar V4 iniciado.");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
