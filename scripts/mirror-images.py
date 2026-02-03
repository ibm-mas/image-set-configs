 #!/usr/bin/env python3

import argparse
import logging
import re
import selectors
import subprocess
import sys
import yaml
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
from alive_progress import alive_bar
from prompt_toolkit import print_formatted_text, HTML
from itertools import groupby

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


def count_images_in_config(config_path: str) -> int:
    """
    Parse YAML config file and count images in mirror.additionalImages.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        Number of images to be mirrored, or 0 if parsing fails
    """
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        additional_images = config.get('mirror', {}).get('additionalImages', [])
        image_count = len(additional_images)
        logger.debug(f"Found {image_count} images in {config_path}")
        return image_count
    except FileNotFoundError:
        logger.error(f"Config file not found: {config_path}")
        return 0
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML config {config_path}: {e}")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error reading config {config_path}: {e}")
        return 0


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


def _process_streams(process: subprocess.Popen, result_data: Dict, progress_bar=None) -> None:
    """
    Process stdout and stderr streams from a subprocess using selectors.

    Uses non-blocking I/O to efficiently read from both streams without threading.
    Filters output and captures result information.

    Args:
        process: The subprocess.Popen object with stdout and stderr pipes
        result_data: Dictionary to store captured result information
        progress_bar: Optional alive-progress bar instance to update on image copy success
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

            # Detect "Success copying" and update progress bar
            success_match = re.search(r'Success copying .+ ➡️', line_stripped)
            if success_match and progress_bar is not None:
                progress_bar()  # Increment progress bar
                logger.debug("Progress bar incremented")

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


def run_command(cmd: List[str], progress_bar=None) -> tuple[int, Dict]:
    """
    Execute a command and stream output/errors in real-time.

    Args:
        cmd: List of command arguments to execute
        progress_bar: Optional alive-progress bar instance to update on image copy success

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
            _process_streams(process, result_data, progress_bar)

            # Wait for process to complete
            return_code = process.wait()

            if return_code != 0:
                logger.error(f"Command failed with exit code {return_code}")

            return return_code, result_data

    except Exception as e:
        logger.error(f"Error executing command: {e}")
        return 1, {}


def _execute_mirror(config_path: str, display_name: str, workspace_path: str, mode: str, target_registry: str="") -> MirrorResult:
    """
    Execute the mirror operation for a given configuration.

    This is a common function used by both mirror_package and mirror_catalog.

    Args:
        config_path: Path to the YAML configuration file
        display_name: Display name for progress bar (e.g., "ibm-mas v9.0.5 (amd64)" or "catalog v9-260129-amd64")
        workspace_path: Workspace path for the mirror operation (e.g., "package/arch/version" or "catalog/version")
        mode: Mirror mode ("m2m", "m2d", or "d2m")
        target_registry: Target registry for m2m and d2m modes

    Returns:
        MirrorResult object with images, mirrored, and success status.
        Returns images=0, mirrored=0, success=False if operation failed or results couldn't be parsed.
    """
    logger.info(f"Using configuration: {config_path}")

    # Count images in config file
    total_images = count_images_in_config(config_path)
    if total_images == 0:
        logger.error(f"No images found in config or failed to parse: {config_path}")
        print(f"❌ {display_name} - No images found in config")
        return MirrorResult(images=0, mirrored=0)

    logger.info(f"Found {total_images} images to mirror")

    if mode == "m2m":
        cmd = [
            "./oc-mirror", "--v2", "--config", config_path, "--authfile", "/home/david/.ibm-mas/auth.json",
            "--workspace", f"file://workspace/{workspace_path}",
            f"docker://{target_registry}"
        ]
    elif mode == "m2d":
        cmd = [
            "./oc-mirror", "--v2", "--config", config_path, "--authfile", "/home/david/.ibm-mas/auth.json",
            f"file://output-dir/{workspace_path}",
        ]
    elif mode == "d2m":
        cmd = [
            "./oc-mirror", "--v2", "--config", config_path, "--authfile", "/home/david/.ibm-mas/auth.json",
            "--from", f"file://output-dir/{workspace_path}",
            f"docker://{target_registry}"
        ]
    else:
        logger.error(f"Unsupported mirror mode: {mode}")
        print(f"❌ {display_name} - Unsupported mirror mode: {mode}")
        return MirrorResult(images=0, mirrored=0)

    # Execute command with progress bar
    # Use fixed-width title (50 chars) for alignment, with in-progress icon
    bar_title_base = display_name.ljust(50)
    bar_title = f"{bar_title_base} ⏳"
    with alive_bar(total_images, title=bar_title, length=20, enrich_print=False) as bar:
        exit_code, result_data = run_command(cmd, progress_bar=bar)

        # Update bar title with status icon after completion
        if exit_code != 0:
            bar.title = f"{bar_title_base} ❌"
            logger.error(f"Mirror operation failed with exit code {exit_code}")
            return MirrorResult(images=0, mirrored=0)

        # Create result object from captured data
        if 'images' in result_data and 'mirrored' in result_data:
            result = MirrorResult(
                images=result_data['images'],
                mirrored=result_data['mirrored']
            )
            logger.info(f"Mirror operation completed: {result.mirrored}/{result.images} images mirrored (success={result.success})")

            if result.success:
                bar.title = f"{bar_title_base} ✅"
            else:
                bar.title = f"{bar_title_base} ⚠️"

            return result
        else:
            bar.title = f"{bar_title_base} ⚠️"
            logger.warning("Mirror operation completed but could not parse result statistics")
            return MirrorResult(images=0, mirrored=0)


def mirror_package(package: str, version: str, arch: str, mode: str, target_registry: str="", flag: bool=True) -> MirrorResult:
    """
    Mirror a package and return the result.

    Args:
        package: Package name (e.g., "ibm-mas")
        version: Package version (e.g., "9.0.5")
        arch: Architecture (e.g., "amd64")
        mode: Mirror mode ("m2m", "m2d", or "d2m")
        target_registry: Target registry for m2m and d2m modes
        flag: Whether to actually perform the mirror operation

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

    config_path = f"packages/{package}/{major_minor}/{arch}/{package}-{version}-{arch}.yaml"

    if not flag:
        logger.info(f"Skipping {package} version {version} for {arch} architecture")
        # Add empty progress bar to align with other status messages
        empty_bar = "|" + " " * 20 + "|"
        print(f"{package} v{version} ({arch})".ljust(50) + f" ⏭️  {empty_bar} Mirroring disabled by user")
        return MirrorResult(images=0, mirrored=0)

    logger.info(f"Mirroring {package} version {version} for {arch} architecture")

    display_name = f"{package} v{version} ({arch})"
    workspace_path = f"{package}/{arch}/{version}"

    return _execute_mirror(config_path, display_name, workspace_path, mode, target_registry)


def mirror_catalog(version: str, mode: str, target_registry: str="") -> MirrorResult:
    """
    Mirror a catalog and return the result.

    Args:
        version: Catalog version (e.g., "v9-260129-amd64")
        mode: Mirror mode ("m2m", "m2d", or "d2m")
        target_registry: Target registry for m2m and d2m modes

    Returns:
        MirrorResult object with images, mirrored, and success status.
        Returns images=0, mirrored=0, success=False if operation failed or results couldn't be parsed.
    """
    config_path = f"catalogs/{version}.yaml"

    logger.info(f"Mirroring catalog {version}")

    display_name = f"catalog {version}"
    workspace_path = f"catalog/{version}"

    return _execute_mirror(config_path, display_name, workspace_path, mode, target_registry)


# Package configuration: (group, arg_name, package_name, catalog_key, description)
PACKAGE_CONFIGS = [
    ("Required Dependencies", "sls", "ibm-sls", "sls_version", "IBM Suite License Service"),
    ("Required Dependencies", "tsm", "ibm-truststore-mgr", "tsm_version", "IBM Truststore Manager"),

    ("Optional Dependencies", "amlen", "amlen", "amlen_extras_version", "Eclipse Amlen"),

    ("Optional Dependencies", "aiservice", "ibm-aiservice", "aiservice_version", "IBM Maximo AI Service"),
    ("Optional Dependencies", "data-dictionary", "ibm-data-dictionary", "dd_version", "IBM Data Dictionary"),

    ("Optional Dependencies", "db2u-s11", "ibm-db2uoperator-s11", "db2u_version", "IBM Db2 Universal Operator (s11)"),
    ("Optional Dependencies", "db2u-s12", "ibm-db2uoperator-s12", "db2u_version", "IBM Db2 Universal Operator (s12)"),

    ("Optional Dependencies", "mongodb-ce", "mongodb-ce", "mongo_extras_version_default", "MongoDb (CE)"),

    # TODO: Support CP4D ("MAS", "manage", "mongodb-ce", "mas_manage_version", "MongoDb (CE)"),
    # TODO: Support CP4D - WSL ("MAS", "manage", "mongodb-ce", "mas_manage_version", "MongoDb (CE)"),
    # TODO: Support CP4D - WML ("MAS", "manage", "mongodb-ce", "mas_manage_version", "MongoDb (CE)"),
    # TODO: Support CP4D - Spark ("MAS", "manage", "mongodb-ce", "mas_manage_version", "MongoDb (CE)"),
    # TODO: Support CP4D - Cognos ("MAS", "manage", "mongodb-ce", "mas_manage_version", "MongoDb (CE)"),

    # TODO: Support catalog ("MAS", "catalog", "ibm-mas-operator-catalog", "mas_catalog_version", "Operator Catalog"),
    ("MAS", "core", "ibm-mas", "mas_core_version", "Core"),
    ("MAS", "assist", "ibm-mas-assist", "mas_assist_version", "Assist"),
    ("MAS", "iot", "ibm-mas-iot", "mas_iot_version", "IoT"),
    ("MAS", "facilities", "ibm-mas-facilities", "mas_facilities_version", "Facilities"),
    ("MAS", "manage", "ibm-mas-manage", "mas_manage_version", "Manage"),
    ("MAS", "manage-icd", "ibm-mas-manage-icd", "mas_manage_version", "Manage (ICD)"),
    ("MAS", "monitor", "ibm-mas-monitor", "mas_monitor_version", "Monitor"),
    ("MAS", "predict", "ibm-mas-predict", "mas_predict_version", "Predict"),
    ("MAS", "optimizer", "ibm-mas-optimizer", "mas_optimizer_version", "Optimizer"),
    ("MAS", "visualinspection", "ibm-mas-visualinspection", "mas_visualinspection_version", "Visual Inspection"),
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Mirror IBM MAS packages using oc-mirror",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --catalog v9-240625-amd64 --release 9.0.x --core --tsm --sls
  %(prog)s --catalog v9-260129-amd64 --release 9.1.x --core --tsm --sls
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
    parser.add_argument(
        "--target-registry",
        required=False,
        type=str,
        help="Target registry for m2m and d2m modes (e.g., registry.example.com/namespace)"
    )

    # Add package-specific arguments dynamically, organized by group
    for group_name, group_items in groupby(PACKAGE_CONFIGS, key=lambda x: x[0]):
        arg_group = parser.add_argument_group(group_name)
        for group, arg_name, package_name, _, description in group_items:
            arg_group.add_argument(
                f"--{arg_name}",
                required=False,
                help=f"Mirror images for the {package_name} package",
                action="store_true"
            )
    args = parser.parse_args()

    catalog_version = args.catalog
    release = args.release
    mode = args.mode

    # Validate that --target-registry is provided for m2m and d2m modes
    if mode in ["m2m", "d2m"] and not args.target_registry:
        parser.error(f"--target-registry is required when mode is '{mode}'")

    # Configure logging to file
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

    print_formatted_text(HTML(f"<B>Mirroring Images for {catalog_version} ({mode})</B>"))

    print_formatted_text(HTML(f"\n<U>IBM Maximo Operator Catalog</U>"))
    mirror_catalog(
        version=catalog_version,
        mode=mode,
        target_registry=args.target_registry or ""
    )

    # Mirror each package with common parameters using shared configuration
    current_group = None
    for group, arg_name, package_name, catalog_key, description in PACKAGE_CONFIGS:
        # Print section header when group changes
        if group != current_group:
            print_formatted_text(HTML(f"\n<U>{group}</U>"))
            current_group = group

        # Get version from catalog - handle both direct keys and release-specific keys
        if catalog_key in ["db2u_version"]:
            version = catalog[catalog_key].split("+")[0]
        elif catalog_key in ["sls_version", "tsm_version", "amlen_extras_version", "dd_version", "mongo_extras_version_default"]:
            version = catalog[catalog_key]
        else:
            version = catalog[catalog_key][release]

        # Get the flag value from args
        flag = getattr(args, arg_name.replace("-", "_"))

        mirror_package(
            package=package_name,
            version=version,
            arch=arch,
            mode=args.mode,
            target_registry=args.target_registry or "",
            flag=flag
        )
