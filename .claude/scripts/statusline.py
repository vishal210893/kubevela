#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml",
# ]
# ///

"""
Statusline generator for Claude Code.

Displays: Model [profile / img-ver / cc-ver / ctx% / usage / project/spec -> branch] repo://path

Performance design:
The render path (what Claude Code invokes on every refresh) must be fast and
constant-time. Claude Code debounces statusline updates at 300ms and CANCELS an
in-flight render when a new update triggers, so a slow render means the status
line silently fails to update after that command. The render therefore never
makes a network call or runs `claude -v` synchronously -- it reads only local
files, caches, and git. Slow/external data (Anthropic usage API, container
version endpoint, `claude -v`) is refreshed by a detached background process
(`statusline.py --refresh <target>`) and served from cache on the next render.

- Render NEVER blocks on network/subprocess: usage, container version, and
  Claude Code version are read from cache; when stale, a detached background
  refresher is spawned (guarded so renders don't spawn a storm) and the stale
  value is served immediately.
- uv startup overhead (~60ms) is bypassed after first run: the script records
  its resolved interpreter path (sys.executable, the pyyaml-equipped venv) in a
  runner-cache file; the statusLine bash wrapper execs that interpreter directly
  and only falls back to `uv run --script` when the cache is missing/stale.
- dev.yaml is read ONCE with PyYAML and cached for the process lifetime.
- devyaml/ruamel.yaml is only imported on first run (when statusline section is
  missing) to materialize defaults; subsequent runs pay no import cost.
- 5 git subprocess calls replaced with single git status --porcelain=v2.
- get_repo_name() called once and passed through to avoid repeated git subprocesses.
- The idle-time segment's cache TTL is detected from the session transcript
  (ground truth from the API's own cache_creation events) rather than an
  environment variable. A per-session byte-offset cache means only the first
  render of a session pays a full transcript scan; every render after that
  tails just the newly-written bytes.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import yaml
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
    'display-format': 'compact',
    'version-format': 'compact',
    'model-format': 'compact',
    'show-model': True,
    'show-profile': True,
    'show-profile-version': True,
    'show-container-version': True,
    'show-claude-code-version': True,
    'show-context-percentage': True,
    'show-context-bar': True,
    'show-usage': True,
    'show-git-branch': True,
    'show-spec': True,
    'show-project': True,
    'show-context': True,
    'show-path': True,
    'show-path-wsroot-shorthand': True,
    'usage-cache-ttl': 120,
    'usage-threshold-warning': 50,
    'usage-threshold-critical': 80,
    'show-idle': True,
    'idle-warn-percent': 80,
    # Prompt-cache health (read/creation token ratio). Off by default; the
    # thresholds invert the usage ones -- higher is better, so >= warning is
    # healthy (mint) and below critical is churning (red).
    'show-cache-health': False,
    'cache-health-warning': 90,
    'cache-health-critical': 85,
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

VERSION_CHECK_URL = "https://ai-coding-sreapp.omega2-andromeda.guidewire.net/image.json"
VERSION_CACHE_FILE = Path.home() / ".container-version-cache.yaml"
VERSION_CACHE_TTL = 43200  # 12h: freshness window for a known-good latest version
VERSION_RETRY_TTL = 300    # 5min: min spacing between fetch attempts (negative cache)

CC_VERSION_CACHE_FILE = Path.home() / ".cc-version-cache.yaml"
CC_VERSION_CACHE_TTL = 300  # 5 minutes
CC_REFRESH_GUARD = 60       # min spacing between background cc-version refreshes

USAGE_CREDS_PATH = Path("/home/node/.claude/.credentials.json")
USAGE_CACHE_FILE = Path.home() / ".usage-cache.yaml"
USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_REFRESH_GUARD = 20    # min spacing between background usage refreshes

# Per-session cache for the idle-TTL transcript detector (see
# _detect_cache_ttl_from_transcript): one small file per transcript, storing
# the byte offset already scanned and the TTL last observed there.
IDLE_TTL_CACHE_DIR = (
    Path(os.getenv('XDG_CACHE_HOME') or (Path.home() / '.cache'))
    / 'statusline' / 'idle-ttl'
)

# Per-session cache for the cache-health accumulator: cumulative cache-read and
# cache-creation token sums plus the byte offset already scanned, tailed the
# same way as the idle-TTL detector so a render never re-reads old history.
CACHE_HEALTH_CACHE_DIR = (
    Path(os.getenv('XDG_CACHE_HOME') or (Path.home() / '.cache'))
    / 'statusline' / 'cache-health'
)

# Currency symbol for the spend segment; unknown currencies render with no
# symbol (just the numbers). USD is overwhelmingly the common case.
_CURRENCY_SYMBOLS = {'USD': '$', 'CAD': '$', 'AUD': '$', 'EUR': '\u20ac', 'GBP': '\u00a3'}

# Interpreter runner-cache: lets the statusLine bash wrapper exec the resolved
# venv python directly and skip uv's ~60ms per-invocation startup. Written by
# the render (keyed on this script's mtime); read by the wrapper.
RUNNER_CACHE_FILE = (
    Path(os.getenv('XDG_CACHE_HOME') or (Path.home() / '.cache'))
    / 'statusline' / 'runner'
)

# Targets the background refresher knows how to refetch.
REFRESH_TARGETS = ('usage', 'version', 'cc')

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
MID_DOT_SEP = ' \u00b7 '

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
    SYM_SUP_PLUS = '\u207a'
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
    SYM_SUP_PLUS = '+'

# Version-check status markers (ASCII -- identical on all platforms)
SYM_UNKNOWN = '?'   # version check could not complete (fail-visible)
SYM_BLOCKED = '!'   # running a version flagged in blocked_versions


# ==================== Cache Helpers ====================

def _read_cache(path):
    """Read a YAML cache file. Returns a dict; {} on missing/empty/corrupt.

    Guards against an empty or half-written cache file (yaml.safe_load returns
    None or a non-dict), which would otherwise raise AttributeError on .get().
    """
    try:
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_cache(path, data):
    """Atomically write a YAML cache file (temp file + os.replace).

    Atomic replace means a concurrent render never observes a partially written
    cache file (the statusline can run many times per second).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Per-process temp name so concurrent renders never share/clobber the
        # same temp file before the atomic os.replace.
        tmp = Path(str(path) + f'.{os.getpid()}.tmp')
        with open(tmp, 'w') as f:
            yaml.safe_dump(data, f)
        os.replace(str(tmp), str(path))
    except Exception:
        pass


# ==================== Background Refresh ====================
#
# The render path must never block on the network or `claude -v`. Each accessor
# reads its cache; when the data is stale it arms a short per-target guard and
# spawns a detached `statusline.py --refresh <target>` process that performs the
# actual fetch and rewrites the cache. The stale value is served immediately so
# the current render stays fast, and the fresh value appears on a later render.


def _spawn_refresh(target):
    """Spawn a detached background process to refresh one cache target.

    Uses sys.executable (the pyyaml-equipped interpreter that is already running
    this render) so the child never pays uv startup cost and always has pyyaml.
    start_new_session detaches it so it outlives this short-lived render.
    """
    try:
        subprocess.Popen(
            [sys.executable, os.path.realpath(__file__), '--refresh', target],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def _arm_and_spawn(cache_file, cache, target):
    """Record a refresh attempt in the cache and spawn the background refresher.

    Writing refresh_ts before spawning is the spawn-storm guard: subsequent
    renders within the target's guard window see a recent refresh_ts and skip
    spawning, even though the in-flight fetch has not finished yet.
    """
    try:
        updated = dict(cache)
        updated['refresh_ts'] = time.time()
        _write_cache(cache_file, updated)
    except Exception:
        pass
    _spawn_refresh(target)


def _needs_refresh(cache, now, ttl, guard, has_data):
    """Decide whether to spawn a background refresh for a cache.

    Returns True only when the data is not fresh AND no refresh was armed within
    the guard window. Fresh data (has_data and within ttl) never refreshes.
    """
    fresh = has_data and (now - cache.get('timestamp', 0) < ttl)
    if fresh:
        return False
    return (now - cache.get('refresh_ts', 0)) >= guard


def run_refresh(targets):
    """Perform live fetches for the requested targets (background process only).

    This is the only place network calls and `claude -v` happen. It is invoked
    as `statusline.py --refresh <target>...` by _spawn_refresh, never inline.
    """
    if not targets or 'all' in targets:
        targets = list(REFRESH_TARGETS)
    for target in targets:
        try:
            if target == 'usage':
                _fetch_usage_live()
            elif target == 'version':
                _fetch_version_live()
            elif target == 'cc':
                _fetch_cc_version_live()
        except Exception:
            pass


# ==================== Interpreter Runner Cache ====================

def _update_runner_cache():
    """Record this script's mtime + interpreter so the wrapper can skip uv.

    The statusLine bash wrapper reads RUNNER_CACHE_FILE ("<mtime> <python>") and
    execs <python> directly when <mtime> still matches the installed script,
    skipping uv's ~60ms startup. When the script is reinstalled its mtime changes,
    the wrapper falls back to `uv run --script` once, and this rewrites the cache.
    Only writes when the content would change, to avoid per-render disk churn.
    """
    try:
        script = os.path.realpath(__file__)
        mtime = int(os.stat(script).st_mtime)
        line = f"{mtime} {sys.executable}\n"
        try:
            if RUNNER_CACHE_FILE.read_text() == line:
                return
        except Exception:
            pass
        RUNNER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = RUNNER_CACHE_FILE.with_name(f'{RUNNER_CACHE_FILE.name}.{os.getpid()}.tmp')
        tmp.write_text(line)
        os.replace(str(tmp), str(RUNNER_CACHE_FILE))
    except Exception:
        pass


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
    """Return cached Anthropic spend data, refreshing in the background if stale.

    Render-path accessor: NEVER calls the network. Reads the cache and, when the
    data is stale, spawns a detached background refresher (guarded by
    USAGE_REFRESH_GUARD) and returns the stale value immediately. The fresh value
    appears on a later render. Returns the cached {'spend': ..., 'credit': ...}
    dict (each entry may be None), or None when nothing has been cached yet.
    """
    cache_ttl = _read_int_config('usage-cache-ttl', 120)
    cache = _read_cache(USAGE_CACHE_FILE)
    now = time.time()
    has_data = cache.get('data') is not None
    if _needs_refresh(cache, now, cache_ttl, USAGE_REFRESH_GUARD, has_data):
        _arm_and_spawn(USAGE_CACHE_FILE, cache, 'usage')
    return cache.get('data')


def _extract_spend(raw):
    """Pull the usage-based-pricing spend meter out of the usage API response.

    The `spend` object reports money spent beyond the plan (see AGENTS.md
    "Anthropic OAuth usage API"). Returns a dict with the fields format_spend
    needs, or None when spend is absent or disabled (the segment is then
    omitted). Money is carried as minor units + exponent (dollars =
    amount_minor / 10**exponent); the API gives no reset date for spend.
    """
    spend = raw.get('spend') or {}
    if not spend.get('enabled'):
        return None
    used = spend.get('used') or {}
    limit = spend.get('limit') or {}
    return {
        'used_minor': used.get('amount_minor'),
        'used_exponent': used.get('exponent', 2),
        'limit_minor': limit.get('amount_minor'),
        'limit_exponent': limit.get('exponent', 2),
        'currency': used.get('currency') or limit.get('currency') or 'USD',
        'percent': spend.get('percent'),
    }


# Top-level keys in the usage response that are dict-shaped but are NOT
# pre-paid credit pools, so the shape-based pool scan must skip them.
_NON_POOL_KEYS = {'spend', 'extra_usage'}


def _extract_credit(raw):
    """Pick the most relevant active pre-paid credit pool from the usage response.

    Usage draws these pre-paid credits down BEFORE the `spend` overage meter
    moves, so the credit pool is usually the number actually changing. Pools
    appear under opaque per-grant codename keys (e.g. cinder_cove) -- not stable
    field names -- so they're detected by shape: a dict with a positive
    limit_dollars and some used/remaining figure. Returns the non-exhausted pool
    nearest exhaustion, shaped for format_credit, or None when there is none.
    Money is in plain dollars here (not minor units like `spend`).
    """
    pools = []
    for key, val in raw.items():
        if key in _NON_POOL_KEYS or not isinstance(val, dict):
            continue
        limit = val.get('limit_dollars')
        if not isinstance(limit, (int, float)) or limit <= 0:
            continue
        used = val.get('used_dollars')
        remaining = val.get('remaining_dollars')
        if not isinstance(used, (int, float)):
            used = None
        if not isinstance(remaining, (int, float)):
            remaining = None
        if remaining is None and used is None:
            continue
        if used is None:
            used = max(0, limit - remaining)
        if remaining is None:
            remaining = max(0, limit - used)
        pools.append({
            'used': used,
            'remaining': remaining,
            'limit': limit,
            'percent': val.get('utilization'),
        })
    if not pools:
        return None
    active_pools = [pool for pool in pools if pool['remaining'] > 0]
    pool = min(active_pools or pools, key=lambda p: (p['remaining'], p['limit']))
    return {
        'used': pool['used'],
        'limit': pool['limit'],
        'percent': pool['percent'],
        'currency': 'USD',
    }


def _fetch_usage_live():
    """Fetch spend + credit data from the Anthropic usage API and cache it (background).

    Runs only inside `statusline.py --refresh usage`, never on the render path.
    Caches both the usage-based-pricing `spend` meter and the smallest active
    pre-paid credit pool under data.{spend,credit}.
    """
    # Read token
    try:
        if not USAGE_CREDS_PATH.exists():
            return
        with open(USAGE_CREDS_PATH) as f:
            creds = json.load(f)
        token = creds["claudeAiOauth"]["accessToken"]
    except Exception:
        return

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
        _write_cache(USAGE_CACHE_FILE, {
            'data': {'spend': _extract_spend(raw), 'credit': _extract_credit(raw)},
            'timestamp': time.time(),
        })
    except Exception:
        # Leave the existing (stale) cache in place on error.
        pass


def _format_money_pct(used, limit, percent, sym, colors):
    """Render compact money tokens such as '16%/$1k' or '$300'."""
    if limit is None:
        return None
    pct = percent
    if pct is None:
        pct = (used / limit * 100) if limit else 0
    pct_int = int(pct)

    warning = _read_int_config('usage-threshold-warning', 50)
    critical = _read_int_config('usage-threshold-critical', 80)
    color = _threshold_color(pct_int, warning, critical, colors)

    cap = _format_money_cap(limit, sym)
    return f"{color}{pct_int}%/{cap}{RESET}"


def _format_money_cap(value, sym):
    """Format whole-dollar caps compactly: '$1000' -> '$1k', '$300' -> '$300'."""
    dollars = int(round(value))
    if abs(dollars) >= 1000 and dollars % 1000 == 0:
        return f"{sym}{dollars // 1000}k"
    return f"{sym}{dollars}"


def _money_percent(used, limit, percent):
    if percent is not None:
        try:
            return float(percent)
        except (TypeError, ValueError):
            pass
    return used / limit * 100


def format_spend(data, colors):
    """Format the usage-based-pricing spend segment.

    Returns None when there is no spend data, so the segment is simply omitted.
    Money is carried as minor units + exponent (dollars =
    amount_minor / 10**exponent).
    """
    if not data:
        return None
    used_minor = data.get('used_minor')
    limit_minor = data.get('limit_minor')
    if used_minor is None or limit_minor is None:
        return None

    used = used_minor / (10 ** data.get('used_exponent', 2))
    limit = limit_minor / (10 ** data.get('limit_exponent', 2))
    if limit <= 0:
        return None
    sym = _CURRENCY_SYMBOLS.get((data.get('currency') or 'USD').upper(), '')
    cap = _format_money_cap(limit, sym)
    pct = _money_percent(used, limit, data.get('percent'))
    if pct <= 0 or used <= 0:
        return f"{colors['mint']}{cap}{RESET}"
    if pct >= 100 or used >= limit:
        return f"{colors['red']}{cap}{RESET}"
    return _format_money_pct(used, limit, data.get('percent'), sym, colors)


def format_credit(data, colors):
    """Format the pre-paid credit pool segment.

    Credit pools use plain dollars. Active credit renders as '16%/$1k';
    exhausted credit renders as the cap only in red.
    """
    if not data:
        return None
    used = data.get('used')
    limit = data.get('limit')
    if used is None or limit is None:
        return None
    if limit <= 0:
        return None
    sym = _CURRENCY_SYMBOLS.get((data.get('currency') or 'USD').upper(), '')
    cap = _format_money_cap(limit, sym)
    pct = _money_percent(used, limit, data.get('percent'))
    if pct >= 100 or used >= limit:
        return f"{colors['red']}{cap}{RESET}"
    return _format_money_pct(used, limit, data.get('percent'), sym, colors)


def _spend_is_moving(data):
    if not data:
        return False
    used_minor = data.get('used_minor')
    limit_minor = data.get('limit_minor')
    if used_minor is None or limit_minor is None:
        return False
    used = used_minor / (10 ** data.get('used_exponent', 2))
    limit = limit_minor / (10 ** data.get('limit_exponent', 2))
    if limit <= 0:
        return False
    pct = _money_percent(used, limit, data.get('percent'))
    return used > 0 or pct > 0


def format_money_usage(usage_data, colors):
    """Format credit and spend meters as one statusline segment.

    Credit is drawn down before spend, so untouched spend is hidden while credit
    is active. Once spend moves, both meaningful meters are shown with an
    internal middle-dot separator.
    """
    if not usage_data:
        return None
    credit_data = usage_data.get('credit')
    spend_data = usage_data.get('spend')
    credit_str = format_credit(credit_data, colors)
    spend_str = format_spend(spend_data, colors)
    parts = []
    if credit_str:
        parts.append(credit_str)
    if spend_str and (_spend_is_moving(spend_data) or not credit_str):
        parts.append(spend_str)
    return f"{colors['sep']}{MID_DOT_SEP}{RESET}".join(parts) if parts else None


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
    """Return the cached Claude Code version, refreshing in the background if stale.

    Render-path accessor: NEVER runs `claude -v`. The version changes rarely, so a
    stale cached value is fine to display; when the cache is stale a detached
    background refresher is spawned (guarded by CC_REFRESH_GUARD) and the stale
    value is returned. Returns None only before the first successful refresh.
    """
    cache = _read_cache(CC_VERSION_CACHE_FILE)
    now = time.time()
    has_data = bool(cache.get('version'))
    if _needs_refresh(cache, now, CC_VERSION_CACHE_TTL, CC_REFRESH_GUARD, has_data):
        _arm_and_spawn(CC_VERSION_CACHE_FILE, cache, 'cc')
    return cache.get('version')


def _fetch_cc_version_live():
    """Run `claude -v` and write the cache (background only)."""
    try:
        output = subprocess.check_output(
            ['claude', '-v'], text=True, stderr=subprocess.DEVNULL, timeout=2
        ).strip()
        version = output.split()[0] if output else None
        if version:
            _write_cache(CC_VERSION_CACHE_FILE, {'version': version, 'timestamp': time.time()})
    except Exception:
        pass


def get_container_version():
    """Get container version from /etc/container-version.txt."""
    try:
        path = Path('/etc/container-version.txt')
        if path.exists():
            return path.read_text().strip().lstrip('v')
    except Exception:
        pass
    return None


def _version_info_from_cache(cache, checked):
    """Shape a cached entry into the get_version_info() return dict."""
    return {
        'latest': cache.get('version') if checked else None,
        'blocked': cache.get('blocked') or [],
        'warning': cache.get('warning'),
        'checked': checked,
    }


def get_version_info():
    """Return cached container-version metadata, refreshing in the background.

    Render-path accessor: NEVER calls the network. Returns a dict:
      latest  -- last known 'current_version' (str), or None when no check has
                 ever succeeded
      blocked -- list of {version, reason} entries from blocked_versions
      warning -- default_warning_message (str) or None
      checked -- True when 'latest' reflects a real (fresh or stale-but-known)
                 answer; False when no version has ever been fetched

    When the cached version is stale (older than VERSION_CACHE_TTL) or absent, a
    detached background refresher is spawned at most once per VERSION_RETRY_TTL
    (the guard doubles as endpoint back-off: an unreachable endpoint is retried
    no more than every VERSION_RETRY_TTL, never blocking the render).
    """
    cache = _read_cache(VERSION_CACHE_FILE)
    now = time.time()
    have_version = bool(cache.get('version'))
    if _needs_refresh(cache, now, VERSION_CACHE_TTL, VERSION_RETRY_TTL, have_version):
        _arm_and_spawn(VERSION_CACHE_FILE, cache, 'version')
    return _version_info_from_cache(cache, checked=have_version)


def _fetch_version_live():
    """Fetch container-version metadata from the remote and cache it (background).

    curl --max-time gives a hard wall-clock bound (urllib's timeout does not
    cover DNS resolution). On failure the existing (stale) cache is left intact;
    the render's refresh_ts guard provides the retry back-off.
    """
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', '3', '-A', 'statusline/1.0', VERSION_CHECK_URL],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl exit {result.returncode}")
        payload = json.loads(result.stdout)
        version = str(payload.get('current_version') or '').strip().lstrip('v')
        if version:
            _write_cache(VERSION_CACHE_FILE, {
                'version': version,
                'blocked': payload.get('blocked_versions') or [],
                'warning': payload.get('default_warning_message'),
                'timestamp': time.time(),
            })
    except Exception:
        pass


def get_version_status(local, latest):
    """Compare versions. Returns (status, patch_count).

    status is one of:
      'current'      -- up to date, or no local version to compare
      'patch'        -- behind by patch_count patch releases
      'major_minor'  -- behind on major or minor
      'unknown'      -- latest could not be determined (fail-visible)
    """
    if not local:
        return ('current', 0)
    if not latest:
        return ('unknown', 0)
    try:
        def parse(v):
            parts = []
            for seg in str(v).lstrip('v').split('.'):
                m = re.match(r'\d+', seg)
                parts.append(int(m.group()) if m else 0)
            # Normalize to exactly 3 segments (pad short, truncate long) so the
            # comparison is well-defined and a 4th segment can't masquerade as
            # equal-but-behind.
            return (parts + [0, 0, 0])[:3]

        loc = parse(local)
        lat = parse(latest)

        if loc >= lat:
            return ('current', 0)
        if loc[0] < lat[0] or loc[1] < lat[1]:
            return ('major_minor', 0)
        return ('patch', lat[2] - loc[2])
    except Exception:
        return ('unknown', 0)


def _blocked_reason(local, vinfo):
    """Return the block reason if the local version is in blocked_versions.

    Falls back to the endpoint's default_warning_message, then a generic label.
    Returns None when the version is not blocked.
    """
    if not local:
        return None
    try:
        local_norm = str(local).lstrip('v')
        for entry in (vinfo.get('blocked') or []):
            bv = str(entry.get('version', '') or '').lstrip('v')
            if bv and bv == local_norm:
                return entry.get('reason') or vinfo.get('warning') or 'blocked'
    except Exception:
        pass
    return None


def get_repo_name():
    """Get repository name from git remote."""
    try:
        url = subprocess.check_output(
            ['git', '--no-optional-locks', 'config', '--get', 'remote.origin.url'],
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
            ['git', '--no-optional-locks', 'status', '--porcelain=v2', '--branch', '--untracked-files=no'],
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
                        ['git', '--no-optional-locks', 'rev-parse', '--short', 'HEAD'],
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


def _read_bool_config(key, default):
    """Read a statusline config value as a bool."""
    value = _read_statusline_config(key)
    if value is None:
        return default
    return value in ('1', 'true', 'yes', 'on')


def get_display_format():
    """Return 'compact' or 'full' for the statusline visual grammar.

    `display-format` is the current setting. `version-format` is accepted as a
    compatibility alias because the first version of this option only controlled
    version labels.
    """
    value = _read_statusline_config('display-format')
    if value is None:
        value = _read_statusline_config('version-format')
    if value in ('compact', 'full'):
        return value
    return 'compact'


def get_segment_config():
    """Get configuration for which segments to display."""
    segments = ['model', 'profile', 'profile-version', 'container-version', 'claude-code-version', 'context-percentage', 'context-bar', 'idle', 'usage', 'project', 'context', 'git-branch', 'spec', 'path']
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

# Raw model ids like 'claude-fable-5[1m]' or 'claude-opus-4-8' (internal or
# unreleased models have no pretty display name, so the raw id passes through).
# Groups: family, dash-separated version, optional 8-digit date, optional
# bracket suffix (e.g. '[1m]').
_RAW_MODEL_ID_RE = re.compile(
    r'^claude-([a-z]+)-(\d+(?:-\d+)?)(?:-\d{8})?(\[[^\]]+\])?$'
)


def _normalize_raw_model_id(name):
    """Convert a raw model id to 'Family version[suffix]' display form.

    'claude-fable-5[1m]' -> 'Fable 5[1m]', 'claude-opus-4-8' -> 'Opus 4.8',
    'claude-haiku-4-5-20251001' -> 'Haiku 4.5'. Names that don't look like a
    raw id are returned unchanged.
    """
    m = _RAW_MODEL_ID_RE.match(name)
    if not m:
        return name
    family, version, bracket = m.groups()
    return f"{family.capitalize()} {version.replace('-', '.')}{bracket or ''}"


def format_model_display_name(display_name, effort_level=None, compact=False):
    """Decorate the raw Claude Code display_name for the statusline.

    full mode:
      - Replace ' (1M context)' with ' 1M' (e.g. 'Opus 4.7 (1M context)' -> 'Opus 4.7 1M').
      - Append a 3-letter effort abbreviation when effort_level is supported
        (e.g. 'xhigh' -> ' XHI'), producing 'Opus 4.7 1M XHI'.

    compact mode (the default model-format):
      - Same 1M handling, but the 'family version' head is shrunk to a single-letter
        family + dotless version: 'Opus 4.7' -> 'O47', 'Sonnet 4.6' -> 'S46',
        'Haiku 4.7' -> 'H47'. Effort is collapsed to a compact suffix
        (l / m / h / + / ++) glued directly to the preceding token. Final
        shape: 'O47 1M+' (xhigh) or 'O47 1M++' (max).

    Raw model ids (e.g. 'claude-fable-5[1m]' for internal models with no
    pretty display name) are normalized first ('Fable 5[1m]'), so compact
    mode yields 'F5[1m]+' instead of 'claude-fable-5[1m]+'.
    """
    name = _normalize_raw_model_id(display_name or 'Claude').replace(' (1M context)', ' 1M')
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


# Default pricing-tier colors for the model segment, keyed by model family.
# This is DATA, not logic, so it is the single place to update when Anthropic's
# pricing tiers shift -- and it can be overridden per-repo via the
# `statusline.model-cost-colors` config (a family -> color map) so an update
# needs no code change and never silently goes stale. Unknown families fall
# back to mint (cheap) so a new model is not mis-flagged as expensive.
MODEL_COST_COLORS = {
    'haiku': 'mint',      # cheapest tier
    'sonnet': 'mint',     # cheap tier -- the everyday default
    'opus': 'yellow',     # mid / expensive tier -- reserve for specialist use
    'fable': 'red',       # premium tier -- rarely warranted for everyday work
}


def _model_family(display_name):
    """Lowercased model family from a raw or pretty display name
    ('Opus 4.8' / 'claude-opus-4-8' -> 'opus')."""
    norm = _normalize_raw_model_id(display_name or '')
    return norm.strip().split(' ', 1)[0].lower()


def _model_cost_color(display_name, colors):
    """Color for the model segment by pricing tier, or None when cost coloring
    is disabled (the caller then renders mint -- the historical default).

    `statusline.model-cost-colors`:
      * falsy / absent -> disabled (returns None)
      * true           -> the built-in MODEL_COST_COLORS tier map
      * a mapping       -> that map merged over the built-in one
    """
    try:
        cfg = _yaml_get('statusline.model-cost-colors')
    except Exception:
        cfg = None
    if not cfg:
        return None
    tiers = dict(MODEL_COST_COLORS)
    if isinstance(cfg, dict):
        tiers.update({str(k).lower(): str(v) for k, v in cfg.items()})
    name = tiers.get(_model_family(display_name), 'mint')
    return colors.get(name, colors['mint'])


def format_model(model_name, colors, cost_color=None):
    """Format model name: Opus 4.7 1M XHI

    `cost_color` (from `_model_cost_color`) overrides the default mint when
    pricing-tier coloring is enabled -- green (mint) for cheap families,
    yellow for mid, red for premium.
    """
    return f"{cost_color or colors['mint']}{model_name}{RESET}"


def _parse_version_parts(version):
    """Parse a version-like string into (major, minor, patch), or None."""
    try:
        raw_parts = str(version).strip().lstrip('v').split('.')
        parts = []
        for seg in raw_parts[:3]:
            m = re.match(r'\d+', seg)
            if not m:
                return None
            parts.append(int(m.group()))
        if not parts:
            return None
        return (parts + [0, 0, 0])[:3]
    except Exception:
        return None


def format_profile_label(profile, version, compact=True):
    """Format profile + version as 'admin2@27' in compact mode."""
    if not version:
        return profile
    if not compact:
        return f"{profile} {version}"
    parts = _parse_version_parts(version)
    if parts:
        major, minor, patch = parts
        if major == 1:
            label = str(minor)
        else:
            label = f"{major}.{minor}"
        if patch:
            label = f"{label}.{patch}"
        return f"{profile}@{label}"
    return f"{profile}@{version}"


def _compact_patch_label(prefix, version):
    parts = _parse_version_parts(version)
    if parts:
        return f"{prefix}{parts[2]}"
    raw = str(version or '').strip().lstrip('v')
    return f"{prefix}{raw}" if raw else prefix


def format_claude_code_version(version, colors, compact=True):
    """Format Claude Code version as 'cc195' in compact mode."""
    label = _compact_patch_label('cc', version) if compact else version
    return f"{colors['dim']}{label}{RESET}"


def format_version(version, status, count, colors, blocked_reason=None, compact=False):
    """Format container version with indicator.

    blocked_reason (when set) means the running version is flagged in the
    endpoint's blocked_versions and takes precedence over staleness: render a
    red version + '!' marker. status 'unknown' renders a dim '?' so a failed
    check is visibly distinct from confirmed-current.
    """
    label = _compact_patch_label('img', version) if compact else version
    if blocked_reason is not None:
        # Running a blocked version: red version + red marker
        return f"{colors['red']}{label}{SYM_BLOCKED}{RESET}"
    if status == 'unknown':
        # Version check could not complete: dim version + dim '?' (fail-visible)
        return f"{colors['dim']}{label}{SYM_UNKNOWN}{RESET}"
    if status == 'major_minor':
        # Major/minor available: gold version + gold indicator
        return f"{colors['gold']}{label}\u2b06{RESET}"
    elif status == 'patch' and count > 0:
        sup = SUPERSCRIPTS[min(count, 9)]
        # Counts above 9 saturate the single superscript; add '+' so a badly
        # stale container is distinguishable from exactly 9 behind.
        plus = SYM_SUP_PLUS if count > 9 else ''
        if count >= 7:
            # 7+ patches behind: dim version + gold superscript
            return f"{colors['dim']}{label}{RESET}{colors['gold']}{sup}{plus}{RESET}"
        # Patches behind: dim version + dim superscript
        return f"{colors['dim']}{label}{sup}{plus}{RESET}"
    else:
        # Current: dim version
        return f"{colors['dim']}{label}{RESET}"


def _threshold_color(value, warning, critical, colors):
    """Return dim/gold/red color based on value vs warning and critical thresholds."""
    if value > critical:
        return colors['red']
    if value >= warning:
        return colors['gold']
    return colors['dim']


# Built-in default context-color stops -- reproduce today's dim/gold/red
# behavior exactly, so unset config is byte-identical to the historical
# threshold scheme. Non-1M: dim <30 / gold 30-60 / red >60 (upper bounds
# 29/60/100). 1M warns earlier -- dim <15 / gold 15-40 / red >40 (14/40/100) --
# because a given % of a 1M window is ~5x the absolute tokens (and per-turn
# cost) of a 200K window.
DEFAULT_CONTEXT_STOPS = [(29, 'dim'), (60, 'gold'), (100, 'red')]
DEFAULT_CONTEXT_STOPS_1M = [(14, 'dim'), (40, 'gold'), (100, 'red')]


def _read_context_stops(key):
    """Read a context-color palette from dev.yaml, or None when unset/malformed.

    A palette is a list of [upper_percent, color_name] stops; color_name is a
    key in the active color scheme ('mint', 'yellow', 'gold', 'orange', 'red',
    'violet', 'dim', ...). Two keys are read (see `_context_color`):
    `context-colors` (all models) and `context-colors-1m` (1M models, which
    warn earlier since a given % of a 1M window is ~5x the absolute tokens --
    and per-turn cost -- of a 200K window). Returns a threshold-sorted list of
    (int, str) tuples, or None so the caller falls back to the next palette or
    the built-in default.
    """
    try:
        raw = _yaml_get(f'statusline.{key}')
    except Exception:
        return None
    if not isinstance(raw, list):
        return None
    stops = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            thr, name = item[0], item[1]
        elif isinstance(item, dict):
            thr, name = item.get('threshold'), item.get('color')
        else:
            continue
        try:
            thr = int(thr)
        except (TypeError, ValueError):
            continue
        if not name:
            continue
        stops.append((thr, str(name)))
    stops.sort(key=lambda s: s[0])
    return stops or None


def _color_from_stops(pct_int, stops, colors):
    """Pick the color for the first stop whose upper bound covers pct_int.

    Percentages above the last stop use the last stop's color. Unknown color
    names fall back to dim so a config typo degrades gracefully instead of
    raising.
    """
    for threshold, name in stops:
        if pct_int <= threshold:
            return colors.get(name, colors['dim'])
    return colors.get(stops[-1][1], colors['dim'])


def _context_color(pct_int, is_1m, colors):
    """Resolve the context-percentage color from a single stops primitive.

    Context coloring is one thing: an [upper-percent, color-name] palette. A
    "warning/critical threshold pair" is just its special case, so today's
    dim/gold/red behavior is the built-in default -- unset config renders
    byte-identically to the historical scheme.

    Precedence:
      1. 1M model with `context-colors-1m` set -> that palette.
      2. else `context-colors` if set (applies to every model -- "uniform").
      3. else the built-in default stops (1M-aware: 1M warns earlier).
    """
    stops = _read_context_stops('context-colors-1m') if is_1m else None
    if stops is None:
        stops = _read_context_stops('context-colors')
    if stops is None:
        stops = DEFAULT_CONTEXT_STOPS_1M if is_1m else DEFAULT_CONTEXT_STOPS
    return _color_from_stops(pct_int, stops, colors)


def format_context(pct, colors, show_bar=True, is_1m=False, compact=False):
    """Format context percentage with color based on usage.

    Color comes from `_context_color`: a single `[upper-percent, color-name]`
    stops palette (`context-colors`, or `context-colors-1m` for 1M models),
    defaulting to today's dim/gold/red behavior when unset.

    Compact mode renders 'ctx35%' with no bar.
    When show_bar is True, renders a visual bar: @@@@@@@@!! 41%
    When False, renders just the colored percentage: 41%
    """
    pct_int = int(pct)
    color = _context_color(pct_int, is_1m, colors)

    if compact:
        return f"{color}ctx{pct_int}%{RESET}"
    if not show_bar:
        return f"{color}{pct_int}%{RESET}"

    bar_width = 10
    filled = round(pct_int * bar_width / 100)
    empty = bar_width - filled
    bar = SYM_BAR_FILLED * filled + SYM_BAR_EMPTY * empty
    return f"{color}{bar} {pct_int}%{RESET}"


def get_idle_seconds(transcript_path):
    """Return seconds since the transcript file was last written, or None.

    A fast local os.stat() call -- no subprocess, no network -- so it's safe
    on the render path unlike the cached/background-refreshed segments.
    """
    if not transcript_path:
        return None
    try:
        mtime = os.path.getmtime(transcript_path)
    except OSError:
        return None
    return max(0, int(time.time() - mtime))


def format_idle_time(seconds):
    """Render idle seconds as 1h02m / 3m05s / 42s."""
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds}s"


def _idle_ttl_cache_file(transcript_path):
    """Per-session cache file path for the transcript-tailing TTL detector.

    Keyed by a hash of the transcript path rather than the path itself, so the
    filename stays short regardless of path depth. Each session's transcript
    gets its own file because the stored byte offset is only meaningful for
    the one file it was read from.
    """
    digest = hashlib.sha1(str(transcript_path).encode()).hexdigest()[:16]
    return IDLE_TTL_CACHE_DIR / f'{digest}.yaml'


def _cache_ttl_from_creation(creation):
    """Return 3600 or 300 if a cache_creation dict records a non-zero write to
    that TTL bucket, else None.

    A single event can carry both counters at once (different content blocks
    in the same request can carry different cache_control TTLs) -- the
    5-minute bucket is checked first so a mixed write reports the shorter,
    more conservative TTL rather than the longer one.
    """
    if not creation:
        return None
    if creation.get('ephemeral_5m_input_tokens'):
        return 300
    if creation.get('ephemeral_1h_input_tokens'):
        return 3600
    return None


def _extract_ttl_from_transcript_line(line):
    """Return the cache TTL (300/3600) recorded by one transcript JSONL line, or None.

    A cheap substring pre-check skips json.loads for the majority of lines,
    which carry no cache_creation event at all. Sidechain entries (Task/Agent
    subagent turns interleaved into the same transcript file) are skipped --
    a subagent can run under different cache parameters than the main chain,
    and its events would otherwise be able to override the main chain's TTL.
    """
    if '"cache_creation"' not in line:
        return None
    try:
        entry = json.loads(line)
    except (ValueError, json.JSONDecodeError):
        return None
    if entry.get('type') != 'assistant' or entry.get('isSidechain'):
        return None
    usage = (entry.get('message') or {}).get('usage') or {}
    return _cache_ttl_from_creation(usage.get('cache_creation'))


def _scan_transcript_for_ttl(path):
    """One-time forward scan of the whole transcript for its most recent cache TTL.

    Paid once per session -- the first render after a fresh start or a resume
    -- after which _detect_cache_ttl_from_transcript tails from a stored byte
    offset instead of re-reading old history.
    """
    ttl = None
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            for line in f:
                found = _extract_ttl_from_transcript_line(line)
                if found is not None:
                    ttl = found
    except OSError:
        return None
    return ttl


def _scan_transcript_range_for_ttl(path, start, end):
    """Scan only the transcript bytes written since the last render (tailing)."""
    try:
        with open(path, 'rb') as f:
            f.seek(start)
            data = f.read(end - start)
    except OSError:
        return None
    ttl = None
    for line in data.decode('utf-8', errors='ignore').splitlines():
        found = _extract_ttl_from_transcript_line(line)
        if found is not None:
            ttl = found
    return ttl


def _detect_cache_ttl_from_transcript(transcript_path):
    """Return this session's actual prompt-cache TTL (300 or 3600), read as
    ground truth from the transcript's own cache_creation events -- no
    environment variable or config guessing.

    Re-reading a multi-megabyte transcript on every render would violate the
    render-path performance budget (see module docstring), so this caches a
    byte offset per transcript file: the first render of a session pays one
    forward scan of the whole file, and every render after that reads only the
    bytes written since the previous render -- a resumed session's prior
    history is scanned exactly once, not on every refresh.

    Returns None only when no cache-write event has ever been observed (e.g.
    the very first render of a session, before any assistant turn exists).
    """
    if not transcript_path:
        return None
    try:
        size = os.path.getsize(transcript_path)
    except OSError:
        return None

    cache_file = _idle_ttl_cache_file(transcript_path)
    cache = _read_cache(cache_file)
    offset = cache.get('offset')
    ttl = cache.get('ttl_seconds')

    if not isinstance(offset, int) or offset > size:
        # No cache yet, or the file shrank/rotated underneath us (unexpected
        # for an append-only transcript) -- treat as a fresh start.
        offset = 0
        ttl = None

    if offset == 0:
        new_ttl = _scan_transcript_for_ttl(transcript_path)
    elif size > offset:
        new_ttl = _scan_transcript_range_for_ttl(transcript_path, offset, size)
    else:
        new_ttl = None

    if new_ttl is not None:
        ttl = new_ttl

    if size != offset or ttl != cache.get('ttl_seconds'):
        _write_cache(cache_file, {'offset': size, 'ttl_seconds': ttl})

    return ttl


# --- Cache health (prompt-cache read/creation ratio) -------------------------
#
# The optimization guide's headline metric. On a healthy session nearly every
# turn re-reads the whole prior prefix from cache (a ~90% discount) and writes
# only the new delta, so the cumulative read/(read+creation) ratio sits high
# (90%+). When something churns the prefix -- a model switch, an MCP toggle, a
# fast-mode flip -- creation spikes and the ratio falls; below ~85-90% is the
# tell that the cache is not doing its job. Accumulated with the same cheap
# byte-offset tailing as the idle-TTL detector.

def _cache_health_cache_file(transcript_path):
    """Per-session cache file for the cumulative cache-read/creation sums.

    Keyed by a hash of the transcript path (short, path-depth independent); the
    stored offset and sums are only meaningful for their own transcript.
    """
    digest = hashlib.sha1(str(transcript_path).encode()).hexdigest()[:16]
    return CACHE_HEALTH_CACHE_DIR / f'{digest}.yaml'


def _cache_tokens_from_transcript_line(line):
    """Return (read_tokens, creation_tokens) for one JSONL line, or None.

    Mirrors _extract_ttl_from_transcript_line: a cheap substring pre-check skips
    json.loads for lines with no cache-read event, and sidechain (subagent)
    turns are skipped -- a subagent runs its own separate cache, so counting its
    tokens would pollute the main chain's health signal.
    """
    if '"cache_read_input_tokens"' not in line:
        return None
    try:
        entry = json.loads(line)
    except (ValueError, json.JSONDecodeError):
        return None
    if entry.get('type') != 'assistant' or entry.get('isSidechain'):
        return None
    usage = (entry.get('message') or {}).get('usage') or {}
    read = usage.get('cache_read_input_tokens')
    creation = usage.get('cache_creation_input_tokens')
    if read is None and creation is None:
        return None
    return int(read or 0), int(creation or 0)


def _sum_cache_tokens(lines):
    read_sum = creation_sum = 0
    for line in lines:
        found = _cache_tokens_from_transcript_line(line)
        if found is not None:
            read_sum += found[0]
            creation_sum += found[1]
    return read_sum, creation_sum


def _scan_transcript_for_cache_tokens(path):
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            return _sum_cache_tokens(f)
    except OSError:
        return 0, 0


def _scan_transcript_range_for_cache_tokens(path, start, end):
    try:
        with open(path, 'rb') as f:
            f.seek(start)
            data = f.read(end - start)
    except OSError:
        return 0, 0
    return _sum_cache_tokens(data.decode('utf-8', errors='ignore').splitlines())


def _read_cache_health(transcript_path):
    """Return (read_tokens, creation_tokens) accumulated over this session's
    main-chain assistant turns, or None when nothing has been served from cache
    yet.

    Same byte-offset tailing as _detect_cache_ttl_from_transcript: the whole
    file is scanned once, then only the delta since the previous render, so the
    render path stays within its performance budget on a large transcript.
    """
    if not transcript_path:
        return None
    try:
        size = os.path.getsize(transcript_path)
    except OSError:
        return None

    cache_file = _cache_health_cache_file(transcript_path)
    cache = _read_cache(cache_file)
    offset = cache.get('offset')
    read_sum = cache.get('read_tokens')
    creation_sum = cache.get('creation_tokens')

    if (not isinstance(offset, int) or offset > size
            or not isinstance(read_sum, int) or not isinstance(creation_sum, int)):
        # No cache yet, or the file shrank/rotated (unexpected for an
        # append-only transcript) -- rescan from the start.
        offset, read_sum, creation_sum = 0, 0, 0

    if offset == 0:
        read_sum, creation_sum = _scan_transcript_for_cache_tokens(transcript_path)
    elif size > offset:
        delta_read, delta_creation = _scan_transcript_range_for_cache_tokens(
            transcript_path, offset, size)
        read_sum += delta_read
        creation_sum += delta_creation

    if size != offset:
        _write_cache(cache_file, {
            'offset': size, 'read_tokens': read_sum, 'creation_tokens': creation_sum,
        })

    if read_sum <= 0:
        # Nothing has been served from cache yet (cold start / first turn): a
        # ratio here would read a misleading 0%. Hide until caching kicks in.
        return None
    return read_sum, creation_sum


def _cache_health_color(pct_int, warning, critical, colors):
    """Color the cache-health ratio -- higher is better (inverse of usage):
    >= warning -> mint (healthy), >= critical -> gold (slipping), below
    critical -> red (the prefix is churning).
    """
    if pct_int < critical:
        return colors['red']
    if pct_int < warning:
        return colors['gold']
    return colors['mint']


def format_cache_health(tokens, colors):
    """Render the prompt-cache health segment: a dim 'cache' label plus the
    colored cumulative read/(read+creation) percentage. Returns None to omit.
    """
    if not tokens:
        return None
    read_sum, creation_sum = tokens
    total = read_sum + creation_sum
    if total <= 0:
        return None
    pct_int = int(read_sum * 100 / total)
    warning = _read_int_config('cache-health-warning', 90)
    critical = _read_int_config('cache-health-critical', 85)
    color = _cache_health_color(pct_int, warning, critical, colors)
    return f"{colors['dim']}cache {RESET}{color}{pct_int}%{RESET}"


def get_idle_ttl_seconds(transcript_path):
    """Resolve the idle-ttl-seconds threshold used by format_idle.

    An explicit `/statusline:config --set idle-ttl-seconds <n>` override always
    wins. Otherwise, detect the real prompt-cache TTL from this session's own
    transcript (see _detect_cache_ttl_from_transcript). Falls back to 300s
    (5 minutes) only when nothing has been detected yet, e.g. before the first
    assistant turn of a brand-new session.
    """
    override = _read_statusline_config('idle-ttl-seconds')
    if override is not None:
        try:
            return int(override)
        except ValueError:
            pass
    detected = _detect_cache_ttl_from_transcript(transcript_path)
    return detected if detected is not None else 300


def format_idle(seconds, ttl, colors, compact=False):
    """Format idle time, colored to flag a likely-cold prompt cache.

    `ttl` is the resolved idle-ttl-seconds value (see get_idle_ttl_seconds).
    Dim while comfortably within ttl, gold once idle time crosses
    idle-warn-percent of ttl, and red with a trailing SYM_BLOCKED marker once
    idle time reaches ttl (the prompt cache has very likely expired by then).
    """
    warn_pct = _read_int_config('idle-warn-percent', 80)
    warning_threshold = ttl * warn_pct // 100
    idle_str = format_idle_time(seconds)
    label = f"idle{idle_str}" if compact else f"idle {idle_str}"
    if seconds >= ttl:
        return f"{colors['red']}{label}{SYM_BLOCKED}{RESET}"
    color = colors['gold'] if seconds >= warning_threshold else colors['dim']
    return f"{color}{label}{RESET}"


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

        # Record the resolved interpreter so the next render can skip uv startup.
        _update_runner_cache()

        # Load dev.yaml once (cached for this process) and materialize defaults if needed
        _load_dev_yaml()
        _ensure_statusline_materialized()

        # Gather data -- get_repo_name() called once and passed through to avoid
        # repeated git subprocess calls
        colors = get_colors()
        config = get_segment_config()
        display_format = get_display_format()
        compact_display = display_format == 'compact'
        model_format = _read_str_config('model-format', 'compact')
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
        blocked_reason = None
        if container_version:
            version_info = get_version_info()
            version_status = get_version_status(container_version, version_info.get('latest'))
            blocked_reason = _blocked_reason(container_version, version_info)
        else:
            version_status = ('current', 0)
        usage_data = fetch_usage_data() if config.get('usage', True) else None
        repo_name = get_repo_name()
        branch, git_status, spec = get_git_info(repo_name)
        contexts = get_branch_contexts(repo_name, branch) if branch and config.get('context', True) else []
        meeting_name, _ = get_active_meeting(repo_name, branch)
        project = get_spec_project(repo_name, branch) if config.get('project', True) else None
        display_path, in_workspace = get_display_path(current_dir)

        # Build info bracket parts: [profile / img / cc / ctx% / usage / branch]
        parts = []
        if profile and config['profile']:
            profile_text = (
                format_profile_label(profile, profile_version, compact=compact_display)
                if profile_version and config.get('profile-version', True)
                else profile
            )
            parts.append(f"{colors['dim']}{profile_text}{RESET}")
        if container_version and config['container-version']:
            parts.append(format_version(
                container_version, version_status[0], version_status[1],
                colors, blocked_reason, compact=compact_display,
            ))
        if cc_version and config['claude-code-version']:
            parts.append(format_claude_code_version(cc_version, colors, compact=compact_display))
        if context_pct is not None and config['context-percentage']:
            is_1m = '1m' in model_name.lower()
            parts.append(format_context(
                context_pct, colors,
                show_bar=config.get('context-bar', True),
                is_1m=is_1m,
                compact=compact_display,
            ))
        if config.get('idle', True):
            transcript_path = input_data.get('transcript_path')
            idle_seconds = get_idle_seconds(transcript_path)
            if idle_seconds is not None:
                idle_ttl = get_idle_ttl_seconds(transcript_path)
                parts.append(format_idle(idle_seconds, idle_ttl, colors, compact=compact_display))
        if config['usage'] and usage_data:
            usage_str = format_money_usage(usage_data, colors)
            if usage_str:
                parts.append(usage_str)
        if _read_bool_config('show-cache-health', False):
            health = _read_cache_health(input_data.get('transcript_path'))
            health_str = format_cache_health(health, colors)
            if health_str:
                parts.append(health_str)
        if branch and config['git-branch']:
            branch_spec = spec if config.get('spec', True) else None
            parts.append(format_branch(
                branch, git_status, branch_spec, colors, contexts,
                project=project,
                meeting_name=meeting_name,
            ))

        # Assemble statusline
        segment_sep = MID_DOT_SEP if compact_display else ' | '
        info_bracket = f"{colors['sep']}[{RESET}" + f"{colors['sep']}{segment_sep}{RESET}".join(parts) + f"{colors['sep']}]{RESET}" if parts else ""
        path_section = format_path(repo_name, display_path, in_workspace, colors, config.get('path-wsroot-shorthand', False))

        output = []
        if config.get('model', True):
            cost_color = _model_cost_color(
                input_data.get('model', {}).get('display_name'), colors)
            output.append(format_model(model_name, colors, cost_color=cost_color))
        if info_bracket:
            output.append(info_bracket)
        if config.get('path', True):
            output.append(path_section)

        print(f"{RESET}" + " ".join(output))

    except Exception:
        # Fallback on error. Prefer the env var (no subprocess); only fall back
        # to whoami with a hard timeout so a slow NSS/LDAP lookup can't hang the
        # one path whose job is to never blank the line.
        user = os.getenv('USER') or os.getenv('USERNAME')
        if not user:
            try:
                user = subprocess.check_output(['whoami'], text=True, timeout=1).strip()
            except Exception:
                user = 'user'
        print(f"{RESET}\033[92m[Claude]{RESET} \033[96m{user}{RESET} \033[38;2;255;215;0m{os.getcwd()}{RESET}")


if __name__ == "__main__":
    # `--refresh <target>...` is the detached background path that performs the
    # slow/external fetches (usage API, container version, claude -v). Everything
    # else is the render path, which only reads caches and local state.
    if len(sys.argv) > 1 and sys.argv[1] == '--refresh':
        run_refresh(sys.argv[2:])
    else:
        get_statusline()
