# image-set-configs

ImageSetConfiguration (ISC) files for IBM Maximo Application Suite and dependencies, generated from CASE bundles and catalog data.

## Quick Start

Generate ISC files automatically from MAS catalog data:

```bash
# Process a specific catalog
python3 scripts/create_iscs.py --catalog v9-260326-amd64

# Process all recent catalogs (newer than v9-260129)
python3 scripts/create_iscs.py --all-catalogs
```

The script will:
1. Extract version information from the catalog YAML file
2. Download CASE bundles using `oc ibm-pak get` (if not already cached)
3. Generate ISC files in the `packages/` directory organized by product and version
4. Process extras (MongoDB, Amlen) from ansible-devops repository

**Prerequisites:**
- `oc` CLI with `ibm-pak` plugin installed
- `python-devops` repository cloned as a sibling to `image-set-configs`
- `ansible-devops` repository cloned as a sibling to `image-set-configs` (for extras)

## Generating ISCs from Catalog

### Process Single Catalog
```bash
# Using short name (recommended)
python scripts/create_iscs.py --catalog v9-260326-amd64

# Or using full path
python scripts/create_iscs.py --catalog ../python-devops/src/mas/devops/data/catalogs/v9-260326-amd64.yaml
```

This will process the specified catalog and generate ISC files for all CASE packages and extras defined in that catalog. The script automatically resolves short catalog names to the full path in the python-devops repository.

### Process All Recent Catalogs
```bash
python scripts/create_iscs.py --all-catalogs
```

This processes all catalogs in `../python-devops/src/mas/devops/data/catalogs/` that are newer than v9-260129 (January 29, 2026). Catalogs are processed in chronological order based on the date in their filename (format: `v9-YYMMDD-arch.yaml`).

## Catalog Field Mappings

The following table shows how catalog data fields map to ISC packages:

| ISC Package | Catalog Field | Architectures | Notes |
|-------------|---------------|---------------|-------|
| **MAS Core & Applications** |
| ibm-mas | `mas_core_version` | amd64, ppc64le, s390x | |
| ibm-mas-manage | `mas_manage_version` | amd64, ppc64le, s390x | Excludes ICD images |
| ibm-mas-manage-icd | `mas_manage_version` | amd64, ppc64le, s390x | ICD images only |
| ibm-mas-monitor | `mas_monitor_version` | amd64 | |
| ibm-mas-optimizer | `mas_optimizer_version` | amd64 | |
| ibm-mas-predict | `mas_predict_version` | amd64 | |
| ibm-mas-assist | `mas_assist_version` | amd64 | |
| ibm-mas-iot | `mas_iot_version` | amd64 | |
| ibm-mas-facilities | `mas_facilities_version` | amd64 | |
| ibm-mas-visualinspection | `mas_visualinspection_version` | amd64, ppc64le, s390x | |
| ibm-aiservice | `aiservice_version` | amd64, ppc64le, s390x | |
| **Dependencies** |
| ibm-truststore-mgr | `tsm_version` | amd64, ppc64le, s390x | |
| ibm-sls | `sls_version` | amd64, ppc64le, s390x | |
| ibm-data-dictionary | `dd_version` | amd64, ppc64le, s390x | |
| ibm-db2uoperator-s11 | `db2u_version` | amd64, ppc64le, s390x | DB2 v11 variant |
| ibm-db2uoperator-s12 | `db2u_version` | amd64, ppc64le, s390x | DB2 v12 variant |
| **Cloud Pak for Data** |
| ibm-cp-common-services | `common_svcs_version` | amd64, ppc64le, s390x | |
| ibm-zen | `ibm_zen_version` | amd64, ppc64le, s390x | |
| ibm-cp-datacore | `cp4d_platform_version` | amd64, ppc64le, s390x | |
| ibm-licensing | `ibm_licensing_version` | amd64, ppc64le, s390x | |
| ibm-ccs | `ccs_build` | amd64, ppc64le, s390x | |
| ibm-cloud-native-postgresql | `postgress_version` | amd64, ppc64le, s390x | |
| ibm-datarefinery | `datarefinery_version` | amd64, ppc64le, s390x | |
| ibm-wsl | `wsl_version` | amd64, ppc64le, s390x | |
| ibm-wsl-runtimes | `wsl_runtimes_version` | amd64, ppc64le, s390x | |
| ibm-elasticsearch-operator | `elasticsearch_version` | amd64, ppc64le, s390x | |
| ibm-opensearch-operator | `opensearch_version` | amd64, ppc64le, s390x | |
| ibm-wml-cpd | `wml_version` | amd64, ppc64le, s390x | |
| ibm-analyticsengine | `spark_version` | amd64, ppc64le, s390x | |
| ibm-cognos-analytics-prod | `cognos_version` | amd64, ppc64le, s390x | |
| **Extras (Non-CASE)** |
| mongodb-ce | `mongo_extras_version_default` | amd64 | From ansible-devops extras |
| amlen | `amlen_extras_version` | amd64 | From ansible-devops extras |

### Notes
- Pre-release versions (containing 'feature' or 'pre') are automatically filtered out
- DB2 operator generates both s11 and s12 variants from a single catalog entry
- Manage generates both regular and ICD variants from a single catalog entry
- Extras are sourced from `ansible-devops/ibm/mas_devops/roles/mirror_extras_prepare/vars/` YAML files
- The `ibm-mas-arcgis` package does not support image mirroring

## Example Usage

### Direct Mirroring (m2m)
```bash
oc-mirror --v2 -c packages/ibm-sls/3.12/amd64/ibm-sls-3.12.5-amd64.yaml --authfile ~/.ibm-mas/auth.json docker://masdeps2-6f1620198115433da1cac8216c06779b-0000.us-south.containers.appdomain.cloud:32500/djp
```

### Two-Phase Mirroring (m2d + d2m)
```bash
oc-mirror --v2 -c packages/ibm-sls/3.12/amd64/ibm-sls-3.12.5-amd64.yaml --authfile ~/.ibm-mas/auth.json file://output-dir/ibm-sls/3.12
oc-mirror --v2 -c packages/ibm-sls/3.12/amd64/ibm-sls-3.12.5-amd64.yaml --from file://output-dir/ibm-sls/3.12 docker://masdeps2-6f1620198115433da1cac8216c06779b-0000.us-south.containers.appdomain.cloud:32500/djp
```
