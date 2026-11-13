# Changelog

## 1.0.0 — 2026-11-13

First public release.

**Five scripts for DaVinci Resolve** (Workspace › Scripts):

- **YouTube Timeline** and **Reels Timeline**: one folder of footage becomes a synced, colour-managed timeline, 16:9 or 9:16. Reels takes portrait clips plus landscape clips cropped to fill 9:16.
- **YouTube Multicam Timeline** and **Reels Multicam Timeline** (Resolve 21.1+): the same, but the cameras become a multicam clip per shoot, so you edit by switching angles. Angle 1 is the camera with the best sound. Recordings more than `SHOOT_GAP_HOURS` apart get their own multicam.
- **Export for AI Review**: exports the open timeline as an MP4 with sound for feedback from Gemini, ChatGPT or Claude, then puts the Deliver page back and checks it. Whole timeline or In/Out range (`RANGE`); never overwrites a file and never changes your file name setting.

**Sync**

- Works with any camera brand. Syncs cameras by sound, also when their clocks are hours off (`CLOCK_TOLERANCE_HOURS`).
- A camera with a single recording syncs too, from one sound match, but only when the 1 kHz waveform confirms it. On 155 real clips this check confirmed 55 of 55 true matches and none of 90 chance matches. The report asks you to check such a sync once by eye.
- **Separate audio recorders:** WAV, AIFF, FLAC, M4A and MP3 files in the folder are found by their sound, also without any recording time, and placed on their own audio track under the picture. Files that match nothing stay out and are listed in the report; the same file copied twice is used once.

**Sound**

- Measures the sound of every camera and keeps the cleanest one audible; you hear one microphone at a time. A camera's clip is cut on the audio track: it sounds only where a better camera didn't record and stays muted (but on the track) where one did. On 155 real clips: 0 seconds of double sound.
- A recorder is always heard first, unless its recording is broken (audible clipping or hardly any voice; then it goes to the back). Two recorders both stay audible. A noise-suppressed phone can't push the recorder aside. `PREFERRED_AUDIO_CAMERA` overrules the choice.
- **Sound trims along with the picture.** On the YouTube and Reels timelines each piece of recorder audio is linked to the camera clip you see above it, next to that camera's own sound. On the multicam timelines all audio is linked to the picture above it. Sound that runs under two picture items is cut at that edge first; what you hear doesn't change.

**Picture and colour**

- Colour profile per camera from metadata (Sony XML, iPhone HLG/Apple Log, BRAW and many cinema cameras) or the `CAMERA_PROFILES` setting. Regular Rec.709 clips keep their look (`useInverseDRT` on).
- `MAIN_CAMERA` chooses the picture on the top video track; without it, the camera that recorded the most goes on top. Phones sit below the other cameras.
- Multicam timelines skip pauses and never show a black angle. Each camera gets a clip colour and a colour group, so one group grade covers every piece of that camera.
- Warns about mixed frame rates and centre-cropped landscape clips.

**Setup**

- No separate Python on Resolve 21.1+: the scripts run on Resolve's own Python. FFmpeg is needed; the scripts find it in Homebrew's folders, in Resolve's scripts folder (next to the scripts) or in `~/bin`. Without working FFmpeg the script stops before you choose a folder and opens a report with the fix.
- macOS and Windows.

**Tested**

- DaVinci Resolve Studio 21.1.1 and 21.2 on macOS: generated clips of three cameras with clocks 37 s and 20 s off (all angles frame-accurate); 25 fps, 29.97 non-drop and drop-frame cameras; real shoots of 19 clips (Sony A7 IV + iPhone 16 Pro) and 149 clips; Cutting Clockwork's own test shoot (Sony A7 IV, Nikon Z fc and a Røde Wireless PRO recorder). Export for AI Review on MP4/H.265 and ProRes 422 HQ presets, an In/Out range and a fixed Deliver size.
- 140 automated tests. Code reviewed by Antigravity in several rounds, all findings handled (see QUALITY.md).
- Not yet tested: Windows and the free version of Resolve.
