#!/bin/sh
# Set KUBECONFIG and validate Atmos session environment variables.
# Sourced on every shell session start via login-dispatcher.
# Silent when Atmos vars are not set (non-Atmos teams see no output).

if [ -z "$ATMOS_SESSION" ]; then
    return 0
fi

# ATMOS_SESSION is set -- we're in an Atmos environment.
# Clear AWS_PROFILE to avoid "config profile () could not be found" errors.
# Atmos sessions use forwarded AWS credentials, not named profiles.
unset AWS_PROFILE
export KUBECONFIG="/home/node/.atmos2/$(basename "$KUBECONFIG")"

# Warn only if partial session vars are missing (likely a misconfigured export).
missing=""
for var in ATMOS_GALAXY_NAME ATMOS_QUADRANT_ALIAS_NAME ATMOS_QUADRANT_NAME \
           AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \
           AWS_ACCOUNT_ID AWS_ACCOUNT_NAME; do
    eval val=\$$var
    if [ -z "$val" ]; then
        if [ -n "$missing" ]; then
            missing="$missing, $var"
        else
            missing="$var"
        fi
    fi
done

if [ -n "$missing" ]; then
    echo "atmos-export: incomplete session -- missing: $missing"
    echo "atmos-export: on your host, run: atmos use <quadrant> && export"
fi
