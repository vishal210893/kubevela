#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
post-create-dispatcher.py - Devcontainer post-creation setup dispatcher

This script runs after the devcontainer is created and executes all
extension scripts in the post-create-scripts/ directory in sorted order.

All output is logged to $WSROOT/.devcontainer/logs/post-create-YYMMDD[a-z].log
Multiple runs on the same day get sequential suffixes (a, b, c, ...)

The dispatcher pattern ensures:
- Modular, capability-based container setup
- Consistent execution order via numeric prefixes
- Complete logging for debugging
- Failure tracking for dev sh/cc to detect and report
- Log history for troubleshooting previous runs
"""

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

# ==================== Constants ====================

SCRIPT_TIMEOUT = 10  # seconds

# ==================== Helper Functions ====================

def get_log_path(base_dir: Path, name: str) -> Path:
    """Get log path with YYMMDD[a,b,c...] format."""
    logs_dir = base_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%y%m%d")

    # Find next available suffix (a, b, c, ...)
    for suffix in 'abcdefghijklmnopqrstuvwxyz':
        log_path = logs_dir / f"{name}-{today}{suffix}.log"
        if not log_path.exists():
            return log_path

    # Fallback if all letters used (unlikely)
    return logs_dir / f"{name}-{today}z.log"

# ==================== Dispatcher Configuration ====================

class DispatcherConfig:
    """Configuration for a dispatcher instance."""

    def __init__(
        self,
        name: str,
        commands_dir: str,
        log_base_dir: Path,
        log_name: str,
        success_message: str,
        use_workspace_root: bool = True
    ):
        """
        Initialize dispatcher configuration.

        Args:
            name: Dispatcher name (for logging)
            commands_dir: Directory containing extension scripts
            log_base_dir: Base directory for logs (logs/ subdir will be created)
            log_name: Name prefix for log files (e.g., "post-create")
            success_message: Message to display on success
            use_workspace_root: Whether to use $WSROOT env var for path resolution
        """
        self.name = name
        self.commands_dir = commands_dir
        self.log_base_dir = log_base_dir
        self.log_name = log_name
        self.success_message = success_message
        self.use_workspace_root = use_workspace_root

# ==================== Dispatcher Base ====================

class Dispatcher:
    """Base dispatcher for executing capability scripts."""

    def __init__(self, config: DispatcherConfig):
        """
        Initialize dispatcher with configuration.

        Args:
            config: Dispatcher configuration instance
        """
        self.config = config
        self.failures: list[tuple[str, int, str]] = []  # (script_name, exit_code, stderr)
        self.log_file: Optional[Path] = None
        self.start_time: float = 0
        self.total_scripts: int = 0
        self.completed_scripts: int = 0

    def _get_timestamp(self) -> str:
        """
        Get current timestamp in PST format.

        Returns:
            Formatted timestamp string (e.g., "12/14/25 02:30:45 PM PST")
        """
        try:
            pst_time = datetime.now(ZoneInfo("America/Los_Angeles"))
            return pst_time.strftime("%m/%d/%y %I:%M:%S %p PST")
        except Exception:
            # Fallback to UTC if PST not available
            utc_time = datetime.utcnow()
            return utc_time.strftime("%m/%d/%y %I:%M:%S %p UTC")

    def _get_short_timestamp(self) -> str:
        """
        Get short timestamp (time only) in PST format.

        Returns:
            Formatted time string (e.g., "02:30:45 PM")
        """
        try:
            pst_time = datetime.now(ZoneInfo("America/Los_Angeles"))
            return pst_time.strftime("%I:%M:%S %p")
        except Exception:
            utc_time = datetime.utcnow()
            return utc_time.strftime("%I:%M:%S %p")

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 1:
            return f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.1f}s"
        else:
            mins = int(seconds // 60)
            secs = seconds % 60
            return f"{mins}m {secs:.1f}s"

    def _log_banner(self, title: str, content_lines: list[str]) -> None:
        """Log a prominent banner with centered title and content."""
        width = 80
        border = "#" * width
        empty = "##" + " " * (width - 4) + "##"

        self._log(border)
        self._log(empty)
        # Center the title
        title_padded = title.center(width - 4)
        self._log(f"##{title_padded}##")
        for line in content_lines:
            line_padded = line.center(width - 4)
            self._log(f"##{line_padded}##")
        self._log(empty)
        self._log(border)

    def run(self) -> int:
        """
        Execute dispatcher workflow.

        Returns 0 even when individual scripts fail: a non-zero
        postCreateCommand is treated by the devcontainer CLI as a failed
        creation, which suppresses postStartCommand on subsequent starts
        and leaves the container half-initialised. Per-script failures
        are still surfaced via the failure banner in the log and a
        summary printed to stderr.

        Returns:
            Exit code (0 always, except for fatal init errors)
        """
        self.start_time = time.time()

        if not self._init_log():
            return 1

        self._log_environment()

        try:
            script_dir = self._resolve_script_dir()
            if script_dir is None:
                self._log_finish_banner("SUCCESS", "No scripts directory")
                return 0

            scripts = self._discover_scripts(script_dir)
            if not scripts:
                self._log_no_scripts()
                return 0

            self._execute_scripts(scripts)

            if self.failures:
                self._log_failure_summary()
                return 0

            self._log_success()
            return 0

        except Exception as e:
            self._log_fatal_error(e)
            return 1

    def _init_log(self) -> bool:
        """
        Initialize log file with start banner.

        Returns:
            True if successful, False otherwise
        """
        try:
            self.log_file = get_log_path(self.config.log_base_dir, self.config.log_name)
            # Start with empty file, banner will be first thing written
            with open(self.log_file, "w") as f:
                f.write("")

            # Write the start banner
            self._log_banner(
                f"DISPATCHER: {self.config.name}",
                [f"STARTED: {self._get_timestamp()}"]
            )
            self._log("")
            return True
        except Exception as e:
            print(f"Error creating log file: {e}", file=sys.stderr)
            return False

    def _log(self, message: str) -> None:
        """
        Write message to log file.

        Args:
            message: Message to log
        """
        if self.log_file is None:
            return
        try:
            with open(self.log_file, "a") as f:
                f.write(f"{message}\n")
        except Exception as e:
            print(f"Error writing to log: {e}", file=sys.stderr)

    def _log_environment(self) -> None:
        """Log environment information with section header."""
        self._log("--- Environment ---")
        self._log(f"Working directory: {os.getcwd()}")
        self._log(f"User: {os.getenv('USER', 'unknown')}")
        if self.config.use_workspace_root:
            self._log(f"WSROOT: {os.getenv('WSROOT', 'not set')}")
        self._log(f"PATH: {os.getenv('PATH', 'unknown')}")
        self._log("")

    def _resolve_script_dir(self) -> Optional[Path]:
        """
        Resolve the directory containing scripts to execute.

        Returns:
            Path to script directory, or None if not found
        """
        if self.config.use_workspace_root:
            workspace_root = os.environ.get("WSROOT")
            if not workspace_root:
                self._log("Warning: WSROOT not set, trying current directory")
                workspace_root = os.getcwd()
            script_dir = Path(workspace_root) / ".devcontainer" / self.config.commands_dir
            if not script_dir.exists():
                fallback = Path(__file__).parent
                self._log(f"WSROOT-based path not found: {script_dir}")
                self._log(f"Falling back to script location: {fallback}")
                script_dir = fallback
        else:
            script_dir = Path(__file__).parent

        if not script_dir.exists():
            self._log("--- Script Discovery ---")
            self._log(f"Script directory: {script_dir}")
            self._log("Directory not found")
            self._log("")
            print(self.config.success_message)
            return None

        return script_dir

    def _discover_scripts(self, script_dir: Path) -> list[Path]:
        """
        Discover executable scripts in sorted order.

        Args:
            script_dir: Directory to scan for scripts

        Returns:
            List of script paths in sorted order
        """
        scripts = sorted(script_dir.glob("[0-9][0-9][0-9]-*.py"))
        self.total_scripts = len(scripts)

        self._log("--- Script Discovery ---")
        self._log(f"Script directory: {script_dir}")
        self._log(f"Found {len(scripts)} script(s)")
        if scripts:
            for s in scripts:
                bg_marker = " (background)" if '-bg-' in s.name else ""
                self._log(f"  - {s.name}{bg_marker}")
        self._log("")

        return scripts

    def _is_background_script(self, script: Path) -> bool:
        """
        Check if script should run in background based on filename.

        Background scripts have '-bg-' in their filename (e.g., 050-bg-install-java.py).

        Args:
            script: Path to the script

        Returns:
            True if script should run in background
        """
        return '-bg-' in script.name

    def _execute_scripts(self, scripts: list[Path]) -> None:
        """
        Execute scripts in order with detailed logging.

        Background scripts (with '-bg-' in filename) are launched without waiting.
        Foreground scripts block until completion with timeout.

        Args:
            scripts: List of script paths to execute
        """
        for idx, script in enumerate(scripts, 1):
            is_background = self._is_background_script(script)
            script_start = time.time()
            start_ts = self._get_short_timestamp()

            # Script header
            self._log("=" * 80)
            self._log(f"SCRIPT [{idx}/{self.total_scripts}]: {script.name}" +
                     (" (background)" if is_background else ""))
            self._log(f"STARTED: {start_ts}")
            self._log("-" * 80)

            try:
                if is_background:
                    # Create individual log file for this background script
                    bg_log_path = get_log_path(
                        self.config.log_base_dir,
                        f"{self.config.log_name}-{script.stem}"
                    )
                    # Write log header before launching
                    with open(bg_log_path, "a") as bg_log:
                        bg_log.write(f"SCRIPT: {script.name}\n")
                        bg_log.write(f"STARTED: {start_ts}\n")
                        bg_log.write(f"{'-' * 80}\n")

                    # Use shell redirection so the FD stays open for the
                    # child's lifetime (Python file objects get GC-closed
                    # when the dispatcher exits, causing EBADF in detached
                    # children).
                    subprocess.Popen(
                        f'uv run --quiet --script {script} >> {bg_log_path} 2>&1',
                        shell=True,
                        stdin=subprocess.DEVNULL,
                        start_new_session=True
                    )
                    self._log(f"Launched in background (log: {bg_log_path.name})")
                    self._log("-" * 80)
                    end_ts = self._get_short_timestamp()
                    self._log(f"LAUNCHED: {end_ts} - BACKGROUND")
                    self.completed_scripts += 1
                else:
                    # Run in foreground with timeout
                    result = subprocess.run(
                        ["uv", "run", "--quiet", "--script", str(script)],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=SCRIPT_TIMEOUT
                    )

                    # Log script output (indented for clarity)
                    if result.stdout:
                        for line in result.stdout.rstrip().split('\n'):
                            self._log(f"  {line}")
                    if result.stderr:
                        self._log("  [STDERR]:")
                        for line in result.stderr.rstrip().split('\n'):
                            self._log(f"    {line}")

                    self._log("-" * 80)
                    script_duration = time.time() - script_start
                    end_ts = self._get_short_timestamp()

                    if result.returncode != 0:
                        self._log(f"COMPLETED: {end_ts} ({self._format_duration(script_duration)}) - ERROR (exit {result.returncode})")
                        stderr_msg = result.stderr.rstrip() if result.stderr else ""
                        self.failures.append((script.name, result.returncode, stderr_msg))
                    else:
                        self._log(f"COMPLETED: {end_ts} ({self._format_duration(script_duration)}) - OK")
                        self.completed_scripts += 1

            except subprocess.TimeoutExpired:
                self._log("-" * 80)
                self._log(f"COMPLETED: {self._get_short_timestamp()} - TIMEOUT ({SCRIPT_TIMEOUT}s)")
                self.failures.append((script.name, -1, f"Timed out after {SCRIPT_TIMEOUT} seconds"))

            except Exception as e:
                self._log("-" * 80)
                self._log(f"COMPLETED: {self._get_short_timestamp()} - EXCEPTION: {e}")
                self.failures.append((script.name, 1, str(e)))

            self._log("=" * 80)
            self._log("")

    def _log_finish_banner(self, status: str, detail: str = "") -> None:
        """Log the finish banner with timing and status."""
        duration = time.time() - self.start_time
        content = [
            f"FINISHED: {self._get_timestamp()}",
            f"DURATION: {self._format_duration(duration)}",
            f"STATUS: {status}",
        ]
        if detail:
            content.append(detail)

        self._log("")
        self._log_banner(f"DISPATCHER: {self.config.name}", content)

    def _log_no_scripts(self) -> None:
        """Log when no scripts found."""
        self._log("No extension scripts found to execute")
        self._log("")
        self._log_finish_banner("SUCCESS", "No scripts to run")
        print(self.config.success_message)

    def _log_success(self) -> None:
        """Log successful completion with finish banner."""
        self._log_finish_banner(
            "SUCCESS",
            f"{self.completed_scripts}/{self.total_scripts} scripts completed"
        )
        print(self.config.success_message)

    def _log_fatal_error(self, error: Exception) -> None:
        """
        Log fatal error with finish banner.

        Args:
            error: Exception that occurred
        """
        self._log(f"FATAL EXCEPTION: {error}")
        self._log("")
        self._log_finish_banner("FATAL ERROR", str(error)[:60])
        error_msg = f"ERROR: Fatal error in {self.config.name}: {error}"
        print(error_msg, file=sys.stderr)

    def _log_failure_summary(self) -> None:
        """Log failure summary and finish banner."""
        self._log("--- Failure Summary ---")
        for script_name, exit_code, stderr in self.failures:
            if exit_code == -1:
                self._log(f"  FAILED: {script_name} (timeout)")
            else:
                self._log(f"  FAILED: {script_name} (exit {exit_code})")
            if stderr:
                for line in stderr.split('\n')[:3]:
                    self._log(f"          {line}")
        self._log("")

        failed_count = len(self.failures)
        self._log_finish_banner(
            "FAILURE",
            f"{self.completed_scripts}/{self.total_scripts} succeeded, {failed_count} failed"
        )

        # Print to stderr for console visibility
        error_msg = f"ERROR: {self.config.name}: {failed_count} script(s) failed"
        print(error_msg, file=sys.stderr)
        for script_name, exit_code, stderr in self.failures:
            if exit_code == -1:
                detail = f"  - {script_name} (timeout)"
            else:
                detail = f"  - {script_name} (exit {exit_code})"
            print(detail, file=sys.stderr)
            if stderr:
                for line in stderr.split('\n')[:3]:
                    print(f"      {line}", file=sys.stderr)

# ==================== Main Functions ====================

def get_log_base_dir() -> Path:
    """Get the base directory for logs using WSROOT."""
    workspace_root = os.environ.get("WSROOT")
    if not workspace_root:
        workspace_root = os.getcwd()
    return Path(workspace_root) / ".devcontainer"


def main() -> int:
    """Main entry point for postCreateCommand dispatcher."""
    config = DispatcherConfig(
        name="postCreateCommand",
        commands_dir="post-create-scripts",
        log_base_dir=get_log_base_dir(),
        log_name="post-create",
        success_message="OK: Claude Code development container ready (latest)!",
        use_workspace_root=True
    )

    dispatcher = Dispatcher(config)
    return dispatcher.run()

# ==================== Main Execution ====================

if __name__ == "__main__":
    sys.exit(main())
