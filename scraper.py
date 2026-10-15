import requests
import json
import re
import base64
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# ================= CONFIG =================
BASE = "https://cinesubz.co"
API = f"{BASE}/wp-json/wp/v2/posts"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,si;q=0.8",
    "Referer": BASE,
}
OUTPUT_FILE = "cinesubz.json"
SEARCH_QUERY = "vikram"   # search keyword
DETAILS_LIMIT = 3         # search results වලින් කීයක් details ගන්නද
# ===========================================


# ---------- 1) SEARCH ----------
def search(query, limit=10):
    """Search API - title, link, poster, date, categories"""
    r = requests.get(API, headers=HEADERS, params={
        "search": query,
        "per_page": limit,
        "_embed": 1,
    }, timeout=30)
    r.raise_for_status()
    out = []
    for p in r.json():
        poster = ""
        cats = []
        try:
            poster = p["_embedded"]["wp:featuredmedia"][0]["source_url"]
        except (KeyError, IndexError):
            pass
        try:
            cats = [c["name"] for c in p["_embedded"]["wp:term"][0]]
        except (KeyError, IndexError):
            pass
        out.append({
            "id": p["id"],
            "title": p["title"]["rendered"],
            "url": p["link"],
            "poster": poster,
            "date": p["date"],
            "categories": cats,
        })
    return out


# ---------- 2) LATEST MOVIES ----------
def get_latest(pages=1):
    """Latest posts - API pagination"""
    movies = []
    for page in range(1, pages + 1):
        r = requests.get(API, headers=HEADERS, params={
            "per_page": 50, "page": page, "_embed": 1,
            "orderby": "date", "order": "desc",
        }, timeout=30)
        if r.status_code == 400:
            break  # no more pages
        r.raise_for_status()
        for p in r.json():
            poster = ""
            try:
                poster = p["_embedded"]["wp:featuredmedia"][0]["source_url"]
            except (KeyError, IndexError):
                pass
            movies.append({
                "id": p["id"],
                "title": p["title"]["rendered"],
                "url": p["link"],
                "poster": poster,
                "date": p["date"],
            })
    return movies


# ---------- 3) DETAILS + POSTER + DOWNLOADS ----------
def get_details(url):
    """Movie/TV page eken details, poster, download links"""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    d = {"url": url}

    # Title
    h1 = soup.select_one("h1")
    d["title"] = h1.get_text(strip=True) if h1 else ""

    # Yoast JSON-LD (description + poster)
    d["description"] = ""
    d["poster"] = ""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            graph = ld.get("@graph", [ld])
            for node in graph:
                if not isinstance(node, dict):
                    continue
                if node.get("@type") == "Article" or node.get("headline"):
                    d["description"] = node.get("description", d["description"])
                if "image" in node:
                    img = node["image"]
                    if isinstance(img, list) and img:
                        img = img[0]
                    if isinstance(img, str):
                        d["poster"] = d["poster"] or img
                    elif isinstance(img, dict) and img.get("url"):
                        d["poster"] = d["poster"] or img["url"]
        except Exception:
            pass

    # og:image fallback
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        d["poster"] = d["poster"] or og["content"]

    # Categories / genre
    cats = [a.get_text(strip=True) for a in
            soup.select('[rel="category tag"], .genres a, .category a')]
    d["categories"] = list(dict.fromkeys(cats))

    # IMDb rating / year
    imdb = soup.select_one(".rating strong, .imdb strong, .dt_rating")
    if imdb:
        d["imdb"] = imdb.get_text(strip=True)
    year = soup.select_one(".release .date, .date")
    if year:
        d["year"] = year.get_text(strip=True)

    # Download links
    d["downloads"] = extract_downloads(html, soup)
    return d


# ---------- 4) DOWNLOAD LINK EXTRACTION ----------
def extract_downloads(html, soup):
    links = set()

    # a) file-host links in <a> tags
    hosts = (
        r"pixeldrain|gofile|mega\.nz|1fichier|krakenfiles|mediafire|"
        r"filelions|hubdrive|hubcloud|linkbox|terabox|filepress|gdtot|"
        r"drive\.google|streamtape|dood|mixdrop|filesd"
    )
    for a in soup.select("a[href]"):
        h = a.get("href", "")
        if re.search(hosts, h):
            links.add(h)

    # b) base64-encoded links hidden in HTML/JS
    for enc in re.findall(r'"([A-Za-z0-9+/=]{60,})"', html):
        try:
            dec = base64.b64decode(enc).decode("utf-8", "ignore")
            if dec.startswith("http"):
                links.add(dec)
        except Exception:
            pass

    # c) direct video/archive URLs in JS strings
    for m in re.findall(
        r'https?://[^\s"\'<>]+\.(?:mkv|mp4|zip|rar)[^\s"\'<>]*', html
    ):
        links.add(m)

    return sorted(links)


# ---------- 5) TV SERIES EPISODES ----------
def get_tv_episodes(tv_url):
    """TV series page eken episode list"""
    r = requests.get(tv_url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    episodes = []
    for a in soup.select("a[href*='/episode/'], a[href*='/tvshows/']"):
        title = a.get_text(strip=True)
        url = a["href"]
        if title and url not in [e["url"] for e in episodes]:
            episodes.append({"title": title, "url": url})
    return episodes


# ---------- MAIN ----------
if __name__ == "__main__":
    result = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source": BASE,
    }

    print("[*] Searching...")
    try:
        result["search"] = search(SEARCH_QUERY, limit=10)
        print(f"    Found {len(result['search'])} results")
    except Exception as e:
        result["search_error"] = str(e)
        print(f"    Search error: {e}")

    print("[*] Getting latest movies...")
    try:
        result["latest"] = get_latest(pages=1)
        print(f"    Got {len(result['latest'])} movies")
    except Exception as e:
        result["latest_error"] = str(e)
        print(f"    Latest error: {e}")

    result["items"] = []
    for s in result.get("search", [])[:DETAILS_LIMIT]:
        print(f"[*] Details: {s['title'][:60]}")
        try:
            result["items"].append(get_details(s["url"]))
        except Exception as e:
            result["items"].append({"url": s["url"], "error": str(e)})

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[+] Done! Output: {OUTPUT_FILE}")
