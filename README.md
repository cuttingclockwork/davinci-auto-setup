# DaVinci Auto-Setup

DaVinci Resolve scripts for the start and the end of an edit. Two of them turn one folder of footage into a ready-to-edit timeline:

| Script | Timeline | Uses |
|---|---|---|
| **YouTube Timeline** | 3840 × 2160 (16:9) | landscape clips |
| **Reels Timeline** | 1080 × 1920 (9:16) | portrait clips, plus landscape clips cropped to fill the frame |

One click, and the script:

- imports every video in the folder (subfolders included), skipping proxies, photos and helper files;
- gives each camera its own video and audio track;
- **syncs the cameras by sound**, even when their clocks are wrong (by up to 3 hours by default);
- sets the **colour profile per camera** under DaVinci Resolve Color Management (output Rec.709 Gamma 2.4);
- picks a timeline frame rate that fits the footage;
- **measures the sound of every camera** and keeps the cleanest one audible, muting duplicates;
- writes a readable report of what it did and what you should check.

Your source files are never changed. Each run saves your current project, then creates a **new project**, so your existing work stays as it is.

The third script, **Export for AI Review**, turns the timeline you are editing into an MP4 you can drop into Gemini, ChatGPT or Claude for feedback, without touching your Deliver settings. See [Export for AI Review](#export-for-ai-review).

## Requirements

- **DaVinci Resolve 21.** Developed and tested on Resolve Studio 21.1 for macOS. The free version and Windows are supported in the code but have not been tested yet. Please open an issue if something breaks.
- **Python 3.10 or newer**, installed system-wide. Resolve uses it to run scripts.
  - macOS: usually already installed. Otherwise use [python.org](https://www.python.org/downloads/).
  - Windows: install from [python.org](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"**.
- **FFmpeg** (`ffmpeg` and `ffprobe`), used by the two timeline scripts to read metadata and analyse sound. Export for AI Review doesn't need it.
  - macOS: `brew install ffmpeg`
  - Windows: `winget install Gyan.FFmpeg`
  - Restart Resolve after installing.

## Installation

1. Download the latest ZIP from [Releases](https://github.com/cuttingclockwork/davinci-auto-setup/releases/latest) and extract it.
2. Copy `YouTube Timeline.py`, `Reels Timeline.py` and `Export for AI Review.py` into Resolve's script folder:

   - **macOS:** `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/`
     In Finder, choose **Go › Go to Folder…** and paste this path.
   - **Windows:** `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`
     Paste this path into File Explorer's address bar.
3. Restart Resolve. The scripts now appear under **Workspace › Scripts**. Copy only the ones you want.

To update, replace the files with the new version. Your settings live at the top of each script, so copy them over first.

## Use

1. Put all footage from one shoot in one folder. Subfolders per camera are fine.
2. In Resolve: **Workspace › Scripts › YouTube Timeline** (or **Reels Timeline**).
3. Choose the folder.
4. Wait. Sound analysis takes longer the first time; results are cached.
5. The report opens automatically. Read the **PLEASE CHECK** section.

Reports are saved in `~/Library/Logs/Resolve Timeline Scripts/` (macOS) or `%LOCALAPPDATA%\Resolve Timeline Scripts\Logs\` (Windows).

## Export for AI Review

Want feedback on an edit from an AI model? It needs a video file. This script makes one from the timeline that is open, and puts your Deliver page back the way it was.

1. Open the timeline in Resolve. Set the Deliver page to **Single clip** (the default).
2. **Workspace › Scripts › Export for AI Review**.
3. Choose a folder. When the export is done, the file is shown in Finder or File Explorer: `<timeline name> - AI review.mp4`.

What it does:

- **Uses your own Deliver settings.** An MP4 stays as you set it (codec, resolution, bitrate). Any other format, such as ProRes, becomes MP4/H.264 for this export, because AI tools need a file they can upload.
- **Always exports video with sound**, the whole timeline by default.
- **Never overwrites a file.** If the name exists, it adds a number.
- **Puts the Deliver page back** and checks every setting Resolve lets a script read: format and codec, audio, range, folder, file name. It never changes your file name setting, so a "Timeline Name" file name keeps following the timeline. If something can't be put back, it keeps a backup preset and tells you which one to load.

| Setting | What it does |
|---|---|
| `RANGE` | `'timeline'` (default) exports the whole timeline. `'marks'` exports only between the In and Out marks; a missing In or Out mark means the start or end of the timeline. |
| `OUTPUT_FOLDER` | A fixed folder, e.g. `'/Users/me/Desktop'`. Empty = ask every time. |
| `MAX_RENDER_MINUTES` | How long the script waits for the export before it gives up (default 30). |

If the script stops, it opens a short note saying why and what to do. Notes are saved next to the timeline reports.

## Settings (timeline scripts)

Open the script in a text editor. All settings sit at the top, under `SETTINGS`. Change both scripts the same way: they are identical except for the `WORKFLOW` line.

| Setting | What it does |
|---|---|
| `CAMERA_PROFILES` | Colour profile per camera, for cameras that don't store it in their files (common for log on Panasonic, DJI, Fujifilm, many Canon MP4s). Use the camera name from the report and the exact name from Resolve's *Clip Attributes › Input Color Space* list. |
| `PREFERRED_AUDIO_CAMERA` | Always hear this camera (and sync the others to it). Empty = automatic: the script measures which camera sounds cleanest. |
| `TIMELINE_FPS` | Force a frame rate (e.g. `25` or `29.97`). Empty = the lowest frame rate in the footage. |
| `CLOCK_TOLERANCE_HOURS` | How far camera clocks may be off and still be matched by sound. Raise it if a camera is set to the wrong time zone. Larger values make the analysis slower. |
| `FFMPEG_FOLDER` | Only needed if the script can't find FFmpeg by itself. |

Example:

```python
CAMERA_PROFILES = {
    'Panasonic': 'Panasonic V-Gamut/V-Log',
}
```

## How it decides

**Cameras** are identified from metadata: make and model tags, Sony XML sidecars, iPhone tags. A file without any camera tags is grouped by folder and recording format, so two unknown cameras don't end up on one track.

**Colour profile**, strongest evidence first:

1. your `CAMERA_PROFILES` entry;
2. camera metadata (Sony S-Log3 XML, HLG or PQ tags);
3. what Resolve detects itself (e.g. Apple Log, BRAW);
4. a Rec.709 tag in the file;
5. other recordings of the same camera in the same folder on the same day, but only if they all agree.

When none of these applies, the clip stays Rec.709 and the report tells you which camera to add to `CAMERA_PROFILES`.

**Sync.** Recording times give a first guess. The script then matches the sound of every camera against the reference camera. A clock correction is only trusted when at least two independent clips agree. After that, each clip is fine-tuned on its own waveform.

**Which audio you hear.** Sync and sound are decided separately:

- The *sync reference* is the dedicated camera (not a phone) with the most recorded audio, because long coverage gives the most reliable sync.
- Which camera you *hear* is measured. Wherever two cameras recorded at the same moment, the script compares them on exactly the same stretches (up to six of 15 seconds), so the same voice in the same room is measured:
  - **voice vs background**: how loud the speech is compared with the quiet moments between words (room noise, echo, hiss). A mic close to your mouth scores high.
  - **top end**: how much high-frequency detail the voice has. A muffled built-in mic scores low.
  - **clipping**: distorted samples. A heavy penalty.
- Another camera only takes over when it scores at least 4 dB better. Near-equal tracks keep the default (dedicated camera before phone).
- The choice is made **once per camera**, never per clip, so the sound doesn't change character halfway through a sentence.
- A clip is muted only when better-sounding audio with confirmed sync covers it completely.

The report lists the measurements and the reason for the choice under **AUDIO**.

**Frame rate.** The timeline uses the lowest frame rate in the footage. Phones that record a variable frame rate (e.g. 29.87 fps on average) are rounded to the nearest standard rate. Slow-motion clips (120/240 fps) count as 60 and never pull the timeline down.

## Known limitations

**Export for AI Review**

- **The file can be large.** It uses your own MP4 bitrate; a 30 Mb/s preset makes about 75 MB for 20 seconds. That uploads fine to Gemini and ChatGPT. Pick a lighter preset on the Deliver page first if you need a smaller file.
- **Subtitles** are exported the way your Deliver page is set (burned in or not); the script doesn't change that.
- **Settings Resolve doesn't let scripts read**, such as quality and hardware encoding, are restored through a backup preset but can't be checked one by one. In tests with an MP4/H.265 preset the export afterwards was identical to before.
- **Individual clips** mode isn't supported; the script asks you to switch to Single clip.
- **The preset menu shows "Custom Export" afterwards.** Resolve switches the label as soon as a script changes any Deliver setting, and scripts can't read or set the label. Your settings are the same as before; pick your preset again if you want to see its name.

**Timeline scripts**

- **Mixed frame rates judder.** Resolve plays a 30 fps clip on a 25 fps timeline by skipping frames. The report warns you. The fix is to record every camera at the same frame rate, or a multiple of it (25 + 50, or 30 + 60).
- **Sync needs shared sound.** A camera without audio, or one that recorded something else (like a GoPro on the outside of a car), falls back to its own clock. The report says which clips aren't confirmed.
- **Wrong camera clocks.** Clocks off by more than `CLOCK_TOLERANCE_HOURS` aren't matched.
- **Reels crops landscape clips in the centre.** A 16:9 shot keeps only the middle ~32% of its width. Someone standing on the left or right third is (partly) cut off. Reposition those clips by hand. Sharp 9:16 crops also need 4K footage: 1080p landscape footage gets upscaled almost 1.8× and looks softer.
- **Log footage from unknown cameras** is treated as Rec.709 until you add the camera to `CAMERA_PROFILES`.
- **The audio check measures technique, not taste.** It catches noise, echo, distortion and muffled sound. It can't hear clothing rustle on a lavalier, a speaker turning away from the mic, or which sound you simply like better. Use `PREFERRED_AUDIO_CAMERA` to overrule it.
- **Double sound on partial overlaps.** When the preferred camera's clip covers only part of another camera's clip, both stay audible on the overlap (the script doesn't cut clips). The report names these clips.
- **Spatial or multichannel audio**: only the main stereo pair is used.
- **Very long clips**: the wide sound comparison uses the first 30 minutes of each file.

## Adapting it

The scripts are plain Python. To make them fit your own setup (another camera, another resolution, extra tracks), give the script to an AI assistant such as Claude or ChatGPT, describe what you want changed, and test the result on a copy of your footage first.

## How this was built and tested

I'm a video creator, not a programmer: Claude (Anthropic's AI assistant) wrote this code, and I test it on my own footage. To make up for that, every release goes through the same checks:

- **Real-world test** in DaVinci Resolve Studio 21.1 on macOS, with iPhone and Sony footage.
- **Automated tests** (`tests/`) for the parts that don't need Resolve: frame rate choice, orientation, folder scanning, Sony metadata and sound sync. The sync test generates clips with a camera clock that is 37 seconds off and checks that the script places them within one frame. For Export for AI Review: the export range, file names, and the Deliver restore against a stand-in that behaves like Resolve (audio reset when switching to MP4, a codec Resolve reports as empty, a file name a script can't restore).
- **Code and safety review**, plus automatic code checks. The script never changes, moves or deletes your footage, runs FFmpeg without a shell, makes no internet connections, and only cleans up its own sound-analysis cache.

Details are in [QUALITY.md](QUALITY.md). Still, it's free software provided as is, without warranty (see the license). **Back up your project before your first run**, and check the report the script writes.

## Help and feedback

Found a bug or tested it with a camera or system not listed here? Open an [issue](https://github.com/cuttingclockwork/davinci-auto-setup/issues) and attach the `.txt` report the script wrote. It contains no video, only file names, camera names and settings.

## License

[MIT](LICENSE). Made by [Cutting Clockwork](https://www.youtube.com/@cuttingclockwork).
