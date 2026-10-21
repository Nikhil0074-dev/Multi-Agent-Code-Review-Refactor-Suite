# Multi-Agent Code Review & Refactor Suite

Three AI reviewers (Security, Performance, Clean Code) read the same GitHub pull request,
check each other's claims, and post one evidence-checked report.

```
PR diff -> 3 agents (independent) -> evidence check -> merge duplicates
        -> peer challenge -> consensus rules -> PR summary (+ optional inline comments)
```

## Quick start (no API key, 1 minute)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest                 # 150 tests
python scripts/demo.py           # full pipeline with scripted model replies
```

## Run on a real diff

```bash
export LLM_BACKEND=hosted LLM_API_KEY=sk-...        # any OpenAI-compatible API
python -m app.review --diff-file my.patch --out-dir out
# or local model (code stays on your machine):
export LLM_BACKEND=local LLM_MODEL=llama3.1          # needs Ollama running
```

Output: `out/report.json` (machine-readable) and `out/report.md` (human-readable).
Exit code: `0` = report written, `1` = every model call failed, `2` = setup problem.

## Use it in GitHub Actions

Two workflows, on purpose:

| File | Permissions | Does |
|---|---|---|
| `code-review.yml` | read-only | Runs the review, uploads the report. Skipped for fork PRs. |
| `publish-review.yml` | `pull-requests: write` | Downloads the report, re-checks the PR head commit, posts. Never runs PR code. |

Setup:
1. Copy this project into your repo (or call it from a shared repo).
2. Add secret `LLM_API_KEY`. Optional variables: `LLM_BACKEND`, `LLM_MODEL`, `LLM_BASE_URL`, `REVIEW_MODE`, `ENABLE_INLINE_COMMENTS`.
3. Replace each `# TODO: pin` action with a reviewed commit SHA.
4. Start with summary only. Turn on `ENABLE_INLINE_COMMENTS=true` after you have seen a few reports.

Local models: GitHub-hosted runners cannot reach your laptop. Use a self-hosted runner.

## Settings

All settings are environment variables. See `.env.example` for the full list. Important ones:

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BACKEND` | `hosted` | `hosted`, `local` or `mock` |
| `REVIEW_MODE` | `debate` | `single` (one agent), `independent` (3 agents, no debate), `debate` |
| `MIN_CONFIDENCE` | `0.5` | Below this, non-severe findings are dropped |
| `MAX_CHALLENGED` | `15` | Caps debate cost |
| `MAX_DIFF_CHARS` | `60000` | Larger diffs are split into chunks |
| `ENABLE_PATCHES` | `false` | Attach validated patch suggestions (never applied) |

## What the code enforces

- Every finding is validated with Pydantic. Bad ones are dropped, not fatal.
- The quoted evidence must appear in the changed code. Wrong line numbers are fixed if the evidence is nearby. Otherwise the finding is removed.
- Findings from different agents about the same lines are merged. Repeats are not votes.
- Severity comes from the finding, not from votes. Disputed critical/high findings are marked **unresolved**, never silently deleted.
- Performance claims without proof are labelled hypotheses and shown as optional.
- "No actionable findings" is a normal result. If model calls fail, the report says so (`partial` or `failed`) and does not claim the code is clean.
- Code from the PR is sent to the model as untrusted data. Model text is sanitized (no `@mentions`) before posting.
- Stale reports (PR got a new commit) and duplicate reports (same commit) are not posted.
- If GitHub rejects inline comments, the full report is still posted as a summary.

## Project layout

```
app/
  review.py, publish.py     entry points
  orchestrator.py           runs the rounds
  agents/                   security, performance, clean code (+ general baseline)
  debate/                   deduplicator, peer_challenge, consensus
  validation/               schemas, evidence_validator, line_mapper
  github/                   client, pull_request, diff_parser, publisher
  llm/                      provider (+ mock), hosted_client, local_client
  refactor/                 patch_generator, patch_validator
  reporting/                markdown_report, json_report
  evaluation/               metrics, run_eval
prompts/                    one prompt file per agent
tests/unit, tests/integration
evaluation/cases/           3 labelled sample cases
```

## Evaluation (single agent vs 3 agents vs 3 agents + debate)

```bash
python -m app.evaluation.run_eval --cases evaluation/cases
```

Reports precision, recall, F1, false-positive rate on clean cases, localization accuracy,
duplicate rate, latency and model calls. The 3 sample cases only prove the runner works.
For a real study, add many labelled cases (JSON format is in `run_eval.py`), fix the model and settings,
and choose the statistical test before looking at results.

## Known limits (read before trusting it)

- Tests use a scripted fake model. They prove the pipeline logic, **not** the review quality of any real model.
- The GitHub client and workflows were tested against a fake API, not against github.com. Try them on a test repo first.
- No static-analysis tools (Semgrep, Ruff, Bandit) are wired in yet. Evidence checking is text-based.
- Patch testing runs your test command in a temporary copy with a clean environment. It is **not** a sandbox and has network access. Use an isolated runner.
- A patch that passes tests can still change behavior.
- Line numbers refer to the new version of the file, so findings on removed code are attached to nearby lines.
