# Open Indiana Law — Muse research workbench

**Using Meta to Conduct Legal Research**

Open-source hackathon workbench, released under the MIT license.

Connect Meta’s Muse Spark to a searchable Indiana-law library. Ask a plain-language question, read the research note, inspect retrieved statutes/opinions beside it, and expand the search/tool trace.

## What the hackathon adds

The Muse companion supplies the tool loop, observable research state, source reader and links, quotation checks, incomplete-result handling, and a fail-closed reservation ledger. Muse selects research tools and writes the synthesis. The existing [Indiana-law engine and corpus](https://github.com/open-indiana-law/indiana-code) predate this build and provide retrieval through the read-only MCP service.

The filmed example establishes one emergency possession route; it does not establish complete ordinary-eviction coverage. Quotation matching is not verification of current law or a citator.

## Local setup

Requires Python3.12+.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/indiana-research-serve
```

Open http://127.0.0.1:8767. No keys or paid credit are included. Live Muse calls remain closed until the user supplies their own Meta key and separately satisfies the local spending/no-overage gates. Do not bypass these gates to try the demo. Read `.env.example` for names, not a credential.

The tests use synthetic/mocked responses and recorded public-source fixtures; running the test suite does not authorize paid inference. Fixture/preflight CLI commands may contact the hosted law MCP and are distinct from the fully mocked tests. Source inspection of an existing answer does not make another model request.

## Scope and dependencies

This release contains the companion’s source, web UI and portable tests. It excludes private production history, owner voice/reference recordings, keys, local ledgers, provider receipts and private owner-specific admission/rehearsal harnesses. The public legal fixture is minimized to the synthetic question, visible model responses/tool calls and public source results needed to reproduce a prior failure. Operator approvals, provider IDs, token accounting and ledger metadata are excluded. Meta’s hosted API/model is not part of this source-code license; third-party dependencies and the separate library retain their own terms. No model weights are distributed.

The companion source is MIT-licensed. Opening a project’s code does not make its deployed service, model or every linked source open source. A public repository and verified judge access are separate release checks.
