
import feedparser
import json
import os
import re
import hashlib

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from difflib import SequenceMatcher
from html import unescape

# =====================================================
# TRANSFER MARKET — MOTOR DE RECOLHA V2.0
# =====================================================

OUTPUT_FILE = "candidatos.json"
MAX_ARTICLES_PER_SOURCE = 100
MAX_CANDIDATES = 300
MAX_AGE_DAYS = 30

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
    }
]

KEYWORDS = [
    "transfer", "transfers", "transferência",
    "transferências", "signing", "signed",
    "signs", "deal", "bid", "loan",
    "agreement", "agreed", "interest",
    "interested", "target", "targets",
    "joins", "contract", "release clause",
    "negotiations", "mercado", "negociações"
]

# =====================================================
# FUNÇÕES DE TEXTO
# =====================================================

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


def is_transfer_article(title, summary):
    text = normalize(title + " " + summary)

    for keyword in KEYWORDS:
        pattern = r"(?<!\w)" + re.escape(
            normalize(keyword)
        ) + r"(?!\w)"

        if re.search(pattern, text):
            return True

    return False


def make_id(url):
    return hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()[:20]


# =====================================================
# DATAS
# =====================================================

def article_date(entry):
    parsed = entry.get("published_parsed")

    if not parsed:
        parsed = entry.get("updated_parsed")

    if parsed:
        from time import mktime
        timestamp = mktime(parsed)

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
        try:
            date = parsedate_to_datetime(raw_date)

            if date.tzinfo is None:
                date = date.replace(
                    tzinfo=timezone.utc
                )

            return date.astimezone(
                timezone.utc
            ).isoformat()

        except Exception:
            pass

    return datetime.now(timezone.utc).isoformat()


def is_recent(date_string):
    try:
        date = datetime.fromisoformat(
            date_string.replace("Z", "+00:00")
        )

        age = datetime.now(timezone.utc) - date

        return age.total_seconds() >= 0 and (
            age.days <= MAX_AGE_DAYS
        )

    except Exception:
        return False


# =====================================================
# RECOLHA DE NOTÍCIAS
# =====================================================

def collect_articles():
    articles = []

    for source in SOURCES:
        print("A consultar:", source["name"])

        try:
            feed = feedparser.parse(
                source["url"],
                request_headers={
                    "User-Agent": "TransferMarket/2.0"
                }
            )

            if not feed.entries:
                print("Feed sem artigos:", source["name"])
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

                if not url.startswith("https://"):
                    continue

                if not is_transfer_article(title, summary):
                    continue

                date = article_date(entry)

                if not is_recent(date):
                    continue

                articles.append({
                    "id": make_id(url),
                    "title": title,
                    "summary": summary[:1200],
                    "source": source["name"],
                    "domain": source["domain"],
                    "url": url,
                    "date": date
                })

        except Exception as error:
            print(
                "Erro na fonte",
                source["name"],
                ":",
                error
            )

    return articles


# =====================================================
# HISTÓRICO E DUPLICADOS
# =====================================================

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


def merge_articles(previous, new_articles):
    records = {}

    for item in previous:
        if isinstance(item, dict) and item.get("id"):
            records[item["id"]] = item

    now = datetime.now(timezone.utc).isoformat()

    for article in new_articles:
        article_id = article["id"]

        if article_id in records:
            old = records[article_id]

            old["lastSeen"] = now
            old["summary"] = article["summary"]
            old["title"] = article["title"]

        else:
            article["firstSeen"] = now
            article["lastSeen"] = now

            article["status"] = "Por verificar"

            article["verification"] = (
                "Artigo recolhido automaticamente. "
                "Ainda não foi verificado editorialmente."
            )

            article["player"] = ""
            article["currentClub"] = ""
            article["destination"] = ""

            records[article_id] = article

    results = list(records.values())

    results.sort(
        key=lambda item: item.get("date", ""),
        reverse=True
    )

    return results[:MAX_CANDIDATES]


# =====================================================
# IDENTIFICAÇÃO DE ARTIGOS SEMELHANTES
# =====================================================

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
            ) >= 0.82:

                group.append(article)
                found = True
                break

        if not found:
            groups.append([article])

    return groups


# =====================================================
# RELATÓRIO DE FONTES
# =====================================================

def build_source_report(articles):
    groups = find_similar_articles(articles)

    report = []

    for group in groups:
        domains = sorted({
            article["domain"]
            for article in group
        })

        report.append({
            "title": group[0]["title"],
            "articlesFound": len(group),
            "differentDomains": len(domains),
            "sources": [
                {
                    "name": article["source"],
                    "url": article["url"],
                    "date": article["date"]
                }
                for article in group
            ],
            "editorialStatus": "Por verificar"
        })

    return report


# =====================================================
# GUARDAR RESULTADOS
# =====================================================

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


# =====================================================
# EXECUÇÃO PRINCIPAL
# =====================================================

def main():
    print("=" * 55)
    print("TRANSFER MARKET — MOTOR V2.0")
    print("=" * 55)

    previous = load_previous()

    print(
        "Artigos no histórico:",
        len(previous)
    )

    articles = collect_articles()

    print(
        "Novos artigos recolhidos:",
        len(articles)
    )

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
        "relatorio_fontes.json",
        report
    )

    print(
        "Candidatos guardados:",
        len(candidates)
    )

    print(
        "Grupos de artigos encontrados:",
        len(report)
    )

    print("Atualização concluída.")


if __name__ == "__main__":
    main()
