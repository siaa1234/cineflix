import requests, json, re, base64
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://cinesubz.co"
API = f"{BASE}/wp-json/wp/v2/posts"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
    "Referer": BASE,
}

# ---------- 1) SEARCH ----------
def search(query, limit=10):
    r = requests.get(API, headers=HEADERS, params={
        "search": query, "per_page": limit, "_embed": 1
    }, timeout=30)
    r.raise_for_status()
    out = []
    for p in r.json():
        poster = ""
        try:
            poster = p["_embedded"]["wp:featuredmedia"][0]["source_url"]
        except (KeyError, IndexError):
            pass
        out.append({
            "id": p["id"],
            "title": p["title"]["rendered"],
            "url": p["link"],
            "poster": poster,
            "date": p["date"],
        })
    return out

# ---------- 2) DETAILS + POSTER ----------
def get_details(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    d = {"url": url}
    d["title"] = soup.select_one("h1").get_text(strip=True) if soup.select_one("h1") else ""

    # Yoast JSON-LD එකෙන් poster/description
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                  r.text, re.S)
    if m:
        try:
            ld = json.loads(m.group(1))
            graph = ld.get("@graph", [ld])
            for node in graph:
                if node.get("@type") == "Article":
                    d["description"] = node.get("description", "")
                    d["headline"] = node.get("headline", "")
        except Exception:
            pass
    og = soup.find("meta", property="og:image")
    d["poster"] = og["content"] if og else ""

    # movie metadata (year, IMDb, duration, quality වගේ) - theme එකේ spec boxes
    d["meta"] = {}
    for row in soup.select(".data, .spec, .mbx, .wp-block-post"):
        txt = row.get_text(" | ", strip=True)
        if txt and len(txt) < 500:
            d["meta"].setdefault("info", []).append(txt)

    # categories = language/genre
    cats = [a.get_text(strip=True) for a in
            soup.select('.categories a, .genre a, [rel="category tag"]')]
    d["categories"] = list(dict.fromkeys(cats))

    d["downloads"] = extract_downloads(r.text, soup)
    return d

# ---------- 3) DOWNLOAD LINKS ----------
def extract_downloads(html, soup):
    links = set()
    # a) plain links
    for a in soup.select("a[href]"):
        h = a["href"]
        if re.search(r"(pixeldrain|gofile|mega\.nz|1fichier|krakenfiles|download\.)", h):
            links.add(h)
    # b) base64-encoded links hidden in HTML/JS
    for enc in re.findall(r'"([A-Za-z0-9+/=]{60,})"', html):
        try:
            dec = base64.b64decode(enc).decode("utf-8", "ignore")
            if dec.startswith("http"):
                links.add(dec)
        except Exception:
            pass
    # c) page JS එකේ variable වල link patterns
    for m in re.findall(r'https?://[^\s"\'<>]+\.(?:mkv|mp4|zip|rar)[^\s"\'<>]*', html):
        links.add(m)
    return sorted(links)

# ---------- MAIN ----------
if __name__ == "__main__":
    result = {"scraped_at": datetime.utcnow().isoformat()}

    # search demo
    result["search"] = search("vikram")

    # search results වල පළවෙනි 3 ට details + downloads
    result["items"] = []
    for s in result["search"][:3]:
        try:
            result["items"].append(get_details(s["url"]))
        except Exception as e:
            result["items"].append({"url": s["url"], "error": str(e)})

    with open("cinesubz.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
