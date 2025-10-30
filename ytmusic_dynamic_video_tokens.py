import requests
import json
import time
import re
import os
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class YouTubeMusicVideoAPI:
    def __init__(self, cache_file="music_api_cache.json", cache_duration_hours=2, headless=True):
        self.driver = None
        self.api_key = None
        self.context = None
        self.base_url = "https://music.youtube.com"
        self.cache_file = cache_file
        self.cache_duration_hours = cache_duration_hours
        self.cached_tokens = None
        self.headless = headless
    
    def load_cache(self):
        """Load tokens from cache file if valid"""
        try:
            if not os.path.exists(self.cache_file):
                print("📂 No cache file found")
                return None
            
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # Get YouTube Music video tokens from unified cache
            if 'ytmusic_videos' not in cache_data:
                return None
            
            tokens_data = cache_data['ytmusic_videos']
            
            # Check if cache is still valid
            cached_time = datetime.fromisoformat(tokens_data['timestamp'])
            expiry_time = cached_time + timedelta(hours=self.cache_duration_hours)
            
            if datetime.now() < expiry_time:
                time_left = expiry_time - datetime.now()
                hours, remainder = divmod(time_left.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                print(f"✅ Using cached YT Music video tokens (expires in {hours}h {minutes}m)")
                return tokens_data['tokens']
            else:
                print(f"⏰ Cache expired (was {self.cache_duration_hours} hours old)")
                return None
                
        except Exception as e:
            print(f"⚠️ Error loading cache: {e}")
            return None
    
    def save_cache(self, tokens):
        """Save tokens to unified cache file"""
        try:
            # Load existing cache to preserve other API tokens
            cache_data = {}
            if os.path.exists(self.cache_file):
                try:
                    with open(self.cache_file, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                except:
                    pass
            
            # Update YouTube Music video tokens
            cache_data['ytmusic_videos'] = {
                'timestamp': datetime.now().isoformat(),
                'tokens': tokens
            }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            print(f"💾 YT Music video tokens cached successfully (valid for {self.cache_duration_hours} hours)")
            
        except Exception as e:
            print(f"⚠️ Error saving cache: {e}")
    
    def get_tokens(self, search_query="", force_refresh=False):
        """Get tokens from cache or fetch fresh ones"""
        
        # Try to use cached tokens first
        if not force_refresh:
            cached_tokens = self.load_cache()
            if cached_tokens:
                self.cached_tokens = cached_tokens
                return cached_tokens
        
        # If no valid cache or force refresh, extract fresh tokens
        print("🔄 Fetching fresh tokens...")
        fresh_tokens = self.extract_tokens_from_page(search_query)
        
        # Save to cache
        self.save_cache(fresh_tokens)
        self.cached_tokens = fresh_tokens
        
        return fresh_tokens
        
    def extract_tokens_from_page(self, search_query=""):
        """Extract fresh tokens from YouTube Music page"""
        print(f"🔄 Starting browser {'(headless)' if self.headless else '(visible)'} to extract fresh tokens...")
        
        # Configure Chrome options for headless mode
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        self.driver = webdriver.Chrome(options=chrome_options)
        
        # Visit YouTube Music search page
        search_url = f"{self.base_url}/search?q={search_query.replace(' ', '+')}" if search_query else self.base_url
        self.driver.get(search_url)
        
        # Wait for page to load
        time.sleep(3)
        
        # Extract tokens from JavaScript
        script = """
        return {
            visitorData: window.ytcfg?.data_?.VISITOR_DATA,
            apiKey: window.ytcfg?.data_?.INNERTUBE_API_KEY,
            clientVersion: window.ytcfg?.data_?.INNERTUBE_CONTEXT_CLIENT_VERSION,
            context: window.ytcfg?.data_?.INNERTUBE_CONTEXT
        };
        """
        
        visitor_data = None
        api_key = None
        client_version = None
        
        try:
            config_data = self.driver.execute_script(script)
            visitor_data = config_data.get('visitorData')
            api_key = config_data.get('apiKey')
            client_version = config_data.get('clientVersion')
            
            print(f"✓ Visitor Data: {visitor_data}")
            print(f"✓ API Key: {api_key}")
            print(f"✓ Client Version: {client_version}")
            
        except Exception as e:
            print(f"⚠ Error extracting from JavaScript: {e}")
        
        self.api_key = api_key
        self.visitor_data = visitor_data
        self.client_version = client_version
        
        self.driver.quit()
        
        return {
            'visitor_data': visitor_data,
            'api_key': api_key,
            'client_version': client_version
        }
    
    def build_context(self, visitor_data=None, client_version=None):
        """Build the context object with fresh or default tokens"""
        import time
        
        current_timestamp = str(int(time.time() * 1000))
        
        return {
            "client": {
                "hl": "en",
                "gl": "IN",
                "clientName": "WEB_REMIX",
                "clientVersion": client_version or "1.20251022.00.01",
                "visitorData": visitor_data or "",
                "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "osName": "Windows",
                "osVersion": "10.0",
                "platform": "DESKTOP",
                "clientFormFactor": "UNKNOWN_FORM_FACTOR",
                "userInterfaceTheme": "USER_INTERFACE_THEME_DARK",
                "timeZone": "Asia/Calcutta",
                "browserName": "Chrome",
                "browserVersion": "131.0.0.0",
                "screenWidthPoints": 1920,
                "screenHeightPoints": 1080,
                "screenPixelDensity": 1,
                "screenDensityFloat": 1,
                "utcOffsetMinutes": 330
            },
            "user": {
                "lockedSafetyMode": False
            },
            "request": {
                "useSsl": True,
                "internalExperimentFlags": [],
                "consistencyTokenJars": []
            },
            "adSignalsInfo": {
                "params": [
                    {"key": "dt", "value": current_timestamp},
                    {"key": "flash", "value": "0"},
                    {"key": "frm", "value": "0"},
                    {"key": "u_tz", "value": "330"},
                    {"key": "u_his", "value": "2"},
                    {"key": "u_h", "value": "1080"},
                    {"key": "u_w", "value": "1920"},
                    {"key": "u_ah", "value": "1040"},
                    {"key": "u_aw", "value": "1920"},
                    {"key": "u_cd", "value": "24"},
                    {"key": "bc", "value": "31"},
                    {"key": "bih", "value": "937"},
                    {"key": "biw", "value": "1903"},
                    {"key": "brdim", "value": "0,0,0,0,1920,0,1920,1040,1920,937"},
                    {"key": "vis", "value": "1"},
                    {"key": "wgl", "value": "true"},
                    {"key": "ca_type", "value": "image"}
                ]
            }
        }
    
    def search_videos(self, query, use_fresh_tokens=True, retry_on_error=True):
        """Search for videos on YouTube Music with caching and auto-retry"""
        
        # Get tokens (from cache or fresh)
        tokens = self.get_tokens(query, force_refresh=not use_fresh_tokens)
        
        # Build URL with API key if available
        if tokens.get('api_key'):
            url = f"https://music.youtube.com/youtubei/v1/search?key={tokens['api_key']}&prettyPrint=false"
        else:
            url = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false"
        
        # Build headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Origin": "https://music.youtube.com",
            "Referer": f"https://music.youtube.com/search?q={query.replace(' ', '+')}"
        }
        
        # Build payload for VIDEO search (different params than songs)
        payload = {
            "context": self.build_context(
                visitor_data=tokens.get('visitor_data'),
                client_version=tokens.get('client_version')
            ),
            "query": query,
            "params": "EgWKAQIQAWoQEAQQAxAJEAUQChAVEBAQEQ%3D%3D"  # Video filter params
        }
        
        print(f"\n🎥 Searching for videos: {query}")
        print(f"📡 URL: {url}")
        
        # Send request
        response = requests.post(url, headers=headers, json=payload)
        
        print(f"📊 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text[:500])
            
            # If error occurs and retry is enabled, try with fresh tokens
            if retry_on_error and use_fresh_tokens:
                print("\n🔄 Retrying with fresh tokens...")
                fresh_tokens = self.get_tokens(query, force_refresh=True)
                
                # Update URL with fresh API key
                if fresh_tokens.get('api_key'):
                    url = f"https://music.youtube.com/youtubei/v1/search?key={fresh_tokens['api_key']}&prettyPrint=false"
                
                # Update payload with fresh tokens
                payload["context"] = self.build_context(
                    visitor_data=fresh_tokens.get('visitor_data'),
                    client_version=fresh_tokens.get('client_version')
                )
                
                # Retry request
                response = requests.post(url, headers=headers, json=payload)
                print(f"📊 Retry Status Code: {response.status_code}")
                
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"❌ Retry failed: {response.status_code}")
                    print(response.text[:500])
            
            return None
    
    def parse_video_results(self, data):
        """Parse and display video search results"""
        if not data:
            return []
        
        videos = []
        
        try:
            contents = data["contents"]["tabbedSearchResultsRenderer"]["tabs"][0]["tabRenderer"]["content"]["sectionListRenderer"]["contents"]
            
            for section in contents:
                if "musicShelfRenderer" in section:
                    shelf = section["musicShelfRenderer"]
                    
                    # Get section title
                    title = shelf["title"]["runs"][0]["text"]
                    
                    if title.lower() == "videos":
                        print(f"\n{'='*60}")
                        print(f"🎥 {title}")
                        print(f"{'='*60}\n")
                        
                        # Get videos
                        for item in shelf.get("contents", []):
                            if "musicResponsiveListItemRenderer" in item:
                                renderer = item["musicResponsiveListItemRenderer"]
                                
                                # Extract video info
                                video_title = renderer["flexColumns"][0]["musicResponsiveListItemFlexColumnRenderer"]["text"]["runs"][0]["text"]
                                video_id = renderer["playlistItemData"]["videoId"]
                                thumbnail = renderer["thumbnail"]["musicThumbnailRenderer"]["thumbnail"]["thumbnails"][-1]["url"]
                                
                                # Metadata
                                metadata_runs = renderer["flexColumns"][1]["musicResponsiveListItemFlexColumnRenderer"]["text"]["runs"]
                                metadata = "".join([run["text"] for run in metadata_runs])
                                
                                video_info = {
                                    'title': video_title,
                                    'video_id': video_id,
                                    'url': f"https://music.youtube.com/watch?v={video_id}",
                                    'youtube_url': f"https://www.youtube.com/watch?v={video_id}",
                                    'thumbnail': thumbnail,
                                    'metadata': metadata
                                }
                                
                                videos.append(video_info)
                                
                                print(f"🎥 {video_title}")
                                print(f"   📺 Video ID: {video_id}")
                                print(f"   🔗 YT Music: https://music.youtube.com/watch?v={video_id}")
                                print(f"   🔗 YouTube: https://www.youtube.com/watch?v={video_id}")
                                print(f"   ℹ️  {metadata}")
                                print(f"   🖼️  Thumbnail: {thumbnail}")
                                print("-" * 60)
                        
                        break
        except Exception as e:
            print(f"❌ Error parsing results: {e}")
        
        return videos


# Example usage
if __name__ == "__main__":
    # Initialize API with 2-hour cache duration
    api = YouTubeMusicVideoAPI(cache_duration_hours=2)
    
    # Search - will use cache if available, or fetch fresh tokens
    search_query = "follow follow song"
    results = api.search_videos(search_query, use_fresh_tokens=True)
    
    if results:
        videos = api.parse_video_results(results)
        print(f"\n✓ Found {len(videos)} videos")
        
        # Save results
        with open("video_search_results.json", "w", encoding="utf-8") as f:
            json.dump(videos, f, indent=2, ensure_ascii=False)
        print("✓ Results saved to video_search_results.json")
    
    # Example: Search again - will use cached tokens
    print("\n" + "="*60)
    print("🔁 Searching again (should use cache)...")
    print("="*60)
    
    results2 = api.search_videos("another video", use_fresh_tokens=True)
    if results2:
        videos2 = api.parse_video_results(results2)
        print(f"\n✓ Found {len(videos2)} videos")
