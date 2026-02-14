#!/usr/bin/env python3
"""
Build script for The Future Modern RSS aggregator.
Fetches all feeds from feeds.json and generates a static index.html.

Usage:
    python3 build.py
    python3 build.py --output docs/index.html
"""

import json
import sys
import os
import time
import html
import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_ITEMS = 200
FETCH_TIMEOUT = 30
USER_AGENT = "TheFutureModern/1.0 (+https://github.com/maxdavis3/the-future-modern)"


def load_feeds_config():
    config_path = os.path.join(SCRIPT_DIR, "feeds.json")
    with open(config_path, "r") as f:
        return json.load(f)


def fetch_feed(url):
    """Fetch and return raw XML text from a feed URL."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
            # Strip BOM if present
            if raw[:3] == b'\xef\xbb\xbf':
                raw = raw[3:]
            text = raw.decode("utf-8", errors="replace")
            # Strip leading whitespace before XML declaration
            text = text.lstrip()
            return text
    except (URLError, HTTPError) as e:
        print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
        return None


def parse_rss(xml_text, source_name, source_category):
    """Parse RSS 2.0 feed XML into a list of item dicts."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  XML parse error for {source_name}: {e}", file=sys.stderr)
        return items

    # RSS 2.0
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        desc = item.findtext("description", "").strip()
        pub_date_str = item.findtext("pubDate", "").strip()
        author = item.findtext("{http://purl.org/dc/elements/1.1/}creator", "").strip()
        if not author:
            author = item.findtext("author", "").strip()

        # Parse image from content:encoded, media:content, or enclosure
        image = ""
        media = item.find("{http://search.yahoo.com/mrss/}content")
        if media is not None:
            image = media.get("url", "")
        if not image:
            enclosure = item.find("enclosure")
            if enclosure is not None and "image" in enclosure.get("type", ""):
                image = enclosure.get("url", "")
        if not image:
            # Try to extract first image from content:encoded
            content = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", "")
            if content:
                img_start = content.find('<img')
                if img_start != -1:
                    src_start = content.find('src="', img_start)
                    if src_start != -1:
                        src_start += 5
                        src_end = content.find('"', src_start)
                        if src_end != -1:
                            image = content[src_start:src_end]

        pub_date = None
        if pub_date_str:
            try:
                pub_date = parsedate_to_datetime(pub_date_str)
            except (ValueError, TypeError):
                pass

        if title and link:
            items.append({
                "title": title,
                "link": link,
                "description": strip_html(desc)[:300],
                "date": pub_date,
                "source": source_name,
                "category": source_category,
                "author": author,
                "image": image,
            })

    return items


def parse_atom(xml_text, source_name, source_category):
    """Parse Atom feed XML into a list of item dicts."""
    items = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  XML parse error for {source_name}: {e}", file=sys.stderr)
        return items

    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", "", ns).strip()
        link_el = entry.find("atom:link[@rel='alternate']", ns)
        if link_el is None:
            link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""

        summary = entry.findtext("atom:summary", "", ns).strip()
        if not summary:
            content_el = entry.find("atom:content", ns)
            if content_el is not None and content_el.text:
                summary = content_el.text.strip()

        updated = entry.findtext("atom:updated", "", ns).strip()
        published = entry.findtext("atom:published", "", ns).strip()
        date_str = published or updated

        author_el = entry.find("atom:author/atom:name", ns)
        author = author_el.text.strip() if author_el is not None and author_el.text else ""

        pub_date = None
        if date_str:
            try:
                pub_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        if title and link:
            items.append({
                "title": title,
                "link": link,
                "description": strip_html(summary)[:300],
                "date": pub_date,
                "source": source_name,
                "category": source_category,
                "author": author,
                "image": "",
            })

    return items


def strip_html(text):
    """Remove HTML tags from a string."""
    result = []
    in_tag = False
    for ch in text:
        if ch == '<':
            in_tag = True
        elif ch == '>':
            in_tag = False
        elif not in_tag:
            result.append(ch)
    return html.unescape("".join(result)).strip()


def format_date(dt):
    """Format a datetime for display."""
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    diff = now - dt
    if diff.days == 0:
        hours = diff.seconds // 3600
        if hours == 0:
            mins = diff.seconds // 60
            return f"{mins}m ago" if mins > 0 else "just now"
        return f"{hours}h ago"
    elif diff.days == 1:
        return "yesterday"
    elif diff.days < 7:
        return f"{diff.days}d ago"
    else:
        return dt.strftime("%b %d, %Y")


def generate_color(name):
    """Generate a consistent muted color for a source name."""
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    hue = h % 360
    return f"hsl({hue}, 40%, 45%)"


def generate_html(config, items):
    """Generate the full index.html content."""
    title = config.get("title", "The Future Modern")
    description = config.get("description", "")
    sources = sorted(set(item["source"] for item in items))
    categories = sorted(set(item["category"] for item in items))
    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    items_html = []
    for item in items:
        date_str = format_date(item["date"])
        source_color = generate_color(item["source"])
        desc = html.escape(item["description"]) if item["description"] else ""

        image_html = ""
        if item["image"]:
            image_html = f'<div class="item-image"><img src="{html.escape(item["image"])}" alt="" loading="lazy" onerror="this.parentElement.remove()"></div>'

        author_html = ""
        if item["author"]:
            author_html = f'<span class="item-author">by {html.escape(item["author"])}</span>'

        items_html.append(f"""
        <article class="item" data-source="{html.escape(item["source"])}" data-category="{html.escape(item["category"])}">
            {image_html}
            <div class="item-content">
                <div class="item-meta">
                    <span class="item-source" style="color: {source_color}">{html.escape(item["source"])}</span>
                    <span class="item-date">{date_str}</span>
                </div>
                <h2 class="item-title"><a href="{html.escape(item["link"])}" target="_blank" rel="noopener">{html.escape(item["title"])}</a></h2>
                {"<p class='item-desc'>" + desc + "</p>" if desc else ""}
                {author_html}
            </div>
        </article>""")

    source_filters = "\n".join(
        f'            <button class="filter-btn" data-filter-source="{html.escape(s)}">{html.escape(s)}</button>'
        for s in sources
    )
    category_filters = "\n".join(
        f'            <button class="filter-btn" data-filter-category="{html.escape(c)}">{html.escape(c)}</button>'
        for c in categories
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <meta name="description" content="{html.escape(description)}">
    <style>
        :root {{
            --bg: #fafaf8;
            --text: #1a1a1a;
            --text-secondary: #666;
            --border: #e5e5e0;
            --surface: #fff;
            --hover: #f5f5f0;
            --accent: #2d2d2d;
        }}

        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg: #111;
                --text: #e8e8e3;
                --text-secondary: #999;
                --border: #2a2a2a;
                --surface: #1a1a1a;
                --hover: #222;
                --accent: #e8e8e3;
            }}
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
        }}

        .container {{
            max-width: 900px;
            margin: 0 auto;
            padding: 0 24px;
        }}

        header {{
            padding: 48px 0 32px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 8px;
        }}

        header h1 {{
            font-size: 28px;
            font-weight: 700;
            letter-spacing: -0.5px;
            color: var(--accent);
        }}

        header p {{
            font-size: 14px;
            color: var(--text-secondary);
            margin-top: 4px;
        }}

        .filters {{
            padding: 16px 0;
            border-bottom: 1px solid var(--border);
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            align-items: center;
        }}

        .filter-label {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-secondary);
            margin-right: 8px;
            font-weight: 600;
        }}

        .filter-btn {{
            background: none;
            border: 1px solid var(--border);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            cursor: pointer;
            color: var(--text-secondary);
            transition: all 0.15s;
            font-family: inherit;
        }}

        .filter-btn:hover {{
            border-color: var(--text);
            color: var(--text);
        }}

        .filter-btn.active {{
            background: var(--accent);
            color: var(--bg);
            border-color: var(--accent);
        }}

        .feed {{
            list-style: none;
        }}

        .item {{
            padding: 20px 0;
            border-bottom: 1px solid var(--border);
            display: flex;
            gap: 20px;
            transition: opacity 0.2s;
        }}

        .item.hidden {{
            display: none;
        }}

        .item-image {{
            flex-shrink: 0;
            width: 140px;
            height: 100px;
            border-radius: 6px;
            overflow: hidden;
            background: var(--hover);
        }}

        .item-image img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}

        .item-content {{
            flex: 1;
            min-width: 0;
        }}

        .item-meta {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 6px;
            font-size: 12px;
        }}

        .item-source {{
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-size: 11px;
        }}

        .item-date {{
            color: var(--text-secondary);
        }}

        .item-title {{
            font-size: 17px;
            font-weight: 600;
            line-height: 1.35;
            letter-spacing: -0.2px;
        }}

        .item-title a {{
            color: var(--text);
            text-decoration: none;
        }}

        .item-title a:hover {{
            text-decoration: underline;
        }}

        .item-desc {{
            font-size: 14px;
            color: var(--text-secondary);
            margin-top: 6px;
            line-height: 1.5;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}

        .item-author {{
            font-size: 12px;
            color: var(--text-secondary);
            margin-top: 4px;
            display: block;
        }}

        footer {{
            padding: 32px 0;
            text-align: center;
            font-size: 12px;
            color: var(--text-secondary);
            border-top: 1px solid var(--border);
            margin-top: 24px;
        }}

        @media (max-width: 640px) {{
            header {{ padding: 32px 0 24px; }}
            header h1 {{ font-size: 22px; }}
            .item {{ flex-direction: column; gap: 12px; }}
            .item-image {{ width: 100%; height: 180px; }}
            .item-title {{ font-size: 15px; }}
            .container {{ padding: 0 16px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{html.escape(title)}</h1>
            <p>{html.escape(description)}</p>
        </header>

        <div class="filters">
            <span class="filter-label">Filter</span>
            <button class="filter-btn active" data-filter-all>All</button>
{category_filters}
            <span class="filter-label" style="margin-left: 12px">Source</span>
{source_filters}
        </div>

        <div class="feed" id="feed">
{"".join(items_html)}
        </div>

        <footer>
            <p>Last updated: {build_time}</p>
            <p style="margin-top: 4px">{len(items)} items from {len(sources)} sources</p>
        </footer>
    </div>

    <script>
        document.addEventListener("DOMContentLoaded", function() {{
            const buttons = document.querySelectorAll(".filter-btn");
            const items = document.querySelectorAll(".item");
            let activeSource = null;
            let activeCategory = null;

            function applyFilters() {{
                items.forEach(item => {{
                    const matchSource = !activeSource || item.dataset.source === activeSource;
                    const matchCategory = !activeCategory || item.dataset.category === activeCategory;
                    item.classList.toggle("hidden", !(matchSource && matchCategory));
                }});
            }}

            buttons.forEach(btn => {{
                btn.addEventListener("click", function() {{
                    if (this.dataset.filterAll !== undefined) {{
                        activeSource = null;
                        activeCategory = null;
                        buttons.forEach(b => b.classList.remove("active"));
                        this.classList.add("active");
                    }} else if (this.dataset.filterSource) {{
                        const src = this.dataset.filterSource;
                        if (activeSource === src) {{
                            activeSource = null;
                            this.classList.remove("active");
                        }} else {{
                            buttons.forEach(b => {{ if (b.dataset.filterSource) b.classList.remove("active"); }});
                            activeSource = src;
                            this.classList.add("active");
                        }}
                        document.querySelector("[data-filter-all]").classList.toggle("active", !activeSource && !activeCategory);
                    }} else if (this.dataset.filterCategory) {{
                        const cat = this.dataset.filterCategory;
                        if (activeCategory === cat) {{
                            activeCategory = null;
                            this.classList.remove("active");
                        }} else {{
                            buttons.forEach(b => {{ if (b.dataset.filterCategory) b.classList.remove("active"); }});
                            activeCategory = cat;
                            this.classList.add("active");
                        }}
                        document.querySelector("[data-filter-all]").classList.toggle("active", !activeSource && !activeCategory);
                    }}
                    applyFilters();
                }});
            }});
        }});
    </script>
</body>
</html>"""


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build The Future Modern RSS aggregator")
    parser.add_argument("--output", default=os.path.join(SCRIPT_DIR, "index.html"),
                        help="Output HTML file path")
    args = parser.parse_args()

    config = load_feeds_config()
    all_items = []

    print(f"Fetching {len(config['feeds'])} feeds...")
    for feed in config["feeds"]:
        name = feed["name"]
        url = feed["url"]
        category = feed.get("category", "")
        print(f"  {name} ({url})...")

        xml_text = fetch_feed(url)
        if xml_text is None:
            continue

        # Detect feed type
        if "<feed" in xml_text[:500]:
            items = parse_atom(xml_text, name, category)
        else:
            items = parse_rss(xml_text, name, category)

        print(f"    -> {len(items)} items")
        all_items.extend(items)

        time.sleep(0.5)  # polite delay

    # Sort by date (newest first), items without dates go to end
    all_items.sort(key=lambda x: x["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    all_items = all_items[:MAX_ITEMS]

    print(f"\nTotal: {len(all_items)} items")

    html_content = generate_html(config, all_items)
    with open(args.output, "w") as f:
        f.write(html_content)
    print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
