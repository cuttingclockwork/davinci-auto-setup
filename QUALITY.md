# Quality report

This file records the checks behind each release. The code is written by Claude (Anthropic's AI assistant); Cutting Clockwork tests it on real footage.

## 1.1.0 — Export for AI Review, checks of 14 October 2026

**Safety rules**, verified by reading the full code:

| Rule | Result |
|---|---|
| Source footage and projects are never changed | Passed. The script only reads the timeline and changes Deliver settings temporarily; it puts them back and checks them. |
| Deleting only in the tool's own folder | Passed. It removes its own render job, its own backup preset (only after a verified restore) and its own empty temporary folder (`os.rmdir`, which refuses a folder with files in it). The MP4 is moved, never deleted. |
| External programs without a shell | Passed. Only `open` / `explorer` to show the result, with an argument list. |
| No internet connections | Passed. |
| No keys, personal paths or e-mail addresses | Passed. |
| Existing files are never overwritten | Passed. A number is added to the name. |

**Design choices after tests in Resolve Studio 21.1.1** (see `github/BEVINDINGEN.md` in the project notes):
- The file name setting (`CustomName`) is never set: once a script sets it, Resolve cannot bring back the "Timeline Name" token, and no check can see the difference. The script renders into its own empty folder instead and renames the file afterwards.
- Resolution, frame rate and quality are not touched; an MP4 setting is used as it is. Only the range, the target folder, "export video/audio" and, for non-MP4 formats, the format and codec change.
- Switching to MP4 resets the audio to AAC 32-bit and a preset doesn't restore it, so audio fields are restored one by one.
- Some presets make Resolve report an empty codec; the codec is then taken from a render job by name.
- The Deliver page is restored before the render starts (the job keeps its own settings) and once more afterwards.

**Automatic code checks:** Ruff (F, E9, B, PLE, PLW): no findings. Bandit (medium and high): no findings.

**Automated tests:** 14 new tests (34 in total, all passing): export range including single In or Out marks and bad marks, file names, never overwriting, and the Deliver restore against a stand-in that reproduces the audio reset, the empty codec and the unrecoverable file name token.

**Real-world test (Claude, through the Resolve MCP, on a disposable project):** passed for an MP4/H.265 preset with an empty reported codec (3.4 s for a 19.7 s 1080×1920 timeline), ProRes 422 HQ with 24-bit LPCM, and an In/Out range (10–300) with `RANGE = 'marks'` (11.7 s file). Every readable Deliver setting identical afterwards; marks unchanged; the file name token still followed a renamed timeline; no render jobs, backup presets or temporary folders left. Not yet tested: a run started by a user from Workspace › Scripts (including the folder dialog and the Finder window), Windows and the free version of Resolve.

## 1.0.0 — checks of 10 October 2026

**Safety rules**, verified by reading the full code:

| Rule | Result |
|---|---|
| Source footage is never changed, moved or deleted | Passed. Files are only read (FFprobe, FFmpeg, Resolve import). |
| Deleting only in the tool's own folder | Passed. The only deletions are the script's own sound-analysis cache files (`*.bin`, capped at 256 MB) in `~/Library/Caches/Resolve Timeline Scripts` (macOS) or `%LOCALAPPDATA%` (Windows). |
| External programs without a shell | Passed. FFmpeg and FFprobe get an argument list; file names can't be interpreted as commands. |
| No internet connections | Passed. |
| No keys, personal paths or e-mail addresses | Passed (code and git history). |
| Existing projects stay intact | Passed. The current project is saved, then a new project is created. An unsaved "Untitled Project" with content stops the script instead of being lost. |

**Automatic code checks**
- Ruff (error rules F, E9, B, PLE, PLW): no errors. Remaining notes are harmless: one unused variable, a deliberately reused loop variable, `zip()` without `strict=`, and `subprocess.run` without `check=` (the return code is checked by hand).
- Bandit (medium and high): one note, `xml.etree` parsing of the Sony XML sidecar. Accepted: the file sits next to the user's own footage and is only used when it matches the recording; a hostile XML file in your own footage folder is not a realistic risk.
- Minimum Python version according to the code: 3.7. The README asks for 3.10 or newer, which is safe.

**Automated tests:** 20 tests, all passing (`uvx --with pytest pytest -q tests`). They cover frame rate choice (including variable-frame-rate phones, slow motion and timelapse), frame rate warnings, time zones, folder scanning (proxies, hidden files, folder links), track layout for overlapping clips, orientation (including rotated phone video), Sony XML matching, and sound sync with a camera clock that is 37 seconds off, for uncompressed audio and for 48 kHz AAC. Both scripts are verified to differ only in the `WORKFLOW` setting.

**Not covered by automated tests:** the Resolve steps themselves (import, colour settings, placing and linking clips, muting, Reels scaling) and the sound-quality ranking. These are covered by the real-world test.

**Real-world test:** passed. Tested by Cutting Clockwork (reported 10 October 2026) in DaVinci Resolve Studio 21.1.1 on macOS, with iPhone and Sony footage. The free version of Resolve and Windows are supported in the code but not yet tested.

**Findings:** none that block release. Note for testers: with AAC audio, the encoder delay (1024 samples, 21 ms at 48 kHz) can shift sync by less than one frame.
