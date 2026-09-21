#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///

"""
CAPABILITY: Copies and rewrites kubeconfig from ~/.kube-host to ~/.kube

When the host's ~/.kube is mounted at ~/.kube-host, this script copies
~/.kube-host/config to ~/.kube/config and rewrites cluster server addresses
that use https://127.0.0.1 or https://0.0.0.0 to use https://host.docker.internal
instead.

Inside a devcontainer, 127.0.0.1 and 0.0.0.0 refer to the container's own
loopback/interfaces, not the host's. Local clusters (kind, k3d, minikube) listen
on one of these addresses on the host, so their server addresses must be rewritten
to host.docker.internal to be reachable from inside the container.

For each rewritten cluster entry:
- server: https://127.0.0.1:PORT or https://0.0.0.0:PORT -> https://host.docker.internal:PORT
- certificate-authority-data is removed (cert was issued for 127.0.0.1)
- insecure-skip-tls-verify: true is set

Remote clusters (EKS, GKE, etc.) are passed through unchanged.

The destination ~/.kube/config is always overwritten since the host config
is the source of truth. This script re-runs on every container start.
"""

import os
import sys
from pathlib import Path

import yaml

HOME = Path.home()
KUBE_HOST = HOME / ".kube-host"
KUBE_DIR = HOME / ".kube"
SRC = KUBE_HOST / "config"
DST = KUBE_DIR / "config"

LOCAL_ADDRS = ("https://127.0.0.1", "https://0.0.0.0", "https://localhost")
DOCKER_HOST_ADDR = "https://host.docker.internal"


def main() -> int:
    if not KUBE_HOST.exists():
        print("No ~/.kube-host found, skipping kubeconfig init")
        return 0

    if not SRC.exists():
        print("No ~/.kube-host/config found, skipping kubeconfig init")
        return 0

    KUBE_DIR.mkdir(mode=0o700, exist_ok=True)

    with open(SRC) as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError:
            print("~/.kube-host/config contains invalid YAML, skipping")
            return 0

    if not isinstance(config, dict):
        print("~/.kube-host/config is not valid YAML, skipping")
        return 0

    clusters = config.get("clusters") or []
    rewritten = 0

    for entry in clusters:
        cluster = entry.get("cluster") or {}
        server = cluster.get("server", "")

        matched = next((addr for addr in LOCAL_ADDRS if addr in server), None)
        if matched is None:
            continue

        cluster["server"] = server.replace(matched, DOCKER_HOST_ADDR)
        cluster.pop("certificate-authority-data", None)
        cluster["insecure-skip-tls-verify"] = True
        rewritten += 1

        name = entry.get("name", "<unnamed>")
        print(f"  {name}: rewrote server address to host.docker.internal")

    with open(DST, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    os.chmod(DST, 0o600)

    total = len(clusters)
    print(f"Kubeconfig init complete: {rewritten} rewritten, {total - rewritten} unchanged ({total} total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
