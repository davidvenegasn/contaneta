# Review: Portal Polish Fase 1 — CSS-only polish

**Date:** 2026-06-09

## Diff Review

### Correctness
- All changes are CSS-only — no behavior, routing, or query changes
- Token references (`--border-strong`, `--border`, `--primary`, `--surface-hover`) are all defined in portal_tokens.css
- Focus ring tokens (`--focus-ring`, `--focus-ring-offset`) defined in portal_tokens.css:110-111
- tabular-nums selectors target real classes used in templates

### Nightmode
- `--border-strong` resolves correctly in nightmode via portal.css dark overrides
- `--border` resolves to `rgba(255,255,255,.08)` in nightmode (portal.css:3738)
- `--primary` / `--surface-hover` have nightmode overrides in portal_dark_overrides.css
- Focus ring uses `var(--accent)` which has nightmode override
- Dev debug panel still uses hardcoded `#fff` background — acceptable (dev-only, not user-facing)

### Accessibility
- Focus rings now use `outline` instead of `box-shadow` — more reliable, not affected by `box-shadow: none !important` suppression
- All `:active` states provide visible press feedback
- `prefers-reduced-motion` not affected (no new animations added, only transform which is instant at scale(.97))

### Risks
- Month-picker hover now shows `var(--primary)` border (indigo) instead of gray — this is a deliberate visual improvement, more polished
- The `scale(.97)` on btn-ghost/icon-btn active is very subtle and won't break layouts

## Verdict: PASS
No issues found. Safe to commit.
