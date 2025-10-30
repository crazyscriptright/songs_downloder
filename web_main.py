"""
Universal Music Downloader - Web Interface

A Flask-based web application that searches multiple music sources simultaneously
and displays results with thumbnails.

Supports:
- YouTube Music (Songs & Videos)
- JioSaavn
- SoundCloud
- Parallel search across all sources
- Image thumbnails
- One-click download

Run:
    python web_main.py
    Then open: http://localhost:5000
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

# Load environment variables
load_dotenv()

# Import our custom modules
try:
    from ytmusic_dynamic_tokens import YouTubeMusicAPI
    from ytmusic_dynamic_video_tokens import YouTubeMusicVideoAPI
    from jiosaavn_search import JioSaavnAPI
    import soundcloud
except ImportError as e:
    print(f"⚠ Import Error: {e}")
    print("Make sure all required modules are in the same directory!")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['DOWNLOAD_FOLDER'] = os.path.join(os.path.expanduser("~"), "Downloads", "Music")

# Ensure download folder exists
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)

# Initialize APIs (lazy loading with unified cache)
ytmusic_api = None
ytvideo_api = None
jiosaavn_api = None

# Store search results
search_results = {}
download_status = {}
active_processes = {}  # Store active download processes for cancellation

# Unified cache file for all APIs
UNIFIED_CACHE_FILE = "music_api_cache.json"
DOWNLOAD_QUEUE_FILE = "download_queue.json"
DOWNLOAD_STATUS_FILE = "download_status.json"


def get_apis():
    """Initialize APIs with unified cache and headless mode"""
    global ytmusic_api, ytvideo_api, jiosaavn_api
    
    if not ytmusic_api:
        ytmusic_api = YouTubeMusicAPI(
            cache_file=UNIFIED_CACHE_FILE,
            cache_duration_hours=2,
            headless=True  # Run browser in background
        )
    if not ytvideo_api:
        ytvideo_api = YouTubeMusicVideoAPI(
            cache_file=UNIFIED_CACHE_FILE,
            cache_duration_hours=2,
            headless=True  # Run browser in background
        )
    if not jiosaavn_api:
        jiosaavn_api = JioSaavnAPI()
    
    return ytmusic_api, ytvideo_api, jiosaavn_api


def load_persistent_data():
    """Load download queue and status from files - DISABLED for fresh start"""
    global download_status
    
    # NO PERSISTENCE - Always start fresh
    download_status = {}
    print("🆕 Starting with clean download status (no persistence)")
    
    # Comment out file loading to prevent any restoration
    # try:
    #     if os.path.exists(DOWNLOAD_STATUS_FILE):
    #         with open(DOWNLOAD_STATUS_FILE, 'r') as f:
    #             download_status = json.load(f)
    #         print(f"📥 Loaded {len(download_status)} download status records")
    # except Exception as e:
    #     print(f"Warning: Could not load download status: {e}")
    #     download_status = {}


def save_download_status():
    """Save download status to file - DISABLED for no persistence"""
    # NO PERSISTENCE - Don't save anything
    pass
    # Comment out file saving to prevent any persistence
    # try:
    #     with open(DOWNLOAD_STATUS_FILE, 'w') as f:
    #         json.dump(download_status, f, indent=2)
    # except Exception as e:
    #     print(f"Warning: Could not save download status: {e}")


def cleanup_old_downloads():
    """Clean up old completed/failed downloads older than 24 hours"""
    try:
        current_time = datetime.now()
        to_remove = []
        
        for download_id, status in download_status.items():
            if 'timestamp' in status:
                download_time = datetime.fromisoformat(status['timestamp'])
                if (current_time - download_time).total_seconds() > 86400:  # 24 hours
                    if status.get('status') in ['complete', 'error', 'cancelled']:
                        to_remove.append(download_id)
        
        for download_id in to_remove:
            del download_status[download_id]
        
        if to_remove:
            print(f"🧹 Cleaned up {len(to_remove)} old download records")
            save_download_status()
    
    except Exception as e:
        print(f"Warning: Could not cleanup old downloads: {e}")


def search_ytmusic(query):
    """Search YouTube Music for songs"""
    results = []
    try:
        ytmusic, _, _ = get_apis()
        
        # Will use cached tokens automatically (2 hour cache)
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
        
        # Will use cached tokens automatically (2 hour cache)
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


def search_jiosaavn(query):
    """Search JioSaavn"""
    results = []
    try:
        _, _, jiosaavn = get_apis()
        
        data = jiosaavn.search_songs(query)
        songs = jiosaavn.parse_results(data) if data else []
        
        for song in songs:
            # Get artist info - try multiple fields
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
        # Use the updated soundcloud module with unified cache
        tracks = soundcloud.soundcloud_search(query, limit=20)
        
        for track in tracks:
            # Format duration
            duration_ms = track.get('duration_ms', 0)
            if duration_ms:
                duration = f"{duration_ms // 60000}:{(duration_ms % 60000) // 1000:02d}"
            else:
                duration = "0:00"
            
            # Get artwork URL (SoundCloud returns it but may need higher resolution)
            artwork_url = track.get('artwork_url', '')
            if artwork_url:
                # Replace small image with larger version for better quality
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
    # Only detect URLs from supported music platforms
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
            # Determine source
            if 'soundcloud.com' in url.lower():
                source = "SoundCloud"
            elif 'jiosaavn.com' in url.lower() or 'saavn.com' in url.lower():
                source = "JioSaavn"
            elif 'spotify.com' in url.lower():
                source = "Spotify"
            else:
                source = "YouTube"
            
            return {
                'is_valid': True,
                'url': url,
                'source': source,
                'type': 'direct_url'
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
    
    # If it's a URL, validate and extract info directly
    if is_url(query):
        print(f"🔗 Direct URL detected: {query}")
        
        # Simple validation - just check if it's supported
        all_results['status'] = 'validating'
        search_results[search_id] = all_results
        
        # Validate URL (instant, no external calls)
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
    
    # Otherwise, search based on type
    threads = []
    results_lock = threading.Lock()
    
    def search_and_store(source_name, search_func):
        try:
            results = search_func(query)
            with results_lock:
                all_results[source_name] = results
        except Exception as e:
            print(f"Error searching {source_name}: {e}")
    
    # Create threads based on search type
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
    
    # Start all threads
    for t in threads:
        t.start()
    
    # Wait for all to complete
    for t in threads:
        t.join()
    
    all_results['status'] = 'complete'
    all_results['timestamp'] = datetime.now().isoformat()
    
    # Store results
    search_results[search_id] = all_results
    
    return all_results


def download_song(url, title, download_id, advanced_options=None):
    """Download song/video using yt-dlp with optional advanced parameters and progress tracking"""
    global download_status, active_processes
    
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
        
        # Sanitize filename
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
        
        # Base command
        cmd = ['yt-dlp']
        
        # Apply advanced options if provided
        if advanced_options:
            audio_format = advanced_options.get('audioFormat', 'mp3')
            audio_quality = advanced_options.get('audioQuality', '0')
            embed_thumbnail = advanced_options.get('embedThumbnail', True)
            add_metadata = advanced_options.get('addMetadata', True)
            embed_subtitles = advanced_options.get('embedSubtitles', False)
            keep_video = advanced_options.get('keepVideo', False)
            custom_args = advanced_options.get('customArgs', '')
            
            if keep_video:
                # Video download defaults: 1080p 30fps MKV with embedded subtitles
                cmd.extend([
                    '-f', 'bestvideo[height<=1080][fps<=30]+bestaudio/best[height<=1080]',
                    '--merge-output-format', 'mkv',
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
            
            if embed_thumbnail:
                cmd.append('--embed-thumbnail')
            
            # Custom arguments
            if custom_args:
                cmd.extend(custom_args.split())
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
        
        # Common options with newline progress for parsing
        cmd.extend([
            '-P', app.config['DOWNLOAD_FOLDER'],
            '-o', '%(title)s.%(ext)s',
            '--newline',  # Progress on new lines for easier parsing
            url
        ])
        
        print(f"🎵 Download command: {' '.join(cmd)}")
        
        # Run with real-time output parsing at LOW PRIORITY
        # Set process creation flags for low priority
        creation_flags = 0
        if os.name == 'nt':  # Windows
            creation_flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            creationflags=creation_flags
        )
        
        # Store process for potential cancellation
        active_processes[download_id] = process
        
        # Set process to low priority on Linux/Mac
        if os.name != 'nt':
            try:
                import resource
                os.setpriority(os.PRIO_PROCESS, process.pid, 10)  # Lower priority
            except Exception as e:
                print(f"Warning: Could not set process priority: {e}")
        
        # Parse progress in real-time
        for line in process.stdout:
            # Check if download was cancelled
            if download_status.get(download_id, {}).get('status') == 'cancelled':
                print(f"🚫 Download {download_id} was cancelled")
                process.terminate()
                break
                
            line = line.strip()
            print(line)  # Debug output
            
            # Parse download progress: [download]  45.2% of 3.50MiB at 1.23MiB/s ETA 00:02
            if '[download]' in line and '%' in line:
                try:
                    # Extract percentage
                    percent_match = regex.search(r'(\d+\.?\d*)%', line)
                    if percent_match:
                        progress = float(percent_match.group(1))
                        
                        # Extract speed
                        speed_match = regex.search(r'at\s+([\d\.]+\s*[KMG]iB/s)', line)
                        speed = speed_match.group(1) if speed_match else 'Unknown'
                        
                        # Extract ETA
                        eta_match = regex.search(r'ETA\s+([\d:]+)', line)
                        eta = eta_match.group(1) if eta_match else 'Unknown'
                        
                        download_status[download_id] = {
                            'status': 'downloading',
                            'progress': min(progress, 99),  # Cap at 99% until complete
                            'title': title,
                            'url': url,
                            'speed': speed,
                            'eta': eta,
                            'timestamp': download_status[download_id]['timestamp'],
                            'advanced_options': advanced_options
                        }
                        save_download_status()
                except Exception as parse_err:
                    print(f"Parse error: {parse_err}")
                    pass
        
        # Clean up process reference
        if download_id in active_processes:
            del active_processes[download_id]
        
        process.wait()
        
        # Check if cancelled during execution
        if download_status.get(download_id, {}).get('status') == 'cancelled':
            return
        
        if process.returncode == 0:
            # Find the downloaded file
            download_folder = app.config['DOWNLOAD_FOLDER']
            files = os.listdir(download_folder)
            
            # Get the most recently created file
            latest_file = max(
                [os.path.join(download_folder, f) for f in files],
                key=os.path.getctime,
                default=None
            )
            
            if latest_file:
                filename = os.path.basename(latest_file)
                download_status[download_id] = {
                    'status': 'complete',
                    'progress': 100,
                    'title': title,
                    'url': url,
                    'file': filename,
                    'speed': 'Complete',
                    'eta': '0:00',
                    'timestamp': download_status[download_id]['timestamp'],
                    'completed_at': datetime.now().isoformat(),
                    'advanced_options': advanced_options
                }
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
        else:
            download_status[download_id] = {
                'status': 'error',
                'progress': 0,
                'title': title,
                'url': url,
                'error': 'Download failed',
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
    
    # Start background search
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
    
    if not url or not title:
        return jsonify({'error': 'Missing url or title'}), 400
    
    # Generate download ID
    download_id = f"download_{datetime.now().timestamp()}"
    
    # Start background download
    thread = threading.Thread(
        target=download_song,
        args=(url, title, download_id, advanced_options)
    )
    thread.start()
    
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
            status['download_url'] = f"/get_file/{status['file']}"
        return jsonify(status)
    else:
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
            status['download_url'] = f"/get_file/{status['file']}"
    
    return jsonify(filtered_downloads)


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


@app.route('/get_file/<filename>')
def get_file(filename):
    """Serve downloaded file to browser"""
    try:
        file_path = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
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
    print("="*70)
    print("🎵 Universal Music Downloader - Web Interface (Enhanced)")
    print("="*70)
    print(f"📁 Download folder: {app.config['DOWNLOAD_FOLDER']}")
    print(f"💾 Unified cache file: {UNIFIED_CACHE_FILE}")
    print(f"� Download status file: {DOWNLOAD_STATUS_FILE}")
    print(f"�🕐 Cache duration: 2 hours")
    print(f"🌐 Browser mode: Headless (background)")
    print("="*70)
    
    # Load persistent data
    load_persistent_data()
    cleanup_old_downloads()
    
    print("\n✅ Server running at: http://localhost:5000")
    print("\n🎯 Features:")
    print("   • Unified cache for all APIs (faster searches)")
    print("   • Headless browser (no popup windows)")
    print("   • Persistent download tracking (survives refresh)")
    print("   • Download cancellation support")
    print("   • Direct URL validation and download")
    print("   • Auto-retry on errors")
    print("\n   Press Ctrl+C to stop\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
