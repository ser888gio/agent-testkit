---
id: installation
title: Installation
sidebar_position: 1
---

# Installation

## Requirements

- Python 3.10 or newer.
- An agent you can reach, either as a Python callable or as an HTTPS endpoint.
- Node.js 20 or newer, only if you want to build this documentation site.

## Install from source

agentaudit is not on PyPI yet. Clone the repository and install it in editable
mode:

```bash
git clone https://github.com/ser888gio/agent-testkit.git
cd agent-testkit
pip install -e .
```

Check that the CLI works:

```bash
agentaudit --version
```

Then confirm it can actually find the shipped test packs and run something. This
uses a bundled demo agent, so it needs no endpoint of your own:

```bash
agentaudit run core --target agentaudit/config/treasury-agent.yaml
```

You should get a category table ending in `Gate: PASS`. Run it from the
repository root — `--target` takes a file path, while packs like `core` are
resolved by name from anywhere.

## If the command is not found

`pip` installs the `agentaudit` console script into a scripts directory that may
not be on your `PATH`. `pip` prints a `WARNING:` line about this near the end of
the install output.

You have two options. Run the module directly:

```bash
python -m agentaudit.cli --version
```

Or add the directory `pip` named to your `PATH`:

- Windows user installs: `%APPDATA%\Python\PythonXY\Scripts`
- Linux and macOS: `~/.local/bin`

## Install for development

To run the test suite and the linter, install the dev extra:

```bash
pip install -e ".[dev]"
python -m pytest
```

The project uses [`uv`](https://docs.astral.sh/uv/) for dependency management:

```bash
uv sync --extra dev
```

:::warning Windows: call pytest as a module
`uv run --frozen --extra dev pytest` fails with
`uv trampoline failed to canonicalize script path`. Use the module form instead:

```bash
uv run --frozen --extra dev python -m pytest
```

This is a console-script trampoline issue, not a problem with the package
layout. `uv run` itself works fine.
:::

## Database setup

Every run is stored in a SQLite file, `database/agentaudit.db` by default
(override with `--db` or `AGENTAUDIT_DB`). The file is
created on first use. If you are upgrading from an earlier version, apply
migrations:

```bash
agentaudit migrate --db database/agentaudit.db
agentaudit migrate --db database/agentaudit.db --status   # show pending migrations
```
