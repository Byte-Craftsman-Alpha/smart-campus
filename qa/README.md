# qa

Result files and the builders for the testing report. Nothing here is typed by hand.

| File | What wrote it |
|---|---|
| `results/pytest_output.txt` | `python3 -m pytest tests -q` |
| `results/browser_results.json` | `python3 tests/e2e/run_browser_suite.py` |
| `results/browser_results_final.json` | a copy of the clean fourth pass, kept as the record |
| `results/fixes.json` | the defect log, one entry per finding, hand-written because a fix has no test output |
| `build_report.py` | writes `docs/testing/TESTING_REPORT.docx` from the files above |
| `build_markdown.py` | writes `docs/testing/TESTING_REPORT.md` from the same files |

Regenerate both reports after any run:

```bash
python3 qa/build_report.py && python3 qa/build_markdown.py
```
