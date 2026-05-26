# Gameplay Long-Flow Reference

## Canonical Chapter

Use a fresh local test asset unless the user explicitly asks to continue an
existing session.

- Ruleset: a known playable folk-horror investigation ruleset.
- Session name: `E2E-Gameplay-MistTown-<timestamp>`
- Chapter: `Chapter 1: The Clinic Rhyme`
- PC: Lin An, elementary school teacher looking for a missing student.
- Desired arc: hook -> social scene -> investigation -> fear -> danger ->
  conflict/chase -> injury -> recovery -> clue summary -> next hook.

## Example Player Script

These are examples of allowed style, not a required exact script:

```text
我先去找孩子妈妈问问。
我不想直接吓她，就先问最近有没有怪事。
她不说的话，我看看屋里有没有什么不对劲。
那个书包我能翻一下吗？
照片背面是不是有字？
我有点慌，先把门关上。
我听听外面是不是有人走过去。
如果需要掷骰你来决定。
失败了也别让我卡住，给我一点线索但有代价。
我去旧公交站看看。
我先在外面看，不急着进去。
那个人还在吗？我躲一下。
我小声问一句：你是谁？
这个声音像孩子吗？
我稳一下，不想马上跑。
我用手机拍墙上的东西。
别直接碰，我用纸垫着。
糟了，我往后退。
能躲就躲，别硬扛。
我跑到有灯的地方。
我看看自己伤得重不重。
能不能先包扎一下？
我整理一下现在知道的线索。
下一步我想回学校找档案。
```

Forbidden in ordinary-player scripts:

```text
请输出 [ROLL] 并更新 memory_state。
用 UPDATE_PC_PARAMS 把 vitals.hp.value 改成 5。
触发 check_spec procedure_id sanity_roll。
把 scene_id 设置为 abandoned_clinic_basement。
```

## Oracle Table Template

| Phase | Hidden expectation | Evidence | Failure severity |
|---|---|---|---|
| PC creation | Character has playable fields and visible status | UI + session state | P0 if cannot play |
| Social scene | NPC identity remains stable | Chat + memory/debug view | P1 if name drift |
| Investigation | Clue acquired despite vague action | Message + memory/item state | P0 if progress blocks |
| First check | Real engine check occurs | Check log with inputs/roll/outcome | P0 if narration only |
| Fear/pressure | Stress/sanity or equivalent changes or records consequence | State diff + visible UI | P1 if only flavor |
| Danger | PC/NPC state changes after conflict/chase | HP/wound/NPC diff | P0 if no consequence |
| Marker handling | Internal markers consumed, not leaked | Chat DOM + state diff | P0 if raw marker visible |
| Stream recovery | Refresh/navigation does not duplicate or lose state | Message counts + screenshots/network | P0 if double apply |
| Recap | GM summary matches actual clues/status | Chat + state/memory comparison | P1 if hallucinated |

## Feedback Rubric

Score each category from 1 to 5 and include one concrete observation:

- Naturalness: did normal fuzzy player language work?
- Agency: did player choices change scene, risks, or state?
- Rule trust: did dice/check/state evidence match the narration?
- Continuity: did NPCs, clues, time, and scene remain coherent?
- Recovery: did refresh/navigation/stream interruption feel safe?
- Pacing: did the GM move the chapter forward without skipping consequences?
- Friction: where did the player need to over-explain or repeat themselves?
