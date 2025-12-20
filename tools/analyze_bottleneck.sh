#!/usr/bin/env bash
# Automatic bottleneck detection from [PERF] logs
# Usage: bash tools/analyze_bottleneck.sh < /path/to/backend.log

set -euo pipefail

echo "=== Bottleneck Analysis Tool ==="
echo ""

# Parse [PERF] logs and extract metrics
awk '
/\[PERF\]/ {
  # Extract all key=value pairs
  delete metrics
  for (i=1; i<=NF; i++) {
    if (match($i, /^([^=]+)=([0-9.]+)/, arr)) {
      metrics[arr[1]] = arr[2]
    }
  }
  
  source = metrics["source"]
  fetch_ms = metrics["fetch_ms"]
  enrich_ms = metrics["enrich_ms"]
  total_backend_ms = metrics["total_backend_ms"]
  total_api_ms = metrics["total_api_ms"]
  tracks = metrics["tracks"]
  
  # Calculate overhead
  overhead_ms = total_api_ms - total_backend_ms
  
  # Categorize by source
  if (source == "spotify") {
    spotify_count++
    spotify_total += total_api_ms
    spotify_fetch += fetch_ms
    spotify_enrich += enrich_ms
  } else if (source == "apple") {
    apple_count++
    apple_total += total_api_ms
    apple_fetch += fetch_ms
    apple_enrich += enrich_ms
  }
  
  # Track max values
  if (total_api_ms > max_total_ms) {
    max_total_ms = total_api_ms
    max_source = source
    max_fetch = fetch_ms
    max_backend = total_backend_ms
    max_overhead = overhead_ms
  }
}

END {
  print "📊 Backend Performance Summary"
  print "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  print ""
  
  if (spotify_count > 0) {
    spotify_avg = spotify_total / spotify_count
    spotify_fetch_avg = spotify_fetch / spotify_count
    printf "Spotify (%d requests):\n", spotify_count
    printf "  Avg total:  %8.1f ms\n", spotify_avg
    printf "  Avg fetch:  %8.1f ms\n", spotify_fetch_avg
    printf "  Avg enrich: %8.1f ms\n", spotify_enrich / spotify_count
    print ""
  }
  
  if (apple_count > 0) {
    apple_avg = apple_total / apple_count
    apple_fetch_avg = apple_fetch / apple_count
    printf "Apple Music (%d requests):\n", apple_count
    printf "  Avg total:  %8.1f ms\n", apple_avg
    printf "  Avg fetch:  %8.1f ms\n", apple_fetch_avg
    printf "  Avg enrich: %8.1f ms\n", apple_enrich / apple_count
    print ""
  }
  
  if (max_total_ms > 0) {
    print "🔍 Worst Case Analysis"
    print "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf "Source:           %s\n", max_source
    printf "Total API time:   %8.1f ms\n", max_total_ms
    printf "  - Backend:      %8.1f ms (%5.1f%%)\n", max_backend, (max_backend/max_total_ms)*100
    printf "  - Overhead:     %8.1f ms (%5.1f%%)\n", max_overhead, (max_overhead/max_total_ms)*100
    printf "  - Fetch:        %8.1f ms (%5.1f%%)\n", max_fetch, (max_fetch/max_total_ms)*100
    print ""
  }
  
  # Bottleneck identification
  print "🎯 Bottleneck Identification"
  print "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  
  if (apple_count > 0 && apple_avg > 15000) {
    print "⚠️  PRIMARY BOTTLENECK: Apple Music Playwright Scraping"
    printf "   Current avg: %.0f ms (target: <10s)\n", apple_avg
    print ""
    print "📋 Recommended Actions:"
    print "   1. Keep Playwright browser warm (connection pooling)"
    print "   2. Optimize scroll loop (reduce wait times)"
    print "   3. Implement cache for frequent playlists"
    print ""
  } else if (spotify_count > 0 && spotify_avg > 2000) {
    print "⚠️  PRIMARY BOTTLENECK: Spotify API"
    printf "   Current avg: %.0f ms (target: <1s)\n", spotify_avg
    print ""
    print "📋 Recommended Actions:"
    print "   1. Implement TTL cache (6-24h)"
    print "   2. Check network latency"
    print "   3. Consider batch API calls"
    print ""
  } else if (max_overhead > 500) {
    print "⚠️  PRIMARY BOTTLENECK: Network/Overhead"
    printf "   Max overhead: %.0f ms\n", max_overhead
    print ""
    print "📋 Recommended Actions:"
    print "   1. Optimize JSON serialization"
    print "   2. Enable gzip compression"
    print "   3. Check frontend TTFB"
    print ""
  } else {
    print "✅ No major bottleneck detected"
    print "   All metrics within acceptable range"
    print ""
  }
}
' | cat

echo ""
echo "💡 To collect fresh data:"
echo "   1. Restart backend: pkill uvicorn && uvicorn app:app"
echo "   2. Run tests and save logs: uvicorn app:app 2>&1 | tee backend.log"
echo "   3. Analyze: bash tools/analyze_bottleneck.sh < backend.log"
