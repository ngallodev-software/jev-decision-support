# Batched tech resume evaluator

From the repository root, use the existing skill runtime:

```sh
skills/jev-decision-support/.venv/bin/python -B scripts/evaluate_tech_resume.py resume.pdf \
  --role "backend engineer" --level senior --job job-description.md \
  --output resume-review.md
```

The evaluator is a Python script. Show help with
`python3 scripts/evaluate_tech_resume.py --help` or, where executable files are
supported, `./scripts/evaluate_tech_resume.py --help`; do not run it with `bash`.

Configure `TYPESAFE_API_KEY` through your runtime's secret mechanism. The script
honors the SDK's `TYPESAFE_BASE_URL` and model configuration; check a custom
endpoint before sending a private document. `--model` selects a model explicitly.
If the runtime is absent, run the repository's existing `./install.sh` first.

Each evaluation makes **one System One request** with all questions in a single
batch. There is no question-by-question loop of API calls or automatic semantic
retry. The SDK may perform transport retries. The evaluator reuses the existing
helper's request identity, payload bounds, and response validation.

Omit `--role` or `--level` to add an independent Choice estimate for that field
to the same batch. Estimates describe the resume's documented role family and
responsibility level; they do not infer your desired job. Reports label them as
estimates and retain full distributions, confidence and an `insufficient_evidence`
option. Explicit user targets are preserved and their estimates are skipped.
JSON keeps supplied targets in `target` (omitted fields are `null`) and estimates
in `target_estimates`. Estimates do not feed assessment questions in the batch;
each question assesses shared evidence independently. Preview shows the estimate
questions, but produces no estimates until the batch is executed.

The report covers:

- Ten dimensions: positioning, technical depth, impact, ownership, delivery and
  reliability, collaboration, scope/progression, projects, clarity, and skills
  backed by evidence. Each has a 0–4 Score and independent Noul context-sufficiency
  estimate.
- A Choice for the most useful first revision and a dimension editing checklist.
- A Score and bounded editing recommendation for each selected resume bullet,
  identified by its extracted line number and quoted text.
- With `--job`: three additional alignment dimensions and a Choice evidence check
  for each selected nonempty job-description line. Employer/benefit content has a
  `not_requirement` option; missing evidence is distinct from missing capability.
- Complete answer distributions, confidence, model, usage, scope, rubric and
  request/decision hashes. JSON includes the exact questions and raw API result.

Markdown is the default; use `--format json` for machine-readable output. Without
`--output`, the report goes to stdout. Named output files must be new; the script
refuses to overwrite them and writes only after the evaluation succeeds.

## Preview before sending

```sh
python -B scripts/evaluate_tech_resume.py resume.md --job job-description.md \
  --dry-run --output request-preview.json
```

Preview requires neither SDK credentials nor a network connection. It contains
the complete projected evidence and request metadata, so treat it as private.
Contact emails, conventional phone numbers, and HTTP/www links are removed before
dispatch. This is best-effort contact filtering, **not anonymization**: names,
employers, locations, and other identifying text can remain. Remove anything you
do not want sent before running. Resume links are never fetched.

## Inputs and bounds

UTF-8 `.txt`, `.md`, `.markdown`, `.docx`, and text-based `.pdf` are supported.
DOCX extraction uses Python's standard library and restores list markers. PDF
extraction uses the installed `pdftotext` command with a 30-second timeout; scanned
PDFs require OCR or manual text export first. Extraction preserves paragraph/text
content but cannot verify page design, tables' reading order, or ATS compatibility.
Inspect extracted evidence in the preview if the source has columns or tables.

By default, the first 20 explicit resume bullets and first 30 nonempty job lines
receive individual questions. `--max-bullets` accepts 0–40; `--max-job-lines`
accepts 0–60. The **full extracted text** remains available to every question;
reports state how many lines did not receive individual review. Wrapped bullet
continuations remain in shared context. Bullets without explicit markers get
overall assessment but no individual bullet question.

The helper enforces a 64 KiB complete-request ceiling and 48 KiB question ceiling.
Oversized requests fail locally without silent text truncation. Lower individual
review limits or supply a deliberately shortened document. `--timeout` sets the
SDK client timeout in seconds (default 90), not an overall wall-clock deadline.

Scores concern the resume's presentation, not the person's abilities. They are
ordinal rubric levels, not percentages; the script computes no aggregate hiring
score. Confidence measures distribution concentration, not correctness. Noul near
0.5 signals unresolved context sufficiency. No probability cutoff is calibrated
or applied. Suggestions are bounded editing templates, not fabricated rewrites.
The model is instructed to ignore embedded document instructions and protected
characteristics; these instructions do not guarantee model behavior.

## Offline checks

```sh
python -B tests/test_resume_evaluator.py
```

Checks exercise the actual builder/executor with a recording fake client: a
single multi-question dispatch, complete distributions, contact filtering,
line-review limits without evidence truncation, request tamper rejection, DOCX
extraction, the PDF command path, preview without dispatch, and file preservation.
They do not claim live model quality or extraction fidelity for every document.
