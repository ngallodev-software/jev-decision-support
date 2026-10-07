#!/usr/bin/env bash
set -euo pipefail

# Usage: ./install.sh [skills-directory]
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
skill_dir="$repo_dir/skills/jev-decision-support"
skills_dir="${1:-$HOME/.agents/skills}"
legacy_dir="${CODEX_HOME:-$HOME/.codex}/skills"

# Preserve an existing installation of this checkout.
if [[ $# == 0 && "$legacy_dir/jev-decision-support" -ef "$skill_dir" ]]; then
    skills_dir="$legacy_dir"
fi
target="$skills_dir/jev-decision-support"
if [[ -e "$target" || -L "$target" ]]; then
    [[ "$target" -ef "$skill_dir" ]] || {
        printf 'Refusing to replace an existing skill: %s\n' "$target" >&2
        exit 1
    }
fi
command -v uv >/dev/null || { printf 'Install uv before running this script.\n' >&2; exit 1; }

if [[ ! -x "$skill_dir/.venv/bin/python" ]]; then
    uv venv --quiet "$skill_dir/.venv"
fi
uv pip install --quiet --python "$skill_dir/.venv/bin/python" typesafe-sdk
"$skill_dir/.venv/bin/python" -B "$skill_dir/scripts/test_jev_decision.py"

mkdir -p -- "$skills_dir"
if [[ ! -e "$target" && ! -L "$target" ]]; then
    ln -s -- "$skill_dir" "$target"
fi
printf 'Installed %s\nConfigure TYPESAFE_API_KEY in the agent runtime before use.\n' "$target"
