# Deferred Work


## Deferred from: code review of story-1-1 (2026-08-11)

- **`write_jsonl` truncation on mid-write failure.** No stage today has an input iterable that can raise mid-stream, so it's unreachable — but the fix (temp-file + atomic rename) should land before any stage's input source can fail partway through. [pipeline/stages/__init__.py:58-70]
- **Unvalidated `--cycle-id` on manual CLI invocation.** `cycle_id_for()`'s auto-generated form is safe by construction (digit-first, colon-free); a manually-supplied `--cycle-id` isn't checked against `STAGE_NAMES` collision or path-safety. Add validation when a later story's automation starts passing externally-derived cycle ids. [pipeline/stages/__init__.py:63-77]
- **`placeholder.py` directory-vs-missing input handling.** `args.input.exists()` doesn't distinguish "is a directory" from "doesn't exist" — the latter gets a clean stderr+exit-1, the former would raise `IsADirectoryError` uncaught. Low priority since `placeholder.py` is explicitly marked for deletion once Story 1.2's `collect` stage replaces its demonstration purpose.
