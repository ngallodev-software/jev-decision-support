# Jev Decision Support

Public repository: https://github.com/ngallodev-software/jev-decision-support · MIT license.

[Skill and API call templates](skills/jev-decision-support/SKILL.md) ·
[Candidate assessment and proof limits](docs/CANDIDATE_REVIEW.md)

`makeJevDecision(context, question, acceptable_answers)` calls the official TypeSafe
SDK and returns the full Jev API result set. Choice is the default; Noul and Score
are also supported. The helper is in `skills/jev-decision-support/scripts/jev_decision.py`.

Install `typesafe-sdk` in the Python environment and configure `TYPESAFE_API_KEY`
through your usual runtime secrets mechanism. For Codex discovery, link this
repository's `skills/jev-decision-support` directory into `~/.codex/skills/jev-decision-support`.

Run the offline checks:

```sh
python skills/jev-decision-support/scripts/test_jev_decision.py
```

Validated with Python 3.13 and `typesafe-sdk==0.6.0`, using mocked HTTP responses.
Live inference and agent activation are separate, unverified checks.
