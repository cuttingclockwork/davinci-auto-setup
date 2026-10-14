# Changelog

## 1.1.0 (unreleased)

- **New script: Export for AI Review.** Exports the open timeline as an MP4 with sound for feedback from Gemini, ChatGPT or Claude, then puts the Deliver page back and checks it. Exports at the timeline's resolution; MP4 codec settings are kept; other formats such as ProRes become MP4/H.264 for this export. Whole timeline or In/Out range (`RANGE`), never overwrites a file, never changes your file name setting.
- The timeline scripts are unchanged apart from the version number.
- Tested on 14 October 2026 in DaVinci Resolve Studio 21.1.1 on macOS on a disposable project: an MP4/H.265 preset whose codec Resolve reports as empty, ProRes 422 HQ with 24-bit LPCM audio, an In/Out range, and a fixed Deliver size different from the timeline. Every readable Deliver setting was identical afterwards, the "Timeline Name" file name still followed the timeline, and no jobs, presets, marks or temporary folders were left behind. Not yet tested: Windows, the free version of Resolve, and starting it from the Workspace menu by a user.

## 1.0.0 (unreleased)

First public version.

- One folder of footage becomes a synced, colour-managed timeline: 16:9 (YouTube Timeline) or 9:16 (Reels Timeline).
- Works with any camera brand; colour profile per camera from metadata or the `CAMERA_PROFILES` setting.
- Syncs cameras by sound, also when their clocks are hours off.
- Measures the sound of every camera and keeps the cleanest one audible.
- Warns about mixed frame rates and centre-cropped landscape clips.
- macOS and Windows.
- Automated test suite (`tests/`) and a quality report ([QUALITY.md](QUALITY.md)).
