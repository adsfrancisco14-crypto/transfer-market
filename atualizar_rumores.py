import feedparser
import json
import os
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

# ==================================================
# TRANSFER MARKET — MOTOR DE RECOLHA DE NOTÍCIAS
# ==================================================

FICHEIRO_SAIDA = "candidatos.json"

FONTES = [
    {
        "nome": "BBC Sport",
        "url": "https://feeds.bbci.co.uk/sport/football/rss.xml",
        "dominio": "bbc.co.uk"
    },
    {
        "nome": "Sky Sports",
        "url": "https://www.skysports.com/rss/11095",
        "dominio": "skysports.com"
    }
]

PALAVRAS_TRANSFERENCIAS = [
    "transfer",
    "transfers",
    "transferência",
    "transferencias",
    "transferências",
    "signing",
    "signs",
    "signed",
    "deal",
    "bid",
    "loan",
    "loan move",
    "agreed",
    "agreement",
    "interest",
    "interested",
    "target",
    "targets",
    "move",
    "move to",
    "joins",
    "join",
    "contract",
    "release clause",
    "mercado",
    "negociações"
]

MAX_ARTIGOS_POR_FONTE = 100
LIMITE_CANDIDATOS = 200
SIMILARIDADE_MINIMA = 0.55


# ==================================================
# FUNÇÕES AUXILIARES
# ==================================================

def texto_limpo(texto):
    texto = str(texto or "")
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def normalizar(texto):
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9áéíóúàèìòùãõç ]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def e_noticia_de_transferencia(titulo, resumo):
    texto = normalizar(titulo + " " + resumo)

    return any(
        palavra in texto
        for palavra in PALAVRAS_TRANSFERENCIAS
    )


def converter_data(entry):
    data = (
        entry.get("published")
        or entry.get("updated")
        or ""
    )

    if not data:
        return datetime.now(timezone.utc).isoformat()

    try:
        data_convertida = parsedate_to_datetime(data)

        if data_convertida.tzinfo is None:
            data_convertida = data_convertida.replace(
                tzinfo=timezone.utc
            )

        return data_convertida.astimezone(
            timezone.utc
        ).isoformat()

    except Exception:
        return datetime.now(timezone.utc).isoformat()


def semelhante(texto1, texto2):
    texto1 = normalizar(texto1)
    texto2 = normalizar(texto2)

    return SequenceMatcher(
        None,
        texto1,
        texto2
    ).ratio()


# ==================================================
# LER NOTÍCIAS DOS FEEDS
# ==================================================

def recolher_noticias():
    noticias = []

    for fonte in FONTES:
        print(f"A consultar: {fonte['nome']}")

        try:
            feed = feedparser.parse(
                fonte["url"],
                request_headers={
                    "User-Agent": "TransferMarketBot/1.0"
                }
            )

            if feed.bozo and not feed.entries:
                print(
                    f"Feed indisponível: {fonte['nome']}"
                )
                continue

            for artigo in feed.entries[:MAX_ARTIGOS_POR_FONTE]:

                titulo = texto_limpo(
                    artigo.get("title", "")
                )

                resumo = texto_limpo(
                    artigo.get("summary", "")
                )

                link = artigo.get("link", "")

                if not titulo or not link:
                    continue

                if not e_noticia_de_transferencia(
                    titulo,
                    resumo
                ):
                    continue

                noticia = {
                    "title": titulo,
                    "summary": resumo[:1000],
                    "source": fonte["nome"],
                    "domain": fonte["dominio"],
                    "url": link,
                    "date": converter_data(artigo),
                }

                noticias.append(noticia)

        except Exception as erro:
            print(
                f"Erro na fonte {fonte['nome']}: {erro}"
            )

    return noticias


# ==================================================
# COMPARAR FONTES INDEPENDENTES
# ==================================================

def agrupar_noticias(noticias):
    grupos = []

    noticias = sorted(
        noticias,
        key=lambda item: item["date"],
        reverse=True
    )

    for noticia in noticias:
        grupo_encontrado = None

        for grupo in grupos:
            titulo_referencia = grupo[0]["title"]

            if semelhante(
                noticia["title"],
                titulo_referencia
            ) >= SIMILARIDADE_MINIMA:

                grupo_encontrado = grupo
                break

        if grupo_encontrado is None:
            grupos.append([noticia])
        else:
            dominios = {
                item["domain"]
                for item in grupo_encontrado
            }

            if noticia["domain"] not in dominios:
                grupo_encontrado.append(noticia)

    return grupos


# ==================================================
# CRIAR CANDIDATOS
# ==================================================

def criar_candidatos(grupos):
    candidatos = []

    for grupo in grupos:

        fontes = sorted({
            artigo["source"]
            for artigo in grupo
        })

        dominios = sorted({
            artigo["domain"]
            for artigo in grupo
        })

        if len(dominios) < 2:
            continue

        principal = sorted(
            grupo,
            key=lambda item: item["date"],
            reverse=True
        )[0]

        candidato = {
            "title": principal["title"],
            "summary": principal["summary"],
            "status": "Por verificar",
            "verification": (
                "Duas fontes encontraram títulos semelhantes. "
                "É necessária verificação editorial."
            ),
            "sourcesCount": len(dominios),
            "sources": [
                {
                    "name": artigo["source"],
                    "url": artigo["url"],
                    "date": artigo["date"]
                }
                for artigo in grupo
            ],
            "date": principal["date"],
            "player": "",
            "currentClub": "",
            "destination": "",
            "league": "Europa",
            "url": principal["url"]
        }

        candidatos.append(candidato)

    return candidatos


# ==================================================
# GUARDAR RESULTADOS
# ==================================================

def guardar_candidatos(novos):
    antigos = []

    if os.path.exists(FICHEIRO_SAIDA):
        try:
            with open(
                FICHEIRO_SAIDA,
                "r",
                encoding="utf-8"
            ) as ficheiro:
                antigos = json.load(ficheiro)

        except Exception:
            antigos = []

    mapa = {}

    for candidato in antigos + novos:
        chave = normalizar(
            candidato.get("title", "")
        )

        if chave:
            mapa[chave] = candidato

    resultados = sorted(
        mapa.values(),
        key=lambda item: item.get("date", ""),
        reverse=True
    )

    resultados = resultados[:LIMITE_CANDIDATOS]

    with open(
        FICHEIRO_SAIDA,
        "w",
        encoding="utf-8"
    ) as ficheiro:

        json.dump(
            resultados,
            ficheiro,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"Foram guardados {len(resultados)} candidatos."
    )


# ==================================================
# EXECUÇÃO PRINCIPAL
# ==================================================

def main():
    print("=" * 50)
    print("TRANSFER MARKET — ATUALIZAÇÃO AUTOMÁTICA")
    print("=" * 50)

    noticias = recolher_noticias()

    print(
        f"Artigos de transferências encontrados: "
        f"{len(noticias)}"
    )

    grupos = agrupar_noticias(noticias)

    candidatos = criar_candidatos(grupos)

    guardar_candidatos(candidatos)

    print("Atualização terminada.")


if __name__ == "__main__":
    main()
