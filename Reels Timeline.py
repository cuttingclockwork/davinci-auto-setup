#!/usr/bin/env python3
"""Build a synced, colour-managed editing timeline from one folder of footage.

Run from Workspace > Scripts inside DaVinci Resolve (macOS or Windows).
Needs FFmpeg (ffprobe + ffmpeg). Source files are never modified.
See README.md for installation, settings and known limitations.
"""
from __future__ import annotations
from array import array
from collections import defaultdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
import json
import hashlib
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
import filecmp
import math
import re
import shutil
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET

VERSION = '1.0.0'  # https://github.com/cuttingclockwork/davinci-auto-setup

# ---------------------------------------------------------------------------
# SETTINGS: the only part most people need to change.
# ---------------------------------------------------------------------------

# 'YouTube'          = 16:9 timeline with landscape clips only, one track per camera.
# 'Reels'            = 9:16 timeline with portrait clips, plus landscape clips cropped to fill.
# 'YouTube Multicam' = 16:9, one multicam clip per shoot (switch cameras while editing); Resolve 21.1+.
# 'Reels Multicam'   = 9:16, one multicam clip per shoot, landscape angles cropped to fill; Resolve 21.1+.
WORKFLOW = 'Reels'

# Colour profile per camera. Key: (part of) the camera name exactly as the
# report lists it under CAMERAS. Value: the exact name from Resolve's
# Clip Attributes > Input Color Space list. Cameras that store their colour
# space in metadata (Sony with its XML file, iPhone HLG/Apple Log, BRAW, many
# cinema cameras) are detected automatically and need no entry here.
CAMERA_PROFILES = {
    # 'Panasonic': 'Panasonic V-Gamut/V-Log',
    # 'Canon EOS R6': 'Canon Cinema Gamut/Canon Log 3',
    # 'DJI': 'DJI D-Gamut/D-Log',
}

# Which camera you hear. Empty = automatic: where cameras recorded at the same
# time, the script measures their sound and keeps the cleanest one audible
# (least background noise and echo, no distortion, not muffled). A separate audio
# recorder in the folder always goes first (unless its recording is broken). Fill in (part
# of) a camera name to always prefer that camera, e.g. 'Sony' or 'Audio recorder'.
PREFERRED_AUDIO_CAMERA = ''

# YouTube and Reels timelines (not multicam): which camera's picture you see; it goes on
# the top video track. Empty = automatic:
# the sync-reference camera (the dedicated camera that recorded the most). Fill in
# (part of) a camera name as the report lists it, e.g. 'Sony'. Phones go at the bottom.
MAIN_CAMERA = ''

# Timeline frame rate, e.g. 25 or 29.97. None = the lowest source frame rate.
TIMELINE_FPS = None

# How far apart camera clocks may be (hours) and still be matched by sound.
# Larger values find cameras set to the wrong time zone, but take longer.
CLOCK_TOLERANCE_HOURS = 3

# Folder that contains ffmpeg and ffprobe, if the script cannot find them itself.
FFMPEG_FOLDER = ''

# Multicam only: a pause longer than this (hours) between recordings starts a
# new shoot, which gets its own multicam clip.
SHOOT_GAP_HOURS = 3

# ---------------------------------------------------------------------------

FORMATS = {'YouTube': ('3840', '2160'), 'Reels': ('1080', '1920'),
           'YouTube Multicam': ('3840', '2160'), 'Reels Multicam': ('1080', '1920')}
WIDTH, HEIGHT = FORMATS[WORKFLOW]
VERTICAL = WORKFLOW.startswith('Reels')
MULTICAM = WORKFLOW.endswith('Multicam')

VIDEO_SUFFIXES = {'.mov', '.mp4', '.mxf', '.m4v', '.mts', '.m2ts', '.avi', '.mkv', '.webm', '.mpg', '.mpeg', '.3gp', '.braw', '.r3d'}
AUDIO_SUFFIXES = {'.wav', '.aif', '.aiff', '.flac', '.m4a', '.mp3'}
SAMPLE_RATE = 400
ENVELOPE_HZ = 10
MAX_CLOCK_ERROR_SECONDS = CLOCK_TOLERANCE_HOURS * 3600
MIN_MATCH_SCORE = 0.55
MIN_MATCH_OVERLAP = 35
SUPPORTED_TIMELINE_RATES = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)
# Variable-frame-rate phones report averages such as 29.87; snap those to 29.97.
RATE_SNAP_TOLERANCE = .015
# Sound quality check: another camera's sound only takes over when it scores
# clearly better, so near-equal tracks never flip on a measuring detail.
QUALITY_MARGIN_DB = 4.0
# A separate recorder is there on purpose: it always goes first, unless the recording
# itself is broken (audible clipping, or hardly any voice in it).
RECORDER_MIN_CONTRAST_DB = 20.0
RECORDER_MAX_CLIPPED = .001
# Phones (and some cameras) suppress noise between words, which makes the pauses almost
# silent and the voice-to-background contrast look far better than the microphone is.
# Measured 10 Nov 2026: an iPhone 16 Pro selfie camera at 59.5 dB against 34.6 dB for a
# Røde Wireless PRO on the speaker's chest. Above this cap, contrast no longer counts.
CONTRAST_CAP_DB = 45.0
QUALITY_WINDOWS = 6
QUALITY_WINDOW_SECONDS = 15
QUALITY_RATE = 16000
CONFIRMED_SYNC = ('sound reference', 'audio match', 'waveform match', 'spectral match', 'audio clock anchor', 'recorder match')
RECORDER_SEARCH_CLIPS = 40  # longest clips tried per audio file
RECORDER_MAX_HOURS = 6
PHONE_MAKES = {'apple', 'samsung', 'google', 'xiaomi', 'oneplus', 'huawei', 'oppo',
               'vivo', 'motorola', 'nothing', 'honor', 'realme', 'sony mobile'}

IS_WINDOWS = sys.platform.startswith('win')
IS_MAC = sys.platform == 'darwin'


def app_folder(kind):
    """Per-user cache and log folders that exist on every platform."""
    if IS_WINDOWS:
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        return local / 'Resolve Timeline Scripts' / ('Cache' if kind == 'cache' else 'Logs')
    if IS_MAC:
        return Path.home() / 'Library' / ('Caches' if kind == 'cache' else 'Logs') / 'Resolve Timeline Scripts'
    base = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    return base / 'resolve-timeline-scripts' / kind


# Shared behaviour is intentionally identical in both menu scripts; only
# WORKFLOW differs. The cache holds sound analysis only, never video.
CACHE_ROOT = app_folder('cache') / 'audio-v2'
REPORT_ROOT = app_folder('logs')
RECOVERABLE = (OSError, ValueError, TypeError, KeyError, OverflowError, RuntimeError, subprocess.SubprocessError)


def say(*parts):
    """Resolve's console on Windows may not accept every character in a file name."""
    try:
        print(*parts)
    except UnicodeEncodeError:
        print(*(str(p).encode('ascii', 'replace').decode() for p in parts))


def run(command, timeout, text=False):
    options = {'capture_output': True, 'timeout': timeout}
    if text:
        options.update(text=True, encoding='utf-8', errors='replace')
    if IS_WINDOWS:
        # Without this every ffmpeg call flashes a console window.
        options['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.run(command, **options)


def path_key(path):
    """Windows paths compare case-insensitively; Resolve may report another case."""
    return os.path.normcase(str(Path(path).resolve()))


def clean(value):
    return ' '.join(str(value or '').replace('\x00', ' ').split())


def number(value, default=0.0):
    try:
        result = float(Fraction(str(value).strip()))
        return result if math.isfinite(result) else default
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return default


def cached_audio(command, path, timeout):
    """Reuse only matching file/decoder signatures; damaged caches are disposable."""
    cache_file = None
    try:
        stat = Path(path).stat()
        decoder = Path(command[0]).stat()
        signature = [str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns,
                     stat.st_ctime_ns, decoder.st_size, decoder.st_mtime_ns, command]
        key = hashlib.sha256(json.dumps(signature).encode()).hexdigest()
        cache_file = CACHE_ROOT / (key + '.bin')
        if cache_file.is_file():
            raw = cache_file.read_bytes()
            if raw[:4] == b'RTA2' and len(raw) >= 36:
                payload = raw[36:]
                if hashlib.sha256(payload).digest() == raw[4:36]:
                    return payload
    except OSError:
        pass
    result = run(command, timeout)
    need(result.returncode == 0, 'Cannot read audio: ' + str(path))
    payload = result.stdout
    if cache_file and len(payload) <= 8 * 1024 * 1024:
        temporary = None
        try:
            CACHE_ROOT.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=CACHE_ROOT, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(b'RTA2' + hashlib.sha256(payload).digest() + payload)
            temporary.replace(cache_file)
        except OSError:
            pass
        finally:
            if temporary and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass
    return payload


def trim_audio_cache():
    """Bound this disposable, shared cache to 256 MiB."""
    try:
        files = sorted(((p.stat().st_mtime, p.stat().st_size, p)
                        for p in CACHE_ROOT.glob('*.bin')), reverse=True)
        total = 0
        for _, size, path in files:
            total += size
            if total > 256 * 1024 * 1024:
                path.unlink()
    except OSError:
        pass


def inspect_sources(paths, ffprobe):
    def one(path):
        try:
            return inspect(Path(path), ffprobe)
        except RECOVERABLE as error:
            return None, 'Unreadable: ' + str(error)
    rows, excluded = [], []
    # Disk reads are bounded; Resolve API calls stay on the main thread.
    with ThreadPoolExecutor(max_workers=4) as workers:
        for path, (row, reason) in zip(paths, workers.map(one, paths)):
            if row:
                rows.append(row)
            else:
                excluded.append({'file': str(path), 'reason': reason})
    return rows, excluded


def allocate_tracks(rows, fps, warnings=None):
    """Preserve simultaneous clips, even from cameras with identical names.

    Video, top to bottom: the main camera (MAIN_CAMERA, else the sync reference), other
    cameras, phones. Audio: best-sounding camera on A1, then the others by sound quality.
    """
    labels, ends = {}, defaultdict(list)
    info = {}
    recorders = {row['camera'] for row in rows if row.get('recorder')}
    for row in rows:
        camera = info.setdefault(row['camera'], {'phone': False, 'reference': False,
                                                 'duration': 0.0, 'rank': len(rows)})
        camera['phone'] = camera['phone'] or row['is_phone']
        camera['reference'] = camera['reference'] or row['reference_audio']
        camera['duration'] += row['duration']
        camera['rank'] = min(camera['rank'], row.get('audio_rank', len(rows)))
    for row in sorted(rows, key=lambda r: (r['sort_time'], r['path'])):
        camera = row['camera']
        start = round(row['sort_time'] * fps)
        duration = max(1, math.ceil(row['duration'] * fps - 1e-6)) + 1  # protect relative frame rounding
        lane = next((i for i, end in enumerate(ends[camera]) if end <= start), len(ends[camera]))
        if lane == len(ends[camera]):
            ends[camera].append(start + duration)
        else:
            ends[camera][lane] = start + duration
        row['lane'] = (camera, lane)
    wanted = MAIN_CAMERA.strip().lower()
    video_cameras = [camera for camera in ends if camera not in recorders]
    main = max((c for c in video_cameras if wanted and wanted in c.lower()),
               key=lambda c: info[c]['duration'], default=None)
    if wanted and main is None and warnings is not None:
        warnings.append('MAIN_CAMERA "%s" matches no camera with picture; the sync reference is on top.'
                        % MAIN_CAMERA)
    def video_order(camera):
        c = info[camera]
        if main:
            rank = 0 if camera == main else 3 if c['phone'] else 1 if c['reference'] else 2
        else:
            rank = 3 if c['phone'] else 0 if c['reference'] else 2
        return (rank, -c['duration'], camera)
    def audio_order(camera):
        c = info[camera]
        return (c['rank'], -c['duration'], camera)
    # Higher V numbers are visually above lower V numbers; A1 is the top audio track.
    video_lanes = [(camera, lane) for camera in sorted(ends, key=video_order)
                   for lane in range(len(ends[camera])) if camera not in recorders]
    audio_lanes = [(camera, lane) for camera in sorted(ends, key=audio_order)
                   for lane in range(len(ends[camera]))]
    indices = {lane: len(video_lanes) - i for i, lane in enumerate(video_lanes)}
    audio_indices = {lane: i + 1 for i, lane in enumerate(audio_lanes)}
    for row in rows:
        row['track_index'] = indices.get(row['lane'])
        row['audio_track_index'] = audio_indices[row['lane']]
        row['lane_label'] = row['camera'] + (' — overlap %d' % (row['lane'][1] + 1) if row['lane'][1] else '')
    return {indices[(camera, lane)]: camera + (' — overlap %d' % (lane + 1) if lane else '')
            for camera, lane in reversed(video_lanes)}


def timeline_items_index(timeline, media_type, indices):
    items = {}
    for index in indices:
        for item in timeline.GetItemListInTrack(media_type, index) or []:
            if item is None:
                continue
            media = item.GetMediaPoolItem()
            if media:
                items[(index, round(item.GetStart()), path_key(media.GetClipProperty('File Path')))] = item
    return items


def import_sources(pool, rows, excluded):
    """Retry only missing files; one unsupported codec must not lose the batch."""
    imported = {}
    def collect(clips):
        for clip in clips or []:
            if clip:
                path = clip.GetClipProperty('File Path')
                if path:
                    imported[path_key(path)] = clip
    for first in range(0, len(rows), 50):
        batch = rows[first:first + 50]
        try:
            collect(pool.ImportMedia([r['path'] for r in batch]))
        except RuntimeError:
            pass
        for row in batch:
            if row['key'] not in imported:
                try:
                    collect(pool.ImportMedia([row['path']]))
                except RuntimeError:
                    pass
    accepted = []
    for row in rows:
        clip = imported.get(row['key'])
        if not clip or clip.GetClipProperty('Online Status') == 'Offline':
            excluded.append({'file': row['path'], 'reason': 'Resolve could not import this video (codec or file problem).'})
            continue
        frames = number(clip.GetClipProperty('Frames'))
        rate = number(clip.GetClipProperty('FPS'))
        if frames <= 0 or rate <= 0:
            excluded.append({'file': row['path'], 'reason': 'Resolve reports no usable video frames or frame rate.'})
            continue
        row.update(frames=int(frames), fps=rate, duration=frames / rate)
        accepted.append(row)
    return accepted, imported


LAST_REPORT = None


def save_report(report):
    """Persistent evidence also when a later critical validation fails."""
    global LAST_REPORT
    LAST_REPORT = report
    try:
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*]', '_', report.get('project', 'Timeline'))
        path = REPORT_ROOT / (name + ' ' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        report['report_path'] = str(path)
        text_path = path.with_suffix('.txt')
        report['text_report_path'] = str(text_path)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        lines = [WORKFLOW + ' timeline: run report (script version %s)' % VERSION,
                 'Result: ' + ('Stopped; see the error below.' if report.get('status') == 'failed' else 'Timeline created.'),
                 'Project: ' + report.get('project', 'Not created'),
                 'Video clips placed: ' + str(report.get('selected', 0)),
                 'Files skipped: ' + str(len(report.get('excluded', []))),
                 'Non-video/helper files ignored: ' + str(report.get('ignored_nonvideo_files', 0)),
                 '']
        if report.get('timeline_fps'):
            lines.extend(['Timeline frame rate: %g fps (sources: %s)' % (
                report['timeline_fps'], ', '.join('%g' % r for r in report.get('source_frame_rates', []))), ''])
        if report.get('error'):
            lines.extend(['ERROR', report['error'], ''])
        if report.get('top_video') and not MULTICAM:
            lines.extend(['Picture on top: %s (set MAIN_CAMERA at the top of the script to choose another).'
                          % report['top_video'], ''])
        if report.get('cameras'):
            lines.append('CAMERAS')
            for camera in report['cameras']:
                lines.append('%s: %d clip(s)%s' % (camera['camera'], camera['clips'],
                                                   ', sync reference' if camera['reference_audio'] else ''))
                lines.append('  Colour: ' + camera['colour'])
            lines.append('')
        if report.get('multicams'):
            lines.append('MULTICAMS (one per shoot; switch cameras in the multicam viewer)')
            for m in report['multicams']:
                lines.append('%s: %d clip(s); angles: %s' % (m['name'], m['clips'], ', '.join(m['angles'])))
            lines.append('Picture comes from the multicam (track V1); the sound under it is placed per camera, '
                         'best camera audible.')
            lines.append('To see all cameras: choose Multicam in the source viewer menu (bottom left of the viewer). '
                         'A black angle means that camera was not recording at that moment.')
            if report.get('clip_colours'):
                lines.append('Clip colour per camera: ' + ', '.join('%s = %s' % (camera, colour) for camera, colour
                                                                    in report['clip_colours'].items()) + '.')
            if report.get('colour_groups'):
                lines.append('Colour groups, one per camera: ' + ', '.join(report['colour_groups']) + '. Clips that sit '
                             'on V1 directly are already in them. To add the clips inside the multicam: on the Edit page '
                             'select a multicam clip › Clip › Open in Timeline, go to the Color page; Clips › Clip Color › that '
                             'camera\'s colour; select all; right-click › Groups › Assign to Group › the group with that '
                             'colour in its name. Grade each camera once on the Group Post-Clip layer, then set the '
                             'filter back to All Clips.')
            lines.append('')
        if report.get('audio_summary'):
            lines.append('AUDIO')
            lines.extend(report['audio_summary'])
            lines.append('')
        lines.append('SKIPPED FILES')
        lines.extend(item['file'] + '\n  Reason: ' + item['reason'] for item in report.get('excluded', []))
        if not report.get('excluded'):
            lines.append('None.')
        lines.extend(['', 'PLEASE CHECK'])
        lines.extend(report.get('warnings') or ['Nothing.'])
        lines.extend(['', 'Detailed report: ' + str(path)])
        text_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    except OSError as error:
        report['report_write_error'] = str(error)
    say('Result:', report.get('status'), '; clips:', report.get('selected', 0),
        '; skipped:', len(report.get('excluded', [])),
        '; to check:', len(report.get('warnings', [])))
    say('Report:', report.get('report_path', 'Could not be saved'))
    if 'report_write_error' in report:
        say(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def need(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def script_folders():
    """Resolve's own script folders, so ffmpeg and ffprobe can simply sit next to the scripts."""
    folders = []
    here = globals().get('__file__')
    if here:
        folders.append(Path(here).resolve().parent)
    if IS_WINDOWS:
        roots = [Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming'),
                 Path(os.environ.get('ProgramData') or r'C:\ProgramData')]
        folders += [r / 'Blackmagic Design' / 'DaVinci Resolve' / 'Support' / 'Fusion' / 'Scripts' / 'Utility'
                    for r in roots]
    else:
        folders += [base / 'Library' / 'Application Support' / 'Blackmagic Design' / 'DaVinci Resolve' / 'Fusion'
                    / 'Scripts' / 'Utility' for base in (Path.home(), Path('/'))]
    return folders


def binaries():
    exe = '.exe' if IS_WINDOWS else ''
    if FFMPEG_FOLDER:
        # An explicit folder is a deliberate choice: use both tools from there, or say what is wrong with it.
        folder = Path(FFMPEG_FOLDER).expanduser()
        found = tuple(str(folder / (name + exe)) for name in ('ffprobe', 'ffmpeg'))
        for path in found:
            problem = tool_problem(path)
            if problem:
                raise RuntimeError('%s (FFMPEG_FOLDER at the top of this script): %s' % (path, problem))
        return found
    folders = []
    if IS_WINDOWS:
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        folders += [local / 'Microsoft' / 'WinGet' / 'Links',
                    Path(os.environ.get('ProgramData') or r'C:\ProgramData') / 'chocolatey' / 'bin',
                    Path.home() / 'scoop' / 'shims',
                    Path(os.environ.get('ProgramFiles') or r'C:\Program Files') / 'ffmpeg' / 'bin',
                    Path(r'C:\ffmpeg\bin')]
        # A winget install that is not on PATH yet (Resolve started before the install).
        folders += sorted((local / 'Microsoft' / 'WinGet' / 'Packages').glob('*FFmpeg*/*/bin'))
    else:
        folders += [Path('/opt/homebrew/bin'), Path('/usr/local/bin'), Path('/usr/bin'), Path.home() / 'bin']
    folders += script_folders()

    def locate(name):
        """First copy that actually starts; a broken old install doesn't hide a working one further on."""
        candidates = [shutil.which(name)] + [str(f / (name + exe)) for f in folders]
        problems = []
        for path in dict.fromkeys(c for c in candidates if c and Path(c).is_file()):
            problem = tool_problem(path)
            if not problem:
                return path
            problems.append('%s: %s' % (path, problem))
        if problems:
            raise RuntimeError(name + ' was found but does not start. ' + ' '.join(problems))
        raise RuntimeError(name + ' not found. Install FFmpeg (see README), put ffmpeg and ffprobe in the same '
                           'folder as this script, or set FFMPEG_FOLDER at the top of this script.')
    return locate('ffprobe'), locate('ffmpeg')


def tool_problem(path):
    """None when the tool starts; otherwise a short reason the user can act on."""
    if not Path(path).is_file():
        return 'not found'
    if not IS_WINDOWS and not os.access(path, os.X_OK):
        return 'not allowed to run (no execute permission).'
    try:
        if run([path, '-version'], 15).returncode == 0:
            return None
        reason = 'it stopped with an error.'
    except subprocess.TimeoutExpired:
        reason = 'it did not respond.'
    except (OSError, subprocess.SubprocessError) as error:
        reason = str(error).rstrip('.') + '.'
    if IS_MAC:
        reason += (' If macOS showed "Not Opened" for a copy you downloaded yourself, click Done (not Move to Bin). Then open System Settings > '
                   'Privacy & Security, scroll down, click "Open Anyway" and run the script again. You may need to '
                   'do this once for ffprobe and once for ffmpeg.')
    return reason


def parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    value = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', value.replace('Z', '+00:00'))
    try:
        date = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    # Camera-local metadata without an offset cannot safely be compared to UTC.
    if date.tzinfo is None or date.year < 1970:
        return None
    return date.astimezone(timezone.utc).timestamp()


def source_frame_rate(stream):
    """Use a nominal delivery rate, including slow/VFR/high-speed recordings."""
    rates = [number(stream.get(key)) for key in ('r_frame_rate', 'avg_frame_rate')]
    rates = [r for r in rates if 0 < r <= 1000]
    if not rates:
        frames, duration = number(stream.get('nb_frames')), number(stream.get('duration'))
        rates = [frames / duration] if frames > 0 and duration > 0 else [25.0]
    # A bogus very high r_frame_rate is common with variable frame rate video.
    rate = rates[1] if len(rates) > 1 and rates[0] > rates[1] * 1.5 else rates[0]
    nearest = min(SUPPORTED_TIMELINE_RATES, key=lambda option: abs(option - rate))
    if abs(nearest - rate) / nearest < RATE_SNAP_TOLERANCE:
        return nearest
    slower = [r for r in SUPPORTED_TIMELINE_RATES if r <= rate]
    return max(slower) if slower else min(SUPPORTED_TIMELINE_RATES)


def timeline_frame_rate(rows):
    if TIMELINE_FPS:
        chosen = min(SUPPORTED_TIMELINE_RATES, key=lambda option: abs(option - float(TIMELINE_FPS)))
        need(abs(chosen - float(TIMELINE_FPS)) < .01,
             'TIMELINE_FPS must be one of: ' + ', '.join('%g' % r for r in SUPPORTED_TIMELINE_RATES))
        return chosen
    return min(row['source_fps'] for row in rows)


def frame_rate_warnings(rows, fps):
    """Name source rates that cannot divide evenly into the timeline rate."""
    counts = defaultdict(int)
    for row in rows:
        ratio = row['source_fps'] / fps
        if abs(ratio - round(ratio)) < .002 and round(ratio) >= 1:
            continue  # same rate, or 50 -> 25 / 59.94 -> 29.97: every 2nd frame, smooth
        counts[row['source_fps']] += 1
    return ['%d clip(s) recorded at %g fps play on a %g fps timeline with slight judder '
            '(frames are skipped or repeated). Record all cameras at the same frame rate, '
            'or set TIMELINE_FPS at the top of the script.' % (n, rate, fps)
            for rate, n in sorted(counts.items())]


def monitor_format(fps):
    need(fps in SUPPORTED_TIMELINE_RATES, 'Unknown monitor frame rate: ' + str(fps))
    return 'HD 1080p ' + format(fps, 'g')


def managed_color_settings():
    return {'colorScienceMode': 'davinciYRGBColorManagedv2',
            'isAutoColorManage': '0',
            'rcmPresetMode': 'Custom',
            'separateColorSpaceAndGamma': '0',
            'colorSpaceTimeline': 'DaVinci WG/Intermediate',
            'colorSpaceOutput': 'Rec.709 Gamma 2.4',
            'inputDRT': 'DaVinci',
            'outputDRT': 'DaVinci',
            # Without this the output DRT dims and desaturates clips that are already
            # Rec.709 (75% grey 191 -> 159, measured); log and HLG clips don't change.
            'useInverseDRT': '1'}


def sony_sidecar(path, recorded, frames):
    """Use a nearby Sony XML only when it describes this exact recording."""
    name = path.stem + 'M01.XML'
    candidates = [path.with_name(name), path.parent.parent / name,
                  path.parent.parent.parent / name]
    candidates = [variant for xml in candidates for variant in
                  (xml, xml.with_suffix('.xml'), xml.with_name(path.stem + 'm01.xml'))]
    for xml in dict.fromkeys(candidates):
        if not xml.is_file():
            continue
        try:
            root = ET.parse(xml).getroot()
            sony = {x.get('name'): x.get('value') for x in root.iter()
                    if x.tag.split('}')[-1] == 'Item'}
            for x in root.iter():
                tag = x.tag.split('}')[-1]
                if tag == 'CreationDate':
                    sony['CreationDate'] = x.get('value')
                elif tag == 'Duration':
                    sony['Duration'] = x.get('value')
                elif tag == 'Device':
                    sony['manufacturer'] = x.get('manufacturer')
                    sony['model'] = x.get('modelName')
                    sony['serial'] = x.get('serialNo')
            if (sony.get('manufacturer') or '').lower() != 'sony':
                continue
            xml_time = parse_time(sony.get('CreationDate'))
            if recorded is not None and xml_time is not None and abs(recorded - xml_time) > 2:
                continue
            if frames and sony.get('Duration') and abs(frames - int(sony['Duration'])) > 1:
                continue
            return sony
        except (ET.ParseError, ValueError, OSError):
            continue
    return {}


def recording_app(tags, is_iphone):
    if not is_iphone:
        return ''
    software = str(tags.get('com.apple.quicktime.software') or tags.get('software') or '').strip()
    if 'blackmagic' in software.lower() or 'com.blackmagic-design.camera.dateRecorded' in tags:
        return 'Blackmagic Camera'
    if re.fullmatch(r'\d+(?:\.\d+)*', software):
        return 'iPhone Camera'
    return software or 'iPhone unknown app'


def strip_make(model, make):
    if make and model.lower().startswith(make.lower()):
        return model[len(make):].strip(' -_')
    return model


def identify_camera(path, stream, tags, sony, rate):
    """Name a camera from its metadata. Returns (label, make, model, is_phone).

    Unknown cameras are grouped by folder and recording format, so two
    untagged cameras in one shoot do not merge into one track or sync group.
    """
    lens = clean(tags.get('com.blackmagic-design.camera.lensType'))
    make = clean(tags.get('com.apple.quicktime.make') or tags.get('make')
                 or tags.get('com.android.manufacturer') or tags.get('manufacturer'))
    model = clean(tags.get('com.apple.quicktime.model') or tags.get('model')
                  or tags.get('com.android.model'))
    brand = clean(tags.get('major_brand')).upper()
    if 'iphone' in ' '.join((make, model, lens)).lower():
        found = re.search(r'iPhone(?:\s+\d+)?(?:\s+(?:Pro(?:\s+Max)?|Plus|mini))?', ' '.join((model, lens, make)), re.I)
        label = found.group(0) if found else 'iPhone'
        return label, 'Apple', label, True
    if sony or brand.startswith('XAVC') or 'sony' in make.lower():
        name = clean(sony.get('model')) or strip_make(model, 'Sony')
        label = 'Sony' + (' ' + name if name else '')
        if name and sony.get('serial') and sony['serial'] not in ('4294967295', '0'):
            label += ' #' + sony['serial']
        return label, 'Sony', name, False
    if not make:
        haystack = ' '.join((clean(stream.get('tags', {}).get('handler_name')),
                             clean(tags.get('encoder')), clean(tags.get('firmware')))).lower()
        hints = (('gopro', 'GoPro'), ('dji', 'DJI'), ('insta360', 'Insta360'), ('canon', 'Canon'),
                 ('panasonic', 'Panasonic'), ('fujifilm', 'Fujifilm'), ('nikon', 'Nikon'))
        make = next((name for key, name in hints if key in haystack), '')
        if not make and brand == 'CAEP':
            make = 'Canon'
        if not make and any(k.startswith('com.blackmagic-design.camera.') for k in tags):
            make = 'Blackmagic Design'
    if make.islower():
        make = make.capitalize()
    model = strip_make(model, make)
    if make or model:
        label = ' '.join(x for x in (make, model) if x)
        phone = make.lower() in PHONE_MAKES or 'com.android.version' in tags
        return label, make, model, phone
    label = 'Camera (%s, %s %sx%s %gp)' % (path.parent.name or 'top folder', stream.get('codec_name', 'video'),
                                         stream.get('width', '?'), stream.get('height', '?'), rate)
    return label, '', '', False


def inspect_audio_file(path, data):
    """A recorder or wireless mic file: sound only, and usually no recording time at all."""
    audio = any(s.get('codec_type') == 'audio' for s in data.get('streams', []))
    duration = number(data.get('format', {}).get('duration'))
    if not audio or path.suffix.lower() not in AUDIO_SUFFIXES or duration <= 0:
        return None, 'no video picture'
    return {'recorder': True, 'name': path.name, 'path': str(path.resolve()), 'key': path_key(path),
            'camera': 'Audio recorder (%s)' % (path.parent.name or 'top folder'), 'make': '', 'camera_model': '',
            'is_phone': False, 'audio': True, 'duration': duration, 'capture_app': '', 'timestamp': 0.0,
            'timestamp_source': 'none', 'source_fps': None}, None


def inspect(path, ffprobe):
    command = [ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]
    result = run(command, 90, text=True)
    need(result.returncode == 0, 'Cannot analyse media: ' + str(path))
    data = json.loads(result.stdout)
    stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
    if stream is None:
        return inspect_audio_file(path, data)
    rotation = next((s.get('rotation') for s in stream.get('side_data_list', []) if 'rotation' in s), stream.get('tags', {}).get('rotate', 0))
    w, h = int(number(stream.get('width'))), int(number(stream.get('height')))
    need(w > 0 and h > 0, 'No usable picture size: ' + str(path))
    aspect = number(str(stream.get('sample_aspect_ratio', '1:1')).replace(':', '/'), 1.0)
    w = round(w * (aspect if aspect > 0 else 1.0))
    if round(number(rotation)) % 180 == 90:
        w, h = h, w
    if w == h:
        return None, 'square video'
    if not VERTICAL and w < h:
        return None, 'portrait video (the Reels scripts use these)'
    tags = dict(stream.get('tags') or {})
    tags.update(data.get('format', {}).get('tags') or {})
    recorded = None
    for key in ('com.blackmagic-design.camera.dateRecorded', 'com.apple.quicktime.creationdate', 'creation_time'):
        recorded = parse_time(tags.get(key))
        if recorded is not None:
            break
    sony = sony_sidecar(path, recorded, int(number(stream.get('nb_frames'))))
    rate = source_frame_rate(stream)
    camera, make, camera_model, is_phone = identify_camera(path, stream, tags, sony, rate)
    # XML contains Sony's local wall time. The MP4 UTC field is preferred because
    # it can be compared directly to other cameras' UTC creation time.
    if recorded is None and sony:
        recorded = parse_time(sony.get('CreationDate'))
    timestamp_source = 'metadata'
    if recorded is None:
        recorded = path.stat().st_mtime
        timestamp_source = 'file modification time (not verified capture time)'
    profile = None
    if sony:
        gamma = (sony.get('CaptureGammaEquation') or '').lower()
        gamut = (sony.get('CaptureColorPrimaries') or '').lower()
        if 's-log3' in gamma and 's-gamut3-cine' in gamut:
            profile = 'S-Gamut3.Cine/S-Log3'
        elif 's-log3' in gamma and 's-gamut3' in gamut:
            profile = 'S-Gamut3/S-Log3'
    duration = number(stream.get('duration')) or number(data.get('format', {}).get('duration'))
    if duration <= 0:
        frames, fallback = number(stream.get('nb_frames')), number(stream.get('avg_frame_rate')) or number(stream.get('r_frame_rate'))
        duration = frames / fallback if frames > 0 and fallback > 0 else 0
    need(duration > 0, 'No usable video duration: ' + str(path))
    # Trust the recorded transfer characteristic, not a folder name such as
    # "Phone with LUT": a stock phone camera can record HLG/Dolby Vision.
    primaries, transfer = stream.get('color_primaries'), stream.get('color_transfer')
    if profile is None and primaries == 'bt2020' and transfer == 'arib-std-b67':
        profile = 'Rec.2100 HLG (Scene)'
    elif profile is None and primaries == 'bt2020' and transfer == 'smpte2084':
        profile = 'Rec.2100 ST2084'
    # Many log cameras still tag their stream as Rec.709, so this is weak evidence.
    tagged_709 = primaries == 'bt709' and transfer == 'bt709'
    raw_rate = number(stream.get('r_frame_rate')) or number(stream.get('avg_frame_rate'))
    rate_warning = ''
    if raw_rate <= 0:
        rate_warning = 'Frame rate missing; a safe timeline rate was derived or 25 fps used.'
    elif raw_rate < 23.9 or raw_rate > 60.1:
        rate_warning = 'Unusual source frame rate %g fps; placed on a supported timeline rate without changing playback speed.' % raw_rate
    return {'rate_warning': rate_warning, 'name': path.name, 'path': str(path.resolve()), 'key': path_key(path),
            'camera': camera, 'make': make, 'camera_model': camera_model, 'is_phone': is_phone,
            'capture_app': recording_app(tags, camera.startswith('iPhone')),
            'apple_core_media': 'Core Media Video' in str(stream.get('tags', {}).get('handler_name', '')),
            'timestamp': recorded, 'timestamp_source': timestamp_source, 'duration': duration,
            'audio': any(s.get('codec_type') == 'audio' for s in data.get('streams', [])),
            'profile': profile, 'tagged_709': tagged_709, 'sony_metadata': sony,
            'source_fps': rate, 'orientation': 'landscape' if w > h else 'portrait'}, None


def same_folder_and_day(row, rows):
    parent = Path(row['path']).parent
    day = datetime.fromtimestamp(row['timestamp'], timezone.utc).date()
    return [other for other in rows if other is not row
            and Path(other['path']).parent == parent
            and datetime.fromtimestamp(other['timestamp'], timezone.utc).date() == day]


def reconcile_missing_camera_metadata(rows):
    """Use unambiguous, same-day sibling recordings when one file lost tags.

    A missing Sony XML or a Core Media export must not become a new camera
    whose audio can never overlap recordings from its real camera.
    """
    warnings = []
    for row in rows:
        # Brand known, model lost (e.g. Sony MP4 without its XML).
        if not row['make'] or row['camera'] != row['make']:
            continue
        verified = [o for o in same_folder_and_day(row, rows)
                    if o['make'] == row['make'] and o['camera'] != o['make']]
        models = {other['camera'] for other in verified}
        if len(models) != 1:
            continue
        row['camera'] = models.pop()
        row['camera_model'] = verified[0]['camera_model']
        warnings.append('Camera model for %s taken from recordings in the same folder on the same day.' % row['name'])
    for row in rows:
        if (row['make'] or not row.get('apple_core_media')
                or row.get('timestamp_source', 'metadata') != 'metadata'):
            continue
        verified = [o for o in same_folder_and_day(row, rows) if o['camera'].startswith('iPhone')]
        cameras = {other['camera'] for other in verified}
        if len(cameras) != 1:
            continue
        row.update(camera=cameras.pop(), make='Apple', is_phone=True,
                   camera_model=verified[0]['camera_model'])
        apps = {other['capture_app'] for other in verified}
        if len(apps) == 1:
            row['capture_app'] = apps.pop()
        warnings.append('Camera model for %s taken from Core Media recordings in the same folder on the same day.' % row['name'])
    return warnings


def envelope(path, ffmpeg, seconds_limit=1800):
    command = [ffmpeg, '-v', 'error', '-i', str(path), '-map', '0:a:0', '-vn', '-ac', '1', '-ar', str(SAMPLE_RATE), '-t', str(seconds_limit), '-f', 'f32le', '-']
    raw = cached_audio(command, path, max(120, seconds_limit // 3))
    samples = array('f')
    samples.frombytes(raw[:len(raw) // 4 * 4])
    samples = array('f', (x if math.isfinite(x) else 0.0 for x in samples))
    stride = SAMPLE_RATE // ENVELOPE_HZ
    out = []
    for i in range(0, len(samples) - stride + 1, stride):
        rms = sum(float(x) * float(x) for x in samples[i:i + stride]) / stride
        out.append(math.log1p(rms * 10000))
    return out


def fft(values, inverse=False):
    """Small dependency-free radix-2 FFT used for audio envelope correlation."""
    a = [complex(x) for x in values]
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    width = 2
    while width <= n:
        angle = (2 if inverse else -2) * math.pi / width
        step = complex(math.cos(angle), math.sin(angle))
        for start in range(0, n, width):
            omega = 1 + 0j
            half = width // 2
            for j in range(start, start + half):
                top = a[j]
                bottom = a[j + half] * omega
                a[j], a[j + half] = top + bottom, top - bottom
                omega *= step
        width *= 2
    if inverse:
        return [x / n for x in a]
    return a


def match_envelopes(a, b, min_overlap=MIN_MATCH_OVERLAP, hz=ENVELOPE_HZ,
                    expected_lag=None, lag_tolerance=None):
    """Return (Pearson score, lag seconds, overlap seconds); lag indexes a against b."""
    if len(a) < min_overlap * hz or len(b) < min_overlap * hz:
        return None
    n = 1 << (len(a) + len(b) - 2).bit_length()
    fa = fft(a + [0] * (n - len(a)))
    fb = fft(list(reversed(b)) + [0] * (n - len(b)))
    conv = fft([x * y for x, y in zip(fa, fb)], True)
    def sums(x):
        s, q = [0.0], [0.0]
        for v in x:
            s.append(s[-1] + v)
            q.append(q[-1] + v * v)
        return s, q
    sa, qa = sums(a)
    sb, qb = sums(b)
    best = None
    for ix in range(len(a) + len(b) - 1):
        lag = ix - len(b) + 1
        if expected_lag is not None and abs(lag / hz - expected_lag) > lag_tolerance:
            continue
        ai, az = max(0, lag), min(len(a), lag + len(b))
        bi, bz = ai - lag, az - lag
        count = az - ai
        if count < min_overlap * hz:
            continue
        suma, sumb = sa[az] - sa[ai], sb[bz] - sb[bi]
        va = qa[az] - qa[ai] - suma * suma / count
        vb = qb[bz] - qb[bi] - sumb * sumb / count
        if va <= .01 or vb <= .01:
            continue
        score = (conv[ix].real - suma * sumb / count) / math.sqrt(va * vb)
        if best is None or score > best[0]:
            best = (score, lag / hz, count / hz)
    return best


def audio_overlap_floor(duration):
    return min(20.0, max(3.0, duration * .7))


def dominant_offset(candidates):
    """A clock anchor requires matching sound from two independent clips."""
    best = None
    for candidate in candidates:
        nearby = [c for c in candidates if abs(c['offset'] - candidate['offset']) <= 1.5]
        unique = {c['source']['path']: c for c in nearby}
        if len(unique) < 2:
            continue
        if (len(unique) == 2 and len({c['reference']['path'] for c in unique.values()}) == 1
                and min(c['score'] for c in unique.values()) < .75):
            continue
        weight = sum(c['score'] * min(c['overlap'], 30) for c in unique.values())
        if best is None or weight > best[0]:
            best = (weight, nearby)
    if best is None:
        return None
    cluster = best[1]
    return {'offset': sorted(c['offset'] for c in cluster)[len(cluster) // 2],
            'source_time': sorted(c['source']['timestamp'] for c in cluster)[len(cluster) // 2],
            'matches': cluster}


def confirmed_single_anchor(candidates, ffmpeg, tries=6):
    """Clock offset for a camera without matches from two clips, e.g. one long take.

    A single loudness match is not proof: on 155 real clips, chance matches
    scored as high as true ones (up to 0.91). The 1 kHz waveform check told them
    apart completely (55 of 55 true matches confirmed, 0 of 90 chance matches),
    so one match only counts when the waveform confirms it.

    Not solved (test shoot 10 Nov 2026): a 7.7 s iPhone selfie clip with voice
    processing fails the waveform check, and its fine loudness curve matched
    other takes of the same lines almost as well (0.81 against 0.82). Such a clip
    keeps its clock and the report asks to check it; a guess would be worse.
    """
    ranked = sorted(candidates, key=lambda c: c['score'] * min(c['overlap'], 30), reverse=True)
    for candidate in ranked[:tries]:
        source, reference = candidate['source'], candidate['reference']
        position = reference['timestamp'] - candidate['lag']
        try:
            fine = precise_audio_position(source, reference, position, ffmpeg)
        except RECOVERABLE:
            continue
        if fine:
            return {'offset': fine[1] - source['timestamp'], 'source_time': source['timestamp'],
                    'matches': [candidate], 'confirmed_by': 'waveform'}
    return None

def pcm_window(path, ffmpeg, start, seconds, sample_rate=1000, filters=None):
    command = [ffmpeg, '-v', 'error', '-ss', str(max(0, start)), '-i', str(path),
               '-map', '0:a:0', '-vn'] + (['-af', filters] if filters else []) + [
               '-ac', '1', '-ar', str(sample_rate), '-t', str(seconds), '-f', 'f32le', '-']
    raw = cached_audio(command, path, 120)
    samples = array('f')
    samples.frombytes(raw[:len(raw) // 4 * 4])
    samples = array('f', (x if math.isfinite(x) else 0.0 for x in samples))
    return list(samples)


def precise_audio_position(source, reference, coarse_position, ffmpeg):
    """Refine an established energy match with signed waveforms at 1 kHz."""
    relative = coarse_position - reference['timestamp']
    candidates = []
    # Compare inside the part both recordings share, wherever that sits in the source.
    overlap_start = max(0.0, -relative)
    overlap_end = min(source['duration'], reference['duration'] - relative)
    if overlap_end - overlap_start < 3:
        return None
    windows = [overlap_start]
    if overlap_end - overlap_start > 45:
        windows.append(overlap_start + (overlap_end - overlap_start) / 2 - 10)
    for source_seek in windows:
        length = min(20.0, overlap_end - source_seek)
        predicted = relative + source_seek
        reference_seek = max(0.0, predicted - 2.0)
        if predicted + length <= 0 or reference_seek >= reference['duration']:
            continue
        a = pcm_window(source['path'], ffmpeg, source_seek, length)
        b = pcm_window(reference['path'], ffmpeg, reference_seek, length + 4)
        if not a or not b:
            continue
        match = match_envelopes(a, b, min(8.0, length * .65), hz=1000,
                                expected_lag=reference_seek - predicted,
                                lag_tolerance=1.0)
        if match and match[0] >= .20:
            position = reference['timestamp'] + reference_seek - match[1] - source_seek
            if abs(position - coarse_position) <= 1.0:
                candidates.append((match[0], position))
    return max(candidates) if candidates else None


SPECTRAL_RATE = 2000
SPECTRAL_WINDOW = 256
SPECTRAL_HOP = 50
SPECTRAL_BANDS = ((50, 130), (130, 220), (220, 350),
                  (350, 500), (500, 700), (700, 950))


def spectral_features(path, ffmpeg, start, seconds):
    """Short-time frequency bands survive differing camera microphones better than RMS."""
    samples = pcm_window(path, ffmpeg, start, seconds, SPECTRAL_RATE)
    taper = [.5 - .5 * math.cos(2 * math.pi * i / (SPECTRAL_WINDOW - 1))
             for i in range(SPECTRAL_WINDOW)]
    bands = [[] for _ in SPECTRAL_BANDS]
    for start_sample in range(0, len(samples) - SPECTRAL_WINDOW, SPECTRAL_HOP):
        spectrum = fft([samples[start_sample + i] * taper[i]
                        for i in range(SPECTRAL_WINDOW)])
        powers = [z.real * z.real + z.imag * z.imag
                  for z in spectrum[:SPECTRAL_WINDOW // 2 + 1]]
        for index, (low, high) in enumerate(SPECTRAL_BANDS):
            first = max(1, round(low * SPECTRAL_WINDOW / SPECTRAL_RATE))
            last = min(len(powers), round(high * SPECTRAL_WINDOW / SPECTRAL_RATE))
            bands[index].append(math.log1p(sum(powers[first:last]) / (last - first)))
    return bands


def spectral_match(source, reference, expected_frame, search_frames):
    """Find a unique peak across frequency bands, rejecting repeated sounds."""
    length = len(source[0])
    if length < 120 or any(len(x) != length for x in source):
        return None
    source_stats = [(sum(x), sum(v * v for v in x)) for x in source]
    ref_stats = []
    for band in reference:
        sums, squares = [0.0], [0.0]
        for value in band:
            sums.append(sums[-1] + value)
            squares.append(squares[-1] + value * value)
        ref_stats.append((sums, squares))
    candidates = []
    for offset in range(expected_frame - search_frames,
                        expected_frame + search_frames + 1):
        if offset < 0 or offset + length > len(reference[0]):
            continue
        score, used = 0.0, 0
        for index, band in enumerate(source):
            suma, qa = source_stats[index]
            sums, squares = ref_stats[index]
            sumb = sums[offset + length] - sums[offset]
            qb = squares[offset + length] - squares[offset]
            va = qa - suma * suma / length
            vb = qb - sumb * sumb / length
            if va <= 1e-6 or vb <= 1e-6:
                continue
            dot = sum(a * b for a, b in zip(band, reference[index][offset:offset + length]))
            score += (dot - suma * sumb / length) / math.sqrt(va * vb)
            used += 1
        if used:
            candidates.append((score / used, offset))
    if not candidates:
        return None
    best_score, best_frame = max(candidates)
    runner_up = max((score for score, frame in candidates
                     if abs(frame - best_frame) * SPECTRAL_HOP / SPECTRAL_RATE > .5),
                    default=-1.0)
    if best_score < .24 or best_score - runner_up < .08 or best_score < 1.5 * max(runner_up, .03):
        return None
    return best_score, best_frame, runner_up


def spectral_audio_position(source, reference, coarse_position, ffmpeg):
    """Resolve weak waveform cases to one video frame using shared sound spectrum."""
    relative = coarse_position - reference['timestamp']
    source_seek = max(0.0, -relative + 1.0)
    predicted = relative + source_seek
    # File clocks are already calibrated by several independent matches.
    # A larger search can lock onto a repeated noise several seconds away.
    margin = 1.5
    if predicted < 0 or predicted >= reference['duration'] - 3:
        return None
    length = min(25.0, source['duration'] - source_seek,
                 reference['duration'] - predicted - margin)
    if length < 4.0:
        return None
    reference_seek = max(0.0, predicted - margin)
    reference_length = min(reference['duration'] - reference_seek,
                           predicted - reference_seek + length + margin)
    a = spectral_features(source['path'], ffmpeg, source_seek, length)
    b = spectral_features(reference['path'], ffmpeg, reference_seek, reference_length)
    expected = round((predicted - reference_seek) * SPECTRAL_RATE / SPECTRAL_HOP)
    match = spectral_match(a, b, expected, round(margin * SPECTRAL_RATE / SPECTRAL_HOP))
    if not match:
        return None
    score, offset, runner = match
    position = reference['timestamp'] + reference_seek + offset * SPECTRAL_HOP / SPECTRAL_RATE - source_seek
    if abs(position - coarse_position) > margin:
        return None
    return score, position, runner


def choose_reference_camera(rows, warnings):
    """The sync reference: the preferred camera, else the dedicated camera with most audio.

    Long coverage gives the most reliable sync; which camera you hear is decided
    later by measuring sound quality (rank_audio).
    """
    totals = defaultdict(float)
    phones = set()
    for row in rows:
        if row['audio']:
            totals[row['camera']] += row['duration']
            if row['is_phone']:
                phones.add(row['camera'])
    if not totals:
        return None
    wanted = PREFERRED_AUDIO_CAMERA.strip().lower()
    if wanted:
        matches = [camera for camera in totals if wanted in camera.lower()]
        if matches:
            return max(matches, key=totals.get)
    dedicated = [camera for camera in totals if camera not in phones]
    return max(dedicated or list(totals), key=totals.get)


def sync_audio(rows, ffmpeg):
    """Place other cameras by matching their audio to the reference camera, not by file clocks.

    The reference camera keeps its own clock. Independent matches across the
    day's recordings establish one robust clock offset per other camera. Fine
    matches may move a clip slightly, but never reverse its camera's clip order.
    """
    warnings, evidence = [], []
    reference_camera = choose_reference_camera(rows, warnings)
    reference_rows = [r for r in rows if r['camera'] == reference_camera and r['audio']]
    other = [r for r in rows if r['camera'] != reference_camera]
    for r in rows:
        if r['duration'] > 1800 and r['audio']:
            warnings.append('Wide audio clock comparison limited to the first 30 minutes: ' + r['path'])
    for r in rows:
        r['reference_audio'] = r['camera'] == reference_camera
        r['clock_offset'] = 0.0
        r['sort_time'] = r['timestamp']
        r['sync_method'] = 'sound reference' if r['reference_audio'] and r['audio'] else 'metadata'
    if not reference_rows or not other:
        return evidence, warnings, reference_camera
    cache = {}
    coarse_cache = {}
    def sound(row):
        if row['path'] not in cache:
            try:
                cache[row['path']] = envelope(row['path'], ffmpeg)
            except RECOVERABLE as error:
                cache[row['path']] = []
                warnings.append('Audio sync skipped for %s: %s' % (row['path'], error))
        return cache[row['path']]
    def coarse(row):
        if row['path'] not in coarse_cache:
            samples = sound(row)
            coarse_cache[row['path']] = [(samples[i] + samples[i + 1]) / 2
                                         for i in range(0, len(samples) - 1, 2)]
        return coarse_cache[row['path']]
    candidates_by_day = defaultdict(list)
    candidates_by_app = defaultdict(list)
    for reference in reference_rows:
        for source in other:
            if (not source['audio'] or source['duration'] < 4
                    or source.get('timestamp_source', 'metadata') != 'metadata'
                    or reference.get('timestamp_source', 'metadata') != 'metadata'):
                continue
            if abs(source['timestamp'] - reference['timestamp']) > MAX_CLOCK_ERROR_SECONDS + reference['duration']:
                continue
            floor = audio_overlap_floor(source['duration'])
            if min(source['duration'], reference['duration']) < floor:
                continue
            match = match_envelopes(coarse(source), coarse(reference), floor, hz=5)
            if match is None or match[0] < .60:
                continue
            score, lag, overlap = match
            offset = reference['timestamp'] - source['timestamp'] - lag
            if abs(offset) <= MAX_CLOCK_ERROR_SECONDS:
                day = datetime.fromtimestamp(source['timestamp'], timezone.utc).date()
                candidate = {'source': source, 'reference': reference, 'offset': offset,
                             'score': score, 'lag': lag, 'overlap': overlap}
                candidates_by_day[(source['camera'], day)].append(candidate)
                candidates_by_app[(source['camera'], source.get('capture_app', ''), day)].append(candidate)
    anchors = {}
    app_anchors = {}
    for key, candidates in candidates_by_day.items():
        anchor = dominant_offset(candidates)
        if anchor:
            anchors[key] = anchor
            evidence.append({'camera': key[0], 'day': str(key[1]),
                             'offset_seconds': round(anchor['offset'], 2),
                             'matches': [(c['source']['name'], c['reference']['name'], round(c['score'], 3))
                                         for c in anchor['matches']]})
    for key, candidates in candidates_by_app.items():
        anchor = dominant_offset(candidates)
        if anchor:
            app_anchors[key] = anchor
            evidence.append({'camera': key[0], 'capture_app': key[1],
                             'day': str(key[2]), 'offset_seconds': round(anchor['offset'], 2),
                             'matches': [(c['source']['name'], c['reference']['name'], round(c['score'], 3))
                                         for c in anchor['matches']]})
    for key, candidates in candidates_by_day.items():
        if key in anchors:
            continue
        anchor = confirmed_single_anchor(candidates, ffmpeg)
        if anchor:
            anchors[key] = anchor
            match = anchor['matches'][0]
            evidence.append({'camera': key[0], 'day': str(key[1]), 'offset_seconds': round(anchor['offset'], 2),
                             'confirmed_by': anchor['confirmed_by'] + ', single match',
                             'matches': [(match['source']['name'], match['reference']['name'], round(match['score'], 3))]})
            warnings.append('Clock of %s set from one sound match (%s with %s), confirmed on the %s. '
                            'Check the sync by eye once.' % (key[0], match['source']['name'], match['reference']['name'],
                                                             anchor['confirmed_by']))
    for camera in {r['camera'] for r in other if r['audio']}:
        if not any(key[0] == camera for key in anchors):
            warnings.append('No reliable sound match between %s and %s; recording times used instead.'
                            % (reference_camera, camera))
    proposals = []
    for source in other:
        day = datetime.fromtimestamp(source['timestamp'], timezone.utc).date()
        app_key = (source['camera'], source.get('capture_app', ''), day)
        anchor = app_anchors.get(app_key) or anchors.get((source['camera'], day))
        if not anchor:
            warnings.append('No sound anchor for %s; recording time used for %s.' %
                            (source['camera'], source['name']))
            continue
        if app_key not in app_anchors and source.get('capture_app'):
            warnings.append('No separate sound anchor for %s; shared camera clock used.' %
                            source['capture_app'])
        source['clock_offset'] = anchor['offset']
        source['sort_time'] = source['timestamp'] + anchor['offset']
        source['sync_method'] = 'audio clock anchor'
        if not source['audio']:
            continue
        for ref in reference_rows:
            expected = ref['timestamp'] - source['sort_time']
            if expected > source['duration'] + 2 or expected < -ref['duration'] - 2:
                continue
            floor = audio_overlap_floor(source['duration'])
            match = match_envelopes(sound(source), sound(ref), floor,
                                    expected_lag=expected, lag_tolerance=2.0)
            if match and match[0] >= (.60 if source['duration'] < 30 else .50):
                score, lag, overlap = match
                proposals.append((score, overlap, source, ref,
                                  ref['timestamp'] - lag))
            # A raw waveform can still match when microphone gain or
            # compression prevents a reliable loudness-envelope match.
            proposals.append((0.0, 0.0, source, ref, source['sort_time']))
    # Start from the proven common offset. Accept the best clip-level positions
    # first, only when they fit between adjacent clips of that same camera.
    by_camera = defaultdict(list)
    for source in other:
        by_camera[source['camera']].append(source)
    for camera in by_camera:
        by_camera[camera].sort(key=lambda r: (r['timestamp'], r['name']))
    for score, overlap, source, ref, position in sorted(proposals, key=lambda x: x[:2], reverse=True):
        if source['sync_method'] in ('audio match', 'waveform match', 'spectral match'):
            continue
        try:
            fine = precise_audio_position(source, ref, position, ffmpeg)
            spectral = None if fine else spectral_audio_position(source, ref, position, ffmpeg)
        except RECOVERABLE as error:
            warnings.append('Fine audio match unavailable for %s: %s' % (source['path'], error))
            continue
        if fine:
            waveform_score, position = fine
        elif spectral:
            spectral_score, position, spectral_runner = spectral
            waveform_score = None
        elif score == 0:
            continue
        else:
            waveform_score = None
        sequence = by_camera[source['camera']]
        index = sequence.index(source)
        previous = sequence[index - 1] if index else None
        following = sequence[index + 1] if index + 1 < len(sequence) else None
        if previous and position < previous['sort_time'] + previous['duration'] - .04:
            continue
        if following and position + source['duration'] > following['sort_time'] + .04:
            continue
        source['sort_time'] = position
        source['clock_offset'] = position - source['timestamp']
        source['sync_method'] = ('spectral match' if spectral else
                                 ('audio match' if score else 'waveform match'))
        evidence.append({'source': source['name'], 'reference': ref['name'],
                         'offset_seconds': round(source['clock_offset'], 2),
                         'score': round(score, 3), 'overlap_seconds': round(overlap, 1),
                         'waveform_score': round(waveform_score, 3) if waveform_score is not None else None,
                         'spectral_score': round(spectral_score, 3) if spectral else None,
                         'spectral_runner_up': round(spectral_runner, 3) if spectral else None})
    for camera, sequence in by_camera.items():
        unmatched = sum(r['sync_method'] == 'audio clock anchor' for r in sequence)
        if unmatched:
            warnings.append('%d clip(s) from %s use the proven clock correction without a direct sound match.' %
                            (unmatched, camera))
    return evidence, warnings, reference_camera


def drop_duplicate_files(recorders, warnings):
    """The same recording copied twice would otherwise end up on two tracks."""
    seen, unique = set(), []
    for row in recorders:
        try:
            with open(row['path'], 'rb') as handle:
                mark = (os.path.getsize(row['path']), hashlib.sha256(handle.read(1 << 20)).hexdigest())
        except OSError:
            unique.append(row)
            continue
        if mark in seen:
            warnings.append('Same recording found twice; used once: ' + row['name'])
            continue
        seen.add(mark)
        unique.append(row)
    return unique


def place_recorders(recorders, rows, ffmpeg, warnings, excluded):
    """Find audio-only files on the shoot's clock, by sound alone.

    Recorders rarely store a usable recording time, so every file is searched
    from start to end. A loudness match is only a candidate; the 1 kHz waveform
    decides (see confirmed_single_anchor). Measured on 18 real recordings without
    any time stamp: all 6 camera clips found, chance matches rejected. Clock
    drift of the recorder was about 10 ms per hour, so one position per file holds.
    """
    def coarse(samples):
        return [(samples[i] + samples[i + 1]) / 2 for i in range(0, len(samples) - 1, 2)]
    clips = sorted((r for r in rows if r['audio'] and r['sync_method'] in CONFIRMED_SYNC),
                   key=lambda r: (r['reference_audio'], r['duration']), reverse=True)[:RECORDER_SEARCH_CLIPS]
    limit = RECORDER_MAX_HOURS * 3600
    sounds = {}
    matched = []
    for recorder in recorders:
        say('Searching', recorder['name'])
        if recorder['duration'] > limit:
            warnings.append('Only the first %d hours were searched: %s' % (RECORDER_MAX_HOURS, recorder['path']))
        target = {'path': recorder['path'], 'duration': recorder['duration'], 'timestamp': 0.0}
        position, tries = None, 0
        try:
            heard = coarse(envelope(recorder['path'], ffmpeg, limit))
            for clip in clips:
                if clip['path'] not in sounds:
                    sounds[clip['path']] = coarse(envelope(clip['path'], ffmpeg, limit))
                match = match_envelopes(sounds[clip['path']], heard,
                                        audio_overlap_floor(min(clip['duration'], recorder['duration'])), hz=5)
                if not match or match[0] < .60:
                    continue
                tries += 1
                fine = precise_audio_position(clip, target, -match[1], ffmpeg)
                if fine:
                    position = clip['sort_time'] - fine[1]
                    break
                if tries >= 12:
                    break
        except RECOVERABLE as error:
            excluded.append({'file': recorder['path'], 'reason': 'Audio file could not be read: ' + str(error)})
            continue
        if position is None:
            excluded.append({'file': recorder['path'], 'reason': 'No matching sound found in the video clips; not placed.'})
            continue
        recorder.update(sort_time=position, timestamp=position, sync_method='recorder match', reference_audio=False,
                        clock_offset=0.0)
        matched.append(recorder)
    # Two recordings at once are usually two speakers, so neither is muted.
    for i, a in enumerate(matched):
        for b in matched[i + 1:]:
            if min(a['sort_time'] + a['duration'], b['sort_time'] + b['duration']) - max(a['sort_time'], b['sort_time']) > 1:
                warnings.append('Two audio recordings run at the same time and both stay audible: %s and %s. '
                                'Mute one if they are the same voice.' % (a['name'], b['name']))
    return matched


def import_recorders(pool, recorders, imported, excluded, ffmpeg, warnings):
    kept = []
    for row in recorders:
        try:
            clips = [c for c in pool.ImportMedia([row['path']]) or [] if c]
        except RuntimeError:
            clips = []
        if not clips or clips[0].GetClipProperty().get('Online Status') == 'Offline':
            excluded.append({'file': row['path'], 'reason': 'Resolve could not import this audio file.'})
            continue
        imported[row['key']] = clips[0]
        row['fps'] = number(clips[0].GetClipProperty().get('FPS')) or None
        try:
            stereo_mapping(clips[0], row['path'], ffmpeg)
        except RECOVERABLE as error:
            warnings.append('Check the channels of %s: %s' % (row['path'], error))
        kept.append(row)
    return kept


def place_recorder_audio(pool, timeline, imported, recorders, spans, fps, warnings):
    """Put each recorder under the picture: only the parts that have picture above them.

    spans: (real start, real end, timeline frame of the real start).
    Returns (row, item, None, source seconds) entries.
    """
    entries = []
    for row in recorders:
        rate = row.get('fps') or fps
        for start, end, frame in spans:
            first, last = max(start, row['sort_time']), min(end, row['sort_time'] + row['duration'])
            if last - first < .5:
                continue
            record = frame + round((first - start) * fps)
            length = frame + round((last - start) * fps) - record
            source = first - row['sort_time']
            begin = round(source * rate)
            item = append_audio(pool, timeline, imported[row['key']], row['audio_track_index'], record,
                                begin, begin + round(length / fps * rate), {e[1].GetUniqueId() for e in entries})
            if item is None:
                warnings.append('Audio recorder file missing on the timeline: ' + row['path'])
                continue
            entries.append((row, item, None, source))
    return entries


def overlap_windows(source_rows, reference_rows):
    """Moments both cameras recorded, cut into a few evenly spread stretches."""
    pieces = []
    for a in source_rows:
        for b in reference_rows:
            first = max(a['sort_time'], b['sort_time']) + .5
            last = min(a['sort_time'] + a['duration'], b['sort_time'] + b['duration']) - .5
            while last - first >= 4:
                length = min(QUALITY_WINDOW_SECONDS, last - first)
                pieces.append((first, length, a, b))
                first += length
    pieces.sort(key=lambda piece: piece[0])
    if len(pieces) > QUALITY_WINDOWS:
        step = len(pieces) / QUALITY_WINDOWS
        pieces = [pieces[int(i * step)] for i in range(QUALITY_WINDOWS)]
    return pieces


def sound_metrics(path, ffmpeg, start, seconds):
    """Voice-to-background contrast, top end and clipping of one stretch of sound."""
    full = pcm_window(path, ffmpeg, start, seconds, QUALITY_RATE)
    high = pcm_window(path, ffmpeg, start, seconds, QUALITY_RATE, 'highpass=f=4000,highpass=f=4000')
    block = QUALITY_RATE // 20  # 50 ms
    levels = []
    for i in range(0, min(len(full), len(high)) - block + 1, block):
        levels.append((sum(x * x for x in full[i:i + block]) / block,
                       sum(x * x for x in high[i:i + block]) / block))
    if len(levels) < 40:
        return None
    def db(value):
        return 10 * math.log10(max(value, 1e-12))
    ordered = sorted(energy for energy, _ in levels)
    # Loud moments are the voice; quiet moments are what the microphone hears
    # between words: room noise, echo tail, hiss.
    contrast = db(ordered[int(len(ordered) * .95)]) - db(ordered[int(len(ordered) * .10)])
    threshold = ordered[int(len(ordered) * .80)]
    loud = [(energy, top) for energy, top in levels if energy >= threshold]
    top_end = db(sum(top for _, top in loud)) - db(sum(energy for energy, _ in loud))
    clipped = sum(abs(x) >= .98 for x in full) / len(full)
    return {'contrast_db': contrast, 'top_end_db': top_end, 'clipped': clipped}


def quality_score(metrics):
    """Contrast counts most; a muffled sound loses a little; audible clipping a lot."""
    return (min(metrics['contrast_db'], CONTRAST_CAP_DB) + .3 * metrics['top_end_db']
            - 10000 * max(0.0, metrics['clipped'] - 1e-4))


def average_metrics(measured):
    return {key: sum(m[key] for m in measured) / len(measured) for key in measured[0]}


def describe_metrics(metrics):
    return 'voice vs background %.1f dB, top end %.1f dB, clipping %.2f%%' % (
        metrics['contrast_db'], metrics['top_end_db'], metrics['clipped'] * 100)


def rank_audio(rows, ffmpeg, reference_camera, warnings):
    """Decide which camera you hear, by measuring sound where cameras recorded together.

    Every camera is compared with the sync reference on the same stretches of
    time, so the same voice in the same room is measured. A camera only takes
    over when it scores clearly better (QUALITY_MARGIN_DB). Sets row['audio_rank']
    (0 = audible first) and returns report lines plus raw measurements.
    """
    cameras = defaultdict(list)
    for row in rows:
        if row['audio']:
            cameras[row['camera']].append(row)
    phones = {row['camera'] for row in rows if row['is_phone']}
    total = {camera: sum(r['duration'] for r in clips) for camera, clips in cameras.items()}
    def default_key(camera):
        return (camera != reference_camera, camera in phones, -total[camera], camera)
    difference, details = {}, {}
    reference_measured = []
    references = [r for r in cameras.get(reference_camera, []) if r['sync_method'] in CONFIRMED_SYNC]
    for camera, clips in cameras.items():
        if camera == reference_camera:
            continue
        synced = [r for r in clips if r['sync_method'] in CONFIRMED_SYNC]
        mine, theirs = [], []
        try:
            for start, length, own, ref in overlap_windows(synced, references):
                a = sound_metrics(own['path'], ffmpeg, start - own['sort_time'], length)
                b = sound_metrics(ref['path'], ffmpeg, start - ref['sort_time'], length)
                if a and b:
                    mine.append(a)
                    theirs.append(b)
        except RECOVERABLE as error:
            warnings.append('Sound quality not measured for %s: %s' % (camera, error))
            continue
        if not mine:
            continue
        reference_measured.extend(theirs)
        own_average, their_average = average_metrics(mine), average_metrics(theirs)
        difference[camera] = quality_score(own_average) - quality_score(their_average)
        details[camera] = {'metrics': own_average, 'compared_stretches': len(mine),
                           'difference_vs_reference_db': round(difference[camera], 1)}
    if reference_measured:
        difference[reference_camera] = 0.0
        details[reference_camera] = {'metrics': average_metrics(reference_measured),
                                     'compared_stretches': len(reference_measured),
                                     'difference_vs_reference_db': 0.0}
    recorders = {row['camera'] for row in rows if row.get('recorder')}
    for camera in sorted(recorders - set(details)):
        # Placed through another camera, or too little overlap to compare: still check the file itself.
        clip = max(cameras.get(camera, []), key=lambda r: r['duration'], default=None)
        try:
            own = clip and sound_metrics(clip['path'], ffmpeg, max(0.0, clip['duration'] / 2 - 7.5),
                                         min(15.0, clip['duration']))
        except RECOVERABLE:
            own = None
        if own:
            details[camera] = {'metrics': own, 'compared_stretches': 0, 'difference_vs_reference_db': None}
    def broken(camera):
        metrics = details.get(camera, {}).get('metrics')
        if not metrics:
            return None
        if metrics['clipped'] > RECORDER_MAX_CLIPPED:
            return 'audible clipping'
        if metrics['contrast_db'] < RECORDER_MIN_CONTRAST_DB:
            return 'hardly any voice against the background'
        return None
    wanted = PREFERRED_AUDIO_CAMERA.strip().lower()
    if wanted and not any(wanted in c.lower() for c in cameras):
        warnings.append('PREFERRED_AUDIO_CAMERA "%s" matches no camera with sound; chose one automatically.'
                        % PREFERRED_AUDIO_CAMERA)
        wanted = ''
    chosen = [c for c in sorted(recorders) if wanted and wanted in c.lower()]
    # A broken recorder never becomes main audio by itself: it goes to the back.
    bad = set() if chosen else {c for c in recorders if broken(c)}
    for camera in sorted(bad):
        warnings.append('Audio recorder %s not used as main audio: %s. Listen to it, or set '
                        'PREFERRED_AUDIO_CAMERA to use it anyway.' % (camera, broken(camera)))
    scored = {c: d for c, d in difference.items() if c not in bad}
    best = max(scored, key=scored.get) if scored else None
    measured = sorted(scored, key=lambda c: (-scored[c], default_key(c)))
    unmeasured = sorted((c for c in cameras if c not in scored and c not in bad), key=default_key)
    if wanted and reference_camera and wanted in reference_camera.lower():
        order = [reference_camera] + [c for c in measured + unmeasured if c != reference_camera]
        reason = 'chosen with PREFERRED_AUDIO_CAMERA'
    elif best and best != reference_camera and scored[best] >= QUALITY_MARGIN_DB:
        order = measured + unmeasured
        reason = 'measured clearly cleaner than %s (%+.1f dB)' % (reference_camera, scored[best])
    else:
        order = ([reference_camera] if reference_camera in cameras and reference_camera not in bad else []) + [
            c for c in measured + unmeasured if c != reference_camera]
        reason = ('no other camera sounded clearly better (margin %g dB)' % QUALITY_MARGIN_DB
                  if difference else 'default: no overlapping sound to compare')
    kept = chosen or ([] if wanted else [c for c in order if c in recorders])
    if kept:
        order = kept + [c for c in order if c not in kept]
        reason = ('chosen with PREFERRED_AUDIO_CAMERA' if chosen
                  else 'a separate audio recorder always goes first')
    order += sorted(bad)
    # Recorders that go first share rank 0: two lavaliers are usually two speakers, both stay audible.
    rank = {camera: (0 if camera in kept else index) for index, camera in enumerate(order)}
    for row in rows:
        row['audio_rank'] = rank.get(row['camera'], len(order))
    lines = []
    if order:
        lines.append('Heard first: %s (%s).' % (' and '.join(kept) if len(kept) > 1 else order[0], reason))
    for camera in order:
        if camera in details:
            d = details[camera]
            lines.append('%s: %s%s' % (camera, describe_metrics(d['metrics']),
                         '' if camera == reference_camera or d['difference_vs_reference_db'] is None
                         else '; score %+.1f dB vs %s' % (d['difference_vs_reference_db'], reference_camera)))
        else:
            lines.append('%s: not measured (no confirmed overlap with %s).' % (camera, reference_camera))
    if order:
        lines.append('The check measures noise, echo, distortion and muffled sound, not taste. '
                     'Set PREFERRED_AUDIO_CAMERA to overrule it.')
    return lines, details


def stereo_mapping(clip, path, ffmpeg):
    """Single-microphone camera audio: map mono to both speakers; preserve genuine stereo."""
    mapping = json.loads(clip.GetAudioMapping())
    channels = int(mapping.get('embedded_audio_channels') or 0)
    need(channels >= 1, 'No embedded audio channels available: ' + str(path))
    if channels == 1:
        selected = [1, 1]
    else:
        command = [ffmpeg, '-v', 'error', '-i', str(path), '-map', '0:a:0', '-vn', '-af', 'pan=stereo|c0=c0|c1=c1', '-ac', '2',
                   '-ar', '200', '-t', '900', '-f', 'f32le', '-']
        raw = cached_audio(command, path, 360)
        samples = array('f')
        samples.frombytes(raw[:len(raw) // 4 * 4])
        samples = array('f', (x if math.isfinite(x) else 0.0 for x in samples))
        energies = [0.0, 0.0]
        for i in range(0, len(samples) - 1, 2):
            energies[0] += samples[i] * samples[i]
            energies[1] += samples[i + 1] * samples[i + 1]
        if min(energies) < max(energies) * .01:
            channel = 1 if energies[0] >= energies[1] else 2
            selected = [channel, channel]
        else:
            selected = [1, 2]
    payload = {'track_mapping': {'1': {'channel_idx': selected,
                                       'mute': False, 'type': 'stereo'}}}
    need(clip.SetAudioMapping(json.dumps(payload)), 'Could not map camera audio to stereo: ' + str(path))
    actual = json.loads(clip.GetAudioMapping())['track_mapping']['1']
    need(actual['type'].lower() == 'stereo' and actual['channel_idx'] == selected,
         'Could not verify the stereo audio mapping: ' + str(path))
    return selected[0] == selected[1]


def primary_stereo_mapping(clip, path):
    """Keep the camera's primary stereo audio; omit extra spatial stems.

    Some phone recordings expose AAC stereo plus four spatial-audio tracks.
    Appending all five mappings spills them onto adjacent camera tracks and
    can make Resolve return None for one of the appended audio items.
    """
    mapping = json.loads(clip.GetAudioMapping())
    tracks = mapping.get('track_mapping') or {}
    if not tracks:
        raise RuntimeError('No audio mapping available: ' + str(path))
    if len(tracks) == 1 and str(next(iter(tracks.values())).get('type', '')).lower() == 'stereo':
        return False
    primary = tracks.get('1') or tracks[min(tracks, key=int)]
    channels = primary.get('channel_idx') or []
    need(channels, 'No primary audio channel for ' + str(path))
    selected = channels[:2] if len(channels) >= 2 else [channels[0], channels[0]]
    payload = {'track_mapping': {'1': {'channel_idx': selected, 'mute': False,
                                       'type': 'stereo'}}}
    need(clip.SetAudioMapping(json.dumps(payload)),
         'Could not set the primary source audio: ' + str(path))
    actual = json.loads(clip.GetAudioMapping()).get('track_mapping') or {}
    need(list(actual) == ['1'] and actual['1']['channel_idx'] == selected
         and actual['1']['type'].lower() == 'stereo',
         'Could not verify the primary source audio: ' + str(path))
    return True


def timeline_source_item(timeline, media_type, track_index, record_frame, key):
    """Read back the real item: Resolve can return None for a successful append."""
    for item in timeline.GetItemListInTrack(media_type, track_index) or []:
        if item is None or abs(item.GetStart() - record_frame) > 1:
            continue
        media = item.GetMediaPoolItem()
        if media and path_key(media.GetClipProperty('File Path')) == key:
            return item
    return None


def link_source_audio(timeline, pairs):
    for video_item, audio_item, path in pairs:
        need(abs(video_item.GetStart() - audio_item.GetStart()) <= 1,
             'Picture and its audio were not placed on the same frame: ' + path)
        linked_ids = {item.GetUniqueId() for item in video_item.GetLinkedItems() or [] if item}
        if audio_item.GetUniqueId() not in linked_ids:
            need(timeline.SetClipsLinked([video_item, audio_item], True),
                 'Could not link audio to picture: ' + path)
            linked_ids = {item.GetUniqueId() for item in video_item.GetLinkedItems() or [] if item}
            need(audio_item.GetUniqueId() in linked_ids,
                 'Could not verify the link between audio and picture: ' + path)


def source_from_resolve(resolve):
    directory = resolve.Fusion().RequestDir('Choose the footage folder for the %s timeline' % WORKFLOW)
    if not directory:
        return None, {}, []
    directory = Path(directory)
    need(directory.is_dir(), 'The chosen folder does not exist: ' + str(directory))
    paths = select_media_paths(directory)
    say('Footage folder: ' + str(directory.resolve()) + ' (' + str(len(paths)) + ' video files)')
    project = need(resolve.GetProjectManager().GetCurrentProject(), 'Open a project first.')
    return project, {}, paths


class MediaPaths(list):
    def __init__(self, values, warnings=(), ignored=0):
        super().__init__(values)
        self.warnings = list(warnings)
        self.ignored = ignored


def select_media_paths(directory):
    """Scan recursively without following folder links or guessing by filenames."""
    directory = Path(directory)
    warnings, paths, seen = [], [], set()
    ignored = 0
    def scan_error(error):
        warnings.append('Folder not readable: ' + str(error))
    for parent, folders, filenames in os.walk(directory, followlinks=False, onerror=scan_error):
        folders[:] = sorted(f for f in folders if not f.startswith('.') and f not in ('__MACOSX',))
        for name in sorted(filenames):
            path = Path(parent) / name
            if name.startswith('.') or path.suffix.lower() not in VIDEO_SUFFIXES | AUDIO_SUFFIXES:
                ignored += 1
                continue
            try:
                real = path.resolve(strict=True)
                if not real.is_file() or path_key(real) in seen:
                    continue
                seen.add(path_key(real))
                paths.append(path)
            except OSError as error:
                warnings.append('File not accessible: %s (%s)' % (path, error))
    paths.sort()
    proxy_names = {'proxy', 'proxies', 'proxy media', 'optimized media'}
    def owner(path):
        for ancestor in path.parents:
            if ancestor == directory.parent:
                break
            if ancestor.name.casefold() in proxy_names:
                return ancestor.parent
        return None
    originals = {(p.parent, p.name.casefold()) for p in paths if owner(p) is None}
    selected, proxy_only = [], defaultdict(list)
    for path in paths:
        proxy_owner = owner(path)
        if proxy_owner is None:
            selected.append(path)
        elif (proxy_owner, path.name.casefold()) not in originals:
            try:
                duplicate = any(filecmp.cmp(path, previous, shallow=False)
                                for previous in proxy_only[path.name.casefold()])
            except OSError:
                duplicate = False
            if not duplicate:
                proxy_only[path.name.casefold()].append(path)
                selected.append(path)
    say('Proxy copies skipped:', len(paths) - len(selected), '; non-video/helper files ignored:', ignored)
    return MediaPaths(selected, warnings, ignored)


def configured_profile(camera):
    """Longest matching CAMERA_PROFILES key wins, so 'Canon EOS R6' beats 'Canon'."""
    matches = [key for key in CAMERA_PROFILES if key and key.lower() in camera.lower()]
    return CAMERA_PROFILES[max(matches, key=len)] if matches else None


def choose_profile(row, detected):
    """Return (input colour space, evidence); strongest evidence first."""
    configured = configured_profile(row['camera'])
    if configured:
        return configured, 'CAMERA_PROFILES setting'
    if row['profile']:
        return row['profile'], 'camera metadata'
    detected = clean(detected)
    # Resolve reads camera metadata for many log formats (Apple Log, BRAW, Canon, ...).
    # 'Project' and Rec.709 are its defaults, not evidence about the camera.
    if detected and detected.lower() != 'project' and not detected.lower().startswith('rec.709'):
        return detected, 'detected by Resolve'
    if row['tagged_709']:
        return 'Rec.709 Gamma 2.4', 'Rec.709 tag in the file'
    return None, None


def assign_profiles(rows, imported, warnings):
    """Decide and apply each clip's input colour space; report it per camera."""
    for row in rows:
        detected = imported[row['key']].GetClipProperty('Input Color Space')
        row['colour'], row['colour_source'] = choose_profile(row, detected)
    # A clip without evidence takes its camera's profile from same-day recordings
    # in the same folder, but only when those all agree.
    for row in rows:
        if row['colour']:
            continue
        siblings = [o for o in same_folder_and_day(row, rows)
                    if o['camera'] == row['camera'] and o['colour_source'] in
                    ('CAMERA_PROFILES setting', 'camera metadata', 'detected by Resolve')]
        profiles = {o['colour'] for o in siblings}
        if len(profiles) == 1:
            row['colour'] = profiles.pop()
            row['colour_source'] = 'same camera, same folder and day'
            warnings.append('Colour profile for %s taken from recordings of the same camera; metadata missing.' % row['name'])
    unknown = defaultdict(int)
    for row in rows:
        if not row['colour']:
            unknown[row['camera']] += 1
            continue
        clip = imported[row['key']]
        try:
            applied = clip.SetClipProperty('Input Color Space', row['colour'])
            actual = clip.GetClipProperty('Input Color Space')
            if not applied or actual != row['colour']:
                warnings.append('Check the colour profile of %s: asked for "%s", Resolve reports "%s". '
                                'Is the name spelled exactly as in Resolve?' % (row['path'], row['colour'], actual))
        except RuntimeError as error:
            warnings.append('Colour profile not set for %s: %s' % (row['path'], error))
    for camera, count in sorted(unknown.items()):
        warnings.append('Colour profile unknown for %d clip(s) from %s; treated as Rec.709. If this camera '
                        'recorded log or HDR, add it to CAMERA_PROFILES at the top of the script.' % (count, camera))


def camera_summary(rows):
    summary = {}
    for row in rows:
        entry = summary.setdefault(row['camera'], {'camera': row['camera'], 'clips': 0,
                                                   'reference_audio': row['reference_audio'], 'colours': set()})
        entry['clips'] += 1
        if row.get('recorder'):
            entry['colours'].add('none, sound only')
            continue
        entry['colours'].add('%s (%s)' % (row['colour'], row['colour_source']) if row['colour']
                             else 'unknown, treated as Rec.709')
    return [{'camera': e['camera'], 'clips': e['clips'], 'reference_audio': e['reference_audio'],
             'colour': '; '.join(sorted(e['colours']))} for e in summary.values()]


# --- Multicam -----------------------------------------------------------------
# The script's own sync decides where every clip belongs. Each clip gets that
# moment as its start timecode in Resolve (the file itself is never changed) and
# a camera number; Resolve then builds the multicam on timecode, one angle per
# camera. Resolve's multicam audio modes either fall silent where the first angle
# did not record, or play every camera at once (tested 18 Oct 2026), so the
# timeline uses the multicam for picture only and places the cameras' own sound
# underneath, exactly like the YouTube timeline: best camera audible, the next
# one taking over in its gaps.

MAX_SHOOT_HOURS = 20  # timecode starts at 01:00:00:00 and must stay below 24 hours


def shoot_sessions(rows):
    """Group recordings into shoots: a long pause or a different day starts a new one."""
    sessions = []
    for row in sorted(rows, key=lambda r: (r['sort_time'], r['path'])):
        end = row['sort_time'] + row['duration']
        if (sessions and row['sort_time'] <= sessions[-1]['end'] + SHOOT_GAP_HOURS * 3600
                and end - sessions[-1]['start'] <= MAX_SHOOT_HOURS * 3600):
            sessions[-1]['rows'].append(row)
            sessions[-1]['end'] = max(sessions[-1]['end'], end)
        else:
            sessions.append({'start': row['sort_time'], 'end': end, 'rows': [row]})
    return sessions


def picture_stretches(rows, gap=.5):
    """Runs of time with at least one camera recording; shorter gaps than `gap` seconds stay."""
    stretches = []
    for row in sorted(rows, key=lambda r: r['sort_time']):
        end = row['sort_time'] + row['duration']
        if stretches and row['sort_time'] <= stretches[-1]['end'] + gap:
            stretches[-1]['rows'].append(row)
            stretches[-1]['end'] = max(stretches[-1]['end'], end)
        else:
            stretches.append({'start': row['sort_time'], 'end': end, 'rows': [row]})
    return stretches


def source_end(in_frame, frames, fps, rate, available=None):
    """Last source frame for a piece of `frames` timeline frames. Resolve rounds a clip with
    another frame rate down, so rounding here too would leave a black frame after the piece."""
    needed = frames / fps * rate
    # A clip slower than the timeline moves in whole source frames: stay short, a piece can't overlap the next.
    end = in_frame + (math.ceil(needed - 1e-6) if rate >= fps else max(1, math.floor(needed + 1e-6)))
    return min(end, available) if available else end


def picture_plan(stretch, angle, minimum):
    """What goes on V1: (start, end, None for the multicam, or the clip that has picture).

    The multicam shows angle 1, so it is used wherever angle 1 recorded. Elsewhere
    the best camera with picture fills in. Parts shorter than `minimum` seconds join
    the part before them, if that part can run on: a clip can't pass its own end.
    """
    rows = sorted(stretch['rows'], key=lambda r: (angle[r['camera']], r['sort_time']))
    main = [(r['sort_time'], r['sort_time'] + r['duration']) for r in rows if angle[r['camera']] == 1]
    moments = sorted({stretch['start'], stretch['end']}
                     | {t for r in rows for t in (r['sort_time'], r['sort_time'] + r['duration'])
                        if stretch['start'] < t < stretch['end']})
    plan = []
    for start, end in zip(moments, moments[1:]):
        middle = (start + end) / 2
        if any(a <= middle < b for a, b in main):
            source = None
        else:
            # A gap of under half a second has no camera at all: the multicam covers it.
            source = next((r for r in rows if r['sort_time'] <= middle < r['sort_time'] + r['duration']), None)
        last = plan[-1][2] if plan else False
        room = last is None or (last and last['sort_time'] + last['duration'] >= end)
        if plan and (last is source or (end - start < minimum and room)):
            plan[-1][1] = end
        else:
            plan.append([start, end, source])
    return [tuple(part) for part in plan]


def timecode_string(frames, rate, drop_frame=False):
    """Frame count to timecode at a clip's own rate; 29.97/59.94 drop-frame when the clip uses it."""
    nominal = int(round(rate))
    if drop_frame and nominal in (30, 60):
        drop = 2 if nominal == 30 else 4
        per_minute = nominal * 60 - drop
        per_ten = per_minute * 10 + drop
        tens, rest = divmod(frames, per_ten)
        frames += drop * 9 * tens + (drop * ((rest - drop) // per_minute) if rest > drop else 0)
    ff = frames % nominal
    seconds = frames // nominal
    return '%02d:%02d:%02d%s%02d' % (seconds // 3600, seconds // 60 % 60, seconds % 60,
                                     ';' if drop_frame and nominal in (30, 60) else ':', ff)


def multicam_timecode(elapsed, clip_rate, drop_frame=False):
    """Start timecode for a clip that starts `elapsed` real seconds into a shoot.

    Resolve turns a clip's start timecode into time as frame count / real frame
    rate, also for 23.976/29.97/59.94 non-drop clips (measured 18 Oct 2026: a
    29.97 non-drop clip labelled by the clock landed 0.1% late, 4.6 s at 76
    minutes). So every clip gets the frame number of its real start time, at its
    own real rate, counted from a shared origin of one hour; drop-frame or
    non-drop only changes how that frame number is written.
    """
    nominal = int(round(clip_rate))
    rate = nominal * 1000 / 1001 if abs(clip_rate - nominal * 1000 / 1001) < .01 else clip_rate
    return timecode_string(round((3600 + elapsed) * rate), clip_rate, drop_frame and nominal in (30, 60))


def same_timecode(a, b):
    return str(a).replace(';', ':') == str(b).replace(';', ':')


def set_multicam_identity(clip, row, timeline_fps, first, number_, camera):
    """Give one clip its synced start timecode and camera number; read both back."""
    drop = str(clip.GetClipProperty().get('Drop frame', '0')) == '1'
    code = multicam_timecode(row['sort_time'] - first, row.get('fps') or timeline_fps, drop)
    metadata = {'Camera #': str(number_), 'Angle': angle_name(number_, camera)}
    if not (clip.SetClipProperty('Start TC', code) and clip.SetMetadata(metadata)):
        return False
    stored = clip.GetMetadata() or {}
    return (same_timecode(clip.GetClipProperty().get('Start TC'), code)
            and all(stored.get(key) == value for key, value in metadata.items()))


def angle_name(number, camera):
    # Resolve orders angles by name: the number keeps the best-sounding camera first.
    return '%d · %s' % (number, camera)


def colour_groups_per_camera(project, timeline, camera_of_clip, warnings, colours=None):
    """One colour group per camera, and every clip that sits on V1 directly joins its camera's group.

    Those clips are not part of the multicam, so a grade on that camera inside the multicam
    never reaches them (measured in Resolve Studio 21.2, 8 Nov 2026); a group grade does.
    The clips inside the multicam can't be reached through the API: the user adds them to
    the same group after Open in Timeline. Each group's name carries its camera's clip colour
    (colour_group_name), in the order of `colours`. Returns {camera: group}.
    """
    groups = {}
    present = set(camera_of_clip.values())
    for camera in [c for c in (colours or {}) if c in present] + sorted(present - set(colours or {})):
        group = project.AddColorGroup(colour_group_name(camera, colours or {}))
        if group:
            groups[camera] = group
        else:
            warnings.append('Could not make a colour group for camera %s.' % camera)
    missed = 0
    for item in timeline.GetItemListInTrack('video', 1) or []:
        clip = item.GetMediaPoolItem() if item else None
        camera = camera_of_clip.get(clip.GetUniqueId()) if clip else None
        if camera and not (camera in groups and item.AssignToColorGroup(groups[camera])):
            missed += 1
    if missed:
        warnings.append('%d clip(s) on V1 could not join their camera\'s colour group; grade them by hand.' % missed)
    return groups


# Resolve's own clip colours, the most distinct first; Blue is left out because it looks like an uncoloured clip.
CAMERA_COLOURS = ['Orange', 'Teal', 'Yellow', 'Violet', 'Lime', 'Pink', 'Brown', 'Navy',
                  'Apricot', 'Olive', 'Green', 'Purple', 'Tan', 'Beige', 'Chocolate']


def camera_order(rows):
    """Cameras in multicam angle order: best sound first (as build_multicam numbers the angles), then by name."""
    return sorted({r['camera'] for r in rows},
                  key=lambda c: (min(r.get('audio_rank', 99) for r in rows if r['camera'] == c), c))


def colour_group_name(camera, colours):
    """'Sony ILCE-7M4 (Orange)': the clip colour in the group's name links the Clip Color filter to its group."""
    return '%s (%s)' % (camera, colours[camera]) if camera in colours else camera


def clip_colour_per_camera(clip_cameras, warnings, order=None):
    """Give every source clip its camera's clip colour, so you can see which clip came from which camera.

    The colour sits on the media pool clip, so it shows on the clips inside the multicam (Open in Timeline)
    and on the clips that sit on V1 directly, on the Edit and the Color page; there the Clips filter
    (Clip Color) shows one camera at a time (measured in Resolve Studio 21.2, 8 Nov 2026). The multicam
    item itself keeps no colour: it holds every camera. Colours follow `order` (angle order: angle 1 is
    Orange), with any camera not in it after, by name. Returns {camera: colour} in that order.
    """
    present = {camera for _, camera in clip_cameras}
    cameras = [c for c in (order or []) if c in present] + sorted(present - set(order or []))
    colours = {camera: CAMERA_COLOURS[i % len(CAMERA_COLOURS)] for i, camera in enumerate(cameras)}
    if len(cameras) > len(CAMERA_COLOURS):
        warnings.append('%d cameras but only %d clip colours: some cameras share a colour, so check the camera '
                        'before you add filtered clips to a group.' % (len(cameras), len(CAMERA_COLOURS)))
    applied, missed = set(), 0
    for clip, camera in clip_cameras:
        if clip.SetClipColor(colours[camera]):
            applied.add(camera)
        else:
            missed += 1
    if missed:
        warnings.append('%d clip(s) did not get their camera\'s clip colour.' % missed)
    # Only list a camera's colour when at least one of its clips really has it.
    return {camera: colour for camera, colour in colours.items() if camera in applied}


def build_multicam(resolve, project, pm, pool, imported, rows, recorders, fps, report, warnings, excluded):
    sessions = shoot_sessions(rows)
    if len(sessions) > 1:
        warnings.append('%d separate shoots found (more than %g hours apart, or longer than %d hours); '
                        'each gets its own multicam clip.' % (len(sessions), SHOOT_GAP_HOURS, MAX_SHOOT_HOURS))
    title = WORKFLOW + ' timeline ' + datetime.now().strftime('%Y-%m-%d %H%M%S')
    timeline = need(pool.CreateEmptyTimeline(title), 'Could not create the timeline.')
    report['timeline'] = title
    need(project.SetCurrentTimeline(timeline), 'Could not open the timeline.')
    need(timeline.SetSettings({'useCustomSettings': '1', 'timelineResolutionWidth': WIDTH,
                              'timelineResolutionHeight': HEIGHT, 'videoMonitorFormat': monitor_format(fps)}),
         'Could not apply custom timeline settings.')
    need(timeline.SetSettings(managed_color_settings()), 'Could not apply timeline colour management.')
    settings = timeline.GetSettings()
    need(settings.get('useCustomSettings') == '1', '"Use project settings" is still on.')
    need(settings.get('timelineResolutionWidth') == WIDTH and settings.get('timelineResolutionHeight') == HEIGHT,
         'The timeline has the wrong picture size.')
    need(abs(number(settings.get('timelineFrameRate')) - fps) < .02, 'The timeline has the wrong frame rate.')
    need(settings.get('videoMonitorFormat') == monitor_format(fps), 'The timeline monitor has the wrong frame rate.')
    need(all(settings.get(key) == value for key, value in managed_color_settings().items()),
         'Project and timeline use different colour management.')
    need(timeline.SetTrackName('video', 1, 'Multicam'), 'Could not name the video track.')
    labels = allocate_tracks(rows + recorders, fps)  # MAIN_CAMERA doesn't apply to multicam
    audio_labels = {row['audio_track_index']: row['lane_label'] for row in rows + recorders}
    for label in labels.values():
        if 'overlap' in label:
            warnings.append('Clips of one camera overlap in time and share one multicam angle; '
                            'check them by hand: ' + label)
    for index, label in sorted(audio_labels.items()):
        while timeline.GetTrackCount('audio') < index:
            need(timeline.AddTrack('audio', 'stereo'), 'Could not add an audio track.')
        need(timeline.SetTrackName('audio', index, label + ' audio'), 'Could not name an audio track.')
    cursor = timeline.GetStartFrame()
    accepted, audio_items, multicams, spans = [], [], [], []
    direct = 0
    for number_, session in enumerate(sessions, 1):
        # Timecode and angles are relative to the earliest clip Resolve accepts, so
        # a refused clip means a second pass over the clips that are left.
        members = list(session['rows'])
        while members:
            cameras = sorted({r['camera'] for r in members},
                             key=lambda c: (min(r.get('audio_rank', 99) for r in members if r['camera'] == c), c))
            angle = {camera: i + 1 for i, camera in enumerate(cameras)}
            first = min(r['sort_time'] for r in members)
            refused = [row for row in sorted(members, key=lambda r: (angle[r['camera']], r['sort_time']))
                       if not set_multicam_identity(imported[row['key']], row, fps, first,
                                                    angle[row['camera']], row['camera'])]
            if not refused:
                break
            for row in refused:
                excluded.append({'file': row['path'], 'reason': 'Resolve did not accept the multicam timecode for this clip.'})
            members = [r for r in members if r not in refused]
        if not members:
            continue
        if len(cameras) == 1:
            warnings.append('Shoot %d has only one camera (%s); its multicam has a single angle.' % (number_, cameras[0]))
        name = 'Multicam %d · %s' % (number_, datetime.fromtimestamp(session['start']).strftime('%Y-%m-%d %H:%M'))
        options = {'name': name, 'angleSyncMode': resolve.MULTICAM_ANGLE_SYNC_TIMECODE,
                   'detectSameCameraClipsMode': resolve.MULTICAM_DETECT_BY_CAMERA_NUMBER,
                   'angleNameMode': resolve.MULTICAM_ANGLE_NAME_ANGLE,
                   'multicamAudioMode': resolve.MULTICAM_AUDIO_REFERENCE,
                   'frameRate': float(fps), 'createBinForSourceClips': False}
        created = [m for m in pool.CreateMulticamClip([imported[r['key']] for r in members], options) or [] if m]
        need(len(created) == 1, 'Resolve could not create the multicam clip for shoot %d.' % number_)
        multicam = created[0]
        expected = round((max(r['sort_time'] + r['duration'] for r in members) - first) * fps)
        length = int(number(multicam.GetClipProperty().get('Frames')))
        if abs(length - expected) > fps:
            warnings.append('Multicam %d is %.1f s long, expected %.1f s: Resolve may have left a clip out. '
                            'Check it with Clip › Open in Timeline.' % (number_, length / fps, expected / fps))
        multicams.append({'name': name, 'angles': [angle_name(angle[c], c) for c in cameras],
                          'clips': len(members), 'start_frame': cursor})
        accepted.extend(members)
        # The timeline shows only the stretches with picture; pauses between
        # recordings stay inside the multicam clip and never reach the edit.
        for stretch in picture_stretches(members):
            ends = [cursor]
            # A script can't choose a multicam item's angle, and a new item always shows
            # angle 1. Where that camera has no picture, the clip that has picture goes on
            # V1 itself; with one camera there is nothing to switch to anyway.
            for part_start, part_end, row in picture_plan(stretch, angle, 2 / fps):
                record = cursor + round((part_start - stretch['start']) * fps)
                frames = cursor + round((part_end - stretch['start']) * fps) - record
                if frames < 1:
                    continue
                if row is None:
                    in_frame = round((part_start - first) * fps)
                    info = {'mediaPoolItem': multicam, 'startFrame': in_frame,
                            'endFrame': min(in_frame + frames, length or expected)}
                else:
                    rate = row.get('fps') or fps
                    in_frame = round((part_start - row['sort_time']) * rate)
                    info = {'mediaPoolItem': imported[row['key']], 'startFrame': in_frame,
                            'endFrame': source_end(in_frame, frames, fps, rate, row.get('frames'))}
                    direct += 1
                if info['endFrame'] <= info['startFrame']:
                    continue
                present = {i.GetUniqueId() for i in timeline.GetItemListInTrack('video', 1) or [] if i}
                try:
                    pool.AppendToTimeline([dict(info, recordFrame=record, trackIndex=1, mediaType=1)])
                except RuntimeError:
                    pass
                items = [i for i in timeline.GetItemListInTrack('video', 1) or [] if i and i.GetUniqueId() not in present]
                placed = next((i for i in items if i.GetStart() == record), None) or next(
                    (i for i in items if abs(i.GetStart() - record) <= 1), None)
                need(placed, 'Could not place multicam clip %d on the timeline.' % number_)
                ends.append(placed.GetEnd())
            audio_requests = [(row, cursor + round((row['sort_time'] - stretch['start']) * fps))
                              for row in stretch['rows'] if row['audio']]
            if audio_requests:
                try:
                    pool.AppendToTimeline([{'mediaPoolItem': imported[r['key']], 'recordFrame': pos,
                                            'trackIndex': r['audio_track_index'], 'mediaType': 2} for r, pos in audio_requests])
                except RuntimeError:
                    pass
                index = timeline_items_index(timeline, 'audio', {r['audio_track_index'] for r, _ in audio_requests})
                for row, position in audio_requests:
                    item = index.get((row['audio_track_index'], position, row['key']))
                    if item is None:
                        try:
                            pool.AppendToTimeline([{'mediaPoolItem': imported[row['key']], 'recordFrame': position,
                                                    'trackIndex': row['audio_track_index'], 'mediaType': 2}])
                        except RuntimeError:
                            pass
                        item = timeline_source_item(timeline, 'audio', row['audio_track_index'], position, row['key'])
                    if item is None:
                        warnings.append('Source audio missing on the timeline: ' + row['path'])
                        continue
                    audio_items.append((row, item))
                    ends.append(item.GetEnd())
            spans.append((stretch['start'], stretch['end'], cursor))
            # The next stretch starts after whatever ends last, picture or sound.
            cursor = max(ends)
        say('Multicam', number_, '/', len(sessions), ':', len(members), 'clips,', len(cameras), 'cameras')
    need(multicams, 'No multicam clip could be made; see the report.')
    report['selected'] = len(accepted)
    for index in audio_labels:
        need(timeline.SetTrackEnable('audio', index, True), 'Could not enable an audio track.')
    apply_audio_priority(timeline, pool, imported, [(row, item, None, 0.0) for row, item in audio_items]
                         + place_recorder_audio(pool, timeline, imported, recorders, spans, fps, warnings), fps, warnings)
    link_audio_to_picture(timeline, pool, {imported[r['key']].GetUniqueId(): (r.get('fps') or fps, r.get('frames') or round(r['duration'] * (r.get('fps') or fps)))
                                           for r in accepted + recorders}, fps, warnings)
    colours = clip_colour_per_camera([(imported[r['key']], r['camera']) for r in accepted], warnings,
                                     camera_order(accepted))
    report['clip_colours'] = colours
    before = len(warnings)
    report['colour_groups'] = [colour_group_name(camera, colours) for camera in colour_groups_per_camera(
        project, timeline, {imported[r['key']].GetUniqueId(): r['camera'] for r in accepted}, warnings, colours)]
    if direct:
        # Only claim the groups worked when colour_groups_per_camera added no warning of its own.
        warnings.append('%d stretch(es) had no picture from the first camera: the clip that has picture sits on V1 '
                        'directly, so those parts are not multicam.' % direct
                        + (' Each one is in its camera\'s colour group: to grade a camera once, open the multicam '
                           '(Edit page › Clip › Open in Timeline), go to the Color page, show that camera\'s clips (Clips › Clip '
                           'Color), add them to the same group and grade the group (Group Post-Clip).'
                           if len(warnings) == before else ''))
    landscape = [r for r in accepted if r.get('orientation') == 'landscape']
    if VERTICAL and landscape:
        warnings.append('%d landscape clip(s) are centre-cropped to 9:16 inside the multicam: only the middle third '
                        'of the picture stays visible. Check that nobody is cut off.' % len(landscape))
    need(pm.SaveProject(), 'Could not save the project.')
    report.update(timeline=title, timeline_fps=fps, multicams=multicams,
                  source_frame_rates=sorted({r['source_fps'] for r in accepted}),
                  source_files=[r['path'] for r in accepted + recorders], cameras=camera_summary(accepted + recorders),
                  duration_seconds=(cursor - timeline.GetStartFrame()) / fps,
                  color_output=project.GetSettings().get('colorSpaceOutput'), warnings=sorted(set(warnings)))
    resolve.OpenPage('edit')
    return report


def build(resolve, project, imported, disk_paths, ffprobe, ffmpeg):
    started = time.monotonic()
    trim_audio_cache()
    report = {'status': 'preflight', 'script_version': VERSION, 'platform': sys.platform, 'warnings': list(getattr(disk_paths, 'warnings', [])),
              'ignored_nonvideo_files': getattr(disk_paths, 'ignored', 0), 'excluded': [], 'selected': 0}
    try:
        result = build_inner(resolve, project, imported, disk_paths, ffprobe, ffmpeg, report)
        result['status'] = 'completed_with_notes' if result['warnings'] or result['excluded'] else 'completed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        # Keep partial output inspectable; never report partial work as complete.
        if report.get('project'):
            try:
                resolve.GetProjectManager().SaveProject()
            except Exception:
                pass
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        save_report(report)
        raise
    result['elapsed_seconds'] = round(time.monotonic() - started, 2)
    trim_audio_cache()
    return save_report(result)


def build_inner(resolve, project, imported, disk_paths, ffprobe, ffmpeg, report):
    if MULTICAM:
        need(getattr(resolve, 'MULTICAM_ANGLE_SYNC_TIMECODE', None) is not None
             and callable(getattr(project.GetMediaPool(), 'CreateMulticamClip', None)),
             WORKFLOW + ' Timeline needs DaVinci Resolve 21.1 or newer.')
    paths = list(dict.fromkeys(Path(p).resolve() for p in
                 ([Path(p) for p in imported] if disk_paths is None else disk_paths)))
    rows, excluded = inspect_sources(paths, ffprobe)
    report['excluded'] = excluded
    warnings = report['warnings']
    recorders = drop_duplicate_files([r for r in rows if r.get('recorder')], warnings)
    rows = [r for r in rows if not r.get('recorder')]
    need(rows, 'No usable video in this format found; see the report.')
    warnings.extend(reconcile_missing_camera_metadata(rows))
    for row in rows:
        if row.get('timestamp_source', 'metadata') != 'metadata':
            warnings.append('No recording time for %s; file date used, order not confirmed.' % row['path'])
    fps = timeline_frame_rate(rows)
    for row in rows:
        if row.get('rate_warning'):
            warnings.append(row['path'] + ': ' + row['rate_warning'])
    pm = resolve.GetProjectManager()
    if project.GetName() == 'Untitled Project':
        need(not project.GetTimelineCount() and not (project.GetMediaPool().GetRootFolder().GetClipList() or []),
             'Save the untitled project first so your existing work is kept.')
    else:
        need(pm.SaveProject(), 'Could not save the current project.')
    new_name = WORKFLOW + ' ' + datetime.now().strftime('%Y-%m-%d %H%M%S-%f')
    project = need(pm.CreateProject(new_name), 'Could not create a new project.')
    report['project'] = new_name
    settings = managed_color_settings()
    settings.update({'colorSpaceInput': 'Rec.709 Gamma 2.4',
                     'timelineResolutionWidth': WIDTH, 'timelineResolutionHeight': HEIGHT,
                     'timelineFrameRate': format(fps, 'g'), 'videoMonitorFormat': monitor_format(fps)})
    if VERTICAL and MULTICAM:
        # Angles inside a multicam can't be scaled one by one through the API; the
        # project rule "scale full frame with crop" fills 9:16 with landscape angles.
        settings['timelineInputResMismatchBehavior'] = 'scaleToCrop'
    need(project.SetSettings(settings), 'Could not apply project and colour settings.')
    if VERTICAL and MULTICAM:
        need(project.GetSettings().get('timelineInputResMismatchBehavior') == 'scaleToCrop',
             'Could not set "scale full frame with crop" for the multicam angles.')
    pool = project.GetMediaPool()
    need(pool.SetCurrentFolder(pool.GetRootFolder()), 'Could not open the Master bin.')
    rows, imported = import_sources(pool, rows, excluded)
    need(rows, 'Resolve cannot use any of the selected video files; see the report.')
    # An unsupported low-rate file must not dictate the surviving timeline rate.
    fps = timeline_frame_rate(rows)
    need(project.SetSettings({'timelineFrameRate': format(fps, 'g'), 'videoMonitorFormat': monitor_format(fps)}),
         'Could not set the frame rate of the imported clips.')
    need(abs(number(project.GetSetting('timelineFrameRate')) - fps) < .02,
         'Resolve did not apply the chosen project frame rate.')
    warnings.extend(frame_rate_warnings(rows, fps))
    for row in rows:
        clip = imported[row['key']]
        if row['audio']:
            try:
                if not row['is_phone']:
                    if stereo_mapping(clip, row['path'], ffmpeg):
                        warnings.append('Single camera microphone copied to left and right: ' + row['name'])
                else:
                    if primary_stereo_mapping(clip, row['path']):
                        warnings.append('Primary stereo pair used (mono doubled or extra channels left out): ' + row['path'])
            except RECOVERABLE as error:
                # Do not let unknown spatial/multichannel mappings spill into another track.
                row['audio'] = False
                warnings.append('Source audio not placed for %s; picture kept: %s' % (row['path'], error))
    assign_profiles(rows, imported, warnings)
    say('Media imported:', len(rows), '; checking audio sync.')
    evidence, sync_warnings, reference_camera = sync_audio(rows, ffmpeg)
    warnings.extend(sync_warnings)
    recorders = import_recorders(pool, place_recorders(recorders, rows, ffmpeg, warnings, excluded), imported, excluded, ffmpeg, warnings)
    say('Audio synced; comparing sound quality.')
    report['audio_summary'], report['audio_quality'] = rank_audio(rows + recorders, ffmpeg, reference_camera, warnings)
    rows.sort(key=lambda r: (r['sort_time'], r['path']))
    report['audio_sync_evidence'] = evidence
    report['audio_reference_camera'] = reference_camera
    if MULTICAM:
        return build_multicam(resolve, project, pm, pool, imported, rows, recorders, fps, report, warnings, excluded)
    title = WORKFLOW + ' timeline ' + datetime.now().strftime('%Y-%m-%d %H%M%S')
    timeline = need(pool.CreateEmptyTimeline(title), 'Could not create the timeline.')
    report['timeline'] = title
    need(project.SetCurrentTimeline(timeline), 'Could not open the timeline.')
    need(timeline.SetSettings({'useCustomSettings': '1', 'timelineResolutionWidth': WIDTH,
                              'timelineResolutionHeight': HEIGHT, 'videoMonitorFormat': monitor_format(fps)}),
         'Could not apply custom timeline settings.')
    need(timeline.SetSettings(managed_color_settings()), 'Could not apply timeline colour management.')
    need(timeline.GetSetting('useCustomSettings') == '1', '"Use project settings" is still on.')
    need(timeline.GetSetting('timelineResolutionWidth') == WIDTH and timeline.GetSetting('timelineResolutionHeight') == HEIGHT,
         'The timeline has the wrong picture size.')
    need(abs(number(timeline.GetSetting('timelineFrameRate')) - fps) < .02, 'The timeline has the wrong frame rate.')
    need(timeline.GetSetting('videoMonitorFormat') == monitor_format(fps), 'The timeline monitor has the wrong frame rate.')
    need(all(timeline.GetSetting(key) == value for key, value in managed_color_settings().items()),
         'Project and timeline use different colour management.')
    labels = allocate_tracks(rows + recorders, fps, warnings)
    if labels:
        report['top_video'] = labels[max(labels)]
    audio_labels = {row['audio_track_index']: row['lane_label'] for row in rows + recorders}
    for index, label in labels.items():
        while timeline.GetTrackCount('video') < index:
            need(timeline.AddTrack('video'), 'Could not add a video track.')
        need(timeline.SetTrackName('video', index, label), 'Could not name a video track.')
        if 'overlap' in label:
            warnings.append('Extra track created for simultaneous clips: ' + label)
    for index, label in sorted(audio_labels.items()):
        while timeline.GetTrackCount('audio') < index:
            need(timeline.AddTrack('audio', 'stereo'), 'Could not add an audio track.')
        need(timeline.SetTrackName('audio', index, label + ' audio'), 'Could not name an audio track.')
    groups = []
    for row in rows:
        end = row['sort_time'] + row['duration']
        if not groups or row['sort_time'] > groups[-1]['end']:
            groups.append({'start': row['sort_time'], 'end': end, 'rows': [row]})
        else:
            groups[-1]['end'] = max(groups[-1]['end'], end)
            groups[-1]['rows'].append(row)
    start = cursor = timeline.GetStartFrame()
    accepted, pairs_all, spans = [], [], []
    for group_number, group in enumerate(groups, 1):
        requests, positions = [], []
        for row in group['rows']:
            position = cursor + round((row['sort_time'] - group['start']) * fps)
            base = {'mediaPoolItem': imported[row['key']], 'recordFrame': position,
                    'trackIndex': row['track_index'], 'mediaType': 1}
            requests.append(base)
            positions.append((row, position))
        try:
            pool.AppendToTimeline(requests)
        except RuntimeError as error:
            warnings.append('Group import incomplete; missing clips are retried: ' + str(error))
        indices = {row['track_index'] for row, _ in positions}
        video_index = timeline_items_index(timeline, 'video', indices)
        placed, surviving, audio_requests = {}, [], []
        for row, position in positions:
            item = video_index.get((row['track_index'], position, row['key']))
            if item is None:
                try:
                    pool.AppendToTimeline([{'mediaPoolItem': imported[row['key']], 'recordFrame': position,
                                            'trackIndex': row['track_index'], 'mediaType': 1}])
                except RuntimeError:
                    pass
                item = timeline_source_item(timeline, 'video', row['track_index'], position, row['key'])
            if item is None:
                excluded.append({'file': row['path'], 'reason': 'Resolve could not place this clip on the timeline.'})
                continue
            placed[row['key']] = item
            surviving.append((row, position))
            accepted.append(row)
            report['selected'] = len(accepted)
            if row['audio']:
                audio_requests.append({'mediaPoolItem': imported[row['key']], 'recordFrame': position,
                                       'trackIndex': row['audio_track_index'], 'mediaType': 2})
        if audio_requests:
            try:
                pool.AppendToTimeline(audio_requests)
            except RuntimeError:
                pass
            audio_index = timeline_items_index(timeline, 'audio', {r['audio_track_index'] for r, _ in surviving})
            pairs = []
            for row, position in surviving:
                if not row['audio']:
                    continue
                index = row['audio_track_index']
                audio_item = audio_index.get((index, position, row['key']))
                if audio_item is None:
                    try:
                        pool.AppendToTimeline([{'mediaPoolItem': imported[row['key']],
                                                'recordFrame': position, 'trackIndex': index, 'mediaType': 2}])
                    except RuntimeError:
                        pass
                    audio_item = timeline_source_item(timeline, 'audio', index, position, row['key'])
                if audio_item is None:
                    row['audio'] = False
                    warnings.append('Source audio missing on the timeline; picture kept: ' + row['path'])
                    continue
                pairs.append((placed[row['key']], audio_item, row['path']))
                pairs_all.append((row, placed[row['key']], audio_item))
            link_source_audio(timeline, pairs)
        if placed:
            spans.append((group['start'], group['end'], cursor))
            cursor = max(item.GetEnd() for item in placed.values())
        if group_number % 10 == 0 or group_number == len(groups):
            say('Timeline groups:', group_number, '/', len(groups), '; video clips:', len(accepted), '/', len(rows))
    need(accepted, 'No clip could be placed on the timeline; see the report.')
    for index in audio_labels:
        need(timeline.SetTrackEnable('audio', index, True), 'Could not enable an audio track.')
    apply_audio_priority(timeline, pool, imported, [(row, audio, video, 0.0) for row, video, audio in pairs_all]
                         + place_recorder_audio(pool, timeline, imported, recorders, spans, fps, warnings), fps, warnings)
    link_recorders_to_picture(timeline, pool, imported, recorders, fps, warnings)
    placed = [item for i in range(1, timeline.GetTrackCount('video') + 1)
              for item in timeline.GetItemListInTrack('video', i) or [] if item]
    need(len(accepted) == len(placed), 'Clip counts do not match.')
    end = start
    for first, last in sorted((item.GetStart(), item.GetEnd()) for item in placed):
        if first > end:
            warnings.append('Timeline gap after skipped media: frames %s–%s.' % (end, first))
        end = max(end, last)
    filled = []
    if WORKFLOW == 'Reels':
        # SCALE_FILL = "Scale full frame with crop". SCALE_CROP would be "Center crop
        # with no resizing": black bars on 1080p sources and extra zoom on 4K.
        fill = getattr(resolve, 'SCALE_FILL', 3)
        by_key = {r['key']: r for r in accepted}
        for item in placed:
            key = path_key(item.GetMediaPoolItem().GetClipProperty('File Path'))
            need(item.SetProperty('Scaling', fill), 'Could not scale to fill: ' + by_key[key]['path'])
            need(abs(number(item.GetProperty('Scaling')) - number(fill)) < .5,
                 'Could not confirm scale to fill: ' + by_key[key]['path'])
            if by_key[key]['orientation'] == 'landscape':
                filled.append(by_key[key]['path'])
        if filled:
            warnings.append('%d landscape clip(s) are centre-cropped to 9:16: only the middle third of the picture '
                            'stays visible. Check that nobody is cut off.' % len(filled))
    need(pm.SaveProject(), 'Could not save the project.')
    report.update(timeline=title, timeline_fps=fps, selected=len(accepted),
                  source_frame_rates=sorted({r['source_fps'] for r in accepted}),
                  source_files=[r['path'] for r in accepted + recorders],
                  cameras=camera_summary(accepted + recorders),
                  portrait=sum(r.get('orientation') == 'portrait' for r in accepted),
                  landscape_fill_cropped=filled, duration_seconds=(end - start) / fps,
                  color_output=project.GetSetting('colorSpaceOutput'),
                  warnings=sorted(set(warnings)))
    resolve.OpenPage('edit')
    return report


def audio_pieces(start, end, better, minimum):
    """Split [start, end) into (first, last, covered) pieces by the better audio around it.

    Uncovered scraps shorter than `minimum` frames count as covered: a blip of a
    second microphone sounds worse than a moment of the main one running out.
    """
    pieces, cursor = [], start
    for first, last in sorted(better):
        first, last = max(first, start), min(last, end)
        if last <= cursor or first >= end:
            continue
        if first > cursor:
            pieces.append([cursor, first, False])
        pieces.append([max(first, cursor), last, True])
        cursor = last
    if cursor < end:
        pieces.append([cursor, end, False])
    for piece in pieces:
        if not piece[2] and piece[1] - piece[0] < minimum:
            piece[2] = True
    merged = []
    for first, last, covered in pieces:
        if merged and merged[-1][1] == first and (merged[-1][2] == covered or last - first < 2):
            merged[-1][1] = last
        else:
            merged.append([first, last, covered])
    if len(merged) > 1 and merged[0][1] - merged[0][0] < 2:
        merged[1][0] = merged[0][0]
        merged.pop(0)
    return [tuple(piece) for piece in merged]


def track_item_ids(timeline, track):
    return {i.GetUniqueId() for i in timeline.GetItemListInTrack('audio', track) or [] if i}


def append_audio(pool, timeline, clip, track, record, first, last, skip=()):
    """Place part of a clip on an audio track; read the real item back, Resolve's answer can be empty."""
    try:
        pool.AppendToTimeline([{'mediaPoolItem': clip, 'mediaType': 2, 'trackIndex': track, 'recordFrame': record,
                                'startFrame': first, 'endFrame': max(last, first + 1)}])
    except RuntimeError:
        return None
    items = [i for i in timeline.GetItemListInTrack('audio', track) or [] if i and i.GetUniqueId() not in skip]
    return (next((i for i in items if i.GetStart() == record), None)
            or next((i for i in items if abs(i.GetStart() - record) <= 1), None))


def replace_with_pieces(timeline, pool, clip, row, item, pieces, fps, warnings, video=None, source=0.0):
    """Swap one audio item for cut pieces, muted where better audio covers them.

    If a piece can't be placed, the whole clip goes back: audible double sound
    with a note beats a clip that is gone.
    """
    track = row['audio_track_index']
    start, whole_end, rate = item.GetStart(), item.GetEnd(), row.get('fps') or fps
    limit = row.get('frames') or round(row['duration'] * rate)
    def frame(position):
        return min(round(((position - start) / fps + source) * rate), limit)
    if video is not None:
        need(timeline.SetClipsLinked([video, item], False), 'Could not unlink source audio: ' + row['path'])
    need(timeline.DeleteClips([item], False), 'Could not cut source audio: ' + row['path'])
    neighbours = track_item_ids(timeline, track)
    placed = []
    for first, last, covered in pieces:
        piece = append_audio(pool, timeline, clip, track, first, frame(first),
                             source_end(frame(first), last - first, fps, rate, limit),
                             neighbours | {i.GetUniqueId() for i in placed})
        if piece is None or not piece.SetClipEnabled(not covered):
            break
        placed.append(piece)
    if len(placed) == len(pieces) and (video is None or timeline.SetClipsLinked([video] + placed, True)):
        return True
    if placed:
        timeline.DeleteClips(placed, False)
    whole = append_audio(pool, timeline, clip, track, start, frame(start),
                         source_end(frame(start), whole_end - start, fps, rate, limit), neighbours)
    if whole is None:
        warnings.append('Source audio lost while cutting, picture kept: ' + row['path'])
        return False
    whole.SetClipEnabled(True)
    if video is not None:
        timeline.SetClipsLinked([video, whole], True)
    warnings.append('Could not cut this clip, so it stays audible as a whole; check for double sound: ' + row['path'])
    return False


def apply_audio_priority(timeline, pool, imported, entries, fps, warnings):
    """One voice at a time: a clip sounds only where no better confirmed camera recorded.

    entries: (row, audio item, video item or None, source seconds). Clips without
    confirmed sync stay whole and audible, because their position isn't proven.
    """
    spans = [(entry[0], entry[1].GetStart(), entry[1].GetEnd()) for entry in entries]
    cut = 0
    for row, item, video, source in entries:
        better = [(first, last) for other, first, last in spans
                  if other['audio_rank'] < row['audio_rank'] and other['sync_method'] in CONFIRMED_SYNC]
        pieces = audio_pieces(item.GetStart(), item.GetEnd(), better, round(fps / 2))
        if row['sync_method'] not in CONFIRMED_SYNC:
            need(item.SetClipEnabled(True), 'Could not enable source audio: ' + row['path'])
            if any(covered for _, _, covered in pieces):
                warnings.append('Sync not confirmed, so this clip stays audible; check for double sound: ' + row['path'])
        elif len(pieces) == 1:
            need(item.SetClipEnabled(not pieces[0][2]), 'Could not enable/mute source audio: ' + row['path'])
        else:
            cut += replace_with_pieces(timeline, pool, imported[row['key']], row, item, pieces, fps, warnings, video, source)
    if cut:
        warnings.append('%d clip(s) cut on the audio track: they sound only where a better camera did not record.' % cut)


def cut_points(start, end, pictures):
    """Where one audio item crosses the edges of the picture items above it.

    No cut within 2 frames of the item's ends or of the previous cut: a one-frame
    piece would be overwritten when it is placed back.
    """
    kept = []
    for edge in sorted({edge for span in pictures for edge in span if start + 2 <= edge <= end - 2}):
        if not kept or edge - kept[-1] >= 2:
            kept.append(edge)
    return kept


def split_audio(timeline, pool, item, track, points, rate, available, fps, warnings):
    """Cut one audio item at these timeline frames; the sound itself doesn't change."""
    clip, start, end = item.GetMediaPoolItem(), item.GetStart(), item.GetEnd()
    # GetSourceStartFrame() rounds down, often one frame too early; the left offset is exact.
    source, enabled = round(item.GetLeftOffset(True) * rate / fps), item.GetClipEnabled()
    edges = [start] + points + [end]
    if not timeline.DeleteClips([item], False):
        warnings.append('Could not cut this audio at the picture edges, so it stays whole: ' + str(clip.GetName()))
        return [item]
    neighbours = track_item_ids(timeline, track)
    placed = []
    for first, last in zip(edges, edges[1:]):
        begin = source + round((first - start) / fps * rate)
        piece = append_audio(pool, timeline, clip, track, first, begin, source_end(begin, last - first, fps, rate, available),
                             neighbours | {i.GetUniqueId() for i in placed})
        if piece is None or not piece.SetClipEnabled(enabled):
            break
        placed.append(piece)
    if len(placed) == len(edges) - 1:
        return placed
    if placed:
        timeline.DeleteClips(placed, False)
    whole = append_audio(pool, timeline, clip, track, start, source, source_end(source, end - start, fps, rate, available), neighbours)
    if whole is None:
        warnings.append('Audio lost while linking it to the picture: ' + str(clip.GetName()))
        return []
    whole.SetClipEnabled(enabled)
    warnings.append('Could not cut this audio at the picture edges, so it stays whole: ' + str(clip.GetName()))
    return [whole]


def link_audio_to_picture(timeline, pool, sources, fps, warnings):
    """Link every sound to the picture above it, so a trim on V1 takes the sound along.

    Sound that runs under two picture items is cut there first: linked to both,
    it would chain all those items into one group.
    """
    videos = sorted((i for i in timeline.GetItemListInTrack('video', 1) or [] if i), key=lambda i: i.GetStart())
    spans = [(i.GetStart(), i.GetEnd()) for i in videos]
    sounds = []
    for track in range(1, timeline.GetTrackCount('audio') + 1):
        for item in [i for i in timeline.GetItemListInTrack('audio', track) or [] if i]:
            points = cut_points(item.GetStart(), item.GetEnd(), spans)
            if points:
                clip = item.GetMediaPoolItem()
                rate, available = sources.get(clip.GetUniqueId(), (fps, None))
                pieces = split_audio(timeline, pool, item, track, points, rate, available, fps, warnings)
                if len(pieces) == len(points) + 1:
                    sounds += pieces
                # Uncut, it would tie the sound under all those pictures to one of them: leave it unlinked.
            else:
                sounds.append(item)
    groups = defaultdict(list)
    for sound in sounds:
        shared = [min(sound.GetEnd(), last) - max(sound.GetStart(), first) for first, last in spans]
        if shared and max(shared) > 0:
            groups[shared.index(max(shared))].append(sound)
    failed = sum(not timeline.SetClipsLinked([videos[index]] + group, True) for index, group in groups.items())
    if failed:
        warnings.append('%d picture item(s) could not be linked to their sound: trim those with Linked Selection off, '
                        'and check the sync.' % failed)


def visible_pictures(timeline):
    """The picture you see from moment to moment: (start, end, item) on the highest video track."""
    items = [(index, item) for index in range(1, timeline.GetTrackCount('video') + 1)
             for item in timeline.GetItemListInTrack('video', index) or [] if item]
    edges = sorted({edge for _, item in items for edge in (item.GetStart(), item.GetEnd())})
    visible = []
    for first, last in zip(edges, edges[1:]):
        over = [(index, item) for index, item in items if item.GetStart() <= first and item.GetEnd() >= last]
        if not over:
            continue
        top = max(over, key=lambda pair: pair[0])[1]
        if visible and visible[-1][2] is top and visible[-1][1] == first:
            visible[-1] = (visible[-1][0], last, top)
        else:
            visible.append((first, last, top))
    return visible


def link_recorders_to_picture(timeline, pool, imported, recorders, fps, warnings):
    """Link each recorder piece to the picture you see above it, so a trim there takes the recorder along.

    The recorder is cut at the edges of that picture first; what you hear doesn't change. Linked to
    two picture items, it would chain them into one group.
    """
    if not recorders:
        return
    visible = visible_pictures(timeline)
    spans = [(first, last) for first, last, _ in visible]
    sources = {imported[r['key']].GetUniqueId(): (r.get('fps') or fps, r.get('frames') or round(r['duration'] * (r.get('fps') or fps)))
               for r in recorders}
    sounds = []
    for track in sorted({r['audio_track_index'] for r in recorders}):
        for item in [i for i in timeline.GetItemListInTrack('audio', track) or [] if i]:
            points = cut_points(item.GetStart(), item.GetEnd(), spans)
            if points:
                rate, available = sources.get(item.GetMediaPoolItem().GetUniqueId(), (fps, None))
                pieces = split_audio(timeline, pool, item, track, points, rate, available, fps, warnings)
                if len(pieces) == len(points) + 1:
                    sounds += pieces
                # Uncut, it would tie the sound under all those pictures to one of them: leave it unlinked.
            else:
                sounds.append(item)
    groups = {}
    for sound in sounds:
        shared = [min(sound.GetEnd(), last) - max(sound.GetStart(), first) for first, last, _ in visible]
        if shared and max(shared) > 0:
            picture = visible[shared.index(max(shared))][2]
            groups.setdefault(id(picture), (picture, []))[1].append(sound)
    # SetClipsLinked replaces a link group (measured 13 Nov 2026), so the camera's own sound goes along.
    failed = sum(not timeline.SetClipsLinked([picture] + (picture.GetLinkedItems() or []) + group, True)
                 for picture, group in groups.values())
    if failed:
        warnings.append('%d picture item(s) could not be linked to the recorder: trim those with Linked Selection off, '
                        'and check the sync.' % failed)


def resolve_modules_folders():
    if IS_WINDOWS:
        data = os.environ.get('PROGRAMDATA') or r'C:\ProgramData'
        return [os.path.join(data, 'Blackmagic Design', 'DaVinci Resolve', 'Support', 'Developer', 'Scripting', 'Modules')]
    if IS_MAC:
        return ['/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules']
    return ['/opt/resolve/Developer/Scripting/Modules', '/home/resolve/Developer/Scripting/Modules']


def connect():
    app = globals().get('resolve')
    if app is None and globals().get('bmd') is not None:
        app = globals()['bmd'].scriptapp('Resolve')
    if app is None:
        try:
            import DaVinciResolveScript
        except ImportError:
            sys.path.extend(resolve_modules_folders())
            import DaVinciResolveScript
        app = DaVinciResolveScript.scriptapp('Resolve')
    return need(app, 'DaVinci Resolve cannot be reached.')


def open_file(path):
    try:
        if IS_WINDOWS:
            os.startfile(path)
        elif IS_MAC:
            subprocess.Popen(['/usr/bin/open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except (OSError, AttributeError):
        pass


def main():
    app = connect()
    try:
        # Before the folder is chosen: without working FFmpeg the user gets a report, not silence.
        ffprobe, ffmpeg = binaries()
    except RuntimeError as error:
        save_report({'status': 'failed', 'script_version': VERSION, 'platform': sys.platform,
                     'error': str(error), 'warnings': [], 'excluded': []})
        if LAST_REPORT.get('text_report_path'):
            open_file(LAST_REPORT['text_report_path'])
        raise
    project, imported, disk_paths = source_from_resolve(app)
    if project is None:
        say('Cancelled; no project changed.')
        return None
    try:
        return build(app, project, imported, disk_paths, ffprobe, ffmpeg)
    finally:
        if LAST_REPORT and LAST_REPORT.get('text_report_path'):
            open_file(LAST_REPORT['text_report_path'])


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
