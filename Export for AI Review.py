#!/usr/bin/env python3
"""Export the current timeline as an MP4 for an AI video review.

Run from Workspace > Scripts inside DaVinci Resolve (macOS or Windows).
The Deliver page is put back the way it was and checked afterwards.
See README.md for installation, settings and known limitations.
"""

VERSION = '1.1.0'  # https://github.com/cuttingclockwork/davinci-auto-setup

# ---------------------------------------------------------------------------
# SETTINGS: the only part most people need to change.
# ---------------------------------------------------------------------------

# 'timeline' = the whole timeline.
# 'marks'    = only between the In and Out marks. A missing In mark means the
#              start of the timeline, a missing Out mark the end.
RANGE = 'timeline'

# Folder for the MP4, e.g. '/Users/me/Desktop'. Empty = ask every time.
OUTPUT_FOLDER = ''

# Stop waiting for the render after this many minutes.
MAX_RENDER_MINUTES = 30

# ---------------------------------------------------------------------------

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

IS_WINDOWS = sys.platform.startswith('win')
IS_MAC = sys.platform == 'darwin'

# Fields of a render job that are compared before and after, but not restored
# as such: they describe the job, not the Deliver settings.
IGNORED_JOB_KEYS = ('JobId', 'RenderJobName', 'TimelineName', 'PresetName', 'UploadStatus')
REQUIRED_JOB_KEYS = ('TargetDir', 'OutputFilename', 'MarkIn', 'MarkOut', 'IsExportVideo', 'IsExportAudio')
# Job fields that SetRenderSettings accepts under the same name. Switching to
# MP4 resets audio (e.g. LPCM -> AAC) and a preset does not bring it back.
RESTORABLE_JOB_KEYS = ('AudioCodec', 'AudioBitDepth', 'AudioSampleRate', 'ExportAlpha', 'AlphaMode',
                       'EncodingProfile', 'MultiPassEncode', 'NetworkOptimization',
                       'ClipStartFrame', 'TimelineStartTimecode', 'ReplaceExistingFilesInPlace')


class Stop(Exception):
    """A situation the user can fix; the message says how."""


def say(*parts):
    """Resolve's console on Windows may not accept every character in a file name."""
    try:
        print(*parts)
    except UnicodeEncodeError:
        print(*(str(p).encode('ascii', 'replace').decode() for p in parts))


def logs_folder():
    if IS_WINDOWS:
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        return local / 'Resolve Timeline Scripts' / 'Logs'
    return Path.home() / 'Library' / 'Logs' / 'Resolve Timeline Scripts'


def open_file(path, reveal=False):
    try:
        if IS_WINDOWS:
            if reveal:
                subprocess.Popen(['explorer', '/select,', str(path)])
            else:
                os.startfile(str(path))
        elif IS_MAC:
            subprocess.Popen(['/usr/bin/open', '-R', str(path)] if reveal else ['/usr/bin/open', str(path)])
        else:
            subprocess.Popen(['xdg-open', str(Path(path).parent if reveal else path)])
    except (OSError, AttributeError):
        pass


def show_message(title, lines):
    """Write a short note to the log folder and open it; Resolve has no simple message box."""
    text = '\n'.join(['Export for AI Review %s' % VERSION, title, ''] + list(lines)) + '\n'
    say(text)
    try:
        folder = logs_folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('Export for AI Review %s.txt' % datetime.now().strftime('%Y-%m-%d %H%M%S'))
        path.write_text(text, encoding='utf-8')
        open_file(path)
    except OSError:
        pass


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
    if not app:
        raise Stop('DaVinci Resolve cannot be reached. Run this script from Workspace > Scripts inside Resolve.')
    return app


# ---------------------------------------------------------------------------
# Range and file names (no Resolve needed; covered by tests)
# ---------------------------------------------------------------------------

def export_range(start, end, marks, mode):
    """Absolute frames with an exclusive end. Resolve's Out mark is inclusive."""
    if mode not in ('timeline', 'marks'):
        raise Stop("RANGE must be 'timeline' or 'marks' (it is %r)." % (mode,))
    first, last = start, end
    if mode == 'marks':
        marks = marks or {}
        video, audio = marks.get('video') or {}, marks.get('audio') or {}
        if video and audio and video != audio:
            raise Stop('The video and audio In/Out marks differ. Align them, or set RANGE to "timeline".')
        mark = video or audio
        if not mark:
            raise Stop('RANGE is "marks", but this timeline has no In or Out mark. Set them, or set RANGE to "timeline".')
        first = start + int(mark['in']) if 'in' in mark else start
        last = start + int(mark['out']) + 1 if 'out' in mark else end
    if not start <= first < last <= end:
        raise Stop('The In/Out range lies outside the timeline. Check the marks.')
    return first, last


def safe_name(text):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(text)).strip(' .')
    return name[:120] or 'Timeline'


def unique_path(folder, stem, suffix):
    path = Path(folder) / (stem + suffix)
    n = 2
    while path.exists():
        path = Path(folder) / ('%s %d%s' % (stem, n, suffix))
        n += 1
    return path


# ---------------------------------------------------------------------------
# Deliver settings: snapshot, restore, verify
# ---------------------------------------------------------------------------

def find_job(project, job_id):
    return next((j for j in project.GetRenderJobList() or [] if j.get('JobId') == job_id), None)


def snapshot(project):
    """What the Deliver page would render now, read from a temporary job."""
    job_id = project.AddRenderJob()
    if not job_id:
        raise Stop('Resolve could not read the Deliver settings. Open the Deliver page once, then try again.')
    try:
        job = find_job(project, job_id)
    finally:
        project.DeleteRenderJob(job_id)
    if not job or any(job.get(k) is None for k in REQUIRED_JOB_KEYS):
        raise Stop('Resolve did not report enough Deliver settings to restore them afterwards. Nothing was changed.')
    fc = dict(project.GetCurrentRenderFormatAndCodec() or {})
    if fc.get('format') and not fc.get('codec'):
        # Some presets (seen with a downloaded H.265 preset) report an empty codec
        # while the job shows its name; a preset does not restore it either.
        fc['codec'] = (project.GetRenderCodecs(fc['format']) or {}).get(job.get('VideoCodec'))
    if not fc.get('format') or not fc.get('codec'):
        raise Stop('Resolve does not report which format and codec the Deliver page uses, so they could not be '
                   'restored afterwards. Choose a format and codec on the Deliver page, then try again. Nothing was changed.')
    return {'job': {k: v for k, v in job.items() if k not in IGNORED_JOB_KEYS},
            'format_codec': fc, 'render_mode': project.GetCurrentRenderMode()}


def restore(project, snap, preset, size_changed=False):
    """Put the Deliver page back and compare every field Resolve exposes."""
    job, fc = snap['job'], snap['format_codec']
    problems = []
    if not project.LoadRenderPreset(preset):
        problems.append('backup preset could not be loaded')
    if not project.SetCurrentRenderMode(snap['render_mode']):
        problems.append('render mode')
    if not project.SetCurrentRenderFormatAndCodec(fc['format'], fc['codec']):
        problems.append('format/codec')
    # The file name is deliberately never set: Resolve cannot restore the
    # "Timeline Name" token once a script has set a fixed name.
    if not project.SetRenderSettings({'TargetDir': job['TargetDir'], 'ExportVideo': job['IsExportVideo'],
                                      'ExportAudio': job['IsExportAudio'], 'SelectAllFrames': False,
                                      'MarkIn': job['MarkIn'], 'MarkOut': job['MarkOut']}):
        problems.append('render settings')
    if size_changed:
        # Only a size the user had set differently from the timeline is ever
        # changed, so setting it back as fixed numbers restores it faithfully.
        if not project.SetRenderSettings({'FormatWidth': job['FormatWidth'], 'FormatHeight': job['FormatHeight']}):
            problems.append('resolution')
    for key in RESTORABLE_JOB_KEYS:
        if key in job:
            # One key per call: a key the format rejects must not block the rest.
            project.SetRenderSettings({key: job[key]})
    after = snapshot(project)
    problems += [k for k, v in job.items() if after['job'].get(k) != v]
    if after['format_codec'] != fc:
        problems.append('format/codec')
    if after['render_mode'] != snap['render_mode']:
        problems.append('render mode')
    return sorted(set(problems))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def wait_for_render(project, job_id):
    deadline = time.time() + MAX_RENDER_MINUTES * 60
    status = {}
    while time.time() < deadline:
        time.sleep(1)
        status = project.GetRenderJobStatus(job_id) or {}
        state = str(status.get('JobStatus') or '')
        if state in ('Complete', 'Failed') or 'cancel' in state.lower():
            return state, status.get('Error')
        if not project.IsRenderingInProgress() and state not in ('Rendering', 'Ready', 'Queued', ''):
            return state, status.get('Error')
    return 'Timed out', None


def export(app, output_folder=None):
    project = app.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        raise Stop('Open the timeline you want to export, then run the script again.')
    if project.IsRenderingInProgress():
        raise Stop('Resolve is already rendering. Wait until it has finished, then try again.')
    if project.GetCurrentRenderMode() != 1:
        raise Stop('Set the Deliver page to "Single clip", then try again. Nothing was changed.')

    first, end = export_range(int(timeline.GetStartFrame()), int(timeline.GetEndFrame()),
                              timeline.GetMarkInOut(), RANGE)
    folder = output_folder or OUTPUT_FOLDER or app.Fusion().RequestDir('Where should the MP4 for the AI review go?')
    if not folder:
        return None
    folder = Path(folder)
    if not folder.is_dir():
        raise Stop('The output folder does not exist: %s' % folder)

    snap = snapshot(project)
    size = (int(timeline.GetSetting('timelineResolutionWidth') or 0), int(timeline.GetSetting('timelineResolutionHeight') or 0))
    # Export at the timeline's own resolution. When Deliver already matches it
    # (for example "Timeline Resolution"), the size is left alone, because a
    # script cannot check whether that choice would survive being set.
    size_changed = min(size) > 0 and (snap['job'].get('FormatWidth'), snap['job'].get('FormatHeight')) != size
    preset = '__ai_review_backup_%s' % datetime.now().strftime('%Y%m%d_%H%M%S')
    if not project.SaveAsNewRenderPreset(preset):
        raise Stop('Resolve could not save a backup of the Deliver settings. Nothing was changed.')
    work = Path(tempfile.mkdtemp(prefix='ai-review-'))
    job_id, problems, warnings, result, failure = None, [], [], None, None
    try:
        if snap['format_codec']['format'] != 'mp4':
            # ProRes and other large formats become H.264; an MP4 setting is kept as it is.
            if not project.SetCurrentRenderFormatAndCodec('mp4', 'H264'):
                raise Stop('Resolve could not switch to MP4/H.264 on this system.')
        if not project.SetRenderSettings({'TargetDir': str(work), 'ExportVideo': True, 'ExportAudio': True,
                                          'SelectAllFrames': False, 'MarkIn': first, 'MarkOut': end - 1}):
            raise Stop('Resolve refused the export settings.')
        if size_changed and not project.SetRenderSettings({'FormatWidth': size[0], 'FormatHeight': size[1]}):
            raise Stop('Resolve refused the timeline resolution for this export.')
        job_id = project.AddRenderJob()
        if not job_id:
            raise Stop('Resolve refused the export job.')
        job = find_job(project, job_id) or {}
        if Path(job.get('TargetDir') or '').resolve() != work.resolve() or job.get('MarkIn') != first \
                or job.get('MarkOut') != end - 1 or not str(job.get('OutputFilename', '')).lower().endswith('.mp4') \
                or (size_changed and (job.get('FormatWidth'), job.get('FormatHeight')) != size):
            raise Stop('The queued export does not match what was asked; nothing was rendered.')
        # The job keeps its own settings, so the Deliver page goes back before rendering.
        problems = restore(project, snap, preset, size_changed)
        if problems:
            raise Stop('Your Deliver settings could not be put back exactly (%s); nothing was rendered.'
                       % ', '.join(problems))
        if not project.StartRendering([job_id]):
            raise Stop('Resolve did not start the export.')
        state, error = wait_for_render(project, job_id)
        if state != 'Complete':
            raise Stop('The export did not finish (%s%s).' % (state, ': %s' % error if error else ''))
        rendered = work / job['OutputFilename']
        if not rendered.is_file():
            files = [p for p in work.iterdir() if p.suffix.lower() == '.mp4']
            rendered = files[0] if len(files) == 1 else rendered
        if not rendered.is_file():
            raise Stop('Resolve reported the export as complete, but the file is missing.')
        result = unique_path(folder, safe_name(timeline.GetName()) + ' - AI review', '.mp4')
        shutil.move(str(rendered), str(result))
    except Stop as stop:
        failure = str(stop)
    except Exception:
        failure = 'Unexpected error:\n' + traceback.format_exc()
    finally:
        if job_id and find_job(project, job_id):
            project.DeleteRenderJob(job_id)
        # Starting a render may reload Deliver settings; check once more.
        problems = restore(project, snap, preset, size_changed)
        if problems:
            warnings.append('Your Deliver settings could not be put back exactly: %s. The backup preset "%s" was '
                            'kept; load it on the Deliver page to get your settings back.' % (', '.join(problems), preset))
        else:
            project.DeleteRenderPreset(preset)
        try:
            os.rmdir(work)  # Only succeeds when empty; never deletes anything else.
        except OSError:
            warnings.append('A temporary folder was left behind: %s' % work)
    if failure:
        raise Stop('\n\n'.join([failure] + warnings))
    return result, warnings


def main():
    try:
        app = connect()
        outcome = export(app)
        if outcome is None:
            say('Cancelled; nothing was changed.')
            return
        path, warnings = outcome
        say('Saved: %s' % path)
        if warnings:
            show_message('The MP4 is ready, but please check:', ['File: %s' % path, ''] + warnings)
        open_file(path, reveal=True)
    except Stop as stop:
        show_message('The export stopped.', [str(stop)])
    except Exception:
        show_message('The export stopped because of an unexpected error.',
                     ['Please report this at https://github.com/cuttingclockwork/davinci-auto-setup/issues', '',
                      traceback.format_exc()])


if __name__ == '__main__':
    main()
