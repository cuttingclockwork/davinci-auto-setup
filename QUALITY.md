# Quality report

*Before the first public release (1.0.0, 13 November 2026) the scripts were developed in stages called 1.0.0, 1.1.0 and 1.2.0; the sections below keep those names. Everything in them is part of the public 1.0.0.*

This file records the checks behind each release.

## 1.0.1, replaced (19 November 2026): sync fixes

**Found by** Cutting Clockwork's own test on a real multi-day shoot (Sony A7 IV with Rec Run timecode, iPhone 16 Pro with the Blackmagic Camera app, 129 clips over about ten days, long stretches of sanding and sawing), measured by Antigravity on the timeline and in the source audio.

**Causes (measured outside Resolve, same code; Resolve's report of that run reproduced exactly):**
1. *Wrong clock for a whole day.* The wide search keeps one best match per clip pair. On 28 July two such matches (repetitive noise) agreed on −3218.6 s; the old rule accepted the first pair of agreeing clips with the most weight and never tested that offset on the other clips of the day. At the true offset (−3018.4 s) three other clips match (r 0.62–0.90) and one is confirmed by the 1 kHz waveform; at −3218.6 s none is.
2. *Reference clips a second apart.* The reference camera kept its own clock per clip; a Sony with Rec Run timecode gives that clock in whole seconds. An iPhone clip synced on C1210 also runs over C1209, which sat 0.54 s off.

**Fixes:** `consensus_anchor` and `day_votes` (every candidate offset tested on every clip of the day, one vote per clip, ≥ 2 independent clips, 1.3× margin; ties broken by the waveform, then by another day's proven clock, else reported); a second pass that also tests other days' proven clocks (same proof needed); `refine_reference_clips` (reference clips lined up through a frame-accurate clip or recorder that runs over two of them, at most 1.2 s, the whole tree of synced clips moves along, no move that makes the camera overlap itself); `shoot_days` (local date, a shoot past midnight stays one day); `local_match` (direct Pearson for a narrow window, same score as the FFT path); shorter report lines; proxy-only files named in the report.

**Measured after the fix** (`verify.py`: own 10 Hz envelope, numpy correlation per overlapping camera pair, ± 3 s):

| Footage | Result |
|---|---|
| Multi-day shoot, 129 clips (Reels) | 24 July unchanged; 28 July −3218.6 → −3018.4 s; C1209 moved +0.513 s (13.5 → 0.7 frames); 1 August newly synced (−3016.45 s, waveform-confirmed; clock drift −3020.2 / −3018.4 / −3016.45 s over the days). All 12 clearly matching pairs (r ≥ 0.5) within 0.7 frames. |
| Cutting Clockwork test shoot: Sony A7 IV, Nikon Z fc, 4 Røde Wireless PRO files (50 items) | Nothing moved. |
| Real shoot, 257 clips (Sony A7 IV + iPhone 16 Pro, YouTube) | Nothing moved, same report notes. 120 clearly matching pairs; 118 within a frame by `verify.py`. The other two (a 40 s and a 24 s phone clip of speech) the 10 Hz check puts 0.79 s and 0.11 s off, but its peak there is flat (r 0.87 at the script's position, 0.90 at 0.74 s); the script's 1 kHz waveform (score 0.74 and 0.61) and the spectral check both confirm the script's position, so these are limits of the check, not of the sync. |

**Automatic checks:** 149 tests pass (new: consensus against two chance matches, clusters before single peaks in the offsets tested, an empty camera clock (1970) and odd times, tie and tie-break, two-clip rule, one vote per clip, local search = full search, shoot past midnight, generated clips with a reference clip 0.4 s off its whole-second time, proxy note). Ruff (F, E9, B, PLE, PLW) and Bandit (medium/high): the same notes as before, nothing new.

**Antigravity review:** Antigravity (Gemini 4 Neon XHigh, read-only, 19 November 2026; `github/reviews/davinci-auto-setup-1.0.1-sync-fix-antigravity.md`, not published): two blocking, five important, four small points. All handled:
1. *(blocking)* A single take was checked only on its best vote. Now the waveform check tries the clip's best fits, then its other fits, then the wide-search candidates, up to 15 in that order.
2. *(blocking)* The 12 offsets tested could be filled with scattered chance matches. Offsets are now clustered first (`candidate_offsets`), clusters of several clips before single peaks; other days' clocks come on top of the 12. Test added.
3. *(important)* `datetime.fromtimestamp` can fail on Windows around 1970. `local_time` falls back safely (also for the multicam name), and `parse_time` refuses times before 1971 (an empty camera clock). Test added.
4. *(important)* Clock drift between days could exceed the 2 s search. Another day's clock is now searched both ± 2 s and ± 10 s (`PRIOR_DRIFT_SECONDS`), and the overlap pre-check allows for that margin. On the multi-day shoot the drift was 1.8–1.95 s per gap.
5. *(important)* Overlap check in `refine_reference_clips` ran once. Now repeated until nothing changes, silent clips of the reference camera count, evidence is written only for moves that are kept, clearer wording.
6. *(important)* A clip's vote is now chosen on score × overlap, like everywhere else.
7. *(important)* Placeholder in CHANGELOG and QUALITY not yet filled: they were being written during the review; done.
8. *(small)* Per-app anchors only when one phone used more than one app that day (no double runs or evidence).
9. *(small)* Links between reference clips are taken best first over several steps (priority queue).
10. *(small)* (a) done with 5; (b) clips matched on loudness only don't move along with a reference clip: left as is, they are only accurate to 0.1 s anyway and the shift is under a second.
11. *(small)* `shoot_days` now uses its own constant (3 h), so `SHOOT_GAP_HOURS` stays multicam-only; README lines on per-day counts updated; the proxy note appears only for a proxy that was really used.

After these changes all measurements above were repeated with the final code: the same results (multi-day shoot identical to the checked placement; test shoot and the 257-clip shoot: nothing moved). One review round per version: no second review.

## 1.0.1 (18 November 2026): documentation only

Only `README.md`, `CHANGELOG.md`, this file and the `VERSION` line in the five scripts changed; no logic. The new requirement was measured, not assumed: on a Windows PC with the free edition of Resolve, the scripts in `…\Support\Fusion\Scripts\Utility\` did not appear under Workspace › Scripts, and the Console offered Lua only (16 November 2026). This matches Blackmagic's 21.1 release notes ("Advanced scripting now requires DaVinci Resolve Studio"), found and checked by Antigravity. All 140 automated tests pass. No Antigravity code review for this patch: there is no code change to review. The code is written by Claude (Anthropic's AI assistant); Cutting Clockwork tests it on real footage.

## 1.2.0: recorder linked to the picture (13 November 2026)

On the YouTube and Reels timelines each recorder piece is now linked to the camera clip you see above it (`visible_pictures`, `link_recorders_to_picture`), next to that camera's own sound. Measured in Resolve Studio 21.2: `SetClipsLinked` replaces an existing link group, so the camera's own sound is linked again in the same call; two picture clips in one group hide the clip's effects in the Inspector, so only the visible picture is linked. Checked on Cutting Clockwork's test shoot (25 Sony, 21 Nikon, 4 Røde files): 26 recorder pieces, each linked to exactly one picture clip that covers it; no camera lost its own sound; where the script cut the recorder, the sound runs on without a jump.

**Review (Antigravity, `github/reviews/davinci-auto-setup-1.2.0-recorder-koppeling-antigravity.md`): no blocking, 2 important, 2 small; all handled.** Recorder sound that could not be cut at a picture edge is now left unlinked with a note (before, it would tie the sound under several pictures to one of them); new tests for a long clip over a shorter one, two recorders, sound under a gap, and the uncut case; no cut within 2 frames of the previous cut; CHANGELOG wording. 140 automated tests pass. The fixes after the review were not rerun in Resolve (they only change the fallback and cuts one frame apart).

## 1.2.0: clip colour per camera (8 November 2026)

Measured in Resolve Studio 21.2 on a test project (two generated clips, one multicam and one direct clip): a clip colour set on the media pool clip shows on that camera's clips inside the multicam (Open in Timeline) on the Edit page (name bar) and on the Color page (dot on the thumbnail, bar in the mini timeline), and the direct clip on V1 takes the same colour (after `ClearClipColor` on the timeline item, `GetClipColor` still gave the media pool colour). The Color page's **Clips › Clip Color** filter then shows one camera at a time, also inside the multicam. The multicam item on the edit timeline stays uncoloured. New: `clip_colour_per_camera` gives each camera one of Resolve's 15 clip colours (Blue left out, since it looks like an uncoloured clip) and the report lists them; failures are reported, not fatal.

**Review round 5 (Antigravity, 8 November 2026): no blocking or important findings, 3 small; all handled.**

| # | Finding | What happened |
|---|---|---|
| 1 | The report listed every camera's colour, even when its clips refused the colour | Fixed: only cameras with at least one coloured clip are listed. |
| 2 | With more than eight cameras a colour was reused without a warning, so a colour filter could select two cameras | Fixed: all 15 non-blue colours are used, and more cameras than colours gives a warning. |
| 3 | A refused clip colour also removed the line that the direct clips are in their colour group | Fixed: the colours are set before that check, so the line depends on the groups only. |

After the fixes: 115 automated tests pass (3 new, one checks the names against Resolve's Clip Color menu).

**After the script review (Antigravity, 8 November 2026):** the colours now follow the multicam's angle order (angle 1, the best sound, is Orange) instead of camera names, and each colour group carries its colour in its name (*Sony ILCE-7M4 (Orange)*), so the Clip Color filter and the Assign to Group menu match without the report. The report and README now open the multicam from the Edit page (Clip › Open in Timeline), which keeps it open on the Color page. 117 automated tests pass (2 new).

**FFmpeg next to the scripts (Claude, 9 November 2026):** the timeline scripts also look for `ffmpeg` and `ffprobe` in Resolve's scripts folder and in `~/bin`, for people without Homebrew. Reviewed by Antigravity (`github/reviews/davinci-auto-setup-1.2.0-ffmpeg-antigravity.md`): two blocking, one important and two small findings, all fixed: every FFmpeg copy is test-started (`-version`) and checked for execute permission, so a blocked or broken copy can't silently produce a timeline without sync; a missing or blocked FFmpeg now stops the script before the folder dialog with a report (including the macOS *Open Anyway* step); `FFMPEG_FOLDER` must hold both tools; the README gives separate macOS and Windows steps. 123 automated tests pass (6 for finding FFmpeg, with real executable stand-ins).

Tested by Cutting Clockwork on 10 November 2026 (Resolve Studio 21.2, macOS): `ffmpeg` and `ffprobe` downloaded from evermeet.cx in the browser, used from a folder next to the script. macOS blocked them ("Not Opened"); the script stopped before the folder dialog and its report gave the Open Anyway steps. After a few Open Anyway confirmations the script imported the footage and built the timeline.

**Recorder first (Claude, 10 November 2026):** in Cutting Clockwork's test shoot (Sony, Nikon Z fc, iPhone 16 Pro selfie camera, Røde Wireless PRO) the iPhone was chosen as main audio, because its noise suppression made the pauses almost silent (contrast 59.5 dB against 34.6 dB for the Røde). A separate recorder now always goes first unless broken, and contrast above 45 dB no longer counts. 126 automated tests pass (3 new, with the measured values from that shoot).

**Main camera on top (Claude, 10 November 2026):** in the same shoot the Nikon recorded longest and sat above the Sony, and the iPhone selfie camera sat above both. New setting `MAIN_CAMERA`; phones now go below the other cameras. 127 automated tests pass (1 new, 1 updated for the new order).

**Short phone clip (Claude, 10 November 2026):** in the second test shoot a 7.7 s iPhone 16 Pro selfie clip wasn't synced: its loudness matched the Nikon at about 245.2 s, but the waveform check scored only 0.07-0.08 (voice processing on the phone). A first fix with the sound spectrum placed it 0.2 s early, which Cutting Clockwork saw on the timeline. The fine loudness curve (400 per second, logarithmic) put it at 245.13 s in the Nikon clip and 211.97 s in the Røde file, consistent within 0.01 s, with a clear peak (0.80 against 0.49). That is now the fallback when the waveform can't confirm, before the spectrum. 129 automated tests pass (2 new: one with a generated 'phone' whose waveform differs but whose words line up). Not yet re-validated against the 155-clip set.

## 1.2.0: colour groups per camera (8 November 2026)

Measured in Resolve Studio 21.2 with two generated clips (camera A 10 s, camera B 16 s; multicam on V1 for 0–10 s, camera B directly on V1 for 10–16 s, as `picture_plan` places it): saturation 0 on camera B inside the multicam turned the multicam piece on angle 2 grey, but the direct camera B piece stayed blue. With camera B inside the multicam and the direct piece in one colour group, and saturation 0 on the *Group Post-Clip* layer, both pieces turned grey. In a real 149-clip run, 33 of the 54 items on V1 were direct clips, so this is not rare. New: `colour_groups_per_camera` makes one group per camera and puts every direct clip on V1 in its camera's group; failures are reported, not fatal. The API can't reach the clips inside a multicam, so the user adds those (README). `AddColorGroup` and `AssignToColorGroup` were checked in Resolve on the test project; in a real run on footage from three cameras (8 November 2026) the three groups appeared and the 3 direct clips sat in their camera's group.

**Review round 4 (Antigravity, 8 November 2026): no blocking or important findings, 2 small; both handled.**

| # | Finding | What happened |
|---|---|---|
| 1 | The report said every direct clip was in its colour group before the groups were made, so a failed group gave two contradicting lines | Fixed: the groups are made first; the line only says so when no group or assignment failed. |
| 2 | No test for a V1 item without a media pool item, or a track list of `None` | Test added. |

After the fixes: 112 automated tests pass (3 new, with fake Resolve objects).

## 1.2.0: changes after the review rounds (6 November 2026)

Pause skipping (`picture_stretches`), the clip with picture on V1 where the first camera has none (`picture_plan`), `source_end` and audio linking were reviewed by Antigravity in round 3 (table below). Checked in Resolve Studio 21.2 on 149 real clips: V1 has 54 items (21 multicam, 33 direct clips), 0 frames of gaps, direct clips within 0.4 frame of their own sound, and thumbnails from the middle of all 21 multicam items and 30 of the 33 direct clips show picture. Audio linking (`link_audio_to_picture`) was checked on the same 149 clips and on Sony + separate recorder: every audio item is linked to exactly one picture item, no holes between pieces of a clip, audible sound equals the timeline length (no double sound), recorder and picture stay at the same offset. Trimming in the Resolve interface was tested by hand and works. YouTube, Reels and Reels Multicam were rerun on the same footage: no holes, no double sound, all audio linked. A first run had 7 one-frame gaps: Resolve rounds a 60 fps clip down on a 25 fps timeline, so `source_end` rounds up.

**Review round 3 (Antigravity, 6 November 2026): 2 blocking, 1 important, 1 small; all handled.**

| # | Finding | What happened |
|---|---|---|
| 1 | `split_audio`: end not limited to the file, `GetSourceStartFrame()` one frame early | Fixed: exact left offset, end of the file as limit. Measured: Resolve does not refuse an end past the file, so the feared loss of audio did not occur. WAV clips report no `Frames`, so recorders use their measured duration. |
| 2 | `picture_plan`: a 0-frame piece could stop the script; a clip stretched past its end left a gap | Fixed: empty pieces are skipped, a clip only runs on while it has picture, a pause under half a second stays with the multicam. |
| 3 | One-frame audio snippets; read-back could pick a neighbouring item | Fixed: no cuts within 2 frames of an end, sound links to the picture it overlaps most, neighbours are left out of the read-back. |
| 4 | `source_end` with a clip slower than the timeline; fallback in `replace_with_pieces` | Fixed. Measured: a 25 fps clip on a 50 fps timeline moves in steps of 2 frames, so an odd length can leave a one-frame hole; that beats an overlap. |

After the fixes: 109 automated tests pass; all four scripts rerun on the same footage and Sony + recorder: 0 frames of gaps on V1, no holes in audio, no double sound, all audio linked, direct clips within 0.4 frame of their sound. The fixes themselves were not reviewed again (one round per version).

## 1.2.0 — YouTube and Reels Multicam Timeline, checks of 18 and 27 October 2026 (in progress)

**Design, decided by tests in Resolve Studio 21.1.1:**
- Resolve's own sync (`AutoAlignClips`) is as accurate as the script's but needs the right clips handed to it, so the multicam is built on timecode from the script's own sync: per clip `SetClipProperty('Start TC', …)` and `SetMetadata({'Camera #': n, 'Angle': name})`, then `CreateMulticamClip` with timecode sync and "detect same camera by camera number". Both calls are read back; a clip whose timecode isn't accepted is skipped and reported.
- Timecode above 24 hours is refused by Resolve without an error (a clip from a month later ended up at 01:00:00:00). Hence one multicam per shoot, at most 20 hours each.
- Resolve orders angles by name, not by camera number; angle names start with the number ("1 · Sony …").
- Multicam audio modes (measured with a different tone per camera and an audio render): REFERENCE and ADAPTIVE play only angle 1 and go silent in its gaps; ALL plays every camera at once. The timeline therefore uses the multicam for picture only and places the source audio itself, with the same muting rule as the YouTube timeline.
- Resolve turns a clip's start timecode into time as frame count / real frame rate, also for 29.97 non-drop (measured: a 29.97 NDF clip labelled by the clock landed 4.6 s late at 76 minutes). Every clip therefore gets the frame number of its real start time at its own real rate, from a shared one-hour origin; drop-frame or non-drop only changes how that number is written. Verified on screen in the multicam viewer with 25 fps, 29.97 NDF and 29.97 DF cameras at 975 s and 1010 s: all angles show the same counter.

**Automatic checks (first round):** 61 tests pass (new: shoot grouping and the 20-hour cap, timecode writing incl. drop-frame, multicam timecode for 25, 29.97 NDF/DF and 59.94 DF, angle name order, Multicam variant differs only in `WORKFLOW`). Ruff (F, E9, B, PLE, PLW) and Bandit (medium/high): only the notes already accepted for 1.0/1.1 below, now once per timeline script.

**Single takes (all timeline scripts).** Until now a camera's clock correction needed matches from two of its clips, so a camera with one long take was never synced by sound. Measured on 155 real clips (Sony A7 IV + iPhone 16 Pro): of 332 loudness matches, 55 were true and 277 chance; chance matches scored up to 0.91, as high as true ones, so no threshold on that score is safe. The 1 kHz waveform check separated them completely (55/55 true confirmed, 0/90 chance confirmed; the spectrum check confirmed 28 chance matches and is therefore not used as proof). New rule: when no two-clip consensus exists, the best loudness matches are tried in turn and the first one the waveform confirms sets the clock, with a note in the report. Real-footage check: 12 phone clips synced one at a time against the Sony footage; 10 landed on exactly the same frame as in the full run, the two others (1.0 s and 3.6 s) are too short for any match and fall back to the camera clock (51 minutes off on that phone), which the report says.

**More automated tests:** frame rates 23.976, 24, 50, 59.94, 60, 100 fps and Android VFR; camera names for Canon, Panasonic, Fujifilm, Nikon, GoPro, DJI, Samsung, Pixel, iPhone (stock and Blackmagic app); unknown cameras kept apart by folder and format; generated shoots with a single take whose clock is 70 minutes off (synced within one frame), a camera that heard different sound (not forced into sync), a clock 5 hours off (beyond the tolerance: falls back and says so), a camera without sound, 29.97 fps next to 25 fps, and file and folder names with spaces, emoji, accents and 130 characters.

**Reels Multicam (27 October 2026, Resolve Studio 21.1.2):** the four timeline scripts now share one code base with `WORKFLOW` set to YouTube, Reels, YouTube Multicam or Reels Multicam (87 tests). Angles inside a multicam can't be scaled one by one through the API, so the Reels Multicam project uses *Scale full frame with crop* (`timelineInputResMismatchBehavior = scaleToCrop`, read back). Test with generated clips (two landscape cameras, one portrait phone, clocks off): multicam 1080 × 1920; a still of the landscape angle fills 9:16 without bars; the portrait angle fills the frame in *Open in Timeline* and shows the right counter (within one frame, the known AAC delay); audio placed and muted as in the other scripts.

**Separate recorders (6 November 2026):** raw Røde files have no time stamp at all (no `bext`, no `creation_time`; the file date is the copy date). Each audio file is searched from start to end: loudness match with the longest clips, then the 1 kHz waveform decides. Real test: 18 files (2 exact copies, skipped) against 6 Sony clips: the 3 files that belong to the shoot found, the other 13 left out. Clock drift of the Røde against the Sony: about 10 ms per hour, so one position per file. Only the parts under picture are placed.

**Audio priority (6 November 2026):** `audio_pieces` splits a clip by the better confirmed audio around it; scraps under half a second stay muted. A partly covered clip is replaced by cut pieces (unlink, `DeleteClips`, `AppendToTimeline` with `startFrame`/`endFrame`, link again). Real test, 155 clips, YouTube Timeline and YouTube Multicam on Resolve 21.2: 0.0 s of double sound, 3 clips cut, source position of the pieces matches the timeline within 0.003 s, all 149 picture clips kept. A piece can start one frame late at 59.94 fps; a one-frame gap at the switch point, accepted. Clips without confirmed sync stay whole and audible, with a note.

**Code review by Antigravity, round 2 (6 November 2026)**, seven findings:

| # | Finding | Response |
|---|---|---|
| 1 | Blocking: cutting audio could read back the wrong piece, place an empty piece, or lose the clip if placing failed | Fixed: pieces under two frames are merged, read-back skips pieces already placed and prefers the exact frame, frames are capped at the clip's length, and on any failure the whole clip goes back with a note. |
| 2 | Blocking: the waveform check looked at the start of the source, not in the shared part | Fixed as proposed. Remeasured on real footage: 55 of 55 true matches confirmed, 0 of 150 chance matches. |
| 3 | Overlapping recordings in one folder don't mute each other | Kept on purpose: two recordings at once are usually two speakers (a podcast). The report now names them. Their sound scores are averaged, accepted. |
| 4 | Slow on long files; misses after minute 30 of a clip; silent cut-off at 6 hours | Fixed: the search stops at the first waveform-confirmed clip, clips are searched up to 6 hours, and a longer file gives a note. |
| 5 | Recorders skipped channel mapping, error handling and the Offline check; a piece could run past the group end | Fixed. |
| 6 | Preferred-camera warning, recorder compared with the reference only, file errors | Fixed: the warning moved to the sound ranking, the recorder is compared with the best camera, unreadable files are kept. |
| 7 | Numbers in README and CHANGELOG, audio rules in the README, version of Export for AI Review | Fixed. |

Final run on Resolve Studio 21.2.0.6: all four scripts on real Sony + Røde files, and YouTube Timeline and YouTube Multicam on 149 real clips: 0.0 s of double sound, all picture clips placed. 99 automated tests pass.

**Pauses on multicam timelines (6 November 2026, after review round 2; Dion's practical test):** the timeline showed long black parts where no camera recorded. `picture_stretches` now places only stretches with picture, as parts of the multicam clip (`startFrame`/`endFrame`), one after the other. 149 real clips: 8.7 hours became 4.8 hours in 51 stretches, 0 gaps, 0.0 s of double sound. Not covered by an Antigravity review.

**Live tests (Claude, external scripting):** see CHANGELOG. Still to do: Dion's real-world test.

**Code review by Antigravity (18 October 2026)**, eight findings (`github/reviews/davinci-auto-setup-1.2.0-antigravity.md` in the project notes):

| # | Finding | Response |
|---|---|---|
| 1 | Wrong timecode for 29.97/59.94 drop-frame (3.6 s at the start) and for 29.97 non-drop next to whole-number rates (3.6 s per hour) | Confirmed and fixed. The proposed fix (count in the multicam's label seconds) proved wrong for non-drop in a Resolve test: Resolve reads every timecode as frames / real rate. Fixed with that rule instead (see above), unit-tested and verified on screen. |
| 2 | Timecode and angles were relative to the shoot start, not to the earliest clip Resolve accepted | Fixed: refused clips are dropped and the remaining clips get timecode and angle numbers again, relative to the earliest accepted clip. |
| 3 | No check that the multicam has the expected length; the next shoot could start before the last audio of the previous one ended | Fixed: a warning when the multicam is more than one second shorter or longer than expected; the next shoot starts after the last picture or sound item. |
| 4 | Overlapping clips of one camera were not reported | Fixed: a warning per overlap, as in the YouTube timeline. |
| 5 | No early check for Resolve 21.1 | Fixed: checked before anything is imported or created. |
| 6 | An empty, unnamed audio track when a camera without sound came first | Fixed: every created track gets its camera name, as in the YouTube timeline. |
| 7 | Fewer read-back checks than the YouTube timeline; camera metadata not read back | Fixed: picture size, monitor format and colour management are checked, and `Camera #` and `Angle` are read back. |
| 8 | README said "two"/"both" scripts; `SHOOT_GAP_HOURS` missing from the settings table; `zip()` without `strict` in a test | Fixed. |

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
- The export uses the timeline's resolution. When Deliver already matches it (for example "Timeline Resolution"), the size is not touched: whether that choice survives an explicit size cannot be checked through the API, and a lost choice would export a 16:9 timeline at 9:16 in projects with both. When Deliver differs (a fixed size), the timeline size is set for the export and the fixed size is set back explicitly, because a backup preset does not restore the output size. A 720p option was considered and dropped (Dion, 14 October): an extra FFmpeg step would lengthen the workflow.
- The preset menu label becomes "Custom Export" after any scripted change (confirmed on screen by Dion); render jobs always report `PresetName: 'Custom'`, so the original preset can't be detected. Documented in the README.

**Second opinion (ChatGPT, 14 October 2026)**, eight findings:

| Finding | Response |
|---|---|
| "Entire Timeline" came back as a fixed In/Out range (same frames, but no longer following a longer timeline) | Confirmed in Resolve: after an export, extending the timeline no longer extended the render range. Fixed: the snapshot records whether the timeline had In/Out marks; without marks the range is restored with `SelectAllFrames`. Verified live: the range follows a longer timeline again, and existing marks come back unchanged. |
| The original preset selection is not restored | Not fixable: render jobs always report `PresetName: 'Custom'`, and any scripted change switches the label to "Custom Export". Documented in the README. |
| A time-out started the cleanup while Resolve could still be rendering | Fixed: the script stops the render (`StopRendering`, only after checking at the start that nothing else was rendering) and waits until it has stopped; if it doesn't stop, it changes nothing more and reports the job, folder and backup preset. Verified live with a forced time-out. |
| Failed deletions of jobs and presets were silently accepted | Fixed: every deletion is checked and anything left is reported with its name. |
| An error during cleanup could skip the restore and hide the backup preset | Fixed: each cleanup step runs on its own and adds to the report. |
| A file could appear under the chosen name just before the move | Fixed: the name is claimed by creating the file exclusively, then the export replaces only that empty file. |
| A failing temporary folder left a backup preset behind | Fixed: the folder is created before the backup preset. |
| The recovery message promised more than the preset can restore | Fixed: each setting that didn't come back is listed with the value it should have, and the message says to set those by hand. |

A stopped or failed export can leave its own partial file in its temporary folder; the cleanup now removes that one file (only the name of its own render job) and the empty folder, nothing else.

**Automatic code checks:** Ruff (F, E9, B, PLE, PLW): no findings. Bandit (medium and high): no findings.

**Automated tests:** 21 new tests (41 in total, all passing): export range including single In or Out marks and bad marks, file names, never overwriting, and the Deliver restore against a stand-in that reproduces the audio reset, the empty codec and the unrecoverable file name token.

**Real-world test (Claude, through the Resolve MCP, on a disposable project):** passed for an MP4/H.265 preset with an empty reported codec (3.4 s for a 19.7 s 1080×1920 timeline), ProRes 422 HQ with 24-bit LPCM, an In/Out range (10–300) with `RANGE = 'marks'` (11.7 s file), a fixed 720×1280 Deliver size on a 1080×1920 timeline (exported at 1080×1920, Deliver back on 720×1280), "Entire Timeline" (the range follows a longer timeline afterwards), existing In/Out marks, and a forced time-out (render stopped, nothing left behind). Every readable Deliver setting identical afterwards; marks unchanged; the file name token still followed a renamed timeline; no render jobs, backup presets or temporary folders left. A run started by Dion from Workspace › Scripts produced the MP4 (1080×1920) in the folder he chose; he noticed the preset label, see above. After the second-opinion fixes he ran it again and confirmed that it works (14 October 2026). Not yet tested: Windows and the free version of Resolve.

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

**Review of the three changes of 10 November (Antigravity, `github/reviews/davinci-auto-setup-1.2.0-audio-tracks-antigravity.md`):** two blocking, three important, two small findings, all fixed. A broken recorder is now taken out before the main audio is chosen and goes to the back (it could still end up first). The single-match fallback is the loudness curve with a wide uniqueness check (one clear peak within ±15 s, ≥ 0.70 and 0.15 above the next best) instead of the sound spectrum, which Antigravity measured to accept 28 of 90 chance matches on the 155-clip set. On Cutting Clockwork's test shoot: true match 0.81 against Nikon and Røde (next best 0.59); 13 wrong positions near a rough match peaked at 0.61, none accepted. Two recorders now both stay audible; an unmatched `PREFERRED_AUDIO_CAMERA` no longer switches off recorder priority; a recorder without overlap is checked on its own file; `MAIN_CAMERA` no longer warns in multicam. 133 automated tests pass. Still to do: re-run the 155-clip set with the loudness fallback.

**Same line, two takes (Claude, 10 November 2026):** with all of Cutting Clockwork's test shoots in one folder, the 7.7 s iPhone clip was placed on an earlier take of the same spoken line (loudness 0.74, accepted because it was tried first). The single-match check now tries the waveform on every candidate first, then the loudness curve on every candidate, and only accepts the best loudness spot when it beats every other spot by 0.05 or more (here 0.82 against 0.74); otherwise the clip keeps its clock and the report asks to check it. Rerun on the same folder: the iPhone clip lands 245.16 s into the Nikon clip of its own take, as before. 134 automated tests pass.

**Short phone clip: fallback withdrawn (Claude, 10 November 2026):** on a second look the fine loudness curve of the 7.7 s iPhone clip matched many spots across all of the day's recordings almost equally well (0.80-0.82 in four different files), because the same lines were said in several takes, and Cutting Clockwork saw the clip land on the wrong moment. Neither the spectrum nor the loudness curve can tell those apart, so both fallbacks for a single match were removed again: only the waveform confirms one match, as before. Such a clip keeps its clock and the report flags it; the README lists this as a known limitation. 131 automated tests pass.
