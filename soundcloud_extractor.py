import json
import requests
from bs4 import BeautifulSoup
import re

# Take URL input from user
url = input("Enter SoundCloud URL: ").strip()

# Validate URL
if not url or not ("soundcloud.com" in url):
    print("Please enter a valid SoundCloud URL")
    exit(1)

# Convert desktop URL to mobile URL for better compatibility
if url.startswith("https://soundcloud.com/"):
    mobile_url = url.replace("https://soundcloud.com/", "https://m.soundcloud.com/")
    print(f"Converting to mobile URL for better data extraction: {mobile_url}")
    url = mobile_url

headers = {"User-Agent": "Mozilla/5.0"}

res = requests.get(url, headers=headers)
soup = BeautifulSoup(res.text, "html.parser")

print("Response status:", res.status_code)

# Find the script tag that contains the JSON data with tracks keyword
script_tag = None
print("Searching for script tags containing 'tracks'...")

# First, try to find any script with "tracks": pattern
tracks_scripts = []
for i, script in enumerate(soup.find_all("script")):
    if script.string and '"tracks":' in script.string:
        print(f"Found 'tracks:' in script tag {i} (length: {len(script.string)})")
        tracks_scripts.append((i, script))

# If we found multiple scripts, prefer the largest one (usually contains the main data)
if tracks_scripts:
    # Sort by script length in descending order and pick the largest
    tracks_scripts.sort(key=lambda x: len(x[1].string), reverse=True)
    script_index, script_tag = tracks_scripts[0]
    print(f"Selected script tag {script_index} for processing (largest with {len(script_tag.string)} characters)")
else:
    # Fallback: look for any large script that might contain track data
    print("No 'tracks:' found, looking for large scripts that might contain data...")
    for i, script in enumerate(soup.find_all("script")):
        if script.string and len(script.string) > 50000:  # Very large scripts
            script_content = script.string.lower()
            if any(keyword in script_content for keyword in ['soundcloud', 'track', 'audio', 'music']):
                print(f"Found potential data script tag {i} (length: {len(script.string)})")
                script_tag = script
                break

if not script_tag:
    print("Could not find script tag with tracks data")
    exit(1)

raw_text = script_tag.string

try:
    # Parse the entire JSON object
    data = json.loads(raw_text)
    
    # Try different possible structures for tracks data
    tracks_data = None
    
    # Method 1: Mobile/new structure - props -> pageProps -> initialStoreState -> entities -> tracks
    initial_store = data.get("props", {}).get("pageProps", {}).get("initialStoreState", {})
    entities = initial_store.get("entities", {})
    if entities and "tracks" in entities:
        tracks_data = entities.get("tracks", {})
        print("Found tracks using mobile/new structure")
    
    # Method 2: Direct tracks access (if it's at root level)
    elif "tracks" in data:
        tracks_data = data.get("tracks", {})
        print("Found tracks using direct access")
    
    # Method 3: Look for tracks in any nested structure
    else:
        def find_tracks_recursive(obj, path=""):
            if isinstance(obj, dict):
                if "tracks" in obj and isinstance(obj["tracks"], dict):
                    # Check if this tracks object contains soundcloud track IDs
                    tracks_obj = obj["tracks"]
                    if any(key.startswith("soundcloud:tracks") for key in tracks_obj.keys()):
                        print(f"Found tracks using recursive search at path: {path}")
                        return tracks_obj
                
                for key, value in obj.items():
                    result = find_tracks_recursive(value, f"{path}.{key}" if path else key)
                    if result:
                        return result
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    result = find_tracks_recursive(item, f"{path}[{i}]" if path else f"[{i}]")
                    if result:
                        return result
            return None
        
        tracks_data = find_tracks_recursive(data)
    
    if not tracks_data:
        print("Could not find tracks data in any expected structure")
        print("Available top-level keys:", list(data.keys()) if isinstance(data, dict) else "Data is not a dict")
        
        # Debug: Show structure of first few keys
        if isinstance(data, dict):
            for key in list(data.keys())[:5]:
                value = data[key]
                if isinstance(value, dict):
                    print(f"  {key}: dict with keys {list(value.keys())[:5]}")
                elif isinstance(value, list):
                    print(f"  {key}: list with {len(value)} items")
                else:
                    print(f"  {key}: {type(value)}")
        exit(1)
    
    print(f"Found {len(tracks_data)} track(s)")
    
except json.JSONDecodeError as e:
    print(f"JSON decode error: {e}")
    print("First 1000 characters of script content:")
    print(raw_text[:1000])
    exit(1)
except Exception as e:
    print(f"Error processing data: {e}")
    exit(1)

# Extract all tracks - first one is main track, others are recommended
if tracks_data:
    track_count = 0
    main_track_id = None
    
    # Get all soundcloud tracks
    soundcloud_tracks = []
    for key, value in tracks_data.items():
        if key.startswith("soundcloud:tracks"):
            soundcloud_tracks.append((key, value))
    
    if not soundcloud_tracks:
        print("No soundcloud tracks found")
        exit(1)
    
    print(f"Found {len(soundcloud_tracks)} SoundCloud track(s)\n")
    
    # Display all tracks
    for i, (key, value) in enumerate(soundcloud_tracks):
        track_data = value.get("data", {})
        
        # Determine if this is the main track or recommended
        if i == 0:
            track_type = "🎵 MAIN TRACK"
            main_track_id = key
        else:
            track_type = "💡 RECOMMENDED"
        
        print(f"{track_type}")
        print(f"Track ID: {key}")
        print(f"Title: {track_data.get('title', 'N/A')}")
        print(f"Created At: {track_data.get('created_at', 'N/A')}")
        print(f"Duration (ms): {track_data.get('duration', 'N/A')}")
        print(f"Genre: {track_data.get('genre', 'N/A')}")
        print(f"Likes: {track_data.get('likes_count', 'N/A')}")
        print(f"Plays: {track_data.get('playback_count', 'N/A')}")
        print(f"Artwork URL: {track_data.get('artwork_url', 'N/A')}")
        
        # Get user info if available
        user_id = track_data.get('user_id')
        if user_id:
            print(f"User ID: {user_id}")
        
        print("-" * 60)
    
    # Summary
    print(f"\n📊 SUMMARY:")
    print(f"Main Track: {soundcloud_tracks[0][1].get('data', {}).get('title', 'N/A')}")
    print(f"Recommended Tracks: {len(soundcloud_tracks) - 1}")
    print(f"Total Tracks Found: {len(soundcloud_tracks)}")
    
else:
    print("No tracks data found")
