# FlowLint

**ESLint, but for Salesforce Flows.** Point it at a folder of `.flow-meta.xml`
files and it tells you which ones will cause a production incident, with an
exit code your CI pipeline can gate on.

## Why this exists

Flow is now the primary automation tool in Salesforce, and it fails in a
small number of well-known, entirely preventable ways — usually discovered
in production, at the worst possible time:

- **A DML element with no fault path** turns a validation-rule bounce or a
  record lock into a silent failure (or a raw, unhelpful error screen for an
  end user) instead of a handled one.
- **A hardcoded record ID** works perfectly in the sandbox where it was built
  and breaks the instant the flow is deployed to any other org.
- **A record-triggered flow that updates its own triggering record with no
  entry criteria** recurses on every save until Salesforce's recursion
  governor kills it — usually the day someone bulk-updates 500 records.
- **Dead automation** — a Flow left Active after the process/Apex/button that
  used to call it was removed — keeps running, keeps consuming limits, and
  keeps confusing the next admin who has to figure out what actually governs
  a record.
- **Two Active flows on the same object and trigger writing the same field**
  race each other. Whichever one runs last wins, non-deterministically, and
  nobody notices until the data looks wrong.

None of these require a bug in Salesforce — they're architecture mistakes
that are easy to make by hand and easy to catch by machine. FlowLint catches
them before they merge.

## Install

```bash
git clone https://github.com/pakshalshah30/flowlint.git
cd flowlint
pip install -e .
```

FlowLint has **zero runtime dependencies** — it's built entirely on the
Python standard library (`xml.etree.ElementTree`, `argparse`,
`dataclasses`). `pytest` is only needed if you want to run the test suite.

## Quick start (2 minutes)

The repo ships with a `fixtures/` folder of hand-written, realistic Flow
metadata files that trigger every rule, plus one clean flow that triggers
nothing. Run FlowLint against it:

```bash
flowlint fixtures/
```

### Real output

This is the actual output of `flowlint fixtures/` against the bundled
fixtures (copy-pasted, not written by hand):

```
Lead_Rating_Standardizer.flow-meta.xml
--------------------------------------
  [FL001] ERROR   element: Update_Lead_Rating
      'Update_Lead_Rating' (Update Records) has no faultConnector. If this operation fails at runtime
      (validation rule, trigger, storage limit, lock contention...) the flow will fail silently or
      surface a raw error to the end user.
  [FL003] WARNING element: Update_Lead_Rating
      Flow triggers on Update of Lead with no entry criteria (filters), and 'Update_Lead_Rating'
      updates the triggering record itself. Every save re-invokes the flow, which updates the record
      again, which re-invokes the flow — add entry criteria that exclude the state you're setting, or
      this will recurse until Salesforce's recursion limit throws a runtime error.
  [FL005] WARNING element: Update_Lead_Rating
      'Lead_Rating_Standardizer' writes Lead.Rating on Update, and so does Opportunity_Stage_Sync. Two
      Active flows on the same object/trigger writing the same field race each other — the final value
      depends on flow execution order. All flows involved: Lead_Rating_Standardizer,
      Opportunity_Stage_Sync.

Legacy_Discount_Calc.flow-meta.xml
----------------------------------
  [FL001] ERROR   element: Apply_Legacy_Discount_Owner
      'Apply_Legacy_Discount_Owner' (Update Records) has no faultConnector. If this operation fails at
      runtime (validation rule, trigger, storage limit, lock contention...) the flow will fail
      silently or surface a raw error to the end user.
  [FL002] ERROR   element: Apply_Legacy_Discount_Owner
      'Apply_Legacy_Discount_Owner' contains a hardcoded record ID literal ('00658000003xy9ZAAQ').
      Record IDs differ between sandboxes, orgs, and production — hardcoding one will break the flow
      the moment it's deployed anywhere else. Use a Get Records / Custom Metadata / Custom Label
      lookup instead.

Old_Lead_Router.flow-meta.xml
-----------------------------
  [FL004] WARNING element: Old_Lead_Router
      'Old_Lead_Router' is Active but its API name does not appear anywhere else in the scanned folder
      — no subflow call, no Apex/LWC reference captured here, nothing. Confirm this automation is
      still wired to something (a Process Builder, a Platform Event, a button) before trusting it;
      otherwise it's dead weight that still counts as Active automation and misleads whoever maintains
      the org next.

Opportunity_Stage_Sync.flow-meta.xml
------------------------------------
  [FL005] WARNING element: Sync_Rating_From_Opportunity_History
      'Opportunity_Stage_Sync' writes Lead.Rating on Update, and so does Lead_Rating_Standardizer. Two
      Active flows on the same object/trigger writing the same field race each other — the final value
      depends on flow execution order. All flows involved: Lead_Rating_Standardizer,
      Opportunity_Stage_Sync.

7 finding(s) across 4 file(s): 3 error(s), 4 warning(s).
```

`Clean_Case_Escalation.flow-meta.xml` — also in `fixtures/` — produces no
findings, and `echo $?` after running FlowLint against it prints `0`.

```bash
$ flowlint fixtures/Clean_Case_Escalation.flow-meta.xml
No findings. FlowLint has nothing to report on the scanned Flows.
$ echo $?
0
```

## Rules

| ID | Name | Severity | What it flags |
|----|------|----------|----------------|
| FL001 | Missing fault path | error | A `recordCreates`, `recordUpdates`, `recordDeletes`, or `recordLookups` element with no `faultConnector`. |
| FL002 | Hardcoded Salesforce ID | error | A 15- or 18-character literal that looks like a Salesforce record ID (mixed case + digits) inside any flow element's values. |
| FL003 | Recursion risk | warning | A record-triggered flow (`recordTriggerType` of `Update`/`CreateAndUpdate`) with no entry criteria (`filters`) that updates its own triggering record (`$Record`). |
| FL004 | Dead automation | warning | An `Active`, non-record-triggered flow (i.e. meant to be called by name — subflow, Process Builder, Apex, a button) whose API name never appears in any other scanned file. |
| FL005 | Conflicting automation | warning | Two or more `Active` record-triggered flows on the same object that write the same field on an overlapping save event (`CreateAndUpdate` overlaps with both `Create` and `Update`). |

**Note on FL004's scope:** record-triggered flows are invoked automatically
by the platform whenever their object is saved — they are never "referenced
by name" the way a subflow or utility flow is. Flagging every unreferenced
record-triggered flow would just flag *all of them*. FL004 therefore only
looks at flows with no `<object>`/`<recordTriggerType>` on `<start>` —
flows meant to be called by name that have lost their last caller.

## CLI usage

```
flowlint <path> [--format table|json] [--rules] [--exit-zero]
```

- `<path>` — a single `.flow-meta.xml` file or a directory to scan recursively.
- `--format table` (default) — human-readable, grouped by file.
- `--format json` — machine-readable, for CI tooling or dashboards.
- `--rules` — print the rule table and exit.
- `--exit-zero` — always exit `0`, even when findings are reported (useful
  when you want visibility without breaking the build yet).

Exit code is `1` when there are findings, `0` when the scan is clean (or
`--exit-zero` is passed).

### JSON output

```bash
$ flowlint fixtures/Legacy_Discount_Calc.flow-meta.xml --format json
{
  "count": 2,
  "findings": [
    {
      "rule": "FL001",
      "severity": "error",
      "file": "fixtures/Legacy_Discount_Calc.flow-meta.xml",
      "element": "Apply_Legacy_Discount_Owner",
      "message": "'Apply_Legacy_Discount_Owner' (Update Records) has no faultConnector. If this operation fails at runtime (validation rule, trigger, storage limit, lock contention...) the flow will fail silently or surface a raw error to the end user."
    },
    {
      "rule": "FL002",
      "severity": "error",
      "file": "fixtures/Legacy_Discount_Calc.flow-meta.xml",
      "element": "Apply_Legacy_Discount_Owner",
      "message": "'Apply_Legacy_Discount_Owner' contains a hardcoded record ID literal ('00658000003xy9ZAAQ'). Record IDs differ between sandboxes, orgs, and production — hardcoding one will break the flow the moment it's deployed anywhere else. Use a Get Records / Custom Metadata / Custom Label lookup instead."
    }
  ]
}
```

(exit code `1` — the shell above shows it as an error only because `--format json`
still exits non-zero on findings, same as table format)

## Wiring into CI

```yaml
name: FlowLint
on: [pull_request]
jobs:
  flowlint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install git+https://github.com/pakshalshah30/flowlint.git
      - run: flowlint force-app/main/default/flows/ --format table
```

The job fails the build the moment any of the five rules fires. Start with
`--exit-zero` for a week to see what's already in your org before flipping
it to a hard gate.

See [`.github/workflows/ci.yml`](.github/workflows/ci.yml) in this repo for
the workflow that lints FlowLint's own test fixtures on every push.

## Development

```bash
pip install -e .
pip install -r requirements.txt   # pytest
pytest -v
```

Test file: [`tests/test_rules.py`](tests/test_rules.py) — one pair of tests
per rule (fires on its designated fixture, silent on the clean fixture),
plus two end-to-end CLI checks. All 14 tests pass.

## Fixtures

| File | Demonstrates |
|------|--------------|
| `Lead_Rating_Standardizer.flow-meta.xml` | FL003 (recursion risk), FL005 (conflict with `Opportunity_Stage_Sync`), and incidentally FL001 |
| `Opportunity_Stage_Sync.flow-meta.xml` | FL005 (conflict — also writes `Lead.Rating` on `Update`), with proper fault handling and entry criteria so FL001/FL003 stay quiet |
| `Old_Lead_Router.flow-meta.xml` | FL004 (Active, autolaunched, never called by anything else in the folder) |
| `Legacy_Discount_Calc.flow-meta.xml` | FL001 (missing fault path) + FL002 (hardcoded record ID), and calls `Clean_Case_Escalation` as a subflow |
| `Clean_Case_Escalation.flow-meta.xml` | The clean fixture — well-formed, fault-handled, has entry criteria, zero findings |

## How parsing works

Salesforce Flow metadata lives in the `http://soap.sforce.com/2006/04/metadata`
namespace. FlowLint uses the standard-library `xml.etree.ElementTree` rather
than `lxml` — Flow files are small, trusted (they come from the scanned
repo, not the network), and ElementTree's namespace handling is sufficient
for Flow's flat, well-documented element structure. This keeps FlowLint at
zero runtime dependencies. See [`src/flowlint/parser.py`](src/flowlint/parser.py).

## Roadmap / not yet implemented

Being honest about the edges:

- **No XSD/schema validation.** FlowLint assumes well-formed Flow metadata
  and reads the specific elements each rule needs; it does not validate the
  file is a deployable Flow.
- **FL002 (hardcoded ID) is a per-node text scan**, not a value-path-aware
  check — it flags any 15/18-char mixed-case-plus-digit token inside a named
  flow node's XML, which covers the common cases (`inputAssignments` values,
  formula text) but doesn't distinguish "this token is inside a comment"
  from "this token is a live value."
- **FL005 (conflicting automation) only inspects `recordUpdates`.** It does
  not yet catch two flows where one uses `recordUpdates` and another uses a
  Get-then-modify pattern, or writes made via Apex/Process Builder that
  aren't visible in Flow metadata at all.
- **No support for Process Builder or Workflow Rule metadata** — only Flow.
  Most orgs still have legacy Process Builder processes that can conflict
  with Flows in the same ways FL005 checks for; extending detection there
  is on the list.
- **No formula-language evaluation.** FL003 looks at whether `<filters>` is
  present at all, not whether the entry criteria actually exclude the
  recursive case — a flow with a `filters` block that doesn't meaningfully
  narrow anything (e.g. `Id != null`) will not be flagged.
- **No config file / per-rule suppression comments.** Today it's all rules,
  every time; there's no `.flowlintrc` or inline `// flowlint-disable` yet.
- **No `--rules FL001,FL002` selective run flag** — `--rules` currently only
  lists rules; there's no way to run a subset from the CLI yet (the
  underlying `rules.RULES` registry already supports it, it's just not
  wired to an argparse flag).
- **Severity levels are fixed** (FL001/FL002 are errors, FL003–FL005 are
  warnings) with no way to configure them per-org yet.

## Author

Pakshal Shah — [pakshalshah.com](https://pakshalshah.com)

## License

MIT — see [LICENSE](LICENSE).
