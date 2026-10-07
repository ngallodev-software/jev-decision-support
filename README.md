# Jev Decision Support

Consult Jev for bounded semantic decisions using validated Choice, Noul, and Score
requests. [Agent instructions](skills/jev-decision-support/SKILL.md).

## Install (for humans)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and configure
`TYPESAFE_API_KEY` through the secrets mechanism used by your agent runtime. Then:

```sh
./install.sh
```

The installer prepares an isolated SDK environment, runs offline checks, and links
the skill into the user skills directory. An existing link to this checkout is
preserved. To choose another skills directory, pass it as the first argument.
Keep this checkout: both the installed skill and its runtime live here.
The installer does not store credentials or call the live API.

## Activation

Explicitly invoke `$jev-decision-support`, or let the host select it when a task
matches its description. `agents/openai.yaml` controls display metadata and the
default invocation prompt; it is not a worker definition and does not spawn agents.
The skill advises the current agent. A worker is launched only when an orchestrator
explicitly delegates a task; the worker footer supplies guidance at that point.
`references/api-usage.md` is for agents using the installed runtime, not installation.

## Checks

```sh
skills/jev-decision-support/.venv/bin/python -B skills/jev-decision-support/scripts/test_jev_decision.py
python tests/test_install.py
```

The installer check exercises repeat installation and preservation of unrelated
content in temporary directories. Live inference and UI behavior require separate checks.

MIT license · https://github.com/ngallodev-software/jev-decision-support
