#!/usr/bin/env python3
"""Gera feed.xml (RSS 2.0) com as notícias da ANEEL lendo o HTML do site.

Só usa a biblioteca padrão do Python (sem pip install).
Mantém um cache.json para o feed acumular notícias mesmo que a página
mostre apenas as mais recentes.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

BASE = "https://www.gov.br/aneel/pt-br/assuntos/noticias"
# Páginas onde procurar links de notícias. Se a listagem principal for
# carregada por JavaScript, acrescente aqui outra página que traga os links
# já no HTML (veja o README/explicação).
FONTES = [BASE]

MAX_ITENS = 50   # itens no feed
MAX_NOVOS = 30   # notícias novas lidas por execução
CACHE = Path("cache.json")
SAIDA = Path("feed.xml")
FUSO = timezone(timedelta(hours=-3))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CABECALHOS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
    "Referer": "https://www.gov.br/aneel/pt-br",
}

LINK_RE = re.compile(
    r'href="((?:https://www\.gov\.br)?/aneel/pt-br/assuntos/noticias/\d{4}/[^"#?\s]+)"'
)
DATA_RE = re.compile(r"Publicado em\s*(\d{2})/(\d{2})/(\d{4})\s*(\d{2}):(\d{2})")


def baixar(url, tentativas=4):
    ultimo_erro = None
    for n in range(tentativas):
        try:
            req = Request(url, headers=CABECALHOS)
            with urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            ultimo_erro = e
            time.sleep(5 * (n + 1))
    raise ultimo_erro


def achar_links(html):
    links = []
    for m in LINK_RE.findall(html):
        u = m if m.startswith("http") else "https://www.gov.br" + m
        u = u.rstrip("/")
        if u not in links:
            links.append(u)
    return links


def meta(html, prop):
    padroes = (
        rf'<meta[^>]+(?:property|name)="{prop}"[^>]+content="([^"]*)"',
        rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{prop}"',
    )
    for p in padroes:
        m = re.search(p, html, re.I)
        if m:
            return unescape(m.group(1)).strip()
    return ""


def sem_tags(texto):
    return unescape(re.sub(r"<[^>]+>", "", texto)).strip()


def ler_noticia(url):
    html = baixar(url)
    titulo = meta(html, "og:title")
    if not titulo:
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        titulo = sem_tags(h1.group(1)) if h1 else url
    resumo = meta(html, "og:description") or meta(html, "description")
    d = DATA_RE.search(sem_tags(html))
    if d:
        dia, mes, ano, h, mi = map(int, d.groups())
        data = datetime(ano, mes, dia, h, mi, tzinfo=FUSO)
    else:
        data = datetime.now(FUSO)
    return {"titulo": titulo, "link": url, "resumo": resumo, "data": data.isoformat()}


def montar_feed(itens):
    rss = ET.Element("rss", version="2.0")
    canal = ET.SubElement(rss, "channel")
    ET.SubElement(canal, "title").text = "ANEEL – Notícias (feed não oficial)"
    ET.SubElement(canal, "link").text = BASE
    ET.SubElement(canal, "description").text = "Notícias da Agência Nacional de Energia Elétrica"
    ET.SubElement(canal, "language").text = "pt-BR"
    ET.SubElement(canal, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    for i in itens:
        it = ET.SubElement(canal, "item")
        ET.SubElement(it, "title").text = i["titulo"]
        ET.SubElement(it, "link").text = i["link"]
        ET.SubElement(it, "guid", isPermaLink="true").text = i["link"]
        ET.SubElement(it, "description").text = i["resumo"]
        ET.SubElement(it, "pubDate").text = format_datetime(datetime.fromisoformat(i["data"]))
    ET.indent(rss)
    ET.ElementTree(rss).write(SAIDA, encoding="utf-8", xml_declaration=True)


def main():
    cache = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}

    links = []
    for fonte in FONTES:
        try:
            links += achar_links(baixar(fonte))
        except Exception as e:
            print(f"Erro ao abrir {fonte}: {e}", file=sys.stderr)

    if not links:
        sys.exit(
            "Nenhum link de notícia obtido. Se houve erro de conexão acima, o site "
            "provavelmente bloqueia este IP (comum em servidores na nuvem). Se a "
            "página abriu mas sem links, a listagem é carregada por JavaScript: "
            "ajuste FONTES ou use o endereço da aba Rede."
        )

    novos = [u for u in dict.fromkeys(links) if u not in cache][:MAX_NOVOS]
    for u in novos:
        try:
            cache[u] = ler_noticia(u)
            print("Nova:", cache[u]["titulo"])
            time.sleep(1)  # educado com o servidor
        except Exception as e:
            print(f"Erro em {u}: {e}", file=sys.stderr)

    itens = sorted(cache.values(), key=lambda i: i["data"], reverse=True)[:MAX_ITENS]
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), "utf-8")
    montar_feed(itens)
    print(f"feed.xml gerado com {len(itens)} itens.")


if __name__ == "__main__":
    main()
