"""
Shared review library for review dispatch scripts.

Contains perspective metadata, persona loading, filename sanitization, and
result persistence logic used by both review-bedrock.py (Converse API)
and review-cli.py (claude -p subprocess).
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Perspective metadata: maps focus keys to persona filenames.
# Persona content is loaded at runtime from .md files in the SDD personas
# directory -- the same files ai-dev's brainstorm/swarm use.
# ---------------------------------------------------------------------------

PERSPECTIVE_KEYS = frozenset({
    'security-reviewer', 'architect', 'chief-architect', 'ops-reviewer',
    'chief-programmer', 'devils-advocate', 'testability-reviewer',
    'simplifier', 'user-advocate', 'api-designer', 'critic',
    'requirements-analyst', 'strategist', 'delivery-manager', 'analyst',
})

# Short aliases for --focus convenience. Maps alias -> canonical key.
FOCUS_ALIASES = {
    'security':      'security-reviewer',
    'architecture':  'architect',
    'system-design': 'chief-architect',
    'ops':           'ops-reviewer',
    'code-quality':  'chief-programmer',
    'testing':       'testability-reviewer',
    'requirements':  'requirements-analyst',
    'strategy':      'strategist',
    'delivery':      'delivery-manager',
    'analysis':      'analyst',
}

PACKS = {
    'quick': ['security-reviewer', 'chief-programmer', 'devils-advocate', 'critic'],
    'standard': ['security-reviewer', 'architect', 'chief-programmer', 'ops-reviewer',
                 'devils-advocate', 'testability-reviewer', 'requirements-analyst'],
    'deep': ['security-reviewer', 'architect', 'chief-architect', 'chief-programmer',
             'ops-reviewer', 'devils-advocate', 'testability-reviewer', 'simplifier',
             'user-advocate', 'api-designer', 'critic', 'requirements-analyst'],
}

PERSONAS_NOT_FOUND_ERROR = (
    "Required personas directory not found. This is likely because:\n"
    "\n"
    "  1. Your devcontainer is not using the standard-concurrent profile "
    "(or one of its derivatives) which includes the SDD skill with persona "
    "definitions, OR\n"
    "  2. The personas have been moved from the expected location: "
    ".claude/skills/spec-driven-development/references/personas/\n"
    "\n"
    "To proceed, provide your own persona text via the --persona flag:\n"
    "  <dispatch-script> --focus <key> "
    "--persona 'You are a security engineer...'\n"
    "\n"
    "Or reference a persona file in your /review prompt and Claude will "
    "read it and pass the content."
)

# Claude model family prefixes -- used to identify Claude models for engine
# routing (CLI engine vs Converse engine).  The `claude` CLI accepts bare
# aliases (opus, sonnet, haiku), versioned names (opus-4.6), or full IDs
# (claude-opus-4-6) -- no translation needed, just pass through.
CLAUDE_MODEL_PREFIXES = ('opus', 'sonnet', 'haiku', 'claude-')


# ---------------------------------------------------------------------------
# Subprocess environment allowlist
# ---------------------------------------------------------------------------
# SECURITY: When spawning `claude -p` subprocesses, we must NOT propagate the
# full parent environment. The parent shell typically contains credentials for
# Atlassian, Artifactory, GitHub, TeamCity, and other services that the review
# subprocess has no business accessing.
#
# This allowlist defines the ONLY environment variables (or prefixes) that are
# copied to subprocess environments. Everything else is dropped.
#
# To add a new variable: add it here AND document WHY the subprocess needs it.
# Do not add secrets or credentials for non-AWS services.
#
# +-------------------------+----------------------------------------------+
# | Variable / prefix       | Why the subprocess needs it                  |
# +-------------------------+----------------------------------------------+
# | PATH                    | Find the `claude` binary                     |
# | HOME                    | ~/.claude/settings.json, ~/.aws/ config      |
# | TMPDIR, TEMP, TMP       | Temp file creation                           |
# | LANG, LC_ALL, LANGUAGE  | Encoding / locale                            |
# | TERM                    | Terminal capability detection                 |
# | SHELL                   | Subprocess shell resolution                  |
# | AWS_*                   | Bedrock auth (creds, region, profile, SSO)   |
# | CLAUDE_CODE_*           | Claude Code config (USE_BEDROCK, telemetry)  |
# | CLAUDECODE              | Claude Code detection flag                   |
# | NVM_*                   | Node version manager (claude is a node app)  |
# | NODE_EXTRA_CA_CERTS     | Corporate CA certificate chain               |
# | WSROOT, WORKSPACE_ROOT  | Workspace context for file resolution        |
# | HTTPS_PROXY, HTTP_PROXY | Corporate proxy configuration                |
# | NO_PROXY                | Proxy bypass list                            |
# | SSL_CERT_FILE           | Custom SSL certificate bundle                |
# | REQUESTS_CA_BUNDLE      | Python requests CA bundle (boto3)            |
# | AWS_CA_BUNDLE           | AWS SDK CA bundle                            |
# +-------------------------+----------------------------------------------+

# Exact variable names to copy
SUBPROCESS_ENV_ALLOWLIST_EXACT = frozenset({
    'PATH',
    'HOME',
    'TMPDIR', 'TEMP', 'TMP',
    'LANG', 'LC_ALL', 'LANGUAGE',
    'TERM',
    'SHELL',
    'CLAUDECODE',
    'NODE_EXTRA_CA_CERTS',
    'WSROOT', 'WORKSPACE_ROOT',
    'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY',
    'https_proxy', 'http_proxy', 'no_proxy',
    'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'AWS_CA_BUNDLE',
})

# Prefixes: any variable starting with these is copied
SUBPROCESS_ENV_ALLOWLIST_PREFIXES = (
    'AWS_',
    'CLAUDE_CODE_',
    'NVM_',
)


def build_subprocess_env(region=None, profile=None):
    """Build a filtered environment dict for claude -p subprocesses.

    Copies ONLY allowlisted variables from the parent environment, then
    applies Bedrock and optional AWS overrides. This prevents leaking
    credentials for non-AWS services (Atlassian, Artifactory, GitHub,
    TeamCity, etc.) into review subprocesses.

    When a profile is specified, inherited static AWS credentials
    (AWS_ACCESS_KEY_ID, etc.) are stripped so the SDK actually uses the
    profile. Without this, the parent Claude Code session's credentials
    take precedence in the SDK credential chain, causing the subprocess
    to authenticate as the wrong identity and hang or fail.

    See SUBPROCESS_ENV_ALLOWLIST_EXACT and SUBPROCESS_ENV_ALLOWLIST_PREFIXES
    for the full allowlist and rationale.

    Args:
        region: AWS region override (sets AWS_REGION)
        profile: AWS profile override (sets AWS_PROFILE)

    Returns:
        dict: Filtered environment variables for subprocess
    """
    env = {}
    for key, value in os.environ.items():
        if key in SUBPROCESS_ENV_ALLOWLIST_EXACT:
            env[key] = value
        elif key.startswith(SUBPROCESS_ENV_ALLOWLIST_PREFIXES):
            env[key] = value

    # Strip empty AWS_PROFILE -- boto3 and claude -p treat '' as a literal
    # profile name and fail with ProfileNotFound. Removing it lets the
    # credential chain fall through to bearer token / SSO / IAM role.
    if env.get('AWS_PROFILE', '').strip() == '':
        env.pop('AWS_PROFILE', None)

    # Always set Bedrock mode
    env['CLAUDE_CODE_USE_BEDROCK'] = '1'

    if profile:
        env['AWS_PROFILE'] = profile
        # Static creds from the parent session override the profile in the
        # SDK credential chain. Remove them so the profile is actually used.
        for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
                    'AWS_SESSION_TOKEN', 'AWS_SECURITY_TOKEN'):
            env.pop(key, None)

    if region:
        env['AWS_REGION'] = region

    return env


# ---------------------------------------------------------------------------
# Persona loading
# ---------------------------------------------------------------------------

def find_personas_dir(start_path=None):
    """Locate the SDD personas directory by walking up from a starting path.

    Convention path: .claude/skills/spec-driven-development/references/personas/
    The script may live in a sub-package (e.g., review/.claude/scripts/) or
    at the repo root (.claude/scripts/). Walk up to 10 levels looking for a
    .claude/ directory that contains the personas path.

    Args:
        start_path: Starting directory for the walk. Defaults to this file's
                    parent directory.

    Returns:
        Path or None: Resolved personas directory, or None if not found.
    """
    personas_rel = Path('skills') / 'spec-driven-development' / 'references' / 'personas'
    current = Path(start_path).resolve() if start_path else Path(__file__).resolve().parent
    for _ in range(10):
        if current.name == '.claude':
            candidate = current / personas_rel
            if candidate.is_dir():
                return candidate
        candidate = current / '.claude' / personas_rel
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def parse_persona_file(filepath):
    """Parse a persona .md file with YAML frontmatter.

    Expected format:
        ---
        name: persona-name
        description: One-line description
        model: inherit
        ---

        Full persona body text...

    Args:
        filepath: Path to the .md file

    Returns:
        dict: {'name': str, 'description': str, 'persona': str}
    """
    text = Path(filepath).read_text(encoding='utf-8')
    name = Path(filepath).stem
    description = ''
    persona = text  # fallback: use entire file as persona

    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            persona = parts[2].strip()
            for line in frontmatter.strip().splitlines():
                if line.startswith('name:'):
                    name = line.split(':', 1)[1].strip()
                elif line.startswith('description:'):
                    description = line.split(':', 1)[1].strip()

    return {'name': name, 'description': description, 'persona': persona}


def load_perspectives(start_path=None):
    """Load perspectives by reading persona files from the SDD personas directory.

    Args:
        start_path: Starting directory for persona search. Defaults to this
                    file's parent directory.

    Returns:
        tuple: (perspectives_dict, personas_dir_path_or_None)
            perspectives_dict: {focus_key: {'name', 'description', 'persona'}}
            If personas dir is not found, returns empty dict and None.
    """
    perspectives = {}
    personas_dir = find_personas_dir(start_path)

    if not personas_dir:
        return perspectives, None

    import sys
    for focus_key in sorted(PERSPECTIVE_KEYS):
        filepath = personas_dir / f'{focus_key}.md'
        if filepath.is_file():
            perspectives[focus_key] = parse_persona_file(filepath)
        else:
            print(f"Warning: persona file not found: {filepath}",
                  file=sys.stderr)

    return perspectives, personas_dir


def list_perspectives_json(perspectives, personas_dir):
    """Build the JSON-serializable dict for --list-perspectives output.

    Args:
        perspectives: Dict from load_perspectives() -- {key: {name, description, persona}}
        personas_dir: Path to the personas directory, or None if not found.

    Returns:
        dict: Ready for json.dumps() with perspectives, packs, and optional warning.
    """
    output = {}
    for key, p in perspectives.items():
        output[key] = {'name': p['name'], 'description': p['description']}
    result = {
        'perspectives': output,
        'packs': PACKS,
        'personas_dir': str(personas_dir) if personas_dir else None,
    }
    if not personas_dir:
        result['warning'] = PERSONAS_NOT_FOUND_ERROR
    return result


def resolve_persona(focus, personas, persona_override=None):
    """Resolve the persona text for a review.

    Resolution order:
    1. If persona_override is provided, use it
    2. If focus matches a loaded persona, use it
    3. Raise -- no generic fallback

    Args:
        focus: Focus area key (e.g., 'security')
        personas: Dict of {focus_key: persona_text}
        persona_override: Optional explicit persona text (from --persona)

    Returns:
        str: The resolved persona text

    Raises:
        ValueError: If no persona could be resolved
    """
    if persona_override:
        return persona_override
    if focus in personas:
        return personas[focus]
    raise ValueError(
        f"No persona found for focus '{focus}'. "
        f"Available: {', '.join(sorted(personas.keys()))}. "
        f"Use --persona to provide custom persona text."
    )


# ---------------------------------------------------------------------------
# Stdin context validation
# ---------------------------------------------------------------------------

SHELL_EXPANSION_PATTERNS = [
    '$(cat ', '$(head ', '$(tail ',   # $() command substitution
    '`cat ', '`head ', '`tail ',       # backtick command substitution
    '$(< ',                            # bash shorthand for $(cat )
]
MIN_CONTEXT_BYTES = 200


def validate_stdin_context(context):
    """Validate stdin context for common orchestrator mistakes.

    Checks for:
    1. Unexpanded shell commands -- indicates a single-quoted heredoc
       (<<'DELIM') that suppressed $() expansion.
    2. Suspiciously small context -- a real diff + file list is > 200 bytes.

    Args:
        context: The stdin content (already checked for empty).

    Returns:
        tuple: (ok: bool, error_msg: str or None)
    """
    if len(context) < 500 and any(p in context for p in SHELL_EXPANSION_PATTERNS):
        return False, (
            f'Stdin appears to contain unexpanded shell commands '
            f'({len(context)} bytes). This usually means $(cmd) was used '
            f"inside a single-quoted heredoc (<<'DELIM'), which suppresses "
            f'expansion. Paste context literally or pipe via: '
            f'cat <file> | <script> ...'
        )
    if len(context) < MIN_CONTEXT_BYTES:
        return False, (
            f'Stdin context is only {len(context)} bytes -- too small to be a '
            f'real diff + file list. The assembled context may not have '
            f'been included. Verify the heredoc body or pipe mechanism.'
        )
    return True, None


# ---------------------------------------------------------------------------
# Review prompt builders
# ---------------------------------------------------------------------------

def build_review_prompt(context, target_description):
    """Build the base review prompt from context and target.

    Used by the Converse engine (static context, no tool access).

    Args:
        context: The assembled review context from stdin.
        target_description: What is being reviewed (e.g., "commit abc123").

    Returns:
        str: Assembled review prompt.
    """
    return f"# Code Review: {target_description}\n\n{context}"


def build_review_prompt_with_tools(context, target_description):
    """Build a review prompt with tool-use instructions appended.

    Used by the CLI engine where perspectives have Read/Bash/Glob/Grep/WebFetch access
    and should dynamically explore the codebase beyond the seed context.

    Args:
        context: The assembled seed context from stdin (diff + file list).
        target_description: What is being reviewed (e.g., "commit abc123").

    Returns:
        str: Assembled review prompt with tool-use instructions.
    """
    return (
        build_review_prompt(context, target_description) + "\n\n"
        "## Instructions\n"
        "Review these changes from your perspective. Read each changed file "
        "in full using the Read tool. Use Grep to find callers and importers, "
        "Glob to locate related test files and configs, and Bash for git "
        "history and blame context. Explore beyond the diff when your focus "
        "area requires it."
    )


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------

def sanitize_filename(name):
    """Sanitize a string for safe use in filenames.

    Replaces path separators and traversal patterns with underscores,
    then collapses non-alphanumeric/hyphen/dot runs into single underscores.

    No length cap -- inputs are model aliases and focus keys which are always
    short. A 255-byte filesystem limit breach is theoretically possible but
    extremely unlikely given the controlled input sources.

    Args:
        name: Raw string (e.g. model alias, focus area)

    Returns:
        str: Safe filename component
    """
    safe = name.replace('/', '_').replace('\\', '_').replace('..', '_')
    safe = re.sub(r'[^a-zA-Z0-9._-]', '_', safe)
    safe = re.sub(r'_+', '_', safe).strip('_')
    return safe or 'unknown'


# ---------------------------------------------------------------------------
# Canonical output builders
# ---------------------------------------------------------------------------

def build_success_output(model_alias, model_id, focus, review_content, engine,
                         input_tokens=0, output_tokens=0,
                         cache_read=0, cache_creation=0):
    """Build a canonical success output dict.

    Args:
        model_alias: Model alias used (e.g., 'opus-4.6', 'nova-pro')
        model_id: Resolved model ID
        focus: Focus area key
        review_content: The review markdown text
        engine: 'cli' or 'converse'
        input_tokens: Input token count
        output_tokens: Output token count
        cache_read: Cache read tokens (0 for Converse)
        cache_creation: Cache creation tokens (0 for Converse)

    Returns:
        dict: Canonical success output
    """
    return {
        'model_alias': model_alias,
        'model_id': model_id,
        'focus': focus,
        'review_content': review_content,
        'token_usage': {
            'input': input_tokens,
            'output': output_tokens,
            'cache_read': cache_read,
            'cache_creation': cache_creation,
        },
        'engine': engine,
    }


def build_error_output(model_alias, focus, error, engine):
    """Build a canonical error output dict.

    Args:
        model_alias: Model alias used
        focus: Focus area key
        error: Error message string
        engine: 'cli' or 'converse'

    Returns:
        dict: Canonical error output
    """
    return {
        'error': error,
        'model_alias': model_alias,
        'focus': focus,
        'engine': engine,
    }


# ---------------------------------------------------------------------------
# Result persistence
# ---------------------------------------------------------------------------

def persist_review(reviews_dir, alias, focus, output):
    """Write review content and metadata sidecar to the reviews directory.

    Uses atomic writes (write to .tmp.<pid>, then os.replace) so parallel
    processes never see partial files.

    Args:
        reviews_dir: Path to the reviews directory
        alias: Model alias (e.g. 'nova-pro')
        focus: Focus area key (e.g. 'security')
        output: The full output dict (success or error)
    """
    import sys

    reviews_path = Path(reviews_dir)
    reviews_path.mkdir(parents=True, exist_ok=True)

    safe_alias = sanitize_filename(alias)
    safe_focus = sanitize_filename(focus)
    suffix = f"{safe_alias}-{safe_focus}"
    pid = os.getpid()

    is_error = 'error' in output
    sidecar = {
        'status': 'failed' if is_error else 'completed',
        'model_alias': alias,
        'model_id': output.get('model_id', ''),
        'focus': focus,
        'engine': output.get('engine', 'unknown'),
        'review_file': f"REVIEW-{suffix}.md" if not is_error else None,
        'token_usage': output.get('token_usage'),
        'error': output.get('error'),
        'completed_at': datetime.now(timezone.utc).isoformat(),
    }

    # Write review markdown (only on success)
    if not is_error:
        review_file = reviews_path / f"REVIEW-{suffix}.md"
        tmp_review = reviews_path / f".tmp.{pid}.REVIEW-{suffix}.md"
        try:
            tmp_review.write_text(output['review_content'], encoding='utf-8')
            os.replace(str(tmp_review), str(review_file))
        except OSError as e:
            print(f"Warning: failed to persist review file: {e}", file=sys.stderr)
            tmp_review.unlink(missing_ok=True)

    # Write sidecar JSON (always)
    sidecar_file = reviews_path / f".result-{suffix}.json"
    tmp_sidecar = reviews_path / f".tmp.{pid}.result-{suffix}.json"
    try:
        tmp_sidecar.write_text(json.dumps(sidecar, indent=2), encoding='utf-8')
        os.replace(str(tmp_sidecar), str(sidecar_file))
    except OSError as e:
        print(f"Warning: failed to persist sidecar file: {e}", file=sys.stderr)
        tmp_sidecar.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Claude model detection
# ---------------------------------------------------------------------------

def is_claude_model(alias):
    """Check if a model alias refers to a Claude/Anthropic model.

    Args:
        alias: Model alias (e.g., 'opus-4.6', 'claude-opus-4-6', 'nova-pro')

    Returns:
        bool: True if the alias is a Claude model
    """
    return alias.startswith(CLAUDE_MODEL_PREFIXES)
