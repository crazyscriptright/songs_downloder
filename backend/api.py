"""
Universal Music Downloader - Flask Web Interface
"""

from flask import Flask, render_template, request, jsonify, send_file
import threading
import os
import json
import re
from datetime import datetime
import requests
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

try:
    from ytmusic_dynamic_tokens import YouTubeMusicAPI
    from ytmusic_dynamic_video_tokens import YouTubeMusicVideoAPI
    from jiosaavn_search import JioSaavnAPI
    import soundcloud
    from bs4 import BeautifulSoup  # Add BeautifulSoup for JioSaavn URL extraction
except ImportError as e:
    print(f"⚠ Import Error: {e}")
    print("Make sure all required modules are in the same directory!")

app = Flask(__name__)
# Enable CORS for frontend
from flask_cors import CORS
CORS(app, resources={r"/*": {"origins": "*"}})

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Use /tmp for Heroku (ephemeral storage)
if os.getenv('DYNO'):  # Running on Heroku
    app.config['DOWNLOAD_FOLDER'] = '/tmp/downloads'
else:
    app.config['DOWNLOAD_FOLDER'] = os.path.join(os.path.expanduser("~"), "Downloads", "Music")

os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)


def cleanup_tmp_directory():
    """Clean up /tmp directory when it's getting full (Heroku has limited space)"""
    if not os.getenv('DYNO'):
        return  # Only run on Heroku
    
    try:
        tmp_dir = '/tmp'
        
        # Get disk usage
        import shutil
        total, used, free = shutil.disk_usage(tmp_dir)
        usage_percent = (used / total) * 100
        
        # If more than 80% full, clean up
        if usage_percent > 80:
            print(f"⚠️ /tmp is {usage_percent:.1f}% full, cleaning up...")
            
            # Get all files in /tmp (excluding .json files)
            files_to_delete = []
            for root, dirs, files in os.walk(tmp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Keep .json cache files, delete everything else
                    if not file.endswith('.json'):
                        try:
                            files_to_delete.append(file_path)
                        except:
                            pass
            
            # Sort by modification time (oldest first)
            files_to_delete.sort(key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0)
            
            # Delete old files
            deleted_count = 0
            for file_path in files_to_delete:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        deleted_count += 1
                except Exception as e:
                    pass
            
            print(f"✅ Cleaned up {deleted_count} old files from /tmp")
            
            # Check new usage
            total, used, free = shutil.disk_usage(tmp_dir)
            new_usage = (used / total) * 100
            print(f"📊 /tmp usage: {new_usage:.1f}% (freed {usage_percent - new_usage:.1f}%)")
    
    except Exception as e:
        print(f"⚠️ Error cleaning /tmp: {e}")


ytmusic_api = None
ytvideo_api = None
jiosaavn_api = None

search_results = {}
download_status = {}
active_processes = {}

# Use /tmp for cache files on Heroku (ephemeral storage)
if os.getenv('DYNO'):  # Running on Heroku
    CACHE_DIR = '/tmp'
else:
    CACHE_DIR = '.'

UNIFIED_CACHE_FILE = os.path.join(CACHE_DIR, "music_api_cache.json")
DOWNLOAD_QUEUE_FILE = os.path.join(CACHE_DIR, "download_queue.json")
DOWNLOAD_STATUS_FILE = os.path.join(CACHE_DIR, "download_status.json")


def get_apis():
    """Initialize APIs with unified cache and headless mode"""
    global ytmusic_api, ytvideo_api, jiosaavn_api
    
    # Always use headless mode (required for Heroku, good for local too)
    headless_mode = True
    
    if not ytmusic_api:
        ytmusic_api = YouTubeMusicAPI(
            cache_file=UNIFIED_CACHE_FILE,
            cache_duration_hours=2,
            headless=headless_mode
        )
    if not ytvideo_api:
        ytvideo_api = YouTubeMusicVideoAPI(
            cache_file=UNIFIED_CACHE_FILE,
            cache_duration_hours=2,
            headless=headless_mode
        )
    if not jiosaavn_api:
        jiosaavn_api = JioSaavnAPI()
    
    return ytmusic_api, ytvideo_api, jiosaavn_api


def load_persistent_data():
    """Load download status if available (from /tmp on Heroku)"""
    global download_status
    try:
        if os.path.exists(DOWNLOAD_STATUS_FILE):
            with open(DOWNLOAD_STATUS_FILE, 'r') as f:
                download_status = json.load(f)
            print(f"✅ Loaded {len(download_status)} download records")
    except (IOError, OSError, json.JSONDecodeError) as e:
        print(f"⚠ Could not load download status: {e}")
        download_status = {}


def save_download_status():
    """Save download status (only in /tmp on Heroku)"""
    try:
        with open(DOWNLOAD_STATUS_FILE, 'w') as f:
            json.dump(download_status, f, indent=2)
    except (IOError, OSError, PermissionError) as e:
        # Read-only filesystem - skip saving
        print(f"Warning: Could not save download status: {e}")
        pass


def cleanup_old_downloads():
    """Clean up old downloads"""
    try:
        current_time = datetime.now()
        to_remove = []
        
        for download_id, status in download_status.items():
            if 'timestamp' in status:
                download_time = datetime.fromisoformat(status['timestamp'])
                if (current_time - download_time).total_seconds() > 86400:
                    if status.get('status') in ['complete', 'error', 'cancelled']:
                        to_remove.append(download_id)
        
        for download_id in to_remove:
            del download_status[download_id]
        
        if to_remove:
            save_download_status()
    
    except Exception as e:
        print(f"Warning: Could not cleanup old downloads: {e}")


def search_ytmusic(query):
    """Search YouTube Music"""
    results = []
    try:
        ytmusic, _, _ = get_apis()
        data = ytmusic.search(query, use_fresh_tokens=True, retry_on_error=True)
        songs = ytmusic.parse_search_results(data) if data else []
        
        for song in songs:
            results.append({
                'title': song['title'],
                'artist': song['metadata'],
                'source': 'YouTube Music',
                'url': song['url'],
                'video_id': song['video_id'],
                'thumbnail': song.get('thumbnail', f"https://img.youtube.com/vi/{song['video_id']}/mqdefault.jpg"),
                'type': 'song'
            })
    except Exception as e:
        print(f"YT Music error: {e}")
    
    return results


def search_ytvideo(query):
    """Search YouTube Music for videos"""
    results = []
    try:
        _, ytvideo, _ = get_apis()
        
        data = ytvideo.search_videos(query, use_fresh_tokens=True, retry_on_error=True)
        
        videos = ytvideo.parse_video_results(data) if data else []
        
        for video in videos:
            results.append({
                'title': video['title'],
                'artist': video['metadata'],
                'source': 'YouTube Video',
                'url': video['url'],
                'video_id': video['video_id'],
                'thumbnail': video.get('thumbnail', f"https://img.youtube.com/vi/{video['video_id']}/mqdefault.jpg"),
                'type': 'video'
            })
    except Exception as e:
        print(f"YT Video error: {e}")
    
    return results


def extract_soundcloud_metadata_with_recommendations(soundcloud_url):
    """Extract metadata from SoundCloud URL including main track and recommendations"""
    print(f"🎯 Starting SoundCloud extraction for: {soundcloud_url}")
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        
        # Convert desktop URL to mobile URL for better compatibility
        if soundcloud_url.startswith("https://soundcloud.com/"):
            mobile_url = soundcloud_url.replace("https://soundcloud.com/", "https://m.soundcloud.com/")
            url = mobile_url
            print(f"📱 Converted to mobile URL: {url}")
        else:
            url = soundcloud_url
        
        print(f"🌐 Making request to: {url}")
        response = requests.get(url, headers=headers, timeout=10)
        print(f"📡 Response status: {response.status_code}")
        if response.status_code != 200:
            print(f"❌ Bad response status: {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find script tags containing tracks data
        tracks_scripts = []
        for i, script in enumerate(soup.find_all("script")):
            if script.string and '"tracks":' in script.string:
                tracks_scripts.append((i, script))
        
        if tracks_scripts:
            # Sort by script length and pick the largest one
            tracks_scripts.sort(key=lambda x: len(x[1].string), reverse=True)
            script_index, script_tag = tracks_scripts[0]
        else:
            # Fallback: look for large scripts
            script_tag = None
            for script in soup.find_all("script"):
                if script.string and len(script.string) > 50000:
                    script_content = script.string.lower()
                    if any(keyword in script_content for keyword in ['soundcloud', 'track', 'audio']):
                        script_tag = script
                        break
        
        if not script_tag:
            return None
        
        # Parse JSON data
        try:
            data = json.loads(script_tag.string)
            
            # Try different structures for tracks data
            tracks_data = None
            users_data = None  # Add users data for artist name lookup
            
            # Method 1: Mobile/new structure
            initial_store = data.get("props", {}).get("pageProps", {}).get("initialStoreState", {})
            entities = initial_store.get("entities", {})
            if entities and "tracks" in entities:
                tracks_data = entities.get("tracks", {})
                users_data = entities.get("users", {})  # Get users data too
                print("Found tracks using mobile/new structure")
            
            # Method 2: Direct tracks access
            elif "tracks" in data:
                tracks_data = data.get("tracks", {})
                users_data = data.get("users", {})  # Try to get users too
                print("Found tracks using direct access")
            
            # Method 3: Recursive search
            else:
                def find_tracks_recursive(obj):
                    if isinstance(obj, dict):
                        if "tracks" in obj and isinstance(obj["tracks"], dict):
                            tracks_obj = obj["tracks"]
                            if any(key.startswith("soundcloud:tracks") for key in tracks_obj.keys()):
                                return tracks_obj
                        for value in obj.values():
                            result = find_tracks_recursive(value)
                            if result:
                                return result
                    elif isinstance(obj, list):
                        for item in obj:
                            result = find_tracks_recursive(item)
                            if result:
                                return result
                    return None
                
                tracks_data = find_tracks_recursive(data)
            
            if not tracks_data:
                return None
            
            # Extract SoundCloud tracks
            soundcloud_tracks = []
            for key, value in tracks_data.items():
                if key.startswith("soundcloud:tracks"):
                    track_data = value.get("data", {})
                    
                    # Debug track data structure
                    print(f"🔍 Processing track: {key}")
                    print(f"📊 Track data keys: {list(track_data.keys())}")
                    
                    # Format duration
                    duration_ms = track_data.get('duration', 0)
                    duration_str = "0:00"
                    if duration_ms:
                        minutes = duration_ms // 60000
                        seconds = (duration_ms % 60000) // 1000
                        duration_str = f"{minutes}:{seconds:02d}"
                    
                    # Format counts
                    plays = track_data.get('playback_count', 0)
                    likes = track_data.get('likes_count', 0)                    # Extract artist name - try multiple fields
                    artist_name = "Unknown Artist"
                    
                    # First try direct user field
                    if 'user' in track_data and isinstance(track_data['user'], dict):
                        artist_name = track_data['user'].get('username', 'Unknown Artist')
                        print(f"👤 Found user.username: {artist_name}")
                    elif 'uploader' in track_data:
                        artist_name = track_data['uploader']
                        print(f"👤 Found uploader: {artist_name}")
                    elif 'artist' in track_data:
                        artist_name = track_data['artist']
                        print(f"👤 Found artist: {artist_name}")
                    else:
                        # Try to find user via user_id lookup in users_data
                        user_id = track_data.get('user_id')
                        if user_id and users_data:
                            print(f"💳 Found user_id: {user_id}, looking up in users data...")
                            
                            # Look for user in users_data by user_id
                            user_key = f"soundcloud:users:{user_id}"
                            if user_key in users_data:
                                user_info = users_data[user_key].get('data', {})
                                artist_name = user_info.get('username', user_info.get('display_name', 'Unknown Artist'))
                                print(f"✅ Found artist via user lookup: {artist_name}")
                            else:
                                # Try direct user_id lookup
                                for key, user_data in users_data.items():
                                    if key.startswith("soundcloud:users:"):
                                        user_info = user_data.get('data', {})
                                        if user_info.get('id') == user_id:
                                            artist_name = user_info.get('username', user_info.get('display_name', 'Unknown Artist'))
                                            print(f"✅ Found artist via ID match: {artist_name}")
                                            break
                                
                                if artist_name == "Unknown Artist":
                                    print(f"❌ Could not find user {user_id} in users data")
                                    print(f"🔍 Available user keys: {list(users_data.keys())[:5] if users_data else 'None'}")
                        elif user_id:
                            print(f"💳 Found user_id: {user_id} but no users_data available")
                        else:
                            print("❌ No user_id found in track data")
                    
                    print(f"🎤 Final Artist: {artist_name}")
                    print(f"🎵 Title: {track_data.get('title', 'Unknown')}")
                    
                    soundcloud_tracks.append({
                        'id': key,
                        'title': track_data.get('title', 'Unknown'),
                        'artist': artist_name,
                        'url': track_data.get('permalink_url', soundcloud_url),
                        'thumbnail': track_data.get('artwork_url', ''),
                        'duration': duration_str,
                        'plays': plays,
                        'likes': likes,
                        'genre': track_data.get('genre', ''),
                        'created_at': track_data.get('created_at', ''),
                        'source': 'SoundCloud'
                    })
            
            if soundcloud_tracks:
                return {
                    'main_track': soundcloud_tracks[0] if soundcloud_tracks else None,
                    'recommended_tracks': soundcloud_tracks[1:] if len(soundcloud_tracks) > 1 else [],
                    'total_tracks': len(soundcloud_tracks)
                }
            
        except json.JSONDecodeError:
            return None
        except Exception:
            return None
            
    except Exception as e:
        print(f"SoundCloud metadata extraction error: {e}")
        return None


def extract_jiosaavn_metadata(jiosaavn_url):
    """Extract metadata from JioSaavn URL using web scraping"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        response = requests.get(jiosaavn_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        metadata = {}
        
        # Extract image source
        img_element = soup.find("img", {"id": "songHeaderImage"})
        if img_element:
            metadata['thumbnail'] = img_element.get("src")
        
        # Extract song title
        song_title_element = soup.find("h1", class_="u-h2 u-margin-bottom-tiny@sm")
        if song_title_element:
            song_title = song_title_element.get_text(strip=True)
            # Remove "Lyrics" suffix if present
            if song_title.endswith("Lyrics"):
                song_title = song_title[:-6].strip()
            metadata['title'] = song_title
        
        # Extract album name and artists
        album_para = soup.find("p", class_="u-color-js-gray u-ellipsis@lg u-margin-bottom-tiny@sm")
        if album_para:
            # Extract album
            album_link = album_para.find("a", {"screen_name": "song_screen", "href": lambda x: x and "/album/" in x})
            if album_link:
                metadata['album'] = album_link.get_text(strip=True)
            
            # Extract artists
            artist_links = album_para.find_all("a", {"screen_name": "song_screen", "href": lambda x: x and "/artist/" in x})
            artists = []
            for link in artist_links:
                artist_name = link.get_text(strip=True)
                if artist_name:
                    artists.append(artist_name)
            
            if artists:
                metadata['artist'] = ", ".join(artists)
        
        # Extract PID from page content
        pid_value = None
        
        # Method 1: Search in script tags for JSON containing "pid"
        script_tags = soup.find_all("script")
        for script in script_tags:
            if script.string and '"pid"' in script.string:
                try:
                    # Try to find PID using regex pattern
                    pid_match = re.search(r'"pid"\s*:\s*"([^"]+)"', script.string)
                    if pid_match:
                        pid_value = pid_match.group(1)
                        break
                    else:
                        # Try to find PID with single quotes
                        pid_match = re.search(r"'pid'\s*:\s*'([^']+)'", script.string)
                        if pid_match:
                            pid_value = pid_match.group(1)
                            break
                except Exception:
                    continue
        
        # Method 2: Search in the entire page source if not found in scripts
        if not pid_value:
            page_content = response.text
            pid_match = re.search(r'"pid"\s*:\s*"([^"]+)"', page_content)
            if pid_match:
                pid_value = pid_match.group(1)
            else:
                # Try with single quotes
                pid_match = re.search(r"'pid'\s*:\s*'([^']+)'", page_content)
                if pid_match:
                    pid_value = pid_match.group(1)
        
        if pid_value:
            metadata['pid'] = pid_value
        
        # Extract language from page content
        language_value = None
        
        # Method 1: Search in script tags for JSON containing "language"
        for script in script_tags:
            if script.string and '"language"' in script.string:
                try:
                    # Try to find language using regex pattern
                    language_match = re.search(r'"language"\s*:\s*"([^"]+)"', script.string)
                    if language_match:
                        language_value = language_match.group(1)
                        break
                    else:
                        # Try to find language with single quotes
                        language_match = re.search(r"'language'\s*:\s*'([^']+)'", script.string)
                        if language_match:
                            language_value = language_match.group(1)
                            break
                except Exception:
                    continue
        
        # Method 2: Search in the entire page source if not found in scripts
        if not language_value:
            page_content = response.text
            language_match = re.search(r'"language"\s*:\s*"([^"]+)"', page_content)
            if language_match:
                language_value = language_match.group(1)
            else:
                # Try with single quotes
                language_match = re.search(r"'language'\s*:\s*'([^']+)'", page_content)
                if language_match:
                    language_value = language_match.group(1)
        
        # Method 3: Extract from URL structure (fallback)
        if not language_value:
            # Look for language indicators in URL or page structure
            if 'english' in jiosaavn_url.lower() or 'english' in response.text.lower():
                language_value = 'english'
            elif 'hindi' in jiosaavn_url.lower() or 'hindi' in response.text.lower():
                language_value = 'hindi'
            elif 'tamil' in jiosaavn_url.lower() or 'tamil' in response.text.lower():
                language_value = 'tamil'
            elif 'telugu' in jiosaavn_url.lower() or 'telugu' in response.text.lower():
                language_value = 'telugu'
            elif 'punjabi' in jiosaavn_url.lower() or 'punjabi' in response.text.lower():
                language_value = 'punjabi'
        
        if language_value:
            metadata['language'] = language_value
        else:
            # Default fallback if no language detected
            metadata['language'] = 'hindi'  # Most common on JioSaavn
        
        return metadata
        
    except Exception as e:
        print(f"JioSaavn metadata extraction error: {e}")
        return None


def search_jiosaavn(query):
    """Search JioSaavn"""
    results = []
    try:
        _, _, jiosaavn = get_apis()
        
        data = jiosaavn.search_songs(query)
        songs = jiosaavn.parse_results(data) if data else []
        
        for song in songs:
            artist = (
                song.get('primary_artists') or 
                song.get('singers') or 
                song.get('subtitle', '').split(' - ')[0] if ' - ' in song.get('subtitle', '') else
                'Unknown Artist'
            )
            
            results.append({
                'title': song['title'],
                'artist': artist,
                'subtitle': song.get('subtitle', ''),
                'source': 'JioSaavn',
                'url': song['perma_url'],
                'song_id': song['id'],
                'thumbnail': song.get('image', ''),
                'year': song.get('year', ''),
                'language': song.get('language', ''),
                'play_count': song.get('play_count', ''),
                'type': 'song'
            })
    except Exception as e:
        print(f"JioSaavn error: {e}")
        import traceback
        traceback.print_exc()
    
    return results


def search_soundcloud(query):
    """Search SoundCloud with unified cache"""
    results = []
    try:
        tracks = soundcloud.soundcloud_search(query, limit=20)
        
        for track in tracks:
            duration_ms = track.get('duration_ms', 0)
            if duration_ms:
                duration = f"{duration_ms // 60000}:{(duration_ms % 60000) // 1000:02d}"
            else:
                duration = "0:00"
            
            artwork_url = track.get('artwork_url', '')
            if artwork_url:
                artwork_url = artwork_url.replace('-large.', '-t500x500.')
            
            results.append({
                'title': track.get('title', 'Unknown'),
                'artist': track.get('uploader', 'Unknown Artist'),
                'source': 'SoundCloud',
                'url': track.get('url', ''),
                'thumbnail': artwork_url,
                'duration': duration,
                'track_id': track.get('id', ''),
                'plays': track.get('playback_count', 0),
                'likes': track.get('likes_count', 0),
                'genre': track.get('genre', ''),
                'type': 'song'
            })
    except Exception as e:
        print(f"SoundCloud error: {e}")
        import traceback
        traceback.print_exc()
    
    return results


def is_url(query):
    """Check if query is a MUSIC-related URL (not just any URL)"""
    music_url_patterns = [
        r'youtube\.com/watch',
        r'youtu\.be/',
        r'music\.youtube\.com',
        r'jiosaavn\.com/',
        r'saavn\.com/',
        r'soundcloud\.com/',
        r'spotify\.com/',
        r'gaana\.com/',
        r'wynk\.in/',
    ]
    return any(re.search(pattern, query, re.IGNORECASE) for pattern in music_url_patterns)


def validate_url_simple(url):
    """Simple URL validation - just check if it's a supported platform"""
    supported_patterns = [
        r'youtube\.com/watch',
        r'youtu\.be/',
        r'music\.youtube\.com',
        r'soundcloud\.com/',
        r'jiosaavn\.com/',
        r'saavn\.com/',
        r'spotify\.com/',
    ]
    
    for pattern in supported_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            if 'soundcloud.com' in url.lower():
                source = "SoundCloud"
            elif 'jiosaavn.com' in url.lower() or 'saavn.com' in url.lower():
                source = "JioSaavn"
            elif 'spotify.com' in url.lower():
                source = "Spotify"
            else:
                source = "YouTube"
            
            is_playlist = bool(re.search(r'[?&]list=([^&]+)', url))
            playlist_id = None
            if is_playlist:
                playlist_match = re.search(r'[?&]list=([^&]+)', url)
                if playlist_match:
                    playlist_id = playlist_match.group(1)
            
            return {
                'is_valid': True,
                'url': url,
                'source': source,
                'type': 'direct_url',
                'is_playlist': is_playlist,
                'playlist_id': playlist_id
            }
    
    return {
        'is_valid': False,
        'error': 'Unsupported URL - Only YouTube, SoundCloud, JioSaavn, and Spotify are supported',
        'url': url
    }


def extract_video_id_from_url(url):
    """Extract video ID from YouTube URLs"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'(?:watch\?v=)([0-9A-Za-z_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def search_all_sources(query, search_id, search_type='music'):
    """Search all sources in parallel or validate and process URL"""
    global search_results
    
    all_results = {
        'ytmusic': [],
        'ytvideo': [],
        'jiosaavn': [],
        'soundcloud': [],
        'direct_url': [],
        'status': 'searching',
        'query_type': 'url' if is_url(query) else 'search'
    }
    
    if is_url(query):
        
        all_results['status'] = 'validating'
        search_results[search_id] = all_results
        
        video_info = validate_url_simple(query)
        
        if video_info and video_info.get('is_valid'):
            all_results['direct_url'] = [video_info]
            all_results['status'] = 'complete'
            all_results['message'] = 'Valid URL - Ready to download'
        else:
            all_results['status'] = 'error'
            all_results['error'] = video_info.get('error', 'Invalid URL')
            all_results['message'] = f"Unable to process URL: {video_info.get('error', 'Unknown error')}"
        
        all_results['timestamp'] = datetime.now().isoformat()
        search_results[search_id] = all_results
        return all_results
    
    threads = []
    results_lock = threading.Lock()
    
    def search_and_store(source_name, search_func):
        try:
            results = search_func(query)
            with results_lock:
                all_results[source_name] = results
        except Exception as e:
            print(f"Error searching {source_name}: {e}")
    
    if search_type == 'music':
        # Search music sources
        t1 = threading.Thread(target=search_and_store, args=('ytmusic', search_ytmusic))
        t3 = threading.Thread(target=search_and_store, args=('jiosaavn', search_jiosaavn))
        t4 = threading.Thread(target=search_and_store, args=('soundcloud', search_soundcloud))
        threads = [t1, t3, t4]
    elif search_type == 'video':
        # Search video sources
        t2 = threading.Thread(target=search_and_store, args=('ytvideo', search_ytvideo))
        threads = [t2]
    else:
        # Search all sources
        t1 = threading.Thread(target=search_and_store, args=('ytmusic', search_ytmusic))
        t2 = threading.Thread(target=search_and_store, args=('ytvideo', search_ytvideo))
        t3 = threading.Thread(target=search_and_store, args=('jiosaavn', search_jiosaavn))
        t4 = threading.Thread(target=search_and_store, args=('soundcloud', search_soundcloud))
        threads = [t1, t2, t3, t4]
    
    for t in threads:
        t.start()
    
    # Wait for all to complete
    for t in threads:
        t.join()
    
    all_results['status'] = 'complete'
    all_results['timestamp'] = datetime.now().isoformat()
    
    search_results[search_id] = all_results
    
    return all_results


def download_song(url, title, download_id, advanced_options=None):
    """Download song/video using yt-dlp with optional advanced parameters and progress tracking"""
    global download_status, active_processes
    
    print(f"\n{'='*70}")
    print(f"🎵 Starting download: {title}")
    print(f"🔗 URL: {url}")
    print(f"🆔 Download ID: {download_id}")
    print(f"⚙️  Advanced Options: {advanced_options}")
    print(f"{'='*70}\n")
    
    # Clean up /tmp if getting full (Heroku)
    cleanup_tmp_directory()
    
    download_status[download_id] = {
        'status': 'downloading',
        'progress': 0,
        'title': title,
        'url': url,
        'eta': 'Calculating...',
        'speed': '0 KB/s',
        'timestamp': datetime.now().isoformat(),
        'advanced_options': advanced_options
    }
    save_download_status()
    
    try:
        import subprocess
        import re as regex
        import shlex
        
        # SECURITY: Validate and sanitize URL to prevent command injection
        if not url or not isinstance(url, str):
            raise ValueError("Invalid URL")
        
        # Only allow URLs (no local files or shell commands)
        if not url.startswith(('http://', 'https://')):
            raise ValueError("Only HTTP/HTTPS URLs are allowed")
        
        # SECURITY: Validate title (prevent dangerous characters in title only)
        DANGEROUS_CHARS_TITLE = ['&&', '||', ';', '|', '`', '$', '<', '>', '\n', '\r']
        for dangerous_char in DANGEROUS_CHARS_TITLE:
            if dangerous_char in title:
                raise ValueError(f"Security: Dangerous character '{dangerous_char}' detected in title")
        
        # Sanitize filename
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
        
        # Base command - using list format for subprocess (safer than shell=True)
        cmd = ['yt-dlp']
        
        # SECURITY: Whitelist of allowed audio formats
        ALLOWED_AUDIO_FORMATS = ['mp3', 'm4a', 'opus', 'vorbis', 'wav', 'flac']
        
        # SECURITY: Whitelist of allowed quality values
        ALLOWED_QUALITIES = ['0', '2', '5', '9']
        
        # Apply advanced options if provided
        if advanced_options:
            audio_format = advanced_options.get('audioFormat', 'mp3')
            audio_quality = advanced_options.get('audioQuality', '0')
            embed_thumbnail = advanced_options.get('embedThumbnail', True)
            add_metadata = advanced_options.get('addMetadata', True)
            embed_subtitles = advanced_options.get('embedSubtitles', False)
            keep_video = advanced_options.get('keepVideo', False)
            custom_args = advanced_options.get('customArgs', '')
            
            # Video quality options (new)
            video_quality = advanced_options.get('videoQuality', '1080')
            video_fps = advanced_options.get('videoFPS', '30')
            video_format = advanced_options.get('videoFormat', 'mkv')
            
            # SECURITY: Validate audio format against whitelist
            if audio_format not in ALLOWED_AUDIO_FORMATS:
                audio_format = 'mp3'  # Default to safe value
            
            # SECURITY: Validate quality against whitelist
            if audio_quality not in ALLOWED_QUALITIES:
                audio_quality = '0'  # Default to safe value
            
            # SECURITY: Validate video format
            ALLOWED_VIDEO_FORMATS = ['mkv', 'mp4', 'webm']
            if video_format not in ALLOWED_VIDEO_FORMATS:
                video_format = 'mkv'
            
            if keep_video:
                # Video download with customizable quality
                # Build format string based on user selection
                if video_quality == 'best':
                    format_selector = 'bestvideo+bestaudio/best'
                else:
                    # Specific resolution
                    if video_fps == '60':
                        format_selector = f'bestvideo[height<={video_quality}][fps<=60]+bestaudio/best[height<={video_quality}]'
                    elif video_fps == '30':
                        format_selector = f'bestvideo[height<={video_quality}][fps<=30]+bestaudio/best[height<={video_quality}]'
                    else:  # any fps
                        format_selector = f'bestvideo[height<={video_quality}]+bestaudio/best[height<={video_quality}]'
                
                cmd.extend([
                    '-f', format_selector,
                    '--merge-output-format', video_format,
                ])
                
                # Add subtitle options if enabled
                if embed_subtitles:
                    cmd.extend([
                        '--embed-subs',
                        '--write-auto-subs',
                        '--sub-langs', 'en.*,hi.*,all',
                    ])
                
                output_template = os.path.join(app.config['DOWNLOAD_FOLDER'], f"%(title)s.%(ext)s")
            else:
                # Audio download
                cmd.extend([
                    '-x',
                    '--audio-format', audio_format,
                    '--audio-quality', audio_quality,
                ])
                output_template = os.path.join(app.config['DOWNLOAD_FOLDER'], f"%(title)s.%(ext)s")
            
            # Metadata options
            if add_metadata:
                cmd.append('--embed-metadata')
            
            if embed_thumbnail and not keep_video:
                cmd.append('--embed-thumbnail')
            
            # SECURITY: Custom arguments - STRICT WHITELIST ONLY
            if custom_args:
                # SECURITY: Block shell operators in custom args (but allow URLs)
                DANGEROUS_CHARS_ARGS = ['&&', '||', ';', '|', '`', '$', '\n', '\r']
                for dangerous_char in DANGEROUS_CHARS_ARGS:
                    if dangerous_char in custom_args:
                        # Security: Block dangerous characters
                        custom_args = ''  # Clear the dangerous input
                        break
                
                if custom_args:  # Only proceed if not cleared
                    # Whitelist of safe yt-dlp arguments for advanced audio downloads
                    SAFE_ARGS = [
                        # Network & Geo
                        '--geo-bypass',
                        '--geo-bypass-country',
                        '--prefer-free-formats',
                        
                        # Playlist handling
                        '--no-playlist',
                        '--yes-playlist',
                        '--playlist-items',
                        '--playlist-start',
                        '--playlist-end',
                        '--max-downloads',
                        
                        # Quality & Format
                        '--windows-filenames',
                        '--format-sort',
                        '--prefer-free-formats',
                        
                        '--max-filesize',
                        '--min-filesize',
                        '--limit-rate',
                        '--throttled-rate',
                        
                        '--retries',
                        '--fragment-retries',
                        '--skip-unavailable-fragments',
                        '--abort-on-unavailable-fragment',
                        '--keep-fragments',
                        
                        # Subtitles
                        '--write-subs',
                        '--write-auto-subs',
                        '--sub-langs',
                        '--sub-format',
                        '--convert-subs',
                        
                        # Metadata & Post-processing
                        '--add-chapters',
                        '--split-chapters',
                        '--no-embed-chapters',
                        '--xattrs',
                        '--concat-playlist',
                        
                        '--no-overwrites',
                        '--continue',
                        '--no-continue',
                        '--no-part',
                        '--no-mtime',
                        '--write-description',
                        '--write-info-json',
                        '--write-playlist-metafiles',
                        
                        # Workarounds
                        '--encoding',
                        '--legacy-server-connect',
                        '--no-check-certificates',
                        '--prefer-insecure',
                        '--add-header',
                        '--sleep-requests',
                        '--sleep-interval',
                        '--max-sleep-interval',
                        '--sleep-subtitles',
                    ]
                    
                    # Parse custom args safely
                    try:
                        # Define dangerous characters for custom args
                        DANGEROUS_CHARS_ARGS = ['&&', '||', ';', '|', '`', '$', '\n', '\r']
                        
                        parsed_args = shlex.split(custom_args)
                        i = 0
                        while i < len(parsed_args):
                            arg = parsed_args[i]
                            
                            # Additional security: check each arg for dangerous chars
                            has_danger = any(dc in arg for dc in DANGEROUS_CHARS_ARGS)
                            if has_danger:
                                # Security: Block dangerous argument
                                i += 1
                                continue
                            
                            # Only allow whitelisted arguments
                            arg_name = arg.split('=')[0] if '=' in arg else arg
                            if arg_name in SAFE_ARGS:
                                cmd.append(arg)
                                # If this argument expects a value (doesn't have =), add the next item too
                                if '=' not in arg and i + 1 < len(parsed_args):
                                    next_arg = parsed_args[i + 1]
                                    # Check if next arg doesn't start with -- (meaning it's a value, not a new flag)
                                    if not next_arg.startswith('-'):
                                        cmd.append(next_arg)
                                        i += 1  # Skip the value in next iteration
                            # Security: Block unsafe argument
                            i += 1
                    except Exception as e:
                        # Security: Failed to parse custom args (ignored)
                        pass
        else:
            # Default: Audio download with best quality and metadata
            cmd.extend([
                '--audio-format', 'mp3',
                '-x',
                '--audio-quality', '0',
                '--embed-metadata',
                '--embed-thumbnail',
            ])
            output_template = os.path.join(app.config['DOWNLOAD_FOLDER'], f"%(title)s.%(ext)s")
        
        # Create a unique directory for this download to avoid filename collisions
        download_dir = os.path.join(app.config['DOWNLOAD_FOLDER'], download_id)
        os.makedirs(download_dir, exist_ok=True)

        # Common options with newline progress for parsing
        cmd.extend([
            '-P', download_dir,
            '-o', '%(title)s.%(ext)s',
            '--newline',  # Progress on new lines for easier parsing
            url
        ])
        
        
        creation_flags = 0
        if os.name == 'nt':  # Windows
            creation_flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            shell=False,  # SECURITY: Never use shell=True!
            creationflags=creation_flags
        )
        
        # Store process for potential cancellation
        active_processes[download_id] = process
        
        if os.name != 'nt':
            try:
                import resource
                os.setpriority(os.PRIO_PROCESS, process.pid, 10)
            except Exception as e:
                pass
        
        # Track error messages from yt-dlp
        error_messages = []
        has_progress = False
        current_file_index = 0
        total_playlist_files = 0
        completed_files = []  # Track completed files as they finish
        current_downloading_file = None  # Track current file being downloaded
        
        # Parse progress in real-time
        for line in process.stdout:
            # Check if download was cancelled
            if download_status.get(download_id, {}).get('status') == 'cancelled':
                print(f"🚫 Download {download_id} was cancelled")
                process.terminate()
                break
                
            line = line.strip()
            
            # Log all output for debugging
            if line:
                print(f"[yt-dlp] {line}")
            
            # Detect playlist download info: [download] Downloading item 2 of 5
            if '[download] Downloading item' in line or '[download] Downloading video' in line:
                playlist_match = regex.search(r'Downloading (?:item|video) (\d+) of (\d+)', line)
                if playlist_match:
                    current_file_index = int(playlist_match.group(1))
                    total_playlist_files = int(playlist_match.group(2))
                    print(f"📦 Playlist progress: {current_file_index}/{total_playlist_files}")
                    # Update title to show playlist progress
                    download_status[download_id]['title'] = f"Downloading {current_file_index}/{total_playlist_files}"
                    save_download_status()
            
            # Detect ERROR messages from yt-dlp
            if 'ERROR:' in line:
                error_msg = line.replace('ERROR:', '').strip()
                error_messages.append(error_msg)
                print(f"❌ Error detected: {error_msg}")
            
            # Detect common error patterns
            error_patterns = [
                'Video unavailable',
                'Private video',
                'This video is not available',
                'Unable to download',
                'HTTP Error',
                'is not a valid URL',
                'Unsupported URL',
                'Video is not available',
                'This video has been removed',
                'no suitable formats',
                'Requested format is not available',
                'Sign in to confirm',
                'members-only content',
                'not supported',
                'Unsupported site',
                'No video formats found',
            ]
            
            if any(pattern.lower() in line.lower() for pattern in error_patterns):
                error_messages.append(line)
                print(f"⚠️  Error pattern matched: {line}")
            
            # Parse download progress: [download]  45.2% of 3.50MiB at 1.23MiB/s ETA 00:02
            if '[download]' in line and '%' in line:
                has_progress = True  # Mark that we've seen actual download progress
                try:
                    # Extract percentage
                    percent_match = regex.search(r'(\d+\.?\d*)%', line)
                    if percent_match:
                        progress = float(percent_match.group(1))
                        
                        # Check if a file just completed (100%)
                        if progress >= 100.0 and total_playlist_files > 0:
                            # A file in the playlist just completed
                            print(f"✅ File {current_file_index}/{total_playlist_files} completed!")
                            
                            # Find the most recently created file
                            download_dir = os.path.join(app.config['DOWNLOAD_FOLDER'], download_id)
                            try:
                                existing_files = os.listdir(download_dir)
                                if existing_files:
                                    # Get the newest file
                                    newest_file = max(
                                        [os.path.join(download_dir, f) for f in existing_files],
                                        key=os.path.getctime
                                    )
                                    filename = os.path.basename(newest_file)
                                    
                                    # Check if we haven't already added this file
                                    if filename not in [f['file'] for f in completed_files]:
                                        file_title = os.path.splitext(filename)[0]
                                        file_download_id = f"{download_id}_file_{len(completed_files)}"
                                        
                                        # Create individual file status immediately
                                        download_status[file_download_id] = {
                                            'status': 'complete',
                                            'progress': 100,
                                            'title': file_title,
                                            'url': url,
                                            'file': filename,
                                            'speed': 'Complete',
                                            'eta': '0:00',
                                            'timestamp': download_status[download_id]['timestamp'],
                                            'completed_at': datetime.now().isoformat(),
                                            'advanced_options': advanced_options,
                                            'parent_download_id': download_id,
                                            'file_index': len(completed_files) + 1,
                                            'total_files': total_playlist_files
                                        }
                                        
                                        completed_files.append({
                                            'download_id': file_download_id,
                                            'title': file_title,
                                            'file': filename
                                        })
                                        
                                        # Update main download status with completed files so far
                                        download_status[download_id]['file_downloads'] = completed_files.copy()
                                        save_download_status()
                                        print(f"💾 Saved completed file {len(completed_files)}/{total_playlist_files}: {file_title}")
                            except Exception as e:
                                print(f"⚠️  Error checking completed file: {e}")
                        
                        # If this is a playlist, calculate overall progress
                        if total_playlist_files > 0:
                            # Progress = (completed files + current file progress) / total files
                            files_done = len(completed_files)
                            current_file_progress = progress / 100.0
                            overall_progress = ((files_done + current_file_progress) / total_playlist_files) * 100
                            progress = overall_progress
                        
                        # Extract speed
                        speed_match = regex.search(r'at\s+([\d\.]+\s*[KMG]iB/s)', line)
                        speed = speed_match.group(1) if speed_match else 'Unknown'
                        
                        # Extract ETA
                        eta_match = regex.search(r'ETA\s+([\d:]+)', line)
                        eta = eta_match.group(1) if eta_match else 'Unknown'
                        
                        # Update title with playlist info if applicable
                        display_title = title
                        if total_playlist_files > 0:
                            display_title = f"Downloading {current_file_index}/{total_playlist_files}: {title}"
                        
                        download_status[download_id] = {
                            'status': 'downloading',
                            'progress': min(progress, 99),  # Cap at 99% until complete
                            'title': display_title,
                            'url': url,
                            'speed': speed,
                            'eta': eta,
                            'current_file': current_file_index if total_playlist_files > 0 else None,
                            'total_files': total_playlist_files if total_playlist_files > 0 else None,
                            'file_downloads': completed_files.copy() if completed_files else None,  # Include completed files
                            'timestamp': download_status[download_id]['timestamp'],
                            'advanced_options': advanced_options
                        }
                        save_download_status()
                except Exception as parse_err:
                    # Parsing error - continue processing
                    pass
        
        # Clean up process reference
        if download_id in active_processes:
            del active_processes[download_id]
        
        process.wait()
        return_code = process.returncode
        print(f"\n🏁 Process completed with return code: {return_code}")
        print(f"📊 Has progress: {has_progress}")
        print(f"❌ Error messages: {len(error_messages)}")
        if error_messages:
            print(f"   Errors: {error_messages[:3]}")
        
        # Check if cancelled during execution
        if download_status.get(download_id, {}).get('status') == 'cancelled':
            print(f"🚫 Download was cancelled, exiting")
            return
        
        # Check for errors even if return code is 0 (yt-dlp sometimes returns 0 on errors)
        if error_messages:
            # Combine error messages
            error_text = ' | '.join(error_messages[:3])  # Limit to first 3 errors
            print(f"❌ Download failed with errors: {error_text}")
            download_status[download_id] = {
                'status': 'error',
                'progress': 0,
                'title': title,
                'url': url,
                'error': error_text,
                'speed': '0 KB/s',
                'eta': 'N/A',
                'timestamp': download_status[download_id]['timestamp'],
                'failed_at': datetime.now().isoformat(),
                'advanced_options': advanced_options
            }
            save_download_status()
            print(f"💾 Status saved as 'error'")
            return
        
        if process.returncode == 0 and has_progress:
            print(f"✅ Download completed successfully")
            # Find the downloaded file in the unique directory
            download_dir = os.path.join(app.config['DOWNLOAD_FOLDER'], download_id)
            try:
                files = os.listdir(download_dir)
                print(f"📁 Files in download folder: {len(files)}")
                
                # Check if multiple files were downloaded (playlist)
                if len(files) > 1:
                    # Multiple files - playlist download
                    print(f"📦 Multiple files detected: {len(files)} files")
                    
                    # If we already tracked files during download, use that
                    if completed_files and len(completed_files) > 0:
                        print(f"✅ Using already tracked {len(completed_files)} files")
                        file_downloads = completed_files
                    else:
                        # Fallback: create file entries now
                        print(f"⚠️  No tracked files, creating entries now")
                        all_files = sorted(
                            [os.path.join(download_dir, f) for f in files],
                            key=os.path.getctime
                        )
                        
                        file_downloads = []
                        for idx, file_path in enumerate(all_files):
                            filename = os.path.basename(file_path)
                            file_title = os.path.splitext(filename)[0]
                            file_download_id = f"{download_id}_file_{idx}"
                            
                            # Create individual file status
                            download_status[file_download_id] = {
                                'status': 'complete',
                                'progress': 100,
                                'title': file_title,
                                'url': url,
                                'file': filename,
                                'speed': 'Complete',
                                'eta': '0:00',
                                'timestamp': download_status[download_id]['timestamp'],
                                'completed_at': datetime.now().isoformat(),
                                'advanced_options': advanced_options,
                                'parent_download_id': download_id,
                                'file_index': idx + 1,
                                'total_files': len(files)
                            }
                            
                            file_downloads.append({
                                'download_id': file_download_id,
                                'title': file_title,
                                'file': filename
                            })
                    
                    # Create summary title using first file
                    first_file_title = file_downloads[0]['title'] if file_downloads else "Playlist"
                    actual_title = f"{first_file_title} (+{len(files)-1} more)"
                    
                    # Update main download status with references to individual files
                    download_status[download_id] = {
                        'status': 'complete',
                        'progress': 100,
                        'title': actual_title,
                        'url': url,
                        'file_count': len(files),
                        'file_downloads': file_downloads,  # Individual file download IDs
                        'speed': 'Complete',
                        'eta': '0:00',
                        'timestamp': download_status[download_id]['timestamp'],
                        'completed_at': datetime.now().isoformat(),
                        'advanced_options': advanced_options
                    }
                    print(f"💾 Status saved as 'complete' with {len(files)} individual file downloads, title: {actual_title}")
                else:
                    # Single file download
                    latest_file = max(
                        [os.path.join(download_dir, f) for f in files],
                        key=os.path.getctime,
                        default=None
                    ) if files else None
                    
                    if latest_file:
                        filename = os.path.basename(latest_file)
                        print(f"📄 Downloaded file: {filename}")
                        
                        # Extract actual title from filename (remove extension)
                        actual_title = os.path.splitext(filename)[0]
                        
                        download_status[download_id] = {
                            'status': 'complete',
                            'progress': 100,
                            'title': actual_title,  # Use extracted title instead of original
                            'url': url,
                            'file': filename,
                            'speed': 'Complete',
                            'eta': '0:00',
                            'timestamp': download_status[download_id]['timestamp'],
                            'completed_at': datetime.now().isoformat(),
                            'advanced_options': advanced_options
                        }
                        print(f"💾 Status saved as 'complete' with file: {filename}, title: {actual_title}")
                    else:
                        download_status[download_id] = {
                            'status': 'complete',
                            'progress': 100,
                            'title': title,
                            'url': url,
                            'file': f"{safe_title}.mp3",
                            'speed': 'Complete',
                            'eta': '0:00',
                            'timestamp': download_status[download_id]['timestamp'],
                            'completed_at': datetime.now().isoformat(),
                            'advanced_options': advanced_options
                        }
            except FileNotFoundError:
                latest_file = None
                download_status[download_id] = {
                    'status': 'complete',
                    'progress': 100,
                    'title': title,
                    'url': url,
                    'file': f"{safe_title}.mp3",
                    'speed': 'Complete',
                    'eta': '0:00',
                    'timestamp': download_status[download_id]['timestamp'],
                    'completed_at': datetime.now().isoformat(),
                    'advanced_options': advanced_options
                }
        elif process.returncode == 0 and not has_progress:
            # yt-dlp returned 0 but no download progress - check if file was actually created
            download_dir = os.path.join(app.config['DOWNLOAD_FOLDER'], download_id)
            try:
                files = os.listdir(download_dir)
                if files:
                    # File was created even without progress output - treat as success
                    filename = files[0]  # Take first file
                    print(f"✅ Download completed (no progress output but file created): {filename}")
                    
                    # Extract actual title from filename (remove extension)
                    actual_title = os.path.splitext(filename)[0]
                    
                    download_status[download_id] = {
                        'status': 'complete',
                        'progress': 100,
                        'title': actual_title,  # Use extracted title instead of original
                        'url': url,
                        'file': filename,
                        'speed': 'Complete',
                        'eta': '0:00',
                        'timestamp': download_status[download_id]['timestamp'],
                        'completed_at': datetime.now().isoformat(),
                        'advanced_options': advanced_options
                    }
                    print(f"💾 Status saved as 'complete' with file: {filename}, title: {actual_title}")
                    save_download_status()
                    return
            except Exception:
                pass
            
            # No file found - likely an error
            print(f"⚠️  No download progress detected (return code 0)")
            download_status[download_id] = {
                'status': 'error',
                'progress': 0,
                'title': title,
                'url': url,
                'error': 'No download progress detected. URL may be invalid, unsupported, or unavailable.',
                'speed': '0 KB/s',
                'eta': 'N/A',
                'timestamp': download_status[download_id]['timestamp'],
                'failed_at': datetime.now().isoformat(),
                'advanced_options': advanced_options
            }
            print(f"💾 Status saved as 'error' (no progress)")
        else:
            # Process returned non-zero exit code
            error_text = 'Download failed'
            if error_messages:
                error_text = ' | '.join(error_messages[:3])  # Use collected error messages
            
            download_status[download_id] = {
                'status': 'error',
                'progress': 0,
                'title': title,
                'url': url,
                'error': error_text,
                'speed': '0 KB/s',
                'eta': 'N/A',
                'timestamp': download_status[download_id]['timestamp'],
                'failed_at': datetime.now().isoformat(),
                'advanced_options': advanced_options
            }
    
    except Exception as e:
        download_status[download_id] = {
            'status': 'error',
            'progress': 0,
            'title': title,
            'url': url,
            'error': str(e),
            'speed': '0 KB/s',
            'eta': 'N/A',
            'timestamp': download_status[download_id]['timestamp'],
            'failed_at': datetime.now().isoformat(),
            'advanced_options': advanced_options
        }
    
    finally:
        # Always save final status
        save_download_status()
        # Clean up process reference
        if download_id in active_processes:
            del active_processes[download_id]


@app.route('/')
def index():
    """Render main page with optional URL parameter search"""
    # Get query parameter from URL
    query = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'music')
    
    # Get frontend URL from environment variable
    frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:5000')
    
    return render_template('index.html', 
                         initial_query=query, 
                         initial_type=search_type,
                         frontend_url=frontend_url)


@app.route('/search', methods=['POST'])
def search():
    """Handle search request"""
    data = request.get_json()
    query = data.get('query', '').strip()
    search_type = data.get('type', 'music')  # 'music', 'video', or 'all'
    
    if not query:
        return jsonify({'error': 'Empty query'}), 400
    
    # Generate search ID
    search_id = f"search_{datetime.now().timestamp()}"
    
    # Detect if it's a URL
    query_type = 'url' if is_url(query) else 'search'
    
    thread = threading.Thread(
        target=search_all_sources,
        args=(query, search_id, search_type)
    )
    thread.start()
    
    return jsonify({
        'search_id': search_id,
        'status': 'started',
        'query_type': query_type
    })


@app.route('/search/jiosaavn', methods=['POST'])
def search_jiosaavn_endpoint():
    """Fast JioSaavn search endpoint"""
    data = request.get_json()
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({'error': 'Query is required'}), 400
    
    try:
        results = search_jiosaavn(query)
        return jsonify({
            'status': 'complete',
            'source': 'jiosaavn',
            'results': results,
            'count': len(results),
            'query': query
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'source': 'jiosaavn',
            'error': str(e),
            'results': [],
            'count': 0,
            'query': query
        })


@app.route('/search/soundcloud', methods=['POST'])
def search_soundcloud_endpoint():
    """Fast SoundCloud search endpoint"""
    data = request.get_json()
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({'error': 'Query is required'}), 400
    
    try:
        results = search_soundcloud(query)
        return jsonify({
            'status': 'complete',
            'source': 'soundcloud',
            'results': results,
            'count': len(results),
            'query': query
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'source': 'soundcloud',
            'error': str(e),
            'results': [],
            'count': 0,
            'query': query
        })


@app.route('/search/ytmusic', methods=['POST'])
def search_ytmusic_endpoint():
    """Fast YouTube Music search endpoint"""
    data = request.get_json()
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({'error': 'Query is required'}), 400
    
    try:
        results = search_ytmusic(query)
        return jsonify({
            'status': 'complete',
            'source': 'ytmusic',
            'results': results,
            'count': len(results),
            'query': query
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'source': 'ytmusic',
            'error': str(e),
            'results': [],
            'count': 0,
            'query': query
        })


@app.route('/search/ytvideo', methods=['POST'])
def search_ytvideo_endpoint():
    """Fast YouTube Video search endpoint"""
    data = request.get_json()
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({'error': 'Query is required'}), 400
    
    try:
        results = search_ytvideo(query)
        return jsonify({
            'status': 'complete',
            'source': 'ytvideo',
            'results': results,
            'count': len(results),
            'query': query
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'source': 'ytvideo',
            'error': str(e),
            'results': [],
            'count': 0,
            'query': query
        })


def get_youtube_suggestions(query):
    """Get search suggestions from YouTube API"""
    try:
        import urllib.parse
        import json
        
        # YouTube's suggestion API endpoint
        encoded_query = urllib.parse.quote(query)
        url = f"https://suggestqueries.google.com/complete/search?client=youtube&q={encoded_query}"
        
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            # YouTube returns JSONP format, extract JSON part
            jsonp_text = response.text
            if jsonp_text.startswith('window.google.ac.h('):
                json_text = jsonp_text[19:-1]  # Remove JSONP wrapper
                data = json.loads(json_text)
                suggestions = [item[0] for item in data[1][:5]]  # Get first 5 suggestions
                return suggestions
    except Exception as e:
        print(f"YouTube suggestions error: {e}")
    return []

def get_jiosaavn_suggestions(query):
    """Get search suggestions from JioSaavn search"""
    try:
        # Use JioSaavn search to get relevant song titles
        from jiosaavn_search import JioSaavnAPI
        
        api = JioSaavnAPI()
        results = api.search_songs(query, limit=3)
        if results and 'results' in results:
            suggestions = []
            for song in results['data']['results'][:3]:
                if 'title' in song:
                    title = song['title']
                    # Clean up the title
                    if title and len(title) > 3:
                        suggestions.append(title)
            return suggestions
    except Exception as e:
        print(f"JioSaavn suggestions error: {e}")
    return []

def get_spotify_suggestions(query):
    """Get search suggestions using Spotify-like approach"""
    try:
        # Use common music search patterns
        suggestions = [
            f"{query} song",
            f"{query} remix",
            f"{query} cover",
            f"{query} acoustic",
            f"{query} live"
        ]
        return suggestions[:3]
    except Exception:
        return []


@app.route('/suggestions')
def get_suggestions():
    """Get dynamic search suggestions from multiple APIs"""
    query = request.args.get('q', '').strip()
    
    if not query or len(query) < 2:
        return jsonify({'suggestions': []})
    
    try:
        all_suggestions = []
        
        # Get YouTube suggestions (most reliable)
        youtube_suggestions = get_youtube_suggestions(query)
        if youtube_suggestions:
            all_suggestions.extend(youtube_suggestions[:4])
        
        # Get JioSaavn-based suggestions
        jiosaavn_suggestions = get_jiosaavn_suggestions(query)
        if jiosaavn_suggestions:
            all_suggestions.extend(jiosaavn_suggestions[:2])
        
        # Add Spotify-like suggestions as fallback
        spotify_suggestions = get_spotify_suggestions(query)
        all_suggestions.extend(spotify_suggestions[:2])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_suggestions = []
        for suggestion in all_suggestions:
            suggestion_lower = suggestion.lower().strip()
            if suggestion_lower not in seen and len(suggestion_lower) > 1:
                seen.add(suggestion_lower)
                unique_suggestions.append(suggestion)
        
        # Limit to 6 suggestions for better UX
        final_suggestions = unique_suggestions[:6]
        
        return jsonify({'suggestions': final_suggestions})
        
    except Exception as e:
        print(f"❌ Suggestions error: {e}")
        # Fallback to simple suggestions
        fallback_suggestions = [
            f"{query} song",
            f"{query} music",
            f"{query} latest"
        ]
        return jsonify({'suggestions': fallback_suggestions})


@app.route('/search_status/<search_id>')
def search_status(search_id):
    """Get search status and results"""
    if search_id in search_results:
        return jsonify(search_results[search_id])
    else:
        return jsonify({'status': 'not_found'}), 404


@app.route('/download', methods=['POST'])
def download():
    """Handle download request with optional advanced options"""
    data = request.get_json()
    url = data.get('url')
    title = data.get('title')
    advanced_options = data.get('advancedOptions')
    
    print(f"\n{'='*70}")
    print(f"📥 Download request received")
    print(f"   URL: {url}")
    print(f"   Title: {title}")
    print(f"   Advanced Options: {advanced_options}")
    print(f"{'='*70}\n")
    
    # SECURITY: Validate required parameters
    if not url or not title:
        print(f"❌ Missing required parameters")
        return jsonify({'error': 'Missing url or title'}), 400
    
    # SECURITY: Validate URL format
    if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return jsonify({'error': 'Invalid URL format. Only HTTP/HTTPS URLs are allowed.'}), 400
    
    # SECURITY: Block shell operators and dangerous characters in title only
    DANGEROUS_CHARS_TITLE = ['&&', '||', ';', '|', '`', '$', '<', '>', '\n', '\r']
    for dangerous_char in DANGEROUS_CHARS_TITLE:
        if dangerous_char in title:
            return jsonify({'error': f'Security: Dangerous character detected in title'}), 400
    
    # SECURITY: Sanitize title (prevent path traversal but allow URLs)
    # Replace path separators and dangerous characters instead of rejecting
    if not isinstance(title, str):
        return jsonify({'error': 'Invalid title type'}), 400
    
    # Check for path traversal attempts
    if '..' in title:
        return jsonify({'error': 'Invalid title: path traversal detected'}), 400
    
    # Sanitize the title by replacing path separators and other unsafe characters
    title = title.replace('\\', '_').replace('/', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
    
    # SECURITY: Limit title length
    if len(title) > 200:
        title = title[:200]
    
    # SECURITY: Validate URL length
    if len(url) > 2048:
        return jsonify({'error': 'URL too long'}), 400
    
    # SECURITY: Validate advanced options if provided
    if advanced_options and isinstance(advanced_options, dict):
        custom_args = advanced_options.get('customArgs', '')
        if custom_args:
            DANGEROUS_CHARS_ARGS = ['&&', '||', ';', '|', '`', '$', '\n', '\r']
            for dangerous_char in DANGEROUS_CHARS_ARGS:
                if dangerous_char in custom_args:
                    return jsonify({'error': f'Security: Dangerous character detected in custom arguments'}), 400
    
    # Generate download ID
    download_id = f"download_{datetime.now().timestamp()}"
    
    print(f"🆔 Generated download ID: {download_id}")
    print(f"🚀 Starting download thread...")
    
    thread = threading.Thread(
        target=download_song,
        args=(url, title, download_id, advanced_options)
    )
    thread.start()
    
    print(f"✅ Download thread started\n")
    
    return jsonify({
        'download_id': download_id,
        'status': 'started'
    })


@app.route('/download_status/<download_id>')
def download_status_check(download_id):
    """Check download status"""
    if download_id in download_status:
        status = download_status[download_id]
        # If download complete, add file download URL
        if status['status'] == 'complete' and 'file' in status:
            status['download_url'] = f"/get_file/{download_id}/{status['file']}"
        
        # Log status check (only for interesting states to avoid spam)
        if status['status'] in ['error', 'complete', 'cancelled']:
            print(f"📊 Status check [{download_id}]: {status['status']}")
            if status['status'] == 'error' and 'error' in status:
                print(f"   Error: {status['error']}")
        
        return jsonify(status)
    else:
        print(f"❓ Status check for unknown download_id: {download_id}")
        return jsonify({'status': 'not_found'}), 404


@app.route('/downloads')
def get_all_downloads():
    """Get all download statuses for persistent tracking"""
    # Filter out very old completed downloads
    filtered_downloads = {}
    current_time = datetime.now()
    
    for download_id, status in download_status.items():
        # Keep all active downloads and recent completed ones
        if status.get('status') in ['downloading', 'queued', 'preparing']:
            filtered_downloads[download_id] = status
        elif status.get('status') in ['complete', 'error', 'cancelled']:
            # Keep completed downloads for 24 hours
            if 'timestamp' in status:
                try:
                    download_time = datetime.fromisoformat(status['timestamp'])
                    if (current_time - download_time).total_seconds() < 86400:  # 24 hours
                        filtered_downloads[download_id] = status
                except:
                    # Keep if timestamp parsing fails
                    filtered_downloads[download_id] = status
            else:
                # Keep if no timestamp
                filtered_downloads[download_id] = status
    
    # Add download URLs for completed files
    for download_id, status in filtered_downloads.items():
        if status['status'] == 'complete' and 'file' in status:
            status['download_url'] = f"/get_file/{download_id}/{status['file']}"
    
    return jsonify(filtered_downloads)


@app.route('/bulk_download', methods=['POST'])
def bulk_download():
    """Handle bulk download request - process URLs sequentially"""
    data = request.get_json()
    urls = data.get('urls', [])
    advanced_options = data.get('advancedOptions')
    
    if not urls or not isinstance(urls, list):
        return jsonify({'error': 'URLs list is required'}), 400
    
    # Validate URLs
    valid_urls = []
    for url in urls:
        if isinstance(url, str) and url.startswith(('http://', 'https://')):
            valid_urls.append(url.strip())
    
    if not valid_urls:
        return jsonify({'error': 'No valid URLs provided'}), 400
    
    print(f"\n{'='*70}")
    print(f"📦 Bulk download request: {len(valid_urls)} URLs")
    print(f"⚙️  Advanced Options: {advanced_options}")
    print(f"{'='*70}\n")
    
    # Generate bulk ID
    bulk_id = f"bulk_{datetime.now().timestamp()}"
    
    # Initialize bulk download status
    bulk_downloads = []
    for i, url in enumerate(valid_urls):
        download_id = f"{bulk_id}_item_{i}"
        bulk_downloads.append({
            'url': url,
            'title': f"Item {i+1}",
            'status': 'queued',
            'progress': 0,
            'download_id': download_id,
            'error': None,
            'speed': 'Queued',
            'eta': 'N/A'
        })
        
        # Add to download_status for tracking
        download_status[download_id] = {
            'status': 'queued',
            'progress': 0,
            'title': f"Item {i+1}",
            'url': url,
            'speed': 'Queued',
            'eta': 'N/A',
            'timestamp': datetime.now().isoformat(),
            'bulk_id': bulk_id,
            'advanced_options': advanced_options
        }
    
    # Store bulk info
    download_status[bulk_id] = {
        'type': 'bulk',
        'status': 'processing',
        'downloads': bulk_downloads,
        'total': len(valid_urls),
        'completed': 0,
        'failed': 0,
        'timestamp': datetime.now().isoformat()
    }
    
    save_download_status()
    
    # Start sequential downloads in background thread
    def process_bulk_downloads():
        for i, download_info in enumerate(bulk_downloads):
            download_id = download_info['download_id']
            url = download_info['url']
            title = download_info['title']
            
            print(f"\n📥 Processing bulk item {i+1}/{len(valid_urls)}: {url}")
            
            # Update status to downloading
            download_status[download_id]['status'] = 'downloading'
            download_status[bulk_id]['downloads'][i]['status'] = 'downloading'
            save_download_status()
            
            # Download the song
            download_song(url, title, download_id, advanced_options)
            
            # Update bulk stats
            if download_status[download_id]['status'] == 'complete':
                download_status[bulk_id]['completed'] += 1
            elif download_status[download_id]['status'] == 'error':
                download_status[bulk_id]['failed'] += 1
            
            # Update download info in bulk
            download_status[bulk_id]['downloads'][i] = {
                'url': url,
                'title': download_status[download_id].get('title', title),
                'status': download_status[download_id]['status'],
                'progress': download_status[download_id]['progress'],
                'download_id': download_id,
                'error': download_status[download_id].get('error'),
                'speed': download_status[download_id].get('speed', 'N/A'),
                'eta': download_status[download_id].get('eta', 'N/A'),
                'download_url': download_status[download_id].get('download_url')
            }
            
            save_download_status()
        
        # Mark bulk as complete
        download_status[bulk_id]['status'] = 'complete'
        save_download_status()
        print(f"\n✅ Bulk download complete: {download_status[bulk_id]['completed']}/{len(valid_urls)} successful\n")
    
    thread = threading.Thread(target=process_bulk_downloads)
    thread.start()
    
    return jsonify({
        'bulk_id': bulk_id,
        'status': 'started',
        'total': len(valid_urls)
    })


@app.route('/bulk_status/<bulk_id>')
def bulk_status_check(bulk_id):
    """Check bulk download status"""
    if bulk_id in download_status:
        bulk_status_data = download_status[bulk_id].copy()
        
        # Add download URLs for completed downloads
        if 'downloads' in bulk_status_data:
            for i, download in enumerate(bulk_status_data['downloads']):
                download_id = download.get('download_id')
                if download_id and download_id in download_status:
                    individual_status = download_status[download_id]
                    # Add download URL if download is complete and has file
                    if individual_status.get('status') == 'complete' and 'file' in individual_status:
                        bulk_status_data['downloads'][i]['download_url'] = f"/get_file/{download_id}/{individual_status['file']}"
                        bulk_status_data['downloads'][i]['file'] = individual_status['file']
                        # Update title with actual filename
                        if 'title' not in bulk_status_data['downloads'][i] or bulk_status_data['downloads'][i]['title'].startswith('Item '):
                            bulk_status_data['downloads'][i]['title'] = individual_status.get('title', bulk_status_data['downloads'][i]['title'])
        
        return jsonify(bulk_status_data)
    else:
        return jsonify({'error': 'Bulk download not found'}), 404


@app.route('/cancel_download/<download_id>', methods=['POST'])
def cancel_download(download_id):
    """Cancel a download"""
    global download_status, active_processes
    
    if download_id not in download_status:
        return jsonify({'error': 'Download not found'}), 404
    
    current_status = download_status[download_id]['status']
    
    if current_status in ['complete', 'error', 'cancelled']:
        return jsonify({'error': 'Download already finished'}), 400
    
    # Mark as cancelled
    download_status[download_id]['status'] = 'cancelled'
    download_status[download_id]['cancelled_at'] = datetime.now().isoformat()
    download_status[download_id]['progress'] = 0
    download_status[download_id]['speed'] = 'Cancelled'
    download_status[download_id]['eta'] = 'N/A'
    
    # Terminate active process if it exists
    if download_id in active_processes:
        try:
            process = active_processes[download_id]
            process.terminate()
            print(f"🚫 Terminated download process for {download_id}")
        except Exception as e:
            print(f"Warning: Could not terminate process for {download_id}: {e}")
    
    save_download_status()
    
    return jsonify({
        'status': 'cancelled',
        'message': f"Download cancelled: {download_status[download_id]['title']}"
    })


@app.route('/clear_downloads', methods=['POST'])
def clear_downloads():
    """Clear completed/failed downloads"""
    global download_status
    
    to_remove = []
    for download_id, status in download_status.items():
        if status.get('status') in ['complete', 'error', 'cancelled']:
            to_remove.append(download_id)
    
    for download_id in to_remove:
        del download_status[download_id]
    
    save_download_status()
    
    return jsonify({
        'message': f'Cleared {len(to_remove)} finished downloads',
        'cleared_count': len(to_remove)
    })


@app.route('/get_file/<download_id>/<filename>')
def get_file(download_id, filename):
    """Serve downloaded file to browser"""
    try:
        # Security check for download_id
        if not re.match(r'^[a-zA-Z0-9_.-]+$', download_id):
            return jsonify({'error': 'Invalid download ID'}), 400
        
        file_path = os.path.join(app.config['DOWNLOAD_FOLDER'], download_id, filename)
        if os.path.exists(file_path):
            return send_file(
                file_path,
                as_attachment=True,
                download_name=filename
            )
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/preview_url', methods=['POST'])
def preview_url():
    """Get video/song info from URL using existing search APIs (FAST)"""
    data = request.get_json()
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'Missing URL'}), 400
    
    # SECURITY: Validate URL
    if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return jsonify({'error': 'Invalid URL format'}), 400
    
    try:
        # First determine the source platform
        source = "Unknown"
        if 'soundcloud.com' in url.lower():
            source = "SoundCloud"
        elif 'jiosaavn.com' in url.lower() or 'saavn.com' in url.lower():
            source = "JioSaavn"
        elif 'spotify.com' in url.lower():
            source = "Spotify"
        elif 'youtube.com' in url.lower() or 'youtu.be' in url.lower() or 'music.youtube.com' in url.lower():
            source = "YouTube"
        
        # Handle YouTube URLs with API
        if source == "YouTube":
            video_id = extract_video_id_from_url(url)
            if video_id:
                try:
                    ytmusic, ytvideo, _ = get_apis()
                    
                    # Try YouTube Music API first
                    try:
                        # Construct YouTube URL
                        yt_url = f"https://www.youtube.com/watch?v={video_id}"
                        
                        # Search by URL to get metadata (uses cached tokens)
                        search_data = ytvideo.search_videos(video_id, use_fresh_tokens=True, retry_on_error=False)
                        
                        if search_data:
                            videos = ytvideo.parse_video_results(search_data)
                            if videos and len(videos) > 0:
                                video = videos[0]
                                
                                # Return formatted preview data
                                preview_data = {
                                    'title': video.get('title', 'Unknown Title'),
                                    'uploader': video.get('metadata', 'Unknown Channel'),
                                    'channel': video.get('metadata', 'Unknown Channel'),
                                    'thumbnail': video.get('thumbnail', f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"),
                                    'video_id': video_id,
                                    'webpage_url': yt_url,
                                    'source': 'YouTube'
                                }
                                
                                return jsonify(preview_data)
                    except Exception as e:
                        # YouTube API preview error - continue with fallback
                        pass
                    
                    # Fallback: Return basic info with video ID if we can extract it
                    if video_id:
                        preview_data = {
                            'title': 'YouTube Video',
                            'uploader': 'Unknown Channel',
                            'channel': 'Unknown Channel',
                            'thumbnail': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                            'video_id': video_id,
                            'webpage_url': url,
                            'source': 'YouTube'
                        }
                        return jsonify(preview_data)
                    else:
                        # No video ID found - invalid YouTube URL
                        return jsonify({'error': 'Invalid YouTube URL - Unable to extract video information'}), 400
                    
                except Exception as e:
                    # YouTube preview error - invalid URL
                    return jsonify({'error': 'Invalid YouTube URL - Unable to extract video information'}), 400
        
        # For non-YouTube URLs (SoundCloud, JioSaavn, Spotify, etc.)
        # Try to extract enhanced metadata for JioSaavn
        if source == "JioSaavn":
            enhanced_metadata = extract_jiosaavn_metadata(url)
            if enhanced_metadata:
                preview_data = {
                    'title': enhanced_metadata.get('title', f'{source} Content'),
                    'uploader': enhanced_metadata.get('artist', source),
                    'channel': enhanced_metadata.get('artist', source),
                    'thumbnail': enhanced_metadata.get('thumbnail', ''),
                    'album': enhanced_metadata.get('album', ''),
                    'pid': enhanced_metadata.get('pid', ''),  # Add PID for suggestions
                    'language': enhanced_metadata.get('language', 'hindi'),  # Add language for suggestions
                    'webpage_url': url,
                    'source': source
                }
                return jsonify(preview_data)
            else:
                # No metadata found - invalid JioSaavn URL
                return jsonify({'error': 'Invalid JioSaavn URL - Unable to extract song information'}), 400
        
        # Try to extract enhanced metadata for SoundCloud
        elif source == "SoundCloud":
            print(f"Processing SoundCloud URL: {url}")
            enhanced_metadata = extract_soundcloud_metadata_with_recommendations(url)
            print(f"SoundCloud metadata result: {enhanced_metadata is not None}")
            if enhanced_metadata:
                print(f"SoundCloud data keys: {enhanced_metadata.keys()}")
                if enhanced_metadata.get('main_track'):
                    print(f"Main track found: {enhanced_metadata['main_track'].get('title', 'No title')}")
            
            if enhanced_metadata and enhanced_metadata.get('main_track'):
                main_track = enhanced_metadata['main_track']
                preview_data = {
                    'title': main_track.get('title', f'{source} Content'),
                    'uploader': main_track.get('artist', source),
                    'channel': main_track.get('artist', source),
                    'thumbnail': main_track.get('thumbnail', ''),
                    'duration': main_track.get('duration', ''),
                    'plays': main_track.get('plays', 0),
                    'likes': main_track.get('likes', 0),
                    'genre': main_track.get('genre', ''),
                    'webpage_url': url,
                    'source': source,
                    'soundcloud_data': enhanced_metadata  # Include full data for frontend
                }
                print(f"Returning enhanced SoundCloud preview: {preview_data['title']}")
                return jsonify(preview_data)
            else:
                print(f"No SoundCloud metadata found - invalid URL")
                # No metadata found - invalid SoundCloud URL
                return jsonify({'error': 'Invalid SoundCloud URL - Unable to extract track information'}), 400
        
        # For other sources that don't have metadata extraction yet
        # Return generic error for unsupported platforms
        return jsonify({'error': f'Invalid {source} URL - Unable to extract content information'}), 400
        
    except Exception as e:
        print(f"❌ Preview error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/jiosaavn_suggestions/<pid>')
def get_jiosaavn_suggestions_by_pid(pid):
    """Get JioSaavn recommendations using PID"""
    try:
        # Validate PID (alphanumeric, reasonable length)
        if not pid or not re.match(r'^[a-zA-Z0-9_-]{1,20}$', pid):
            return jsonify({'error': 'Invalid PID format'}), 400
        
        # Default to English if no language specified
        language = request.args.get('language', 'english')
        
        # Validate language (allow only safe values)
        allowed_languages = ['english', 'hindi', 'telugu', 'tamil', 'punjabi', 'bengali', 'marathi', 'gujarati', 'kannada', 'malayalam']
        if language not in allowed_languages:
            language = 'english'
        
        # Build JioSaavn API URL
        api_url = f"https://www.jiosaavn.com/api.php?__call=reco.getreco&api_version=4&_format=json&_marker=0&ctx=wap6dot0&pid={pid}&language={language}"
        
        # Make request to JioSaavn API
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://www.jiosaavn.com/"
        }
        
        response = requests.get(api_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            try:
                data = response.json()
                
                # Parse and format the response
                suggestions = []
                
                # Check if data is a direct list (which it is based on our test)
                if isinstance(data, list):
                    items_to_process = data
                # Fallback: check for results key (in case API structure varies)
                elif 'results' in data and isinstance(data['results'], list):
                    items_to_process = data['results']
                else:
                    items_to_process = []
                
                for item in items_to_process:
                    if isinstance(item, dict):
                        # Extract artist from subtitle (format: "Artist - Album")
                        subtitle = item.get('subtitle', '')
                        artist = subtitle.split(' - ')[0] if ' - ' in subtitle else 'Unknown Artist'
                        
                        suggestion = {
                            'id': item.get('id', ''),
                            'title': item.get('title', ''),
                            'artist': artist,
                            'subtitle': subtitle,
                            'thumbnail': item.get('image', ''),
                            'url': item.get('perma_url', ''),
                            'duration': str(item.get('duration', 0)) if item.get('duration') else '0:00',
                            'language': item.get('language', ''),
                            'type': item.get('type', 'song'),
                            'year': item.get('year', ''),
                            'play_count': item.get('play_count', 0)
                        }
                        suggestions.append(suggestion)
                
                return jsonify({
                    'success': True,
                    'pid': pid,
                    'language': language,
                    'suggestions': suggestions,
                    'count': len(suggestions)
                })
                
            except json.JSONDecodeError:
                return jsonify({'error': 'Invalid JSON response from JioSaavn API'}), 500
        else:
            return jsonify({'error': f'JioSaavn API returned status {response.status_code}'}), 500
            
    except requests.RequestException as e:
        return jsonify({'error': f'Request failed: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.route('/extract_jiosaavn_pid', methods=['POST'])
def extract_jiosaavn_pid():
    """Extract PID from JioSaavn URL"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Validate that it's a JioSaavn URL
        if 'jiosaavn.com' not in url and 'saavn.com' not in url:
            return jsonify({'error': 'Not a valid JioSaavn URL'}), 400
        
        # Extract PID using the existing function
        metadata = extract_jiosaavn_metadata(url)
        
        if metadata and 'pid' in metadata:
            return jsonify({
                'success': True,
                'pid': metadata['pid'],
                'metadata': metadata
            })
        else:
            return jsonify({'error': 'Could not extract PID from URL'}), 404
            
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.route('/proxy_image')
def proxy_image():
    """Proxy images to avoid CORS issues"""
    url = request.args.get('url')
    if not url:
        return '', 404
    
    try:
        response = requests.get(url, timeout=5)
        return send_file(
            BytesIO(response.content),
            mimetype=response.headers.get('Content-Type', 'image/jpeg')
        )
    except:
        return '', 404


if __name__ == '__main__':
    print("🎵 Universal Music Downloader")
    print(f"📁 Downloads: {app.config['DOWNLOAD_FOLDER']}")
    print(f"💾 Cache file: {UNIFIED_CACHE_FILE}")
    print(f"📊 Download status: {DOWNLOAD_STATUS_FILE}")
    print(f"🕐 Cache duration: 2 hours")
    print(f"🌐 Browser mode: Headless (always)")
    if os.getenv('DYNO'):
        print(f"☁️  Running on Heroku (ephemeral /tmp storage)")
        print(f"🧹 Auto-cleanup enabled when /tmp > 80% full")
    print("="*70)
    
    load_persistent_data()
    cleanup_old_downloads()
    
    # Initial cleanup if on Heroku
    if os.getenv('DYNO'):
        cleanup_tmp_directory()

    # Use PORT from environment (Heroku provides this)
    port = int(os.getenv('PORT', 5000))
    # Disable debug in production
    debug = os.getenv('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', debug=debug, port=port, threaded=True)
