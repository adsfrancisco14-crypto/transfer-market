
import feedparser
import json
import os
import re
import hashlib
import calendar

from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from html import unescape
from urllib.parse import urlparse

# ============================================================
# TRANSFER MARKET — INTELLIGENCE ENGINE V3.0
# Motor inteligente de recolha de notícias de transferências
# ============================================================

VERSION = "3.0"

OUTPUT_FILE = "candidatos.json"
REPORT_FILE = "relatorio_fontes.json"

MAX_ARTICLES_PER_SOURCE = 100
MAX_CANDIDATES = 300
MAX_AGE_DAYS = 30
SIMILARITY_THRESHOLD = 0.78

USER_AGENT = "TRANSFER-MARKET/3.0"

# ============================================================
# FONTES
# ============================================================

SOURCES = [
    {
        "name": "BBC Sport",
        "url": "https://feeds.bbci.co.uk/sport/football/rss.xml",
        "domain": "bbc.co.uk"
    },
    {
        "name": "Sky Sports",
        "url": "https://www.skysports.com/rss/11095",
        "domain": "skysports.com"
    },
    {
        "name": "Fabrizio Romano",
        "url": os.environ.get(
            "FABRIZIO_RSS_URL",
            "https://rsshub.app/telegram/channel/fabrizioromanotg"
        ),
        "domain": "t.me"
    }
]

# O feed de Fabrizio utiliza um serviço público intermediário.
# Não é um feed RSS oficial do jornalista.
# Não são utilizadas publicações do X.

# ============================================================
# PALAVRAS-CHAVE E CLASSIFICAÇÃO
# ============================================================

TRANSFER_KEYWORDS = [
    "transfer", "transfers", "transferência",
    "transferências", "transfer market",
    "signing", "signed", "signs",
    "deal", "bid", "loan",
    "agreement", "agreed",
    "interest", "interested",
    "target", "targets",
    "joins", "joined",
    "contract", "release clause",
    "negotiations", "negotiation",
    "mercado", "negociações",
    "contratação", "contrato",
    "emprestado", "empréstimo",
    "proposta", "propostas",
    "renovação", "renews",
    "extends contract",
    "here we go",
    "medical", "personal terms",
    "official announcement"
]

TRANSFER_ACTIONS = [
    "sign", "signed", "signing",
    "join", "joined", "joining",
    "move", "moving",
    "transfer", "deal",
    "bid", "offer",
    "loan", "agreement",
    "negotiate", "negotiations",
    "interest", "target",
    "release clause",
    "renew", "renewal",
    "extend", "here we go"
]

GENERAL_NEWS_KEYWORDS = [
    "match report",
    "live commentary",
    "highlights",
    "player ratings",
    "starting line-up",
    "lineup",
    "kick-off",
    "goal of the season",
    "match preview",
    "fixture",
    "result",
    "champions league preview"
]

CONFIRMATION_KEYWORDS = [
    "officially announced",
    "official announcement",
    "club confirms signing",
    "has officially signed",
    "transfer confirmed"
]

# ============================================================
# CLUBES — DICIONÁRIO DE IDENTIFICAÇÃO
# ============================================================

CLUBS = {
    "Arsenal": ["Arsenal"],
    "Chelsea": ["Chelsea"],
    "Liverpool": ["Liverpool"],
    "Manchester City": ["Manchester City", "Man City"],
    "Manchester United": ["Manchester United", "Man United", "Man Utd"],
    "Tottenham": ["Tottenham", "Spurs"],
    "Newcastle": ["Newcastle United", "Newcastle"],
    "Aston Villa": ["Aston Villa"],
    "Everton": ["Everton"],
    "West Ham": ["West Ham United", "West Ham"],
    "Brighton": ["Brighton", "Brighton and Hove Albion"],
    "Real Madrid": ["Real Madrid"],
    "Barcelona": ["Barcelona", "Barça"],
    "Atletico Madrid": ["Atletico Madrid", "Atlético Madrid"],
    "Girona": ["Girona"],
    "Sevilla": ["Sevilla"],
    "Valencia": ["Valencia"],
    "Bayern Munich": ["Bayern Munich", "Bayern München"],
    "Borussia Dortmund": ["Borussia Dortmund", "Dortmund"],
    "RB Leipzig": ["RB Leipzig", "Leipzig"],
    "Bayer Leverkusen": ["Bayer Leverkusen", "Leverkusen"],
    "Eintracht Frankfurt": ["Eintracht Frankfurt"],
    "Juventus": ["Juventus"],
    "Inter": ["Inter Milan", "Inter Milano", "Inter"],
    "AC Milan": ["AC Milan", "Milan"],
    "Napoli": ["Napoli"],
    "Roma": ["AS Roma", "Roma"],
    "Lazio": ["Lazio"],
    "Atalanta": ["Atalanta"],
    "Paris Saint-Germain": ["Paris Saint-Germain", "PSG"],
    "Marseille": ["Marseille"],
    "Monaco": ["AS Monaco", "Monaco"],
    "Lyon": ["Lyon"],
    "Lille": ["Lille"],
    "Ajax": ["Ajax Amsterdam", "Ajax"],
    "PSV": ["PSV Eindhoven", "PSV"],
    "Feyenoord": ["Feyenoord"],
    "Benfica": ["Benfica"],
    "Porto": ["FC Porto", "Porto"],
    "Sporting": ["Sporting CP", "Sporting"],
    "Braga": ["SC Braga", "Braga"],
    "Galatasaray": ["Galatasaray"],
    "Fenerbahce": ["Fenerbahçe", "Fenerbahce"],
    "Besiktas": ["Besiktas", "Beşiktaş"],
    "Al Hilal": ["Al Hilal"],
    "Al Nassr": ["Al Nassr"],
    "Al Ittihad": ["Al Ittihad"]
}

# ============================================================
# JOGADORES
# ============================================================

# Criar futuramente um ficheiro players.json para associar
# jogadores aos respetivos clubes atuais.
#
# Exemplo:
#
# {
#   "Nome do Jogador": {
#       "currentClub": "Nome do Clube"
#   }
# }
#
# O motor não inventa jogadores nem clubes.

def load_players():
    filename = "players.json"

    if not os.path.exists(filename):
        return {}

    try:
        with open(filename, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except (OSError, json.JSONDecodeError):
        print("Erro ao carregar players.json")
        return {}


# ============================================================
# TEXTO
# ============================================================

def clean_text(value):
    value = unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def contains_phrase(text, phrase):
    pattern = (
        r"(?<!\w)"
        + re.escape(normalize(phrase))
        + r"(?!\w)"
    )

    return bool(re.search(pattern, normalize(text)))


# ============================================================
# FILTRO INTELIGENTE
# ============================================================

def classify_article(title, summary):

    text = normalize(title + " " + summary)

    transfer_matches = [
        word for word in TRANSFER_KEYWORDS
        if contains_phrase(text, word)
    ]

    general_matches = [
        word for word in GENERAL_NEWS_KEYWORDS
        if contains_phrase(text, word)
    ]

    action_matches = [
        word for word in TRANSFER_ACTIONS
        if contains_phrase(text, word)
    ]

    if not transfer_matches:
        return {
            "isTransfer": False,
            "classification": "Notícia geral",
            "relevance": 0
        }

    score = (
        len(transfer_matches) * 2
        + len(action_matches) * 2
    )

    if general_matches:
        score -= len(general_matches)

    if score < 2:
        return {
            "isTransfer": False,
            "classification": "Notícia geral",
            "relevance": score
        }

    return {
        "isTransfer": True,
        "classification": "Notícia de transferências",
        "relevance": score
    }


# ============================================================
# IDENTIFICAÇÃO DE JOGADORES
# ============================================================

def identify_players(text, players):

    found = []

    normalized_text = normalize(text)

    for player in players:

        if contains_phrase(normalized_text, player):
            found.append(player)

    return sorted(set(found), key=len, reverse=True)


# ============================================================
# IDENTIFICAÇÃO DE CLUBES
# ============================================================

def identify_clubs(text):

    found = []

    normalized_text = normalize(text)

    for club, aliases in CLUBS.items():

        for alias in aliases:

            if contains_phrase(normalized_text, alias):
                found.append(club)
                break

    return sorted(set(found))


# ============================================================
# IDENTIFICAÇÃO DO CLUBE ATUAL E DESTINO
# ============================================================

def identify_transfer_details(text, players):

    detected_players = identify_players(text, players)
    detected_clubs = identify_clubs(text)

    current_club = ""
    destination = ""

    text_lower = normalize(text)

    for player in detected_players:

        information = players.get(player, {})

        if isinstance(information, dict):
            current_club = information.get(
                "currentClub", ""
            )

        if current_club:
            break

    # Identificação de expressões de destino explícito.
    destination_patterns = [
        r"\bto\s+([A-Za-z][A-Za-z .'-]{2,35})",
        r"\bpara\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{2,35})",
        r"\bjoins\s+([A-Za-z][A-Za-z .'-]{2,35})"
    ]

    # Só aceitar destinos pertencentes ao dicionário de clubes.
    for club, aliases in CLUBS.items():

        for alias in aliases:

            escaped = re.escape(normalize(alias))

            patterns = [
                r"\bto\s+" + escaped + r"\b",
                r"\bpara\s+" + escaped + r"\b",
                r"\bjoins\s+" + escaped + r"\b",
                r"\bjoin\s+" + escaped + r"\b"
            ]

            if any(
                re.search(pattern, text_lower)
                for pattern in patterns
            ):
                destination = club
                break

        if destination:
            break

    # Evitar confundir o clube atual com o destino.
    if destination == current_club:
        destination = ""

    return {
        "players": detected_players,
        "clubs": detected_clubs,
        "currentClub": current_club,
        "destination": destination
    }


# ============================================================
# IDENTIFICADORES
# ============================================================

def make_id(url):

    return hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()[:20]


# ============================================================
# DATAS
# ============================================================

def article_date(entry):

    parsed = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
    )

    if parsed:

        timestamp = calendar.timegm(parsed)

        return datetime.fromtimestamp(
            timestamp,
            timezone.utc
        ).isoformat()

    raw_date = (
        entry.get("published")
        or entry.get("updated")
        or ""
    )

    if raw_date:

        from email.utils import parsedate_to_datetime

        try:
            date = parsedate_to_datetime(raw_date)

            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)

            return date.astimezone(
                timezone.utc
            ).isoformat()

        except Exception:
            pass

    return ""


def is_recent(date_string):

    if not date_string:
        return False

    try:
        date = datetime.fromisoformat(
            date_string.replace("Z", "+00:00")
        )

        age = datetime.now(timezone.utc) - date

        return (
            timedelta(0) <= age
            <= timedelta(days=MAX_AGE_DAYS)
        )

    except (ValueError, TypeError):
        return False


# ============================================================
# RECOLHA
# ============================================================

def collect_articles():

    articles = []
    players = load_players()

    for source in SOURCES:

        print("A consultar:", source["name"])

        try:

            feed = feedparser.parse(
                source["url"],
                request_headers={
                    "User-Agent": USER_AGENT
                }
            )

            if getattr(feed, "bozo", False):
                print(
                    "Aviso: feed com problemas:",
                    source["name"]
                )

            if not feed.entries:
                print(
                    "Feed sem artigos:",
                    source["name"]
                )
                continue

            for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:

                title = clean_text(
                    entry.get("title", "")
                )

                summary = clean_text(
                    entry.get("summary", "")
                )

                url = entry.get("link", "").strip()

                if not title or not url:
                    continue

                parsed_url = urlparse(url)

                if parsed_url.scheme != "https":
                    continue

                if not parsed_url.netloc:
                    continue

                classification = classify_article(
                    title,
                    summary
                )

                if not classification["isTransfer"]:
                    continue

                date = article_date(entry)

                if not is_recent(date):
                    continue

                details = identify_transfer_details(
                    title + " " + summary,
                    players
                )

                articles.append({

                    "id": make_id(url),

                    "title": title,

                    "summary": summary[:1200],

                    "source": source["name"],

                    "domain": source["domain"],

                    "url": url,

                    "date": date,

                    "classification": classification[
                        "classification"
                    ],

                    "transferRelevance": classification[
                        "relevance"
                    ],

                    "player": (
                        details["players"][0]
                        if details["players"]
                        else ""
                    ),

                    "detectedPlayers": details["players"],

                    "detectedClubs": details["clubs"],

                    "currentClub": details["currentClub"],

                    "destination": details["destination"],

                    "status": "Por verificar",

                    "verification": (
                        "Candidato recolhido automaticamente. "
                        "Sem validação editorial."
                    )

                })

        except Exception as error:

            print(
                "Erro na fonte",
                source["name"],
                ":",
                error
            )

    return articles


# ============================================================
# HISTÓRICO
# ============================================================

def load_previous():

    if not os.path.exists(OUTPUT_FILE):
        return []

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        return data if isinstance(data, list) else []

    except (OSError, json.JSONDecodeError):

        print("Não foi possível ler o histórico.")

        return []


# ============================================================
# AGRUPAMENTO DE NOTÍCIAS
# ============================================================

def similarity(first, second):

    return SequenceMatcher(
        None,
        normalize(first),
        normalize(second)
    ).ratio()


def find_similar_articles(articles):

    groups = []

    for article in articles:

        found = False

        for group in groups:

            reference = group[0]

            if similarity(
                article["title"],
                reference["title"]
            ) >= SIMILARITY_THRESHOLD:

                group.append(article)

                found = True

                break

        if not found:

            groups.append([article])

    return groups


# ============================================================
# RELATÓRIO DE FONTES INDEPENDENTES
# ============================================================

def build_source_report(articles):

    groups = find_similar_articles(articles)

    report = []

    for group in groups:

        domains = sorted({
            article["domain"]
            for article in group
        })

        sources = []

        for article in group:

            sources.append({

                "name": article["source"],

                "domain": article["domain"],

                "url": article["url"],

                "date": article["date"]

            })

        report.append({

            "title": group[0]["title"],

            "articlesFound": len(group),

            "differentDomains": len(domains),

            "sources": sources,

            "independentSources": len(domains),

            "editorialStatus": "Por verificar",

            "confirmation": False,

            "note": (
                "A semelhança entre artigos não confirma "
                "a veracidade de uma transferência. "
                "É necessária verificação editorial."
            )

        })

    return report


# ============================================================
# PRESERVAR CANDIDATOS ANTERIORES
# ============================================================

def merge_articles(previous, new_articles):

    records = {}

    now = datetime.now(timezone.utc).isoformat()

    for item in previous:

        if isinstance(item, dict) and item.get("id"):

            records[item["id"]] = item

    for article in new_articles:

        article_id = article["id"]

        if article_id in records:

            old = records[article_id]

            # Atualizar informação recolhida sem apagar
            # eventuais decisões editoriais anteriores.

            old["lastSeen"] = now

            old["title"] = article["title"]

            old["summary"] = article["summary"]

            old["date"] = article["date"]

            for field in [
                "player",
                "detectedPlayers",
                "detectedClubs",
                "currentClub",
                "destination",
                "classification",
                "transferRelevance"
            ]:

                if article.get(field):
                    old[field] = article[field]

        else:

            article["firstSeen"] = now

            article["lastSeen"] = now

            article["editorApproved"] = False

            records[article_id] = article

    results = list(records.values())

    results.sort(
        key=lambda item: item.get("date", ""),
        reverse=True
    )

    return results[:MAX_CANDIDATES]


# ============================================================
# IDENTIFICAÇÃO DE GRUPOS
# ============================================================

def add_group_information(articles):

    groups = find_similar_articles(articles)

    for group in groups:

        domains = sorted({
            article["domain"]
            for article in group
        })

        group_id = hashlib.sha256(
            normalize(group[0]["title"]).encode("utf-8")
        ).hexdigest()[:12]

        for article in group:

            article["similarGroupId"] = group_id

            article["similarArticles"] = len(group)

            article["independentSources"] = len(domains)

            article["editorialStatus"] = "Por verificar"

            article["confirmed"] = False

    return articles


# ============================================================
# GUARDAR JSON COM SEGURANÇA
# ============================================================

def save_json(filename, data):

    temporary = filename + ".tmp"

    with open(
        temporary,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temporary, filename)


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main():

    print("=" * 65)

    print("TRANSFER MARKET — INTELLIGENCE ENGINE V" + VERSION)

    print("=" * 65)

    previous = load_previous()

    print(
        "Candidatos anteriores:",
        len(previous)
    )

    articles = collect_articles()

    print(
        "Artigos relevantes encontrados:",
        len(articles)
    )

    articles = add_group_information(articles)

    candidates = merge_articles(
        previous,
        articles
    )

    report = build_source_report(
        articles
    )

    save_json(
        OUTPUT_FILE,
        candidates
    )

    save_json(
        REPORT_FILE,
        report
    )

    print("-" * 65)

    print(
        "Candidatos guardados:",
        len(candidates)
    )

    print(
        "Grupos de notícias:",
        len(report)
    )

    print(
        "Fontes configuradas:",
        len(SOURCES)
    )

    print(
        "Jogadores reconhecidos:",
        sum(
            1 for item in articles
            if item.get("player")
        )
    )

    print(
        "Clubes identificados:",
        sum(
            1 for item in articles
            if item.get("detectedClubs")
        )
    )

    print("-" * 65)

    print(
        "Estado editorial: TODOS OS NOVOS CANDIDATOS "
        "AGUARDAM VERIFICAÇÃO."
    )

    print("Atualização concluída.")

    print("=" * 65)


if __name__ == "__main__":

    main()
