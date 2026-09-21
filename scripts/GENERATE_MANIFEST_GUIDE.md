# `generate_manifest.py` — Maintenance Guide

This guide explains every part of `scripts/generate_manifest.py` that requires
human attention when new packages or catalog versions are added.

---

## How it works (overview)

```
packages/<pkg>/<channel>/amd64/*.yaml   ← ISC files (source of versions)
charts/<pkg>/<channel>/*.yaml           ← Helm chart ISCs
../ibm-maximo-operator-catalog/
  config/<pkg>.yaml                     ← MAS catalog references
  ibm-operator-catalog/<date>-curated-amd64/<subdir>/catalog.yaml
                                        ← CPD/dep catalog references + CSV names
```

The script scans these directories at runtime and generates `MANIFEST.md`.
The **only things you ever need to edit manually** are the mapping tables
described below — the rest is automatic.

---

## Running the script

```bash
# From the image-set-configs repo root
python3 scripts/generate_manifest.py

# Custom output path
python3 scripts/generate_manifest.py --output MANIFEST.md
```

**Dependencies:** `pyyaml`, `packaging`
```bash
pip install pyyaml packaging
```

---

## Scenario 1 — A new CASE package is added to `packages/`

### Step 1 — Add it to `OLM_GROUPS`

Find the right section in `OLM_GROUPS` (lines ~33–74) and append the package name:

```python
OLM_GROUPS = {
    "IBM Maximo Application Suite": [
        ...
        "ibm-mas-newapp",      # ← add here
    ],
    ...
}
```

If it doesn't belong to an existing section, add it to `"Other Dependencies"`.

### Step 2 — Add it to `PACKAGE_CATALOG_MAP`

This controls the **Catalog Reference** column link and the **Operator Bundle** column.

**For a new MAS package** (has a config file in `../ibm-maximo-operator-catalog/config/`):
```python
PACKAGE_CATALOG_MAP = {
    ...
    "ibm-mas-newapp": (None, _mas_x, "ibm-mas-newapp.yaml"),
    #                   ^      ^       ^ config filename
    #                   |      |       MAS config dir
    #                   |      channel fn: "9.2" -> "9.2.x"
    #                   None = not a curated catalog package
}
```

**For a new CPD/dependency package** (appears in the curated catalog):
```python
# 1. First find the catalog subdir name:
ls ../ibm-maximo-operator-catalog/ibm-operator-catalog/2026-08-07-curated-amd64/

# 2. Find its channel names:
python3 -c "
import re
raw = open('../ibm-maximo-operator-catalog/ibm-operator-catalog/2026-08-07-curated-amd64/<subdir>/catalog.yaml').read()
for doc in re.split(r'(?m)^---\s*$', raw):
    if 'schema: olm.channel' in doc:
        ch = re.search(r'^name:\s+(\S+)', doc, re.MULTILINE)
        en = re.search(r'entries:\s*\n\s*-\s*name:\s+(\S+)', doc)
        print(f'channel={ch.group(1)}  csv={en.group(1)}')
"

# 3. Build the channel mapping dict (our dir -> catalog channel):
_NEWPKG_CH = {"1.0": "v1.0", "2.0": "v2.0"}

# 4. Add to PACKAGE_CATALOG_MAP:
"ibm-newpkg": ("new-operator-subdir", _lookup(_NEWPKG_CH), None),
```

**Only map channels that actually exist in the catalog.** Leave out channels
that are newer than the latest curated snapshot — they will correctly show
blank Operator Bundle and Catalog Reference cells.

### Step 3 — Add it to `BUNDLE_PATTERNS` (if versions differ)

Only needed when the CASE version number differs from the OLM CSV name.
Most packages need this:

```python
BUNDLE_PATTERNS = {
    ...
    "ibm-newpkg": (None, None, "new-operator-name"),
    #                           ^ the OLM operator name (prefix of the CSV name)
}
```

---

## Scenario 2 — A new channel is added to an existing package

For example, `ibm-ccs` gains a new `13.0` channel.

### For MAS packages
Nothing to do. MAS channels follow the `<major>.<minor>.x` pattern automatically
via `_mas_x`. The new channel directory will appear in the table automatically.

### For CPD packages
Add the new `our_channel -> catalog_channel` entry to the relevant `_*_CH` dict:

```python
# Before:
_CCS_CH = {"11.0": "v11.0", "12.1": "v12.1"}

# After adding 13.0:
_CCS_CH = {"11.0": "v11.0", "12.1": "v12.1", "13.0": "v13.0"}
```

**How to find the catalog channel name for the new version:**
```bash
python3 -c "
import re
raw = open('../ibm-maximo-operator-catalog/ibm-operator-catalog/<latest-curated>/ibm-cpd-ccs/catalog.yaml').read()
for doc in re.split(r'(?m)^---\s*\$', raw):
    if 'schema: olm.channel' in doc:
        ch = re.search(r'^name:\s+(\S+)', doc, re.MULTILINE)
        en = re.search(r'entries:\s*\n\s*-\s*name:\s+(\S+)', doc)
        print(ch.group(1), '->', en.group(1))
"
```

---

## Scenario 3 — A new curated catalog snapshot is published

The script **automatically picks up the newest** `*-curated-amd64` directory
(sorted alphabetically, which matches date order `YYYY-MM-DD`).

**You still need to check:**

1. **Are any new channels added?** If a package previously had only `v11.0`
   and now has `v12.1`, add the new mapping to the `_*_CH` dict.

2. **Have any channel names changed?** Unlikely but possible — check packages
   with custom encoded channel names like DB2U (`v120105.0` style).

3. **Are there new packages in the curated dir that need mapping?**
   ```bash
   ls ../ibm-maximo-operator-catalog/ibm-operator-catalog/<new-curated>/
   ```
   Compare against existing entries in `PACKAGE_CATALOG_MAP`.

---

## Scenario 4 — DB2U adds a new major version

DB2U uses encoded channel names (`v120105.0` style) that don't follow any
derivable pattern. When a new DB2U version is added:

1. Find the new channel name in the catalog:
   ```bash
   grep "^name: v" ../ibm-maximo-operator-catalog/ibm-operator-catalog/<curated>/db2u-operator/catalog.yaml
   ```

2. Add the mapping to `_DB2_CH`:
   ```python
   # Example: adding 7.8 -> v120106.0
   _DB2_CH = {
       "7.8": "v120106.0",   # ← new
       "7.7": "v120105.0",
       "7.6": "v120104.0",
       "7.3": "v110509.0",
   }
   ```

---

## Scenario 5 — A package is removed

Simply remove it from `OLM_GROUPS` and `PACKAGE_CATALOG_MAP`. The script
will silently skip any package not in `OLM_GROUPS`, and missing directories
in `packages/` produce no rows.

---

## Scenario 6 — A Helm chart package is added under `charts/`

**Nothing to do.** The chart table is fully automatic — it scans
`charts/<component>/<channel>/*.yaml` with no configuration required.

---

## Reference: key mapping tables

| Table | Purpose | When to update |
|---|---|---|
| `OLM_GROUPS` | Section grouping and display order | New package added |
| `PACKAGE_CATALOG_MAP` | Catalog reference URL + CSV name source | New package or new catalog subdir |
| `_*_CH` dicts | `our_channel` → `catalog_channel` translation | New channel in existing package |
| `_DB2_CH` | DB2U encoded channel names | New DB2U major version |
| `BUNDLE_PATTERNS` | Operator display name for Operator Bundle column | New package with differing versions |

---

## Verifying correctness after changes

```bash
# Regenerate
python3 scripts/generate_manifest.py

# Check for any packages with blank Catalog Reference that shouldn't be blank
grep "| $" MANIFEST.md | grep -v "ibm-cognos\|mongodb-ce\|opendatahub\|ibm-redis-cp"

# Check for any packages missing from the OLM table entirely
ls packages/ | while read p; do grep -q "^| $p" MANIFEST.md || echo "MISSING: $p"; done

# Spot-check a specific package's CSV name against the catalog
python3 -c "
import re
pkg = 'db2u-operator'   # change to the subdir you want to check
raw = open('../ibm-maximo-operator-catalog/ibm-operator-catalog/2026-08-07-curated-amd64/$pkg/catalog.yaml').read()
for doc in re.split(r'(?m)^---\s*$', raw):
    if 'schema: olm.channel' in doc:
        ch = re.search(r'^name:\s+(\S+)', doc, re.MULTILINE)
        en = re.search(r'entries:\s*\n\s*-\s*name:\s+(\S+)', doc)
        print(ch.group(1), '->', en.group(1))
"
```
