"""
code_risk - Shared risk classification module.

Provides the core classification algorithm used by both the local
`code-risk` command and the CI `harness-code-risk.yaml` workflow.

Usage:
    from code_risk import load_config, classify

    config = load_config('.harness.yaml')
    tier, score, per_file_tiers = classify(
        changed_files=['src/foo.py', 'docs/README.md'],
        config=config,
        line_count=150,
        file_count=2,
    )
"""

import os
import re
import subprocess
from pathlib import Path


TIER_ORDER = ["low", "medium", "high", "critical"]
TIER_RANK = {t: i for i, t in enumerate(TIER_ORDER)}

BASE_SCORES = {
    "critical": 88,
    "high": 63,
    "medium": 38,
    "low": 12,
    "unmatched": 63,
}

SCRIPT_TIER_DELTAS = {
    "critical": 25,
    "high": 10,
    "medium": 0,
    "low": -15,
}

SCORE_TIERS = [
    (80, "critical"),
    (55, "high"),
    (25, "medium"),
    (0, "low"),
]


# --- YAML parsing ---

TIER_NAMES = frozenset({"low", "medium", "high", "critical"})


def _coerce_scalar(v):
    """Coerce a YAML scalar string to int/bool/str."""
    v = v.strip().strip('"').strip("'")
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    try:
        return int(v)
    except ValueError:
        return v


def _parse_tier_line(stripped, container, current_subkey):
    """Apply a child line under a tier dict/list container.

    Returns the (possibly updated) current_subkey.
    """
    if isinstance(container, list):
        if stripped.startswith("- "):
            val = stripped[2:].strip().strip('"').strip("'")
            container.append(val)
        return current_subkey
    # dict
    if stripped.startswith("- "):
        if current_subkey and isinstance(container.get(current_subkey), list):
            val = stripped[2:].strip().strip('"').strip("'")
            container[current_subkey].append(val)
        return current_subkey
    if ":" in stripped:
        k, _, v = stripped.partition(":")
        k = k.strip()
        v = v.strip()
        if v:
            container[k] = _coerce_scalar(v)
            return k
        else:
            container[k] = []
            return k
    return current_subkey


def parse_simple_yaml(text):
    """Parse the subset of YAML used by .harness.yaml (scalars + flat lists or dicts).

    Standard YAML parsers choke on unquoted ** glob patterns.

    Recognises these top-level shapes:
      - Scalar:   key: value
      - List:     key: \n  - item
      - Tier:     low: <list-of-globs> | dict-with-patterns/max-lines/max-files
      - Container: assess-risk: \n  enabled: true \n  categories: \n    low: <tier> \n    ...

    The `assess-risk` parent block nests an `enabled` scalar and a
    `categories:` map holding the four tier sub-blocks. Each nested tier
    supports the same list-or-dict shape as a top-level tier.
    """
    result = {}
    current_key = None
    current_subkey = None
    # When inside `assess-risk.categories:`, track the active sub-tier
    # (e.g. "low") whose body lines (at indent 6) are being collected.
    current_subtier = None
    # True while indented under `assess-risk.categories:` (indent >= 4).
    in_categories = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)

        if indent == 0 and ":" in stripped:
            key_part = stripped.split(":", 1)[0].strip()
            value_part = stripped.split(":", 1)[1].strip()
            current_subkey = None
            current_subtier = None
            in_categories = False
            if value_part in ("|", ">", "|+", "|-", ">+", ">-"):
                current_key = None
                continue
            if value_part and not value_part.startswith("#"):
                result[key_part] = value_part
                current_key = None
                continue
            current_key = key_part
            if current_key in TIER_NAMES:
                result[current_key] = None  # format determined by first content line
            elif current_key == "assess-risk":
                result[current_key] = {}
            else:
                result[current_key] = []
            continue

        if current_key is None:
            continue

        # --- assess-risk: nested container of `enabled` + `categories.<tier>` ---
        if current_key == "assess-risk":
            ar = result[current_key]
            if not isinstance(ar, dict):
                ar = {}
                result[current_key] = ar

            # Indent 2: either `enabled: true`, `categories:`, or (legacy
            # nested) a tier opener like `low:`.
            if indent == 2 and ":" in stripped:
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip()
                current_subkey = None
                if k == "categories":
                    in_categories = True
                    current_subtier = None
                    ar.setdefault("categories", {})
                    continue
                in_categories = False
                if k in TIER_NAMES:
                    current_subtier = k
                    if v and not v.startswith("#"):
                        ar[k] = _coerce_scalar(v)
                        current_subtier = None
                    else:
                        ar[k] = None  # decide list-vs-dict on first child line
                else:
                    current_subtier = None
                    if v and not v.startswith("#"):
                        ar[k] = _coerce_scalar(v)
                    else:
                        ar[k] = []
                continue

            # Inside `categories:` -- indent 4 opens a tier, indent >= 6 is body.
            if in_categories:
                cats = ar.setdefault("categories", {})
                if not isinstance(cats, dict):
                    cats = {}
                    ar["categories"] = cats
                if indent == 4 and ":" in stripped:
                    k, _, v = stripped.partition(":")
                    k = k.strip()
                    v = v.strip()
                    current_subkey = None
                    if k in TIER_NAMES:
                        current_subtier = k
                        if v and not v.startswith("#"):
                            cats[k] = _coerce_scalar(v)
                            current_subtier = None
                        else:
                            cats[k] = None
                    else:
                        current_subtier = None
                    continue
                if current_subtier is not None and indent >= 6:
                    if cats.get(current_subtier) is None:
                        cats[current_subtier] = (
                            [] if stripped.startswith("- ") else {}
                        )
                    current_subkey = _parse_tier_line(
                        stripped, cats[current_subtier], current_subkey
                    )
                continue

            # Legacy nested-direct shape (assess-risk.<tier>) body at indent >= 4.
            if current_subtier is not None:
                if ar.get(current_subtier) is None:
                    ar[current_subtier] = (
                        [] if stripped.startswith("- ") else {}
                    )
                current_subkey = _parse_tier_line(
                    stripped, ar[current_subtier], current_subkey
                )
            continue

        # --- top-level tier (legacy shape) ---
        if current_key in TIER_NAMES:
            if result[current_key] is None:
                result[current_key] = [] if stripped.startswith("- ") else {}
            current_subkey = _parse_tier_line(
                stripped, result[current_key], current_subkey
            )

        elif isinstance(result.get(current_key), list) and stripped.startswith("- "):
            val = stripped[2:].strip().strip('"').strip("'")
            result[current_key].append(val)

    return result


def load_config(path):
    """Load and parse a .harness.yaml file.

    Args:
        path: Path to .harness.yaml file.

    Returns:
        dict: Parsed configuration.

    Raises:
        FileNotFoundError: If the file does not exist.

    Side effects:
        If both the new `assess-risk.categories.<tier>` shape and the
        deprecated top-level `<tier>` shape define the same tier, emits a
        one-shot stderr warning. The new shape wins (see `get_tier_config`).
    """
    import sys as _sys
    with open(path) as f:
        data = parse_simple_yaml(f.read())
    ar = data.get("assess-risk")
    if isinstance(ar, dict):
        cats = ar.get("categories")
        if isinstance(cats, dict):
            clashes = [t for t in TIER_ORDER if t in cats and t in data]
            if clashes:
                print(
                    "[WARN] .harness.yaml defines tier(s) both at top level "
                    "and under assess-risk.categories: "
                    f"{','.join(clashes)}. assess-risk.categories wins; "
                    "remove the top-level entries.",
                    file=_sys.stderr,
                )
    return data


def get_tier_config(data, tier):
    """Read a tier's config dict, preferring the new nested shape.

    Precedence (first match wins):
      1. `assess-risk.categories.<tier>` -- new shape (since harness.ci 1.24.0)
      2. top-level `<tier>`              -- deprecated shape, kept for
                                             backwards compat during the
                                             migration window

    Returns the raw tier value (list of patterns or dict with patterns/
    max-lines/max-files), or an empty list when no config is present.
    """
    ar = data.get("assess-risk") or {}
    if isinstance(ar, dict):
        cats = ar.get("categories")
        if isinstance(cats, dict) and tier in cats:
            val = cats[tier]
            if isinstance(val, (list, dict)):
                return val
    return data.get(tier, [])


# --- Pattern matching ---

def pattern_to_regex(p):
    """Convert a gitignore-style glob to a regex string."""
    has_leading = p.startswith("/")
    inner = p.strip("/")
    anchored = has_leading or ("/" in inner)

    i, parts = 0, []
    while i < len(inner):
        if inner[i: i + 2] == "**":
            i += 2
            if i < len(inner) and inner[i] == "/":
                i += 1
                parts.append("(.*/)?")
            else:
                parts.append(".*")
        elif inner[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif inner[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(inner[i]))
            i += 1

    body = "".join(parts)
    if anchored:
        return "^" + body + "(/|$)"
    else:
        return "(^|/)" + body + "(/|$)"


def build_regex(patterns):
    """Build combined regex from a list of patterns."""
    if not patterns:
        return None
    combined = "|".join(pattern_to_regex(p) for p in patterns)
    return re.compile(combined)


def _build_tier_regexes(config):
    """Build regex matchers for each tier from config."""
    tier_regexes = {}
    for tier in TIER_ORDER:
        patterns = get_tier_config(config, tier)
        if isinstance(patterns, list):
            tier_regexes[tier] = build_regex(patterns)
        elif isinstance(patterns, dict) and "patterns" in patterns:
            tier_regexes[tier] = build_regex(patterns["patterns"])
    return tier_regexes


def _classify_files(files, tier_regexes):
    """Classify each file into a tier. Returns dict of tier -> file list."""
    buckets = {t: [] for t in TIER_ORDER}
    buckets["unmatched"] = []

    for f in files:
        matched = False
        for tier in reversed(TIER_ORDER):
            regex = tier_regexes.get(tier)
            if regex and regex.search(f):
                buckets[tier].append(f)
                matched = True
                break
        if not matched:
            buckets["unmatched"].append(f)

    return buckets


# --- Scoring ---

def _threshold_val(thresholds, key, default):
    """Get a threshold value; "*" means unlimited (None)."""
    val = thresholds.get(key, default)
    if val == "*":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _determine_highest_match(buckets):
    """Determine the highest pattern match from file classification."""
    if buckets.get("critical"):
        return "critical"
    if buckets.get("high"):
        return "high"
    if buckets.get("unmatched"):
        return "unmatched"
    if buckets.get("medium"):
        return "medium"
    if buckets.get("low"):
        return "low"
    return "low"


def _compute_size_pressure(total_lines, total_files, highest_match, config):
    """Stage 2: size pressure 0-12 proportional to threshold utilization."""
    tier_key = highest_match if highest_match != "unmatched" else "high"
    tier_conf = get_tier_config(config, tier_key)

    max_lines = _threshold_val(tier_conf, "max-lines", None) if isinstance(tier_conf, dict) else None
    max_files = _threshold_val(tier_conf, "max-files", None) if isinstance(tier_conf, dict) else None

    pressures = []
    if max_lines is not None and max_lines > 0:
        pressures.append(10 * min(total_lines / max_lines, 1.5))
    if max_files is not None and max_files > 0:
        pressures.append(10 * min(total_files / max_files, 1.5))

    return min(max(pressures) if pressures else 0, 12)


def _compute_script_delta(script_results):
    """Stage 3: sum of script deltas, clamped to [-30, +30]."""
    total = 0
    for sr in script_results:
        result = sr.get("result", "")
        if result in ("abstain", "not found") or result.startswith("error"):
            continue
        if result in SCRIPT_TIER_DELTAS:
            total += SCRIPT_TIER_DELTAS[result]
        else:
            try:
                total += int(result)
            except ValueError:
                pass
    return max(-30, min(30, total))


def _score_to_tier(score):
    """Stage 4: derive tier from final score."""
    for threshold, tier in SCORE_TIERS:
        if score >= threshold:
            return tier
    return "low"


# --- Script execution ---

def run_custom_scripts(config, files, repo_root, pr_number=None):
    """Run custom risk scripts and collect results.

    Scripts may return a tier string (backward compat) or signed integer delta.
    """
    scripts = config.get("scripts", [])
    if not scripts:
        return []

    script_results = []
    env = os.environ.copy()
    env["CHANGED_FILES"] = "\n".join(files)
    env["PR_NUMBER"] = pr_number or ""

    for script in scripts:
        script_path = Path(repo_root) / script
        if not script_path.exists():
            script_results.append({"script": script, "result": "not found"})
            continue

        try:
            result = subprocess.run(
                ["uv", "run", "--quiet", "--script", str(script_path)],
                capture_output=True, text=True, env=env, timeout=30,
            )
            output = result.stdout.strip().splitlines()
            raw = output[0].strip() if output else ""
        except (subprocess.TimeoutExpired, Exception) as e:
            script_results.append({"script": script, "result": f"error: {e}"})
            continue

        if not raw:
            script_results.append({"script": script, "result": "abstain"})
            continue

        if raw in TIER_RANK:
            script_results.append({"script": script, "result": raw})
        else:
            try:
                int(raw)
                script_results.append({"script": script, "result": raw})
            except ValueError:
                script_results.append({"script": script, "result": "abstain"})

    return script_results


# --- Public API ---

def classify(changed_files, config, line_count=0, file_count=0,
             script_results=None):
    """Classify changed files and compute a weighted risk score.

    Args:
        changed_files: List of file paths to classify.
        config: Parsed .harness.yaml configuration dict.
        line_count: Total lines changed (additions + deletions).
        file_count: Total files changed.
        script_results: Pre-computed script results (list of dicts).
            If None, no script delta is applied.

    Returns:
        tuple: (tier, score, per_file_tiers) where:
            - tier: str -- "low", "medium", "high", or "critical"
            - score: int -- 0-100 weighted risk score
            - per_file_tiers: dict[str, str] -- maps each file to its tier
    """
    if not file_count:
        file_count = len(changed_files)

    tier_regexes = _build_tier_regexes(config)
    buckets = _classify_files(changed_files, tier_regexes)

    if script_results is None:
        script_results = []

    highest = _determine_highest_match(buckets)
    base = BASE_SCORES.get(highest, 63)
    pressure = _compute_size_pressure(line_count, file_count, highest, config)
    delta = _compute_script_delta(script_results)

    score = max(0, min(100, round(base + pressure + delta)))
    tier = _score_to_tier(score)

    per_file_tiers = {}
    for t in TIER_ORDER + ["unmatched"]:
        for f in buckets.get(t, []):
            per_file_tiers[f] = t

    return tier, score, per_file_tiers
