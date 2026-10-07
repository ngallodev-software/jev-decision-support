# API usage

Read when constructing requests, importing helpers, selecting primitives,
rebuilding decisions, or enforcing domain completeness.

## Python imports and validated batch

Add the resolved skill's `scripts` directory to `sys.path` before importing.
Run Python with `<skill-dir>/.venv/bin/python`; the installer provides the SDK.
Authentication comes from the agent runtime, not the skill metadata.

```python
from jev_decision import buildJevRequest, executeJevRequest, rebuildJevRequest

context = {
    "requirement": "Verbatim requirement text",
    "proposals": {"reuse": "Full proposal text", "replace": "Full proposal text"},
    "repository_evidence": [{"source": "src/cache.py:18", "text": "Exact source"}],
    "verification": {"output": "Verbatim check output", "not_exercised": ["migration"]},
}
questions = {
    "best_option": {
        "type": "choice",
        "instructions": "Which proposal best fits the requirement and evidence?",
        "criteria": {
            "reuse": "Extend the existing helper",
            "replace": "Replace it with the proposal",
            "insufficient_evidence": "Neither option is justified by the evidence",
        },
    },
    "supported": {
        "type": "noul",
        "instructions": "Is the evidence sufficient to choose a proposal?",
        "criteria": {"true": "Sufficient evidence", "false": "Material evidence missing"},
    },
    "risk": {
        "type": "score",
        "instructions": "How much migration risk do the supplied proposals introduce?",
        "criteria": ["Low: localized", "Moderate: shared behavior", "High: irreversible state"],
    },
}
built = buildJevRequest(context, questions, purpose="Choose an implementation approach")
result = executeJevRequest(built, timeout=90)

# Only after retrieving materially new evidence or changing alternatives:
revised_context = {**context, "migration_check": "Verbatim new check output"}
revised = rebuildJevRequest(
    built, revised_context, questions, change_reason="Added migration-check output"
)
```

The builder returns `request`, `request_sha256`, `decision_sha256` (state+questions),
state/question hashes, byte counts, and revision metadata. Purpose is local metadata,
not evidence. Preserve the previous decision hash and revision reason.

## Convenience helpers and response fields

`makeJevDecision` builds, executes, and validates a single question named `decision`.
`makeJevDecisions(context, questions)` does the same for a batch with the question
map above. Both return full API JSON: `model`, `answers`, and `usage`.

```python
from jev_decision import makeJevDecision, makeJevDecisions

result = makeJevDecision(
    context,
    "Which proposal best fits the requirement and evidence?",
    {"reuse": "Extend the helper", "replace": "Replace it", "unknown": "Need evidence"},
)
answer = result["answers"]["decision"]
print(answer["choice"], answer["confidence"], answer["probabilities"])

result = makeJevDecisions(context, questions, timeout=90)
```

- **Choice:** `kind="choice"` (default); 2–255 IDs with descriptions, or unique
  string IDs. Prefer descriptions. Response: `choice`, `confidence`, `probabilities`.
- **Noul:** `kind="noul"`; omit `acceptable_answers` or supply exactly `true`/`false`
  descriptions. Response: `noul`, the probability that the proposition is true.
- **Score:** `kind="score"`; `acceptable_answers` is 2–10 ordered descriptions.
  Response: `score`, `legend`, `confidence`, `probabilities`.

All helpers accept `model=None` for the SDK default (`TYPESAFE_DEFAULT_MODEL`),
or an explicit model ID. `timeout` defaults to 30 seconds for helper-owned clients.
The raw SDK's `client.system_one` skips helper validation. For an exposed
`jev_system_one` host tool, pass `state=context`, `questions`, and optional `purpose`.

## CLI

Replace `<skill-dir>` with the resolved skill directory. This request performs one
Choice; use `questions` instead of `question`/`acceptable_answers`/`kind` for a batch.

```sh
<skill-dir>/.venv/bin/python <skill-dir>/scripts/jev_decision.py <<'JSON'
{
  "context": {"goal": "Select a proposal", "proposals": {"a": "Reuse", "b": "Replace"}},
  "question": "Which proposal best meets the goal?",
  "acceptable_answers": {"a": "Reuse the helper", "b": "Replace it", "unknown": "Need evidence"}
}
JSON
```

Use `--build-only` for local request validation and hash inspection. CLI execution
accepts convenience-helper inputs; explicit builder/revision records are executed
through the Python API. No bridge or MCP registration is required.

## Domain completeness

For stronger guarantees, validate required evidence before calling the generic
builder. A proposal-selection adapter might require verbatim requirements, sourced
evidence, verification scope, and exact correspondence between proposal IDs and
Choice criteria. The builder validates structure and identity; the adapter enforces
the domain's completeness policy.
