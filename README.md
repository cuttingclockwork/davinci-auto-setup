# DaVinci Auto-Setup

DaVinci Resolve scripts for the start and the end of an edit. Four of them turn one folder of footage into a ready-to-edit timeline:

| Script | Timeline | Uses |
|---|---|---|
| **YouTube Timeline** | 3840 × 2160 (16:9), one track per camera | landscape clips |
| **Reels Timeline** | 1080 × 1920 (9:16) | portrait clips, plus landscape clips cropped to fill the frame |
| **YouTube Multicam Timeline** | 3840 × 2160 (16:9), one multicam clip per shoot: switch cameras while you edit | landscape clips (Resolve 21.1+) |
| **Reels Multicam Timeline** | 1080 × 1920 (9:16), one multicam clip per shoot | portrait clips, plus landscape clips cropped to fill (Resolve 21.1+) |

**Tracks or multicam?** All four sync the same way. Pick a plain **Timeline** script if you like to see every camera on its own track and cut by hand. Pick a **Multicam Timeline** if you'd rather play the edit and switch angles live in the multicam viewer, like a TV director. Install the ones you want.

One click, and the script:

- imports every video in the folder (subfolders included), skipping proxies, photos and helper files, and finds separate audio recordings (WAV and similar) by their sound;
- gives each camera its own video and audio track, and each recorder its own audio track;
- **syncs the cameras by sound**, even when their clocks are wrong (by up to 3 hours by default);
- sets the **colour profile per camera** under DaVinci Resolve Color Management (output Rec.709 Gamma 2.4);
- picks a timeline frame rate that fits the footage;
- **measures the sound of every camera** and keeps the cleanest one audible: other cameras sound only where it didn't record;
- writes a readable report of what it did and what you should check.

Your source files are never changed. Each run saves your current project, then creates a **new project**, so your existing work stays as it is.

The fifth script, **Export for AI Review**, turns the timeline you are editing into an MP4 you can drop into Gemini, ChatGPT or Claude for feedback, without touching your Deliver settings. See [Export for AI Review](#export-for-ai-review).

## Requirements

- **DaVinci Resolve Studio 21.1 or newer.** From Resolve 21.1 on, Blackmagic runs Python scripts in Studio only: in the free edition `.py` files are not listed under Workspace › Scripts, and the Console has no Py3 tab (measured on the free edition for Windows, 16 Nov 2026; Blackmagic's 21.1 release notes say "Advanced scripting now requires DaVinci Resolve Studio"). Developed and tested on Resolve Studio 21.1 and 21.2 for macOS. Windows is supported in the code but has not been tested yet. Please open an issue if something breaks.
- **No separate Python needed on Resolve Studio 21.1 or newer.** Resolve runs scripts from the Workspace › Scripts menu with its own built-in Python. Only on Resolve Studio 21.0 do you need Python 3.10 or newer, installed system-wide:
  - macOS: usually already installed. Otherwise use [python.org](https://www.python.org/downloads/).
  - Windows: install from [python.org](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"**.
- **FFmpeg** (`ffmpeg` and `ffprobe`), used by the four timeline scripts to read metadata and analyse sound. Export for AI Review doesn't need it.
  - macOS with Homebrew (recommended): `brew install ffmpeg`
  - Windows (recommended): `winget install Gyan.FFmpeg`
  - **No Homebrew, no Terminal (macOS):** on [evermeet.cx/ffmpeg](https://evermeet.cx/ffmpeg/) (the macOS download that [ffmpeg.org](https://ffmpeg.org/download.html) points to), download **both** the `ffmpeg` and the `ffprobe` ZIP, unzip them and put the two files `ffmpeg` and `ffprobe` in the scripts folder, next to the scripts (see [Installation](#installation)). These builds aren't notarized by Apple, so macOS blocks them the first time ("ffprobe" Not Opened). Click **Done**, not *Move to Bin*. Then open **System Settings › Privacy & Security**, scroll down, click **Open Anyway** and run the script again. macOS asks a few times (for `ffprobe` and for `ffmpeg`, and once more to confirm each); after that it's done for good. Only use Open Anyway for files you downloaded yourself from that page. These are Intel builds; on an Apple Silicon Mac they run through Rosetta 2 (macOS offers to install it if needed). Homebrew installs a native version. The report tells you when this is needed.
  - **No winget (Windows):** download a `.zip` build such as `ffmpeg-release-essentials.zip` from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), unzip it, open its `bin` folder and copy `ffmpeg.exe` and `ffprobe.exe` into the scripts folder, next to the scripts (not the `bin` folder itself).
  - Restart Resolve after installing.

## Installation

1. Download the latest ZIP from [Releases](https://github.com/cuttingclockwork/davinci-auto-setup/releases/latest) and extract it.
2. Copy the scripts you want (`YouTube Timeline.py`, `Reels Timeline.py`, `YouTube Multicam Timeline.py`, `Reels Multicam Timeline.py`, `Export for AI Review.py`) into Resolve's script folder:

   - **macOS:** `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/`
     In Finder, choose **Go › Go to Folder…** and paste this path.
   - **Windows:** `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`
     Paste this path into File Explorer's address bar.
3. Restart Resolve. The scripts now appear under **Workspace › Scripts**. Copy only the ones you want.

To update, replace the files with the new version. Your settings live at the top of each script, so copy them over first.

## Use

1. Put all footage from one shoot in one folder. Subfolders per camera are fine.
2. In Resolve: **Workspace › Scripts**, then the script you want (for example **YouTube Timeline**).
3. Choose the folder.
4. Wait. Sound analysis takes longer the first time; results are cached.
5. The report opens automatically. Read the **PLEASE CHECK** section.

Reports are saved in `~/Library/Logs/Resolve Timeline Scripts/` (macOS) or `%LOCALAPPDATA%\Resolve Timeline Scripts\Logs\` (Windows).

### YouTube Multicam and Reels Multicam Timeline

To see all cameras, turn on the multicam view: in the source viewer's menu (bottom left of the viewer) choose **Multicam**, and use the dual viewer layout. A black angle means that camera wasn't recording at that moment.

Same sync, colour profiles and sound check as the track timelines, but the cameras end up in a **multicam clip**, so you cut by switching angles in the multicam viewer instead of stacking tracks.

- **No black stretches on the timeline.** Pauses when no camera was recording are left out; the timeline only shows parts with picture. They do stay inside the multicam clip itself.
- **Sound is linked to the picture.** Every audio clip is linked to the picture above it, so trimming takes the sound along. To trim sound or picture on its own, turn off Linked Selection in the timeline toolbar.
- **One multicam per shoot.** A pause of more than `SHOOT_GAP_HOURS` (default 3) between recordings, or footage from another day, starts a new multicam. They follow each other on the timeline.
- **Angle 1 is the camera with the best sound**, then the others in order of sound quality. Angles are named after the camera.
- **Picture on V1, sound underneath.** The timeline holds the multicam for picture only. The cameras' own sound sits on the audio tracks below it, exactly like the YouTube timeline: the best camera audible, the next one taking over where it didn't record. (Resolve's built-in multicam audio either goes silent where the first angle didn't record, or plays every camera at once.)
- **How it syncs:** the script gives every clip its synced moment as start timecode inside Resolve and builds the multicam on timecode. Your files are not changed; only the clip's timecode in this new project.
- **Each camera has its own clip colour.** Every clip gets its camera's colour (the report lists them; angle 1 is always Orange), inside the multicam and on the timeline, so you can see which clip came from which camera. The multicam clip itself stays uncoloured, because it holds every camera; so a coloured clip on V1 is a part where the first camera wasn't recording.
- **Grade each camera once, as a colour group.** The script makes one colour group per camera. A grade on a piece of your edit timeline only changes that piece, so grade per camera instead: on the Edit page, select a multicam clip › **Clip › Open in Timeline** and go to the Color page. Show one camera with the **Clips** filter › Clip Color › that camera's colour, select all, and add them to the group with that colour in its name, like *Sony ILCE-7M4 (Orange)* (right-click › Groups › Assign to Group). Grade the group on the *Group Post-Clip* layer, and set the filter back to *All Clips*. Every piece of that camera follows, also the parts where only that camera was recording: those sit on the timeline directly and are already in the group.
- **Reels Multicam** takes portrait and landscape cameras. Landscape angles are cropped to fill 9:16 in the centre (the project is set to *Scale full frame with crop*, because angles inside a multicam can't be repositioned one by one by a script). Reframe a shot by hand with *Clip › Open in Timeline* if someone is cut off.

## Export for AI Review

Want feedback on an edit from an AI model? It needs a video file. This script makes one from the timeline that is open, and puts your Deliver page back the way it was.

1. Open the timeline in Resolve. Set the Deliver page to **Single clip** (the default).
2. **Workspace › Scripts › Export for AI Review**.
3. Choose a folder. When the export is done, the file is shown in Finder or File Explorer: `<timeline name> - AI review.mp4`.

What it does:

- **Exports at the timeline's resolution**, so the AI sees the frame as you edited it. If the Deliver page already matches it (for example "Timeline Resolution"), nothing is changed; a different size is set back afterwards.
- **Uses your own codec settings.** An MP4 stays as you set it (codec, bitrate). Any other format, such as ProRes, becomes MP4/H.264 for this export, because AI tools need a file they can upload.
- **Always exports video with sound**, the whole timeline by default.
- **Never overwrites a file.** If the name exists, it adds a number.
- **Keeps your render range.** "Entire Timeline" stays Entire Timeline, In/Out marks stay where they were.
- **Puts the Deliver page back** and checks every setting Resolve lets a script read: format and codec, audio, range, folder, file name. It never changes your file name setting, so a "Timeline Name" file name keeps following the timeline. If something can't be put back, it keeps a backup preset and tells you which one to load.

| Setting | What it does |
|---|---|
| `RANGE` | `'timeline'` (default) exports the whole timeline. `'marks'` exports only between the In and Out marks; a missing In or Out mark means the start or end of the timeline. |
| `OUTPUT_FOLDER` | A fixed folder, e.g. `'/Users/me/Desktop'`. Empty = ask every time. |
| `MAX_RENDER_MINUTES` | How long the script waits for the export before it gives up (default 30). |

If the script stops, it opens a short note saying why and what to do. Notes are saved next to the timeline reports.

## Settings (timeline scripts)

Open the script in a text editor. All settings sit at the top, under `SETTINGS`. Change the timeline scripts the same way: they are identical except for the `WORKFLOW` line.

| Setting | What it does |
|---|---|
| `CAMERA_PROFILES` | Colour profile per camera, for cameras that don't store it in their files (common for log on Panasonic, DJI, Fujifilm, many Canon MP4s). Use the camera name from the report and the exact name from Resolve's *Clip Attributes › Input Color Space* list. |
| `PREFERRED_AUDIO_CAMERA` | Always hear this camera (and sync the others to it). Empty = automatic: a separate audio recorder goes first; otherwise the script measures which camera sounds cleanest. |
| `MAIN_CAMERA` | YouTube and Reels timelines: the camera whose picture you see, on the top video track. Empty = the camera that recorded the most (the sync reference). Phones always go below the other cameras. |
| `TIMELINE_FPS` | Force a frame rate (e.g. `25` or `29.97`). Empty = the lowest frame rate in the footage. |
| `CLOCK_TOLERANCE_HOURS` | How far camera clocks may be off and still be matched by sound. Raise it if a camera is set to the wrong time zone. Larger values make the analysis slower. |
| `SHOOT_GAP_HOURS` | Multicam only: a pause longer than this between recordings starts a new multicam clip. Default 3. |
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

**Sync.** Recording times give a first guess. The script then matches the sound of every camera against the reference camera. A clock correction is trusted when at least two independent clips agree. A camera with a single take (one long recording) gets its correction from one match only when the waveform itself confirms it; the report then asks you to check that sync once by eye. After that, each clip is fine-tuned on its own waveform.

**Which audio you hear.** Sync and sound are decided separately:

- The *sync reference* is the dedicated camera (not a phone) with the most recorded audio, because long coverage gives the most reliable sync.
- Which camera you *hear* is measured. Wherever two cameras recorded at the same moment, the script compares them on exactly the same stretches (up to six of 15 seconds), so the same voice in the same room is measured:
  - **voice vs background**: how loud the speech is compared with the quiet moments between words (room noise, echo, hiss). A mic close to your mouth scores high.
  - **top end**: how much high-frequency detail the voice has. A muffled built-in mic scores low.
  - **clipping**: distorted samples. A heavy penalty.
- Another camera only takes over when it scores at least 4 dB better. Near-equal tracks keep the default (dedicated camera before phone).
- The choice is made **once per camera**, never per clip, so the sound doesn't change character halfway through a sentence.
- A clip sounds only where no better camera with confirmed sync recorded: it is cut on the audio track, and the covered part stays there, muted.
- A separate audio recorder always goes first: you put it there on purpose. Only a broken recording (audible clipping, or hardly any voice) is skipped, and the report says so. Phones that suppress noise between words no longer win on that alone: above 45 dB the voice-to-background contrast stops counting. Two recordings that run at the same time both stay audible, because they are usually two speakers; the report names them.

The report lists the measurements and the reason for the choice under **AUDIO**.

**Frame rate.** The timeline uses the lowest frame rate in the footage. Phones that record a variable frame rate (e.g. 29.87 fps on average) are rounded to the nearest standard rate. Slow-motion clips (120/240 fps) count as 60 and never pull the timeline down.

## Known limitations

**Export for AI Review**

- **The file can be large.** It uses your own MP4 bitrate at the timeline's resolution; a 30 Mb/s preset makes about 75 MB for 20 seconds. That uploads fine to Gemini and ChatGPT. Pick a preset with a lower bitrate first if you need a smaller file.
- **Subtitles** are exported the way your Deliver page is set (burned in or not); the script doesn't change that.
- **Settings Resolve doesn't let scripts read**, such as quality and hardware encoding, are restored through a backup preset but can't be checked one by one. In tests with an MP4/H.265 preset the export afterwards was identical to before.
- **Individual clips** mode isn't supported; the script asks you to switch to Single clip.
- **The preset menu shows "Custom Export" afterwards.** Resolve switches the label as soon as a script changes any Deliver setting, and scripts can't read or set the label. Your settings are the same as before; pick your preset again if you want to see its name.

**Timeline scripts**

- **Mixed frame rates judder.** Resolve plays a 30 fps clip on a 25 fps timeline by skipping frames. The report warns you. The fix is to record every camera at the same frame rate, or a multiple of it (25 + 50, or 30 + 60).
- **Sync needs shared sound.** A camera without audio, or one that recorded something else (like a GoPro on the outside of a car), falls back to its own clock. The report says which clips aren't confirmed.
- **Audio files need shared sound.** A recorder file is found by matching its sound to the cameras, because recorders rarely store a recording time. A file without matching sound (music, a voice-over, another shoot) isn't placed; the report lists it. Tested with a Røde Wireless PRO; other recorders should work the same way.
- **Short phone clips with voice processing.** Phones that clean up your voice (noise suppression, voice isolation) change the sound so much that a short clip from a phone without other clips can't be confirmed by sound. It then keeps the phone's own clock, and the report says so. Film with the phone for longer stretches, or record more than one clip with it.
- **Very short clips** (under about 4 seconds) can't be matched by sound. When their camera has no other matched clips, they follow that camera's own clock, which may be minutes off. The report names them.
- **Wrong camera clocks.** Clocks off by more than `CLOCK_TOLERANCE_HOURS` aren't matched.
- **Reels crops landscape clips in the centre.** A 16:9 shot keeps only the middle ~32% of its width. Someone standing on the left or right third is (partly) cut off. Reposition those clips by hand. Sharp 9:16 crops also need 4K footage: 1080p landscape footage gets upscaled almost 1.8× and looks softer.
- **Log footage from unknown cameras** is treated as Rec.709 until you add the camera to `CAMERA_PROFILES`.
- **The audio check measures technique, not taste.** It catches noise, echo, distortion and muffled sound. It can't hear clothing rustle on a lavalier, a speaker turning away from the mic, or which sound you simply like better. Use `PREFERRED_AUDIO_CAMERA` to overrule it.
- **Spatial or multichannel audio**: only the main stereo pair is used.
- **Very long clips**: the wide sound comparison uses the first 30 minutes of each file.

**Multicam timelines**

- **Needs DaVinci Resolve 21.1 or later** (the first version that lets scripts make multicam clips).
- **Parts without the first camera aren't multicam.** A script can't choose a multicam clip's angle, so where angle 1 has no picture, the clip that does sits on the timeline directly. With three or more cameras you can't switch between the others there; the report says how many parts this is. They are already in their camera's colour group, so a group grade reaches them; a grade on that camera inside the multicam does not.
- **Switching angles doesn't switch the sound.** That's on purpose: the best sound stays. Switch the audio tracks yourself if you want a different microphone.
- **A shoot can be at most 20 hours long**, because Resolve timecode stops at 24 hours. Longer recordings are split into more multicams.
- **Clips of one camera that overlap** (two recordings running at the same time on one camera) share one angle; check those by hand.

## Adapting it

The scripts are plain Python. To make them fit your own setup (another camera, another resolution, extra tracks), give the script to an AI assistant such as Claude or ChatGPT, describe what you want changed, and test the result on a copy of your footage first.

## Tested with

| Cameras | Situation | Resolve | System | Result |
|---|---|---|---|---|
| Sony A7 IV (S-Log3 + XML) and iPhone 16 Pro (Blackmagic Camera app, HLG) | Two shoots: 155 clips over a day, and 1.5 hours with long Sony takes; phone clock about 51 minutes off | Studio 21.1.1 | macOS | Synced within one frame; Multicam: one multicam per shoot |
| Generated test clips | Other brands' metadata (Canon, Panasonic, Fujifilm, Nikon, GoPro, DJI, Samsung, Pixel), 23.976–60 fps, 29.97 drop-frame, clocks off by seconds to hours, single takes, no sound, odd file names | Studio 21.1.1 (multicam) and automated tests | macOS | See [QUALITY.md](QUALITY.md) |

**Used it with other gear?** Open an [issue](https://github.com/cuttingclockwork/davinci-auto-setup/issues) with your cameras and the `.txt` report, whether it worked or not, and this table grows.

## How this was built and tested

I'm a video creator, not a programmer: Claude (Anthropic's AI assistant) wrote this code, and I test it on my own footage. To make up for that, every release goes through the same checks:

- **Real-world test** in DaVinci Resolve Studio 21.1 on macOS, with iPhone and Sony footage (see *Tested with*).
- **Automated tests** (`tests/`) for the parts that don't need Resolve: frame rate choice, orientation, folder scanning, Sony metadata and sound sync. The sync tests generate clips and check that the script places them within one frame: a camera clock 37 seconds off, a single take with a clock 70 minutes off, a 29.97 fps camera next to 25 fps, and odd file names; and that it does *not* force a camera into sync when it heard something else, or when its clock is beyond the tolerance. For Export for AI Review: the export range, file names, and the Deliver restore against a stand-in that behaves like Resolve (audio reset when switching to MP4, a codec Resolve reports as empty, a file name a script can't restore).
- **Code and safety review**, plus automatic code checks. The script never changes, moves or deletes your footage, runs FFmpeg without a shell, makes no internet connections, and only cleans up its own sound-analysis cache.

Details are in [QUALITY.md](QUALITY.md). Still, it's free software provided as is, without warranty (see the license). **Back up your project before your first run**, and check the report the script writes.

## Help and feedback

Found a bug or tested it with a camera or system not listed here? Open an [issue](https://github.com/cuttingclockwork/davinci-auto-setup/issues) and attach the `.txt` report the script wrote. It contains no video, only file names, camera names and settings.

Want an email when a new version is out? Click **Watch → Custom → Releases** at the top of this page.

Want this set up for your own team? Business enquiries: cuttingclockwork@gmail.com

## License

Free to use, also for paid client work, and free to change for your own use. Not for resale or redistribution: to share it, link to this page. See [LICENSE](LICENSE). Made by [Cutting Clockwork](https://www.youtube.com/@cuttingclockwork).
