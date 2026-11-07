
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================
TRANSFER MARKET — INTELLIGENCE ENGINE V6.0
============================================================
- Recolha automática de notícias RSS.
- Tradução para português.
- Preservação dos textos originais.
- Correção da tradução de candidatos antigos.
- Classificação mais rigorosa.
- Redução de notícias irrelevantes.
- Deteção de duplicados.
- Preservação das decisões editoriais.
- Ordenação cronológica.
- Separação dos dados de transferências oficiais.
============================================================
"""

import os
import re
import json
import hashlib
import logging
import time
import unicodedata

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

VERSAO = "6.0"

PASTA = Path(__file__).resolve().parent

FICHEIRO_SAIDA = PASTA / "candidatos.json"
FICHEIRO_RELATORIO = PASTA / "relatorio_fontes.json"
FICHEIRO_HISTORICO = PASTA / "historico_transferencias.json"
FICHEIRO_JOGADORES = PASTA / "players.json"
FICHEIRO_OFICIAIS = PASTA / "oficiais.json"

IDADE_MAXIMA = 30
MAXIMO_CANDIDATOS = 500
SIMILARIDADE = 0.84

PAUSA_TRADUCAO = 0.3

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

if os.getenv("FABRIZIO_RSS_URL"):
    FONTES.append({
        "nome": "Fonte adicional",
        "url": os.getenv("FABRIZIO_RSS_URL")
    })


# ============================================================
# PALAVRAS-CHAVE
# ============================================================

# Expressões específicas de transferências.
SINAIS_TRANSFERENCIA = [
    "transfer news",
    "transfer window",
    "transfer target",
    "transfer interest",
    "transfer move",
    "transfer deal",
    "transfer talks",
    "transfer agreement",
    "transfer fee",
    "transfer bid",
    "loan move",
    "loan deal",
    "loan signing",
    "signs for",
    "signed for",
    "signing for",
    "joins on loan",
    "joins permanently",
    "set to join",
    "set to sign",
    "agrees to join",
    "agrees terms",
    "personal terms",
    "medical booked",
    "medical scheduled",
    "agreement reached",
    "deal agreed",
    "bid submitted",
    "bid rejected",
    "club interested",
    "interested in signing",
    "fichajes",
    "mercato",
    "transferência",
    "transferências",
    "mercado de transferências",
    "contratação",
    "contratado por",
    "assina por",
    "assinar por",
    "empréstimo",
    "proposta de transferência",
    "negociações por"
]

SINAIS_RUMOR = [
    "interested in",
    "interest in",
    "monitoring",
    "tracking",
    "considering a move",
    "could sign",
    "could join",
    "linked with",
    "linked to",
    "reportedly wants",
    "transfer target",
    "transfer pursuit",
    "rumour",
    "rumor",
    "gossip",
    "keen on signing",
    "wants to sign"
]

SINAIS_NEGOCIACAO = [
    "negotiations",
    "talks over a move",
    "talks over a deal",
    "talks with",
    "bid submitted",
    "bid rejected",
    "offer submitted",
    "offer rejected",
    "formal offer",
    "proposal submitted",
    "discussions over a move"
]

SINAIS_ACORDO = [
    "agreement reached",
    "deal agreed",
    "verbal agreement",
    "personal terms agreed",
    "medical booked",
    "medical scheduled",
    "final stages of the deal",
    "advanced talks",
    "set to complete",
    "close to signing"
]

# Não basta encontrar estas expressões para confirmar
# uma transferência. A confirmação oficial é verificada
# separadamente, através de um anúncio do clube.

EXCLUSOES = [
    "match report",
    "live commentary",
    "live score",
    "highlights",
    "fixtures",
    "standings",
    "injury update",
    "predicted lineup",
    "player ratings",
    "match reaction",
    "post-match",
    "champions league result",
    "premier league result",
    "race meeting",
    "horse racing",
    "november handicap",
    "doncaster races",
    "southwell",
    "uttoxeter",
    "cricket",
    "tennis",
    "rugby",
    "golf"
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

    return re.sub(
        r"[^a-z0-9 ]+",
        " ",
        texto
    ).strip()


def normalizar_url(url):

    try:

        p = urlparse(url)

        if not p.netloc:
            return ""

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


def converter_data(valor):

    if not valor:
        return None

    try:

        data = datetime.fromisoformat(
            str(valor).replace("Z", "+00:00")
        )

        if data.tzinfo is None:
            data = data.replace(tzinfo=timezone.utc)

        return data.astimezone(timezone.utc)

    except Exception:
        return None


def chave_data(item):

    data = converter_data(item.get("date", ""))

    if data:
        return data.timestamp()

    return 0


# ============================================================
# TRADUÇÃO
# ============================================================

CACHE_TRADUCAO = {}


def traduzir(texto):

    texto = limpar_texto(texto)

    if not texto:
        return ""

    if texto in CACHE_TRADUCAO:
        return CACHE_TRADUCAO[texto]

    try:

        tradutor = GoogleTranslator(
            source="auto",
            target="pt"
        )

        partes = [
            texto[i:i + 4000]
            for i in range(0, len(texto), 4000)
        ]

        resultado = []

        for parte in partes:

            traducao = tradutor.translate(parte)

            if traducao:
                resultado.append(traducao)
            else:
                resultado.append(parte)

            time.sleep(PAUSA_TRADUCAO)

        texto_final = " ".join(resultado).strip()

        if not texto_final:
            return texto

        CACHE_TRADUCAO[texto] = texto_final

        return texto_final

    except Exception as erro:

        log.warning(
            "Erro de tradução: %s",
            erro
        )

        return texto


# ============================================================
# DATAS RSS
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

                from calendar import timegm

                return datetime.fromtimestamp(
                    timegm(valor),
                    timezone.utc
                )

            except Exception:
                pass

    return None


# ============================================================
# CLASSIFICAÇÃO
# ============================================================

def contem_expressao(texto, expressoes):

    return any(
        normalizar(expressao) in texto
        for expressao in expressoes
    )


def classificar(titulo, resumo):

    texto_original = normalizar(titulo + " " + resumo)

    motivos = []

    exclusao = contem_expressao(
        texto_original,
        EXCLUSOES
    )

    if exclusao:

        return (
            "Por verificar",
            0,
            ["Notícia excluída por não parecer relacionada com transferências"]
        )

    sinais = [
        sinal
        for sinal in SINAIS_TRANSFERENCIA
        if normalizar(sinal) in texto_original
    ]

    if not sinais:

        return (
            "Por verificar",
            0,
            ["Não foram encontrados sinais suficientes de transferência"]
        )

    pontuacao = min(60, len(sinais) * 20)

    motivos.append(
        "Expressões relacionadas com transferências"
    )

    if contem_expressao(texto_original, SINAIS_ACORDO):

        estado = "Acordo próximo"
        pontuacao += 25

        motivos.append(
            "Indícios de acordo avançado"
        )

    elif contem_expressao(texto_original, SINAIS_NEGOCIACAO):

        estado = "Negociações"
        pontuacao += 20

        motivos.append(
            "Indícios de negociações"
        )

    elif contem_expressao(texto_original, SINAIS_RUMOR):

        estado = "Rumor"
        pontuacao += 15

        motivos.append(
            "Indícios de interesse ou rumor"
        )

    else:

        estado = "Por verificar"

    return (
        estado,
        min(100, pontuacao),
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

    texto_normalizado = normalizar(texto)

    encontrados = []

    for jogador in jogadores:

        nome = normalizar(jogador["name"])

        if not nome or len(nome) < 4:
            continue

        if re.search(
            r"\b" + re.escape(nome) + r"\b",
            texto_normalizado
        ):

            encontrados.append(jogador)

    return encontrados


# ============================================================
# RECOLHA RSS
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

    # Evitar guardar notícias sem relevância suficiente.
    if pontuacao < 20:
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

    data = noticia["date"]

    return {

        "id": identificador,

        # Campos do site
        "title": titulo_pt,
        "summary": resumo_pt,
        "source": noticia["source"],
        "domain": noticia["domain"],
        "url": noticia["url"],
        "date": data,

        "firstSeen": data_atual(),
        "lastSeen": data_atual(),

        "status": estado,

        "verification": (
            "Artigo recolhido automaticamente. "
            "Aguarda verificação editorial."
        ),

        "player": jogador,
        "currentClub": clube,
        "destination": "",

        "detectedClubs": [clube] if clube else [],

        "classification": "Notícia de transferências",
        "transferRelevance": pontuacao,

        # Texto original
        "originalTitle": titulo_original,
        "originalSummary": resumo_original,

        "originalLanguage": "auto",
        "displayLanguage": "pt-PT",

        # Dados do motor
        "collectedAt": data_atual(),
        "suggestedStatus": estado,
        "relevance": pontuacao,
        "classificationReasons": motivos,

        "detectedPlayers": [
            j["name"] for j in encontrados
        ],

        # Decisões editoriais
        "editorApproved": False,
        "editorStatus": "Por verificar",
        "editorNotes": "",

        "independentSources": [noticia["source"]],
        "sourceCount": 1,

        "engineVersion": VERSAO
    }


# ============================================================
# ATUALIZAR CANDIDATOS ANTIGOS
# ============================================================

def atualizar_candidato_antigo(candidato):

    if not isinstance(candidato, dict):
        return candidato

    titulo_original = limpar_texto(
        candidato.get("originalTitle")
        or candidato.get("title", "")
    )

    resumo_original = limpar_texto(
        candidato.get("originalSummary")
        or candidato.get("summary", "")
    )

    if not titulo_original:
        return candidato

    candidato["originalTitle"] = titulo_original
    candidato["originalSummary"] = resumo_original

    # Recriar a tradução a partir do texto original.
    # Isto corrige registos anteriormente marcados
    # como pt-PT sem terem sido traduzidos.

    candidato["title"] = traduzir(titulo_original)
    candidato["summary"] = traduzir(resumo_original)

    candidato["originalLanguage"] = candidato.get(
        "originalLanguage",
        "auto"
    )

    candidato["displayLanguage"] = "pt-PT"

    candidato.setdefault("firstSeen", data_atual())
    candidato.setdefault("lastSeen", data_atual())

    candidato.setdefault(
        "verification",
        "Aguarda verificação editorial."
    )

    candidato.setdefault(
        "classification",
        "Notícia de transferências"
    )

    candidato.setdefault(
        "transferRelevance",
        candidato.get("relevance", 0)
    )

    candidato.setdefault("detectedClubs", [])
    candidato.setdefault("destination", "")
    candidato.setdefault("player", "")
    candidato.setdefault("currentClub", "")

    candidato.setdefault("editorApproved", False)
    candidato.setdefault("editorStatus", "Por verificar")
    candidato.setdefault("editorNotes", "")

    candidato.setdefault(
        "relevance",
        candidato.get("transferRelevance", 0)
    )

    candidato["engineVersion"] = VERSAO

    return candidato


# ============================================================
# DUPLICADOS
# ============================================================

def sao_duplicados(a, b):

    titulo_a = normalizar(
        a.get("originalTitle") or a.get("title", "")
    )

    titulo_b = normalizar(
        b.get("originalTitle") or b.get("title", "")
    )

    if not titulo_a or not titulo_b:
        return False

    semelhanca = SequenceMatcher(
        None,
        titulo_a,
        titulo_b
    ).ratio()

    if semelhanca >= SIMILARIDADE:
        return True

    # Comparação adicional através dos nomes dos jogadores.
    jogador_a = normalizar(a.get("player", ""))
    jogador_b = normalizar(b.get("player", ""))

    if jogador_a and jogador_a == jogador_b:

        palavras_a = set(titulo_a.split())
        palavras_b = set(titulo_b.split())

        comuns = palavras_a.intersection(palavras_b)

        if len(comuns) >= 5:
            return True

    return False


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

        # Preferir a notícia com mais informação.
        grupo.sort(
            key=lambda item: (
                len(item.get("summary", "")),
                chave_data(item)
            ),
            reverse=True
        )

        principal = grupo[0]

        fontes = sorted(set(
            item.get("source", "")
            for item in grupo
            if item.get("source")
        ))

        principal["independentSources"] = fontes
        principal["sourceCount"] = len(fontes)

        resultado.append(principal)

    return resultado


# ============================================================
# TRANSFERÊNCIAS OFICIAIS
# ============================================================

def carregar_oficiais():

    dados = carregar_json(
        FICHEIRO_OFICIAIS,
        []
    )

    if not isinstance(dados, list):
        dados = []

    # Não criar confirmações automaticamente a partir
    # de notícias da BBC ou da Sky.
    #
    # Este ficheiro fica separado dos rumores.
    # Só devem ser adicionados registos com anúncio
    # oficial verificável do clube.

    dados = [
        item for item in dados
        if isinstance(item, dict)
    ]

    dados.sort(
        key=chave_data,
        reverse=True
    )

    guardar_json(
        FICHEIRO_OFICIAIS,
        dados
    )

    return dados


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

    anteriores_por_id = {}

    # Migrar e preservar candidatos antigos.
    for item in anteriores:

        if not isinstance(item, dict):
            continue

        if not item.get("id"):
            continue

        item = atualizar_candidato_antigo(item)

        anteriores_por_id[item["id"]] = item

    noticias = []
    relatorios = []

    # --------------------------------------------------------
    # RECOLHER FONTES
    # --------------------------------------------------------

    for fonte in FONTES:

        log.info(
            "A pesquisar: %s",
            fonte["nome"]
        )

        resultados, relatorio = recolher_fonte(fonte)

        noticias.extend(resultados)
        relatorios.append(relatorio)

    noticias.sort(
        key=lambda n: (
            converter_data(n.get("date", ""))
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
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

            antigos = anteriores_por_id[identificador]

            antigos["lastSeen"] = data_atual()

            continue

        candidato = criar_candidato(
            noticia,
            jogadores
        )

        if candidato:
            novos.append(candidato)

    # --------------------------------------------------------
    # DUPLICADOS
    # --------------------------------------------------------

    novos = agrupar_duplicados(novos)

    # --------------------------------------------------------
    # PRESERVAR CANDIDATOS E DECISÕES
    # --------------------------------------------------------

    todos = dict(anteriores_por_id)

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
            "manualDestination",
            "status",
            "verification"
        ]:

            if campo in antigo:
                novo[campo] = antigo[campo]

        todos[identificador] = novo

    candidatos = list(todos.values())

    # Ordenação pela data de publicação.
    candidatos.sort(
        key=chave_data,
        reverse=True
    )

    candidatos = candidatos[:MAXIMO_CANDIDATOS]

    # --------------------------------------------------------
    # RELATÓRIO
    # --------------------------------------------------------

    for relatorio in relatorios:

        relatorio["candidatesKept"] = sum(
            1 for n in novos
            if n.get("source") == relatorio["source"]
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
    # HISTÓRICO
    # --------------------------------------------------------

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
    historico["engineVersion"] = VERSAO

    # --------------------------------------------------------
    # OFICIAIS
    # --------------------------------------------------------

    oficiais = carregar_oficiais()

    # --------------------------------------------------------
    # GUARDAR
    # --------------------------------------------------------

    guardar_json(
        FICHEIRO_SAIDA,
        candidatos
    )

    guardar_json(
        FICHEIRO_RELATORIO,
        relatorio_final
    )

    guardar_json(
        FICHEIRO_HISTORICO,
        historico
    )

    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    log.info("--------------------------------")
    log.info("TRANSFER MARKET concluído!")
    log.info("Versão: %s", VERSAO)
    log.info("Novos candidatos: %s", len(novos))
    log.info("Total de candidatos: %s", len(candidatos))
    log.info("Transferências oficiais: %s", len(oficiais))
    log.info("Tradução: português")
    log.info("Rumores: candidatos.json")
    log.info("Oficiais: oficiais.json")
    log.info("--------------------------------")


# ============================================================
# INICIAR
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
