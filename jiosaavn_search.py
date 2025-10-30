"""
JioSaavn Song Search API

This script searches for songs on JioSaavn using their public API
and displays the results with download links.

Usage:
    python jiosaavn_search.py
"""

import requests
import json
from urllib.parse import quote_plus

class JioSaavnAPI:
    def __init__(self):
        self.base_url = "https://www.jiosaavn.com/api.php"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }
    
    def search_songs(self, query, page=1, limit=20):
        """Search for songs on JioSaavn"""
        
        # Build query parameters
        params = {
            "p": page,
            "q": query,
            "_format": "json",
            "_marker": "0",
            "api_version": "4",
            "ctx": "wap6dot0",
            "n": limit,
            "__call": "search.getResults"
        }
        
        # Build URL
        url = f"{self.base_url}?p={params['p']}&q={quote_plus(query)}&_format={params['_format']}&_marker={params['_marker']}&api_version={params['api_version']}&ctx={params['ctx']}&n={params['n']}&__call={params['__call']}"
        
        print(f"🔍 Searching JioSaavn for: {query}")
        print(f"📡 URL: {url}\n")
        
        try:
            # Send GET request
            response = requests.get(url, headers=self.headers)
            
            print(f"📊 Status Code: {response.status_code}")
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Error: {response.status_code}")
                print(response.text[:500])
                return None
                
        except Exception as e:
            print(f"❌ Request failed: {e}")
            return None
    
    def parse_results(self, data):
        """Parse and display search results"""
        if not data:
            return []
        
        songs = []
        
        try:
            # Check if results exist
            if "results" not in data:
                print("⚠ No results found")
                return []
            
            results = data["results"]
            
            print(f"\n{'='*70}")
            print(f"🎵 Found {len(results)} Songs")
            print(f"{'='*70}\n")
            
            for idx, song in enumerate(results, 1):
                # Extract song information
                song_info = {
                    'title': song.get('title', 'Unknown'),
                    'subtitle': song.get('subtitle', ''),
                    'id': song.get('id', ''),
                    'url': song.get('url', ''),
                    'image': song.get('image', ''),
                    'language': song.get('language', ''),
                    'year': song.get('year', ''),
                    'play_count': song.get('play_count', ''),
                    'primary_artists': song.get('primary_artists', ''),
                    'singers': song.get('singers', ''),
                    'type': song.get('type', ''),
                    'perma_url': song.get('perma_url', ''),
                    'more_info': song.get('more_info', {})
                }
                
                songs.append(song_info)
                
                # Display song info
                print(f"{idx}. {song_info['title']}")
                print(f"   👤 Artists: {song_info['primary_artists']}")
                print(f"   📀 Album/Subtitle: {song_info['subtitle']}")
                print(f"   🆔 ID: {song_info['id']}")
                print(f"   🔗 URL: {song_info['perma_url']}")
                print(f"   🖼️  Image: {song_info['image']}")
                print(f"   🗣️  Language: {song_info['language']}")
                print(f"   📅 Year: {song_info['year']}")
                print(f"   ▶️  Plays: {song_info['play_count']}")
                print(f"   🎤 Singers: {song_info['singers']}")
                print("-" * 70)
            
        except Exception as e:
            print(f"❌ Error parsing results: {e}")
        
        return songs
    
    def get_song_details(self, song_id):
        """Get detailed information about a specific song"""
        
        params = {
            "pids": song_id,
            "_format": "json",
            "_marker": "0",
            "api_version": "4",
            "ctx": "wap6dot0",
            "__call": "song.getDetails"
        }
        
        url = f"{self.base_url}?pids={song_id}&_format=json&_marker=0&api_version=4&ctx=wap6dot0&__call=song.getDetails"
        
        print(f"\n📥 Fetching details for song ID: {song_id}")
        
        try:
            response = requests.get(url, headers=self.headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Error: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Request failed: {e}")
            return None


def main():
    print("="*70)
    print("JioSaavn Song Search")
    print("="*70)
    
    # Initialize API
    api = JioSaavnAPI()
    
    # Get search query
    search_query = input("\n🔍 Enter song name to search: ").strip()
    
    if not search_query:
        search_query = "love me again"  # Default
        print(f"Using default search: {search_query}")
    
    # Search for songs
    results = api.search_songs(search_query)
    
    if results:
        # Parse and display results
        songs = api.parse_results(results)
        
        if songs:
            print(f"\n{'='*70}")
            print(f"✓ Total songs found: {len(songs)}")
            print(f"{'='*70}")
            
            # Save results to file
            output_file = "jiosaavn_search_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(songs, f, indent=2, ensure_ascii=False)
            print(f"✓ Results saved to {output_file}")
            
            # Save full response
            full_response_file = "jiosaavn_full_response.json"
            with open(full_response_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"✓ Full response saved to {full_response_file}")
            
            # Ask if user wants song details
            print(f"\n{'='*70}")
            get_details = input("Do you want to get details for any song? (Enter song number or 'n' to skip): ").strip()
            
            if get_details.isdigit():
                song_index = int(get_details) - 1
                if 0 <= song_index < len(songs):
                    song_id = songs[song_index]['id']
                    details = api.get_song_details(song_id)
                    
                    if details:
                        print(f"\n{'='*70}")
                        print(f"Song Details:")
                        print(f"{'='*70}")
                        print(json.dumps(details, indent=2))
                        
                        # Save details
                        details_file = f"song_details_{song_id}.json"
                        with open(details_file, "w", encoding="utf-8") as f:
                            json.dump(details, f, indent=2, ensure_ascii=False)
                        print(f"\n✓ Details saved to {details_file}")
                else:
                    print("❌ Invalid song number")
        else:
            print("⚠ No songs found")
    else:
        print("❌ Search failed")


if __name__ == "__main__":
    main()
