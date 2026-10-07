---
title: "Efficient Build Workflow"
tags: [build-rules, code-review, workflow]
status: active
created: 2026-10-07
---

# Efficient build workflow

Use this sequence for every new feature, fix, or automation change in
[pinterest-builder](https://github.com/michaelchamboko/pinterest-builder).

1. **Inspect.** Read `AGENTS.md`, the relevant plan and runbook, and the current code.
   For new features or repeated operational logic, read
   [code-structure](https://github.com/michaelchamboko/build-faster-skills/blob/main/code-structure/SKILL.md).
   Finish when the existing flow, invariants, and smallest useful change are clear.
2. **Structure.** Keep domain policy, state transitions, and orchestration in the batch
   or export flow. Keep provider calls and reusable mechanics in service modules.
   Extract a shared function only after the same mechanic appears in two callers.
3. **Build.** Implement one bounded slice. Preserve exact affiliate URLs, keep secrets
   in `.env.local`, and add tests for changed behavior and failure paths.
4. **Prove.** Run `python -m unittest discover -v` and the relevant live verification.
   In Codex, use bundled `@Code Review`; never use
   [Greploop](https://github.com/michaelchamboko/build-faster-skills/blob/main/greploop/SKILL.md).
   Resolve every actionable finding, rerun checks, and stop after three failed fixes to
   identify the assumption that is probably wrong.
5. **Finish.** Apply
   [Unslop](https://github.com/michaelchamboko/build-faster-skills/blob/main/unslop/SKILL.md)
   to documentation, marketing copy, commit messages, and PR text. Use
   [michaelchamboko/marketingskills](https://github.com/michaelchamboko/marketingskills)
   for copy in the [Pinterest Builder](https://github.com/michaelchamboko/pinterest-builder)
   workflow.
   Review the staged diff and secret exclusions before committing or pushing.

Efficiency means one source of truth, one bounded change, one verification loop, and
no speculative abstraction.
