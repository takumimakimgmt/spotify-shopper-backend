# Rekordbox XML Upload Limits (Backend)

## Current Design Decision

**Max Size: 50 MB (Default, Configurable via Environment Variable)**

### Configuration

Set `REKORDBOX_MAX_XML_MB` environment variable to adjust limit:

```bash
export REKORDBOX_MAX_XML_MB=75  # Increase to 75 MB
uvicorn app:app --reload
```

Default: `50` (MB)

### Rationale

- **Data Point**: 2,226 tracks ≈ 2.39 MB  
  Extrapolation: ~50,000 tracks ≈ ~50 MB (largest personal library)
- **50 MB Limit Benefits**:
  - Safe margin for most users (up to ~50,000 tracks)
  - Avoids memory bloat during XML parsing
  - Prevents accidental uploads of entire music library
  - Fast parsing (<500ms for typical libraries)

### Error Handling

When file exceeds limit:
```
OverflowError: Rekordbox XML exceeds 50MB limit (55.3MB). 
See docs/REKORDBOX_XML_LIMITS.md for guidance.
```

**User Action**: Export smaller playlist-level XML from Rekordbox instead of entire library.

### Performance Metrics

| Library Size | Tracks | Parse Time |
|--------------|--------|------------|
| 2.4 MB       | ~2,200 | ~150ms     |
| 10 MB        | ~10,000| ~300ms     |
| 50 MB        | ~50,000| ~900-1200ms (estimate) |

### Future Scaling

If demand arises for >50k track support:
1. **Option A**: Raise limit to 100 MB + implement streaming XML parse (iterparse)
2. **Option B**: Support multi-file uploads (e.g., 5 playlists × 4MB each)
3. **Option C**: Add chunked processing with progress feedback

### Implementation

See: `lib/rekordbox/parser.py`
- `MAX_XML_SIZE_BYTES`: Read from `REKORDBOX_MAX_XML_MB` env var
- Guard: Checks file size before parsing, raises `OverflowError`
