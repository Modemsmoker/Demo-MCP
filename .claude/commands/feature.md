---
description: Run the plan -> implement -> review pipeline for a Demo-MCP change
argument-hint: <what you want built or fixed>
---

Deliver this change to the Demo-MCP server: **$ARGUMENTS**

Run the three-stage pipeline. Your job in the main thread is to be a thin
coordinator — the reason this pipeline exists is to keep bulk file reads, test
output, and build logs out of *this* context. So do not read source files
yourself, and do not paste subagent output back into the conversation.

## Stage 1 — Plan

Spawn `mcp-planner` with the request above. It writes
`.claude/handoff/<slug>.plan.md` and returns a summary.

Show me the outcome sentence, the commit line, and the step count, then **stop
and wait for my approval.** If the planner returned open questions, ask me those
instead of proceeding.

## Stage 2 — Implement

Once I approve, spawn `mcp-implementer` and give it the handoff file path plus
any amendments I made. Do not re-describe the plan — the file is the spec.

Report back its file list and the `make check` result.

If `make check` fails, send the failure back to the *same* implementer via
SendMessage rather than spawning a fresh one — a new agent would re-read
everything from cold.

## Stage 3 — Review

Spawn `mcp-reviewer` with the handoff file path.

- **REQUEST CHANGES** → send the blocking findings back to the existing
  implementer with SendMessage. Re-review after. Cap at two rounds; if it is
  still failing, surface it to me rather than looping.
- **APPROVE** → show me the verdict and the final commit message.

## Finish

Print the `git commit` command for me to run. Do not commit or push yourself.

## Skip the pipeline when

The change is a typo, a comment, a version bump, or a one-line doc edit. Just do
those directly — three agent spawns cost far more than the edit is worth.
