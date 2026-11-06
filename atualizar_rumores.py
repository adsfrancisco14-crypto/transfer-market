#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TRANSFER MARKET — INTELLIGENCE ENGINE V4.0
Recolhe notícias de transferências, traduz para português de Portugal,
preserva o original, remove duplicados e gera:
  - candidatos.json
  - relatorio_fontes.json

Compatível com o site GitHub Pages existente.
IMPORTANTE:
- Não altera rumores.json.
- Não publica automaticamente rumores no site.
- Todos os candidatos começam como "Por verificar".
- Não utiliza publicações do X como fonte.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import feedparser

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None


# ============================================================
# CONFIGURAÇÃO
# ============================================================

VERSION = "4.0"
BASE_DIR = Path(__file__).resolve().parent

OUTPUT_FILE = BASE_DIR / "candidatos.json"
REPORT_FILE = BASE_DIR / "relatorio_fontes.json"
HISTORY_FILE = BASE_DIR / "historico_transferencias.json"
PLAYERS_FILE = BASE_DIR / "players.json"

MAX_AGE_DAYS = int(os.getenv("MAX_AGE_DAYS", "30"))
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "300"))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.78"))
TRANSLATION_DELAY = float(os.getenv("TRANSLATION_DELAY", "0.25"))
TRANSLATION_ENABLED = os.getenv("TRANSLATION_ENABLED", "true").lower() not in {
    "0", "false", "no", "off"
}

# Fontes RSS. Podem ser substituídas/adicionadas através de variáveis
# de ambiente sem ser necessário alterar o código.
SOURCES = [
    {
        "name": "BBC Sport",
        "url": os.getenv(
            "BBC_RSS_URL",
            "https://feeds.bbci.co.uk/sport/football/rss.xml"
        ),
    },
    {
        "name": "Sky Sports",
        "url": os.getenv(
            "SKY_RSS_URL",
            "https://www.skysports.com/rss/12040"
        ),
    },
]

# Fonte opcional. Só será usada se FABRIZIO_RSS_URL estiver configurado.
fabrizio_url = os.getenv("FABRIZIO_RSS_URL", "").strip()
if fabrizio_url:
    SOURCES.append({"name": "Fonte configurada — Fabrizio", "url": fabrizio_url})


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("transfer-market")


# ============================================================
# PALAVRAS-CHAVE E CLASSIFICAÇÃO
# ============================================================

TRANSFER_KEYWORDS = [
    "transfer", "transfers", "transfer news", "transfer rumour",
    "transfer rumor", "signing", "sign", "signed", "deal", "agreement",
    "loan", "bid", "offer", "interest", "target", "talks", "negotiations",
    "contract", "release clause", "medical", "here we go",
    "mercato", "transferts", "fichajes", "calciomercato",
    "mercado de transferências", "transferência", "contratação",
    "empréstimo", "negociações", "proposta"
]

CONFIRMED_KEYWORDS = [
    "official", "confirmed", "completes move", "joins", "has joined",
    "signs for", "signed for", "announces", "here we go",
    "officially"
]

ADVANCED_KEYWORDS = [
    "agreement reached", "deal agreed", "verbal agreement",
    "personal terms agreed", "medical booked", "medical scheduled",
    "final stages", "close to completing", "advanced talks"
]

NEGOTIATION_KEYWORDS = [
    "negotiations", "talks", "bid", "offer", "proposal",
    "discussions", "in talks", "opening offer"
]

RUMOUR_KEYWORDS = [
    "interested", "interest", "monitoring", "tracking",
    "considering", "target", "could sign", "linked with",
    "rumour", "rumor", "reportedly"
]

GENERAL_NEWS_EXCLUSIONS = [
    "match report", "live commentary", "live score", "highlights",
    "fixture", "fixtures", "table", "standings", "injury update",
    "manager press conference", "predicted lineup", "team news"
]


# ============================================================
# FUNÇÕES GERAIS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def clean_html(value: str) -> str:
    """Remove HTML e normaliza espaços."""
    if not value:
        return ""
    value = unescape(str(value))
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_text(value: str) -> str:
    value = clean_html(value).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", value).strip()


def normalize_url(url: str) -> str:
    """Retira parâmetros de tracking e fragmentos."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        host = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.rstrip("/")
        return urlunparse((parsed.scheme or "https", host, path, "", "", ""))
    except Exception:
        return url.strip()


def make_id(url: str, title: str) -> str:
    basis = normalize_url(url) or normalize_text(title)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def parse_entry_date(entry) -> datetime | None:
    for field in ("published", "updated", "created"):
        raw = entry.get(field)
        if not raw:
            continue
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass

    for field in ("published_parsed", "updated_parsed"):
        parsed_tuple = entry.get(field)
        if parsed_tuple:
            try:
                from time import mktime
                return datetime.fromtimestamp(
                    mktime(parsed_tuple), timezone.utc
                )
            except Exception:
                pass
    return None


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:
        log.warning("Não foi possível ler %s: %s", path.name, exc)
        return default


def save_json(path: Path, data) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temp_path.replace(path)


# ============================================================
# TRADUÇÃO
# ============================================================

_translation_cache: dict[str, str] = {}


def translate_to_pt(value: str) -> str:
    """
    Traduz texto para português.
    Se o serviço de tradução falhar, mantém o original.
    O original é sempre preservado nos campos originalTitle/originalSummary.
    """
    value = clean_html(value)
    if not value or not TRANSLATION_ENABLED or GoogleTranslator is None:
        return value

    if value in _translation_cache:
        return _translation_cache[value]

    try:
        translator = GoogleTranslator(source="auto", target="pt")
        translated = translator.translate(value)
        if translated and translated.strip():
            result = translated.strip()
        else:
            result = value
        _translation_cache[value] = result
        time.sleep(TRANSLATION_DELAY)
        return result
    except Exception as exc:
        log.warning("Falha na tradução; será mantido o original: %s", exc)
        _translation_cache[value] = value
        return value


# ============================================================
# JOGADORES E CLUBES
# ============================================================

def load_players() -> list[dict]:
    raw = load_json(PLAYERS_FILE, [])
    players = []

    # Formato recomendado:
    # [
    #   {"name":"Nome do jogador","currentClub":"Clube"},
    #   ...
    # ]
    if isinstance(raw, dict):
        raw = raw.get("players", [])

    if not isinstance(raw, list):
        return players

    for item in raw:
        if isinstance(item, str):
            players.append({"name": item, "currentClub": ""})
        elif isinstance(item, dict) and item.get("name"):
            players.append({
                "name": str(item["name"]).strip(),
                "currentClub": str(item.get("currentClub", "")).strip(),
            })

    return players


def detect_players(text: str, players: list[dict]) -> list[dict]:
    found = []
    normalized = normalize_text(text)

    for player in players:
        name = player["name"]
        if not name:
            continue
        # Comparação sem acentos e sem distinguir maiúsculas/minúsculas.
        if normalize_text(name) in normalized:
            found.append(player)

    return found


# ============================================================
# CLASSIFICAÇÃO EDITORIAL
# ============================================================

def classify_article(title: str, summary: str) -> tuple[str, int, list[str]]:
    text = normalize_text(f"{title} {summary}")
    reasons = []

    keyword_hits = [
        keyword for keyword in TRANSFER_KEYWORDS
        if normalize_text(keyword) in text
    ]

    score = min(100, len(keyword_hits) * 15)
    if keyword_hits:
        reasons.append("Palavras-chave de mercado detetadas")

    if any(normalize_text(word) in text for word in CONFIRMED_KEYWORDS):
        status = "Possível confirmação"
        score = min(100, score + 25)
        reasons.append("Linguagem associada a anúncio ou confirmação")
    elif any(normalize_text(word) in text for word in ADVANCED_KEYWORDS):
        status = "Possível acordo avançado"
        score = min(100, score + 20)
        reasons.append("Linguagem associada a acordo avançado")
    elif any(normalize_text(word) in text for word in NEGOTIATION_KEYWORDS):
        status = "Possíveis negociações"
        score = min(100, score + 10)
        reasons.append("Referência a conversações, proposta ou negociações")
    elif any(normalize_text(word) in text for word in RUMOUR_KEYWORDS):
        status = "Rumor"
        reasons.append("Linguagem de interesse ou rumor")
    else:
        status = "Por verificar"

    if any(normalize_text(word) in text for word in GENERAL_NEWS_EXCLUSIONS):
        score -= 35
        reasons.append("Possível notícia geral, não centrada no mercado")

    return status, max(0, min(100, score)), reasons


# ============================================================
# RECOLHA RSS
# ============================================================

def get_entry_summary(entry) -> str:
    summary = entry.get("summary", "") or entry.get("description", "")
    if not summary and entry.get("content"):
        try:
            summary = entry["content"][0].get("value", "")
        except Exception:
            pass
    return clean_html(summary)


def fetch_source(source: dict) -> tuple[list[dict], dict]:
    source_name = source["name"]
    source_url = source["url"]

    report = {
        "source": source_name,
        "feed": source_url,
        "checkedAt": iso_now(),
        "status": "ok",
        "articlesRead": 0,
        "candidatesKept": 0,
        "error": None,
    }

    try:
        parsed = feedparser.parse(source_url)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise RuntimeError(str(getattr(parsed, "bozo_exception", "Erro RSS")))

        entries = []
        cutoff = utc_now() - timedelta(days=MAX_AGE_DAYS)

        for entry in parsed.entries:
            report["articlesRead"] += 1
            title = clean_html(entry.get("title", ""))
            url = normalize_url(entry.get("link", ""))
            summary = get_entry_summary(entry)

            if not title or not url:
                continue

            published = parse_entry_date(entry)
            if published and published < cutoff:
                continue

            # Sem data RSS, mantém a notícia mas assinala a ausência.
            date_value = (
                published.replace(microsecond=0).isoformat()
                if published else ""
            )

            entries.append({
                "title": title,
                "summary": summary,
                "url": url,
                "date": date_value,
                "source": source_name,
                "domain": urlparse(url).netloc.lower().replace("www.", ""),
            })

        return entries, report

    except Exception as exc:
        report["status"] = "erro"
        report["error"] = str(exc)
        log.error("Erro na fonte %s: %s", source_name, exc)
        return [], report


# ============================================================
# HISTÓRICO E DUPLICADOS
# ============================================================

def load_previous_candidates() -> list[dict]:
    old = load_json(OUTPUT_FILE, [])
    return old if isinstance(old, list) else []


def load_history() -> dict:
    history = load_json(HISTORY_FILE, {})
    return history if isinstance(history, dict) else {}


def merge_editorial_data(candidate: dict, previous_by_id: dict) -> dict:
    previous = previous_by_id.get(candidate["id"])
    if not previous:
        return candidate

    # Preserva decisões editoriais feitas anteriormente.
    for field in (
        "editorApproved", "editorNotes", "editorStatus",
        "manualPlayer", "manualCurrentClub", "manualDestination"
    ):
        if field in previous:
            candidate[field] = previous[field]

    return candidate


def is_similar_to_existing(candidate: dict, existing: list[dict]) -> bool:
    title = normalize_text(candidate.get("originalTitle", ""))
    if not title:
        return False

    for other in existing:
        other_title = normalize_text(
            other.get("originalTitle", other.get("title", ""))
        )
        if not other_title:
            continue

        if SequenceMatcher(None, title, other_title).ratio() >= SIMILARITY_THRESHOLD:
            return True

    return False


# ============================================================
# CONSTRUÇÃO DOS CANDIDATOS
# ============================================================

def build_candidate(article: dict, players: list[dict]) -> dict | None:
    original_title = article["title"]
    original_summary = article.get("summary", "")

    status, relevance, reasons = classify_article(
        original_title, original_summary
    )

    if relevance < 15:
        return None

    combined = f"{original_title} {original_summary}"
    detected = detect_players(combined, players)

    player_name = detected[0]["name"] if detected else ""
    current_club = detected[0]["currentClub"] if detected else ""

    translated_title = translate_to_pt(original_title)
    translated_summary = translate_to_pt(original_summary)

    candidate_id = make_id(article["url"], original_title)

    return {
        "id": candidate_id,

        # Campos principais usados pelo site.
        "title": translated_title,
        "summary": translated_summary,

        # Texto original para a opção "Ver original".
        "originalTitle": original_title,
        "originalSummary": original_summary,
        "originalLanguage": "en",
        "displayLanguage": "pt-PT",

        "source": article["source"],
        "domain": article["domain"],
        "url": article["url"],
        "date": article.get("date", ""),
        "collectedAt": iso_now(),

        "player": player_name,
        "currentClub": current_club,
        "destination": "",

        # A classificação automática é apenas uma sugestão.
        "status": status,
        "suggestedStatus": status,
        "relevance": relevance,
        "classificationReasons": reasons,

        "detectedPlayers": [p["name"] for p in detected],
        "editorApproved": False,
        "editorStatus": "Por verificar",
        "editorNotes": "",
        "independentSources": [article["source"]],
        "duplicateGroup": candidate_id,
        "engineVersion": VERSION,
    }


# ============================================================
# AGRUPAMENTO DE NOTÍCIAS SEMELHANTES
# ============================================================

def group_similar_candidates(candidates: list[dict]) -> None:
    groups: list[list[dict]] = []

    for candidate in candidates:
        placed = False
        title = normalize_text(candidate.get("originalTitle", ""))

        for group in groups:
            for other in group:
                other_title = normalize_text(other.get("originalTitle", ""))
                ratio = SequenceMatcher(None, title, other_title).ratio()

                same_player = (
                    candidate.get("player")
                    and candidate.get("player") == other.get("player")
                )

                if ratio >= SIMILARITY_THRESHOLD or (
                    same_player and ratio >= 0.55
                ):
                    group.append(candidate)
                    placed = True
                    break

            if placed:
                break

        if not placed:
            groups.append([candidate])

    for group in groups:
        group_id = min(item["id"] for item in group)
        sources = sorted({
            item["source"] for item in group if item.get("source")
        })

        for item in group:
            item["duplicateGroup"] = group_id
            item["independentSources"] = sources
            item["sourceCount"] = len(sources)


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    log.info("A iniciar TRANSFER MARKET INTELLIGENCE ENGINE V%s", VERSION)

    if TRANSLATION_ENABLED and GoogleTranslator is None:
        log.warning(
            "deep-translator não está instalado. "
            "Os textos serão mantidos no idioma original."
        )

    players = load_players()
    previous = load_previous_candidates()
    previous_by_id = {
        item.get("id"): item for item in previous if item.get("id")
    }

    history = load_history()
    known_ids = set(history.get("seenIds", []))

    # Também considera os candidatos já existentes.
    known_ids.update(previous_by_id.keys())

    all_articles = []
    source_reports = []

    for source in SOURCES:
        articles, report = fetch_source(source)
        all_articles.extend(articles)
        source_reports.append(report)

    # Mais recentes primeiro; notícias sem data ficam no fim.
    all_articles.sort(
        key=lambda item: item.get("date", ""),
        reverse=True
    )

    candidates = []
    seen_this_run = set()

    for article in all_articles:
        candidate_id = make_id(article["url"], article["title"])

        if candidate_id in seen_this_run:
            continue
        seen_this_run.add(candidate_id)

        candidate = build_candidate(article, players)
        if not candidate:
            continue

        # Mantém os candidatos anteriores no ficheiro, mas não volta
        # a criar a mesma notícia.
        if candidate_id in previous_by_id:
            continue

        # Agrupamento por semelhança evita repetir a mesma notícia
        # publicada por fontes diferentes como candidatos separados.
        if is_similar_to_existing(candidate, candidates):
            # A fonte adicional fica registada no grupo após agrupamento.
            candidates.append(candidate)
        else:
            candidates.append(candidate)

        known_ids.add(candidate_id)

    # Junta candidatos novos e antigos, preservando decisões editoriais.
    combined_by_id = {}

    for old in previous:
        if isinstance(old, dict) and old.get("id"):
            combined_by_id[old["id"]] = old

    for candidate in candidates:
        candidate = merge_editorial_data(candidate, previous_by_id)
        combined_by_id[candidate["id"]] = candidate

    final_candidates = list(combined_by_id.values())

    # Ordena por data e relevância.
    final_candidates.sort(
        key=lambda item: (
            item.get("date", ""),
            int(item.get("relevance", 0))
        ),
        reverse=True
    )

    final_candidates = final_candidates[:MAX_CANDIDATES]

    group_similar_candidates(final_candidates)

    for report in source_reports:
        report["candidatesKept"] = sum(
            1 for item in candidates if item.get("source") == report["source"]
        )

    report_data = {
        "engine": "TRANSFER MARKET — INTELLIGENCE ENGINE",
        "version": VERSION,
        "generatedAt": iso_now(),
        "translation": {
            "enabled": TRANSLATION_ENABLED,
            "target": "pt-PT",
            "provider": "GoogleTranslator via deep-translator",
            "originalPreserved": True,
        },
        "rules": {
            "maxAgeDays": MAX_AGE_DAYS,
            "similarityThreshold": SIMILARITY_THRESHOLD,
            "maxCandidates": MAX_CANDIDATES,
            "xPostsUsed": False,
            "automaticPublication": False,
        },
        "totals": {
            "sources": len(SOURCES),
            "articlesCollected": len(all_articles),
            "newCandidates": len(candidates),
            "totalCandidates": len(final_candidates),
            "confirmedByEditor": sum(
                1 for item in final_candidates
                if item.get("editorApproved") is True
            ),
            "awaitingReview": sum(
                1 for item in final_candidates
                if item.get("editorApproved") is not True
            ),
        },
        "sourcesReport": source_reports,
    }

    # O motor só escreve nos seus próprios ficheiros.
    save_json(OUTPUT_FILE, final_candidates)
    save_json(REPORT_FILE, report_data)

    # Histórico limitado para não crescer indefinidamente.
    history_ids = list(known_ids)
    history["seenIds"] = history_ids[-10000:]
    history["updatedAt"] = iso_now()
    save_json(HISTORY_FILE, history)

    log.info("Concluído.")
    log.info("Novos candidatos: %s", len(candidates))
    log.info("Total no ficheiro: %s", len(final_candidates))
    log.info("Ficheiro criado: %s", OUTPUT_FILE.name)
    log.info("Relatório criado: %s", REPORT_FILE.name)


if __name__ == "__main__":
    main()
