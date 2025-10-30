"""
YouTube Music Search - Using Dynamic Token Extraction

This script uses the YouTubeMusicAPI class from ytmusic_dynamic_tokens.py
to automatically extract fresh tokens and search for songs.

Usage:
    python ytmusic_api_request.py
"""

from ytmusic_dynamic_tokens import YouTubeMusicAPI
import json

def main():
    print("="*70)
    print("YouTube Music Search with Dynamic Token Extraction")
    print("="*70)
    
    # Initialize the API
    api = YouTubeMusicAPI()
    
    # Get search query from user
    search_query = input("\n🔍 Enter song name to search: ").strip()
    
    if not search_query:
        search_query = "follow follow song"  # Default
        print(f"Using default search: {search_query}")
    
    # ===== AUTOMATIC MODE (with fallback) =====
    # Try static tokens first (faster), then fallback to fresh tokens if it fails
    print("\n" + "="*70)
    print("🚀 Trying fast mode (static tokens)...")
    results = api.search(search_query, use_fresh_tokens=False)
    
    # If failed, automatically fallback to fresh tokens
    if not results or results.get("error"):
        print("⚠️  Static tokens failed or expired!")
        print("🔄 Automatically switching to fresh tokens mode...")
        results = api.search(search_query, use_fresh_tokens=True)
    
    # ===== MANUAL MODE (commented out) =====
    # Uncomment below to manually choose mode each time
    """
    # Choose mode
    print("\nSelect mode:")
    print("1. Use fresh tokens (slower, always works)")
    print("2. Use static tokens (faster, may expire)")
    mode = input("Enter choice (1 or 2): ").strip()
    
    use_fresh = mode != "2"
    
    # Perform search
    print("\n" + "="*70)
    results = api.search(search_query, use_fresh_tokens=use_fresh)
    """
    
    if results:
        # Parse and display results
        songs = api.parse_search_results(results)
        
        if songs:
            print(f"\n{'='*70}")
            print(f"✓ Found {len(songs)} songs")
            print(f"{'='*70}")
            
            # Save results to file
            output_file = "search_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(songs, f, indent=2, ensure_ascii=False)
            print(f"✓ Results saved to {output_file}")
            
            # Save full response
            full_response_file = "ytmusic_response.json"
            with open(full_response_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"✓ Full response saved to {full_response_file}")
            
            # Show first 3 songs
            print(f"\n{'='*70}")
            print("Top 3 Results:")
            print(f"{'='*70}\n")
            
            for i, song in enumerate(songs[:3], 1):
                print(f"{i}. {song['title']}")
                print(f"   🔗 {song['url']}")
                print(f"   ℹ️  {song['metadata']}\n")
        else:
            print("⚠ No songs found in search results")
    else:
        print("❌ Search failed")

if __name__ == "__main__":
    main()
