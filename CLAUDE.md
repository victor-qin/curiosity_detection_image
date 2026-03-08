
  # Web Development Process

  ## Planning Requirements

  When entering plan mode or creating implementation plans, follow these requirements strictly.

  ### 1. Be Specific About Code Changes

  Every plan must explicitly list each function/method/class that will be **added**, **edited**, or **deleted**. For
  each one, include:

  - The file path and function/method name
  - Whether it is being added, modified, or removed
  - Pseudocode showing the core logic

  Do not describe changes vaguely (e.g., "update the handler"). Spell out the exact functions affected and what the
  pseudocode looks like for each.

  ### 2. Critically Review Your Own Plan

  Before presenting a plan, actively look for problems with it:

  - Identify edge cases, race conditions, or error scenarios the plan doesn't handle
  - Check for missing steps, incorrect assumptions, or overlooked dependencies
  - Consider whether the plan breaks existing functionality or tests
  - Flag any risks or trade-offs explicitly in the plan

  If issues are found, do not just flag them — propose excellent, well-reasoned solutions for each one. Explain why the
  proposed solution is the right fix and incorporate it into the plan. Only present truly unresolvable trade-offs to the
   user for discussion.

  ---

  ## Production Migration Rules

  When a code change involves any of the following, you **must** include a `## Migration Plan` section in your response
  before the change is considered complete:

  - Database schema changes (new/altered tables, columns, indexes, constraints)
  - New or changed environment variables
  - Config file changes (nginx, systemd units, cron jobs, etc.)
  - New system dependencies or packages

  ### Migration plan structure

  Every migration plan must include these sections in order:

  #### 1. Pre-deploy

  - Back up the database (include the exact command, e.g., `pg_dump`, `mysqldump`, `sqlite3 .backup`)
  - Note the current git SHA so you can revert if needed: `git rev-parse HEAD`
  - For large data migrations: check available disk space

  #### 2. Ordered migration steps

  List every step as a numbered command. Explicitly call out ordering dependencies:

  - State whether each step must run **before** or **after** the code deploy (git pull)
  - State whether the migration is **backwards-compatible** with the currently running code (this matters during the
  brief window between running the migration and restarting the server)
  - If multiple migration steps exist, state their ordering dependencies on each other

  Example format:
  1. [BEFORE deploy] Add new column as nullable: python manage.py migrate
    - Backwards-compatible: yes (old code ignores the new column)
  2. [AFTER deploy] Git pull + restart
  3. [AFTER restart] Backfill column: python manage.py backfill_foo
    - Depends on: step 2 (new code has the backfill command)

  #### 3. Restart

  Reference the project's restart script or process. Do not assume a specific script name — check the project's README,
  Makefile, or package.json for the correct command.

  #### 4. Post-deploy verification

  Include specific checks to confirm the migration succeeded:

  - Database: query to verify the schema change or data state
  - Config: command to verify the service loaded the new config (e.g., `nginx -t`, `systemctl status`)
  - Env vars: confirm the application reads the new value (e.g., check logs, curl a health endpoint)
  - Smoke test: a user-facing action to verify nothing is broken

  ### Rollback plan (risky changes only)

  A rollback section is **required** when the migration is destructive or hard to reverse:

  - Dropping columns, tables, or indexes
  - Renaming fields or tables
  - Transforming data in-place (irreversible data changes)
  - Removing environment variables that running code depends on

  For these changes, include:

  - Exact commands to reverse the migration, **or**
  - Instructions to restore from the pre-deploy backup
  - Whether the rollback requires a code revert (git checkout of the previous SHA) in addition to the data rollback

  For additive, non-destructive changes (adding a nullable column, adding a new env var), a rollback section is not
  required.

  ### Reasoning checklist

  Before presenting the migration plan, reason through these questions explicitly:

  1. **Order**: Does the migration run before or after the code deploy? Why?
  2. **Compatibility window**: During the seconds/minutes between migration and restart, is the running code compatible
  with the new DB state?
  3. **Failure mode**: If the migration fails halfway, what state is the database in? Is it safe to re-run?
  4. **Dependencies**: Do any migration steps depend on others completing first?

  ---

  ## Dev Server Port Awareness

  Multiple dev servers may run in parallel on different ports. To avoid CORS / proxy / cookie breakage that different
  ports cause, follow these rules:

  ### Why different ports break things in dev

  In browsers, the **origin** is `protocol + hostname + port`. `http://localhost:3000` and `http://localhost:3001` are
  **different origins**, which triggers:

  - **CORS rejection** — the backend's allowlist doesn't include the new port.
  - **Proxy misconfiguration** — bundler proxies (Vite, webpack, Next.js) forward to a hardcoded backend port.
  - **Cookie / session loss** — cookies are scoped by origin; a different port means auth cookies aren't sent.
  - **Hardcoded env vars** — values like `API_URL=http://localhost:3000` don't match the actual port.

  ### Rules

  1. **Use permissive CORS in dev only.** Configure backends to accept any localhost origin in development (e.g.,
  `origin: /^http:\/\/localhost:\d+$/`). Never use a wildcard `*` with `credentials: true` — echo the request's `Origin`
   header back instead. **Production CORS must remain locked to explicit origins.**

  2. **Make ports configurable via env vars, not hardcoded.** URLs like `NEXT_PUBLIC_API_URL` or proxy targets should
  read from environment variables so parallel servers on different ports still connect correctly.

  3. **Configure cookies for localhost broadly.** In dev, set cookies with `Domain=localhost` (no port restriction) and
  `SameSite=Lax` so they're sent across ports.

  4. **Prefer a reverse proxy for complex stacks.** When a project has multiple services (frontend, API, WebSocket), put
   them behind a single local proxy (e.g., nginx, Caddy) on one port. All services then share the same origin and
  CORS/cookies work automatically.

  5. **Check for port conflicts before starting.** Run `lsof -iTCP -sTCP:LISTEN -nP` to see what's already running. Only
   kill a process if it's a stale/orphaned server, not a server from a parallel workflow.

  6. **Use the project's default port when possible.** This avoids needing to reconfigure other services that expect it.

  7. **Clean up when done.** Stop your dev server when testing is complete so the port is freed.

  ---

  ## Pre-Push Checklist

  Before every push to a PR branch, run these steps in order:

  1. **Lint**: Run the project's linter — fix all errors (warnings are acceptable)
  2. **Tests**: Run the full test suite — all tests must pass
  3. **Review**: Review changed code for reuse, quality, and efficiency issues, then fix any findings

  This ensures CI passes and code quality is maintained before review.

  ## Pre-Merge Checklist

  Before merging a PR, review whether project documentation (including CLAUDE.md) needs updates:

  - **New architectural patterns** — Did the PR introduce a pattern that future work should know about? Document it.
  - **New key files or components** — If a new component or hook was added that other features will build on, note its
  purpose and API.
  - **Test count** — Update the test count if tests were added or removed.
  - **Changed conventions** — If the PR changes how something is done (e.g., new prop patterns, new mock patterns),
  update the relevant section.
  - **Infrastructure changes** — New env vars, ports, scripts, or dependencies must be documented.

  ---

  ## Deployment Architecture Principles

  When setting up or documenting production deployments:

  ### Separate client vs server URLs

  Client-side code (browser JS) and server-side code (API routes, SSR) often need different URLs for the same backend
  service. Document this split explicitly:

  - Client URL: baked into JS at build time, must be reachable from the user's browser
  - Server URL: resolved at runtime inside the container/server, often uses internal Docker networking or localhost

  Define a clear fallback chain (e.g., `INTERNAL_URL ?? PUBLIC_URL`) and document where it lives.

  ### Make ports configurable

  All service ports should be configurable via environment variables with sensible defaults. Document the port
  assignments in a table so the full topology is visible at a glance.

  ### Document the startup order

  When multiple services depend on each other, document the orchestration sequence: which service starts first, what
  health checks to wait for, and what data must be seeded before the app is ready.

  ### Scripts should be idempotent

  Startup and teardown scripts should be safe to run multiple times. Re-running a start script should detect an
  already-running service and print status rather than fail or create duplicates. Teardown should be safe when already
  stopped.

  ---

  ## Documenting Runtime Constraints

  When a project depends on external services with unusual limitations (e.g., single-threaded inference engines,
  rate-limited APIs, eventually-consistent databases), document them in CLAUDE.md with this structure:

  1. **The constraint** — what the limitation is and what symptoms appear when violated
  2. **The solution** — the specific code pattern or architecture used to work around it
  3. **Where it lives** — the exact file(s) and function(s) implementing the solution

  This prevents future contributors from unknowingly reintroducing bugs that the architecture was specifically designed
  to prevent.

