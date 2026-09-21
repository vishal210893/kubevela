#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml",
#     "ruamel.yaml",
# ]
# ///

"""
Statusline generator for Claude Code.

Displays: [Model] [profile | container-ver | claude-code-ver | context% | project | ctx spec -> branch status meeting] repo://path
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import yaml
from pathlib import Path

# Find scripts lib directory - try WSROOT first (runtime), then relative paths
def _find_lib():
    wsroot = os.getenv('WSROOT', '')
    if wsroot:
        lib = Path(wsroot) / '.claude' / 'scripts' / 'lib'
        if lib.exists():
            return str(lib)
    # Fallback: relative to this script
    return str(Path(__file__).parent / 'lib')

_lib = _find_lib()
if _lib not in sys.path:
    sys.path.insert(0, _lib)

from devyaml import get as _yaml_get, register_defaults

register_defaults('statusline', {
    'theme': 'dark',
    'show-model': True,
    'show-profile': True,
    'show-container-version': True,
    'show-claude-code-version': True,
    'show-context-percentage': True,
    'show-git-branch': True,
    'show-spec': True,
    'show-project': True,
    'show-context': True,
    'show-path': True,
    'show-path-wsroot-shorthand': True,
    'context-threshold-warning': 30,
    'context-threshold-critical': 60,
})

# ==================== Constants ====================

VERSION_CHECK_URL = "https://ai-coding-sreapp.orange.guidewire.net/image.json"
VERSION_CACHE_FILE = Path.home() / ".container-version-cache.yaml"
VERSION_CACHE_TTL = 43200  # 12 hours

COLOR_SCHEMES = {
    'dark': {
        'mint': '\033[38;2;80;250;123m',
        'cyan': '\033[96m',
        'gold': '\033[38;2;255;215;0m',
        'dim': '\033[90m',
        'sep': '\033[90m',
        'red': '\033[91m',
        'violet': '\033[38;2;200;130;255m',
    },
    'light': {
        'mint': '\033[1;38;2;0;100;0m',
        'cyan': '\033[1;38;2;0;110;110m',
        'gold': '\033[1;38;2;139;69;19m',
        'dim': '\033[38;2;190;190;190m',
        'sep': '\033[38;2;190;190;190m',
        'red': '\033[1;38;2;178;34;34m',
        'violet': '\033[1;38;2;128;0;200m',
    }
}

SUPERSCRIPTS = ['\u2070', '\u00b9', '\u00b2', '\u00b3', '\u2074', '\u2075', '\u2076', '\u2077', '\u2078', '\u2079']
RESET = '\033[0m'

# Git status symbols
SYM_UNCOMMITTED = '\u2737'
SYM_AHEAD = '\u25b2'
SYM_BEHIND = '\u25bc'
SYM_DIVERGED = '\u21c5'
SYM_ARROW = '\u27a3'
SYM_MEETING = '\u25c9'


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


# ==================== Data Gathering ====================

def get_profile_name():
    """Get profile name from $WSROOT/.devcontainer/profile.yaml.

    Strips namespace prefix if present (e.g., 'aidev.aidev' -> 'aidev').
    """
    try:
        wsroot = os.getenv('WSROOT', str(Path.home()))
        path = Path(wsroot) / '.devcontainer' / 'profile.yaml'
        if path.exists():
            with open(path) as f:
                name = yaml.safe_load(f).get('name')
            if name and '.' in name:
                name = name.rsplit('.', 1)[1]
            return name
    except Exception:
        pass
    return None


def get_claude_version():
    """Get Claude Code version from 'claude -v'."""
    try:
        output = subprocess.check_output(
            ['claude', '-v'], text=True, stderr=subprocess.DEVNULL, timeout=2
        ).strip()
        return output.split()[0] if output else None
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
            return url.rstrip('/').rstrip('.git').split('/')[-1].split(':')[-1]
    except Exception:
        pass
    return None


def get_git_info():
    """Get git branch and status. Returns (branch, status_symbol, spec_name)."""
    try:
        # Check if in git repo
        subprocess.check_output(['git', 'rev-parse', '--git-dir'], stderr=subprocess.DEVNULL, timeout=2)

        # Get branch
        try:
            branch = subprocess.check_output(
                ['git', 'symbolic-ref', '--quiet', '--short', 'HEAD'],
                text=True, stderr=subprocess.DEVNULL, timeout=2
            ).strip()
        except Exception:
            branch = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                text=True, stderr=subprocess.DEVNULL, timeout=2
            ).strip()

        if not branch:
            return None, '', None

        # Check uncommitted changes
        has_uncommitted = False
        try:
            subprocess.check_output(['git', 'diff-index', '--quiet', 'HEAD', '--'], stderr=subprocess.DEVNULL, timeout=2)
        except Exception:
            has_uncommitted = True

        # Check ahead/behind (only if no uncommitted)
        ahead, behind = False, False
        if not has_uncommitted:
            try:
                ahead = int(subprocess.check_output(
                    ['git', 'rev-list', '--count', '@{u}..HEAD'],
                    text=True, stderr=subprocess.DEVNULL, timeout=2
                ).strip()) > 0
                behind = int(subprocess.check_output(
                    ['git', 'rev-list', '--count', 'HEAD..@{u}'],
                    text=True, stderr=subprocess.DEVNULL, timeout=2
                ).strip()) > 0
            except Exception:
                ahead = True  # No upstream = needs push

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

        # Get spec association - read from dev.yaml (speclib handles migration lazily)
        spec = None
        repo_name = get_repo_name()
        if repo_name:
            try:
                spec = _yaml_get(f'spec.{repo_name}.branches.{branch}.spec') or None
            except Exception:
                pass
        # Note: migration from v1.4.0 git config is handled by speclib on first access
        # via spec commands. The statusline just reads what's already in dev.yaml.

        return branch, status, spec

    except Exception:
        return None, '', None


def get_branch_contexts(branch):
    """Get context list for current branch from dev.yaml."""
    repo_name = get_repo_name()
    if not repo_name:
        return []
    try:
        value = _yaml_get(f'spec.{repo_name}.branches.{branch}.ctx') or ''
        if value:
            return [c.strip() for c in str(value).split(',') if c.strip() and c.strip() != 'steering']
    except Exception:
        pass
    return []


def get_spec_project(branch=None):
    """Get the current spec project.

    Uses speclib's full 3-tier resolution (with persist-on-fallback) if the spec
    capability is installed, otherwise falls back to direct dev.yaml read.
    """
    try:
        from speclib import get_project
        return get_project(branch)
    except ImportError:
        pass
    # Fallback: direct dev.yaml read (spec capability not installed)
    repo_name = get_repo_name()
    if not repo_name:
        return None
    if branch:
        try:
            value = _yaml_get(f'spec.{repo_name}.branches.{branch}.project')
            if value:
                return str(value)
        except Exception:
            pass
    try:
        value = _yaml_get(f'spec.{repo_name}.project')
        if value:
            return str(value)
    except Exception:
        pass
    return None


def get_active_meeting(branch):
    """Get active meeting for a branch from dev.yaml. Returns (name, meeting_branch) or (None, None)."""
    if not branch:
        return None, None
    repo = get_repo_name()
    if not repo:
        return None, None
    try:
        name = _yaml_get(f'meeting.{repo}.branches.{branch}.meeting-name') or None
    except Exception:
        return None, None
    if not name:
        return None, None
    # meeting_branch is no longer needed (was used for legacy display)
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


def get_segment_config():
    """Get configuration for which segments to display."""
    segments = ['model', 'profile', 'container-version', 'claude-code-version', 'context-percentage', 'project', 'context', 'git-branch', 'spec', 'path']
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

def format_model(model_name, colors):
    """Format model bracket: [Opus 4.5]"""
    return f"{colors['mint']}[{model_name}]{RESET}"


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


def format_context(pct, colors):
    """Format context percentage with color based on usage."""
    pct_int = int(pct)
    warning_threshold = _read_int_config('context-threshold-warning', 30)
    critical_threshold = _read_int_config('context-threshold-critical', 60)

    if pct_int > critical_threshold:
        color = colors['red']
    elif pct_int >= warning_threshold:
        color = colors['gold']
    else:
        color = colors['dim']
    return f"{color}{pct_int}%{RESET}"


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

        # Gather data
        colors = get_colors()
        config = get_segment_config()
        model_name = input_data.get('model', {}).get('display_name', 'Claude')
        context_pct = input_data.get('context_window', {}).get('used_percentage')
        profile = get_profile_name()
        cc_version = get_claude_version()
        container_version = get_container_version()
        version_status = get_version_status(container_version, get_latest_version()) if container_version else ('current', 0)
        branch, git_status, spec = get_git_info()
        contexts = get_branch_contexts(branch) if branch and config.get('context', True) else []
        meeting_name, meeting_branch = get_active_meeting(branch)
        project = get_spec_project(branch) if config.get('project', True) else None
        repo_name = get_repo_name()
        display_path, in_workspace = get_display_path(current_dir)

        # Build info bracket parts: [profile | ver | cc | ctx% | branch-with-project-and-meeting]
        parts = []
        if profile and config['profile']:
            parts.append(f"{colors['dim']}{profile}{RESET}")
        if container_version and config['container-version']:
            parts.append(format_version(container_version, version_status[0], version_status[1], colors))
        if cc_version and config['claude-code-version']:
            parts.append(f"{colors['dim']}{cc_version}{RESET}")
        if context_pct is not None and config['context-percentage']:
            parts.append(format_context(context_pct, colors))
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
