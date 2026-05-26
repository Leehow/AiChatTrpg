# Rule Editor Long-Flow Reference

## Canonical Scenario

Use a fresh local test asset. Avoid user-owned rulesets unless the user
explicitly asks to test one.

- Draft name: `E2E-RuleEditor-MistTown-<timestamp>`
- Ruleset concept: light folk-horror investigation, simpler than Call of
  Cthulhu.
- Player/user persona: ordinary TRPG fan, not a developer, does not know
  ChatRPG internals.
- Repair loop: discover that a generated character skill label and a dice
  check input do not align; repair through natural language; prove the fixed
  version is used.

## Example Human Prompts

These are examples of allowed style, not a required exact script:

```text
我想做一个小镇怪谈规则，像克苏鲁但简单点。
玩家都是普通人，不要太多数值。
我也不知道角色卡该有什么，你帮我定。
调查失败别直接卡死，给点代价也行。
要有害怕或者压力，但别太复杂。
如果遇到危险，最好也能受伤或者逃跑。
骰子就简单一点，我不想每次查表。
这个规则能不能真的开一局？
我感觉这里有些东西还是空的，你帮我补完整。
如果技能只是“擅长/普通”这种，掷骰时怎么算？
保存一下，我想拿它开房间。
刚才跑的时候检定好像没吃到角色卡，你帮我修一下。
修好后覆盖原来的那套，不要变成另一套我找不到的规则。
```

Forbidden in ordinary-user scripts:

```text
请生成 parsed_v6。
请补 dice_ir。
让 check_spec 的 procedure_id 读取 skills.observe.value。
用 JSON patch 更新 vitals.hp.value。
```

## Oracle Table Template

| Phase | Hidden expectation | Evidence | Failure severity |
|---|---|---|---|
| Initial draft | Playable sections exist; no placeholders | Export/draft JSON + UI sections | P0 if unplayable |
| Dice design | Checks compile and execute deterministically | Check spec/IR evidence + sample run | P0 if LLM-only adjudication |
| Field alignment | Character fields match check inputs | Field list vs check input list | P0 if silent default |
| Save/publish | Ruleset has traceable version identity | ID/revision/hash/timestamp/export | P0 if target cannot be proven |
| Repair | Natural-language edit changes the broken part only | Before/after diff | P1 if unrelated drift |
| Reuse | Existing or new room uses repaired version | Runtime rule identity + successful check | P0 if old version used silently |
| Persistence | Chats and drafts survive reload | Message counts/screenshots | P1 if history loss |

## Feedback Rubric

Score each category from 1 to 5 and include one concrete observation:

- Prompt naturalness: did the system work with vague normal language?
- UI clarity: could a new user tell what state the draft/save/target is in?
- Trust: did the user see enough evidence that the rule was real and usable?
- Repairability: could the user fix a defect without knowing internals?
- Continuity: did chat, dice design, draft state, and target version remain
  coherent?
- Friction: where did the user need to repeat, over-specify, or use unnatural
  wording?
