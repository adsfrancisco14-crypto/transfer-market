const feed = document.getElementById("rumour-feed");
const searchInput = document.getElementById("search");
const statusFilter = document.getElementById("status-filter");
const leagueFilter = document.getElementById("league-filter");
const count = document.getElementById("result-count");
const empty = document.getElementById("empty-state");
const today = document.getElementById("today-label");

if (today) today.textContent = new Intl.DateTimeFormat("pt-PT", { dateStyle: "long" }).format(new Date());

function statusClass(status) {
  return status.toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").replaceAll(" ", "-");
}
function render(items) {
  feed.innerHTML = "";
  count.textContent = `${items.length} ${items.length === 1 ? "resultado" : "resultados"}`;
  empty.hidden = items.length !== 0;
  items.forEach(item => {
    const card = document.createElement("article");
    card.className = "rumour-card";
    const content = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = item.player;
    const route = document.createElement("div");
    route.className = "transfer-route";
    route.textContent = `${item.currentClub}  →  ${item.destination}`;
    const summary = document.createElement("p");
    summary.className = "rumour-summary";
    summary.textContent = item.summary;
    const meta = document.createElement("div");
    meta.className = "rumour-meta";
    const league = document.createElement("span");
    league.textContent = item.league;
    const date = document.createElement("span");
    date.textContent = item.date;
    const source = document.createElement("span");
    source.textContent = `Fonte: ${item.source}`;
    meta.append(league, date, source);
    if (item.url && item.url !== "#") {
      const link = document.createElement("a");
      link.href = item.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.textContent = "Ver fonte original ↗"; meta.append(link);
    }
    content.append(title, route, summary, meta);
    const badge = document.createElement("span");
    badge.className = `status status-${statusClass(item.status)}`;
    badge.textContent = item.status;
    card.append(content, badge);
    feed.append(card);
  });
}
let allItems = [];
function applyFilters() {
  const term = searchInput.value.trim().toLocaleLowerCase("pt-PT");
  const status = statusFilter.value;
  const league = leagueFilter.value;
  const filtered = allItems.filter(item => {
    const haystack = [item.player, item.currentClub, item.destination, item.summary, item.source].join(" ").toLocaleLowerCase("pt-PT");
    return (!term || haystack.includes(term)) && (status === "all" || item.status === status) && (league === "all" || item.league === league);
  });
  render(filtered);
}
Promise.all([fetch("data/rumores.json").then(r => { if (!r.ok) throw new Error("Não foi possível carregar os dados"); return r.json(); })])
  .then(([data]) => { allItems = data; applyFilters(); })
  .catch(() => { count.textContent = "Dados indisponíveis"; empty.hidden = false; });
[searchInput, statusFilter, leagueFilter].forEach(el => el.addEventListener("input", applyFilters));
document.getElementById("clear-filters").addEventListener("click", () => {
  searchInput.value = ""; statusFilter.value = "all"; leagueFilter.value = "all"; applyFilters();
});