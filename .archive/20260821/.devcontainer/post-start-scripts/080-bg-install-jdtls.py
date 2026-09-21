#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
CAPABILITY: lang-java

Installs Eclipse JDT Language Server (jdtls) for Java code intelligence.
Downloads and extracts JDTLS directly from Eclipse.org.
Provides go-to-definition, find references, hover docs for Java files.
"""
import subprocess
import sys
from pathlib import Path

JDTLS_VERSION = "1.57.0"
JDTLS_BUILD = "202602261110"
JDTLS_URL = f"https://www.eclipse.org/downloads/download.php?file=/jdtls/milestones/{JDTLS_VERSION}/jdt-language-server-{JDTLS_VERSION}-{JDTLS_BUILD}.tar.gz"


def get_install_dir() -> Path:
    """Get the installation directory for jdtls."""
    return Path.home() / ".local" / "share" / "jdtls"


def is_installed() -> bool:
    """Check if jdtls is installed."""
    install_dir = get_install_dir()
    launcher = install_dir / "plugins" / "org.eclipse.equinox.launcher_*.jar"

    # Check if the installation directory exists and has content
    if install_dir.exists():
        # Look for any launcher jar file
        import glob
        launchers = list(glob.glob(str(launcher)))
        if launchers:
            return True
    return False


def main() -> int:
    """Install jdtls by downloading and extracting from Eclipse."""

    install_dir = get_install_dir()

    print(f"Installing jdtls {JDTLS_VERSION}...")

    try:
        # Create installation directory
        install_dir.mkdir(parents=True, exist_ok=True)

        # Download the tar.gz
        tar_path = install_dir.parent / f"jdtls-{JDTLS_VERSION}.tar.gz"
        print(f"  Downloading from Eclipse.org...")

        result = subprocess.run(
            ["curl", "-fL", "-o", str(tar_path), JDTLS_URL],
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            print("ERROR: Failed to download jdtls", file=sys.stderr)
            if result.stderr:
                print(f"  {result.stderr[:200]}", file=sys.stderr)
            return 1

        # Extract to installation directory
        print(f"  Extracting to {install_dir}...")
        result = subprocess.run(
            ["tar", "-xzf", str(tar_path), "-C", str(install_dir)],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            print("ERROR: Failed to extract jdtls", file=sys.stderr)
            if result.stderr:
                print(f"  {result.stderr[:200]}", file=sys.stderr)
            return 1

        # Clean up tar file
        tar_path.unlink()

        # Verify installation
        if not is_installed():
            print("ERROR: Installation verification failed", file=sys.stderr)
            return 1

        # Symlink jdtls executable to ~/.local/bin for PATH access
        bin_dir = Path.home() / ".local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)

        jdtls_exe = install_dir / "bin" / "jdtls"
        jdtls_link = bin_dir / "jdtls"

        if jdtls_exe.exists():
            print(f"  Linking {jdtls_exe} to {jdtls_link}...")
            if jdtls_link.exists() or jdtls_link.is_symlink():
                jdtls_link.unlink()
            jdtls_link.symlink_to(jdtls_exe)
            print(f"[OK] jdtls {JDTLS_VERSION} installed and available in PATH")
        else:
            print(f"[OK] jdtls {JDTLS_VERSION} installed to {install_dir}")

        return 0

    except subprocess.TimeoutExpired:
        print("ERROR: Installation timed out", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
