# Implementation Tests Plan

## Objective

Evolve `agentaudit` from a fixed-pack black-box test runner into an adaptive harness platform
for AI agents. The platform should:

1. discover what an agent does and how it is exposed,
2. generate an agent-specific harness from reusable building blocks,
3. select the most relevant tests from internal and external libraries,
4. run iterative adversarial evaluations,
5. produce engineering, security, and compliance evidence.

This document focuses on how to implement that using ideas and components from:

- `promptfoo`
- `garak`
- `inspect_ai`
- `openai/evals` and `openai/simple-evals`
- `AgentDojo`
- `tau2-bench` / future `tau3` direction
- `ToolEmu`
- `BrowserGym` and `AgentLab`
- `PurpleLlama`

## Product Decision

We should **not** build one bespoke harness codebase per tested AI agent.

We should build:

- one reusable `agentaudit` runtime,
- one reusable test and harness catalog,
- one generated or configured **agent profile** per tested system,
- one generated **harness plan** per agent profile.

This keeps the product scalable while preserving agent-specific realism.

## Guiding Principles

1. **Black-box first**
   Test through the interface the customer actually exposes whenever possible.

2. **Harnesses are assembled, not hand-built**
   Per-agent harnesses should be composed from templates, adapters, simulators, and validators.

3. **External libraries should be wrapped, not allowed to dominate the architecture**
   `agentaudit` should define the core runtime and evidence model; imported tools should plug into it.

4. **Every integration must improve one of three things**
   - attack coverage
   - harness realism
   - evidence quality

5. **Repeatability matters**
   Adaptive testing must still be explainable, reproducible, and auditable.

## Recommended Integration Order

### Wave 1: immediate practical leverage

- `promptfoo`
- `garak`
- `inspect_ai`
- `openai/simple-evals`

### Wave 2: adaptive harness realism

- `ToolEmu`
- `AgentDojo`
- `tau2-bench`

### Wave 3: environment-specific expansion

- `BrowserGym`
- `AgentLab`
- `PurpleLlama`

## Target Architecture Additions

Add these new core concepts to `agentaudit`:

- `AgentProfile`
  - purpose
  - domain
  - endpoint schema
  - side-effect surfaces
  - tool classes
  - permissions
  - risk level
  - policy tags

- `HarnessTemplate`
  - conversation driver
  - simulator(s)
  - setup/teardown rules
  - validators
  - artifact collectors

- `HarnessPlan`
  - chosen templates
  - selected tests
  - attack strategy
  - stop conditions
  - evidence settings

- `ExternalEvalAdapter`
  - normalized adapter interface for third-party eval tools

- `TestCatalogEntry`
  - source
  - category
  - domain tags
  - risk tags
  - prerequisites
  - input strategy
  - scoring strategy

## Workstreams

## 1. Core Platform Refactor

Goal: make the current repo ready to host adaptive harness generation and external test adapters.

### Subtasks

1. Add a first-class `AgentProfile` model to the core schema.
2. Add `HarnessPlan` and `TestCatalogEntry` models.
3. Split current test pack loading into:
   - static local packs
   - generated packs
   - external adapter-backed packs
4. Add a normalized adapter interface for third-party eval engines.
5. Extend result storage so every test result records:
   - original source library
   - why the test was selected
   - harness context
   - reproducibility inputs

### Deliverables

- core schema update
- loader changes
- adapter interface
- migration for stored run metadata

### Tests

1. schema round-trip tests for `AgentProfile`, `HarnessPlan`, and `TestCatalogEntry`
2. loader tests for mixed local and adapter-backed test sources
3. store tests proving new metadata persists and reads back cleanly

## 2. Test Catalog and Metadata System

Goal: create a common internal language for selecting tests from many sources.

### Subtasks

1. Define a tag taxonomy:
   - domain
   - modality
   - interaction type
   - side-effect type
   - risk category
   - compliance mapping
2. Convert existing built-in packs into catalog entries with metadata.
3. Add ranking rules for test selection:
   - relevance score
   - coverage score
   - novelty score
   - cost score
4. Add support for prerequisites such as:
   - requires multi-turn
   - requires tool-use
   - requires browser
   - requires stateful memory
5. Add selection explanations to support reporting.

### Deliverables

- metadata schema
- catalog builder
- ranking engine v1
- selection-explanation output

### Tests

1. unit tests for catalog tagging and validation
2. ranking tests for domain/risk matching
3. regression tests that ensure obviously irrelevant tests are not selected

## 3. `promptfoo` Adapter

Goal: reuse practical black-box eval and red-team workflows quickly.

### Why integrate it

`promptfoo` is a strong near-term source of declarative evals, red-team workflows, and CI-friendly execution.

### Integration strategy

Use `promptfoo` as an external execution backend behind an `agentaudit` adapter rather than making it the primary runtime.

### Subtasks

1. Define an adapter that maps an `AgentProfile` into `promptfoo` configuration.
2. Support `promptfoo` prompt-based and endpoint-based execution modes.
3. Normalize `promptfoo` results into `agentaudit` `TestResult`s.
4. Map `promptfoo` vulnerabilities and assertions into internal categories and risk levels.
5. Add import support for reusable `promptfoo` scenarios into the internal test catalog.

### Deliverables

- `promptfoo` adapter
- config translator
- result normalizer

### Tests

1. adapter snapshot tests for generated `promptfoo` configs
2. fixture-based result normalization tests
3. end-to-end test against a local stub endpoint

## 4. `garak` Adapter

Goal: add broad adversarial probe coverage with minimal custom probe authoring up front.

### Why integrate it

`garak` already provides a scanner-like model for LLM weaknesses and is especially useful for broad first-pass attack coverage.

### Integration strategy

Treat `garak` as a probe library and execution backend for black-box adversarial scans.

### Subtasks

1. Build a `garak` runner wrapper that can target `HTTPAgent` style endpoints.
2. Create a mapping from `garak` probe families to internal categories such as:
   - prompt injection
   - data leakage
   - jailbreak / policy bypass
   - harmful output
3. Normalize hit reports into reproducible `agentaudit` evidence artifacts.
4. Add allowlist and blocklist controls for probe families per domain.
5. Add cost and runtime budgeting so scans stay bounded.

### Deliverables

- `garak` adapter
- probe mapping table
- normalized evidence model

### Tests

1. wrapper tests for endpoint invocation
2. mapping tests for probe-to-category normalization
3. smoke tests on a controlled intentionally vulnerable agent

## 5. `inspect_ai` Bridge

Goal: support richer multi-turn, tool-using, and scored evaluations without giving up the `agentaudit` evidence model.

### Why integrate it

`inspect_ai` is a strong framework for structured multi-turn tasks, tool use, and model-graded evaluation patterns.

### Integration strategy

Bridge `agentaudit` harness plans into `inspect_ai` tasks and map outputs back into the `agentaudit` store.

### Subtasks

1. Define a translation layer from `HarnessPlan` to `inspect_ai` task definitions.
2. Decide which `inspect_ai` concepts become first-class in `agentaudit`:
   - task
   - scorer
   - sample
   - transcript
3. Support importing selected `inspect_ai` tasks into the internal catalog.
4. Normalize tool-use traces and scored outputs.
5. Add optional model-graded evaluation hooks behind a feature flag.

### Deliverables

- `inspect_ai` bridge
- task translation layer
- trace normalization support

### Tests

1. translation tests from `HarnessPlan` to task definitions
2. transcript normalization tests
3. end-to-end multi-turn evaluation test using a stub tool-using agent

## 6. `openai/simple-evals` and `openai/evals` Pattern Import

Goal: reuse simple eval patterns and registry ideas without pulling the whole product toward a single external framework.

### Why integrate them

These repositories are most useful as references for eval structure, scoring, and small reusable checks.

### Integration strategy

Reuse ideas and selective task patterns, not full runtime ownership.

### Subtasks

1. Add a lightweight internal eval definition format inspired by simple evals.
2. Add standard scorer helpers:
   - exact match
   - contains
   - regex
   - structured field check
   - LLM judge, optional
3. Add an internal registry mechanism for reusable small evals.
4. Document a path for porting community evals into `agentaudit` format.

### Deliverables

- internal mini-eval format
- scorer library
- registry support

### Tests

1. scorer correctness tests
2. mini-eval loading tests
3. compatibility tests using ported sample evals

## 7. `ToolEmu`-Style Harness Emulation

Goal: generate more realistic tool-use harnesses for agents whose risk depends on actions, not just text.

### Why integrate it

This is close to the product vision: emulate tool ecosystems, observe agent behavior, and score failures in context.

### Integration strategy

Adopt the pattern more than the literal code where needed: toolkits, emulated environments, safety and helpfulness judgments, and risk grading.

### Subtasks

1. Add a `ToolSurface` abstraction to represent:
   - available tools
   - schemas
   - permissions
   - side-effect classes
2. Implement reusable simulator templates:
   - email
   - banking / treasury
   - CRM / ticketing
   - file system
3. Add validators for unsafe tool trajectories.
4. Add attack mutations that target tool misuse, overreach, and escalation.
5. Add severity grading for action failures.

### Deliverables

- tool surface schema
- simulator template library
- tool-trajectory validator set

### Tests

1. simulator state transition tests
2. validator tests for unsafe action chains
3. multi-turn misuse attack tests

## 8. `AgentDojo`-Style Prompt Injection Harnesses

Goal: improve prompt-injection and defense evaluation for tool-using agents.

### Why integrate it

`AgentDojo` is particularly relevant for dynamic prompt-injection evaluation and defense comparison.

### Integration strategy

Adopt its task and attack patterns into reusable injection harness templates.

### Subtasks

1. Add injection attack families to the internal catalog:
   - direct override
   - tool knowledge attacks
   - indirect injected content
   - stateful multi-turn poisoning
2. Add explicit defense metadata to results:
   - no defense
   - filter
   - policy layer
   - human approval gate
3. Add benchmark-style comparison mode for attack/defense variants.
4. Add replayable transcripts for successful injection attacks.

### Deliverables

- prompt injection harness templates
- defense comparison support
- replay artifacts

### Tests

1. attack family selection tests
2. defense-comparison regression tests
3. replay artifact integrity tests

## 9. `tau2-bench`-Style Domain Conversation Harnesses

Goal: support domain-aware, policy-heavy, realistic multi-turn agent evaluation.

### Why integrate it

`tau2-bench` is useful for modeling dynamic user-agent-tool interaction in real business domains.

### Integration strategy

Borrow the domain/task/policy structure to generate harnesses for customer service and operations agents.

### Subtasks

1. Add a `PolicyBundle` concept to `AgentProfile`.
2. Add user simulator templates for:
   - support
   - retail
   - finance
   - scheduling
3. Add task goals with hidden constraints and success criteria.
4. Add conversation outcome scoring beyond single-response assertions.
5. Add a per-domain harness template package.

### Deliverables

- policy bundle model
- user simulator interfaces
- domain harness packages

### Tests

1. simulator determinism tests
2. hidden-constraint scoring tests
3. domain task end-to-end tests

## 10. Browser Agent Expansion with `BrowserGym` and `AgentLab`

Goal: support agents that act through browser environments instead of pure API or chat endpoints.

### Why integrate them

They are the right reference point for browser-native agent harnesses and experiment management.

### Integration strategy

Treat browser evaluation as a specialized harness family inside `agentaudit`, not a separate product.

### Subtasks

1. Add a browser harness type to the `HarnessTemplate` model.
2. Define observation and action adapters between `agentaudit` and browser environments.
3. Add browser-specific artifact capture:
   - screenshots
   - action timelines
   - DOM snapshots
   - network activity, if available
4. Add browser task categories such as:
   - navigation
   - form entry
   - data exfiltration risk
   - unsafe click or submit actions
5. Add performance budgets for browser tests to contain cost.

### Deliverables

- browser harness adapter
- browser artifact model
- browser risk pack v1

### Tests

1. adapter contract tests
2. artifact capture tests
3. browser sandbox smoke tests on a tiny local target

## 11. `PurpleLlama` / Cybersecurity Mapping

Goal: strengthen security evidence and compliance mapping for customers who need structured reporting.

### Why integrate it

This helps position `agentaudit` as an assurance product rather than just a test runner.

### Integration strategy

Reuse benchmark categories and reporting ideas where they match agent risk, without constraining all of `agentaudit` to cybersecurity-only use cases.

### Subtasks

1. Add mapping from internal findings to security benchmark families.
2. Add optional CWE / ATT&CK style references where appropriate.
3. Extend compliance reports to include security-oriented finding groupings.
4. Add templates for remediation guidance.

### Deliverables

- security mapping table
- enhanced reporting sections
- remediation templates

### Tests

1. finding-to-framework mapping tests
2. report rendering tests
3. snapshot tests for compliance exports

## 12. Discovery and Harness Planning Engine

Goal: build the actual adaptive layer that chooses harnesses and tests.

This is the key product differentiator.

### Subtasks

1. Implement endpoint discovery:
   - schema sampling
   - response shape inference
   - conversation capability checks
2. Implement profile inference:
   - domain classifier
   - capability classifier
   - risk classifier
3. Implement harness planning:
   - choose templates
   - choose simulators
   - choose test families
   - choose attack depth
4. Implement stop conditions:
   - fixed budget
   - confidence reached
   - critical failure reached
   - diminishing returns
5. Record planning rationale for each run.

### Deliverables

- discovery service
- planning engine
- rationale recorder

### Tests

1. endpoint inference tests with varied stub agents
2. profile classification tests with fixed fixtures
3. planning tests that verify selected harnesses match agent traits
4. determinism tests for planning under fixed seeds

## 13. Iterative Attack Engine

Goal: move beyond static test execution into adaptive probing.

### Subtasks

1. Add attack mutation primitives:
   - paraphrase
   - escalation
   - role manipulation
   - hidden payload insertion
   - delayed multi-turn attack
2. Add branch-and-retry execution support.
3. Add memory poisoning and context carryover flows.
4. Add exploit confirmation logic so promising failures are reproduced.
5. Add budget controls for tokens, turns, and wall-clock time.

### Deliverables

- attack mutation engine
- branching execution runtime
- exploit confirmation flow

### Tests

1. mutation generation tests
2. branch execution tests
3. exploit reproduction tests on intentionally vulnerable fixtures

## 14. Reporting and Product Surface

Goal: make the adaptive behavior legible to engineers, security reviewers, and compliance teams.

### Subtasks

1. Add run views showing:
   - discovered profile
   - selected harness components
   - selected external libraries
   - attack path tree
2. Add selection-why explanations to test detail pages.
3. Add confidence and coverage indicators.
4. Add explicit unsupported or untested area reporting.
5. Add export formats for customer evidence packs.

### Deliverables

- dashboard changes
- richer run detail
- evidence pack exports

### Tests

1. web tests for new run and test detail surfaces
2. export tests for evidence pack formats
3. snapshot tests for summary reports

## Milestones

## Milestone A: External Eval Foundations

Scope:

- workstreams 1 through 6

Outcome:

`agentaudit` can ingest and normalize external eval results from practical black-box tools.

## Milestone B: Adaptive Harness Foundations

Scope:

- workstreams 7 through 9
- partial workstream 12

Outcome:

`agentaudit` can generate domain-aware tool-use and conversation harnesses.

## Milestone C: Iterative Adversarial Engine

Scope:

- remaining workstream 12
- workstream 13

Outcome:

`agentaudit` can select, adapt, escalate, and reproduce attacks rather than only run static suites.

## Milestone D: Specialized Environments and Reporting

Scope:

- workstreams 10, 11, and 14

Outcome:

`agentaudit` supports browser agents and stronger security/compliance reporting.

## What Not To Do

1. Do not integrate all external libraries at once.
2. Do not let third-party result formats leak directly into the core store.
3. Do not hand-author fully custom harness logic for every new customer agent.
4. Do not rely on adaptive attack generation without reproducibility metadata.
5. Do not promise compliance determination; produce compliance evidence instead.

## Success Criteria

The implementation is successful when:

1. a new agent endpoint can be profiled and assigned a harness plan with minimal manual setup,
2. the planner can explain why it selected each test or attack family,
3. third-party eval tools can run through adapters and produce normalized `agentaudit` results,
4. multi-turn and tool-use agents can be tested in realistic simulated environments,
5. successful attacks can be replayed and reproduced,
6. reports clearly separate:
   - tested areas
   - untested areas
   - failed controls
   - advisory findings

## Suggested First Build Slice

Build this first before anything broader:

1. core refactor for `AgentProfile`, `HarnessPlan`, and adapter-backed test sources
2. metadata-driven test catalog
3. `promptfoo` adapter
4. `garak` adapter
5. minimal planner that selects among:
   - built-in packs
   - `promptfoo`
   - `garak`
6. dashboard support for showing selection rationale

That slice gives us the first convincing version of:

black-box endpoint discovery -> test selection -> adversarial execution -> normalized evidence
