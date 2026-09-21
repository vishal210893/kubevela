#!/bin/sh
# Warn the user if the active workspace profile is deprecated.
# Sourced on every shell session start via login-dispatcher.
# Silent for non-deprecated profiles.

_profile_yaml=""
if [ -n "$WSROOT" ] && [ -f "$WSROOT/.devcontainer/profile.yaml" ]; then
    _profile_yaml="$WSROOT/.devcontainer/profile.yaml"
fi

[ -z "$_profile_yaml" ] && return 0

_profile_name=$(grep '^name:' "$_profile_yaml" | head -1 | sed 's/^name:[[:space:]]*//' | tr -d '[:space:]')

# Hardcoded list of deprecated profiles. Source profile.yaml carries
# `tags: [deprecated]` but the dev CLI does not propagate that field to the
# resolved .devcontainer/profile.yaml, so we match on name here. Keep this
# list in sync with `tags: [deprecated]` entries in ns/*/profiles/*/profile.yaml.
case "$_profile_name" in
    ccs.ccs|ccs.ccs-wiz)
        cat >&2 <<EOF

  ⚠  Profile "$_profile_name" is DEPRECATED and will be removed in a future release.
     Switch to one of these active CCS profiles:
       • ccs.ccsbase       — general CCS development
       • ccs.atmos         — Atmos cloud workflows
       • ccs.microservices — Spring Boot microservices
       • ccs.aipy          — Python LLM development

     Run \`dev profile install <new-profile>\` or edit ~/.dev/dev.yaml.
     Questions: jguionnet@guidewire.com or #claude-code-ccs on Slack.

EOF
        ;;
esac

unset _profile_yaml _profile_name
