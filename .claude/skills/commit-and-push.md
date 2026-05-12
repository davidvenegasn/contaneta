---
name: commit-and-push
description: Performs commit and push using conventional commits. Commit messages in English. No AI/agent references. No trailers. Inferred type/message if user does not provide them.
---

# Commit and push

Perform a commit and push of all pending changes using conventional commits. The commit message must be in English.

## Exclude AI/agent references

- **Commit message:** Describe only the code or product change. Do NOT mention Claude, AI, or how the change was produced (avoid "via Claude", "AI-generated", "from assistant").
- **Confirmation to user:** When confirming success, do NOT include any reference to AI or how the commit was made. Only state branch, commit message, and that push succeeded.
- **No trailers:** Run only `git commit -m "type: message"`. Do NOT use `--trailer` or any option that adds footers (no `Co-Authored-By`, no `Made-with`).

## If user provided type and message

Use them. Normalize type to lowercase. Format as: `type: message` (e.g., `feat: add invoice retry button`). Then run the steps below.

## If user did NOT provide type and message: infer automatically

1. **Stage and inspect:**
   - `git add -A`
   - `git status -s` and `git diff --cached --stat`
2. **Infer type and message:**
   - Type hints:
     - `.claude/`, config, scripts → `chore`
     - `routers/`, `templates/` new screens/flows, new user-facing behavior → `feat`
     - Bug fix (error handling, wrong logic) → `fix`
     - Same area, clearer code, no new behavior → `refactor`
     - Docs only → `docs`
     - Tests added/updated → `test`
     - Formatting only → `style`
     - CI/build/deps → `ci` / `build`
     - Performance → `perf`
   - Message: Short, imperative, English, lowercase after the colon. Describe only the change.
3. **Commit and push** with the inferred `type: message`.
4. **Confirm:** show only branch name, commit message, push status.

## Allowed types

- `feat` — new feature
- `fix` — bug fix
- `chore` — maintenance, config, tooling
- `improvement` — non-breaking enhancement
- `docs` — documentation only
- `refactor` — neither fixes a bug nor adds a feature
- `style` — formatting
- `test` — tests added or updated
- `ci` — CI config
- `build` — build system or deps
- `perf` — performance

## Steps

1. Confirm there is a git repository.
2. `git pull origin $(git branch --show-current)` to fetch and integrate remote changes. If conflicts, stop and inform user.
3. `git add -A`
4. If nothing to commit (`git diff --cached --quiet`), say so and stop.
5. `git commit -m "type: message"` in English. No `--trailer`.
6. `git push origin $(git branch --show-current)`
7. Confirm: branch name + commit message + push success.

## Never run destructive or force commands.
