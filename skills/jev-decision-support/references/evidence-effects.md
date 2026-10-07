# How sensitive Jev is to what you send

Read when tuning evidence or investigating surprising results. These recorded
code-review observations with `jev-1.13.0` explain the safeguards in `SKILL.md`;
the magnitudes are case-specific, not calibrated thresholds.

## Leaked judgments and claims move the answer

- One unlabeled sentence claiming a serious defect flipped a correct commit from
  `ready` to `needs_changes` (P(needs_changes) 0.19 to 0.87).
- Verbatim tool output was the strongest input measured: a real type-checker
  failure moved P(needs_changes) from 0.21 to 0.98, while a confident claim that it
  was a false positive barely moved it.
- Putting an unverified observation under a labeled key such as
  `agent_observations` cut a false claim's effect by about two-thirds — reduced, not
  removed. Leaving it out entirely is safer.
- A `proposal_by_agent` added to a batch also shifted that batch's unrelated
  questions, which is why the skill asks for a separate call.

## Context dominates the artifact

- In one controlled case (5 calls per arm), rich context raised spec-fit from about
  0.35 to 0.89 and cut P(needs_changes) from about 0.49 to 0.18. Swapping a commit
  that failed its type checker for the fixed commit changed almost nothing.
- Sharper is not more correct: Jev judges the evidence you project, so a defect that
  only an unrun check would reveal stays invisible. Run deterministic checks yourself.

## Presentation order matters

- Answers shifted by about 0.1, and a top choice flipped, when only the JSON key
  order changed. Keep context and question order fixed when comparing calls, and do
  not over-read the second decimal of a single call.
