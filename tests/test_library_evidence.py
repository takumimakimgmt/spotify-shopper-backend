import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from app import TrackModel
from lib.rekordbox.matcher import mark_owned_tracks


def test_match_evidence_is_scoped_to_exact_export_and_contains_no_file_paths():
    xml = b'<DJ_PLAYLISTS><COLLECTION><TRACK Name="Song" Artist="A" Location="file://private/library.wav"/></COLLECTION></DJ_PLAYLISTS>'
    with TemporaryDirectory() as directory:
        path = Path(directory) / "library.xml"
        path.write_bytes(xml)
        result = mark_owned_tracks(
            {
                "tracks": [
                    {"title": "Song", "artist": "A"},
                    {"title": "Missing", "artist": "B"},
                    {"title": "Song", "artist": "A & C"},
                ]
            },
            path,
        )
    evidence = [
        TrackModel.model_validate(t).model_dump()["library_match"]
        for t in result["tracks"]
    ]
    assert [e["status"] for e in evidence] == ["matched", "not_found", "review"]
    assert evidence[0]["matched_title"] == "Song"
    assert evidence[1]["reason"] == "no_match"
    assert evidence[2]["reason"] == "artist_mismatch"
    meta = result["meta"]["rekordbox"]
    assert meta["scope"] == "selected_xml"
    assert meta["library_track_count"] == 1
    assert meta["library_sha256"] == hashlib.sha256(xml).hexdigest()
    assert meta["matched_at"]
    assert "file://" not in str(evidence)
