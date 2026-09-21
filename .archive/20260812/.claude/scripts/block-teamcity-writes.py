#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
PreToolUse hook: block TeamCity write operations based on TEAMCITY_RO tier.

Tiers:
  TEAMCITY_RO=1     -> block all writes: 30 infra + 15 orchestration (default)
  TEAMCITY_RO=infra -> block infra/admin writes only: 30 commands + API writes
  TEAMCITY_RO=""    -> block nothing (full write access)
  (other values)    -> treated as "1" for defense-in-depth

The teamcity capability sets TEAMCITY_RO=1 via devcontainer remote env
(source: TEAMCITY_RO:-1), so every container gets full write protection
by default. Teams that ship their own build-operation governance (e.g. a
rate-limiter hook) can set TEAMCITY_RO=infra to allow orchestration
commands while keeping infra protection.
"""

import json
import os
import re
import sys

# --- Infra/admin commands (30) ---
# High blast radius, rarely needed by agents. Blocked when TEAMCITY_RO
# is "1" or "infra". Covers: agent, project, pool, pipeline, skill.
INFRA_COMMANDS = [
    "agent disable",
    "agent enable",
    "agent authorize",
    "agent deauthorize",
    "agent reboot",
    "agent move",
    "agent exec",
    "agent term",
    "project create",
    "project param set",
    "project param delete",
    "project vcs create",
    "project vcs delete",
    "project connection create",
    "project connection delete",
    "project ssh upload",
    "project ssh generate",
    "project ssh delete",
    "project token put",
    "project cloud image start",
    "project cloud instance stop",
    "project connection authorize",
    "pool link",
    "pool unlink",
    "pipeline create",
    "pipeline delete",
    "pipeline push",
    "skill install",
    "skill remove",
    "skill update",
]

# --- Build orchestration commands (15) ---
# Routine for teams with their own governance hooks (e.g. rate-limiters).
# Blocked only when TEAMCITY_RO is "1" (full read-only). Covers: run,
# queue, job. Teams needing these should set TEAMCITY_RO=infra and ship
# a build-governance hook.
ORCHESTRATION_COMMANDS = [
    "run start",
    "run cancel",
    "run restart",
    "run pin",
    "run unpin",
    "run tag",
    "run untag",
    "run comment",
    "queue remove",
    "queue top",
    "queue approve",
    "job pause",
    "job resume",
    "job param set",
    "job param delete",
]

API_WRITE_METHODS = re.compile(r"-X\s*(POST|PUT|DELETE|PATCH)")
API_IMPLICIT_POST = re.compile(r"(--data\b|-d(?=[ \t@]|$)|--json[ \t=])")


def main() -> int:
    ro = os.environ.get("TEAMCITY_RO", "1")
    if ro == "":
        return 0
    if ro not in ("1", "infra"):
        ro = "1"

    raw = sys.stdin.read()
    if not raw:
        return 0

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd or "teamcity" not in cmd:
        return 0

    blocked = INFRA_COMMANDS if ro == "infra" else INFRA_COMMANDS + ORCHESTRATION_COMMANDS
    tier_label = "infra-only" if ro == "infra" else "read-only"

    for sub in blocked:
        pattern = r"\bteamcity\s+" + r"\s+".join(re.escape(w) for w in sub.split()) + r"\b"
        if re.search(pattern, cmd):
            print(
                f"BLOCKED: TeamCity write operation 'teamcity {sub}' is not "
                f"allowed. TEAMCITY_RO={ro} ({tier_label} mode).",
                file=sys.stderr,
            )
            return 2

    if re.search(r"\bteamcity\s+api\b", cmd):
        if API_WRITE_METHODS.search(cmd) or API_IMPLICIT_POST.search(cmd):
            print(
                f"BLOCKED: TeamCity API write method not allowed. "
                f"TEAMCITY_RO={ro} ({tier_label} mode). Only GET requests permitted.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
