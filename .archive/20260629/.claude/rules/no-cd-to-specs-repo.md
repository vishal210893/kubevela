# Never Change Working Directory to Specs Repo

CRITICAL: Do NOT use `cd` or `os.chdir()` to change into the specs repository directory.
You may read, analyze, and write files in the specs repo freely using absolute paths,
but the working directory must NEVER be changed to the specs repo.

## Rule

- NEVER run `cd /path/to/specs` or any equivalent that changes the shell working directory
- NEVER use `os.chdir()` to switch into the specs repo in Python scripts
- NEVER run git commands like `git commit` from inside the specs repo by first cd'ing to it

## Correct Approach

Use absolute paths and the `git -C` flag to operate on the specs repo without leaving the
current working directory:

```bash
# WRONG
cd /workspaces/src/specs/dev && git add . && git commit -m "..."

# CORRECT
git -C /workspaces/src/specs/dev add .
git -C /workspaces/src/specs/dev commit -m "..."
```

For file reads and writes, use the absolute path directly:

```bash
# WRONG
cd /workspaces/src/specs/dev && cat specs/auth/requirements.md

# CORRECT
cat /workspaces/src/specs/dev/specs/auth/requirements.md
```

## Why

Changing into the specs repo disrupts the working directory for the rest of the session.
Subsequent commands that assume the dev2 repo context will fail or operate on the wrong
repository. The specs repo is a sibling repo and should always be accessed via absolute
paths only.

## Exception

Only change to the specs repo if the USER explicitly asks: "change to the specs repo" or
"cd to specs". Even then, confirm before doing so.
