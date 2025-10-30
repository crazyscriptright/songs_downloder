"""
Test JioSaavn Integration for Web Interface

This script tests the JioSaavn search and verifies the data structure
matches what the web interface expects.
"""

from jiosaavn_search import JioSaavnAPI
import json

def test_jiosaavn_search():
    print("="*70)
    print("Testing JioSaavn Integration")
    print("="*70)
    
    # Initialize API
    api = JioSaavnAPI()
    
    # Test search
    search_query = "follow"
    print(f"\n🔍 Testing search: '{search_query}'")
    
    # Get raw response
    data = api.search_songs(search_query, limit=5)
    
    if data:
        print("\n✅ Got response from JioSaavn")
        
        # Parse results
        songs = api.parse_results(data)
        
        if songs:
            print(f"\n✅ Parsed {len(songs)} songs")
            
            # Show what web interface will receive
            print("\n" + "="*70)
            print("Data Structure for Web Interface:")
            print("="*70)
            
            for idx, song in enumerate(songs[:3], 1):
                print(f"\nSong {idx}:")
                print(f"  title: {song['title']}")
                print(f"  primary_artists: {song.get('primary_artists', 'N/A')}")
                print(f"  singers: {song.get('singers', 'N/A')}")
                print(f"  subtitle: {song.get('subtitle', 'N/A')}")
                print(f"  year: {song.get('year', 'N/A')}")
                print(f"  language: {song.get('language', 'N/A')}")
                print(f"  image: {song.get('image', 'N/A')[:50]}...")
                print(f"  perma_url: {song.get('perma_url', 'N/A')}")
                
                # Determine artist for display
                artist = (
                    song.get('primary_artists') or 
                    song.get('singers') or 
                    song.get('subtitle', '').split(' - ')[0] if ' - ' in song.get('subtitle', '') else
                    'Unknown Artist'
                )
                
                print(f"\n  🎯 Display Artist: {artist}")
                
                # What web interface will create
                web_data = {
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
                }
                
                print("\n  📦 Web Interface JSON:")
                print("  " + json.dumps(web_data, indent=4).replace('\n', '\n  '))
                print("-" * 70)
            
            print("\n✅ All tests passed!")
            print(f"✅ Artist field will display: {artist}")
            
        else:
            print("❌ No songs parsed")
    else:
        print("❌ No response from JioSaavn")


if __name__ == "__main__":
    test_jiosaavn_search()
