#!/usr/bin/env python3
"""
Convert script for IBM MAS CASE package operations.
Equivalent to convert.sh bash script.
"""

import csv
import subprocess
import sys
import os
from copy import deepcopy
from typing import List
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


def generate_isc(case_name, case_version, arch="amd64", include_group=None, exclude_group=None, child_name=None) -> None:
    """Generate image set configuration by executing oc ibm-pak commands."""

    output_path = f"packages/{case_name}/{arch}/{case_name}-{case_version}-{arch}.yaml"
    if child_name is not None:
        output_path = f"packages/{case_name}/extras/{child_name}/{arch}/{case_name}-{case_version}-{arch}.yaml"

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
            image_fqn = dict(
                name=f"{registry}/{name}:{tag}@{digest}"
            )
            if architecture == arch and groups != exclude_group and (include_group is None or groups == include_group):
                isc["mirror"]["additionalImages"].append(image_fqn)  # pyright: ignore

    if len(isc["mirror"]["additionalImages"]) > 0:  # pyright: ignore
        if child_name is not None:
            os.makedirs(os.path.join("packages", case_name, "extras", child_name, arch), exist_ok=True)
        else:
            os.makedirs(os.path.join("packages", case_name, arch), exist_ok=True)

        with open(output_path, 'w') as file:
            yaml.dump(isc, file, indent=2)

if __name__ == "__main__":
    # Truststore Mgr
    # -------------------------------------------------------------------------
    # generate_iscs(case_name="ibm-truststore-mgr", case_versions=[
    #     "1.5.0", "1.5.1", "1.5.2", "1.5.3", "1.5.4", "1.6.0", "1.6.1", "1.6.2", "1.7.0", "1.7.1", "1.7.2"
    # ])

    # Suite License Service
    # -------------------------------------------------------------------------
    # generate_iscs(case_name="ibm-sls", case_versions=[
    #     "3.0.1", "3.1.0", "3.2.0", "3.2.1", "3.2.3", "3.2.4", "3.3.0" , "3.3.1",
    #     "3.4.0", "3.4.1", "3.5.0", "3.6.0", "3.7.0", "3.8.0", "3.8.1", "3.9.0", "3.9.1", "3.10.0", "3.10.1",
    #     "3.10.2", "3.10.3", "3.11.0", "3.11.1", "3.12.0", "3.12.1", "3.12.2", "3.12.3", "3.12.4", "3.12.5"
    # ])

    # Maximo Application Suite Core Platform
    # -------------------------------------------------------------------------
    # generate_iscs(case_name="ibm-mas", architectures=["amd64"], case_versions=[
    #     "8.10.0", "8.10.1", "8.10.2", "8.10.3", "8.10.4", "8.10.5", "8.10.6", "8.10.7", "8.10.8", "8.10.9", "8.10.10",
    #     "8.10.11", "8.10.12", "8.10.13", "8.10.14", "8.10.15", "8.10.16", "8.10.17", "8.10.18", "8.10.19", "8.10.20",
    #     "8.10.21", "8.10.22", "8.10.23", "8.10.24", "8.10.25", "8.10.26", "8.10.27", "8.10.28", "8.10.29", "8.10.30",
    #     "8.10.31", "8.10.32", "8.10.33"
    # ])

    # generate_iscs(case_name="ibm-mas", architectures=["amd64"], case_versions=[
    #     "8.11.0", "8.11.1", "8.11.2", "8.11.3", "8.11.4", "8.11.5", "8.11.6", "8.11.7", "8.11.8", "8.11.9", "8.11.10",
    #     "8.11.11", "8.11.12", "8.11.13", "8.11.14", "8.11.15", "8.11.16", "8.11.17", "8.11.18", "8.11.19", "8.11.20",
    #     "8.11.21", "8.11.22", "8.11.23", "8.11.24", "8.11.25", "8.11.26", "8.11.27", "8.11.28", "8.11.29", "8.11.30"
    # ])

    # generate_iscs(case_name="ibm-mas", architectures=["amd64"], case_versions=["9.0.0", "9.0.1", "9.0.2", "9.0.3"])
    # generate_iscs(case_name="ibm-mas", case_versions=["9.0.5", "9.0.6", "9.0.7", "9.0.8", "9.0.9", "9.0.10"])
    # generate_iscs(case_name="ibm-mas", case_versions=["9.1.0", "9.1.1", "9.1.2", "9.1.3", "9.1.4", "9.1.5", "9.1.6", "9.1.7", "9.1.8"])

    # Maximo Manage
    # -------------------------------------------------------------------------
    # generate_iscs(case_name="ibm-mas-manage", case_versions=[
    #     "8.6.0", "8.6.1", "8.6.2", "8.6.3", "8.6.4", "8.6.5", "8.6.6", "8.6.7", "8.6.8", "8.6.9", "8.6.10",
    #     "8.6.11", "8.6.12", "8.6.13", "8.6.14", "8.6.15", "8.6.16", "8.6.17", "8.6.18", "8.6.19", "8.6.20",
    #     "8.6.21", "8.6.22", "8.6.23", "8.6.24", "8.6.25", "8.6.26", "8.6.27", "8.6.28", "8.6.29", "8.6.30",
    #     "8.6.31", "8.6.32", "8.6.33", "8.6.34"
    # ], exclude_group="ibmmasMaximoIT")
    # # Note: 8.7.0 was a botched release, so we don't include it here
    # generate_iscs(case_name="ibm-mas-manage", case_versions=[
    #     "8.7.1", "8.7.2", "8.7.3", "8.7.4", "8.7.5", "8.7.6", "8.7.7", "8.7.8", "8.7.9", "8.7.10",
    #     "8.7.11", "8.7.12", "8.7.13", "8.7.14", "8.7.15", "8.7.16", "8.7.17", "8.7.18", "8.7.19", "8.7.20",
    #     "8.7.21", "8.7.22", "8.7.23", "8.7.24", "8.7.25", "8.7.26", "8.7.27", "8.7.28"
    # ], exclude_group="ibmmasMaximoIT")
    # generate_iscs(case_name="ibm-mas-manage", case_versions=[
    #     "9.0.0", "9.0.1", "9.0.2", "9.0.3", "9.0.4", "9.0.5", "9.0.6", "9.0.7", "9.0.8", "9.0.9", "9.0.10",
    #     "9.0.11", "9.0.12", "9.0.13", "9.0.14", "9.0.15", "9.0.16", "9.0.17", "9.0.18", "9.0.19", "9.0.20",
    #     "9.0.21"
    # ], exclude_group="ibmmasMaximoIT")
    # generate_iscs(case_name="ibm-mas-manage", case_versions=[
    #     "9.1.0", "9.1.1", "9.1.2", "9.1.3", "9.1.4", "9.1.5", "9.1.6", "9.1.7", "9.1.8"
    # ], exclude_group="ibmmasMaximoIT")


    # Maximo Manage - ICD
    # -------------------------------------------------------------------------
    # generate_iscs(case_name="ibm-mas-manage", case_versions=[
    #     "8.6.0", "8.6.1", "8.6.2", "8.6.3", "8.6.4", "8.6.5", "8.6.6", "8.6.7", "8.6.8", "8.6.9", "8.6.10",
    #     "8.6.11", "8.6.12", "8.6.13", "8.6.14", "8.6.15", "8.6.16", "8.6.17", "8.6.18", "8.6.19", "8.6.20",
    #     "8.6.21", "8.6.22", "8.6.23", "8.6.24", "8.6.25", "8.6.26", "8.6.27", "8.6.28", "8.6.29", "8.6.30",
    #     "8.6.31", "8.6.32", "8.6.33", "8.6.34"
    # ], include_group="ibmmasMaximoIT", child_name="icd")
    # # Note: 8.7.0 was a botched release, so we don't include it here
    # generate_iscs(case_name="ibm-mas-manage", case_versions=[
    #     "8.7.1", "8.7.2", "8.7.3", "8.7.4", "8.7.5", "8.7.6", "8.7.7", "8.7.8", "8.7.9", "8.7.10",
    #     "8.7.11", "8.7.12", "8.7.13", "8.7.14", "8.7.15", "8.7.16", "8.7.17", "8.7.18", "8.7.19", "8.7.20",
    #     "8.7.21", "8.7.22", "8.7.23", "8.7.24", "8.7.25", "8.7.26", "8.7.27", "8.7.28"
    # ], include_group="ibmmasMaximoIT", child_name="icd")
    # generate_iscs(case_name="ibm-mas-manage", case_versions=[
    #     "9.0.0", "9.0.1", "9.0.2", "9.0.3", "9.0.4", "9.0.5", "9.0.6", "9.0.7", "9.0.8", "9.0.9", "9.0.10",
    #     "9.0.11", "9.0.12", "9.0.13", "9.0.14", "9.0.15", "9.0.16", "9.0.17", "9.0.18", "9.0.19", "9.0.20",
    #     "9.0.21"
    # ], include_group="ibmmasMaximoIT", child_name="icd")
    # generate_iscs(case_name="ibm-mas-manage", case_versions=[
    #     "9.1.0", "9.1.1", "9.1.2", "9.1.3", "9.1.4", "9.1.5", "9.1.6", "9.1.7", "9.1.8"
    # ], include_group="ibmmasMaximoIT", child_name="icd")

    # Maximo Visual Inspection
    generate_iscs(case_name="ibm-mas-visualinspection", case_versions=[
        "8.8.0", "8.8.1", "8.8.2", "8.8.3", "8.8.4"
    ])
    generate_iscs(case_name="ibm-mas-visualinspection", case_versions=[
        "8.9.0", "8.9.1", "8.9.2", "8.9.3", "8.9.4", "8.9.5", "8.9.6", "8.9.7", "8.9.8", "8.9.9", "8.9.10",
        "8.9.11", "8.9.12", "8.9.13", "8.9.14", "8.9.15", "8.9.16", "8.9.17", "8.9.18", "8.9.19"
    ])
    generate_iscs(case_name="ibm-mas-visualinspection", case_versions=[
        "9.0.0", "9.0.1", "9.0.2", "9.0.3", "9.0.4", "9.0.5", "9.0.6", "9.0.7", "9.0.8", "9.0.9", "9.0.10",
        "9.0.11", "9.0.12", "9.0.13", "9.0.14", "9.0.15", "9.0.16"
    ])
    generate_iscs(case_name="ibm-mas-visualinspection", case_versions=[
        "9.1.0", "9.1.1", "9.1.2", "9.1.3", "9.1.4", "9.1.5", "9.1.6", "9.1.7"
    ])
