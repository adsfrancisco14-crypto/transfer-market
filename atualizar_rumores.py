#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================
TRANSFER MARKET — INTELLIGENCE ENGINE V4.0
============================================================
- Pesquisa notícias de transferências.
- Traduz títulos e resumos para português.
- Guarda os textos originais em inglês.
- Identifica rumores e negociações.
- Deteta notícias repetidas.
- Identifica jogadores através de players.json.
- Guarda candidatos em candidatos.json.
- Cria relatório de fontes.
- Não altera rumores.json.
============================================================
"""

# ============================================================
# INSTALAÇÃO AUTOMÁTICA
# ============================================================

import importlib.util
import subprocess
import sys

def instalar(modulo, pacote):
    if importlib.util.find_spec(modulo) is None:
        print("A instalar:", pacote)
        subprocess.check_call([
            sys.executable, "-m", "pip",
            "install", "--disable-pip-version-check", pacote
        ])

instalar("feedparser", "feedparser")
instalar("deep_translator", "deep-translator")

# ============================================================
# IMPORTAÇÕES
# ============================================================

import os
import re
import json
import hashlib
import logging
import unicodedata
import time

from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlunparse
from html import unescape

import feedparser
from deep_translator import GoogleTranslator

# ============================================================
# CONFIGURAÇÕES
# ============================================================

VERSAO = "4.0"

PASTA = Path(__file__).resolve().parent

FICHEIRO_SAIDA = PASTA / "candidatos.json"
FICHEIRO_RELATORIO = PASTA / "relatorio_fontes.json"
FICHEIRO_HISTORICO = PASTA / "historico_transferencias.json"
FICHEIRO_JOGADORES = PASTA / "players.json"

IDADE_MAXIMA = 30
MAXIMO_CANDIDATOS = 300
SIMILARIDADE = 0.78

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("TRANSFER MARKET")

# ============================================================
# FONTES RSS
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

# Fonte adicional opcional
if os.getenv("FABRIZIO_RSS_URL"):
    FONTES.append({
        "nome": "Fonte adicional",
        "url": os.getenv("FABRIZIO_RSS_URL")
    })

# ============================================================
# PALAVRAS-CHAVE
# ============================================================

PALAVRAS_MERCADO = [
    "transfer", "transfers", "transfer news",
    "transfer rumour", "transfer rumor",
    "signing", "signed", "signs for",
    "deal", "agreement", "loan",
    "bid", "offer", "interest",
    "target", "talks", "negotiations",
    "contract", "release clause",
    "medical", "here we go",
    "mercato", "fichajes",
    "transferência", "contratação",
    "empréstimo", "negociações",
    "proposta"
]

PALAVRAS_CONFIRMADAS = [
    "official", "confirmed",
    "completes move", "has joined",
    "joins", "signed for",
    "announces", "officially"
]

PALAVRAS_AVANCADAS = [
    "agreement reached",
    "deal agreed",
    "verbal agreement",
    "personal terms agreed",
    "medical booked",
    "final stages",
    "advanced talks"
]

PALAVRAS_NEGOCIACOES = [
    "negotiations",
    "talks",
    "bid",
    "offer",
    "proposal",
    "discussions"
]

PALAVRAS_RUMORES = [
    "interested",
    "interest",
    "monitoring",
    "tracking",
    "considering",
    "target",
    "could sign",
    "linked with",
    "rumour",
    "rumor",
    "reportedly"
]

EXCLUSOES = [
    "match report",
    "live commentary",
    "live score",
    "highlights",
    "fixtures",
    "standings",
    "injury update",
    "predicted lineup"
]

# ============================================================
# FUNÇÕES GERAIS
# ============================================================

def agora():
    return datetime.now(timezone.utc)


def data_atual():
    return agora().replace(microsecond=0).isoformat()


def limpar_texto(texto):

    if not texto:
        return ""

    texto = unescape(str(texto))

    texto = re.sub(
        r"<script.*?</script>",
        " ",
        texto,
        flags=re.I | re.S
    )

    texto = re.sub(
        r"<style.*?</style>",
        " ",
        texto,
        flags=re.I | re.S
    )

    texto = re.sub(r"<[^>]+>", " ", texto)

    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def normalizar(texto):

    texto = limpar_texto(texto).lower()

    texto = unicodedata.normalize("NFKD", texto)

    texto = "".join(
        c for c in texto
        if not unicodedata.combining(c)
    )

    return re.sub(r"[^a-z0-9 ]+", " ", texto).strip()


def normalizar_url(url):

    try:

        p = urlparse(url)

        return urlunparse((
            p.scheme or "https",
            p.netloc.lower().replace("www.", ""),
            p.path.rstrip("/"),
            "",
            "",
            ""
        ))

    except Exception:
        return url


def criar_id(url, titulo):

    base = normalizar_url(url) or normalizar(titulo)

    return hashlib.sha256(
        base.encode("utf-8")
    ).hexdigest()[:20]


def carregar_json(ficheiro, valor_padrao):

    if not ficheiro.exists():
        return valor_padrao

    try:

        with open(ficheiro, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as erro:

        log.warning(
            "Erro ao ler %s: %s",
            ficheiro.name,
            erro
        )

        return valor_padrao


def guardar_json(ficheiro, dados):

    temporario = ficheiro.with_suffix(".tmp")

    with open(temporario, "w", encoding="utf-8") as f:

        json.dump(
            dados,
            f,
            ensure_ascii=False,
            indent=2
        )

    temporario.replace(ficheiro)


# ============================================================
# TRADUÇÃO AUTOMÁTICA
# ============================================================

CACHE_TRADUCAO = {}


def traduzir(texto):

    texto = limpar_texto(texto)

    if not texto:
        return ""

    if texto in CACHE_TRADUCAO:
        return CACHE_TRADUCAO[texto]

    try:

        resultado = GoogleTranslator(
            source="auto",
            target="pt"
        ).translate(texto)

        if resultado:
            resultado = resultado.strip()
        else:
            resultado = texto

        CACHE_TRADUCAO[texto] = resultado

        time.sleep(0.25)

        return resultado

    except Exception as erro:

        log.warning(
            "Erro na tradução: %s",
            erro
        )

        return texto


# ============================================================
# DATAS
# ============================================================

def obter_data(entry):

    for campo in ["published", "updated"]:

        valor = entry.get(campo)

        if valor:

            try:

                data = parsedate_to_datetime(valor)

                if data.tzinfo is None:
                    data = data.replace(tzinfo=timezone.utc)

                return data.astimezone(timezone.utc)

            except Exception:
                pass

    for campo in ["published_parsed", "updated_parsed"]:

        valor = entry.get(campo)

        if valor:

            try:

                from time import mktime

                return datetime.fromtimestamp(
                    mktime(valor),
                    timezone.utc
                )

            except Exception:
                pass

    return None


# ============================================================
# CLASSIFICAÇÃO DAS NOTÍCIAS
# ============================================================

def classificar(titulo, resumo):

    texto = normalizar(titulo + " " + resumo)

    pontuacao = 0

    motivos = []

    palavras_encontradas = [
        palavra
        for palavra in PALAVRAS_MERCADO
        if normalizar(palavra) in texto
    ]

    pontuacao += min(
        60,
        len(palavras_encontradas) * 15
    )

    if palavras_encontradas:
        motivos.append("Palavras-chave de transferências")

    if any(
        normalizar(p) in texto
        for p in PALAVRAS_CONFIRMADAS
    ):

        estado = "Possível confirmação"

        pontuacao += 25

        motivos.append("Linguagem de confirmação")

    elif any(
        normalizar(p) in texto
        for p in PALAVRAS_AVANCADAS
    ):

        estado = "Possível acordo avançado"

        pontuacao += 20

        motivos.append("Acordo avançado")

    elif any(
        normalizar(p) in texto
        for p in PALAVRAS_NEGOCIACOES
    ):

        estado = "Negociações"

        pontuacao += 15

        motivos.append("Possíveis negociações")

    elif any(
        normalizar(p) in texto
        for p in PALAVRAS_RUMORES
    ):

        estado = "Rumor"

        pontuacao += 10

        motivos.append("Possível rumor")

    else:

        estado = "Por verificar"

    if any(
        normalizar(p) in texto
        for p in EXCLUSOES
    ):

        pontuacao -= 35

        motivos.append("Possível notícia geral")

    return (
        estado,
        max(0, min(100, pontuacao)),
        motivos
    )


# ============================================================
# JOGADORES
# ============================================================

def carregar_jogadores():

    dados = carregar_json(
        FICHEIRO_JOGADORES,
        []
    )

    if isinstance(dados, dict):
        dados = dados.get("players", [])

    jogadores = []

    if not isinstance(dados, list):
        return jogadores

    for jogador in dados:

        if isinstance(jogador, str):

            jogadores.append({
                "name": jogador,
                "currentClub": ""
            })

        elif isinstance(jogador, dict) and jogador.get("name"):

            jogadores.append({
                "name": jogador["name"],
                "currentClub": jogador.get("currentClub", "")
            })

    return jogadores


def encontrar_jogadores(texto, jogadores):

    texto = normalizar(texto)

    encontrados = []

    for jogador in jogadores:

        nome = jogador["name"]

        if normalizar(nome) in texto:

            encontrados.append(jogador)

    return encontrados


# ============================================================
# RECOLHA DE NOTÍCIAS
# ============================================================

def recolher_fonte(fonte):

    noticias = []

    relatorio = {
        "source": fonte["nome"],
        "feed": fonte["url"],
        "checkedAt": data_atual(),
        "status": "ok",
        "articlesRead": 0,
        "candidatesKept": 0,
        "error": None
    }

    try:

        feed = feedparser.parse(fonte["url"])

        if getattr(feed, "bozo", False) and not feed.entries:

            raise Exception("Feed RSS indisponível")

        limite = agora() - timedelta(
            days=IDADE_MAXIMA
        )

        for entry in feed.entries:

            relatorio["articlesRead"] += 1

            titulo = limpar_texto(
                entry.get("title", "")
            )

            resumo = limpar_texto(
                entry.get("summary", "")
            )

            if not resumo and entry.get("content"):

                resumo = limpar_texto(
                    entry["content"][0].get("value", "")
                )

            url = normalizar_url(
                entry.get("link", "")
            )

            if not titulo or not url:
                continue

            data = obter_data(entry)

            if data and data < limite:
                continue

            noticias.append({

                "title": titulo,

                "summary": resumo,

                "url": url,

                "date": (
                    data.replace(microsecond=0).isoformat()
                    if data else ""
                ),

                "source": fonte["nome"],

                "domain": urlparse(url).netloc.lower().replace(
                    "www.", ""
                )

            })

    except Exception as erro:

        relatorio["status"] = "erro"

        relatorio["error"] = str(erro)

        log.error(
            "Erro na fonte %s: %s",
            fonte["nome"],
            erro
        )

    return noticias, relatorio


# ============================================================
# CRIAR CANDIDATO
# ============================================================

def criar_candidato(noticia, jogadores):

    titulo_original = noticia["title"]

    resumo_original = noticia["summary"]

    estado, pontuacao, motivos = classificar(
        titulo_original,
        resumo_original
    )

    if pontuacao < 15:
        return None

    encontrados = encontrar_jogadores(
        titulo_original + " " + resumo_original,
        jogadores
    )

    jogador = ""

    clube = ""

    if encontrados:

        jogador = encontrados[0]["name"]

        clube = encontrados[0]["currentClub"]

    titulo_pt = traduzir(titulo_original)

    resumo_pt = traduzir(resumo_original)

    identificador = criar_id(
        noticia["url"],
        titulo_original
    )

    return {

        "id": identificador,

        "title": titulo_pt,

        "summary": resumo_pt,

        "originalTitle": titulo_original,

        "originalSummary": resumo_original,

        "originalLanguage": "en",

        "displayLanguage": "pt-PT",

        "source": noticia["source"],

        "domain": noticia["domain"],

        "url": noticia["url"],

        "date": noticia["date"],

        "collectedAt": data_atual(),

        "player": jogador,

        "currentClub": clube,

        "destination": "",

        "status": estado,

        "suggestedStatus": estado,

        "relevance": pontuacao,

        "classificationReasons": motivos,

        "detectedPlayers": [
            j["name"] for j in encontrados
        ],

        "editorApproved": False,

        "editorStatus": "Por verificar",

        "editorNotes": "",

        "independentSources": [
            noticia["source"]
        ],

        "engineVersion": VERSAO

    }


# ============================================================
# DUPLICADOS
# ============================================================

def sao_duplicados(a, b):

    titulo_a = normalizar(
        a.get("originalTitle", a.get("title", ""))
    )

    titulo_b = normalizar(
        b.get("originalTitle", b.get("title", ""))
    )

    if not titulo_a or not titulo_b:
        return False

    semelhanca = SequenceMatcher(
        None,
        titulo_a,
        titulo_b
    ).ratio()

    return semelhanca >= SIMILARIDADE


def agrupar_duplicados(candidatos):

    grupos = []

    for candidato in candidatos:

        encontrado = False

        for grupo in grupos:

            if any(
                sao_duplicados(candidato, outro)
                for outro in grupo
            ):

                grupo.append(candidato)

                encontrado = True

                break

        if not encontrado:

            grupos.append([candidato])

    resultado = []

    for grupo in grupos:

        principal = grupo[0]

        fontes = sorted(set(
            item["source"]
            for item in grupo
        ))

        principal["independentSources"] = fontes

        principal["sourceCount"] = len(fontes)

        resultado.append(principal)

    return resultado


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def executar():

    log.info(
        "A iniciar TRANSFER MARKET V%s",
        VERSAO
    )

    jogadores = carregar_jogadores()

    anteriores = carregar_json(
        FICHEIRO_SAIDA,
        []
    )

    if not isinstance(anteriores, list):
        anteriores = []

    anteriores_por_id = {
        item["id"]: item
        for item in anteriores
        if isinstance(item, dict) and item.get("id")
    }

    noticias = []

    relatorios = []

    # --------------------------------------------------------
    # RECOLHER TODAS AS FONTES
    # --------------------------------------------------------

    for fonte in FONTES:

        log.info(
            "A pesquisar: %s",
            fonte["nome"]
        )

        resultados, relatorio = recolher_fonte(
            fonte
        )

        noticias.extend(resultados)

        relatorios.append(relatorio)

    # Mais recentes primeiro

    noticias.sort(
        key=lambda n: n.get("date", ""),
        reverse=True
    )

    novos = []

    ids_processados = set()

    # --------------------------------------------------------
    # PROCESSAR NOTÍCIAS
    # --------------------------------------------------------

    for noticia in noticias:

        identificador = criar_id(
            noticia["url"],
            noticia["title"]
        )

        if identificador in ids_processados:
            continue

        ids_processados.add(identificador)

        if identificador in anteriores_por_id:
            continue

        candidato = criar_candidato(
            noticia,
            jogadores
        )

        if candidato:

            novos.append(candidato)

    # --------------------------------------------------------
    # AGRUPAR DUPLICADOS
    # --------------------------------------------------------

    novos = agrupar_duplicados(novos)

    # --------------------------------------------------------
    # PRESERVAR HISTÓRICO E DECISÕES EDITORIAIS
    # --------------------------------------------------------

    todos = {}

    for antigo in anteriores:

        if not isinstance(antigo, dict):
            continue

        if antigo.get("id"):
            todos[antigo["id"]] = antigo

    for novo in novos:

        identificador = novo["id"]

        antigo = anteriores_por_id.get(
            identificador,
            {}
        )

        for campo in [
            "editorApproved",
            "editorNotes",
            "editorStatus",
            "manualPlayer",
            "manualCurrentClub",
            "manualDestination"
        ]:

            if campo in antigo:

                novo[campo] = antigo[campo]

        todos[identificador] = novo

    candidatos = list(todos.values())

    # Ordenação

    candidatos.sort(
        key=lambda n: (
            n.get("date", ""),
            n.get("relevance", 0)
        ),
        reverse=True
    )

    candidatos = candidatos[:MAXIMO_CANDIDATOS]

    # --------------------------------------------------------
    # RELATÓRIO DAS FONTES
    # --------------------------------------------------------

    for relatorio in relatorios:

        relatorio["candidatesKept"] = sum(
            1 for n in novos
            if n["source"] == relatorio["source"]
        )

    relatorio_final = {

        "engine": "TRANSFER MARKET",

        "version": VERSAO,

        "generatedAt": data_atual(),

        "translation": {

            "enabled": True,

            "target": "pt-PT",

            "provider": "GoogleTranslator",

            "originalPreserved": True

        },

        "automaticPublication": False,

        "xPostsUsed": False,

        "totals": {

            "sources": len(FONTES),

            "articlesCollected": len(noticias),

            "newCandidates": len(novos),

            "totalCandidates": len(candidatos),

            "awaitingReview": sum(
                1 for n in candidatos
                if not n.get("editorApproved", False)
            )

        },

        "sourcesReport": relatorios

    }

    # --------------------------------------------------------
    # GUARDAR FICHEIROS
    # --------------------------------------------------------

    guardar_json(
        FICHEIRO_SAIDA,
        candidatos
    )

    guardar_json(
        FICHEIRO_RELATORIO,
        relatorio_final
    )

    historico = carregar_json(
        FICHEIRO_HISTORICO,
        {}
    )

    if not isinstance(historico, dict):
        historico = {}

    ids_antigos = set(
        historico.get("seenIds", [])
    )

    ids_antigos.update(ids_processados)

    historico["seenIds"] = list(
        ids_antigos
    )[-10000:]

    historico["updatedAt"] = data_atual()

    guardar_json(
        FICHEIRO_HISTORICO,
        historico
    )

    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    log.info("--------------------------------")

    log.info("TRANSFER MARKET concluído!")

    log.info(
        "Novos candidatos: %s",
        len(novos)
    )

    log.info(
        "Total de candidatos: %s",
        len(candidatos)
    )

    log.info(
        "Ficheiro: candidatos.json"
    )

    log.info(
        "Relatório: relatorio_fontes.json"
    )

    log.info("--------------------------------")


# ============================================================
# INICIAR MOTOR
# ============================================================

if __name__ == "__main__":

    try:

        executar()

    except Exception as erro:

        log.exception(
            "Erro geral no motor: %s",
            erro
        )

        raise
