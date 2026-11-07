#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================
TRANSFER MARKET — INTELLIGENCE ENGINE V7.2
============================================================

FUNCIONALIDADES
- Recolha de notícias através de RSS.
- Filtragem de notícias sem relevância para transferências.
- Tradução de títulos e resumos.
- Preservação dos textos originais.
- Deteção de duplicados entre notícias antigas e novas.
- Preservação das decisões editoriais.
- Histórico de notícias já recolhidas.
- Identificação de clubes e das seis ligas selecionadas.
- Ordenação cronológica.
- Escrita segura dos ficheiros JSON.
- Compatibilidade com o radar.js V5.0.

IMPORTANTE
- Uma notícia nunca é considerada transferência oficial
  apenas por ser publicada por um jornal.
- As transferências oficiais são mantidas separadamente.
- O motor não inventa valores de transferências.
============================================================
"""

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

import feedparser

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None


# ============================================================
# 1. CONFIGURAÇÃO
# ============================================================

VERSION = "7.2"

FICHEIRO_CANDIDATOS = Path("candidatos.json")
FICHEIRO_RELATORIO = Path("relatorio_fontes.json")
FICHEIRO_HISTORICO = Path("historico_transferencias.json")
FICHEIRO_JOGADORES = Path("players.json")
FICHEIRO_OFICIAIS = Path("oficiais.json")

IDADE_MAXIMA_DIAS = 30
MAXIMO_CANDIDATOS = 500
MAXIMO_HISTORICO = 10000

LIMIAR_DUPLICADOS = 0.92
PAUSA_TRADUCAO = 0.3

IDIOMA_DESTINO = "pt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

LOGGER = logging.getLogger("TRANSFER_MARKET")


# ============================================================
# 2. FONTES RSS
# ============================================================

FONTES_RSS = [
    {
        "nome": "BBC Sport",
        "url": "https://feeds.bbci.co.uk/sport/football/rss.xml"
    },
    {
        "nome": "Sky Sports",
        "url": "https://www.skysports.com/rss/12040"
    }
]

# Fonte adicional opcional, configurada por variável de ambiente.
FABRIZIO_RSS_URL = os.getenv("FABRIZIO_RSS_URL", "").strip()

if FABRIZIO_RSS_URL:
    FONTES_RSS.append({
        "nome": "Fonte adicional",
        "url": FABRIZIO_RSS_URL
    })


# ============================================================
# 3. CLUBES E COMPETIÇÕES
# ============================================================

CLUBES = {
    "Premier League": [
        "Arsenal", "Aston Villa", "Bournemouth", "Brentford",
        "Brighton", "Burnley", "Chelsea", "Crystal Palace",
        "Everton", "Fulham", "Leeds United", "Liverpool",
        "Manchester City", "Manchester United", "Newcastle United",
        "Nottingham Forest", "Sunderland", "Tottenham",
        "West Ham", "Wolverhampton", "Wolves"
    ],

    "La Liga": [
        "Alaves", "Athletic Bilbao", "Atletico Madrid",
        "Barcelona", "Celta Vigo", "Elche", "Espanyol",
        "Getafe", "Girona", "Levante", "Mallorca",
        "Osasuna", "Real Madrid", "Real Betis",
        "Real Sociedad", "Sevilla", "Valencia",
        "Villarreal", "Rayo Vallecano", "Oviedo"
    ],

    "Serie A": [
        "Atalanta", "Bologna", "Cagliari", "Como",
        "Cremonese", "Fiorentina", "Genoa", "Inter",
        "Juventus", "Lazio", "Lecce", "AC Milan",
        "Milan", "Napoli", "Parma", "Pisa",
        "Roma", "Sassuolo", "Torino", "Udinese"
    ],

    "Bundesliga": [
        "Augsburg", "Bayern Munich", "Bayern",
        "Borussia Dortmund", "Dortmund", "Eintracht Frankfurt",
        "Freiburg", "Hamburg", "Heidenheim", "Hoffenheim",
        "Koln", "Mainz", "RB Leipzig", "St Pauli",
        "Stuttgart", "Union Berlin", "Werder Bremen",
        "Wolfsburg", "Bayer Leverkusen", "Leverkusen"
    ],

    "Ligue 1": [
        "Auxerre", "Angers", "Brest", "Le Havre",
        "Lens", "Lille", "Lorient", "Lyon",
        "Marseille", "Monaco", "Nantes", "Nice",
        "Paris FC", "Paris Saint-Germain", "PSG",
        "Rennes", "Strasbourg", "Toulouse", "Metz"
    ],

    "Primeira Liga": [
        "Arouca", "AVS", "Benfica", "Boavista",
        "Braga", "Casa Pia", "Estoril", "Estrela da Amadora",
        "Famalicao", "Farense", "Gil Vicente", "Moreirense",
        "Nacional", "Porto", "Rio Ave", "Santa Clara",
        "Sporting", "Sporting CP", "Tondela", "Vitoria Guimaraes"
    ]
}


# ============================================================
# 4. PALAVRAS-CHAVE DE TRANSFERÊNCIAS
# ============================================================

SINAIS_TRANSFERENCIA = [
    "transfer", "transferência", "transferencia",
    "signing", "sign", "signs", "signed",
    "deal", "move", "switch",
    "loan", "loan move", "emprestimo", "empréstimo",
    "bid", "offer", "proposal",
    "interest", "interested", "target",
    "negotiations", "talks",
    "agreement", "agreed",
    "release clause", "buyout clause",
    "transfer window", "transfer market",
    "contract extension", "new contract",
    "contract talks", "contract negotiations"
]

SINAIS_NEGOCIACOES = [
    "negotiations", "in talks", "talks with",
    "talks over", "discussions",
    "negotiating", "negotiation",
    "formal offer", "official bid",
    "bid submitted", "offer submitted"
]

SINAIS_ACORDO = [
    "agreement reached", "deal agreed",
    "personal terms agreed", "medical scheduled",
    "medical booked", "set to sign",
    "close to signing", "close to completing",
    "deal close", "agreement close"
]

SINAIS_INTERESSE = [
    "interested in", "interest in",
    "monitoring", "scouting",
    "considering a move", "considering signing",
    "wants to sign", "want to sign",
    "targeting", "target"
]


# ============================================================
# 5. FILTROS DE CONTEÚDO
# ============================================================

PADROES_EXCLUSAO = [
    r"\bhorse racing\b",
    r"\bcricket\b",
    r"\brugby\b",
    r"\btennis\b",
    r"\bgolf\b",
    r"\bboxing\b",
    r"\bformula one\b",
    r"\bf1\b",
    r"\bmotogp\b",
    r"\bgreyhound racing\b",
    r"\bhorseracing\b",
    r"\bworld snooker\b"
]

PADROES_FUTEBOL = [
    r"\bfootball\b",
    r"\bsoccer\b",
    r"\bpremier league\b",
    r"\bla liga\b",
    r"\bserie a\b",
    r"\bbundesliga\b",
    r"\bligue 1\b",
    r"\bprimeira liga\b",
    r"\bchampions league\b",
    r"\beuropa league\b",
    r"\bfa cup\b",
    r"\bclub\b",
    r"\bmanager\b",
    r"\bstriker\b",
    r"\bmidfielder\b",
    r"\bdefender\b",
    r"\bgoalkeeper\b"
]


# ============================================================
# 6. FUNÇÕES GERAIS
# ============================================================

def agora():
    return datetime.now(timezone.utc)


def data_iso(valor=None):
    if valor is None:
        valor = agora()

    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=timezone.utc)

        return valor.astimezone(timezone.utc).isoformat()

    return str(valor)


def limpar_texto(valor):
    if not valor:
        return ""

    texto = unescape(str(valor))
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def normalizar_texto(valor):
    texto = limpar_texto(valor).lower()

    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        c for c in texto
        if not unicodedata.combining(c)
    )

    return texto


def gerar_id(valor):
    base = normalizar_texto(valor)

    return hashlib.sha256(
        base.encode("utf-8")
    ).hexdigest()[:20]


def normalizar_url(url):
    if not url:
        return ""

    try:
        partes = urlparse(str(url).strip())

        if partes.scheme not in ("http", "https"):
            return ""

        if not partes.netloc:
            return ""

        parametros = []

        for chave, valor in parse_qsl(
            partes.query,
            keep_blank_values=True
        ):
            chave_lower = chave.lower()

            if chave_lower.startswith("utm_"):
                continue

            if chave_lower in {
                "fbclid",
                "gclid",
                "mc_cid",
                "mc_eid",
                "ref",
                "source"
            }:
                continue

            parametros.append((chave, valor))

        query = urlencode(parametros, doseq=True)

        caminho = partes.path.rstrip("/")

        return urlunparse((
            partes.scheme.lower(),
            partes.netloc.lower(),
            caminho,
            "",
            query,
            ""
        ))

    except Exception:
        return str(url).strip()


def data_publicacao(entry):
    possibilidades = [
        entry.get("published"),
        entry.get("updated"),
        entry.get("created")
    ]

    for valor in possibilidades:
        if not valor:
            continue

        try:
            data = parsedate_to_datetime(valor)

            if data.tzinfo is None:
                data = data.replace(tzinfo=timezone.utc)

            return data.astimezone(timezone.utc)

        except Exception:
            continue

    for campo in ("published_parsed", "updated_parsed"):
        valor = entry.get(campo)

        if valor:
            try:
                return datetime(
                    *valor[:6],
                    tzinfo=timezone.utc
                )
            except Exception:
                pass

    return None


def carregar_json(caminho, valor_por_defeito):
    """
    Não substitui ficheiros JSON danificados por ficheiros vazios.
    Se um ficheiro existente estiver inválido, interrompe o processo.
    """

    if not caminho.exists():
        return valor_por_defeito

    try:
        with caminho.open("r", encoding="utf-8") as ficheiro:
            return json.load(ficheiro)

    except json.JSONDecodeError as erro:
        raise RuntimeError(
            f"O ficheiro {caminho} contém JSON inválido. "
            "Foi preservado para evitar perda de dados."
        ) from erro

    except OSError as erro:
        raise RuntimeError(
            f"Não foi possível ler {caminho}: {erro}"
        ) from erro


def guardar_json(caminho, dados):
    temporario = caminho.with_suffix(
        caminho.suffix + ".tmp"
    )

    caminho.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with temporario.open("w", encoding="utf-8") as ficheiro:
        json.dump(
            dados,
            ficheiro,
            ensure_ascii=False,
            indent=2
        )

        ficheiro.flush()
        os.fsync(ficheiro.fileno())

    os.replace(temporario, caminho)


# ============================================================
# 7. TRADUÇÃO
# ============================================================

CACHE_TRADUCAO = {}


def traduzir_texto(texto):
    texto = limpar_texto(texto)

    if not texto:
        return ""

    if texto in CACHE_TRADUCAO:
        return CACHE_TRADUCAO[texto]

    if GoogleTranslator is None:
        LOGGER.warning(
            "deep-translator não está instalado. "
            "O texto original será mantido."
        )
        return texto

    try:
        tradutor = GoogleTranslator(
            source="auto",
            target=IDIOMA_DESTINO
        )

        partes = []

        for inicio in range(0, len(texto), 4000):
            parte = texto[inicio:inicio + 4000]

            partes.append(
                tradutor.translate(parte) or parte
            )

            time.sleep(PAUSA_TRADUCAO)

        resultado = " ".join(partes).strip()

        if not resultado:
            resultado = texto

        CACHE_TRADUCAO[texto] = resultado

        return resultado

    except Exception as erro:
        LOGGER.warning("Falha na tradução: %s", erro)
        return texto


def traduzir_candidato(candidato):
    """
    A tradução só é feita quando ainda não existe.
    Os textos originais nunca são substituídos.
    """

    titulo_original = (
        candidato.get("originalTitle")
        or candidato.get("title")
        or ""
    )

    resumo_original = (
        candidato.get("originalSummary")
        or candidato.get("summary")
        or ""
    )

    candidato["originalTitle"] = titulo_original
    candidato["originalSummary"] = resumo_original

    precisa_traduzir = (
        not candidato.get("translatedTitle")
        or not candidato.get("translatedSummary")
        or candidato.get("translationVersion") != VERSION
    )

    if precisa_traduzir:
        titulo = traduzir_texto(titulo_original)
        resumo = traduzir_texto(resumo_original)

        candidato["translatedTitle"] = titulo
        candidato["translatedSummary"] = resumo

        candidato["title"] = titulo
        candidato["summary"] = resumo

        candidato["translationVersion"] = VERSION

        if titulo == titulo_original and resumo == resumo_original:
            candidato["translationStatus"] = "original"
        else:
            candidato["translationStatus"] = "translated"

    else:
        candidato["title"] = candidato["translatedTitle"]
        candidato["summary"] = candidato["translatedSummary"]

    candidato["displayLanguage"] = "pt"

    return candidato


# ============================================================
# 8. IDENTIFICAÇÃO DE CLUBES E LIGAS
# ============================================================

def identificar_clubes(texto):
    texto_normalizado = normalizar_texto(texto)

    encontrados = []

    for liga, clubes in CLUBES.items():
        for clube in clubes:
            nome = normalizar_texto(clube)

            if not nome:
                continue

            padrao = r"(?<!\w)" + re.escape(nome) + r"(?!\w)"

            if re.search(padrao, texto_normalizado):
                if clube not in encontrados:
                    encontrados.append(clube)

    return encontrados


def identificar_ligas(texto):
    clubes_encontrados = identificar_clubes(texto)

    ligas = []

    texto_normalizado = normalizar_texto(texto)

    for liga, clubes in CLUBES.items():
        for clube in clubes:
            if clube in clubes_encontrados:
                if liga not in ligas:
                    ligas.append(liga)

    # Reconhece nomes das competições quando aparecem diretamente.
    nomes_competicoes = {
        "premier league": "Premier League",
        "la liga": "La Liga",
        "serie a": "Serie A",
        "bundesliga": "Bundesliga",
        "ligue 1": "Ligue 1",
        "primeira liga": "Primeira Liga"
    }

    for nome, liga in nomes_competicoes.items():
        if re.search(
            r"(?<!\w)" + re.escape(nome) + r"(?!\w)",
            texto_normalizado
        ):
            if liga not in ligas:
                ligas.append(liga)

    return ligas


def obter_liga_principal(ligas):
    if not ligas:
        return "Europa"

    return ligas[0]


# ============================================================
# 9. FILTROS DE RELEVÂNCIA
# ============================================================

def contem_padrao(texto, padroes):
    return any(
        re.search(padrao, texto, re.IGNORECASE)
        for padrao in padroes
    )


def noticia_excluida(titulo, resumo):
    texto = normalizar_texto(titulo + " " + resumo)

    return contem_padrao(
        texto,
        PADROES_EXCLUSAO
    )


def noticia_de_futebol(titulo, resumo):
    texto = normalizar_texto(titulo + " " + resumo)

    if contem_padrao(texto, PADROES_FUTEBOL):
        return True

    if identificar_clubes(texto):
        return True

    return False


def tem_sinal_transferencia(texto):
    texto = normalizar_texto(texto)

    return any(
        normalizar_texto(sinal) in texto
        for sinal in SINAIS_TRANSFERENCIA
    )


def classificar(titulo, resumo):
    """
    Devolve:
    estado, pontuação, motivos

    Esta classificação é uma sugestão automática.
    Nunca confirma uma transferência.
    """

    titulo_normalizado = normalizar_texto(titulo)
    resumo_normalizado = normalizar_texto(resumo)

    texto = titulo_normalizado + " " + resumo_normalizado

    motivos = []
    pontuacao = 0

    if noticia_excluida(titulo, resumo):
        return "Excluir", 0, ["Conteúdo de outra modalidade"]

    if not noticia_de_futebol(titulo, resumo):
        return "Excluir", 0, ["Não foi identificado conteúdo de futebol"]

    sinais_titulo = [
        sinal for sinal in SINAIS_TRANSFERENCIA
        if normalizar_texto(sinal) in titulo_normalizado
    ]

    sinais_resumo = [
        sinal for sinal in SINAIS_TRANSFERENCIA
        if normalizar_texto(sinal) in resumo_normalizado
    ]

    if sinais_titulo:
        pontuacao += 30
        motivos.append("Sinal de transferência no título")

    elif sinais_resumo:
        pontuacao += 15
        motivos.append("Sinal de transferência no resumo")

    if any(
        normalizar_texto(sinal) in texto
        for sinal in SINAIS_NEGOCIACOES
    ):
        pontuacao += 25
        motivos.append("Referência a negociações")

    if any(
        normalizar_texto(sinal) in texto
        for sinal in SINAIS_ACORDO
    ):
        pontuacao += 30
        motivos.append("Referência a possível acordo")

    if any(
        normalizar_texto(sinal) in texto
        for sinal in SINAIS_INTERESSE
    ):
        pontuacao += 15
        motivos.append("Referência a interesse de um clube")

    clubes = identificar_clubes(texto)

    if len(clubes) >= 2:
        pontuacao += 10
        motivos.append("Dois ou mais clubes identificados")

    elif len(clubes) == 1:
        pontuacao += 5
        motivos.append("Clube identificado")

    # Exige um sinal real de transferência.
    if not sinais_titulo and not sinais_resumo:
        return "Excluir", 0, ["Sem indicação suficientemente clara de transferência"]

    if pontuacao >= 65 and any(
        normalizar_texto(sinal) in texto
        for sinal in SINAIS_ACORDO
    ):
        estado = "Acordo próximo"

    elif pontuacao >= 55 and any(
        normalizar_texto(sinal) in texto
        for sinal in SINAIS_NEGOCIACOES
    ):
        estado = "Negociações"

    elif pontuacao >= 25:
        estado = "Rumor"

    else:
        estado = "Por verificar"

    return estado, pontuacao, motivos


# ============================================================
# 10. JOGADORES
# ============================================================

def carregar_jogadores():
    dados = carregar_json(
        FICHEIRO_JOGADORES,
        []
    )

    if isinstance(dados, dict):
        return dados

    return {
        "players": dados
    }


def identificar_jogadores(texto, base_jogadores):
    encontrados = []

    jogadores = base_jogadores.get("players", [])

    if not isinstance(jogadores, list):
        return encontrados

    texto_normalizado = normalizar_texto(texto)

    for jogador in jogadores:
        if isinstance(jogador, str):
            nome = jogador

        elif isinstance(jogador, dict):
            nome = (
                jogador.get("name")
                or jogador.get("player")
                or ""
            )

        else:
            continue

        if not nome:
            continue

        nome_normalizado = normalizar_texto(nome)

        padrao = (
            r"(?<!\w)"
            + re.escape(nome_normalizado)
            + r"(?!\w)"
        )

        if re.search(padrao, texto_normalizado):
            encontrados.append(nome)

    return list(dict.fromkeys(encontrados))


# ============================================================
# 11. CRIAÇÃO DE CANDIDATOS
# ============================================================

def criar_candidato(entry, fonte, base_jogadores):
    titulo_original = limpar_texto(
        entry.get("title", "")
    )

    resumo_original = limpar_texto(
        entry.get("summary", "")
        or entry.get("description", "")
    )

    url = normalizar_url(
        entry.get("link", "")
    )

    if not titulo_original or not url:
        return None

    if "twitter.com" in url or "x.com" in url:
        return None

    estado, pontuacao, motivos = classificar(
        titulo_original,
        resumo_original
    )

    if estado == "Excluir":
        return None

    data = data_publicacao(entry)

    if data:
        limite = agora() - timedelta(
            days=IDADE_MAXIMA_DIAS
        )

        if data < limite:
            return None

    texto_completo = (
        titulo_original + " " + resumo_original
    )

    clubes = identificar_clubes(texto_completo)
    ligas = identificar_ligas(texto_completo)

    jogadores = identificar_jogadores(
        texto_completo,
        base_jogadores
    )

    identificador = gerar_id(url)

    candidato = {
        "id": identificador,

        "title": titulo_original,
        "summary": resumo_original,

        "originalTitle": titulo_original,
        "originalSummary": resumo_original,

        "translatedTitle": "",
        "translatedSummary": "",

        "source": fonte,
        "domain": urlparse(url).netloc.lower(),
        "url": url,

        "date": data_iso(data) if data else "",
        "firstSeen": data_iso(),
        "lastSeen": data_iso(),

        "status": estado,
        "suggestedStatus": estado,
        "editorStatus": "Por verificar",

        "verification": "Por verificar",

        "transferRelevance": pontuacao,
        "relevance": pontuacao,
        "classificationReasons": motivos,

        "player": jogadores[0] if jogadores else "",
        "detectedPlayers": jogadores,

        "currentClub": "",
        "destination": "",

        "detectedClubs": clubes,
        "leagues": ligas,
        "league": obter_liga_principal(ligas),

        "sourceLinks": [
            {
                "source": fonte,
                "url": url
            }
        ],

        "sourceCount": 1,

        "displayLanguage": "pt",
        "translationStatus": "pending",
        "translationVersion": "",

        "engineVersion": VERSION
    }

    return traduzir_candidato(candidato)


# ============================================================
# 12. DUPLICADOS
# ============================================================

def similaridade_titulos(a, b):
    titulo_a = normalizar_texto(
        a.get("originalTitle")
        or a.get("title")
        or ""
    )

    titulo_b = normalizar_texto(
        b.get("originalTitle")
        or b.get("title")
        or ""
    )

    if not titulo_a or not titulo_b:
        return 0

    return SequenceMatcher(
        None,
        titulo_a,
        titulo_b
    ).ratio()


def mesmo_url(a, b):
    return (
        normalizar_url(a.get("url", ""))
        == normalizar_url(b.get("url", ""))
    )


def encontrar_duplicado(novo, existentes):
    for antigo in existentes:
        if mesmo_url(novo, antigo):
            return antigo

    melhor = None
    melhor_valor = 0

    for antigo in existentes:
        valor = similaridade_titulos(
            novo,
            antigo
        )

        if valor > melhor_valor:
            melhor_valor = valor
            melhor = antigo

    if melhor and melhor_valor >= LIMIAR_DUPLICADOS:
        return melhor

    return None


def fundir_fontes(principal, secundario):
    links = principal.get("sourceLinks", [])

    if not isinstance(links, list):
        links = []

    outros_links = secundario.get("sourceLinks", [])

    if not isinstance(outros_links, list):
        outros_links = []

    vistos = set()

    resultado = []

    for item in links + outros_links:
        if not isinstance(item, dict):
            continue

        url = normalizar_url(item.get("url", ""))

        if not url or url in vistos:
            continue

        vistos.add(url)

        resultado.append({
            "source": item.get("source", ""),
            "url": url
        })

    principal["sourceLinks"] = resultado

    fontes = {
        item.get("source")
        for item in resultado
        if item.get("source")
    }

    principal["sourceCount"] = len(fontes)

    return principal


# ============================================================
# 13. PRESERVAÇÃO EDITORIAL
# ============================================================

CAMPOS_EDITORIAIS = [
    "editorStatus",
    "verification",
    "editorApproved",
    "editorRejected",
    "editorNotes",
    "manualStatus",
    "manualTitle",
    "manualSummary",
    "verifiedBy",
    "verifiedAt"
]


def preservar_decisoes(antigo, novo):
    """
    Mantém o registo antigo como principal.
    Não substitui o ID nem as decisões editoriais.
    """

    resultado = dict(antigo)

    for chave, valor in novo.items():
        if chave in CAMPOS_EDITORIAIS:
            continue

        if chave in {
            "id",
            "firstSeen",
            "editorStatus",
            "verification"
        }:
            continue

        if valor not in ("", None, [], {}):
            resultado[chave] = valor

    for campo in CAMPOS_EDITORIAIS:
        if campo in antigo:
            resultado[campo] = antigo[campo]

    resultado["id"] = antigo.get(
        "id",
        novo.get("id")
    )

    resultado["firstSeen"] = antigo.get(
        "firstSeen",
        novo.get("firstSeen", data_iso())
    )

    resultado["lastSeen"] = data_iso()

    return resultado


def registo_protegido(candidato):
    if candidato.get("editorApproved"):
        return True

    if candidato.get("editorRejected"):
        return True

    for campo in (
        "editorNotes",
        "manualStatus",
        "manualTitle",
        "manualSummary",
        "verifiedBy",
        "verifiedAt"
    ):
        if candidato.get(campo):
            return True

    estado = normalizar_texto(
        candidato.get("editorStatus", "")
    )

    return estado not in ("", "por verificar")


# ============================================================
# 14. HISTÓRICO
# ============================================================

def carregar_historico():
    dados = carregar_json(
        FICHEIRO_HISTORICO,
        {"seenIds": []}
    )

    if not isinstance(dados, dict):
        dados = {"seenIds": []}

    ids = dados.get("seenIds", [])

    if not isinstance(ids, list):
        ids = []

    dados["seenIds"] = ids

    return dados


def atualizar_historico(historico, candidatos):
    ids = historico.get("seenIds", [])

    if not isinstance(ids, list):
        ids = []

    conjunto = set(ids)

    for candidato in candidatos:
        identificador = candidato.get("id")

        if identificador:
            conjunto.add(identificador)

    # Mantém os IDs mais recentes na ordem de entrada.
    resultado = list(conjunto)

    if len(resultado) > MAXIMO_HISTORICO:
        resultado = resultado[-MAXIMO_HISTORICO:]

    historico["seenIds"] = resultado
    historico["updatedAt"] = data_iso()

    return historico


# ============================================================
# 15. RECOLHA RSS
# ============================================================

def recolher_fonte(fonte, base_jogadores):
    nome = fonte["nome"]
    url = fonte["url"]

    LOGGER.info("A consultar %s", nome)

    resultado = {
        "source": nome,
        "url": url,
        "success": False,
        "itemsFound": 0,
        "itemsAccepted": 0,
        "error": ""
    }

    try:
        feed = feedparser.parse(url)

        if getattr(feed, "bozo", False):
            erro = getattr(feed, "bozo_exception", None)

            if erro:
                resultado["error"] = str(erro)

        entradas = getattr(feed, "entries", [])

        resultado["itemsFound"] = len(entradas)

        candidatos = []

        for entry in entradas:
            try:
                candidato = criar_candidato(
                    entry,
                    nome,
                    base_jogadores
                )

                if candidato:
                    candidatos.append(candidato)

            except Exception as erro:
                LOGGER.warning(
                    "Erro numa notícia de %s: %s",
                    nome,
                    erro
                )

        resultado["success"] = True
        resultado["itemsAccepted"] = len(candidatos)

        return candidatos, resultado

    except Exception as erro:
        resultado["error"] = str(erro)

        LOGGER.error(
            "Falha na fonte %s: %s",
            nome,
            erro
        )

        return [], resultado


# ============================================================
# 16. INTEGRAÇÃO DE NOTÍCIAS
# ============================================================

def integrar_candidatos(antigos, novos, historico):
    if not isinstance(antigos, list):
        antigos = []

    if not isinstance(novos, list):
        novos = []

    resultado = []

    por_id = {}

    for antigo in antigos:
        if not isinstance(antigo, dict):
            continue

        identificador = antigo.get("id")

        if not identificador:
            identificador = gerar_id(
                antigo.get("url")
                or antigo.get("title")
                or str(len(resultado))
            )

            antigo["id"] = identificador

        if identificador in por_id:
            continue

        por_id[identificador] = antigo
        resultado.append(antigo)

    ids_historico = set(
        historico.get("seenIds", [])
    )

    for novo in novos:
        identificador = novo.get("id")

        if not identificador:
            continue

        # Se o ID já existe, atualiza o registo existente.
        if identificador in por_id:
            antigo = por_id[identificador]

            atualizado = preservar_decisoes(
                antigo,
                novo
            )

            fundir_fontes(
                atualizado,
                novo
            )

            por_id[identificador].update(atualizado)

            continue

        # Não volta a criar uma notícia antiga removida
        # se já estiver registada no histórico.
        if identificador in ids_historico:
            continue

        duplicado = encontrar_duplicado(
            novo,
            resultado
        )

        if duplicado:
            atualizado = preservar_decisoes(
                duplicado,
                novo
            )

            fundir_fontes(
                atualizado,
                novo
            )

            duplicado.update(atualizado)

            continue

        resultado.append(novo)
        por_id[identificador] = novo

    resultado.sort(
        key=lambda item: item.get("date", ""),
        reverse=True
    )

    protegidos = [
        item for item in resultado
        if registo_protegido(item)
    ]

    normais = [
        item for item in resultado
        if not registo_protegido(item)
    ]

    espaco = max(
        0,
        MAXIMO_CANDIDATOS - len(protegidos)
    )

    resultado_final = protegidos + normais[:espaco]

    resultado_final.sort(
        key=lambda item: item.get("date", ""),
        reverse=True
    )

    return resultado_final


# ============================================================
# 17. RELATÓRIO DE FONTES
# ============================================================

def guardar_relatorio(relatorios):
    dados = {
        "engineVersion": VERSION,
        "updatedAt": data_iso(),
        "sources": relatorios
    }

    guardar_json(
        FICHEIRO_RELATORIO,
        dados
    )


# ============================================================
# 18. TRANSFERÊNCIAS OFICIAIS
# ============================================================

def carregar_oficiais():
    """
    Apenas carrega e preserva transferências oficiais
    já registadas e verificadas.

    Este motor NÃO confirma transferências automaticamente.
    """

    dados = carregar_json(
        FICHEIRO_OFICIAIS,
        []
    )

    if not isinstance(dados, list):
        LOGGER.warning(
            "oficiais.json não contém uma lista. "
            "O ficheiro não será substituído."
        )

        return []

    return dados


# ============================================================
# 19. EXECUÇÃO PRINCIPAL
# ============================================================

def executar():
    inicio = time.time()

    LOGGER.info(
        "A iniciar TRANSFER MARKET ENGINE V%s",
        VERSION
    )

    antigos = carregar_json(
        FICHEIRO_CANDIDATOS,
        []
    )

    if not isinstance(antigos, list):
        raise RuntimeError(
            "candidatos.json não contém uma lista."
        )

    historico = carregar_historico()
    base_jogadores = carregar_jogadores()

    todos_novos = []
    relatorios = []

    fontes_com_sucesso = 0

    for fonte in FONTES_RSS:
        candidatos, relatorio = recolher_fonte(
            fonte,
            base_jogadores
        )

        todos_novos.extend(candidatos)
        relatorios.append(relatorio)

        if relatorio["success"]:
            fontes_com_sucesso += 1

    # Se todas as fontes falharem, não altera candidatos
    # nem histórico. Evita substituir dados por listas vazias.
    if FONTES_RSS and fontes_com_sucesso == 0:
        LOGGER.error(
            "Todas as fontes RSS falharam. "
            "Os ficheiros de notícias foram preservados."
        )

        guardar_relatorio(relatorios)
        return

    integrados = integrar_candidatos(
        antigos,
        todos_novos,
        historico
    )

    historico = atualizar_historico(
        historico,
        integrados
    )

    # Só grava os ficheiros depois de a integração terminar.
    guardar_json(
        FICHEIRO_CANDIDATOS,
        integrados
    )

    guardar_json(
        FICHEIRO_HISTORICO,
        historico
    )

    guardar_relatorio(relatorios)

    oficiais = carregar_oficiais()

    duracao = round(
        time.time() - inicio,
        2
    )

    LOGGER.info("--------------------------------------------")
    LOGGER.info("EXECUÇÃO CONCLUÍDA")
    LOGGER.info("Versão: %s", VERSION)
    LOGGER.info("Notícias antigas: %s", len(antigos))
    LOGGER.info("Notícias recolhidas: %s", len(todos_novos))
    LOGGER.info("Notícias guardadas: %s", len(integrados))
    LOGGER.info("Transferências oficiais preservadas: %s", len(oficiais))
    LOGGER.info("Fontes com sucesso: %s", fontes_com_sucesso)
    LOGGER.info("Duração: %s segundos", duracao)
    LOGGER.info("--------------------------------------------")


# ============================================================
# 20. ARRANQUE
# ============================================================

if __name__ == "__main__":
    try:
        executar()

    except KeyboardInterrupt:
        LOGGER.warning("Execução interrompida pelo utilizador.")

    except Exception:
        LOGGER.exception(
            "O motor encontrou um erro. "
            "Verifica a mensagem acima antes de voltar a executar."
        )
        raise
