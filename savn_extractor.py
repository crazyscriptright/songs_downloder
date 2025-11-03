import requests
from bs4 import BeautifulSoup
import json
import re

url = input("Enter JioSaavn URL: ").strip()
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

try:
    res = requests.get(url, headers=headers)
    print("Response status:", res.status_code)
    
    if res.status_code != 200:
        print(f"Failed to fetch page. Status code: {res.status_code}")
        exit(1)
    
    soup = BeautifulSoup(res.text, "html.parser")
    
    # Extract image source
    img_element = soup.find("img", {"id": "songHeaderImage"})
    if img_element:
        img_src = img_element.get("src")
        print("Image URL:", img_src)
    else:
        print("Image not found")
    
    # Extract song title
    song_title_element = soup.find("h1", class_="u-h2 u-margin-bottom-tiny@sm")
    if song_title_element:
        song_title = song_title_element.get_text(strip=True)
        # Remove "Lyrics" suffix if present
        if song_title.endswith("Lyrics"):
            song_title = song_title[:-6].strip()
        print("Song Title:", song_title)
    else:
        print("Song title not found")
    
    # Extract album name and artists from the specific paragraph
    # Look for the paragraph that contains album and artist info
    album_para = soup.find("p", class_="u-color-js-gray u-ellipsis@lg u-margin-bottom-tiny@sm")
    album_name = None
    artists = []
    
    if album_para:
        # Extract album - specifically look for the link with screen_name="song_screen" and /album/ in href
        album_link = album_para.find("a", {"screen_name": "song_screen", "href": lambda x: x and "/album/" in x})
        if album_link:
            album_name = album_link.get_text(strip=True)
            print("Album:", album_name)
        
        # Extract artists from this specific paragraph - look for links with screen_name="song_screen" and /artist/ in href
        artist_links = album_para.find_all("a", {"screen_name": "song_screen", "href": lambda x: x and "/artist/" in x})
        for link in artist_links:
            artist_name = link.get_text(strip=True)
            if artist_name:
                artists.append(artist_name)
    
    if not album_name:
        print("Album not found")
    
    if artists:
        print("Artists:", ", ".join(artists))
    else:
        print("Artists not found")
    
    # Extract PID from page content
    pid_value = None
    print("\nSearching for PID...")
    
    # Method 1: Search in script tags for JSON containing "pid"
    script_tags = soup.find_all("script")
    for i, script in enumerate(script_tags):
        if script.string and '"pid"' in script.string:
            print(f"Found 'pid' in script tag {i}")
            try:
                # Try to find PID using regex pattern
                pid_match = re.search(r'"pid"\s*:\s*"([^"]+)"', script.string)
                if pid_match:
                    pid_value = pid_match.group(1)
                    print(f"PID found: {pid_value}")
                    break
                else:
                    # Try to find PID with single quotes
                    pid_match = re.search(r"'pid'\s*:\s*'([^']+)'", script.string)
                    if pid_match:
                        pid_value = pid_match.group(1)
                        print(f"PID found: {pid_value}")
                        break
            except Exception as e:
                print(f"Error parsing script tag {i}: {e}")
                continue
    
    # Method 2: Search in the entire page source if not found in scripts
    if not pid_value:
        print("PID not found in script tags, searching entire page...")
        page_content = res.text
        pid_match = re.search(r'"pid"\s*:\s*"([^"]+)"', page_content)
        if pid_match:
            pid_value = pid_match.group(1)
            print(f"PID found in page content: {pid_value}")
        else:
            # Try with single quotes
            pid_match = re.search(r"'pid'\s*:\s*'([^']+)'", page_content)
            if pid_match:
                pid_value = pid_match.group(1)
                print(f"PID found in page content: {pid_value}")
    
    if not pid_value:
        print("PID not found")
    
    print("-" * 50)
    print("EXTRACTED DATA:")
    print("-" * 50)
    print(f"Song: {song_title if 'song_title' in locals() else 'Not found'}")
    print(f"Album: {album_name if 'album_name' in locals() else 'Not found'}")
    print(f"Artists: {', '.join(artists) if artists else 'Not found'}")
    print(f"Image: {img_src if 'img_src' in locals() else 'Not found'}")
    print(f"PID: {pid_value if pid_value else 'Not found'}")

except requests.RequestException as e:
    print(f"Request error: {e}")
except Exception as e:
    print(f"Error processing page: {e}")
