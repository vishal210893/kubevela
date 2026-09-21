#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml",
# ]
# ///

"""
Statusline generator for Claude Code.

Displays: [Model] [profile | container-ver | claude-code-ver | context% | usage% ~time | project | ctx spec -> branch status meeting] repo://path

Performance design:
- dev.yaml is read ONCE with PyYAML and cached for the process lifetime
- devyaml/ruamel.yaml is only imported on first run (when statusline section is
  missing) to materialize defaults; subsequent runs pay no import cost (~112ms saved)
- 5 git subprocess calls replaced with single git status --porcelain=v2 (~70ms saved)
- claude -v cached to file with 5-minute TTL (~60ms saved on cache hit)
- get_repo_name() called once and passed through to avoid repeated git subprocesses
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ==================== Dev.yaml fast-path (no ruamel.yaml) ====================

_dev_yaml_data = None  # Process-level cache: populated once per invocation


def _find_lib():
    """Find the scripts lib directory."""
    wsroot = os.getenv('WSROOT', '')
    if wsroot:
        lib = Path(wsroot) / '.claude' / 'scripts' / 'lib'
        if lib.exists():
            return str(lib)
    return str(Path(__file__).parent / 'lib')


_branch_key_fn = None


def _branch_key(branch):
    """Resolve dev.yaml branch key via shared branchkey helper.

    For trunk branches (main/master/develop), the key is clone-scoped
    (e.g. dev2::main). Imports branchkey lazily -- it's a tiny no-dep
    module, but the lazy pattern avoids touching sys.path at startup
    when the statusline doesn't actually need to read spec state.
    """
    global _branch_key_fn
    if _branch_key_fn is None:
        try:
            lib = _find_lib()
            if lib not in sys.path:
                sys.path.insert(0, lib)
            from branchkey import branch_key as _bk
            _branch_key_fn = _bk
        except Exception:
            _branch_key_fn = lambda b: b
    return _branch_key_fn(branch)


def _load_dev_yaml():
    """Load dev.yaml with PyYAML, caching result for this process."""
    global _dev_yaml_data
    if _dev_yaml_data is not None:
        return _dev_yaml_data
    dev_yaml = Path.home() / '.dev' / 'dev.yaml'
    try:
        if dev_yaml.exists():
            with open(str(dev_yaml)) as f:
                _dev_yaml_data = yaml.safe_load(f) or {}
        else:
            _dev_yaml_data = {}
    except Exception:
        _dev_yaml_data = {}
    return _dev_yaml_data


def _yaml_get(dotpath, default=None):
    """Read a value from dev.yaml by dot-separated path (uses process-level cache)."""
    data = _load_dev_yaml()
    parts = dotpath.split('.')
    current = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


_STATUSLINE_DEFAULTS = {
    'theme': 'dark',
    'show-model': True,
    'show-profile': True,
    'show-profile-version': True,
    'show-container-version': True,
    'show-claude-code-version': True,
    'show-context-percentage': True,
    'show-usage': True,
    'show-git-branch': True,
    'show-spec': True,
    'show-project': True,
    'show-context': True,
    'show-path': True,
    'show-path-wsroot-shorthand': True,
    'context-threshold-warning': 30,
    'context-threshold-critical': 60,
    'context-threshold-warning-1m': 15,
    'context-threshold-critical-1m': 40,
    'usage-cache-ttl': 120,
}


def _ensure_statusline_materialized():
    """Write statusline defaults to dev.yaml on first run (lazy devyaml import).

    Only imports devyaml/ruamel.yaml when the statusline section is missing from
    dev.yaml (first run only). All subsequent runs skip this entirely.
    """
    if _yaml_get('statusline') is not None:
        return  # Fast path: section exists, nothing to do
    try:
        lib = _find_lib()
        if lib not in sys.path:
            sys.path.insert(0, lib)
        from devyaml import register_defaults as _reg, get as _dget
        _reg('statusline', _STATUSLINE_DEFAULTS)
        _dget('statusline.theme')  # triggers materialization
        # Reload cache to pick up newly written defaults
        global _dev_yaml_data
        _dev_yaml_data = None
        _load_dev_yaml()
    except Exception:
        pass


# ==================== Constants ====================

VERSION_CHECK_URL = "https://ai-coding-sreapp.orange.guidewire.net/image.json"
VERSION_CACHE_FILE = Path.home() / ".container-version-cache.yaml"
VERSION_CACHE_TTL = 43200  # 12 hours

CC_VERSION_CACHE_FILE = Path.home() / ".cc-version-cache.yaml"
CC_VERSION_CACHE_TTL = 300  # 5 minutes

USAGE_CREDS_PATH = Path("/home/node/.claude/.credentials.json")
USAGE_CACHE_FILE = Path.home() / ".usage-cache.yaml"
USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"

COLOR_SCHEMES = {
    'dark': {
        'mint': '\033[38;2;80;250;123m',
        'cyan': '\033[96m',
        'gold': '\033[38;2;255;215;0m',
        'yellow': '\033[38;2;255;215;0m',
        'orange': '\033[38;2;255;140;0m',
        'dim': '\033[90m',
        'sep': '\033[90m',
        'red': '\033[91m',
        'violet': '\033[38;2;200;130;255m',
    },
    'light': {
        'mint': '\033[1;38;2;0;100;0m',
        'cyan': '\033[1;38;2;0;110;110m',
        'gold': '\033[1;38;2;139;69;19m',
        'yellow': '\033[38;2;160;130;0m',
        'orange': '\033[38;2;200;80;0m',
        'dim': '\033[38;2;190;190;190m',
        'sep': '\033[38;2;190;190;190m',
        'red': '\033[1;38;2;178;34;34m',
        'violet': '\033[1;38;2;128;0;200m',
    }
}

RESET = '\033[0m'

_EFFORT_ABBREV = {
    'low': 'LOW',
    'medium': 'MED',
    'high': 'HI',
    'xhigh': 'XHI',
    'max': 'MAX',
}

# Compact mode uses lowercase first letters, with '+' for xhigh and '++' for max.
# Glued (no space) to the preceding token, so the full segment reads e.g.
# 'O47 1M+' (xhigh) or 'O47 1M++' (max).
_EFFORT_ABBREV_COMPACT = {
    'low': 'l',
    'medium': 'm',
    'high': 'h',
    'xhigh': '+',
    'max': '++',
}

_IS_WINDOWS = sys.platform == 'win32' or os.name == 'nt'

if not _IS_WINDOWS:
    SUPERSCRIPTS = ['\u2070', '\u00b9', '\u00b2', '\u00b3', '\u2074', '\u2075', '\u2076', '\u2077', '\u2078', '\u2079']
    SYM_UNCOMMITTED = '\u2737'
    SYM_AHEAD = '\u25b2'
    SYM_BEHIND = '\u25bc'
    SYM_DIVERGED = '\u21c5'
    SYM_ARROW = '\u27a3'
    SYM_MEETING = '\u25c9'
    SYM_RESET = '\u21bb'
    SYM_BAR_FILLED = '\u2588'
    SYM_BAR_EMPTY = '\u2591'
else:
    SUPERSCRIPTS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
    SYM_UNCOMMITTED = '*'
    SYM_AHEAD = '^'
    SYM_BEHIND = 'v'
    SYM_DIVERGED = '^v'
    SYM_ARROW = '->'
    SYM_MEETING = '@'
    SYM_RESET = '~'
    SYM_BAR_FILLED = '#'
    SYM_BAR_EMPTY = '-'


# ==================== Color Helpers ====================

def detect_theme():
    """Detect terminal theme from dev.yaml or environment."""
    try:
        theme = _yaml_get('statusline.theme')
        if theme and str(theme).lower() in ('dark', 'light'):
            return str(theme).lower()
    except Exception:
        pass
    # Auto-detect from COLORFGBG
    colorfgbg = os.getenv('COLORFGBG', '')
    if colorfgbg:
        try:
            bg_color = int(colorfgbg.split(';')[-1])
            return 'light' if bg_color >= 8 else 'dark'
        except (ValueError, IndexError):
            pass
    return 'dark'


def get_colors():
    """Get color scheme based on theme."""
    return COLOR_SCHEMES[detect_theme()]


# ==================== Usage Data ====================

def fetch_usage_data():
    """Fetch usage data from Anthropic API with caching.

    Returns dict with 'utilization' (float) and 'resets_at' (ISO string) or None.
    """
    cache_ttl = _read_int_config('usage-cache-ttl', 120)

    # Check cache first
    try:
        if USAGE_CACHE_FILE.exists():
            with open(USAGE_CACHE_FILE) as f:
                cache = yaml.safe_load(f)
            age = time.time() - cache.get('timestamp', 0) if cache else float('inf')
            if cache and age < cache_ttl:
                return cache.get('data')
    except Exception:
        pass

    # Read token
    try:
        if not USAGE_CREDS_PATH.exists():
            return None
        with open(USAGE_CREDS_PATH) as f:
            creds = json.load(f)
        token = creds["claudeAiOauth"]["accessToken"]
    except Exception:
        return None

    # Fetch from API via curl (urllib rejects Zscaler's non-critical Basic Constraints)
    # Pass auth header via stdin to avoid token exposure in process listings
    try:
        result = subprocess.run(
            [
                'curl', '-s', '--max-time', '3', '--config', '-',
                '-H', 'anthropic-beta: oauth-2025-04-20',
                '-H', 'Accept: application/json',
                USAGE_API_URL,
            ],
            input=f'header "Authorization: Bearer {token}"',
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl exit {result.returncode}")
        raw = json.loads(result.stdout)

        fh = raw.get('five_hour') or {}
        data = {
            'utilization': fh.get('utilization'),
            'resets_at': fh.get('resets_at'),
        }

        try:
            with open(USAGE_CACHE_FILE, 'w') as f:
                yaml.safe_dump({'data': data, 'timestamp': time.time()}, f)
        except Exception:
            pass

        return data

    except Exception:
        # Return stale cache on error
        try:
            if USAGE_CACHE_FILE.exists():
                with open(USAGE_CACHE_FILE) as f:
                    return yaml.safe_load(f).get('data')
        except Exception:
            pass
        return None


def _format_clock_time(dt):
    """Format a datetime as clock time rounded to nearest 5min: '3pm', '3:30pm', '2:10pm'."""
    local_dt = dt.astimezone()
    m = local_dt.minute
    rounded_m = round(m / 5) * 5
    if rounded_m == 60:
        local_dt = local_dt + timedelta(minutes=(60 - m))
        rounded_m = 0
    h = local_dt.hour % 12 or 12
    ampm = 'am' if local_dt.hour < 12 else 'pm'
    if rounded_m == 0:
        return f"{h}{ampm}"
    return f"{h}:{rounded_m:02d}{ampm}"


def format_usage(data, colors):
    """Format usage segment with projection-based coloring and window timing.

    All times are rounded to the nearest 5 minutes for readability.

    Format: actual%/remaining/endtime [projection%/[exhaustion/]endtime]
    - Base:               19%/4h15m/5pm
    - Projection > 50%:   19%/4h15m 55%/5pm
    - Projection >= 80%:  19%/4h15m 90%/5pm          (gold)
    - Projection >= 100%: 19%/4h15m 155%/3:10pm/5pm  (red)

    The 1st part (actual/remaining/endtime) is always dim.
    The 2nd part (projection info) carries warning/critical coloring.
    Projection suppressed in first 15 min of window (too noisy).
    """
    if not data:
        return None

    util = data.get('utilization')
    resets_at = data.get('resets_at')
    if util is None:
        return None

    util_int = int(util)
    window_sec = 5 * 3600

    # Calculate time remaining, elapsed, and window end time
    time_str = ''
    remaining_sec = 0
    end_time_str = ''
    reset_dt = None
    if resets_at:
        try:
            reset_dt = datetime.fromisoformat(resets_at)
            now = datetime.now(timezone.utc)
            remaining_sec = max(int((reset_dt - now).total_seconds()), 0)
            # Round to nearest 5 minutes for display
            remaining_rounded = round(remaining_sec / 300) * 300
            h, rem = divmod(remaining_rounded, 3600)
            m, _ = divmod(rem, 60)
            parts = []
            if h:
                parts.append(f"{h}h")
            if m:
                parts.append(f"{m}m")
            time_str = ''.join(parts) if parts else '<1m'
            end_time_str = _format_clock_time(reset_dt)
        except Exception:
            pass

    # Projection thresholds (configurable)
    proj_display = _read_int_config('usage-projection-display', 50)
    proj_warning = _read_int_config('usage-projection-warning', 80)
    proj_critical = _read_int_config('usage-projection-critical', 100)
    min_elapsed_sec = 15 * 60

    # Calculate projection (suppressed until 15m into window)
    elapsed_sec = window_sec - remaining_sec
    projection = None
    if elapsed_sec >= min_elapsed_sec and elapsed_sec > 0 and util_int > 0:
        projection = int(util_int * window_sec / elapsed_sec)

    # First part: actual%/remaining (always dim)
    first_part = f"{util_int}%/{time_str}" if time_str else f"{util_int}%"

    # Compute exhaustion time for critical projections
    exhaust_str = ''
    if (projection is not None and projection >= proj_critical
            and elapsed_sec > 0 and 0 < util_int < 100):
        secs_to_100 = elapsed_sec * (100 - util_int) / util_int
        exhaust_dt = now + timedelta(seconds=secs_to_100)
        exhaust_str = _format_clock_time(exhaust_dt)

    # Projection cascade -- only the projection portion ever gets color
    if projection is not None and projection > proj_display:
        # Build projection second part
        if projection >= proj_critical:
            # Critical -- red, include exhaustion time
            if exhaust_str and end_time_str:
                second_part = f"{projection}%/{exhaust_str}/{end_time_str}"
            elif end_time_str:
                second_part = f"{projection}%/{end_time_str}"
            else:
                second_part = f"{projection}%"
            color = colors['red']
        elif projection >= proj_warning:
            # Warning -- gold
            second_part = f"{projection}%/{end_time_str}" if end_time_str else f"{projection}%"
            color = colors['gold']
        else:
            # Above 50% but below warning -- dim for awareness
            second_part = f"{projection}%/{end_time_str}" if end_time_str else f"{projection}%"
            color = colors['dim']
        return f"{colors['dim']}{first_part}{RESET} {color}{second_part}{RESET}"

    # No projection concern -- dim with window end time
    end_suffix = f"/{end_time_str}" if end_time_str else ''
    return f"{colors['dim']}{first_part}{end_suffix}{RESET}"


# ==================== Data Gathering ====================

def get_profile_info():
    """Get profile name and version from $WSROOT/.devcontainer/profile.yaml.

    Strips namespace prefix from name if present (e.g., 'aidev.profile-dev' ->
    'profile-dev'). Returns (name, version) -- either may be None.
    """
    try:
        wsroot = os.getenv('WSROOT', str(Path.home()))
        path = Path(wsroot) / '.devcontainer' / 'profile.yaml'
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            name = data.get('name')
            version = data.get('version')
            if name and '.' in name:
                name = name.rsplit('.', 1)[1]
            return name, (str(version) if version is not None else None)
    except Exception:
        pass
    return None, None


def get_claude_version():
    """Get Claude Code version, with 5-minute file cache."""
    try:
        if CC_VERSION_CACHE_FILE.exists():
            with open(CC_VERSION_CACHE_FILE) as f:
                cache = yaml.safe_load(f)
                if cache and time.time() - cache.get('timestamp', 0) < CC_VERSION_CACHE_TTL:
                    return cache.get('version')
    except Exception:
        pass

    try:
        output = subprocess.check_output(
            ['claude', '-v'], text=True, stderr=subprocess.DEVNULL, timeout=2
        ).strip()
        version = output.split()[0] if output else None
        if version:
            try:
                with open(CC_VERSION_CACHE_FILE, 'w') as f:
                    yaml.safe_dump({'version': version, 'timestamp': time.time()}, f)
            except Exception:
                pass
        return version
    except Exception:
        return None


def get_container_version():
    """Get container version from /etc/container-version.txt."""
    try:
        path = Path('/etc/container-version.txt')
        if path.exists():
            return path.read_text().strip().lstrip('v')
    except Exception:
        pass
    return None


def get_latest_version():
    """Get latest container version from remote (cached 12hr)."""
    try:
        # Check cache
        if VERSION_CACHE_FILE.exists():
            with open(VERSION_CACHE_FILE) as f:
                cache = yaml.safe_load(f)
                if cache and time.time() - cache.get('timestamp', 0) < VERSION_CACHE_TTL:
                    return cache.get('version')

        # Fetch from remote
        req = urllib.request.Request(VERSION_CHECK_URL, headers={'User-Agent': 'statusline/1.0'})
        with urllib.request.urlopen(req, timeout=2) as resp:
            version = json.loads(resp.read().decode()).get('current_version', '').strip().lstrip('v')
            if version:
                with open(VERSION_CACHE_FILE, 'w') as f:
                    yaml.safe_dump({'version': version, 'timestamp': time.time()}, f)
                return version
    except Exception:
        # Return stale cache on error
        try:
            if VERSION_CACHE_FILE.exists():
                with open(VERSION_CACHE_FILE) as f:
                    return yaml.safe_load(f).get('version')
        except Exception:
            pass
    return None


def get_version_status(local, latest):
    """Compare versions. Returns ('current'|'patch'|'major_minor', patch_count)."""
    if not local or not latest:
        return ('current', 0)
    try:
        def parse(v):
            parts = [int(x) for x in v.lstrip('v').split('.')]
            return parts + [0] * (3 - len(parts))

        loc = parse(local)
        lat = parse(latest)

        if loc >= lat:
            return ('current', 0)
        if loc[0] < lat[0] or loc[1] < lat[1]:
            return ('major_minor', 0)
        return ('patch', lat[2] - loc[2])
    except Exception:
        return ('current', 0)


def get_repo_name():
    """Get repository name from git remote."""
    try:
        url = subprocess.check_output(
            ['git', 'config', '--get', 'remote.origin.url'],
            text=True, stderr=subprocess.DEVNULL, timeout=2
        ).strip()
        if url:
            basename = url.rstrip('/').split('/')[-1].split(':')[-1]
            return basename.removesuffix('.git')
    except Exception:
        pass
    return None


def get_git_info(repo_name=None):
    """Get git branch and status using a single git status call.

    Uses git status --porcelain=v2 --branch --untracked-files=no to replace
    five separate subprocess calls (rev-parse, symbolic-ref, diff-index,
    two rev-list calls) with one.
    """
    try:
        result = subprocess.check_output(
            ['git', 'status', '--porcelain=v2', '--branch', '--untracked-files=no'],
            text=True, stderr=subprocess.DEVNULL, timeout=2
        )
    except Exception:
        return None, '', None

    branch = None
    has_upstream = False
    ahead = False
    behind = False
    has_uncommitted = False

    for line in result.splitlines():
        if line.startswith('# branch.head '):
            val = line[14:]
            if val == '(detached)':
                try:
                    branch = subprocess.check_output(
                        ['git', 'rev-parse', '--short', 'HEAD'],
                        text=True, stderr=subprocess.DEVNULL, timeout=2
                    ).strip()
                except Exception:
                    branch = 'HEAD'
            else:
                branch = val
        elif line.startswith('# branch.ab '):
            has_upstream = True
            for part in line[12:].split():
                if part.startswith('+'):
                    ahead = int(part[1:]) > 0
                elif part.startswith('-'):
                    behind = int(part[1:]) > 0
        elif line and not line.startswith('#'):
            has_uncommitted = True

    if not branch:
        return None, '', None

    # No upstream tracking branch = needs push (show ahead indicator)
    if not has_upstream and not has_uncommitted:
        ahead = True

    # Determine status symbol (priority: uncommitted > diverged > ahead > behind)
    if has_uncommitted:
        status = SYM_UNCOMMITTED
    elif ahead and behind:
        status = SYM_DIVERGED
    elif ahead:
        status = SYM_AHEAD
    elif behind:
        status = SYM_BEHIND
    else:
        status = ''

    # Get spec association from cached dev.yaml (clone-scoped for trunk branches)
    spec = None
    if repo_name:
        spec = _yaml_get(f'spec.{repo_name}.branches.{_branch_key(branch)}.spec') or None

    return branch, status, spec


def get_branch_contexts(repo_name, branch):
    """Get context list for current branch from dev.yaml."""
    if not repo_name:
        return []
    try:
        value = _yaml_get(f'spec.{repo_name}.branches.{_branch_key(branch)}.ctx') or ''
        if value:
            return [c.strip() for c in str(value).split(',') if c.strip() and c.strip() != 'steering']
    except Exception:
        pass
    return []


def get_spec_project(repo_name, branch=None):
    """Get the current spec project from cached dev.yaml.

    Uses direct dev.yaml navigation (no speclib/devyaml import) to avoid
    the ruamel.yaml import cost. Implements the same 3-tier resolution as
    speclib (branch-level -> repo-level) without the persist-on-fallback write.
    """
    if not repo_name:
        return None
    if branch:
        value = _yaml_get(f'spec.{repo_name}.branches.{_branch_key(branch)}.project')
        if value:
            return str(value)
    value = _yaml_get(f'spec.{repo_name}.project')
    if value:
        return str(value)
    return None


def get_active_meeting(repo_name, branch):
    """Get active meeting for a branch from dev.yaml. Returns (name, None)."""
    if not branch or not repo_name:
        return None, None
    try:
        name = _yaml_get(f'meeting.{repo_name}.branches.{branch}.meeting-name') or None
    except Exception:
        return None, None
    return name, None


def _read_statusline_config(key):
    """Read a statusline config value from dev.yaml."""
    try:
        value = _yaml_get(f'statusline.{key}')
        if value is not None:
            return str(value).lower()
    except Exception:
        pass
    return None


def _read_int_config(key, default):
    """Read a statusline config value as an integer."""
    value = _read_statusline_config(key)
    if value is not None:
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _read_str_config(key, default):
    """Read a statusline config value as a string."""
    value = _read_statusline_config(key)
    return value if value is not None else default


def get_segment_config():
    """Get configuration for which segments to display."""
    segments = ['model', 'profile', 'profile-version', 'container-version', 'claude-code-version', 'context-percentage', 'context-bar', 'usage', 'project', 'context', 'git-branch', 'spec', 'path']
    config = {}
    for segment in segments:
        value = _read_statusline_config(f'show-{segment}')
        config[segment] = value == 'true' if value is not None else True

    # Read show-path-wsroot-shorthand config
    value = _read_statusline_config('show-path-wsroot-shorthand')
    config['path-wsroot-shorthand'] = value == 'true' if value is not None else True

    return config


def get_display_path(current_dir):
    """Get display path relative to workspace or home."""
    wsroot = os.getenv('WSROOT', str(Path.home()))
    home = str(Path.home())

    if current_dir == wsroot:
        return '', True
    if current_dir.startswith(wsroot + '/'):
        return current_dir[len(wsroot) + 1:], True
    if current_dir == home:
        return '~/', False
    return current_dir.replace(home, '~', 1), False


# ==================== Formatting ====================

def format_model_display_name(display_name, effort_level=None, compact=False):
    """Decorate the raw Claude Code display_name for the statusline.

    full mode (default):
      - Replace ' (1M context)' with ' 1M' (e.g. 'Opus 4.7 (1M context)' -> 'Opus 4.7 1M').
      - Append a 3-letter effort abbreviation when effort_level is supported
        (e.g. 'xhigh' -> ' XHI'), producing 'Opus 4.7 1M XHI'.

    compact mode:
      - Same 1M handling, but the 'family version' head is shrunk to a single-letter
        family + dotless version: 'Opus 4.7' -> 'O47', 'Sonnet 4.6' -> 'S46',
        'Haiku 4.7' -> 'H47'. Effort is collapsed to a compact suffix
        (l / m / h / + / ++) glued directly to the preceding token. Final
        shape: 'O47 1M+' (xhigh) or 'O47 1M++' (max).
    """
    name = (display_name or 'Claude').replace(' (1M context)', ' 1M')
    if compact:
        suffix_1m = ''
        if name.endswith(' 1M'):
            suffix_1m = ' 1M'
            name = name[:-3]
        family, sep, version = name.partition(' ')
        if sep and family:
            name = f"{family[0].upper()}{version.replace('.', '')}"
        name = name + suffix_1m
    abbrev_map = _EFFORT_ABBREV_COMPACT if compact else _EFFORT_ABBREV
    abbrev = abbrev_map.get(effort_level)
    if abbrev:
        sep = '' if compact else ' '
        name = f"{name}{sep}{abbrev}"
    return name


def format_model(model_name, colors):
    """Format model name: Opus 4.7 1M XHI"""
    return f"{colors['mint']}{model_name}{RESET}"


def format_version(version, status, count, colors):
    """Format container version with indicator."""
    if status == 'major_minor':
        # Major/minor available: gold version + gold indicator
        return f"{colors['gold']}{version}\u2b06{RESET}"
    elif status == 'patch' and count > 0:
        sup = SUPERSCRIPTS[min(count, 9)]
        if count >= 7:
            # 7+ patches behind: dim version + gold superscript
            return f"{colors['dim']}{version}{RESET}{colors['gold']}{sup}{RESET}"
        # Patches behind: dim version + dim superscript
        return f"{colors['dim']}{version}{sup}{RESET}"
    else:
        # Current: dim version
        return f"{colors['dim']}{version}{RESET}"


def _threshold_color(value, warning, critical, colors):
    """Return dim/gold/red color based on value vs warning and critical thresholds."""
    if value > critical:
        return colors['red']
    if value >= warning:
        return colors['gold']
    return colors['dim']


def format_context(pct, colors, show_bar=True, is_1m=False):
    """Format context percentage with color based on usage.

    When show_bar is True, renders a visual bar: @@@@@@@@!! 41%
    When False, renders just the colored percentage: 41%
    When is_1m is True, uses the 1M-specific thresholds (lower defaults).
    """
    pct_int = int(pct)
    if is_1m:
        warning_threshold = _read_int_config('context-threshold-warning-1m', 15)
        critical_threshold = _read_int_config('context-threshold-critical-1m', 40)
    else:
        warning_threshold = _read_int_config('context-threshold-warning', 30)
        critical_threshold = _read_int_config('context-threshold-critical', 60)
    color = _threshold_color(pct_int, warning_threshold, critical_threshold, colors)

    if not show_bar:
        return f"{color}{pct_int}%{RESET}"

    bar_width = 10
    filled = round(pct_int * bar_width / 100)
    empty = bar_width - filled
    bar = SYM_BAR_FILLED * filled + SYM_BAR_EMPTY * empty
    return f"{color}{bar} {pct_int}%{RESET}"


def format_branch(branch, status, spec, colors, contexts=None, project=None, meeting_name=None):
    """Format branch section with compact composite format.

    Format: project:spec:ctx1,ctx2 -> branch status * meeting-name
    - No spaces around colons in composite prefix
    - Spec is mint (bright), project and contexts are dim
    - When meeting active: entire segment turns violet, meeting indicator at end
    """
    is_default = branch in ('main', 'master')
    has_indicator = status != ''
    has_meeting = meeting_name is not None

    branch_color = colors['dim'] if is_default and not has_indicator else colors['mint']
    prefix_color = colors['dim']
    spec_color = colors['mint']
    status_color = colors['mint']

    suffix = f" {status_color}{status}{RESET}" if status else ""

    # Build compact composite prefix: project:spec:ctx1,ctx2
    # When spec is absent but project+contexts are present, use double colon:
    # project::ctx (empty string in the spec slot produces the double colon)
    composite_parts = []
    if project:
        composite_parts.append(f"{prefix_color}{project}{RESET}")
    if spec:
        composite_parts.append(f"{spec_color}{spec}{RESET}")
    elif contexts and project:
        # Spec absent: insert empty slot so join produces "project::ctx"
        composite_parts.append("")
    if contexts:
        ctx_str = ",".join(contexts)
        composite_parts.append(f"{prefix_color}{ctx_str}{RESET}")

    colon = f"{prefix_color}:{RESET}"
    composite = colon.join(composite_parts) if composite_parts else ""

    # Meeting indicator: * meeting-name (appended after branch status)
    meeting_suffix = ""
    if has_meeting:
        meeting_suffix = f" {colors['violet']}{SYM_MEETING} {meeting_name}{RESET}"

    # Assemble: composite -> branch status * meeting-name
    if composite:
        if spec:
            arrow = f"{colors['mint']}{SYM_ARROW}{RESET}"
        else:
            arrow = f"{colors['dim']}{SYM_ARROW}{RESET}"
        return f"{composite} {arrow} {branch_color}{branch}{RESET}{suffix}{meeting_suffix}"
    elif has_meeting:
        return f"{branch_color}{branch}{RESET}{suffix}{meeting_suffix}"
    else:
        return f"{branch_color}{branch}{RESET}{suffix}"


def format_path(repo_name, path, in_workspace, colors, use_shorthand=False):
    """Format path section. Repo portion in cyan, rest in gold."""
    wsroot = os.getenv('WSROOT', '')
    if wsroot and path:
        if use_shorthand:
            # Use // prefix when shorthand is enabled
            parts = path.split('/', 1)
            repo_part = parts[0]
            rest = '/' + parts[1] if len(parts) > 1 else ''
            return f"{colors['cyan']}//{RESET}{colors['cyan']}{repo_part}{RESET}{colors['gold']}{rest}{RESET}"
        else:
            # Split path into repo (first segment) and rest
            parts = path.split('/', 1)
            repo_part = parts[0]
            rest = '/' + parts[1] if len(parts) > 1 else ''
            return f"{colors['gold']}{wsroot}/{RESET}{colors['cyan']}{repo_part}{RESET}{colors['gold']}{rest}{RESET}"
    elif wsroot:
        return f"{colors['gold']}{wsroot}{RESET}"
    elif in_workspace:
        return f"{colors['gold']}//{path}{RESET}"
    else:
        return f"{colors['gold']}{path}{RESET}"


# ==================== Main ====================

def get_statusline():
    """Generate and print the statusline."""
    try:
        # Read input
        input_data = json.loads(sys.stdin.read())
        current_dir = input_data.get('workspace', {}).get('current_dir', os.getcwd())

        # Change to current directory for git operations
        try:
            os.chdir(current_dir)
        except Exception:
            pass

        # Load dev.yaml once (cached for this process) and materialize defaults if needed
        _load_dev_yaml()
        _ensure_statusline_materialized()

        # Gather data -- get_repo_name() called once and passed through to avoid
        # repeated git subprocess calls
        colors = get_colors()
        config = get_segment_config()
        model_format = _read_str_config('model-format', 'full')
        compact_model = model_format == 'compact'
        model_name = format_model_display_name(
            input_data.get('model', {}).get('display_name'),
            input_data.get('effort', {}).get('level'),
            compact=compact_model,
        )
        context_pct = input_data.get('context_window', {}).get('used_percentage')
        profile, profile_version = get_profile_info()
        cc_version = get_claude_version()
        container_version = get_container_version()
        version_status = get_version_status(container_version, get_latest_version()) if container_version else ('current', 0)
        usage_data = fetch_usage_data() if config.get('usage', True) else None
        repo_name = get_repo_name()
        branch, git_status, spec = get_git_info(repo_name)
        contexts = get_branch_contexts(repo_name, branch) if branch and config.get('context', True) else []
        meeting_name, _ = get_active_meeting(repo_name, branch)
        project = get_spec_project(repo_name, branch) if config.get('project', True) else None
        display_path, in_workspace = get_display_path(current_dir)

        # Build info bracket parts: [profile | ver | cc | ctx% | branch-with-project-and-meeting]
        parts = []
        if profile and config['profile']:
            profile_text = profile
            if profile_version and config.get('profile-version', True):
                profile_text = f"{profile} {profile_version}"
            parts.append(f"{colors['dim']}{profile_text}{RESET}")
        if container_version and config['container-version']:
            parts.append(format_version(container_version, version_status[0], version_status[1], colors))
        if cc_version and config['claude-code-version']:
            parts.append(f"{colors['dim']}{cc_version}{RESET}")
        if context_pct is not None and config['context-percentage']:
            is_1m = '1M' in model_name
            parts.append(format_context(context_pct, colors, show_bar=config.get('context-bar', True), is_1m=is_1m))
        if config['usage']:
            usage_str = format_usage(usage_data, colors)
            if usage_str:
                parts.append(usage_str)
        if branch and config['git-branch']:
            branch_spec = spec if config.get('spec', True) else None
            parts.append(format_branch(
                branch, git_status, branch_spec, colors, contexts,
                project=project,
                meeting_name=meeting_name,
            ))

        # Assemble statusline
        info_bracket = f"{colors['sep']}[{RESET}" + f"{colors['sep']} | {RESET}".join(parts) + f"{colors['sep']}]{RESET}" if parts else ""
        path_section = format_path(repo_name, display_path, in_workspace, colors, config.get('path-wsroot-shorthand', False))

        output = []
        if config.get('model', True):
            output.append(format_model(model_name, colors))
        if info_bracket:
            output.append(info_bracket)
        if config.get('path', True):
            output.append(path_section)

        print(f"{RESET}" + " ".join(output))

    except Exception:
        # Fallback on error
        try:
            user = subprocess.check_output(['whoami'], text=True).strip()
        except Exception:
            user = os.getenv('USER', 'user')
        print(f"{RESET}\033[92m[Claude]{RESET} \033[96m{user}{RESET} \033[38;2;255;215;0m{os.getcwd()}{RESET}")


if __name__ == "__main__":
    get_statusline()
