#!/usr/bin/env python3

import argparse
import logging
import re
import subprocess
import sys
import threading
from typing import List, Dict, Optional
from dataclasses import dataclass

from mas.devops.data import getCatalog


@dataclass
class MirrorResult:
    """Result of a mirror operation."""
    images: int
    mirrored: int
    success: bool

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


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
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # Line buffered for real-time output
        )

        # Create threads to stream stdout and stderr simultaneously
        stdout_thread = threading.Thread(
            target=stream_output,
            args=(process.stdout, logger.debug, result_data)
        )
        stderr_thread = threading.Thread(
            target=stream_output,
            args=(process.stderr, logger.error, result_data)
        )

        # Start both threads
        stdout_thread.start()
        stderr_thread.start()

        # Wait for process to complete
        return_code = process.wait()

        # Wait for threads to finish processing output
        stdout_thread.join()
        stderr_thread.join()

        if return_code != 0:
            logger.error(f"Command failed with exit code {return_code}")
            return 1, result_data

        return 0, result_data

    except FileNotFoundError:
        logger.error("Command not found. Please ensure the required CLI is installed.")
        return 1, {}
    except Exception as e:
        logger.error(f"Error executing command: {e}")
        return 1, {}


def mirror_package(package: str, version: str, arch: str) -> MirrorResult:
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
    major_minor = f"{version_parts[0]}.{version_parts[1]}"

    path = f"packages/{package}/{major_minor}/{arch}/{package}-{version}-{arch}.yaml"

    logger.info(f"Mirroring {package} version {version} for {arch} architecture")
    logger.info(f"Using configuration: {path}")

    # Execute oc-mirror command
    cmd = [
        "./oc-mirror", "--v2", "--config", path, "--authfile", "/home/david/.ibm-mas/auth.json", "file://output-dir"
    ]

    exit_code, result_data = run_command(cmd)

    if exit_code != 0:
        logger.error("Mirror operation failed")
        return MirrorResult(images=0, mirrored=0, success=False)

    # Create result object from captured data
    if 'images' in result_data and 'mirrored' in result_data:
        result = MirrorResult(
            images=result_data['images'],
            mirrored=result_data['mirrored'],
            success=(result_data['images'] == result_data['mirrored'])
        )
        logger.info(f"Mirror operation completed: {result.mirrored}/{result.images} images mirrored (success={result.success})")
        return result
    else:
        logger.warning("Mirror operation completed but could not parse result statistics")
        return MirrorResult(images=0, mirrored=0, success=False)


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

    args = parser.parse_args()

    catalog_version = args.catalog
    release = args.release

    catalog = getCatalog(catalog_version)
    arch = catalog_version.split("-")[-1]

    logger.info(f"Catalog: {catalog_version}")
    logger.info(f"Release: {release}")
    logger.info(f"Architecture: {arch}")

    # sls_result = mirror_package("ibm-sls", catalog["sls_version"], arch)
    tsm_result = mirror_package("ibm-truststore-mgr", catalog["tsm_version"], arch)
    # mas_result = mirror_package("ibm-mas", catalog["mas_core_version"][release], arch)
