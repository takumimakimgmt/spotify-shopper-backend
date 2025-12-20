#!/usr/bin/env python3
"""
Initial delay diagnosis tool.
Measures: API call time, Playwright cold start, backend processing.
"""
import time
import requests
import json

BACKEND_URL = "http://127.0.0.1:8000"
TEST_SPOTIFY_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"  # Small playlist
TEST_APPLE_URL = "https://music.apple.com/jp/playlist/ampm-thinking-may/pl.024712183de946b7be5ba1267d94e035"

def measure_request(url, source, label):
    """Measure a single API request."""
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")
    
    # Frontend timing simulation
    t1_start = time.time()
    
    # Measure TTFB (Time To First Byte)
    t2_ttfb_start = time.time()
    try:
        response = requests.get(
            f"{BACKEND_URL}/api/playlist",
            params={"url": url, "source": source, "refresh": "1"},
            timeout=120,
            stream=True
        )
        # First byte received
        t3_ttfb_done = time.time()
        ttfb_ms = (t3_ttfb_done - t2_ttfb_start) * 1000
        
        # Read full response
        data = response.json()
        t4_response_done = time.time()
        response_time_ms = (t4_response_done - t2_ttfb_start) * 1000
        total_time_ms = (t4_response_done - t1_start) * 1000
        
        # Extract meta
        meta = data.get("meta", {})
        fetch_ms = meta.get("fetch_ms", 0)
        total_backend_ms = meta.get("total_backend_ms", 0)
        
        # Results
        print(f"\n📊 Timing Breakdown:")
        print(f"  TTFB (Time To First Byte):  {ttfb_ms:8.1f} ms")
        print(f"  Full Response:              {response_time_ms:8.1f} ms")
        print(f"  Total (client-side):        {total_time_ms:8.1f} ms")
        print(f"\n🔧 Backend Metrics:")
        print(f"  fetch_ms:                   {fetch_ms:8.1f} ms")
        print(f"  total_backend_ms:           {total_backend_ms:8.1f} ms")
        print(f"\n⚡ Analysis:")
        overhead_ms = response_time_ms - total_backend_ms
        print(f"  Backend processing:         {total_backend_ms:8.1f} ms ({total_backend_ms/response_time_ms*100:5.1f}%)")
        print(f"  Network + overhead:         {overhead_ms:8.1f} ms ({overhead_ms/response_time_ms*100:5.1f}%)")
        
        if source == "apple":
            apple_mode = meta.get("apple_mode")
            apple_strategy = meta.get("apple_strategy")
            apple_extraction = meta.get("apple_extraction_method")
            print(f"\n🍎 Apple Details:")
            print(f"  Mode: {apple_mode}, Strategy: {apple_strategy}, Extraction: {apple_extraction}")
        
        tracks_count = len(data.get("tracks", []))
        print(f"\n✅ Result: {tracks_count} tracks extracted")
        
        return {
            "ttfb_ms": ttfb_ms,
            "response_time_ms": response_time_ms,
            "backend_ms": total_backend_ms,
            "fetch_ms": fetch_ms,
            "tracks": tracks_count
        }
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None

def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║  Initial Delay Diagnosis Tool                                ║
║  Identifies bottleneck: API / Playwright / Cold Start / FE   ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Test 1: Spotify (warm - should be fast)
    spotify_result = measure_request(TEST_SPOTIFY_URL, "spotify", "TEST 1: Spotify (Warm Run)")
    time.sleep(2)
    
    # Test 2: Apple Music (cold start)
    print("\n\n⏳ Restarting backend to simulate cold start...")
    print("   (In production, this would be after Render/Vercel cold start)")
    input("   Press Enter when backend is restarted (pkill uvicorn && uvicorn app:app)...")
    
    apple_cold = measure_request(TEST_APPLE_URL, "apple", "TEST 2: Apple Music (Cold Start)")
    time.sleep(2)
    
    # Test 3: Apple Music (warm)
    apple_warm = measure_request(TEST_APPLE_URL, "apple", "TEST 3: Apple Music (Warm Run)")
    
    # Summary
    print(f"\n\n{'='*60}")
    print("📈 SUMMARY")
    print(f"{'='*60}")
    
    if spotify_result:
        print(f"\nSpotify (warm): {spotify_result['response_time_ms']:.0f}ms total")
        print(f"  - Backend: {spotify_result['backend_ms']:.0f}ms")
        print(f"  - Overhead: {spotify_result['response_time_ms'] - spotify_result['backend_ms']:.0f}ms")
    
    if apple_cold:
        print(f"\nApple (cold):   {apple_cold['response_time_ms']:.0f}ms total")
        print(f"  - Backend: {apple_cold['backend_ms']:.0f}ms")
        print(f"  - TTFB: {apple_cold['ttfb_ms']:.0f}ms")
        print(f"  - Overhead: {apple_cold['response_time_ms'] - apple_cold['backend_ms']:.0f}ms")
    
    if apple_warm:
        print(f"\nApple (warm):   {apple_warm['response_time_ms']:.0f}ms total")
        print(f"  - Backend: {apple_warm['backend_ms']:.0f}ms")
        print(f"  - TTFB: {apple_warm['ttfb_ms']:.0f}ms")
        print(f"  - Overhead: {apple_warm['response_time_ms'] - apple_warm['backend_ms']:.0f}ms")
    
    if apple_cold and apple_warm:
        cold_start_penalty = apple_cold['response_time_ms'] - apple_warm['response_time_ms']
        print(f"\n🎯 Cold Start Penalty: {cold_start_penalty:.0f}ms")
        
        if cold_start_penalty > 3000:
            print(f"\n⚠️  BOTTLENECK IDENTIFIED: Playwright Cold Start")
            print(f"   - Recommendation: Keep browser warm or implement connection pooling")
        elif apple_cold['backend_ms'] > 15000:
            print(f"\n⚠️  BOTTLENECK IDENTIFIED: Apple Scraping (Playwright execution)")
            print(f"   - Recommendation: Optimize scroll loop or implement caching")
        elif spotify_result and spotify_result['response_time_ms'] > 2000:
            print(f"\n⚠️  BOTTLENECK IDENTIFIED: API call")
            print(f"   - Recommendation: Check network/Spotify API latency")
        else:
            print(f"\n✅ No major bottleneck detected (all < 2s)")

if __name__ == "__main__":
    main()
