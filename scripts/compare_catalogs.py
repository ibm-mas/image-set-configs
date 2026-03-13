#!/usr/bin/env python3
"""
Script to compare two catalog YAML files and get the with new versions.

This script compares previous catalog with latest catalog and identifies
newly added versions that need to be added to convert.py.
"""

import argparse
import yaml
from typing import Dict, List, Set

def load_yaml(file_path: str) -> Dict:
    """Load YAML file and return parsed content."""
    with open(file_path, 'r') as f:
        return yaml.safe_load(f)

def extract_versions(data: Dict, key: str) -> Set[str]:
    """Extract version numbers from a version dictionary."""
    versions = set()
    if key in data and isinstance(data[key], dict):
        for version_key, version_value in data[key].items():
            if version_value and version_value != "":
                versions.add(version_value)
    return versions

def find_new_versions(previous_file: str, latest_file: str) -> Dict[str, List[str]]:
    """Compare two YAML files and return newly added versions."""
    previous_data = load_yaml(previous_file)
    latest_data = load_yaml(latest_file)
    
    new_versions = {}
    
    # Version keys to check
    version_keys = [
        'tsm_version', 'dd_version', 'sls_version',
        'mas_core_version', 'mas_assist_version', 'mas_iot_version',
        'mas_manage_version', 'mas_monitor_version', 'mas_optimizer_version',
        'mas_predict_version', 'mas_visualinspection_version',
        'mas_facilities_version', 'aiservice_version', 'db2u_version', 'common_svcs_version',
        'ibm_zen_version', 'cp4d_platform_version',  'ibm_licensing_version', 'ccs_build', 
        'postgress_version', 'spark_version', 'wsl_version', 'wsl_runtimes_version', 
        'elasticsearch_version', 'opensearch_version', 'wml_version', 'spark_version',
        'cognos_version'

    ]
    
    for key in version_keys:
        if key in latest_data:
            if isinstance(latest_data[key], dict):
                # Handle versioned dictionaries (like mas_core_version)
                previous_versions_set = extract_versions(previous_data, key)
                latest_versions_set = extract_versions(latest_data, key)
                added = sorted(latest_versions_set - previous_versions_set)
                if added:
                    new_versions[key] = added
            elif isinstance(latest_data[key], str):
                # Handle simple version strings
                previous_val = previous_data.get(key, '')
                latest_val = latest_data[key]
                if previous_val != latest_val:
                    new_versions[key] = [latest_val]
    return new_versions

def print_version_updates(new_versions: Dict[str, List[str]]):
    """Print a formatted report of version updates."""
    print("\n" + "="*80)
    print("NEW VERSIONS FOUND")
    print("="*80)
    
    if not new_versions:
        print("\nNo new versions found.")
        return
    
    # Group by category
    dependencies = {}
    mas_apps = {}
    
    for key, versions in new_versions.items():
        if key in ['tsm_version', 'dd_version', 'sls_version', 'db2u_version', 'common_svcs_version',
        'ibm_zen_version', 'cp4d_platform_version',  'ibm_licensing_version', 'ccs_build', 
        'postgress_version', 'spark_version', 'wsl_version', 'wsl_runtimes_version', 
        'elasticsearch_version', 'opensearch_version', 'wml_version', 'spark_version',
        'cognos_version']:
            dependencies[key] = versions
        else:
            mas_apps[key] = versions
    
    if dependencies:
        print("\n📦 DEPENDENCIES:")
        print("-" * 80)
        for key, versions in dependencies.items():
            name = key.replace('_version', '').upper()
            print(f"  {name}: {', '.join(versions)}")
    
    if mas_apps:
        print("\n🔧 MAS APPLICATIONS:")
        print("-" * 80)
        for key, versions in mas_apps.items():
            name = key.replace('_version', '').replace('mas_', '').replace('_', ' ').title()
            print(f"  {name}: {', '.join(versions)}")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--previous', required=True, help="path of the previous catalog")
    parser.add_argument('-l', '--latest', required=True, help="path of the latest catalog")
    

    args, unknown = parser.parse_known_args()
    # Catalog paths
    previous_catalog = args.previous
    latest_catalog = args.latest
    
    
    print("Comparing catalog files...")
    print(f"previous: {previous_catalog}")
    print(f"latest: {latest_catalog}")
    
    # Find latest versions
    new_versions = find_new_versions(str(previous_catalog), str(latest_catalog))
    
    if new_versions:
        # Print results
        print_version_updates(new_versions)
    else:
        print("\nNo updates needed.")


"""
This is the mapping of dependencies case names in catalog to convert.py

    db2u_version -> ibmdb2u-standalone
    common_svcs_version -> ibm-cp-common-services
    ibm_zen_version -> ibm-zen
    cp4d_platform_version -> ibm-cp-datacore
    ibm_licensing_version -> ibm-licensing
    ccs_build -> ibm-ccs
    postgress_version -> ibm-cloud-native-postgresql
    datarefinery_version -> ibm-datarefinery
    wsl_version -> ibm-wsl
    wsl_runtimes_version -> ibm-wsl-runtimes
    elasticsearch_version -> ibm-elasticsearch-operator
    opensearch_version -> ibm-opensearch-operator
    wml_version -> ibm-wml-cpd
    spark_version -> ibm-analyticsengine
    cognos_version -> ibm-cognos-analytics-prod
"""