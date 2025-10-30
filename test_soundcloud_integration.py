"""
Test SoundCloud Integration for Web Interface

This script tests the SoundCloud search and verifies that artwork URLs
and other metadata are properly retrieved.
"""

import soundcloud
import json

def test_soundcloud_search():
    print("="*70)
    print("Testing SoundCloud Integration")
    print("="*70)
    
    # Test search
    search_query = "follow"
    print(f"\n🔍 Testing search: '{search_query}'")
    
    try:
        # Get tracks
        tracks = soundcloud.soundcloud_search(search_query, limit=5)
        
        if tracks:
            print(f"\n✅ Found {len(tracks)} tracks")
            
            # Show what web interface will receive
            print("\n" + "="*70)
            print("SoundCloud Data for Web Interface:")
            print("="*70)
            
            for idx, track in enumerate(tracks, 1):
                print(f"\nTrack {idx}:")
                print(f"  Title: {track.get('title')}")
                print(f"  Artist: {track.get('uploader')}")
                print(f"  URL: {track.get('url')}")
                print(f"  Artwork: {track.get('artwork_url', 'NO ARTWORK')}")
                print(f"  Duration: {track.get('duration_ms', 0) // 60000}:{(track.get('duration_ms', 0) % 60000) // 1000:02d}")
                print(f"  Plays: {track.get('playback_count', 0):,}")
                print(f"  Likes: {track.get('likes_count', 0):,}")
                print(f"  Genre: {track.get('genre', 'N/A')}")
                
                # Format for web interface
                duration_ms = track.get('duration_ms', 0)
                duration = f"{duration_ms // 60000}:{(duration_ms % 60000) // 1000:02d}" if duration_ms else "0:00"
                
                artwork_url = track.get('artwork_url', '')
                if artwork_url:
                    artwork_url = artwork_url.replace('-large.', '-t500x500.')
                
                web_data = {
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
                }
                
                print("\n  📦 Web Interface JSON:")
                print("  " + json.dumps(web_data, indent=4).replace('\n', '\n  '))
                
                # Check if artwork exists
                if web_data['thumbnail']:
                    print(f"\n  ✅ Artwork URL exists!")
                    print(f"  🖼️  {web_data['thumbnail']}")
                else:
                    print(f"\n  ⚠️  NO ARTWORK URL - will use fallback")
                
                print("-" * 70)
            
            # Check overall
            with_artwork = sum(1 for t in tracks if t.get('artwork_url'))
            print(f"\n📊 Summary:")
            print(f"  Total tracks: {len(tracks)}")
            print(f"  With artwork: {with_artwork}")
            print(f"  Without artwork: {len(tracks) - with_artwork}")
            
            if with_artwork > 0:
                print(f"\n✅ All tests passed! Artwork URLs are being fetched.")
            else:
                print(f"\n⚠️  Warning: No artwork URLs found. Check SoundCloud API response.")
            
        else:
            print("❌ No tracks returned")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_soundcloud_search()
