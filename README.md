# image-set-configs

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

## IBM Pak Conversion

```
python scripts/convert.py
```
