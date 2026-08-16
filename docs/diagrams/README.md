# Diagrams

D2 sources and rendered SVGs for the two diagrams embedded in the root
[`README.md`](../../README.md). Regenerate with `d2 --bundle <file>.d2 <file>-light.svg --theme 0`
(swap `--theme 200` for the dark variant) after editing the `.d2` source — the SVGs are
generated output, never edit them directly (see the root `CLAUDE.md` "Generated / vendored"
list).

## Infrastructure

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./infrastructure-simplified-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./infrastructure-simplified-light.svg">
  <img alt="Infrastructure Overview" src="./infrastructure-simplified-light.svg">
</picture>

Source: [`infrastructure-simplified.d2`](./infrastructure-simplified.d2). Reflects
`infra/docker-compose.yml`: the web service, the network-isolated run worker, the target
agent it calls, the SQLite run store (reached as a shared file, not a network service), and
Keycloak for OIDC. See [`infra/CLAUDE.md`](../../infra/CLAUDE.md) for the isolation
boundary this diagram simplifies.

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./architecture-simplified-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./architecture-simplified-light.svg">
  <img alt="Architecture Overview" src="./architecture-simplified-light.svg">
</picture>

Source: [`architecture-simplified.d2`](./architecture-simplified.d2). Reflects the
runner/control-plane split described in the root `CLAUDE.md`: CLI/web drive the runner,
the runner asserts against domain sandboxes and redacts before handing off a `RunResult`,
scoring persists it via the store (redacting again as defense-in-depth) and produces a
`ScoreReport`, and `agentkit report --run` replays a stored run through the report
renderers. For the full module-level breakdown, see
[`docs/architecture.md`](../architecture.md).
