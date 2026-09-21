# Check Spec Location Before Searching

**When to use this rule**: Before searching for specs or referencing spec file paths.

## Problem

Never assume specs are in `.dev/specs/`. Specs live in a shared repository at `<spec-repo-directory>/<project>/`.

## Discovery Process

### Step 1: Check Config

Run `/spec:config` to see the current configuration. Configuration is stored in `~/.dev/dev.yaml` under the `spec` section.

### Step 2: Resolve Doc Root

The path is: `<spec-repo-directory>/<project>/`

Default spec-repo-directory is `$WSROOT/specs`. Project defaults to the repo name.

For example, if project is `dev`, specs are at `$WSROOT/specs/dev/specs/<spec-name>/`.

### Step 3: If Not Configured

If no config exists, the user needs to run `/spec:setup` first. This validates the specs repo exists and sets the project name.

## Quick Check Command

Run `/spec:config` to see the formatted configuration including the resolved spec root path.

## Example

If config shows:
```
spec-repo-directory:  $WSROOT/specs
project:              dev (repo default)

Spec root: /workspaces/src/specs/dev/
```

Then:
- Doc root = `$WSROOT/specs/dev/` (e.g., `/workspaces/src/specs/dev/`)
- Specs are at = `$WSROOT/specs/dev/specs/<spec-name>/`
- NOT at `.dev/specs/<spec-name>/`

## Action

Before searching for specs, check the config to discover the actual storage location.
