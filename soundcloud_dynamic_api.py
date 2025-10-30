import re
import requests
import json
import time
import os
from urllib.parse import quote_plus

CACHE_FILE = "soundcloud_cache.json"
CACHE_TTL = 60 * 60 * 24  # 24 hours cache validity (adjust if needed)


def load_cache():
    """Load existing cache if not expired."""
    if not os.path.exists(CACHE_FILE):
        return {}

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) < CACHE_TTL:
            return data
        else:
            return {}  # expired
    except Exception:
        return {}


def save_cache(client_id, app_version="1761662631", user_id=""):
    """Save cache with timestamp."""
    data = {
        "client_id": client_id,
        "app_version": app_version,
        "user_id": user_id,
        "timestamp": time.time(),
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def get_valid_client_id(force_refresh=False):
    """Return cached or freshly scraped client_id."""
    cache = load_cache()
    if not force_refresh and "client_id" in cache:
        print(f"[Cache] Using cached client_id: {cache['client_id']}")
        return cache["client_id"]

    print("[Fetch] Grabbing new client_id from SoundCloud...")
    page = requests.get("https://soundcloud.com/discover").text
    js_links = re.findall(r'https://a-v2\.sndcdn\.com/assets/[^"]+\.js', page)
    for js_url in js_links[:10]:
        js_code = requests.get(js_url).text
        match = re.search(r'client_id:"([a-zA-Z0-9]+)"', js_code)
        if match:
            client_id = match.group(1)
            save_cache(client_id)
            print(f"[Fetch] New client_id: {client_id}")
            return client_id
    raise RuntimeError("No valid client_id found. SoundCloud may have changed layout.")


def soundcloud_search(query, limit=20, offset=0):
    """Perform a SoundCloud search using cached client_id."""
    app_version = "1761662631"
    user_id = ""
    q = quote_plus(query)

    client_id = get_valid_client_id()

    url = (
        f"https://api-v2.soundcloud.com/search?q={q}&facet=model"
        f"&user_id={user_id}&client_id={client_id}"
        f"&limit={limit}&offset={offset}&linked_partitioning=1"
        f"&app_version={app_version}&app_locale=en"
    )
    print(f"[API] Fetching results for: '{query}'")

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    r = requests.get(url, headers=headers)

    # If 401, refresh client_id automatically
    if r.status_code == 401:
        print("[Warning] client_id expired. Refreshing...")
        client_id = get_valid_client_id(force_refresh=True)
        url = url.replace(client_id, client_id)
        r = requests.get(url, headers=headers)

    if r.status_code != 200:
        raise RuntimeError(f"Request failed ({r.status_code}): {r.text[:200]}")

    data = r.json()
    tracks = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "uploader": t.get("user", {}).get("username"),
            "url": t.get("permalink_url"),
            "duration_ms": t.get("duration"),
        }
        for t in data.get("collection", [])
        if "title" in t
    ]

    return tracks


if __name__ == "__main__":
    song=input("type to search SoundCloudtracks...")
    results = soundcloud_search(song)
    print(f"\nFound {len(results)} tracks:")
    for track in results[:5]:
        print(f"🎵 {track['title']} — {track['uploader']}")
        print(f"🔗 {track['url']}\n")
