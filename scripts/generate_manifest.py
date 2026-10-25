#!/usr/bin/env python3
"""
Generate MANIFEST.md — a human-readable package manifest table for both
OLM CASE packages (packages/) and Helm chart ISCs (charts/).

Catalog reference URLs are added by scanning the local operator catalog repos:
  - MAS packages  → ../ibm-maximo-operator-catalog/config/<pkg>.yaml
  - CPD/dep pkgs  → ../ibm-maximo-operator-catalog/ibm-operator-catalog/<latest-curated-amd64>/

A "Version Mappings" section is also generated for packages where the CASE
bundle version differs from the operator bundle version inside the ISC YAML
(e.g. ibm-couchdb 1.0.13 CASE = couchdb-operator 2.2.1 operator bundle).

Usage:
    python3 scripts/generate_manifest.py
    python3 scripts/generate_manifest.py --output MANIFEST.md
"""

import argparse
import os
import re
import yaml
from collections import defaultdict
from packaging.version import Version, InvalidVersion

GITHUB_ISC_BASE  = "https://github.com/ibm-mas/image-set-configs/blob/master"
GITHUB_MAS_BASE  = "https://github.ibm.com/maximoappsuite/ibm-maximo-operator-catalog/blob/master"
CATALOG_REPO     = "../ibm-maximo-operator-catalog"

# ---------------------------------------------------------------------------
# OLM groupings
# ---------------------------------------------------------------------------
OLM_GROUPS = {
    "IBM Maximo Application Suite": [
        "ibm-mas",
        "ibm-mas-aibroker",
        "ibm-mas-arcgis",
        "ibm-mas-assist",
        "ibm-mas-facilities",
        "ibm-mas-iot",
        "ibm-mas-manage",
        "ibm-mas-manage-icd",
        "ibm-mas-monitor",
        "ibm-mas-optimizer",
        "ibm-mas-predict",
        "ibm-mas-visualinspection",
        "ibm-sls",
        "ibm-truststore-mgr",
        "ibm-data-dictionary",
        "ibm-aiservice",
        "ibm-aiservice-tenant",
    ],
    "IBM Cloud Pak for Data": [
        "ibm-cp-common-services",
        "ibm-zen",
        "ibm-cp-datacore",
        "ibm-licensing",
        "ibm-ccs",
        "ibm-cloud-native-postgresql",
        "ibm-datarefinery",
        "ibm-wsl",
        "ibm-wsl-runtimes",
        "ibm-elasticsearch-operator",
        "ibm-opensearch-operator",
        "ibm-redis-cp",
        "ibm-wml-cpd",
        "ibm-analyticsengine",
        "ibm-cognos-analytics-prod",
        "ibm-db2uoperator-s11",
        "ibm-db2uoperator-s12",
    ],
    "Other Dependencies": [
        "ibm-couchdb",
        "mongodb-ce",
        "amlen",
        "minio",
        "opendatahub",
    ],
}

# ---------------------------------------------------------------------------
# Mapping: our package dir name → (catalog_subdir, our_channel → catalog_channel)
#
# For MAS packages the source is config/<file>.yaml; the key is None.
# For CPD/dep packages the source is ibm-operator-catalog/<curated>/<subdir>/catalog.yaml.
#
# channel_map: fn(our_channel_str) -> catalog_channel_str  (or None = skip)
# ---------------------------------------------------------------------------

def _mas_x(ch):
    """'9.2' -> '9.2.x'"""
    return f"{ch}.x"

def _lookup(mapping: dict):
    """Return a channel_fn that does a direct dict lookup; returns None if key missing."""
    return lambda ch: mapping.get(ch)

# ---------------------------------------------------------------------------
# Explicit our_channel -> catalog_channel mappings for CPD packages.
#
# CPD operators use their own versioning in the catalog that does not match
# the channel directory names used in this repo.  The mapping is built by
# comparing packages/<component>/<channel>/ dirs against the olm.channel
# names present in the curated catalog.
# ---------------------------------------------------------------------------

# ibm-analyticsengine: 11.0->v8.0, 12.1->v9.1  (analyticsengine-operator)
_AE_CH     = {"11.0": "v8.0",   "12.1": "v9.1"}

# ibm-wml-cpd: 11.0->v8.0, 12.1->v9.1  (ibm-cpd-wml-operator)
_WML_CH    = {"11.0": "v8.0",   "12.1": "v9.1"}

# ibm-cp-datacore: 5.2->v6.2, 5.4->v6.4  (cpd-platform-operator)
_DATACORE_CH = {"5.2": "v6.2",  "5.4": "v6.4"}

# ibm-zen: 6.2->v6.2, 6.4->v6.4  (ibm-zen-operator) — direct match
_ZEN_CH    = {"6.2": "v6.2",   "6.4": "v6.4"}

# ibm-cp-common-services: 4.13->v4.13, 4.17->v4.17  (ibm-common-service-operator)
_CSVC_CH   = {"4.13": "v4.13", "4.17": "v4.17"}

# ibm-ccs: 11.0->v11.0, 12.1->v12.1  (ibm-cpd-ccs) — direct match with v prefix
_CCS_CH    = {"11.0": "v11.0", "12.1": "v12.1"}

# ibm-datarefinery: only 11.0 exists in curated catalog
_REFINERY_CH = {"11.0": "v11.0"}

# ibm-wsl / ibm-wsl-runtimes: only 11.0 exists in curated catalog
_WSL_CH    = {"11.0": "v11.0"}

# ibm-cloud-native-postgresql: only stable-v1.25 exists in curated catalog; 5.16 maps to it
_PG_CH     = {"5.16": "stable-v1.25"}

# ibm-licensing: 4.2->v4.2  (ibm-licensing-operator-app)
_LIC_CH    = {"4.2": "v4.2"}

# ibm-elasticsearch-operator: 1.1->v1.1
_ES_CH     = {"1.1": "v1.1"}

# ibm-opensearch-operator: 1.1->v1.1, 1.2->v1.1 (only v1.1 in curated)
_OS_CH     = {"1.1": "v1.1",  "1.2": "v1.1"}

# ibm-db2uoperator: catalog uses encoded names (only 3 channels exist in curated)
_DB2_CH    = {"7.7": "v120105.0", "7.6": "v120104.0", "7.3": "v110509.0"}

# ibm-couchdb: CASE 1.0 contains the v2.2 operator bundle
_COUCH_CH  = {"1.0": "v2.2"}

# minio: 1.0->v1.0
_MINIO_CH  = {"1.0": "v1.0"}


# package -> (catalog_subdir_or_None, channel_fn, config_file_for_MAS_or_None)
PACKAGE_CATALOG_MAP = {
    # ---- MAS packages (config/ dir) ----
    "ibm-mas":                  (None, _mas_x,                    "ibm-mas.yaml"),
    "ibm-mas-aibroker":         (None, _mas_x,                    "ibm-mas-aibroker.yaml"),
    "ibm-mas-arcgis":           (None, _mas_x,                    "ibm-mas-arcgis.yaml"),
    "ibm-mas-assist":           (None, lambda ch: f"{ch}.x",      "ibm-mas-assist.yaml"),
    "ibm-mas-facilities":       (None, _mas_x,                    "ibm-mas-facilities.yaml"),
    "ibm-mas-iot":              (None, lambda ch: f"{ch}.x",      "ibm-mas-iot.yaml"),
    "ibm-mas-manage":           (None, _mas_x,                    "ibm-mas-manage.yaml"),
    "ibm-mas-manage-icd":       (None, _mas_x,                    "ibm-mas-manage.yaml"),
    "ibm-mas-monitor":          (None, lambda ch: f"{ch}.x",      "ibm-mas-monitor.yaml"),
    "ibm-mas-optimizer":        (None, lambda ch: f"{ch}.x",      "ibm-mas-optimizer.yaml"),
    "ibm-mas-predict":          (None, lambda ch: f"{ch}.x",      "ibm-mas-predict.yaml"),
    "ibm-mas-visualinspection": (None, lambda ch: f"{ch}.x",      "ibm-mas-visualinspection.yaml"),
    "ibm-sls":                  (None, lambda _: "3.x",           "ibm-sls.yaml"),
    "ibm-truststore-mgr":       (None, lambda ch: f"{ch}.x",      "ibm-truststore-mgr.yaml"),
    "ibm-data-dictionary":      (None, lambda _: "1.1.x",         "ibm-data-dictionary.yaml"),
    "ibm-aiservice":            (None, _mas_x,                    "ibm-aiservice.yaml"),
    "ibm-aiservice-tenant":     (None, _mas_x,                    "ibm-aiservice-tenant.yaml"),
    "amlen":                    (None, lambda _: "1.x",           "eclipse-amlen.yaml"),
    # ---- CPD / dep packages (ibm-operator-catalog curated dir) ----
    "ibm-cp-common-services":   ("ibm-common-service-operator",   _lookup(_CSVC_CH),     None),
    "ibm-zen":                  ("ibm-zen-operator",               _lookup(_ZEN_CH),      None),
    "ibm-cp-datacore":          ("cpd-platform-operator",          _lookup(_DATACORE_CH), None),
    "ibm-licensing":            ("ibm-licensing-operator-app",     _lookup(_LIC_CH),      None),
    "ibm-ccs":                  ("ibm-cpd-ccs",                    _lookup(_CCS_CH),      None),
    "ibm-cloud-native-postgresql": ("cloud-native-postgresql",     _lookup(_PG_CH),       None),
    "ibm-datarefinery":         ("ibm-cpd-datarefinery",           _lookup(_REFINERY_CH), None),
    "ibm-wsl":                  ("ibm-cpd-wsl",                    _lookup(_WSL_CH),      None),
    "ibm-wsl-runtimes":         ("ibm-cpd-ws-runtimes",            _lookup(_WSL_CH),      None),
    "ibm-elasticsearch-operator": ("ibm-elasticsearch-operator",   _lookup(_ES_CH),       None),
    "ibm-opensearch-operator":  ("ibm-opensearch-operator",        _lookup(_OS_CH),       None),
    "ibm-redis-cp":             (None,                             None,                  None),
    "ibm-wml-cpd":              ("ibm-cpd-wml-operator",           _lookup(_WML_CH),      None),
    "ibm-analyticsengine":      ("analyticsengine-operator",       _lookup(_AE_CH),       None),
    "ibm-cognos-analytics-prod": (None,                            None,                  None),
    "ibm-db2uoperator-s11":     ("db2u-operator",                  _lookup(_DB2_CH),      None),
    "ibm-db2uoperator-s12":     ("db2u-operator",                  _lookup(_DB2_CH),      None),
    "ibm-couchdb":              ("couchdb-operator",               _lookup(_COUCH_CH),    None),
    "mongodb-ce":               (None,                             None,                  None),
    "minio":                    ("ibm-minio-operator",             _lookup(_MINIO_CH),    None),
    "opendatahub":              (None,                             None,                  None),
}

# ---------------------------------------------------------------------------
# BUNDLE_PATTERNS — operator name for packages where CASE version != CSV name.
# Used only as fallback when no catalog CSV name is available.
# Format: package -> operator_name (for display as `<operator_name>.v<csv>`)
# ---------------------------------------------------------------------------
BUNDLE_PATTERNS = {
    "ibm-couchdb":                (None, None, "couchdb-operator"),
    "ibm-opensearch-operator":    (None, None, "ibm-opensearch-operator"),
    "ibm-elasticsearch-operator": (None, None, "ibm-elasticsearch-operator"),
    "ibm-redis-cp":               (None, None, "ibm-redis-cp-operator"),
    "ibm-db2uoperator-s11":       (None, None, "db2u-operator"),
    "ibm-db2uoperator-s12":       (None, None, "db2u-operator"),
    "ibm-analyticsengine":        (None, None, "analyticsengine-operator"),
    "ibm-wml-cpd":                (None, None, "ibm-cpd-wml-operator"),
    "ibm-ccs":                    (None, None, "ibm-cpd-ccs"),
    "ibm-wsl":                    (None, None, "ibm-cpd-wsl"),
    "ibm-wsl-runtimes":           (None, None, "ibm-cpd-ws-runtimes"),
    "ibm-datarefinery":           (None, None, "ibm-cpd-datarefinery"),
    "ibm-cp-datacore":            (None, None, "cpd-platform-operator"),
    "ibm-cp-common-services":     (None, None, "ibm-common-service-operator"),
    "ibm-zen":                    (None, None, "ibm-zen-operator"),
    "ibm-licensing":              (None, None, "ibm-licensing-operator"),
    "ibm-cloud-native-postgresql":(None, None, "cloud-native-postgresql"),
    "minio":                      (None, None, "ibm-minio-operator"),
}


# ---------------------------------------------------------------------------
# Version mapping helpers
#
# Primary source: curated catalog CSV names (channel -> entries[0].name).
# These are the authoritative OLM identifiers (e.g. db2u-operator.v110509.0.8).
#
# The mapping is built at runtime from the local catalog repo so it stays
# accurate whenever the catalog is updated.
# ---------------------------------------------------------------------------

def _load_catalog_csv_names(curated_dir_path: str | None) -> dict:
    """
    Scan every catalog.yaml in the curated dir and return:
        { catalog_subdir: { catalog_channel: csv_name } }
    e.g. { "db2u-operator": { "v110509.0": "db2u-operator.v110509.0.8", ... } }
    """
    if not curated_dir_path or not os.path.isdir(curated_dir_path):
        return {}
    result = {}
    for pkg_dir in os.listdir(curated_dir_path):
        path = os.path.join(curated_dir_path, pkg_dir, "catalog.yaml")
        if not os.path.exists(path):
            continue
        raw = open(path).read()
        channel_csv = {}
        for doc in re.split(r"(?m)^---\s*$", raw):
            if "schema: olm.channel" not in doc:
                continue
            ch_m     = re.search(r"^name:\s+(\S+)", doc, re.MULTILINE)
            entry_m  = re.search(r"entries:\s*\n\s*-\s*name:\s+(\S+)", doc)
            if ch_m and entry_m:
                channel_csv[ch_m.group(1)] = entry_m.group(1)
        if channel_csv:
            result[pkg_dir] = channel_csv
    return result


def collect_version_mappings(packages_dir: str,
                             catalog_csv_names: dict) -> dict:
    """
    Build { package: { case_version: full_csv_name } } by resolving the
    catalog CSV name for each (package, channel) pair.

    For packages in PACKAGE_CATALOG_MAP that have a curated catalog entry,
    the CSV name is read from the catalog (e.g. 'db2u-operator.v110509.0.8').
    Packages not in the catalog map produce no entry.
    """
    results: dict = defaultdict(dict)

    for package in BUNDLE_PATTERNS:
        pkg_path = os.path.join(packages_dir, package)
        if not os.path.isdir(pkg_path):
            continue

        cat_entry = PACKAGE_CATALOG_MAP.get(package)
        if not cat_entry:
            continue
        cat_subdir, ch_fn, _config = cat_entry
        if ch_fn is None or cat_subdir is None:
            continue

        # channel_csv: { catalog_channel -> csv_name }
        channel_csv = catalog_csv_names.get(cat_subdir, {})
        if not channel_csv:
            continue

        for our_channel in sorted(os.listdir(pkg_path)):
            amd64_dir = os.path.join(pkg_path, our_channel, "amd64")
            if not os.path.isdir(amd64_dir):
                continue

            catalog_channel = ch_fn(our_channel)
            if not catalog_channel:
                continue

            csv_name = channel_csv.get(catalog_channel)
            if not csv_name:
                continue

            # Record mapping for every stable version in this channel
            for fname in sorted(os.listdir(amd64_dir)):
                if not fname.endswith(".yaml"):
                    continue
                stem = fname.replace(".yaml", "").replace("-amd64", "")
                if not stem.startswith(package + "-"):
                    continue
                case_version = stem[len(package) + 1:]
                if "pre" in case_version or "stable" in case_version:
                    continue
                results[package][case_version] = csv_name

    return results


def render_version_mapping_section(version_mappings: dict) -> list:
    """
    Render a '## Version Mappings' section listing packages where the CASE
    version differs from the contained operator bundle version.
    """
    lines = []
    lines.append("## Version Mappings")
    lines.append("")
    lines.append(
        "The following packages use IBM CASE versioning that differs from "
        "the operator bundle version contained within the ISC."
    )
    lines.append("")

    for package in sorted(version_mappings.keys()):
        mappings = version_mappings[package]
        if not mappings:
            continue

        _op_name = BUNDLE_PATTERNS[package][2]

        # Only render section if at least one version has a differing operator version
        differing = {cv: ov for cv, ov in mappings.items() if cv != ov}
        if not differing:
            continue

        lines.append(f"### `{package}`")
        lines.append("")
        lines.append(f"| CASE Version | Operator Bundle |")
        lines.append(f"|---|---|")

        for case_ver in sorted(differing.keys(), key=parse_version_safe, reverse=True):
            op_ver = differing[case_ver]
            lines.append(f"| `{package}.v{case_ver}` | `{_op_name}.v{op_ver}` |")

        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Catalog reference helpers
# ---------------------------------------------------------------------------

def _find_latest_curated_dir():
    """Return the path to the most recent *-curated-amd64 directory."""
    olm_dir = os.path.join(CATALOG_REPO, "ibm-operator-catalog")
    if not os.path.isdir(olm_dir):
        return None
    candidates = [
        d for d in os.listdir(olm_dir)
        if re.match(r"\d{4}-\d{2}-\d{2}-curated-amd64", d)
    ]
    if not candidates:
        return None
    latest = sorted(candidates)[-1]
    return os.path.join(olm_dir, latest), latest


def _channel_line(catalog_yaml_path: str, channel_name: str) -> int | None:
    """
    Return the 1-based line number where `name: <channel_name>` appears
    inside an olm.channel block in the catalog YAML.

    The schema: olm.channel declaration may appear either before OR after
    the name: line within the same YAML document block (separated by ---).
    We split on document boundaries and search within each document.
    """
    if not os.path.exists(catalog_yaml_path):
        return None

    raw = open(catalog_yaml_path).read()
    # Split into individual YAML documents on --- boundaries, tracking line offsets
    docs = []
    offset = 0
    for doc_text in re.split(r"(?m)^---\s*$", raw):
        docs.append((offset, doc_text))
        offset += doc_text.count("\n") + 1  # +1 for the --- line itself

    target = f"name: {channel_name}"
    for doc_offset, doc_text in docs:
        if "olm.channel" not in doc_text:
            continue
        for i, line in enumerate(doc_text.split("\n")):
            if line.strip() == target:
                return doc_offset + i + 1   # 1-based absolute line
    return None


def _config_channel_line(config_yaml_path: str, channel_name: str) -> int | None:
    """
    Return the 1-based line number for `- name: <channel_name>` in a MAS config file.
    """
    if not os.path.exists(config_yaml_path):
        return None
    lines = open(config_yaml_path).readlines()
    for i, line in enumerate(lines, 1):
        if re.match(rf"\s+- name:\s+{re.escape(channel_name)}\s*$", line):
            return i
    return None


def catalog_ref(package: str, our_channel: str,
                curated_dir_path: str | None, curated_dir_name: str | None) -> str | None:
    """
    Return a markdown link for the catalog reference for this package/channel,
    or None if not resolvable.
    """
    entry = PACKAGE_CATALOG_MAP.get(package)
    if not entry:
        return None
    cat_subdir, ch_fn, config_file = entry
    if ch_fn is None:
        return None

    catalog_channel = ch_fn(our_channel)
    if catalog_channel is None:
        return None

    # --- MAS config/ file ---
    if config_file is not None:
        cfg_path = os.path.join(CATALOG_REPO, "config", config_file)
        lineno   = _config_channel_line(cfg_path, catalog_channel)
        rel      = f"config/{config_file}"
        url      = f"{GITHUB_MAS_BASE}/{rel}"
        if lineno:
            url += f"#L{lineno}"
        return f"[{config_file}]({url})"

    # --- curated catalog dir ---
    if cat_subdir is not None and curated_dir_path and curated_dir_name:
        cat_yaml = os.path.join(curated_dir_path, cat_subdir, "catalog.yaml")
        lineno   = _channel_line(cat_yaml, catalog_channel)
        rel      = f"ibm-operator-catalog/{curated_dir_name}/{cat_subdir}/catalog.yaml"
        url      = f"{GITHUB_MAS_BASE}/{rel}"
        if lineno:
            url += f"#L{lineno}"
        return f"[{cat_subdir}/catalog.yaml]({url})"

    return None


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def parse_version_safe(v: str):
    normalised = re.sub(r"[-_]", ".", v)
    try:
        return (0, Version(normalised))
    except InvalidVersion:
        return (1, v)


def latest_version_in_channel(versions: list) -> str:
    stable = [v for v in versions if "pre" not in v and "stable" not in v]
    candidates = stable if stable else versions
    return max(candidates, key=parse_version_safe)


def isc_url(rel_path: str) -> str:
    return f"{GITHUB_ISC_BASE}/{rel_path}"


# ---------------------------------------------------------------------------
# OLM packages (packages/)
# ---------------------------------------------------------------------------

def collect_olm_packages(packages_dir: str = "packages") -> dict:
    data: dict = defaultdict(lambda: defaultdict(list))
    for component in sorted(os.listdir(packages_dir)):
        comp_path = os.path.join(packages_dir, component)
        if not os.path.isdir(comp_path):
            continue
        for channel in sorted(os.listdir(comp_path)):
            chan_path = os.path.join(comp_path, channel)
            if not os.path.isdir(chan_path):
                continue
            amd64_path = os.path.join(chan_path, "amd64")
            if not os.path.isdir(amd64_path):
                continue
            for fname in os.listdir(amd64_path):
                if not fname.endswith(".yaml"):
                    continue
                stem = fname.replace(".yaml", "").replace("-amd64", "")
                if stem.startswith(component + "-"):
                    version = stem[len(component) + 1:]
                    data[component][channel].append(version)
    return data


def default_channel(channels: dict) -> str:
    return max(
        channels.keys(),
        key=lambda ch: parse_version_safe(latest_version_in_channel(channels[ch]))
    )


def render_olm_table(components: list, pkg_data: dict,
                     curated_dir_path, curated_dir_name,
                     version_mappings: dict) -> list:
    lines = []
    header = (
        f"| {'Package':<32} | {'Default Channel':<17} | {'Channel':<17}"
        f" | {'Latest Version':<48} | {'Operator Bundle':<35} | Catalog Reference |"
    )
    sep = (
        f"|{'-'*34}|{'-'*19}|{'-'*19}|{'-'*50}|{'-'*37}|{'-'*35}|"
    )
    lines.append(header)
    lines.append(sep)

    for component in components:
        if component not in pkg_data:
            continue
        channels = pkg_data[component]
        def_ch = default_channel(channels)
        sorted_channels = sorted(
            channels.keys(),
            key=lambda ch: parse_version_safe(latest_version_in_channel(channels[ch])),
            reverse=True,
        )

        for i, channel in enumerate(sorted_channels):
            latest   = latest_version_in_channel(channels[channel])
            rel      = f"packages/{component}/{channel}/amd64/{component}-{latest}-amd64.yaml"
            ver_link = f"[{latest}]({isc_url(rel)})"
            cat_link = catalog_ref(component, channel, curated_dir_path, curated_dir_name) or ""

            # Operator bundle CSV name — full string from catalog
            # (e.g. "db2u-operator.v110509.0.8"), only shown when it differs
            # from the plain CASE version
            csv_name = version_mappings.get(component, {}).get(latest)
            if csv_name and csv_name != latest:
                op_col = f"`{csv_name}`"
            else:
                op_col = ""

            col_pkg = component if i == 0 else ""
            col_def = def_ch    if i == 0 else ""
            lines.append(
                f"| {col_pkg:<32} | {col_def:<17} | {channel:<17}"
                f" | {ver_link:<48} | {op_col:<35} | {cat_link} |"
            )

    return lines


# ---------------------------------------------------------------------------
# Helm charts (charts/)
# ---------------------------------------------------------------------------

def collect_chart_packages(charts_dir: str = "charts") -> dict:
    data: dict = defaultdict(lambda: defaultdict(list))
    for component in sorted(os.listdir(charts_dir)):
        comp_path = os.path.join(charts_dir, component)
        if not os.path.isdir(comp_path):
            continue
        for channel in sorted(os.listdir(comp_path)):
            chan_path = os.path.join(comp_path, channel)
            if not os.path.isdir(chan_path):
                continue
            for fname in os.listdir(chan_path):
                if not fname.endswith(".yaml"):
                    continue
                stem = fname.replace(".yaml", "")
                if stem.startswith(component + "-"):
                    version = stem[len(component) + 1:]
                    data[component][channel].append(version)
    return data


def render_chart_table(pkg_data: dict) -> list:
    lines = []
    header = (
        f"| {'Component':<30} | {'Default Channel':<15} | {'Channel':<7}"
        f" | {'Latest Version':<48} |"
    )
    sep = f"|{'-'*32}|{'-'*17}|{'-'*9}|{'-'*50}|"
    lines.append(header)
    lines.append(sep)

    for component in sorted(pkg_data.keys()):
        channels  = pkg_data[component]
        def_ch    = default_channel(channels)
        sorted_ch = sorted(
            channels.keys(),
            key=lambda ch: parse_version_safe(latest_version_in_channel(channels[ch])),
            reverse=True,
        )
        for i, channel in enumerate(sorted_ch):
            latest   = latest_version_in_channel(channels[channel])
            rel      = f"charts/{component}/{channel}/{component}-{latest}.yaml"
            ver_link = f"[{latest}]({isc_url(rel)})"

            col_comp = component if i == 0 else ""
            col_def  = def_ch    if i == 0 else ""
            lines.append(
                f"| {col_comp:<30} | {col_def:<15} | {channel:<7} | {ver_link:<48} |"
            )

    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate MANIFEST.md")
    parser.add_argument("--output",       default="MANIFEST.md")
    parser.add_argument("--packages-dir", default="packages")
    parser.add_argument("--charts-dir",   default="charts")
    args = parser.parse_args()

    olm_data   = collect_olm_packages(args.packages_dir)
    chart_data = collect_chart_packages(args.charts_dir)

    curated_result = _find_latest_curated_dir()
    curated_dir_path = curated_dir_name = None
    if curated_result:
        curated_dir_path, curated_dir_name = curated_result
        print(f"Using curated catalog: {curated_dir_name}")
    else:
        print("Warning: curated catalog dir not found; catalog references will be omitted")

    catalog_csv_names = _load_catalog_csv_names(curated_dir_path)
    version_mappings  = collect_version_mappings(args.packages_dir, catalog_csv_names)

    # Add ungrouped packages to Other Dependencies
    grouped = {pkg for pkgs in OLM_GROUPS.values() for pkg in pkgs}
    ungrouped = sorted(set(olm_data.keys()) - grouped)
    if ungrouped:
        OLM_GROUPS.setdefault("Other Dependencies", []).extend(ungrouped)

    out = []
    out.append("# Package Manifest")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## OLM Packages")
    out.append("")

    for section, members in OLM_GROUPS.items():
        present = [m for m in members if m in olm_data]
        if not present:
            continue
        out.append(f"### {section}")
        out.append("")
        out.extend(render_olm_table(members, olm_data, curated_dir_path, curated_dir_name, version_mappings))
        out.append("")

    out.append("---")
    out.append("")
    out.append("## Helm Charts")
    out.append("")
    out.extend(render_chart_table(chart_data))
    out.append("")

    content = "\n".join(out)
    with open(args.output, "w") as f:
        f.write(content)

    print(f"Written {args.output}")


if __name__ == "__main__":
    main()
