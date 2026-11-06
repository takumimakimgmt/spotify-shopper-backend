"""Stable public errors: never return provider messages, tokens or credentials."""

from spotipy.exceptions import SpotifyException, SpotifyOauthError


class SpotifyConfigurationError(RuntimeError):
    pass


def spotify_error_details(error):
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (SpotifyConfigurationError, SpotifyOauthError)):
            return 503, "SPOTIFY_AUTH_CONFIG", {}
        if isinstance(current, SpotifyException):
            status = current.http_status
            if status == 401:
                return 503, "SPOTIFY_AUTH_CONFIG", {}
            if status == 400:
                return 400, "SPOTIFY_PLAYLIST_RESTRICTED", {}
            if status == 403:
                return 403, "SPOTIFY_ACCESS_RESTRICTED", {}
            if status == 404:
                return 404, "SPOTIFY_PLAYLIST_UNAVAILABLE", {}
            if status == 429:
                raw = str((current.headers or {}).get("Retry-After", "60"))
                wait = min(86400, max(1, int(raw))) if raw.isdigit() else 60
                return 429, "SPOTIFY_RATE_LIMITED", {"Retry-After": str(wait)}
            if status and status >= 500:
                return 502, "SPOTIFY_UNAVAILABLE", {}
        current = current.__cause__ or current.__context__
    return None
