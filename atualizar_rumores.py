#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TRANSFER MARKET — INTELLIGENCE ENGINE V7.3
Recolhe RSS, filtra notícias de transferências de futebol, traduz títulos/resumos,
conserva os originais e as decisões editoriais e deduplica contra os registos existentes.
Nunca transforma uma notícia jornalística numa confirmação oficial.
"""
from __future__ import annotations

import os
import re
import json
import time
import hashlib
import logging
import unicodedata

from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

try:
    import feedparser
except ImportError as exc:
    raise SystemExit(
        "Falta feedparser. Instala com: pip install -r requirements.txt"
    ) from exc

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None


# ============================================================
# 1. CONFIGURAÇÃO
# ============================================================

VERSION = "7.3"
ROOT = Path(__file__).resolve().parent

CANDIDATOS = ROOT / "candidatos.json"
HISTORICO = ROOT / "historico_transferencias.json"
RELATORIO = ROOT / "relatorio_fontes.json"
JOGADORES = ROOT / "players.json"
OFICIAIS = ROOT / "oficiais.json"

MAX_DIAS = int(os.getenv("MAX_DIAS", "30"))
MAX_CANDIDATOS = int(os.getenv("MAX_CANDIDATOS", "500"))

SIMILARIDADE_DUPLICADOS = 0.93
PAUSA_TRADUCAO = 0.15
IDIOMA_TRADUCAO = "pt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("transfer-market")


# ============================================================
# 2. FONTES RSS
# ============================================================

FONTES = [
    {
        "nome": "BBC Sport",
        "url": "https://feeds.bbci.co.uk/sport/football/rss.xml"
    },
    {
        "nome": "Sky Sports",
        "url": "https://www.skysports.com/rss/12040"
    }
]

extra = os.getenv("FABRIZIO_RSS_URL", "").strip()

if extra:
    FONTES.append({
        "nome": "Fonte adicional",
        "url": extra
    })


# ============================================================
# 3. CLUBES E REGIÕES
# ============================================================

CLUBES = {
    "Inglaterra": [
        "Arsenal", "Aston Villa", "Bournemouth", "Brentford",
        "Brighton", "Burnley", "Chelsea", "Crystal Palace",
        "Everton", "Fulham", "Leeds United", "Liverpool",
        "Manchester City", "Manchester United", "Newcastle United",
        "Nottingham Forest", "Sunderland", "Tottenham",
        "West Ham", "Wolves", "Wolverhampton"
    ],

    "Espanha": [
        "Alaves", "Athletic Bilbao", "Atletico Madrid",
        "Barcelona", "Celta Vigo", "Elche", "Espanyol",
        "Getafe", "Girona", "Levante", "Mallorca",
        "Osasuna", "Real Madrid", "Real Betis",
        "Real Sociedad", "Sevilla", "Valencia",
        "Villarreal", "Rayo Vallecano", "Oviedo"
    ],

    "Itália": [
        "Atalanta", "Bologna", "Cagliari", "Como",
        "Cremonese", "Fiorentina", "Genoa", "Inter",
        "Juventus", "Lazio", "Lecce", "AC Milan",
        "Milan", "Napoli", "Parma", "Pisa",
        "Roma", "Sassuolo", "Torino", "Udinese"
    ],

    "Alemanha": [
        "Augsburg", "Bayern Munich", "Bayern",
        "Borussia Dortmund", "Dortmund",
        "Eintracht Frankfurt", "Freiburg", "Hamburg",
        "Heidenheim", "Hoffenheim", "Koln", "Mainz",
        "RB Leipzig", "St Pauli", "Stuttgart",
        "Union Berlin", "Werder Bremen", "Wolfsburg",
        "Bayer Leverkusen", "Leverkusen"
    ],

    "França": [
        "Auxerre", "Angers", "Brest", "Le Havre",
        "Lens", "Lille", "Lorient", "Lyon",
        "Marseille", "Monaco", "Nantes", "Nice",
        "Paris FC", "Paris Saint-Germain", "PSG",
        "Rennes", "Strasbourg", "Toulouse", "Metz"
    ],

    "Portugal": [
        "Arouca", "AVS", "Benfica", "Boavista",
        "Braga", "Casa Pia", "Estoril",
        "Estrela da Amadora", "Famalicao", "Farense",
        "Gil Vicente", "Moreirense", "Nacional",
        "Porto", "Rio Ave", "Santa Clara",
        "Sporting", "Sporting CP", "Tondela",
        "Vitoria Guimaraes"
    ]
}


# ============================================================
# 4. TERMOS DE TRANSFERÊNCIAS
# ============================================================

TERMOS_TRANSFERENCIA = [
    "transfer", "transferência", "transferencia",
    "transfer news", "transfer latest",
    "transfer target", "transfer interest",
    "transfer talks", "transfer bid",
    "transfer offer", "signing",
    "signs for", "signed for", "set to sign",
    "loan move", "loan deal", "loan signing",
    "on loan", "permanent move",
    "transfer fee", "release clause",
    "buyout clause", "contract talks",
    "contract extension", "new contract",
    "wants to sign", "interested in signing",
    "bid submitted", "offer submitted",
    "agreement reached", "deal agreed",
    "personal terms", "negotiations",
    "in talks over", "talks over a move",
    "close to signing", "close to agreeing",
    "medical scheduled", "medical booked"
]

TERMOS_NEGOCIACAO = [
    "negotiations", "in talks", "talks over",
    "talks with", "bid submitted",
    "offer submitted", "formal offer"
]

TERMOS_ACORDO = [
    "agreement reached", "deal agreed",
    "personal terms agreed", "medical scheduled",
    "medical booked", "close to signing",
    "close to completing"
]

TERMOS_INTERESSE = [
    "interested in", "interest in", "monitoring",
    "targeting", "wants to sign",
    "considering a move"
]


# ============================================================
# 5. EXCLUSÕES E CORREÇÕES DE PORTUGUÊS
# ============================================================

EXCLUSOES = [
    r"\bhorse racing\b",
    r"\bgreyhound racing\b",
    r"\bcricket\b",
    r"\brugby\b",
    r"\btennis\b",
    r"\bgolf\b",
    r"\bboxing\b",
    r"\bformula one\b",
    r"\bmotogp\b",
    r"\bsnooker\b"
]

CORRECOES_PTPT = [
    (r"\bzagueiro(s)?\b", r"defesa\1"),
    (r"\bdefensor(es)?\b", r"defesa\1"),
    (r"\bvolante(s)?\b", r"médio defensivo\1"),
    (r"\bmeia(s)?\b", r"médio\1"),
    (r"\bgramado\b", "relvado"),
    (r"\bgramados\b", "relvados"),
    (r"\btorcida\b", "adeptos"),
    (r"\btime(s)?\b", r"equipa\1"),
    (r"\bgoleiro(s)?\b", r"guarda-redes\1"),
    (r"\btreinador principal\b", "treinador"),
    (r"\bjanela de transferências\b", "mercado de transferências"),
    (r"\bemprestimo\b", "empréstimo")
]

CACHE_TRADUCAO = {}

EDITOR_FIELDS = {
    "editorStatus", "verification",
    "editorApproved", "editorRejected",
    "editorNotes", "manualStatus",
    "manualTitle", "manualSummary",
    "verifiedBy", "verifiedAt",
    "editorialDecision", "editorialNotes"
}


# ============================================================
# 6. FUNÇÕES GERAIS
# ============================================================

def agora():
    return datetime.now(timezone.utc)


def iso(dt=None):
    dt = dt or agora()

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).isoformat()


def limpar_texto(value):
    if value is None:
        return ""

    s = unescape(str(value))
    s = re.sub(r"<[^>]*>", " ", s)

    return re.sub(r"\s+", " ", s).strip()


def normalizar(value):
    s = unicodedata.normalize(
        "NFKD",
        limpar_texto(value).lower()
    )

    return "".join(
        c for c in s
        if not unicodedata.combining(c)
    )


def carregar_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"{path.name} tem JSON inválido; o ficheiro foi preservado."
        ) from e


def guardar_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp, path)


def normalizar_url(url):
    try:
        p = urlparse((url or "").strip())

        if p.scheme not in ("http", "https") or not p.netloc:
            return ""

        q = [
            (k, v)
            for k, v in parse_qsl(
                p.query,
                keep_blank_values=True
            )
            if not k.lower().startswith("utm_")
            and k.lower() not in {
                "fbclid", "gclid", "mc_cid", "mc_eid"
            }
        ]

        return urlunparse((
            p.scheme.lower(),
            p.netloc.lower(),
            p.path.rstrip("/"),
            "",
            urlencode(q, doseq=True),
            ""
        ))

    except Exception:
        return ""


def data_entry(entry):
    for key in ("published", "updated", "created"):
        raw = entry.get(key)

        if raw:
            try:
                dt = parsedate_to_datetime(raw)

                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)

                return dt.astimezone(timezone.utc)

            except Exception:
                pass

    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)

        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass

    return None


# ============================================================
# 7. TRADUÇÃO
# ============================================================

def traduzir(texto):
    texto = limpar_texto(texto)

    if not texto:
        return "", "empty"

    if texto in CACHE_TRADUCAO:
        return CACHE_TRADUCAO[texto], "translated"

    if GoogleTranslator is None:
        return texto, "unavailable"

    try:
        tradutor = GoogleTranslator(
            source="auto",
            target=IDIOMA_TRADUCAO
        )

        blocos = [
            texto[i:i + 4000]
            for i in range(0, len(texto), 4000)
        ]

        resultado = " ".join(
            (tradutor.translate(b) or b)
            for b in blocos
        ).strip()

        for pattern, replacement in CORRECOES_PTPT:
            resultado = re.sub(
                pattern,
                replacement,
                resultado,
                flags=re.IGNORECASE
            )

        CACHE_TRADUCAO[texto] = resultado or texto

        time.sleep(PAUSA_TRADUCAO)

        return (
            CACHE_TRADUCAO[texto],
            "translated" if resultado else "failed"
        )

    except Exception as e:
        logging.warning("Falha na tradução: %s", e)
        return texto, "failed"


def garantir_traducao(item):
    original_title = limpar_texto(
        item.get("originalTitle")
        or item.get("title")
        or ""
    )

    original_summary = limpar_texto(
        item.get("originalSummary")
        or item.get("summary")
        or ""
    )

    item["originalTitle"] = original_title
    item["originalSummary"] = original_summary

    if (
        not item.get("translatedTitle")
        or item.get("translationVersion") != VERSION
    ):
        translated_title, status_t = traduzir(original_title)
        translated_summary, status_s = traduzir(original_summary)

        item["translatedTitle"] = translated_title
        item["translatedSummary"] = translated_summary

        item["translationStatus"] = (
            "translated"
            if status_t == "translated"
            and status_s in ("translated", "empty")
            else (
                "failed"
                if any(
                    x in ("failed", "unavailable")
                    for x in (status_t, status_s)
                )
                else "original"
            )
        )

        if (
            status_t in ("translated", "empty")
            and status_s in ("translated", "empty")
        ):
            item["translationVersion"] = VERSION
        else:
            item["translationVersion"] = ""

    item["title"] = item.get("translatedTitle") or original_title
    item["summary"] = item.get("translatedSummary") or original_summary

    item["displayLanguage"] = (
        "pt-PT"
        if item.get("translationStatus") == "translated"
        else "original"
    )

    return item


# ============================================================
# 8. CLUBES E REGIÕES
# ============================================================

def clubes_no_texto(text):
    n = normalizar(text)
    found = []

    for clubs in CLUBES.values():
        for club in clubs:
            cn = normalizar(club)

            if re.search(
                r"(?<!\w)" + re.escape(cn) + r"(?!\w)",
                n
            ):
                if club not in found:
                    found.append(club)

    return found


def regioes_no_texto(text):
    n = normalizar(text)
    found = []

    detected_clubs = clubes_no_texto(text)

    for region, clubs in CLUBES.items():
        if any(c in detected_clubs for c in clubs):
            found.append(region)

    competitions = {
        "premier league": "Inglaterra",
        "la liga": "Espanha",
        "serie a": "Itália",
        "bundesliga": "Alemanha",
        "ligue 1": "França",
        "primeira liga": "Portugal"
    }

    for token, region in competitions.items():
        if re.search(
            r"(?<!\w)" + re.escape(token) + r"(?!\w)",
            n
        ) and region not in found:
            found.append(region)

    return found


# ============================================================
# 9. CLASSIFICAÇÃO
# ============================================================

def classificar(titulo, resumo):
    title_n = normalizar(titulo)
    summary_n = normalizar(resumo)
    whole = title_n + " " + summary_n

    if any(re.search(p, whole) for p in EXCLUSOES):
        return "Excluir", 0, ["Outra modalidade desportiva"]

    title_signals = [
        x for x in TERMOS_TRANSFERENCIA
        if normalizar(x) in title_n
    ]

    summary_signals = [
        x for x in TERMOS_TRANSFERENCIA
        if normalizar(x) in summary_n
    ]

    if not title_signals and not summary_signals:
        return "Excluir", 0, ["Sem sinal específico de transferência"]

    football_context = (
        bool(clubes_no_texto(whole))
        or any(
            x in whole
            for x in (
                "football", "soccer", "premier league",
                "la liga", "champions league",
                "europa league", "striker",
                "midfielder", "defender",
                "goalkeeper", "manager"
            )
        )
    )

    if not football_context:
        return "Excluir", 0, ["Contexto de futebol não confirmado"]

    score = 0
    reasons = []

    if title_signals:
        score += 35
        reasons.append("Sinal de transferência no título")
    else:
        score += 20
        reasons.append("Sinal de transferência no resumo")

    if any(normalizar(x) in whole for x in TERMOS_NEGOCIACAO):
        score += 25
        reasons.append("Referência a negociações")

    if any(normalizar(x) in whole for x in TERMOS_ACORDO):
        score += 25
        reasons.append("Possível acordo")

    if any(normalizar(x) in whole for x in TERMOS_INTERESSE):
        score += 10
        reasons.append("Interesse de clube")

    clubs = clubes_no_texto(whole)

    if len(clubs) >= 2:
        score += 10
        reasons.append("Dois ou mais clubes identificados")
    elif clubs:
        score += 5
        reasons.append("Clube identificado")

    has_agreement = any(
        normalizar(x) in whole for x in TERMOS_ACORDO
    )

    has_negotiation = any(
        normalizar(x) in whole for x in TERMOS_NEGOCIACAO
    )

    has_interest = any(
        normalizar(x) in whole for x in TERMOS_INTERESSE
    )

    if has_agreement and score >= 60:
        phase = "Acordo próximo"
    elif has_negotiation and score >= 50:
        phase = "Negociações"
    elif has_interest:
        phase = "Interesse"
    else:
        phase = "Rumor"

    return phase, score, reasons


# ============================================================
# 10. IDENTIFICAÇÃO DE JOGADORES
# ============================================================

def jogadores_detectados(text, base):
    arr = base.get("players", base) if isinstance(base, dict) else base

    if not isinstance(arr, list):
        return []

    n = normalizar(text)
    out = []

    for player in arr:
        if isinstance(player, str):
            name = player
        elif isinstance(player, dict):
            name = player.get("name") or player.get("player") or ""
        else:
            name = ""

        if name:
            nn = normalizar(name)

            if re.search(
                r"(?<!\w)" + re.escape(nn) + r"(?!\w)",
                n
            ):
                out.append(name)

    return list(dict.fromkeys(out))


# ============================================================
# 11. CRIAR CANDIDATOS
# ============================================================

def criar_candidato(entry, source, players):
    original_title = limpar_texto(entry.get("title", ""))

    original_summary = limpar_texto(
        entry.get("summary")
        or entry.get("description")
        or ""
    )

    url = normalizar_url(entry.get("link", ""))

    if not original_title or not url:
        return None

    host = urlparse(url).netloc.lower()

    if host.endswith(("x.com", "twitter.com")):
        return None

    phase, score, reasons = classificar(
        original_title,
        original_summary
    )

    if phase == "Excluir":
        return None

    published = data_entry(entry)

    if published and published < agora() - timedelta(days=MAX_DIAS):
        return None

    full = original_title + " " + original_summary

    clubs = clubes_no_texto(full)
    regions = regioes_no_texto(full)
    player_names = jogadores_detectados(full, players)

    uid = hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()[:20]

    item = {
        "id": uid,

        "title": original_title,
        "summary": original_summary,

        "originalTitle": original_title,
        "originalSummary": original_summary,

        "translatedTitle": "",
        "translatedSummary": "",

        "source": source,
        "domain": host,
        "url": url,

        "date": iso(published) if published else "",
        "firstSeen": iso(),
        "lastSeen": iso(),

        "status": phase,
        "suggestedStatus": phase,
        "phase": phase,

        "editorStatus": "Por verificar",
        "verification": "Por verificar",
        "verificationStatus": "Por verificar",

        "transferRelevance": score,
        "relevance": score,
        "classificationReasons": reasons,

        "player": player_names[0] if player_names else "",
        "detectedPlayers": player_names,

        "currentClub": "",
        "destination": "",

        "detectedClubs": clubs,
        "regions": regions,
        "league": regions[0] if regions else "Por identificar",

        "sourceLinks": [
            {"source": source, "url": url}
        ],

        "sourceCount": 1,

        "translationStatus": "pending",
        "translationVersion": "",
        "displayLanguage": "original",

        "engineVersion": VERSION
    }

    return garantir_traducao(item)


# ============================================================
# 12. DUPLICADOS E PRESERVAÇÃO EDITORIAL
# ============================================================

def similarity(a, b):
    ta = normalizar(
        a.get("originalTitle") or a.get("title") or ""
    )

    tb = normalizar(
        b.get("originalTitle") or b.get("title") or ""
    )

    return (
        SequenceMatcher(None, ta, tb).ratio()
        if ta and tb else 0.0
    )


def protected(item):
    if item.get("editorApproved") or item.get("editorRejected"):
        return True

    if any(
        item.get(k)
        for k in EDITOR_FIELDS - {"editorStatus", "verification"}
    ):
        return True

    status = normalizar(item.get("editorStatus", ""))

    return status not in ("", "por verificar")


def merge_sources(a, b):
    links = (
        a.get("sourceLinks")
        if isinstance(a.get("sourceLinks"), list)
        else []
    )

    links += (
        b.get("sourceLinks")
        if isinstance(b.get("sourceLinks"), list)
        else []
    )

    seen = set()
    merged = []

    for link in links:
        if not isinstance(link, dict):
            continue

        url = normalizar_url(link.get("url", ""))

        if not url or url in seen:
            continue

        seen.add(url)

        merged.append({
            "source": link.get("source", ""),
            "url": url
        })

    a["sourceLinks"] = merged

    a["sourceCount"] = len({
        x["source"]
        for x in merged
        if x.get("source")
    })


def merge_preserving_editorial(old, new):
    result = dict(old)

    for key, value in new.items():
        if key in EDITOR_FIELDS or key in {"id", "firstSeen"}:
            continue

        if value not in (None, "", [], {}):
            result[key] = value

    for key in EDITOR_FIELDS:
        if key in old:
            result[key] = old[key]

    result["id"] = old.get("id") or new.get("id")
    result["firstSeen"] = old.get("firstSeen") or new.get("firstSeen") or iso()
    result["lastSeen"] = iso()

    merge_sources(result, new)

    return result


def integrate(old_items, new_items, history_ids):
    items = []
    by_id = {}

    for old in old_items:
        if not isinstance(old, dict):
            continue

        uid = old.get("id") or hashlib.sha256(
            normalizar_url(old.get("url", "")).encode()
        ).hexdigest()[:20]

        old["id"] = uid

        if uid not in by_id:
            by_id[uid] = old
            items.append(old)

    for new in new_items:
        uid = new.get("id")

        if not uid:
            continue

        if uid in by_id:
            merged = merge_preserving_editorial(
                by_id[uid],
                new
            )

            by_id[uid].update(merged)
            continue

        duplicate = next(
            (
                x for x in items
                if normalizar_url(x.get("url", ""))
                == normalizar_url(new.get("url", ""))
            ),
            None
        )

        if duplicate is None:
            candidates = [
                (similarity(x, new), x)
                for x in items
            ]

            candidates = [
                (s, x)
                for s, x in candidates
                if s >= SIMILARIDADE_DUPLICADOS
            ]

            if candidates:
                duplicate = max(
                    candidates,
                    key=lambda pair: pair[0]
                )[1]

        if duplicate is not None:
            duplicate.update(
                merge_preserving_editorial(duplicate, new)
            )
            continue

        if uid in history_ids:
            continue

        items.append(new)
        by_id[uid] = new

    # Migrar e traduzir também as notícias antigas.
    for item in items:
        if not item.get("originalTitle"):
            item["originalTitle"] = limpar_texto(
                item.get("title", "")
            )

        if not item.get("originalSummary"):
            item["originalSummary"] = limpar_texto(
                item.get("summary", "")
            )

        item.setdefault(
            "verification",
            item.get("verificationStatus") or "Por verificar"
        )

        item.setdefault(
            "verificationStatus",
            item.get("verification") or "Por verificar"
        )

        item.setdefault("editorStatus", "Por verificar")

        phase, score, reasons = classificar(
            item.get("originalTitle", ""),
            item.get("originalSummary", "")
        )

        if phase != "Excluir":
            item["phase"] = phase
            item["suggestedStatus"] = phase
            item["status"] = phase

            item["transferRelevance"] = score
            item["relevance"] = score
            item["classificationReasons"] = reasons

            full = (
                item.get("originalTitle", "")
                + " "
                + item.get("originalSummary", "")
            )

            item["detectedClubs"] = clubes_no_texto(full)
            item["regions"] = regioes_no_texto(full)

            item["league"] = (
                item["regions"][0]
                if item["regions"]
                else "Por identificar"
            )

            garantir_traducao(item)

        else:
            if not protected(item):
                item["_removeByFilter"] = True

    items = [
        x for x in items
        if not x.pop("_removeByFilter", False)
    ]

    items.sort(
        key=lambda x: x.get("date") or x.get("firstSeen") or "",
        reverse=True
    )

    pinned = [x for x in items if protected(x)]
    ordinary = [x for x in items if not protected(x)]

    return sorted(
        pinned + ordinary[:max(0, MAX_CANDIDATOS - len(pinned))],
        key=lambda x: x.get("date") or x.get("firstSeen") or "",
        reverse=True
    )


# ============================================================
# 13. HISTÓRICO
# ============================================================

def load_history():
    history = carregar_json(
        HISTORICO,
        {"seenIds": []}
    )

    if not isinstance(history, dict):
        history = {"seenIds": []}

    if not isinstance(history.get("seenIds"), list):
        history["seenIds"] = []

    return history


# ============================================================
# 14. RECOLHA RSS
# ============================================================

def recolher_fonte(source, players):
    report = {
        "source": source["nome"],
        "url": source["url"],
        "success": False,
        "itemsFound": 0,
        "itemsAccepted": 0,
        "error": ""
    }

    try:
        feed = feedparser.parse(source["url"])
        entries = getattr(feed, "entries", [])

        report["itemsFound"] = len(entries)

        if (
            getattr(feed, "bozo", False)
            and getattr(feed, "bozo_exception", None)
        ):
            report["error"] = str(feed.bozo_exception)

        found = []

        for entry in entries:
            try:
                item = criar_candidato(
                    entry,
                    source["nome"],
                    players
                )

                if item:
                    found.append(item)

            except Exception as e:
                log.warning(
                    "Falha a processar entrada RSS (%s): %s",
                    source["nome"],
                    e
                )

        report["success"] = True
        report["itemsAccepted"] = len(found)

        return found, report

    except Exception as e:
        report["error"] = str(e)
        return [], report


# ============================================================
# 15. EXECUÇÃO PRINCIPAL
# ============================================================

def main():
    log.info("A iniciar TRANSFER MARKET V%s", VERSION)

    old = carregar_json(CANDIDATOS, [])

    if not isinstance(old, list):
        raise RuntimeError(
            "candidatos.json tem de conter uma lista JSON."
        )

    players = carregar_json(JOGADORES, [])
    history = load_history()
    history_ids = set(history.get("seenIds", []))

    new = []
    reports = []
    successes = 0

    for source in FONTES:
        found, report = recolher_fonte(source, players)

        new.extend(found)
        reports.append(report)

        successes += int(report["success"])

        log.info(
            "%s: %d notícias aceites",
            source["nome"],
            len(found)
        )

    if FONTES and successes == 0:
        guardar_json(
            RELATORIO,
            {
                "engineVersion": VERSION,
                "updatedAt": iso(),
                "sources": reports,
                "warning": (
                    "Todas as fontes falharam; "
                    "candidatos e histórico não foram alterados."
                )
            }
        )

        raise RuntimeError(
            "Todas as fontes RSS falharam. "
            "Os dados existentes foram preservados."
        )

    merged = integrate(
        old,
        new,
        history_ids
    )

    ids = list(dict.fromkeys(
        history.get("seenIds", [])
        + [
            x.get("id")
            for x in merged
            if x.get("id")
        ]
    ))

    history["seenIds"] = ids[-10000:]
    history["updatedAt"] = iso()

    guardar_json(CANDIDATOS, merged)
    guardar_json(HISTORICO, history)

    guardar_json(
        RELATORIO,
        {
            "engineVersion": VERSION,
            "updatedAt": iso(),
            "sources": reports,
            "acceptedTotal": len(new),
            "savedTotal": len(merged)
        }
    )

    # O ficheiro oficial é apenas validado; nunca é alterado pelo motor.
    if OFICIAIS.exists():
        official = carregar_json(OFICIAIS, [])

        if not isinstance(official, list):
            log.warning(
                "oficiais.json não é uma lista; não foi alterado."
            )

    log.info(
        "Concluído: %d notícias guardadas; %d novas recolhidas.",
        len(merged),
        len(new)
    )


if __name__ == "__main__":
    main()
