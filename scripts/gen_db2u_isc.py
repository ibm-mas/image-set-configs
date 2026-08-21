#!/usr/bin/env python3
"""
Generate ibm-db2uoperator-s11 and ibm-db2uoperator-s12 ISC files
directly from two CASE bundle inventory files, replicating exactly
what create_iscs.py does via oc ibm-pak.

Sources used:
  - inventory/db2uOperatorStandaloneSetup/resources.yaml  → OLM operator images
    (db2u-operator, db2u-day2-operator, ibm-db2uoperator-bundle/catalog)
  - inventory/db2uOperatorStandalone/resources.yaml       → db2u workload images
    (db2u, db2u.instdb, etcd, etc.) filtered by arch and s11/s12 variant

Usage:
  python3 gen_db2u_isc.py <case-bundle-dir> <case-version> <image-set-configs-dir>

  <case-bundle-dir>  — directory produced by extracting the ibm-db2uoperator tgz
                       (contains inventory/, digests.yaml, etc.)
"""

import sys
import yaml
from copy import deepcopy
from pathlib import Path

ISC_TEMPLATE = dict(
    apiVersion="mirror.openshift.io/v1alpha2",
    kind="ImageSetConfiguration",
    archiveSize=2,
    mirror=dict(additionalImages=[])
)

ARCHITECTURES = ["amd64", "ppc64le", "s390x"]


def load_resources(path):
    with open(path) as f:
        return yaml.safe_load(f)


def get_arch(platform):
    arch = platform.get("architecture", "")
    if arch in ("amd64", "ppc64le", "s390x"):
        return arch
    return None


def is_s11_image(tag):
    """Exclude s12-series workload images (12.x / standalone-12.x)."""
    return not (tag.startswith("s12.") or tag.startswith("12.") or tag.startswith("standalone-12."))


def is_s12_image(tag):
    """Exclude s11-series workload images (11.x / standalone-11.x)."""
    return not (tag.startswith("s11.") or tag.startswith("11.") or tag.startswith("standalone-11."))


def collect_operator_images(setup_resources_path):
    """
    Return all images from db2uOperatorStandaloneSetup/resources.yaml.
    These are the arch-neutral OLM operator images (bundle, catalog, operator).
    They have no platform field so we include them in every arch's ISC.
    """
    data = load_resources(setup_resources_path)
    images = data["resources"]["resourceDefs"]["containerImages"]
    results = []
    for img in images:
        registries = img.get("registries", [])
        if not registries:
            continue
        results.append(f"{registries[0]['host']}/{img['image']}:{img['tag']}@{img['digest']}")
    return results


def generate_iscs(case_bundle_dir, case_version, output_dir):
    bundle = Path(case_bundle_dir)
    standalone_path = bundle / "inventory" / "db2uOperatorStandalone" / "resources.yaml"
    setup_path = bundle / "inventory" / "db2uOperatorStandaloneSetup" / "resources.yaml"

    workload_data = load_resources(standalone_path)
    workload_images = workload_data["resources"]["resourceDefs"]["containerImages"]
    operator_images = collect_operator_images(setup_path)

    file_version = case_version.split("+")[0]
    version_parts = file_version.split(".")
    major_minor = f"{version_parts[0]}.{version_parts[1]}"

    for arch in ARCHITECTURES:
        for variant, filter_fn in [("s11", is_s11_image), ("s12", is_s12_image)]:
            package_name = f"ibm-db2uoperator-{variant}"
            isc = deepcopy(ISC_TEMPLATE)

            # Add OLM operator images (same for every arch/variant)
            for img_name in operator_images:
                isc["mirror"]["additionalImages"].append({"name": img_name})

            # Add arch/variant-filtered workload images
            for img in workload_images:
                groups = img.get("groups", {})
                if "ibmdb2u-standalone" not in groups:
                    continue

                if get_arch(img.get("platform", {})) != arch:
                    continue

                if not filter_fn(img["tag"]):
                    continue

                registries = img.get("registries", [])
                if not registries:
                    continue

                isc["mirror"]["additionalImages"].append({
                    "name": f"{registries[0]['host']}/{img['image']}:{img['tag']}@{img['digest']}"
                })

            if not isc["mirror"]["additionalImages"]:
                print(f"WARNING: no images found for {package_name} {arch} — skipping")
                continue

            isc["mirror"]["additionalImages"].sort(key=lambda x: x["name"])

            out_path = Path(output_dir) / "packages" / package_name / major_minor / arch
            out_path.mkdir(parents=True, exist_ok=True)
            out_file = out_path / f"{package_name}-{file_version}-{arch}.yaml"

            with open(out_file, "w") as f:
                yaml.dump(isc, f, indent=2)

            print(f"Generated: {out_file}  ({len(isc['mirror']['additionalImages'])} images)")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <case-bundle-dir> <case-version> <image-set-configs-dir>")
        sys.exit(1)

    generate_iscs(sys.argv[1], sys.argv[2], sys.argv[3])
