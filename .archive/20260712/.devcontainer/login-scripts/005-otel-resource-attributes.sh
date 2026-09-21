#!/bin/sh
# Build OTEL_RESOURCE_ATTRIBUTES from various sources for Claude Code telemetry
# Sourced on every shell session start

_otel_attrs=""

# Container version from /etc/container-version.txt
if [ -f /etc/container-version.txt ]; then
    _ver=$(cat /etc/container-version.txt | tr -d '[:space:]')
    [ -n "$_ver" ] && _otel_attrs="container_version=$_ver"
fi

# Dev version from ~/.dev/dev.yaml (written by dev CLI on host)
if [ -f "$HOME/.dev/dev.yaml" ]; then
    _cli_ver=$(grep '^dev-version:' "$HOME/.dev/dev.yaml" | sed 's/^dev-version:[[:space:]]*//' | tr -d '[:space:]')
    if [ -n "$_cli_ver" ]; then
        [ -n "$_otel_attrs" ] && _otel_attrs="$_otel_attrs,"
        _otel_attrs="${_otel_attrs}dev_version=$_cli_ver"
    fi
fi

# Profile name and version from .version file (written by dev profile install)
_version_file=""
if [ -n "$WSROOT" ] && [ -f "$WSROOT/.devcontainer/.version" ]; then
    _version_file="$WSROOT/.devcontainer/.version"
elif [ -n "$WSROOT" ] && [ -f "$WSROOT/.claude/.version" ]; then
    _version_file="$WSROOT/.claude/.version"
fi

if [ -n "$_version_file" ]; then
    _profile_name=$(grep '^profile:' "$_version_file" | sed 's/^profile:[[:space:]]*//' | tr -d '[:space:]')
    if [ -n "$_profile_name" ]; then
        [ -n "$_otel_attrs" ] && _otel_attrs="$_otel_attrs,"
        _otel_attrs="${_otel_attrs}profile_name=$_profile_name"
    fi

    _profile_ver=$(grep '^version:' "$_version_file" | sed 's/^version:[[:space:]]*//' | tr -d '[:space:]')
    if [ -n "$_profile_ver" ]; then
        [ -n "$_otel_attrs" ] && _otel_attrs="$_otel_attrs,"
        _otel_attrs="${_otel_attrs}profile_version=$_profile_ver"
    fi
fi

# Artifactory username from ARTIFACTORY_USERNAME
if [ -n "$ARTIFACTORY_USERNAME" ]; then
    [ -n "$_otel_attrs" ] && _otel_attrs="$_otel_attrs,"
    _otel_attrs="${_otel_attrs}artifactory_username=$ARTIFACTORY_USERNAME"
fi

# Host username from HOST_USER (Unix/macOS) or HOST_USERNAME (Windows)
_host_user="${HOST_USER:-$HOST_USERNAME}"
if [ -n "$_host_user" ]; then
    [ -n "$_otel_attrs" ] && _otel_attrs="$_otel_attrs,"
    _otel_attrs="${_otel_attrs}host_username=$_host_user"
fi

# Export if we have any attributes
[ -n "$_otel_attrs" ] && export OTEL_RESOURCE_ATTRIBUTES="$_otel_attrs"

unset _otel_attrs _ver _cli_ver _version_file _profile_name _profile_ver _host_user
