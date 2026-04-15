#!/usr/bin/env python3
"""
Create ISCs script for IBM MAS CASE package operations with command-line arguments.
Allows users to specify CASE names and versions via command line.
"""

import argparse
import csv
import subprocess
import sys
import os
from copy import deepcopy
from typing import List, Optional, Dict, Set
import yaml

ISC_TEMPLATE = dict(
    apiVersion="mirror.openshift.io/v1alpha2",
    kind="ImageSetConfiguration",
    archiveSize=2,  # GB
    mirror=dict(
        additionalImages=[]
    )
)

def run_command(cmd: List[str]) -> int:
    """
    Execute a command and handle output/errors.

    Args:
        cmd: List of command arguments to execute

    Returns:
        0 on success, 1 on failure
    """
    print(f"Executing: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return 0

    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}", file=sys.stderr)
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("Error: 'oc' command not found. Please ensure OpenShift CLI is installed.", file=sys.stderr)
        return 1


def generate_iscs(case_name, case_versions, architectures=["amd64", "ppc64le", "s390x"], include_group=None, exclude_group=None, child_name=None) -> None:
    for case_version in case_versions:
        for arch in architectures:
            generate_isc(case_name, case_version, arch, include_group, exclude_group, child_name)


def generate_db2_iscs(case_versions, architectures=["amd64", "ppc64le", "s390x"], include_group=None) -> None:
    """Generate separate ISCs for DB2 operator s11 and s12 variants."""
    for case_version in case_versions:
        for arch in architectures:
            # Generate s11 variant (excludes s12 images)
            generate_isc("ibm-db2uoperator", case_version, arch, include_group, None, None, "s11")
            # Generate s12 variant (excludes s11 images)
            generate_isc("ibm-db2uoperator", case_version, arch, include_group, None, None, "s12")


def load_catalog_file(catalog_path: str) -> Dict:
    """Load catalog YAML file and return parsed content."""
    with open(catalog_path, 'r') as f:
        return yaml.safe_load(f)


def extract_versions_from_dict(version_dict: Dict) -> Set[str]:
    """Extract version values from a dictionary, filtering out empty strings and pre-release versions."""
    versions = set()
    if isinstance(version_dict, dict):
        for key, value in version_dict.items():
            # Skip feature/pre-release versions (containing 'feature' or 'pre')
            if key and ('feature' in key.lower() or 'pre' in str(value).lower()):
                continue
            if value and value != "":
                versions.add(value)
    return versions


def load_extras_file(extras_path: str) -> List[Dict]:
    """Load extras YAML file and return list of images."""
    with open(extras_path, 'r') as f:
        data = yaml.safe_load(f)
        return data.get('extra_images', [])


def generate_catalog_isc(catalog_name: str, catalog_digest: str) -> None:
    """Generate ISC for the catalog image itself."""

    # Extract architecture from catalog name (e.g., v9-260430-amd64 -> amd64)
    import re
    match = re.match(r'v\d+-\d{6}-(.+)', catalog_name)
    if not match:
        print(f"Warning: Could not extract architecture from catalog name: {catalog_name}")
        return

    arch = match.group(1)
    output_dir = "catalogs"
    output_file = f"{catalog_name}.yaml"
    output_path = os.path.join(output_dir, output_file)

    if os.path.exists(output_path):
        print(f"Catalog ISC {output_path} already exists. Skipping generation.")
        return

    # Create ISC with catalog image
    isc = deepcopy(ISC_TEMPLATE)

    # Remove archiveSize from catalog ISC (not needed for single image)
    if 'archiveSize' in isc:
        del isc['archiveSize']

    catalog_image = dict(
        name=f"icr.io/cpopen/ibm-maximo-operator-catalog:{catalog_name}@{catalog_digest}"
    )
    isc["mirror"]["additionalImages"].append(catalog_image)  # pyright: ignore

    os.makedirs(output_dir, exist_ok=True)

    with open(output_path, 'w') as file:
        yaml.dump(isc, file, indent=2)

    print(f"Generated catalog ISC: {output_path}")


def generate_extras_isc(extras_name: str, extras_version: str, extras_path: str) -> None:
    """Generate ISC from extras YAML file."""

    # Determine output path based on extras type
    if extras_name == "mongodb-ce":
        output_dir = f"packages/mongodb-ce/{extras_version.split('.')[0]}.{extras_version.split('.')[1]}/amd64"
        output_file = f"mongodb-ce-{extras_version}-amd64.yaml"
    elif extras_name == "amlen":
        output_dir = f"packages/amlen/{extras_version.split('.')[0]}.{extras_version.split('.')[1]}/amd64"
        output_file = f"amlen-{extras_version}-amd64.yaml"
    else:
        output_dir = f"packages/{extras_name}/{extras_version}/amd64"
        output_file = f"{extras_name}-{extras_version}-amd64.yaml"

    output_path = os.path.join(output_dir, output_file)

    if os.path.exists(output_path):
        print(f"File {output_path} already exists. Skipping generation.")
        return

    # Load extras images
    try:
        extra_images = load_extras_file(extras_path)
    except FileNotFoundError:
        print(f"Warning: Extras file not found: {extras_path}")
        return
    except Exception as e:
        print(f"Warning: Error loading extras file {extras_path}: {e}")
        return

    if not extra_images:
        print(f"Warning: No images found in extras file: {extras_path}")
        return

    # Create ISC
    isc = deepcopy(ISC_TEMPLATE)

    for image in extra_images:
        registry = image.get('registry', '')
        name = image.get('name', '')
        tag = image.get('tag', '')
        digest = image.get('digest', '')

        if registry and name and tag and digest:
            image_fqn = dict(
                name=f"{registry}/{name}:{tag}@{digest}"
            )
            isc["mirror"]["additionalImages"].append(image_fqn)  # pyright: ignore

    if len(isc["mirror"]["additionalImages"]) > 0:  # pyright: ignore
        # Sort additionalImages by the name field
        isc["mirror"]["additionalImages"].sort(key=lambda x: x["name"])  # pyright: ignore

        os.makedirs(output_dir, exist_ok=True)

        with open(output_path, 'w') as file:
            yaml.dump(isc, file, indent=2)

        print(f"Generated extras ISC: {output_path}")


def extract_catalog_date(catalog_filename: str) -> Optional[int]:
    """
    Extract date from catalog filename (e.g., v9-260326-amd64.yaml -> 260326).
    Returns date as integer for comparison, or None if format doesn't match.
    """
    import re
    match = re.match(r'v\d+-(\d{6})-.*\.yaml', catalog_filename)
    if match:
        return int(match.group(1))
    return None


def find_catalogs(catalogs_dir: str, min_date: int = 260129) -> List[str]:
    """
    Find all catalog files in directory that are newer than min_date.
    Returns sorted list of full paths.
    """
    import glob

    if not os.path.exists(catalogs_dir):
        return []

    catalog_files = []
    pattern = os.path.join(catalogs_dir, "v9-*.yaml")

    for filepath in glob.glob(pattern):
        filename = os.path.basename(filepath)
        date = extract_catalog_date(filename)
        if date and date > min_date:
            catalog_files.append(filepath)

    # Sort by date (extracted from filename)
    catalog_files.sort(key=lambda x: extract_catalog_date(os.path.basename(x)) or 0)

    return catalog_files


def process_catalog(catalog_path: str) -> Dict[str, List[str]]:
    """
    Process catalog file and extract versions for all CASE packages.
    Returns a dictionary mapping argument names to version lists.
    """
    catalog_data = load_catalog_file(catalog_path)
    versions_map = {}

    # Mapping from catalog keys to our argument names
    # Based on compare_catalogs.py and catalog structure
    catalog_mappings = {
        # Dependencies
        'tsm_version': 'tsm',
        'dd_version': 'data_dictionary',
        'sls_version': 'sls',
        'db2u_version': 'db2u',
        'common_svcs_version': 'cp_common_services',
        'ibm_zen_version': 'zen',
        'cp4d_platform_version': 'cp_datacore',
        'ibm_licensing_version': 'licensing',
        'ccs_build': 'ccs',
        'postgress_version': 'cloud_native_postgresql',
        'wsl_version': 'wsl',
        'wsl_runtimes_version': 'wsl_runtimes',
        'elasticsearch_version': 'elasticsearch_operator',
        'opensearch_version': 'opensearch_operator',
        'wml_version': 'wml_cpd',
        'spark_version': 'analyticsengine',
        'cognos_version': 'cognos_analytics_prod',
        # MAS Applications
        'mas_core_version': 'mas',
        'mas_assist_version': 'assist',
        'mas_iot_version': 'iot',
        'mas_manage_version': 'manage',
        'mas_monitor_version': 'monitor',
        'mas_optimizer_version': 'optimizer',
        'mas_predict_version': 'predict',
        'mas_visualinspection_version': 'mvi',
        'mas_facilities_version': 'facilities',
        'aiservice_version': 'aiservice',
    }

    for catalog_key, arg_name in catalog_mappings.items():
        if catalog_key in catalog_data:
            value = catalog_data[catalog_key]
            if isinstance(value, dict):
                # Handle versioned dictionaries (like mas_core_version)
                versions = extract_versions_from_dict(value)
                if versions:
                    versions_map[arg_name] = sorted(versions)
            elif isinstance(value, str) and value:
                # Handle simple version strings
                versions_map[arg_name] = [value]

    # Special handling for manage-icd (same versions as manage)
    if 'manage' in versions_map:
        versions_map['manage_icd'] = versions_map['manage'].copy()

    # Handle extras versions
    if 'mongo_extras_version_default' in catalog_data:
        versions_map['mongo_extras'] = [catalog_data['mongo_extras_version_default']]

    if 'amlen_extras_version' in catalog_data:
        versions_map['amlen_extras'] = [catalog_data['amlen_extras_version']]

    return versions_map


def generate_isc(case_name, case_version, arch="amd64", include_group=None, exclude_group=None, child_name=None, db2_variant=None) -> None:
    """Generate image set configuration by executing oc ibm-pak commands."""

    # Extract major.minor version (first two components)
    version_parts = case_version.split('.')
    major_minor = f"{version_parts[0]}.{version_parts[1]}"

    # Strip extended semver (everything after '+') for file naming
    file_version = case_version.split('+')[0]

    # Handle DB2 operator variants (s11/s12) and ICD
    effective_case_name = case_name
    if db2_variant:
        effective_case_name = f"{case_name}-{db2_variant}"
    if child_name:
        effective_case_name = f"{case_name}-{child_name}"
    output_path = f"packages/{effective_case_name}/{major_minor}/{arch}/{effective_case_name}-{file_version}-{arch}.yaml"

    images_csv_path = os.path.expanduser(
        f"~/.ibm-pak/data/cases/{case_name}/{case_version}/{case_name}-{case_version}-images.csv"
    )

    if os.path.exists(output_path):
        print(f"File {output_path} already exists. Skipping generation.")
        return

    if not os.path.exists(images_csv_path):
        # Execute oc ibm-pak get command
        cmd = [
            "oc", "ibm-pak", "get", case_name,
            "--version", case_version,
            "--skip-dependencies"
        ]

        result = run_command(cmd)
        if result != 0:
            sys.exit(1)

    isc = deepcopy(ISC_TEMPLATE)

    # Get list of images from images.csv
    with open(images_csv_path, 'r') as file:  # Open the file in read mode
        reader = csv.reader(file)  # Create a CSV reader object
        next(reader)  # Skip the header row
        for row in reader:  # Iterate over each row in the CSV file
            # registry,image_name,tag,digest,mtype,os,arch,variant,insecure,digest_source,image_type,groups
            registry = row[0]
            name = row[1]
            tag = row[2]
            digest = row[3]
            architecture = row[6]
            groups=row[11]

            # Apply DB2 variant filtering if specified
            if db2_variant:
                # Filter based on tag prefix (handles "s11.", "11.", "standalone-11." formats)
                if db2_variant == "s11":
                    # For s11 variant: exclude images with s12, 12, or standalone-12 prefix
                    if tag.startswith("s12.") or tag.startswith("12.") or tag.startswith("standalone-12."):
                        continue
                elif db2_variant == "s12":
                    # For s12 variant: exclude images with s11, 11, or standalone-11 prefix
                    if tag.startswith("s11.") or tag.startswith("11.") or tag.startswith("standalone-11."):
                        continue

            image_fqn = dict(
                name=f"{registry}/{name}:{tag}@{digest}"
            )

            # Note: not all IBM products properly define the architecture field so we need to also match "" as amd64
            if (architecture == arch or (arch == "amd64" and architecture == "")) and groups != exclude_group and (include_group is None or groups == include_group):
                isc["mirror"]["additionalImages"].append(image_fqn)  # pyright: ignore

    if len(isc["mirror"]["additionalImages"]) > 0:  # pyright: ignore
        # Sort additionalImages by the name field
        isc["mirror"]["additionalImages"].sort(key=lambda x: x["name"])  # pyright: ignore

        os.makedirs(os.path.join("packages", effective_case_name, major_minor, arch), exist_ok=True)

        with open(output_path, 'w') as file:
            yaml.dump(isc, file, indent=2)


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Generate ImageSetConfiguration files for IBM MAS CASE packages from catalog data.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --catalog ../python-devops/src/mas/devops/data/catalogs/v9-260326-amd64.yaml
  %(prog)s --all-catalogs
        """
    )

    # Mutually exclusive group for catalog processing
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--catalog', type=str,
                       help='Path to catalog YAML file (e.g., ../python-devops/src/mas/devops/data/catalogs/v9-260326-amd64.yaml)')
    group.add_argument('--all-catalogs', action='store_true',
                       help='Process all catalogs in ../python-devops/src/mas/devops/data/catalogs/ newer than v9-260129')

    return parser.parse_args()


def process_single_catalog(catalog_path: str) -> bool:
    """
    Process a single catalog file and generate all ISCs.
    Returns True if any CASE packages were processed.
    """
    print(f"\n{'='*80}")
    print(f"Processing catalog: {catalog_path}")
    print(f"{'='*80}")

    try:
        catalog_data = load_catalog_file(catalog_path)
        catalog_versions = process_catalog(catalog_path)
        print(f"Extracted versions for {len(catalog_versions)} CASE packages from catalog\n")
    except FileNotFoundError:
        print(f"Error: Catalog file not found: {catalog_path}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error processing catalog file: {e}", file=sys.stderr)
        return False

    # Generate catalog ISC if catalog_digest is present
    if 'catalog_digest' in catalog_data:
        catalog_digest = catalog_data['catalog_digest']
        # Extract catalog name from path (e.g., v9-260430-amd64)
        catalog_filename = os.path.basename(catalog_path)
        catalog_name = catalog_filename.replace('.yaml', '')
        print(f"Generating catalog ISC for {catalog_name} with digest {catalog_digest}")
        generate_catalog_isc(catalog_name, catalog_digest)
    else:
        print("Warning: No catalog_digest found in catalog data file")

    # Track if any CASE was processed
    processed = False

    # Process ibm-sls
    if 'sls' in catalog_versions:
        versions = catalog_versions['sls']
        print(f"Generating ISCs for ibm-sls versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-sls",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-mas
    if 'mas' in catalog_versions:
        versions = catalog_versions['mas']
        print(f"Generating ISCs for ibm-mas versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-truststore-mgr
    if 'tsm' in catalog_versions:
        versions = catalog_versions['tsm']
        print(f"Generating ISCs for ibm-truststore-mgr versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-truststore-mgr",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-mas-manage (excludes ICD images)
    if 'manage' in catalog_versions:
        versions = catalog_versions['manage']
        print(f"Generating ISCs for ibm-mas-manage versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas-manage",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"],
            exclude_group="ibmmasMaximoIT"
        )
        processed = True

    # Process ibm-mas-manage ICD (ICD images only)
    if 'manage_icd' in catalog_versions:
        versions = catalog_versions['manage_icd']
        print(f"Generating ISCs for ibm-mas-manage-icd versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas-manage",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"],
            include_group="ibmmasMaximoIT",
            child_name="icd"
        )
        processed = True

    # Process ibm-mas-monitor (amd64 only)
    if 'monitor' in catalog_versions:
        versions = catalog_versions['monitor']
        print(f"Generating ISCs for ibm-mas-monitor versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas-monitor",
            case_versions=versions,
            architectures=["amd64"]
        )
        processed = True

    # Process ibm-mas-optimizer (amd64 only)
    if 'optimizer' in catalog_versions:
        versions = catalog_versions['optimizer']
        print(f"Generating ISCs for ibm-mas-optimizer versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas-optimizer",
            case_versions=versions,
            architectures=["amd64"]
        )
        processed = True

    # Process ibm-mas-visualinspection
    if 'mvi' in catalog_versions:
        versions = catalog_versions['mvi']
        print(f"Generating ISCs for ibm-mas-visualinspection versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas-visualinspection",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-mas-predict (amd64 only)
    if 'predict' in catalog_versions:
        versions = catalog_versions['predict']
        print(f"Generating ISCs for ibm-mas-predict versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas-predict",
            case_versions=versions,
            architectures=["amd64"]
        )
        processed = True

    # Process ibm-mas-assist (amd64 only)
    if 'assist' in catalog_versions:
        versions = catalog_versions['assist']
        print(f"Generating ISCs for ibm-mas-assist versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas-assist",
            case_versions=versions,
            architectures=["amd64"]
        )
        processed = True

    # Process ibm-mas-iot (amd64 only)
    if 'iot' in catalog_versions:
        versions = catalog_versions['iot']
        print(f"Generating ISCs for ibm-mas-iot versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas-iot",
            case_versions=versions,
            architectures=["amd64"]
        )
        processed = True

    # Process ibm-mas-facilities (amd64 only)
    if 'facilities' in catalog_versions:
        versions = catalog_versions['facilities']
        print(f"Generating ISCs for ibm-mas-facilities versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-mas-facilities",
            case_versions=versions,
            architectures=["amd64"]
        )
        processed = True

    # Process ibm-data-dictionary
    if 'data_dictionary' in catalog_versions:
        versions = catalog_versions['data_dictionary']
        print(f"Generating ISCs for ibm-data-dictionary versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-data-dictionary",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-aiservice
    if 'aiservice' in catalog_versions:
        versions = catalog_versions['aiservice']
        print(f"Generating ISCs for ibm-aiservice versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-aiservice",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-cp-common-services
    if 'cp_common_services' in catalog_versions:
        versions = catalog_versions['cp_common_services']
        print(f"Generating ISCs for ibm-cp-common-services versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-cp-common-services",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-zen
    if 'zen' in catalog_versions:
        versions = catalog_versions['zen']
        print(f"Generating ISCs for ibm-zen versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-zen",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-cp-datacore
    if 'cp_datacore' in catalog_versions:
        versions = catalog_versions['cp_datacore']
        print(f"Generating ISCs for ibm-cp-datacore versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-cp-datacore",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-licensing
    if 'licensing' in catalog_versions:
        versions = catalog_versions['licensing']
        print(f"Generating ISCs for ibm-licensing versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-licensing",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-ccs
    if 'ccs' in catalog_versions:
        versions = catalog_versions['ccs']
        print(f"Generating ISCs for ibm-ccs versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-ccs",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-cloud-native-postgresql
    if 'cloud_native_postgresql' in catalog_versions:
        versions = catalog_versions['cloud_native_postgresql']
        print(f"Generating ISCs for ibm-cloud-native-postgresql versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-cloud-native-postgresql",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-datarefinery
    if 'datarefinery' in catalog_versions:
        versions = catalog_versions['datarefinery']
        print(f"Generating ISCs for ibm-datarefinery versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-datarefinery",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-wsl
    if 'wsl' in catalog_versions:
        versions = catalog_versions['wsl']
        print(f"Generating ISCs for ibm-wsl versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-wsl",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-wsl-runtimes
    if 'wsl_runtimes' in catalog_versions:
        versions = catalog_versions['wsl_runtimes']
        print(f"Generating ISCs for ibm-wsl-runtimes versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-wsl-runtimes",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-elasticsearch-operator
    if 'elasticsearch_operator' in catalog_versions:
        versions = catalog_versions['elasticsearch_operator']
        print(f"Generating ISCs for ibm-elasticsearch-operator versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-elasticsearch-operator",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-opensearch-operator
    if 'opensearch_operator' in catalog_versions:
        versions = catalog_versions['opensearch_operator']
        print(f"Generating ISCs for ibm-opensearch-operator versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-opensearch-operator",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-wml-cpd
    if 'wml_cpd' in catalog_versions:
        versions = catalog_versions['wml_cpd']
        print(f"Generating ISCs for ibm-wml-cpd versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-wml-cpd",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-analyticsengine
    if 'analyticsengine' in catalog_versions:
        versions = catalog_versions['analyticsengine']
        print(f"Generating ISCs for ibm-analyticsengine versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-analyticsengine",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-cognos-analytics-prod
    if 'cognos_analytics_prod' in catalog_versions:
        versions = catalog_versions['cognos_analytics_prod']
        print(f"Generating ISCs for ibm-cognos-analytics-prod versions: {', '.join(versions)}")
        generate_iscs(
            case_name="ibm-cognos-analytics-prod",
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"]
        )
        processed = True

    # Process ibm-db2uoperator (generates both s11 and s12 variants)
    if 'db2u' in catalog_versions:
        versions = catalog_versions['db2u']
        print(f"Generating ISCs for ibm-db2uoperator versions (s11 and s12 variants): {', '.join(versions)}")
        generate_db2_iscs(
            case_versions=versions,
            architectures=["amd64", "ppc64le", "s390x"],
            include_group="ibmdb2u-standalone"
        )
        processed = True

    # Process MongoDB extras
    if 'mongo_extras' in catalog_versions:
        for version in catalog_versions['mongo_extras']:
            print(f"Generating ISC for MongoDB extras version: {version}")
            # Determine path to extras file (assuming ansible-devops is sibling to image-set-configs)
            extras_path = os.path.join("..", "ansible-devops", "ibm", "mas_devops", "roles",
                                      "mirror_extras_prepare", "vars", f"mongoce_{version}.yml")
            generate_extras_isc("mongodb-ce", version, extras_path)
            processed = True

    # Process Amlen extras
    if 'amlen_extras' in catalog_versions:
        for version in catalog_versions['amlen_extras']:
            print(f"Generating ISC for Amlen extras version: {version}")
            # Determine path to extras file (assuming ansible-devops is sibling to image-set-configs)
            extras_path = os.path.join("..", "ansible-devops", "ibm", "mas_devops", "roles",
                                      "mirror_extras_prepare", "vars", f"amlen_{version}.yml")
            generate_extras_isc("amlen", version, extras_path)
            processed = True

    if not processed:
        print("Warning: No CASE packages found in catalog.", file=sys.stderr)

    return processed


def resolve_catalog_path(catalog_input: str) -> str:
    """
    Resolve catalog path from input.
    If input is a short name (e.g., 'v9-260326-amd64'), generate full path.
    If input is already a path, return as-is.
    """
    # If it's already a path (contains / or \), return as-is
    if '/' in catalog_input or '\\' in catalog_input:
        return catalog_input

    # If it doesn't have .yaml extension, add it
    if not catalog_input.endswith('.yaml'):
        catalog_input = f"{catalog_input}.yaml"

    # Generate full path
    catalogs_dir = os.path.join("..", "python-devops", "src", "mas", "devops", "data", "catalogs")
    return os.path.join(catalogs_dir, catalog_input)


def main():
    """Main entry point for the script."""
    args = parse_arguments()

    if args.all_catalogs:
        # Process all catalogs in the python-devops directory
        catalogs_dir = os.path.join("..", "python-devops", "src", "mas", "devops", "data", "catalogs")

        if not os.path.exists(catalogs_dir):
            print(f"Error: Catalogs directory not found: {catalogs_dir}", file=sys.stderr)
            print("Make sure python-devops repository is in the same parent directory as image-set-configs", file=sys.stderr)
            sys.exit(1)

        catalog_files = find_catalogs(catalogs_dir, min_date=260129)

        if not catalog_files:
            print(f"No catalogs found newer than v9-260129 in {catalogs_dir}", file=sys.stderr)
            sys.exit(1)

        print(f"\nFound {len(catalog_files)} catalog(s) to process:")
        for catalog in catalog_files:
            print(f"  - {os.path.basename(catalog)}")

        total_processed = 0
        for catalog_path in catalog_files:
            if process_single_catalog(catalog_path):
                total_processed += 1

        print(f"\n{'='*80}")
        print(f"Processed {total_processed} of {len(catalog_files)} catalogs successfully")
        print(f"{'='*80}")

    else:
        # Process single catalog
        catalog_path = resolve_catalog_path(args.catalog)
        if process_single_catalog(catalog_path):
            print("\nISC generation complete!")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
