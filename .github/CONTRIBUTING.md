# Contributing

- Keep changes scoped and one-sweep where possible.
- Add or update docs whenever behavior or CLI flags change.
- Prefer executable scripts under `tools/` and runtime logic under `src/`.
- Run the pipeline help command after major edits:

```bash
python3 src/media_ark/process_captures.py --help
```
