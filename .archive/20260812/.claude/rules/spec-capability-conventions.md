# Spec Capability Conventions

- `TRUNK_BRANCHES = frozenset({'main', 'master', 'develop'})` is defined in `speclib.py` -- always import it, never inline the tuple
- `capabilities/spec` is namespace-agnostic -- never reference `/ccs:feature` or other namespace-specific commands in it
- `speclib.py` is the shared library for all spec scripts -- add new shared constants and functions there, not in individual scripts
