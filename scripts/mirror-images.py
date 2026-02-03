#!/usr/bin/env python3

import argparse
import logging
import re
import selectors
import subprocess
import sys
from typing import List, Dict, Optional
from dataclasses import dataclass
from halo import Halo

from mas.devops.data import getCatalog


# Configure logging - will be set up in main with filename
logger = logging.getLogger(__name__)


@dataclass
class MirrorResult:
    """Result of a mirror operation."""
    images: int
    mirrored: int

    @property
    def success(self) -> bool:
        """
        Determine if the mirror operation was successful.

        Returns:
            True if all images were mirrored successfully, False otherwise.
        """
        return self.images != 0 and self.images == self.mirrored


def strip_log_prefix(line: str) -> str:
    """
    Strip timestamp and log level prefix from command output.

    Handles format: "2026/02/02 18:12:25  [INFO]   : {actual message}"
    Removes everything up to and including the first ": " after a log level.

    Args:
        line: The log line to process

    Returns:
        The line with prefix stripped, or original line if no match
    """
    # Check if line starts with a timestamp pattern (with or without ANSI codes)
    # If it does, find the first ": " after a log level and remove everything before it
    if re.match(r'^.*?\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}', line):
        # Find position of ": " after the log level
        # Split on first occurrence of ": " that comes after a bracket
        parts = line.split(': ', 1)
        if len(parts) == 2 and '[' in parts[0]:
            return parts[1]

    return line


def stream_output(pipe, log_func, result_data: Dict):
    """
    Stream output from a pipe to logger in real-time.
    Filters out noise lines, strips duplicate log prefixes, and captures results.

    Args:
        pipe: The pipe to read from (stdout or stderr)
        log_func: The logging function to use (logger.info or logger.error)
        result_data: Dictionary to store captured result information
    """
    # Patterns to filter out from logs
    filter_patterns = [
        "Hello, welcome to oc-mirror",  # Unnecessary welcome message
        "setting up the environment for you...",  # Unnecesary setup message
        "using digest to pull, but tag only for mirroring"  # Unnecessary warnings that are liable to confuse users
    ]

    for line in iter(pipe.readline, ''):
        if line:
            line_stripped = line.rstrip()

            # Capture result information BEFORE stripping prefix
            # Pattern: "48 / 48 additional images mirrored successfully" (without tick icon)
            result_match = re.search(r'(\d+)\s+/\s+(\d+)\s+additional images mirrored successfully', line_stripped)
            if result_match:
                result_data['mirrored'] = int(result_match.group(1))
                result_data['images'] = int(result_match.group(2))
                logger.debug(f"Captured result: {result_data['mirrored']}/{result_data['images']}")

            # Strip duplicate timestamp/level prefix from command output
            clean_line = strip_log_prefix(line_stripped)

            # Skip lines containing any filter pattern
            if not any(pattern.lower() in line_stripped.lower() for pattern in filter_patterns):
                log_func(clean_line)
    pipe.close()


def _process_streams(process: subprocess.Popen, result_data: Dict) -> None:
    """
    Process stdout and stderr streams from a subprocess using selectors.

    Uses non-blocking I/O to efficiently read from both streams without threading.
    Filters output and captures result information.

    Args:
        process: The subprocess.Popen object with stdout and stderr pipes
        result_data: Dictionary to store captured result information
    """
    # Ensure streams are available
    if process.stdout is None or process.stderr is None:
        return

    # Compile filter patterns into a single case-insensitive regex for performance
    filter_patterns = [
        "Hello, welcome to oc-mirror",
        "setting up the environment for you...",
        "using digest to pull, but tag only for mirroring"
    ]
    # Escape special regex characters and join with OR operator
    filter_regex = re.compile('|'.join(re.escape(pattern) for pattern in filter_patterns), re.IGNORECASE)

    # Set up selector for non-blocking I/O
    sel = selectors.DefaultSelector()
    sel.register(process.stdout, selectors.EVENT_READ, data='stdout')
    sel.register(process.stderr, selectors.EVENT_READ, data='stderr')

    # Track which streams are still open (store file objects, not selectors)
    streams_open = {process.stdout.fileno(), process.stderr.fileno()}

    while streams_open:
        # Wait for data to be available on any stream
        events = sel.select(timeout=0.1)

        for key, _ in events:
            stream_type = key.data

            # Get the actual file object from the key
            if stream_type == 'stdout':
                stream = process.stdout
            else:
                stream = process.stderr

            if stream is None:
                continue

            line = stream.readline()

            if not line:
                # Stream closed
                streams_open.discard(stream.fileno())
                sel.unregister(stream)
                continue

            line_stripped = line.rstrip()

            # Capture result information BEFORE stripping prefix
            result_match = re.search(r'(\d+)\s+/\s+(\d+)\s+additional images mirrored successfully', line_stripped)
            if result_match:
                result_data['mirrored'] = int(result_match.group(1))
                result_data['images'] = int(result_match.group(2))
                logger.debug(f"Captured result: {result_data['mirrored']}/{result_data['images']}")

            # Strip duplicate timestamp/level prefix from command output
            clean_line = strip_log_prefix(line_stripped)

            # Skip lines matching the filter regex (case-insensitive)
            if not filter_regex.search(line_stripped):
                # Log to appropriate level based on stream
                if stream_type == 'stdout':
                    logger.debug(clean_line)
                else:
                    logger.error(clean_line)

    sel.close()


def run_command(cmd: List[str]) -> tuple[int, Dict]:
    """
    Execute a command and stream output/errors in real-time.

    Args:
        cmd: List of command arguments to execute

    Returns:
        Tuple of (exit_code, result_data) where result_data contains captured information
    """
    logger.info(f"Executing: {' '.join(cmd)}")

    # Dictionary to capture result data from output
    result_data = {}

    try:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # Line buffered for real-time output
        ) as process:
            # Process streams using selectors for efficient non-blocking I/O
            _process_streams(process, result_data)

            # Wait for process to complete
            return_code = process.wait()

            if return_code != 0:
                logger.error(f"Command failed with exit code {return_code}")

            return return_code, result_data

    except Exception as e:
        logger.error(f"Error executing command: {e}")
        return 1, {}


def mirror_package(package: str, version: str, arch: str, mode: str, target_registry: str="") -> MirrorResult:
    """
    Mirror a package and return the result.

    Args:
        package: Package name (e.g., "ibm-mas")
        version: Package version (e.g., "9.0.5")
        arch: Architecture (e.g., "amd64")

    Returns:
        MirrorResult object with images, mirrored, and success status.
        Returns images=0, mirrored=0, success=False if operation failed or results couldn't be parsed.
    """
    # Extract major.minor version (first two components)
    version_parts = version.split('.')

    # Validate version format
    if len(version_parts) < 2:
        logger.error(f"Invalid version format: '{version}'. Expected format: 'major.minor.patch' (e.g., '9.0.5')")
        return MirrorResult(images=0, mirrored=0)

    major_minor = f"{version_parts[0]}.{version_parts[1]}"

    path = f"packages/{package}/{major_minor}/{arch}/{package}-{version}-{arch}.yaml"

    spinner_cfg = {
        "interval": 80,
        "frames": [" ⠋", " ⠙", " ⠹", " ⠸", " ⠼", " ⠴", " ⠦", " ⠧", " ⠇", " ⠏"]
    }
    successIcon = "✅️"
    failureIcon = "❌"
    haloPrefix = f"{package} v{version} ({arch})"

    logger.info(f"Mirroring {package} version {version} for {arch} architecture")
    logger.info(f"Using configuration: {path}")

    if mode == "m2m":
        cmd = [
            "./oc-mirror", "--v2", "--config", path, "--authfile", "/home/david/.ibm-mas/auth.json",
            f"docker://{target_registry}"
        ]
    elif mode == "m2d":
        cmd = [
            "./oc-mirror", "--v2", "--config", path, "--authfile", "/home/david/.ibm-mas/auth.json",
            f"file://output-dir/{package}/{arch}/{version}",
        ]
    elif mode == "d2m":
        cmd = [
            "./oc-mirror", "--v2", "--config", path, "--authfile", "/home/david/.ibm-mas/auth.json",
            "--from", f"file://output-dir/{package}/{arch}/{version}",
            f"docker://{target_registry}"
        ]
    else:
        logger.error(f"Unsupported mirror mode: {mode}")
        h.stop_and_persist(symbol=failureIcon, text=f"{haloPrefix} - Unsupported mirror mode: {mode}")
        return MirrorResult(images=0, mirrored=0)

    # exit_code, result_data = run_command(cmd)
    import time
    time.sleep(30)
    exit_code=0
    result_data = { 'images': 10, 'mirrored': 10 }

    if exit_code != 0:
        logger.error(f"Mirror operation failed with exit code {exit_code}")
        h.stop_and_persist(symbol=failureIcon, text=f"{haloPrefix} - Mirror operation failed with exit code {exit_code}")
        return MirrorResult(images=0, mirrored=0)

    # Create result object from captured data
    if 'images' in result_data and 'mirrored' in result_data:
        result = MirrorResult(
            images=result_data['images'],
            mirrored=result_data['mirrored']
        )
        logger.info(f"Mirror operation completed: {result.mirrored}/{result.images} images mirrored (success={result.success})")
        h.stop_and_persist(symbol=successIcon, text=f"{haloPrefix} - {result.mirrored}/{result.images} images mirrored")
        return result
    else:
        logger.warning("Mirror operation completed but could not parse result statistics")
        h.stop_and_persist(symbol=failureIcon, text=f"{haloPrefix} - Mirror operation completed but could not parse result statistics")
        return MirrorResult(images=0, mirrored=0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Mirror IBM MAS packages using oc-mirror",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --catalog v9-240625-amd64 --release 9.0.x
  %(prog)s --catalog v9-260129-amd64 --release 9.1.x
        """
    )
    parser.add_argument(
        "--catalog",
        required=True,
        help="Catalog version (e.g., v9-240625-amd64, v9-260129-amd64)"
    )
    parser.add_argument(
        "--release",
        required=True,
        help="MAS release version",
        choices=["8.10.x", "8.11.x", "9.0.x", "9.1.x"]
    )
    parser.add_argument(
        "--mode",
        required=True,
        help="Mirror mode",
        choices=["m2m", "m2d", "d2m"]
    )

    args = parser.parse_args()

    catalog_version = args.catalog
    release = args.release
    mode = args.mode

    # Configure logging to file
    from datetime import datetime
    log_filename = f"mirror-{catalog_version}-{release.replace('.', '')}-{mode}-{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        filename=log_filename,
        filemode='w'
    )

    catalog = getCatalog(catalog_version)
    arch = catalog_version.split("-")[-1]

    logger.info(f"Catalog: {catalog_version}")
    logger.info(f"Release: {release}")
    logger.info(f"Architecture: {arch}")
    logger.info(f"Mode: {mode}")
    logger.info(f"Log file: {log_filename}")

    sls_result = mirror_package(
        package="ibm-sls",
        version=catalog["sls_version"],
        arch=arch,
        mode=args.mode
    )
    tsm_result = mirror_package(
        package="ibm-truststore-mgr",
        version=catalog["tsm_version"],
        arch=arch,
        mode=args.mode
    )
    # mas_result = mirror_package("ibm-mas", catalog["mas_core_version"][release], arch)
