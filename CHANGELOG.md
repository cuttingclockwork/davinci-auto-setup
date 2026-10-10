# Changelog

## 1.0.0 (unreleased)

First public version.

- One folder of footage becomes a synced, colour-managed timeline: 16:9 (YouTube Timeline) or 9:16 (Reels Timeline).
- Works with any camera brand; colour profile per camera from metadata or the `CAMERA_PROFILES` setting.
- Syncs cameras by sound, also when their clocks are hours off.
- Measures the sound of every camera and keeps the cleanest one audible.
- Warns about mixed frame rates and centre-cropped landscape clips.
- macOS and Windows.
- Automated test suite (`tests/`) and a quality report ([QUALITY.md](QUALITY.md)).
