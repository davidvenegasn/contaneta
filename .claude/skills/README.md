# Claude Skills

Custom skills for the ContaNeta project. Adapted from a Node.js/MongoDB enterprise workflow to Python/FastAPI/SQLite stack.

## Workflow skills (use in order)
- `research.md` — Product-first research with explicit confirmation
- `planner.md` — Deterministic implementation plan
- `programmer.md` — Strict execution following plan + CLAUDE.md
- `reviewer.md` — Final authority audit
- `qa.md` — pytest + endpoint verification via FastAPI TestClient

## Utility skills
- `commit-and-push.md` — Conventional commits, no AI references, no trailers

## How to invoke
In Claude Code, use the Skill tool or reference the skill name. Each skill's frontmatter has a description that the harness uses for relevance matching.

## Outputs
All workflow skills save artifacts to `context/{phase}/{YYYY-MM-DD}-{slug}.md`. The slug stays the same across all phases of a single change.
