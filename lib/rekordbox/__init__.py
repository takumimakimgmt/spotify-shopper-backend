"""
Rekordbox library parsing and matching.

Public API:
  - mark_owned_tracks(playlist_data, rekordbox_xml_path) -> dict
  - load_rekordbox_library_xml(path, timeout_sec) -> RekordboxLibrary
"""
from lib.rekordbox.matcher import mark_owned_tracks
from lib.rekordbox.parser import load_rekordbox_library_xml
from lib.rekordbox.models import RekordboxLibrary, RekordboxTrack, OwnedDetail, MatchMethod

__all__ = [
    "mark_owned_tracks",
    "load_rekordbox_library_xml",
    "RekordboxLibrary",
    "RekordboxTrack",
    "OwnedDetail",
    "MatchMethod",
]
