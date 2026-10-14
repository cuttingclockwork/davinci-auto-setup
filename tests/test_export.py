"""Tests for 'Export for AI Review': the parts that do not need DaVinci Resolve,
plus the Deliver restore logic against a stand-in that mimics Resolve's quirks.

Run from the repo root:
    uvx --with pytest pytest -q tests
"""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope='module')
def ex():
    spec = importlib.util.spec_from_file_location('export_for_ai_review', ROOT / 'Export for AI Review.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Range ---------------------------------------------------------------

def test_whole_timeline_ignores_marks(ex):
    assert ex.export_range(90000, 90491, {'video': {'in': 10, 'out': 300}}, 'timeline') == (90000, 90491)


def test_marks_use_inclusive_out(ex):
    marks = {'video': {'in': 10, 'out': 300}, 'audio': {'in': 10, 'out': 300}}
    assert ex.export_range(90000, 90491, marks, 'marks') == (90010, 90301)


def test_single_mark_extends_to_timeline_edge(ex):
    assert ex.export_range(90000, 90491, {'video': {'out': 99}}, 'marks') == (90000, 90100)
    assert ex.export_range(90000, 90491, {'video': {'in': 50}}, 'marks') == (90050, 90491)


@pytest.mark.parametrize('marks', [
    {},  # no marks at all
    {'video': {'in': 0, 'out': 10}, 'audio': {'in': 0, 'out': 20}},  # video and audio differ
    {'video': {'in': 0, 'out': 9999}},  # beyond the timeline
])
def test_bad_marks_stop_with_a_message(ex, marks):
    with pytest.raises(ex.Stop):
        ex.export_range(90000, 90491, marks, 'marks')


def test_unknown_range_setting_stops(ex):
    with pytest.raises(ex.Stop):
        ex.export_range(0, 100, {}, 'everything')


# --- File names ----------------------------------------------------------

def test_safe_name_removes_characters_that_break_paths(ex):
    assert ex.safe_name('Reel: v2/final?') == 'Reel_ v2_final_'
    assert ex.safe_name('...') == 'Timeline'


def test_claim_path_never_overwrites(ex, tmp_path):
    existing = tmp_path / 'Short - AI review.mp4'
    existing.write_bytes(b'keep')
    first = ex.claim_path(tmp_path, 'Short - AI review', '.mp4')
    second = ex.claim_path(tmp_path, 'Short - AI review', '.mp4')
    assert (first.name, second.name) == ('Short - AI review 2.mp4', 'Short - AI review 3.mp4')
    assert existing.read_bytes() == b'keep' and first.exists() and second.exists()


# --- Deliver restore against a stand-in for Resolve --------------------------

CODEC_NAMES = {'H264': 'H.264', 'H265': 'H.265', 'ProRes422HQ': 'Apple ProRes 422 HQ'}


class FakeTimeline:
    def __init__(self, project): self.project = project
    def GetMarkInOut(self): return copy.deepcopy(self.project.marks)


class FakeProject:
    """Mimics what was observed in Resolve Studio 21.1.1: switching to MP4 resets the
    audio to AAC 32-bit, presets do not restore audio, the file name or a codec that
    Resolve reports as empty."""

    def __init__(self, fmt='mov', codec='ProRes422HQ', hide_codec=False):
        self.fc = {'format': fmt, 'codec': codec}
        self.hide_codec = hide_codec
        self.mode = 1
        self.settings = {'TargetDir': '/user/exports', 'Name': 'Timeline Name token', 'ExportVideo': True,
                         'FormatWidth': 1080, 'FormatHeight': 1920,
                         'ExportAudio': False, 'MarkIn': 90000, 'MarkOut': 90490,
                         'AudioCodec': 'lpcm', 'AudioBitDepth': 24}
        self.presets, self.jobs, self.counter = {}, {}, 0
        self.marks = {}  # no In/Out marks: Deliver renders the whole timeline
        self.delete_job_ok, self.delete_preset_ok = True, True

    def GetCurrentTimeline(self): return FakeTimeline(self)
    def DeleteRenderPreset(self, name):
        if self.delete_preset_ok: self.presets.pop(name, None)
        return self.delete_preset_ok

    def GetCurrentRenderFormatAndCodec(self):
        if self.hide_codec and self.fc['codec'] == 'H265':
            return {'format': self.fc['format'], 'codec': ''}
        return dict(self.fc)

    def SetCurrentRenderFormatAndCodec(self, fmt, codec):
        self.fc = {'format': fmt, 'codec': codec}
        if fmt == 'mp4':
            self.settings.update(AudioCodec='aac', AudioBitDepth=32)
        return True

    def GetRenderCodecs(self, fmt):
        return {'H.264': 'H264', 'H.265': 'H265'} if fmt == 'mp4' else {'Apple ProRes 422 HQ': 'ProRes422HQ'}

    def GetCurrentRenderMode(self): return self.mode
    def SetCurrentRenderMode(self, mode): self.mode = mode; return True

    def SetRenderSettings(self, settings):
        if 'CustomName' in settings:
            self.settings['Name'] = settings['CustomName']  # the token is lost for good
        self.settings.update({k: v for k, v in settings.items() if k not in ('CustomName', 'SelectAllFrames')})
        # The render range is the timeline's In/Out marks, as in Resolve.
        if settings.get('SelectAllFrames') is True:
            self.marks = {}
            self.settings.update(MarkIn=90000, MarkOut=90490)
        elif 'MarkIn' in settings:
            mark = {'in': settings['MarkIn'] - 90000, 'out': settings['MarkOut'] - 90000}
            self.marks = {'video': dict(mark), 'audio': dict(mark)}
        return True

    def AddRenderJob(self):
        self.counter += 1
        s = self.settings
        job = {'JobId': str(self.counter), 'TargetDir': s['TargetDir'], 'OutputFilename': s['Name'] + '.' + self.fc['format'],
               'MarkIn': s['MarkIn'], 'MarkOut': s['MarkOut'], 'IsExportVideo': s['ExportVideo'],
               'IsExportAudio': s['ExportAudio'], 'AudioCodec': s['AudioCodec'], 'AudioBitDepth': s['AudioBitDepth'],
               'VideoCodec': CODEC_NAMES[self.fc['codec']], 'FormatWidth': s['FormatWidth'], 'FormatHeight': s['FormatHeight']}
        self.jobs[job['JobId']] = job
        return job['JobId']

    def GetRenderJobList(self): return copy.deepcopy(list(self.jobs.values()))
    def DeleteRenderJob(self, job_id):
        if self.delete_job_ok: self.jobs.pop(job_id, None)
        return self.delete_job_ok

    def SaveAsNewRenderPreset(self, name):
        self.presets[name] = (copy.deepcopy(self.settings), dict(self.fc)); return True

    def LoadRenderPreset(self, name):
        if name not in self.presets:
            return False
        keep = {k: self.settings[k] for k in ('AudioCodec', 'AudioBitDepth', 'Name', 'FormatWidth', 'FormatHeight',
                                              'MarkIn', 'MarkOut')}
        fc = dict(self.fc)
        self.settings, self.fc = copy.deepcopy(self.presets[name])
        self.settings.update(keep)
        if self.hide_codec and self.fc['codec'] == 'H265':
            self.fc = fc
        return True


def simulate_export(ex, project):
    """The changes export() makes before rendering, followed by the restore."""
    snap = ex.snapshot(project)
    project.SaveAsNewRenderPreset('__backup')
    if snap['format_codec']['format'] != 'mp4':
        project.SetCurrentRenderFormatAndCodec('mp4', 'H264')
    project.SetRenderSettings({'TargetDir': '/tmp/ai-review-x', 'ExportVideo': True, 'ExportAudio': True,
                               'SelectAllFrames': False, 'MarkIn': 90010, 'MarkOut': 90300})
    return snap, ex.restore(project, snap, '__backup')


def test_fixed_size_is_restored_after_exporting_at_timeline_size(ex):
    project = FakeProject()
    project.settings.update(FormatWidth=720, FormatHeight=1280)
    snap = ex.snapshot(project)
    project.SaveAsNewRenderPreset('__backup')
    project.SetRenderSettings({'FormatWidth': 1080, 'FormatHeight': 1920})
    assert ex.restore(project, snap, '__backup') == ['FormatHeight', 'FormatWidth']  # a preset doesn't restore size
    assert ex.restore(project, snap, '__backup', size_changed=True) == []
    assert (project.settings['FormatWidth'], project.settings['FormatHeight']) == (720, 1280)


def test_whole_timeline_stays_whole_timeline(ex):
    project = FakeProject()
    snap, problems = simulate_export(ex, project)
    assert snap['whole_timeline'] and problems == []
    assert project.marks == {}  # no fixed In/Out range left behind


def test_existing_marks_come_back(ex):
    project = FakeProject()
    project.SetRenderSettings({'SelectAllFrames': False, 'MarkIn': 90020, 'MarkOut': 90200})
    before = copy.deepcopy(project.marks)
    snap, problems = simulate_export(ex, project)
    assert not snap['whole_timeline'] and problems == []
    assert project.marks == before


def test_snapshot_job_that_cannot_be_deleted_stops(ex):
    project = FakeProject()
    project.delete_job_ok = False
    with pytest.raises(ex.Stop, match='render queue'):
        ex.snapshot(project)


def test_cleanup_reports_a_preset_it_could_not_remove(ex, tmp_path):
    project = FakeProject()
    snap = ex.snapshot(project)
    project.SaveAsNewRenderPreset('__backup')
    project.delete_preset_ok = False
    notes = ex.cleanup(project, snap, '__backup', False, None, tmp_path / 'gone', False)
    assert any('__backup' in n and 'could not be removed' in n for n in notes)


def test_problem_report_names_the_original_value(ex):
    project = FakeProject()
    snap = ex.snapshot(project)
    assert 'AudioCodec (should be lpcm)' in ex.describe(['AudioCodec'], snap)


def test_prores_with_lpcm_is_restored_exactly(ex):
    project = FakeProject()
    before = copy.deepcopy(project.settings), dict(project.fc)
    snap, problems = simulate_export(ex, project)
    assert problems == []
    assert (project.settings, project.fc) == before
    assert project.jobs == {}


def test_codec_reported_empty_is_restored_by_name(ex):
    project = FakeProject('mp4', 'H265', hide_codec=True)
    snap, problems = simulate_export(ex, project)
    assert snap['format_codec'] == {'format': 'mp4', 'codec': 'H265'}
    assert problems == []
    assert project.fc == {'format': 'mp4', 'codec': 'H265'}


def test_file_name_is_never_touched(ex):
    project = FakeProject()
    simulate_export(ex, project)
    assert project.settings['Name'] == 'Timeline Name token'


def test_unknown_codec_stops_before_any_change(ex):
    project = FakeProject('mp4', 'H265', hide_codec=True)
    project.GetRenderCodecs = lambda fmt: {}
    with pytest.raises(ex.Stop):
        ex.snapshot(project)
    assert project.presets == {} and project.jobs == {}


def test_restore_reports_what_did_not_come_back(ex):
    project = FakeProject()
    snap = ex.snapshot(project)
    project.SaveAsNewRenderPreset('__backup')
    project.settings['TargetDir'] = '/somewhere/else'
    project.LoadRenderPreset = lambda name: True  # Resolve accepts both calls but changes nothing
    project.SetRenderSettings = lambda settings: True
    assert 'TargetDir' in ex.restore(project, snap, '__backup')


def test_cleanup_removes_only_its_own_partial_file(ex, tmp_path):
    project = FakeProject()
    snap = ex.snapshot(project)
    project.SaveAsNewRenderPreset('__backup')
    work = tmp_path / 'ai-review-x'
    work.mkdir()
    (work / 'Export test.mp4').write_bytes(b'partial')
    assert ex.cleanup(project, snap, '__backup', False, None, work, False, 'Export test.mp4') == []
    assert not work.exists()
    work.mkdir()
    (work / 'someone else.txt').write_text('keep')
    notes = ex.cleanup(project, snap, '__backup', False, None, work, False, 'Export test.mp4')
    assert (work / 'someone else.txt').exists() and any('left behind' in n for n in notes)
