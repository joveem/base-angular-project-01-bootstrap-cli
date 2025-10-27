# AGENTS

## Overview
- This repository ships a CLI (`project_bootstrap.py`) that automates the kickoff of new Angular projects with Tailwind plus optional Three.js, Node.js API, Firebase (Hosting + Firestore), AWS S3, and GoDaddy DNS integrations.
- The tool wraps the workflow in sequential steps, persists state between runs, and presents interactive prompts with undo/redo so a human can spin up the project ecosystem quickly.

## Conceptual agents

### Stack Planner
- **Responsibilities:** uses `STACK_OPTIONS` and `NodeAPIConfig` to compose desired integrations, builds `UserConfig`, and decides whether to clone the Angular and Node.js templates.
- **Key inputs:** user preferences captured via prompts (`stack`, internal and public names, domain options) and remote templates (`TEMPLATE_REPO_URL`, `NODE_API_TEMPLATE_URL`).
- **Outputs:** populates `ExecutionContext.config` with consistent decisions and stores them in `.bootstrap_last_session.json`.

### Prompt Orchestrator
- **Responsibilities:** `PromptManager` centralizes the interactive experience, renders questions, shows colored summaries, supports `--undo/--redo`, and pre-fills previous answers.
- **Key inputs:** formatted messages, default values inferred from history, and validation rules (for example, name sanitization or domain confirmation).
- **Outputs:** emits `PromptOutcome` commands (`next`, `undo`, `redo`) that keep the CLI flow consistent.

### Step Executor
- **Responsibilities:** `StepExecutor` chains `Step` objects such as `step_clone_repository`, `step_create_firebase_project`, and `step_copy_build_directories`, providing rollback when possible.
- **Key inputs:** step list from `build_steps(ctx)`, the active context (`ctx.active_step`), and artifacts tracked in `step_backups` and `step_created_paths`.
- **Outputs:** incremental project provisioning, clear success/failure logs, and an ordered rollback trail.

### Infrastructure Provisioner
- **Responsibilities:** orchestrates steps that interact with external services such as Firebase (`step_create_firebase_hosting_sites`, `step_enable_firestore`), AWS S3 (`step_create_s3_buckets`), GoDaddy (`step_configure_godaddy_dns`), and Railway (`step_configure_railway_services`).
- **Key inputs:** API keys via environment variables (`GODADDY_API_KEY`, `GODADDY_API_SECRET`), local credentials (Firebase CLI, AWS CLI), and `ctx.replacements` for resource naming.
- **Outputs:** provisioned infrastructure or explicit entries in `remaining_tasks` when human intervention is required.

### Placeholder Curator
- **Responsibilities:** scans the extensions listed in `PLACEHOLDER_EXTENSIONS`, performs replacements (`step_replace_placeholders`), and duplicates configuration per environment (`step_update_environment_files`, `step_copy_build_directories`).
- **Key inputs:** placeholders (`PROJECT_PLACEHOLDER_ID`, `PROJECT_PLACEHOLDER_PUBLIC_NAME`, `PROJECT_PLACEHOLDER_PUBLIC_NOSPACE`) and the frontend root directory (`ctx.require_frontend_root()`).
- **Outputs:** Angular code with placeholders replaced plus updated `firebase.json` and environment files for `local`, `development`, `beta`, and `prod`.

### Tasks Recorder
- **Responsibilities:** `log_remaining` captures items that still need human action (for example, manual Railway API setup or DNS changes that could not be automated).
- **Key inputs:** calls sprinkled across steps whenever an automatic action cannot be completed.
- **Outputs:** final checklist presented to the user when the CLI finishes.

## Collaboration flow
- The Stack Planner kicks off the process and feeds the Prompt Orchestrator.
- Each valid answer triggers the Step Executor, which delegates sub-tasks to the Infrastructure Provisioner and Placeholder Curator.
- Whenever a step cannot finish automatically, the Tasks Recorder adds an entry so the human knows what is pending.
- The final state is persisted so subsequent runs can resume without repeating work.

## Expectations for new contributors
- Review `project_bootstrap.py` and the agents above before changing behavior; most decisions pivot on domain objects (`StackOption`, `UserConfig`, `ExecutionContext`).
- When adding new integrations (new "agents"), extend `STACK_OPTIONS`, add validations, and implement matching `Step` functions with rollback whenever feasible.
- Update the wrapper scripts (`ng-bootstrap-cli.cmd` and `.ps1`) if the entry point or required arguments change.



## Guardrail: Engineering Standards (SOLID, KISS & FP Lean)

**Intent**  
Enforce consistent engineering standards across all new/changed features: follow the project's code style, apply SOLID and KISS, and leverage functional programming where it **adds clarity and safety** - especially pure functions and immutability.

**Scope**  
- Applies to all code contributions (TypeScript/Angular, Node.js; UnityC# policy in Appendix).  
- Code and comments **must be in ENGLISH**.  
- Avoid pleonastic terms like "system"/"module"; prefer **handling**, **support**, **logic**, **utilities**.

---

### Core Principles

1) **KISS (Keep It Simple, Stupid)**
- Prefer the simplest design that solves the problem **today** (no speculative abstractions).  
- Reduce branching and nesting; extract small helpers when complexity grows.

2) **SOLID (pragmatic)**
- **S**ingle Responsibility: each class/function has one reason to change.  
- **O**pen/Closed: extend via composition/DI rather than editing internals.  
- **L**iskov: respect contracts; avoid surprising subtype behavior.  
- **I**nterface Segregation: smaller, focused interfaces over god-interfaces.  
- **D**ependency Inversion: depend on abstractions; inject collaborators.

3) **Functional Lean**
- **Pure functions first** for domain transforms (no I/O, no hidden state).  
- **Immutability by default**: prefer `readonly` (TS) / immutable structs & records (C#) / `const` bindings; clone or map instead of mutating.  
- Side effects only at the **edges** (I/O, UI, DB, network).  
- Composition over inheritance where viable.

---

### Language/Stack Notes

**Angular / TypeScript**
- Prefer **standalone components**, **OnPush** change detection, and **pure pipes**.  
- State as **readonly**; update via copies (`{ ...state, x: ... }`, `map`, `reduce`).  
- Strong typing everywhere (DTOs, API responses, signals/observables).  
- Side effects isolated (services/effects); components remain declarative.  
- Avoid "smart" templates; move logic into pure functions/utilities.

**Node.js / TypeScript**
- Domain logic in **pure functions** and stateless services; side effects at the **edges** (controllers, adapters, gateways).  
- Typed, explicit errors; no silent swallows.  
- Composition (middlewares/helpers) > inheritance frameworks.

---

### Implementation Checklist (Definition of Done)

- [ ] Code follows **project style** and **formatters/linters** clean.  
- [ ] **Pure core**: domain without I/O; encapsulate side effects.  
- [ ] **Immutability** in states and collections; avoid unnecessary in-place mutations.  
- [ ] **SOLID/KISS**: clear responsibilities; DI for dependencies.  
- [ ] **Tests** for pure functions (unit) and "edge adapters" with fakes/mocks.  
- [ ] Names precise (no "system/module"); comments/docstrings **in ENGLISH**.

---

### Examples (micro-patterns)

- **Prefer**:
  - `result = transform(input)` (pure)  
  - `next = { ...prev, count: prev.count + 1 }` (immutable update)

- **Avoid**:
  - `transformAndSave(input, repo)` that both mutates state and does I/O  
  - `prev.count++` on shared objects

---

### PR Acceptance Gates

- If a simpler design exists -> request simplification (KISS).  
- If domain logic mixes I/O -> request extraction to a pure core.  
- If state mutates in-place without reason -> request immutable updates.  
- If abstractions do not respect SOLID -> request **refactoring** (small interfaces, DI).
 
**CI Gates**: Lint, type-check, and unit tests must pass in CI. Commit messages are validated by a pre-commit hook (regex: title in gerund, quoted context, no trailing period, and ` [...]` only when a multi-line description follows).

## Agent: Commit All (Repo + Submodules)

**Intent**  
Commit all pending changes in the current Git repository **and** in all submodules, generating **standardized English commit messages** and splitting commits when it improves clarity.

**When to Run**  
- After local edits, before sharing work.
- From the superproject root. Submodules must be initialized.

**Assumptions / Preconditions**  
- Git 2.35+ available.  
- Author identity configured (`user.name`, `user.email`).  
- Working tree clean of in-progress merges/rebases/cherry-picks.  
- Submodules initialized and checked out.

**Inputs (optional)**  
- `allow_split: boolean` (default: `true`) - split commits by logical context/change type.  
- `max_split: number` (default: `5`) - upper bound to prevent over-fragmentation.  
- `dry_run: boolean` (default: `false`) - print the plan and messages, do not commit.  
- `include_untracked: boolean` (default: `true`) - include new files.  
- `push: "no" | "if_upstream" | "set_upstream:<remote>"` (default: `"no"`) - pushing is **opt-in**.  
- `message_preview: boolean` (default: `true`) - echo final messages before commit.

---

### Commit Message Standard

**1) TITLE (single line, active voice, present participle/gerund, no trailing period)**  
Accepted formats:  
- `a) <verb-ing> <feature/alteration> in "<context>"`  
- `b) <verb-ing> "<Feature Name>" features`  
Examples of verbs: adding, updating, fixing, refactoring, introducing, removing, renaming, improving.  
**Contexts MUST be quoted**, e.g.: `"Features/UI - Panels"`, `"Features/Database - SQLite"`, `"Features/App - Main Menu"`, `"Utils"`. Define **context** as the top-level feature/folder path or a well-known domain tag; always quoted.  
Do **NOT** end the title with ` [...]` if there is **no** description.  
Only append ` [...]` when a multi-line description follows.

**2) DESCRIPTION (optional; only if needed for clarity)**  
- Use bullet lines starting with `- ` in present participle (gerund).  
- You may group bullets by context using a quoted header line, e.g.:  
```

"Features/UI - Panels":
- implementing "reset" action handling
- implementing "next" action handling

```
- Prefer terms like **handling**, **support**, **logic**, **utilities**. **DO NOT** use "system"/"module".

**3) SCOPE & HYGIENE RULES**  
- Do **NOT** mention TODO lists, personal tracking, or tags like `[WIP]`, `[FAKE-STASH]`, etc. Ignore them entirely.  
- Avoid pleonastic/generic terms such as "system"/"module".  
- Small, unambiguous changes -> **TITLE ONLY** (no ` [...]`).  
- Multiple areas/deliverables -> **TITLE + ` [...]`** and bullets. All contexts quoted both in title and headers.

**4) SUBMODULES**  
- For each submodule with pending changes: make local commits following the **same** message standard (contexts quoted).  
- Back in the superproject, commit the updated submodule pointers:  
  - If a title is enough: `updating submodule pointers`  
  - If details are needed: `updating submodule pointers [...]` with bullets listing affected contexts/paths in quotes.

**5) SPLITTING COMMITS (IF IT IMPROVES CLARITY)**  
- Split pending changes **when it meaningfully improves** clarity/traceability (and simplifies reverts/conflict handling).  
- Favor atomic commits per logical context or change type (feature vs fix vs refactor).  
- Ensure each resulting commit still follows **all** message rules above.

**Examples**  
- **Title only** (no description, no ` [...]`):  
```
adding attribute-based mapping and query helpers in "Features/Database - SQLite"
adding StringUtils text sanitization helpers in "Utils"
```
- **Title + description** (with ` [...]`):  
```
finishing "QueuePanel v1" features [...]
- implementing "reset" action handling
- implementing "next" action handling
- adding queue clearing on new session starting
- keeping HUD open after game ends
- keeping floor visual state after game ends
- fixing queue list panel responsiveness on non-1080p screens
```

---

### Procedure (Algorithm)

1. **Scan pending changes**  
 - Superproject: `git status --porcelain=v2` (include untracked if `include_untracked`).  
 - Collect file paths, submodule dirtiness.

2. **Handle submodules first**  
 - For each dirty submodule (recursive):  
   - Enter submodule.  
   - Group files by **context** (top-level folder or feature path) and **change type** (feature/fix/refactor/rename/remove).  
   - If `allow_split`, split into up to `max_split` logical commits.  
   - Build messages per **Commit Message Standard**.  
   - Stage group -> `git commit -m "<TITLE>"` and, if needed, `-m "<bullets>"`.  
 - Return to superproject.

3. **Update superproject pointers**  
 - `git add <submodule paths>` for those that advanced.  
 - Commit pointer update:  
   - Minimal: `updating submodule pointers`  
   - Or `updating submodule pointers [...]` + bullets listing `"path/to/submodule"` and short SHAs.

4. **Commit superproject files**  
 - Group by context/change type; split if `allow_split`.  
 - Generate messages; commit each group.

5. **Optional push**  
 - If `push: "if_upstream"` and the current branch has upstream -> `git push`.  
 - If `push: "set_upstream:<remote>"` and no upstream -> `git push -u <remote> <current-branch>`.  
 - Otherwise, **do not push**.

6. **Output**  
 - Print a summary table with repo path, commit count, and last commit SHAs.

### Failure Modes & Safe-Guards

- **In-progress operations** (merge/rebase/cherry-pick): abort with instructions to resolve/abort before running.  
- **Detached HEAD**: create `auto/commit-<YYYYmmdd-HHMM>` and proceed (report branch name in output).  
- **No changes** in a scope: skip politely.  
- **Renames**: prefer `git mv` detection to avoid noisy deletes/adds.  
- **Line endings / perms only**: collapse into a single housekeeping commit if isolated.

## Appendix A - Cross-repo policy (UnityC#)

**Unity / C#**
- Keep logic pure outside `MonoBehaviour`; use `MonoBehaviour` only to orchestrate I/O and lifecycle.  
- Prefer **ScriptableObject** for configuration; avoid static singletons for state.  
- Use **interfaces** + DI (constructor or explicit setters) for services.  
- Favor structs only for small value types; avoid boxing hot paths.  
- Thread-safety: no mutable shared state; use immutable messages for jobs/tasks.

---
```
