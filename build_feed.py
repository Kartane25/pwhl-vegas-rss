
#!/usr/bin/env python3
"""Build an RSS feed from official Vegas Vanguards news."""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import os
import re
import time
from html import escape
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

HOME = "https://www.thepwhl.com/en/teams/vegas-vanguards"
NEWS = HOME + "/news"
PREFIXES = (
    "/en/teams/vegas-vanguards/news/",
    "/en/teams/las-vegas/news/",
)
OUT = "site/feed.xml"
LIMIT = 20
STATE_FILE = "article_timestamps.json"
LIVE_FEED = "https://kartane25.github.io/pwhl-vegas-rss/feed.xml"
NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"
NS_MEDIA = "http://search.yahoo.com/mrss/"

ET.register_namespace("content", NS_CONTENT)
ET.register_namespace("media", NS_MEDIA)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; VegasVanguardsRSS/2.0)",
    "Accept-Language": "en-US,en;q=0.9",
})


def fetch(url):
    response = SESSION.get(url, timeout=25)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def meta(soup, *keys):
    for key in keys:
        node = (
            soup.find("meta", attrs={"property": key})
            or soup.find("meta", attrs={"name": key})
        )
        if node and node.get("content", "").strip():
            return node["content"].strip()
    return ""


def clean_text(value):
    return " ".join(str(value or "").split())


def discover(soup):
    results = []

    for a in soup.select("a[href]"):
        url = urljoin(NEWS, a["href"])
        url = url.split("#")[0].split("?")[0]
        parsed = urlparse(url)

        if parsed.netloc not in (
            "thepwhl.com",
            "www.thepwhl.com",
        ):
            continue

        path = parsed.path.rstrip("/")

        if not any(
            path.startswith(prefix)
            for prefix in PREFIXES
        ):
            continue

        # Exclude news indexes and other non-article paths.
        if not re.search(
            r"/news/\d{4}/[a-z]+/\d{1,2}/",
            path,
            re.I,
        ):
            continue

        if url not in results:
            results.append(url)

    return results[:LIMIT]


def jsonld_articles(soup):
    objects = []

    for tag in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            raw = json.loads(tag.string or tag.get_text())
        except (ValueError, TypeError):
            continue

        stack = [raw]

        while stack:
            obj = stack.pop()

            if isinstance(obj, list):
                stack.extend(obj)

            elif isinstance(obj, dict):
                objects.append(obj)
                stack.extend(
                    value
                    for key, value in obj.items()
                    if key in (
                        "@graph",
                        "mainEntity",
                        "itemListElement",
                    )
                )

    return [
        obj for obj in objects
        if any(
            kind in str(obj.get("@type", ""))
            for kind in ("Article", "NewsArticle")
        )
    ]


def parse_date(value):
    if not value:
        return None

    try:
        stamp = dt.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        return stamp
    except ValueError:
        return None


def parse_article(url):
    soup = fetch(url)
    schemas = jsonld_articles(soup)
    item = schemas[0] if schemas else {}

    title = (
        meta(soup, "og:title", "twitter:title")
        or item.get("headline", "")
    )

    if not title and soup.h1:
        title = soup.h1.get_text(" ", strip=True)

    title = clean_text(title)

    if not title:
        raise ValueError("No article title: " + url)

    description = (
        meta(
            soup,
            "og:description",
            "description",
            "twitter:description",
        )
        or item.get("description", "")
    )

    description = clean_text(description)

    if not description:
        main = soup.find("article") or soup.find("main")
        if main:
            for p in main.find_all("p"):
                value = clean_text(
                    p.get_text(" ", strip=True)
                )
                if len(value) > 80:
                    description = value
                    break

    image = meta(soup, "og:image", "twitter:image")

    if not image:
        raw_image = item.get("image", "")

        if isinstance(raw_image, str):
            image = raw_image
        elif isinstance(raw_image, dict):
            image = raw_image.get("url", "")
        elif isinstance(raw_image, list) and raw_image:
            first = raw_image[0]
            image = (
                first if isinstance(first, str)
                else first.get("url", "")
                if isinstance(first, dict)
                else ""
            )

    image = urljoin(url, image) if image else ""

    published = (
        item.get("datePublished")
        or meta(
            soup,
            "article:published_time",
            "datePublished",
        )
    )

    stamp = parse_date(published)

    # Preserve the original publication date from the URL.
    if stamp is None:
        match = re.search(
            r"/news/(\d{4})/([a-z]+)/(\d{1,2})/",
            url,
            re.I,
        )

        if match:
            try:
                stamp = dt.datetime.strptime(
                    " ".join(match.groups()),
                    "%Y %B %d",
                ).replace(tzinfo=dt.timezone.utc)
            except ValueError:
                pass

    if stamp is None:
        stamp = dt.datetime.now(dt.timezone.utc)

    return {
        "title": title,
        "url": url,
        "description": description[:750],
        "image": image,
        "date": stamp,
    }


def load_timestamps():
    """Load permanent first-discovered article timestamps."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    # First-run migration: preserve dates already published
    # in the existing RSS feed.
    print("Initializing timestamps from existing live RSS.")

    response = SESSION.get(LIVE_FEED, timeout=25)
    response.raise_for_status()
    root = ET.fromstring(response.content)

    saved = {}

    for item in root.findall("./channel/item"):
        guid = item.findtext("guid")
        link = item.findtext("link")
        date = item.findtext("pubDate")

        url = link or guid

        if not url or not date:
            continue

        stamp = email.utils.parsedate_to_datetime(date)
        saved[url] = stamp.astimezone(
            dt.timezone.utc
        ).isoformat()

    # Protect existing posts against accidental restamping.
    if len(saved) < 18:
        raise RuntimeError(
            "Existing RSS baseline is incomplete. "
            "Refusing to restamp historical articles."
        )

    print("Preserved", len(saved), "existing timestamps.")
    return saved


def assign_discovery_timestamps(articles, saved):
    """Stamp newly discovered articles once, permanently."""
    now = dt.datetime.now(dt.timezone.utc)
    used = set(saved.values())
    new_count = 0

    for article in articles:
        url = article["url"]

        if url not in saved:
            stamp = now + dt.timedelta(seconds=new_count)

            while stamp.isoformat() in used:
                stamp += dt.timedelta(seconds=1)

            saved[url] = stamp.isoformat()
            used.add(saved[url])
            new_count += 1

            print("NEW:", article["title"][:90])

        article["date"] = dt.datetime.fromisoformat(
            saved[url]
        )

    print("New articles discovered:", new_count)
    return saved


def save_timestamps(saved):
    """Write timestamp history for GitHub Actions to commit."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(saved, f, indent=2, sort_keys=True)
        f.write("\n")

def build():
    print("Checking official Vegas Vanguards news...")
    soup = fetch(NEWS)
    urls = discover(soup)

    # Try the team homepage as a backup.
    if not urls:
        print("No news links found; checking homepage.")
        urls = discover(fetch(HOME))

    if not urls:
        if os.path.exists(OUT):
            print("No articles found. Existing RSS preserved.")
            return

        raise RuntimeError(
            "No official Vegas Vanguards articles found "
            "and no previous feed exists."
        )

    articles = []

    for url in urls:
        try:
            article = parse_article(url)
            articles.append(article)
            print("OK:", article["title"][:90])
        except Exception as exc:
            print("SKIP:", url, repr(exc))

        time.sleep(0.3)

    if not articles:
        if os.path.exists(OUT):
            print("Parsing failed. Existing RSS preserved.")
            return

        raise RuntimeError(
            "No articles parsed and no previous feed exists."
        )

    # Load permanent timestamps for existing articles.
    saved = load_timestamps()

    # Assign first-detected timestamps to new articles.
    saved = assign_discovery_timestamps(articles, saved)

    # Publish newest timestamps first.
    articles.sort(
        key=lambda article: article["date"],
        reverse=True,
    )


   

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    def add(parent, name, value):
        ET.SubElement(parent, name).text = value or ""

    add(
        channel,
        "title",
        "Vegas Vanguards | Official Team News",
    )
    add(channel, "link", NEWS)
    add(
        channel,
        "description",
        "Latest official Vegas Vanguards PWHL news",
    )
    add(channel, "language", "en-US")
    add(
        channel,
        "lastBuildDate",
        email.utils.format_datetime(
            dt.datetime.now(dt.timezone.utc),
            usegmt=True,
        ),
    )

    for article in articles:
        entry = ET.SubElement(channel, "item")

        add(entry, "title", article["title"])
        add(entry, "link", article["url"])

        guid = ET.SubElement(
            entry,
            "guid",
            {"isPermaLink": "true"},
        )
        guid.text = article["url"]

        add(
            entry,
            "pubDate",
            email.utils.format_datetime(article["date"]),
        )
        add(
            entry,
            "description",
            article["description"],
        )

        body = (
            "<p>" + escape(article["description"]) + "</p>"
            if article["description"]
            else ""
        )

        if article["image"]:
            ET.SubElement(
                entry,
                f"{{{NS_MEDIA}}}content",
                {
                    "url": article["image"],
                    "medium": "image",
                },
            )

            body = (
                '<p><img src="'
                + escape(article["image"], quote=True)
                + '" alt="" /></p>'
                + body
            )

        if body:
            ET.SubElement(
                entry,
                f"{{{NS_CONTENT}}}encoded",
            ).text = body

    os.makedirs(
        os.path.dirname(OUT),
        exist_ok=True,
    )

    ET.indent(rss, space="  ")

    ET.ElementTree(rss).write(
        OUT,
        encoding="utf-8",
        xml_declaration=True,
    )
    save_timestamps(saved)
    print(
        "Wrote",
        OUT,
        "articles:",
        len(articles),
        "with images:",
        sum(bool(a["image"]) for a in articles),
    )


if __name__ == "__main__":
    build()
