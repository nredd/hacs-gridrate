# Dependencies Overview

All dependencies are managed through `pyproject.toml` using `uv`.

## 📁 Files

### `pyproject.toml` — Single Source of Truth

All development, test, and tooling dependencies live in the `[dependency-groups.dev]` section.
Install everything with:

```bash
uv sync --locked
```

**Includes:**

- `pytest-homeassistant-custom-component` — HA test fixtures and the full pytest stack
- `opower` — the integration's runtime dependency, installed so it imports cleanly in dev and CI
- `ruff` — formatter + linter
- `ty` — type checker (Astral)
- `colorlog` — colored logging for development scripts
- `zlib_ng`, `isal` — optional HA startup performance packages

### `custom_components/gridrate/manifest.json` — Runtime Dependencies

**Purpose:** Python packages needed by the integration at runtime
**Installed by:** Home Assistant automatically when loading the integration

This is the authoritative source for runtime deps — not `pyproject.toml`.

## 🔄 Adding Dependencies

| Dependency type               | Where to add                              |
| ----------------------------- | ----------------------------------------- |
| Runtime (end users need it)   | `manifest.json` `requirements` field      |
| Dev / test / tooling          | `pyproject.toml` `[dependency-groups.dev]`|

After editing `pyproject.toml`, run `uv lock` to update the lockfile, then commit both files.

## 🔍 hacs.json vs manifest.json

**`hacs.json`** — metadata only (HA minimum version, HACS minimum version). No Python packages.

**`manifest.json`** — runtime Python package dependencies, installed by Home Assistant.

No duplication needed: `hacs.json` never lists Python packages.
