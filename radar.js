/* ==========================================================
   TRANSFER MARKET — TRANSFER RADAR
   V6.0 — filtros independentes e compatibilidade V7.3
   ========================================================== */

(() => {
  "use strict";

  const CONFIG = {
    candidatesUrl: "./candidatos.json",
    officialUrl: "./oficiais.json",
    refreshInterval: 60 * 1000
  };

  const $ = (selector, root = document) => root.querySelector(selector);

  const normalize = value => String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();

  const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);

  const PHASE_ALIASES = {
    "interesse": "Interesse",
    "interest": "Interesse",
    "rumor": "Rumor",
    "rumour": "Rumor",
    "negociacoes": "Negociações",
    "negotiation": "Negociações",
    "negotiations": "Negociações",
    "acordo proximo": "Acordo próximo",
    "advanced agreement": "Acordo próximo",
    "confirmed": "Confirmada",
    "confirmada": "Confirmada",
    "official": "Confirmada"
  };

  const REGION_ALIASES = {
    "inglaterra": "Inglaterra",
    "england": "Inglaterra",
    "premier league": "Inglaterra",

    "espanha": "Espanha",
    "spain": "Espanha",
    "la liga": "Espanha",

    "italia": "Itália",
    "italy": "Itália",
    "serie a": "Itália",

    "alemanha": "Alemanha",
    "germany": "Alemanha",
    "bundesliga": "Alemanha",

    "franca": "França",
    "france": "França",
    "ligue 1": "França",

    "portugal": "Portugal",
    "primeira liga": "Portugal"
  };

  const state = {
    candidates: [],
    officials: [],
    timer: null
  };

  function phaseOf(item) {
    const raw =
      item.phase ||
      item.suggestedStatus ||
      item.status ||
      "Por classificar";

    return PHASE_ALIASES[normalize(raw)] || raw;
  }

  function verificationOf(item) {
    const raw =
      item.verificationStatus ||
      item.verification ||
      item.editorStatus ||
      "Por verificar";

    const n = normalize(raw);

    if ([
      "verified",
      "verificada",
      "confirmada",
      "official",
      "oficial"
    ].includes(n)) {
      return "Verificada";
    }

    if ([
      "rejected",
      "rejeitada",
      "excluida",
      "excluída"
    ].includes(n)) {
      return "Rejeitada";
    }

    return "Por verificar";
  }

  function regionsOf(item) {
    const raw = Array.isArray(item.regions)
      ? item.regions
      : Array.isArray(item.leagues)
        ? item.leagues
        : (item.league ? [item.league] : []);

    const mapped = raw
      .map(value => REGION_ALIASES[normalize(value)] || value)
      .filter(value => [
        "Inglaterra",
        "Espanha",
        "Itália",
        "Alemanha",
        "França",
        "Portugal"
      ].includes(value));

    return [...new Set(mapped)];
  }

  function isOfficial(item) {
    const verification = normalize(
      item.verification || item.verificationStatus || ""
    );

    return item.verified === true ||
      item.official === true ||
      [
        "official",
        "oficial",
        "confirmed",
        "confirmada"
      ].includes(verification) ||
      item.verification === "official";
  }

  function normalizeCandidate(item) {
    const phase = phaseOf(item);

    return {
      ...item,

      _phase: phase,
      _verification: verificationOf(item),
      _regions: regionsOf(item),

      _search: normalize([
        item.title,
        item.summary,
        item.originalTitle,
        item.originalSummary,
        item.translatedTitle,
        item.translatedSummary,
        item.player,
        item.currentClub,
        item.destination,
        ...(item.detectedPlayers || []),
        ...(item.detectedClubs || [])
      ].join(" "))
    };
  }

  function ensureVerificationFilter() {
    if ($("#verification-filter")) {
      return $("#verification-filter");
    }

    const status = $("#status-filter");

    if (!status) {
      return null;
    }

    const wrapper = document.createElement("label");

    wrapper.className =
      "filter-control verification-filter-control";

    wrapper.innerHTML = `
      <span>Verificação</span>
      <select id="verification-filter">
        <option value="">Todas</option>
        <option value="Por verificar">Por verificar</option>
        <option value="Verificada">Verificada</option>
        <option value="Rejeitada">Rejeitada</option>
      </select>
    `;

    status.parentElement?.insertBefore(
      wrapper,
      status.nextSibling
    );

    return $("#verification-filter");
  }

  function dateLabel(value) {
    if (!value) {
      return "Data não disponível";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return escapeHTML(value);
    }

    return new Intl.DateTimeFormat("pt-PT", {
      dateStyle: "medium",
      timeStyle: "short"
    }).format(date);
  }

  function sourceLink(item) {
    const url =
      item.url ||
      item.officialUrl ||
      item.announcementUrl ||
      "#";

    return `
      <a
        href="${escapeHTML(url)}"
        target="_blank"
        rel="noopener noreferrer"
      >
        Ver fonte original ↗
      </a>
    `;
  }

  function renderRumour(item) {
    const title =
      item.title ||
      item.translatedTitle ||
      item.originalTitle ||
      "Notícia sem título";

    const summary =
      item.summary ||
      item.translatedSummary ||
      item.originalSummary ||
      "";

    const player = item.player
      ? `<p class="card-player"><strong>Jogador:</strong> ${escapeHTML(item.player)}</p>`
      : "";

    const club = item.currentClub
      ? `<p class="card-club"><strong>Clube:</strong> ${escapeHTML(item.currentClub)}</p>`
      : "";

    const destination = item.destination
      ? `<p class="card-destination"><strong>Destino:</strong> ${escapeHTML(item.destination)}</p>`
      : "";

    const region = item._regions.length
      ? item._regions.join(" · ")
      : "Por identificar";

    return `
      <article class="rumour-card" data-id="${escapeHTML(item.id || "")}">
        <div class="card-top">
          <span class="card-league">${escapeHTML(region)}</span>
          <span class="card-status">${escapeHTML(item._phase)}</span>
        </div>

        <h3>${escapeHTML(title)}</h3>

        ${summary
          ? `<p class="card-summary">${escapeHTML(summary)}</p>`
          : ""
        }

        ${player}
        ${club}
        ${destination}

        <div class="card-footer">
          <span>${escapeHTML(item.source || item.domain || "Fonte não identificada")}</span>
          <time>${dateLabel(item.date)}</time>
        </div>

        <div class="card-actions">
          <span class="verification-label">${escapeHTML(item._verification)}</span>
          ${sourceLink(item)}
        </div>
      </article>
    `;
  }

  function renderOfficial(item) {
    const player =
      item.player ||
      item.playerName ||
      "Jogador não identificado";

    const oldClub =
      item.oldClub ||
      item.from ||
      item.previousClub ||
      "";

    const newClub =
      item.newClub ||
      item.to ||
      item.destination ||
      "";

    const type =
      item.transferType ||
      item.type ||
      "Transferência";

    const fee =
      item.fee ||
      item.amount ||
      "";

    const date =
      item.announcementDate ||
      item.date ||
      "";

    const url =
      item.officialUrl ||
      item.announcementUrl ||
      item.url ||
      "#";

    return `
      <article class="official-card">
        <div class="official-card-top">
          <span class="official-label">Confirmada oficialmente</span>
          <time>${dateLabel(date)}</time>
        </div>

        <h3>${escapeHTML(player)}</h3>

        <div class="official-movement">
          <span>${escapeHTML(oldClub || "Clube anterior não indicado")}</span>
          <span class="movement-arrow">→</span>
          <strong>${escapeHTML(newClub || "Novo clube não indicado")}</strong>
        </div>

        <p class="card-summary">
          ${escapeHTML(type)}${fee ? ` · ${escapeHTML(fee)}` : ""}
        </p>

        <div class="card-actions">
          <a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">
            Anúncio oficial ↗
          </a>
        </div>
      </article>
    `;
  }

  function ensureOfficialSection() {
    let section = $("#official-section");

    if (section) {
      return section;
    }

    const feed = $("#rumour-feed");

    if (!feed) {
      return null;
    }

    section = document.createElement("section");
    section.id = "official-section";
    section.className = "official-section";

    section.innerHTML = `
      <h2>Transferências oficiais</h2>
      <div id="official-feed" class="official-feed"></div>
      <p id="official-empty">
        Ainda não existem transferências oficiais registadas.
      </p>
    `;

    feed.parentElement?.insertBefore(section, feed);

    return section;
  }

  function matchesFilters(item) {
    const search = normalize($("#search")?.value || "");
    const phase = $("#status-filter")?.value || "";
    const verification = $("#verification-filter")?.value || "";
    const region = $("#league-filter")?.value || "";

    if (search && !item._search.includes(search)) {
      return false;
    }

    if (
      phase &&
      normalize(item._phase) !==
      normalize(PHASE_ALIASES[normalize(phase)] || phase)
    ) {
      return false;
    }

    if (
      verification &&
      normalize(item._verification) !== normalize(verification)
    ) {
      return false;
    }

    if (region) {
      if (region === "Europa") {
        return item._regions.length === 0;
      }

      if (!item._regions.some(
        value => normalize(value) ===
          normalize(REGION_ALIASES[normalize(region)] || region)
      )) {
        return false;
      }
    }

    return true;
  }

  function update() {
    const rumourFeed = $("#rumour-feed");

    if (!rumourFeed) {
      return;
    }

    const filtered = state.candidates
      .map(normalizeCandidate)
      .filter(item => !isOfficial(item))
      .filter(matchesFilters);

    rumourFeed.innerHTML = filtered
      .map(renderRumour)
      .join("");

    const count = $("#result-count");

    if (count) {
      count.textContent = String(filtered.length);
    }

    const empty = $("#empty-state");

    if (empty) {
      empty.hidden = filtered.length !== 0;
    }

    ensureOfficialSection();

    const officialFeed = $("#official-feed");

    if (officialFeed) {
      officialFeed.innerHTML = state.officials
        .filter(isOfficial)
        .sort((a, b) =>
          new Date(b.announcementDate || b.date || 0) -
          new Date(a.announcementDate || a.date || 0)
        )
        .map(renderOfficial)
        .join("");

      const officialEmpty = $("#official-empty");

      if (officialEmpty) {
        officialEmpty.hidden = officialFeed.innerHTML !== "";
      }
    }

    const demoAlert = $(".demo-alert");

    if (demoAlert) {
      demoAlert.hidden = state.candidates.length > 0;
    }

    const today = $("#today-label");

    if (today) {
      today.textContent = new Intl.DateTimeFormat("pt-PT", {
        dateStyle: "full"
      }).format(new Date());
    }
  }

  async function readJSON(url, fallback) {
    try {
      const response = await fetch(
        `${url}?v=${Date.now()}`,
        { cache: "no-store" }
      );

      if (!response.ok) {
        throw new Error(
          `${response.status} ${response.statusText}`
        );
      }

      return await response.json();

    } catch (error) {
      console.warn(
        `TRANSFER MARKET: não foi possível carregar ${url}`,
        error
      );

      return fallback;
    }
  }

  async function load() {
    const [candidates, officials] = await Promise.all([
      readJSON(CONFIG.candidatesUrl, []),
      readJSON(CONFIG.officialUrl, [])
    ]);

    state.candidates = Array.isArray(candidates)
      ? candidates
      : [];

    state.officials = Array.isArray(officials)
      ? officials
      : [];

    update();
  }

  function bindFilters() {
    ensureVerificationFilter();

    [
      "#search",
      "#status-filter",
      "#verification-filter",
      "#league-filter"
    ].forEach(selector => {
      $(selector)?.addEventListener(
        selector === "#search" ? "input" : "change",
        update
      );
    });

    $("#clear-filters")?.addEventListener("click", event => {
      event.preventDefault();

      [
        "#search",
        "#status-filter",
        "#verification-filter",
        "#league-filter"
      ].forEach(selector => {
        const element = $(selector);

        if (element) {
          element.value = "";
        }
      });

      update();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindFilters();
    load();

    state.timer = window.setInterval(
      load,
      CONFIG.refreshInterval
    );
  });

})();
