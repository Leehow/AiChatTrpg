"""Dice rule design agent.

A focused side-agent that lets the user author dice procedures (CoC d100,
d20-vs-DC, PbtA 2d6, dice pool, …) by describing them in natural
language. Wraps the existing `agents.trpg.check_ir.compile_to_ir_direct`
+ `agents.trpg.check_runtime.execute_check_runtime` infrastructure.

Separate from the main rule editor agent — different system prompt,
different tools, different SSE endpoint. Keeps the main agent's
context lean (no dice prompt clutter) and lets dice authoring live in
its own focused conversation.

Design: docs/design/2026-05-01-rule-editor-agent.md §11 P3.5
"""
