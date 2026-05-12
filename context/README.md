# Context — Workflow artifacts

Esta carpeta guarda los artefactos del workflow Research → Plan → Implement → Review → QA.
Cada artefacto se nombra `{YYYY-MM-DD}-{slug}.md` donde el slug es el mismo a lo largo de todas las fases de un cambio.

## Estructura
- `research/` — preguntas, decisiones de producto, definicion explicita
- `plan/` — plan determinista de implementacion
- `implementation/` — log de cambios realizados
- `review/` — auditoria final del cambio
- `qa/` — resultado de tests y verificacion

## Como se usa
Ver `.claude/skills/` para los skills que generan estos artefactos.
Ver `CLAUDE.md` seccion "Workflow" para el flujo completo.
