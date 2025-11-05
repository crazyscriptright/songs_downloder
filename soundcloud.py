import re
import requests
import json
import time
import os
from datetime import datetime, timedelta
from urllib.parse import quote_plus

CACHE_FILE = "music_api_cache.json"  # Unified cache file
CACHE_TTL = 60 * 60 * 2  # 2 hours cache validity


def load_cache():
    """Load existing cache if not expired."""
    if not os.path.exists(CACHE_FILE):
        return {}

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        # Get SoundCloud tokens from unified cache
        if 'soundcloud' not in cache_data:
            return {}
        
        sc_data = cache_data['soundcloud']
        
        # Check if cache is still valid
        if 'timestamp' in sc_data:
            cached_time = datetime.fromisoformat(sc_data['timestamp'])
            expiry_time = cached_time + timedelta(hours=2)
            
            if datetime.now() < expiry_time:
                time_left = expiry_time - datetime.now()
                hours, remainder = divmod(time_left.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                print(f"Using cached SoundCloud client_id (expires in {hours}h {minutes}m)")
                return sc_data
            else:
                return {}  # expired
        else:
            # Old format compatibility
            if time.time() - sc_data.get("timestamp_old", 0) < CACHE_TTL:
                return sc_data
            return {}
    except Exception:
        return {}


def save_cache(client_id, app_version="1761662631", user_id=""):
    """Save cache to unified cache file."""
    try:
        # Load existing cache to preserve other API tokens
        cache_data = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
            except:
                pass
        
        # Update SoundCloud tokens
        cache_data['soundcloud'] = {
            "client_id": client_id,
            "app_version": app_version,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
        }
        
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        
        print(f"SoundCloud client_id cached successfully (valid for 2 hours)")
        return cache_data['soundcloud']
    except Exception as e:
        print(f"Error saving cache: {e}")
        return {}


def get_valid_client_id(force_refresh=False):
    """Return cached or freshly scraped client_id."""
    cache = load_cache()
    if not force_refresh and "client_id" in cache:
        # Test if cached client_id still works
        test_url = f"https://api-v2.soundcloud.com/search?q=test&client_id={cache['client_id']}&limit=1"
        try:
            test_response = requests.get(test_url, timeout=5)
            if test_response.status_code == 200:
                print(f"Using valid cached client_id: {cache['client_id']}")
                return cache["client_id"]
            else:
                print(f"Cached client_id expired ({test_response.status_code}), refreshing...")
        except:
            print(f"Cached client_id test failed, refreshing...")

    print("[Fetch] Extracting new client_id from SoundCloud...")
    
    # Use the proven method first (most reliable)
    try:
        print("Using discover page method (most reliable)...")
        page = requests.get("https://soundcloud.com/discover", timeout=15).text
        js_links = re.findall(r'https://a-v2\.sndcdn\.com/assets/[^"]+\.js', page)
        print(f"Found {len(js_links)} JS files to check")
        
        for i, js_url in enumerate(js_links[:12]):  # Check up to 12 files
            try:
                print(f"   Checking JS {i+1}/{min(12, len(js_links))}: ...{js_url[-30:]}")
                js_response = requests.get(js_url, timeout=10)
                js_code = js_response.text
                
                # Try multiple patterns
                patterns = [
                    r'client_id:"([a-zA-Z0-9]{32})"',      # Most common
                    r'"client_id":"([a-zA-Z0-9]{32})"',    # Quoted version
                    r'client_id:"([a-zA-Z0-9_-]{32})"',   # With hyphens/underscores
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, js_code)
                    if match:
                        client_id = match.group(1)
                        print(f"Found potential client_id: {client_id}")
                        
                        # Test the client_id immediately
                        test_url = f"https://api-v2.soundcloud.com/search?q=test&client_id={client_id}&limit=1"
                        test_response = requests.get(test_url, timeout=8)
                        if test_response.status_code == 200:
                            save_cache(client_id)
                            print(f"Working client_id found: {client_id}")
                            return client_id
                        else:
                            print(f"   Client_id test failed: {test_response.status_code}")
                        
            except Exception as e:
                print(f"   JS {i+1} error: {str(e)[:40]}")
                continue
        
        print("No working client_id found in any JS files")
        raise RuntimeError("No valid client_id found in discover page JS files")
        
    except Exception as e:
        print(f"Discover page method failed: {e}")
        
        # Last resort: Try main page
        try:
            print("Trying main page as last resort...")
            page = requests.get("https://soundcloud.com/", timeout=15).text
            js_links = re.findall(r'https://a-v2\.sndcdn\.com/[^"]+\.js', page)
            
            for js_url in js_links[:5]:  # Only check first 5 from main page
                try:
                    js_code = requests.get(js_url, timeout=8).text
                    match = re.search(r'client_id:"([a-zA-Z0-9]{32})"', js_code)
                    if match:
                        client_id = match.group(1)
                        # Test it
                        test_url = f"https://api-v2.soundcloud.com/search?q=test&client_id={client_id}&limit=1"
                        test_response = requests.get(test_url, timeout=5)
                        if test_response.status_code == 200:
                            save_cache(client_id)
                            print(f"Working client_id from main page: {client_id}")
                            return client_id
                except:
                    continue
                    
            raise RuntimeError("All SoundCloud client_id extraction methods failed")
            
        except Exception as final_e:
            print(f"All methods failed: {final_e}")
            raise RuntimeError("SoundCloud client_id extraction completely failed")


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
            "artwork_url": t.get("artwork_url") or t.get("user", {}).get("avatar_url"),
            "playback_count": t.get("playback_count", 0),
            "likes_count": t.get("likes_count", 0),
            "genre": t.get("genre", ""),
            "description": t.get("description", ""),
        }
        for t in data.get("collection", [])
        if "title" in t
    ]

    return tracks


if __name__ == "__main__":
    song=input("type to search SoundCloudtracks: ")
    results = soundcloud_search(song)
    print(f"\nFound {len(results)} tracks:")
    for track in results[:5]:
        print(f"♪ {track['title']} — {track['uploader']}")
        print(f"URL: {track['url']}\n")
        print(f"Art: {track['artwork_url']}\n")

