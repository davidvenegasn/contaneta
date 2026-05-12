---
name: research
description: Performs product-first research with explicitness-first mindset. Never infers product intent. Asks clarifying questions when info is missing. Saves to context/research/{YYYY-MM-DD}-{slug}.md.
---

# Research (Product-first, Explicitness-gated)

## Purpose

Understand the product correctly, not quickly. Treat anything the user has not stated explicitly as unknown.

## Core rule: explicit beats inferred

> If the user has not stated something explicitly, treat it as unknown.

Do NOT:
- Infer user goals or success criteria
- Guess user flows or fill gaps with "common sense"
- Use prior session experience to complete missing context

## When to ask questions

Ask if the information is implied, ambiguous, open to interpretation, or critical to product coherence.

The bar: "Could a reasonable person interpret this in more than one way?" If yes → ask.

## Dimensions that must be explicit

Before saving research, confirm with the user:

1. **User and context** — who, when, in what workflow.
2. **Problem statement** — what is broken, why it matters, what happens if nothing changes.
3. **Value and success** — concrete value, observable measure, what counts as failure.
4. **Proposed solution** — restate in your own words and ask for confirmation.
5. **User flow** — start, happy path, error path, end.
6. **Scope and boundaries** — in-scope, out-of-scope, MVP vs final.

## Allowed outputs

A single research session message may produce ONE of:

- **A) Clarifying questions** grouped by product dimension.
- **B) A saved research document** (only when all dimensions are explicitly confirmed).

## Completion gate

Research is complete only when:
- No critical product information is inferred.
- Product logic is coherent end-to-end.
- Remaining doubts are documented as risks.

If any doubt remains, ask. Do not proceed.

## Output

Save to: `./context/research/{YYYY-MM-DD}-{slug}.md`

The document must include:
- Explicit statements vs confirmed assumptions
- Product reasoning
- Final verdict: **READY FOR PLANNING: yes / no**
