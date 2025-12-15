#!/usr/bin/env python3
"""
Test script to reproduce Spotify authentication failures.
Tests both direct token request and spotipy client.
"""

import os
import sys
import base64
import requests
from dotenv import load_dotenv

# Load .env file if it exists
env_file = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_file):
    print(f"✓ Loading .env from: {env_file}")
    load_dotenv(env_file)
else:
    print(f"⚠ No .env file found at: {env_file}")

# Load .env.local as fallback
env_local_file = os.path.join(os.path.dirname(__file__), '.env.local')
if os.path.exists(env_local_file):
    print(f"✓ Loading .env.local from: {env_local_file}")
    load_dotenv(env_local_file, override=True)

print("\n" + "="*60)
print("ENVIRONMENT VARIABLES CHECK")
print("="*60)

client_id = os.getenv("SPOTIFY_CLIENT_ID")
client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")

print(f"SPOTIFY_CLIENT_ID: {client_id[:10] + '...' if client_id else 'NOT SET'}")
print(f"SPOTIFY_CLIENT_SECRET: {client_secret[:10] + '...' if client_secret else 'NOT SET'}")

if not client_id or not client_secret:
    print("\n❌ ERROR: Spotify credentials not set!")
    print("Please create a .env file with:")
    print("SPOTIFY_CLIENT_ID=your_client_id")
    print("SPOTIFY_CLIENT_SECRET=your_client_secret")
    sys.exit(1)

print("\n" + "="*60)
print("TEST 1: Direct Spotify Token Request (client_credentials)")
print("="*60)

# Prepare credentials
auth_string = f"{client_id}:{client_secret}"
auth_bytes = auth_string.encode("utf-8")
auth_base64 = base64.b64encode(auth_bytes).decode("utf-8")

# Make token request
token_url = "https://accounts.spotify.com/api/token"
headers = {
    "Authorization": f"Basic {auth_base64}",
    "Content-Type": "application/x-www-form-urlencoded"
}
data = {"grant_type": "client_credentials"}

print(f"POST {token_url}")
print(f"Authorization: Basic {auth_base64[:20]}...")
print(f"Data: {data}")

try:
    response = requests.post(token_url, headers=headers, data=data)
    print(f"\nStatus Code: {response.status_code}")
    print(f"Response Headers: {dict(response.headers)}")
    print(f"Response Body: {response.text}")
    
    if response.status_code == 200:
        token_data = response.json()
        if "access_token" in token_data:
            print(f"\n✓ SUCCESS: Got access_token (first 20 chars): {token_data['access_token'][:20]}...")
            print(f"  Token Type: {token_data.get('token_type')}")
            print(f"  Expires In: {token_data.get('expires_in')} seconds")
        else:
            print("\n❌ UNEXPECTED: 200 but no access_token in response")
    else:
        print(f"\n❌ FAILED: HTTP {response.status_code}")
        if response.status_code == 400:
            error_data = response.json()
            if error_data.get("error") == "invalid_client":
                print("  Error: invalid_client")
                print("  This means the client_id or client_secret is incorrect!")
except Exception as e:
    print(f"\n❌ EXCEPTION: {e}")

print("\n" + "="*60)
print("TEST 2: Spotipy Client Test")
print("="*60)

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    
    print("Creating SpotifyClientCredentials...")
    auth_manager = SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret
    )
    
    print("Creating Spotify client...")
    sp = spotipy.Spotify(auth_manager=auth_manager)
    
    print("Testing with a public playlist (Spotify Top 50 Global)...")
    test_playlist_id = "37i9dQZEVXbMDoHDwVN2tF"  # Global Top 50
    
    result = sp.playlist(test_playlist_id, fields="id,name,external_urls")
    print(f"\n✓ SUCCESS: Retrieved playlist")
    print(f"  ID: {result['id']}")
    print(f"  Name: {result['name']}")
    print(f"  URL: {result['external_urls']['spotify']}")
    
except Exception as e:
    print(f"\n❌ EXCEPTION: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("TEST 3: FastAPI Endpoint Test (requires server running)")
print("="*60)

base_url = os.getenv("NEXT_PUBLIC_API_BASE_URL", "http://127.0.0.1:8000")
test_playlist_url = "https://open.spotify.com/playlist/37i9dQZEVXbMDoHDwVN2tF"

print(f"Testing: GET {base_url}/api/playlist?url={test_playlist_url}")
print("(Note: This requires the server to be running on port 8000)")

try:
    response = requests.get(
        f"{base_url}/api/playlist",
        params={"url": test_playlist_url},
        timeout=10
    )
    print(f"\nStatus Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✓ SUCCESS: Got playlist data")
        print(f"  Playlist Name: {data.get('playlist_name')}")
        print(f"  Track Count: {len(data.get('tracks', []))}")
    else:
        print(f"❌ FAILED: HTTP {response.status_code}")
        print(f"Response: {response.text}")
except requests.exceptions.ConnectionError:
    print("\n⚠ Server not running (connection refused)")
    print("  Start server with: uvicorn app:app --host 127.0.0.1 --port 8000")
except Exception as e:
    print(f"\n❌ EXCEPTION: {e}")

print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print("Check the results above to identify authentication issues.")
print("If you see 'invalid_client', your credentials are incorrect.")
print("="*60)
