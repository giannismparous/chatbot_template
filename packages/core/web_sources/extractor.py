from __future__ import annotations

from bs4 import BeautifulSoup

STRIP_TAGS = ("script", "style", "nav", "footer", "header", "noscript", "iframe", "svg", "form")


def extract_readable_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag_name in STRIP_TAGS:
        for node in soup.find_all(tag_name):
            node.decompose()

    main = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"})
    root = main or soup.body or soup
    text = root.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def extract_page_title(html: str) -> str | None:
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        return title or None
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        return text or None
    return None
