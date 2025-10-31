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
except ImportError as e:
    print(f"⚠ Import Error: {e}")
    print("Make sure all required modules are in the same directory!")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['DOWNLOAD_FOLDER'] = os.path.join(os.path.expanduser("~"), "Downloads", "Music")

os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)

ytmusic_api = None
ytvideo_api = None
jiosaavn_api = None

search_results = {}
download_status = {}
active_processes = {}

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
            headless=True
        )
    if not ytvideo_api:
        ytvideo_api = YouTubeMusicVideoAPI(
            cache_file=UNIFIED_CACHE_FILE,
            cache_duration_hours=2,
            headless=True
        )
    if not jiosaavn_api:
        jiosaavn_api = JioSaavnAPI()
    
    return ytmusic_api, ytvideo_api, jiosaavn_api


def load_persistent_data():
    """Start fresh without persistence"""
    global download_status
    download_status = {}


def save_download_status():
    """No persistence - skip saving"""
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
        
        # SECURITY: Block shell operators and dangerous characters
        DANGEROUS_CHARS = ['&&', '||', ';', '|', '`', '$', '(', ')', '<', '>', '\n', '\r', '&']
        for dangerous_char in DANGEROUS_CHARS:
            if dangerous_char in url:
                raise ValueError(f"Security: Dangerous character '{dangerous_char}' detected in URL")
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
                # SECURITY: Block shell operators in custom args
                for dangerous_char in DANGEROUS_CHARS:
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
                        parsed_args = shlex.split(custom_args)
                        for arg in parsed_args:
                            # Additional security: check each arg for dangerous chars
                            has_danger = any(dc in arg for dc in DANGEROUS_CHARS)
                            if has_danger:
                                # Security: Block dangerous argument
                                continue
                            
                            # Only allow whitelisted arguments
                            arg_name = arg.split('=')[0] if '=' in arg else arg
                            if arg_name in SAFE_ARGS:
                                cmd.append(arg)
                            # Security: Block unsafe argument
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
        
        # Common options with newline progress for parsing
        cmd.extend([
            '-P', app.config['DOWNLOAD_FOLDER'],
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
        
        # Parse progress in real-time
        for line in process.stdout:
            # Check if download was cancelled
            if download_status.get(download_id, {}).get('status') == 'cancelled':
                print(f"🚫 Download {download_id} was cancelled")
                process.terminate()
                break
                
            line = line.strip()
            # Skip printing every line for cleaner output
            
            # Detect ERROR messages from yt-dlp
            if 'ERROR:' in line:
                error_msg = line.replace('ERROR:', '').strip()
                error_messages.append(error_msg)
            
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
            ]
            
            if any(pattern.lower() in line.lower() for pattern in error_patterns):
                error_messages.append(line)
            
            # Parse download progress: [download]  45.2% of 3.50MiB at 1.23MiB/s ETA 00:02
            if '[download]' in line and '%' in line:
                has_progress = True  # Mark that we've seen actual download progress
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
                    # Parsing error - continue processing
                    pass
        
        # Clean up process reference
        if download_id in active_processes:
            del active_processes[download_id]
        
        process.wait()
        
        # Check if cancelled during execution
        if download_status.get(download_id, {}).get('status') == 'cancelled':
            return
        
        # Check for errors even if return code is 0 (yt-dlp sometimes returns 0 on errors)
        if error_messages:
            # Combine error messages
            error_text = ' | '.join(error_messages[:3])  # Limit to first 3 errors
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
            return
        
        if process.returncode == 0 and has_progress:
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
        elif process.returncode == 0 and not has_progress:
            # yt-dlp returned 0 but no download progress - likely an error
            download_status[download_id] = {
                'status': 'error',
                'progress': 0,
                'title': title,
                'url': url,
                'error': 'No download progress detected. URL may be invalid or unavailable.',
                'speed': '0 KB/s',
                'eta': 'N/A',
                'timestamp': download_status[download_id]['timestamp'],
                'failed_at': datetime.now().isoformat(),
                'advanced_options': advanced_options
            }
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
    
    # SECURITY: Validate required parameters
    if not url or not title:
        return jsonify({'error': 'Missing url or title'}), 400
    
    # SECURITY: Validate URL format
    if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return jsonify({'error': 'Invalid URL format. Only HTTP/HTTPS URLs are allowed.'}), 400
    
    # SECURITY: Block shell operators and dangerous characters
    DANGEROUS_CHARS = ['&&', '||', ';', '|', '`', '$', '(', ')', '<', '>', '\n', '\r', '&']
    for dangerous_char in DANGEROUS_CHARS:
        if dangerous_char in url:
            return jsonify({'error': f'Security: Dangerous character detected in URL'}), 400
        if dangerous_char in title:
            return jsonify({'error': f'Security: Dangerous character detected in title'}), 400
    
    # SECURITY: Validate title (prevent path traversal)
    if not isinstance(title, str) or '..' in title or '/' in title or '\\' in title:
        return jsonify({'error': 'Invalid title'}), 400
    
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
            for dangerous_char in DANGEROUS_CHARS:
                if dangerous_char in custom_args:
                    return jsonify({'error': f'Security: Dangerous character detected in custom arguments'}), 400
    
    # Generate download ID
    download_id = f"download_{datetime.now().timestamp()}"
    
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
        # Extract video ID for YouTube URLs
        video_id = extract_video_id_from_url(url)
        
        if video_id:
            # YouTube URL - use existing YouTube APIs (FAST - uses cached tokens)
            try:
                ytmusic, ytvideo, _ = get_apis()
                
                # Try YouTube Music API first
                try:
                    # Construct YouTube URL
                    yt_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    # Search by URL to get metadata (uses cached tokens)
                    # IMPORTANT: use_fresh_tokens=True means USE CACHE (backwards naming!)
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
                
                # Fallback: Return basic info with video ID
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
                
            except Exception as e:
                # YouTube preview error - continue with basic info
                pass
        
        # For non-YouTube URLs or if YouTube preview failed, return basic info
        # Determine source
        source = "Unknown"
        if 'soundcloud.com' in url.lower():
            source = "SoundCloud"
        elif 'jiosaavn.com' in url.lower() or 'saavn.com' in url.lower():
            source = "JioSaavn"
        elif 'spotify.com' in url.lower():
            source = "Spotify"
        
        # Return minimal preview data
        preview_data = {
            'title': f'{source} Content',
            'uploader': source,
            'channel': source,
            'thumbnail': '',
            'webpage_url': url,
            'source': source
        }
        
        return jsonify(preview_data)
        
    except Exception as e:
        print(f"❌ Preview error: {e}")
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
    print("🎵 Universal Music Downloader")
    print(f"📁 Downloads: {app.config['DOWNLOAD_FOLDER']}")
    print(f"� Download status file: {DOWNLOAD_STATUS_FILE}")
    print(f"�🕐 Cache duration: 2 hours")
    print(f"🌐 Browser mode: Headless (background)")
    print("="*70)
    
    load_persistent_data()
    cleanup_old_downloads()
    
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
