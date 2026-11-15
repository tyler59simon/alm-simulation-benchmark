"""Simulated calendar. With `init --clock`, each sprint spans `clock_days_per_sprint` (simkit/config.json, default 14)
simulated days from the run's creation time, so Living Memory's time-based features (review dates, staleness, the
auto-resolve of finished plans) are exercised. Nothing here waits: agent sessions and harness calls are given an offset
from real time (LIVING_MEMORY_CLOCK_OFFSET_SECONDS, honoured by Living Memory only when LIVING_MEMORY_HEADLESS=1) and git
author and committer dates.

Mapping (D = days per sprint, W = working days per sprint in the scenario, start = run creation time):
- sprint s, day d: start + (s-1)*D + (d-1)*floor(D/W) days.
- review step at the end of sprint s: start + s*D - 1 day (the last day before the next sprint starts).
- quizzes, probes, grading and the knowledge-base quiz: start + (N+1)*D days, N = number of sprints (one sprint length
  after the end of the last sprint).
- the end-of-run readout: one day after that, so it sees the activity of the quiz sessions that ran in real time on top of it."""
import re
from datetime import datetime, timedelta, timezone

from .common import config

WORK_KEY = re.compile(r'^s(\d+)(?:d(\d+))?/')
_current = {'at': None}   # simulated time of the phase the harness is in (set once per phase, read by lm() and git())


def enabled(run):
    return bool((getattr(run, 'clock', None) or {}).get('enabled'))


def settings(on, created, cfg=None):
    """The manifest record {enabled, days_per_sprint, start}: the simulated start is the run's creation time."""
    return {'enabled': bool(on), 'days_per_sprint': int((cfg or config()).get('clock_days_per_sprint', 14)), 'start': created}


def start(run):
    return datetime.fromisoformat(run.clock['start'])


def _days(run):
    return int(run.clock['days_per_sprint'])


def day_time(run, sprint, day=1):
    """Simulated start of working day `day` (1-based) of sprint `sprint`; None when the clock is off."""
    if not enabled(run):
        return None
    per_day = _days(run) // max(1, int(getattr(run, 'days', 1)))
    return start(run) + timedelta(days=(sprint - 1) * _days(run) + (day - 1) * per_day)


def review_time(run, sprint):
    if not enabled(run):
        return None
    return start(run) + timedelta(days=sprint * _days(run) - 1)


def final_time(run):
    if not enabled(run):
        return None
    return start(run) + timedelta(days=(int(run.scenario['sprints']) + 1) * _days(run))


def readout_time(run):
    """The end-of-run readout: one day after final_time. Quiz and grading sessions run at final_time plus the real time they
    take (their offset is fixed at launch), so a readout at final_time itself would end before their activity."""
    return final_time(run) + timedelta(days=1) if enabled(run) else None


def session_time(run, key):
    """Simulated start of the session with this state key: s<N>/..., s<N>d<D>/... are working days; anything else
    (quiz, quiz-repo, quiz-kb, grade, probe grading) belongs to the final phase."""
    if not enabled(run):
        return None
    m = WORK_KEY.match(key)
    return day_time(run, int(m[1]), int(m[2] or 1)) if m else final_time(run)


def enter(run, when):
    """Make `when` the simulated time of harness Living Memory and git calls until the next phase (None when the clock is off)."""
    _current['at'] = when if enabled(run) else None


def current():
    return _current['at']


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec='seconds')


def offset_seconds(when, real_now=None):
    return (when - (real_now or datetime.now(timezone.utc))).total_seconds()


def lm_env(when=None, real_now=None):
    """Environment that makes a Living Memory process see `when` (default: the current phase) as now."""
    when = when or _current['at']
    if not when:
        return {}
    return {'LIVING_MEMORY_HEADLESS': '1', 'LIVING_MEMORY_CLOCK_OFFSET_SECONDS': f'{offset_seconds(when, real_now):.3f}'}


def git_env(when=None):
    when = when or _current['at']
    return {'GIT_AUTHOR_DATE': _iso(when), 'GIT_COMMITTER_DATE': _iso(when)} if when else {}


def session_env(when, real_now=None):
    """Environment for an agent session that starts at simulated time `when`; computed at launch."""
    return {**lm_env(when, real_now), **git_env(when)} if when else {}
