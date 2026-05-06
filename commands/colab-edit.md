---
description: Add, edit, or delete a cell in a notebook (no execution — see /colab-run)
---

# /colab-edit

Cell CRUD via Drive API + nbformat. Optimistic-locking: aborts cleanly if Drive saw a concurrent edit.

## Action

For non-trivial source (multi-line code), write to a temp file and pass `--source-file` to avoid shell-quoting issues:

```bash
TMP=$(mktemp --suffix=.py)
cat > "$TMP" <<'EOF'
<cell source here>
EOF
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" edit "$FILE_ID" add --type code --source-file "$TMP"
rm "$TMP"
```

For short single-line code, `--source` is fine.

## Subcommands

- `add` — append or insert. Use `--after CELL_ID` to insert after a specific cell. `--type code|markdown` (default code).
- `edit` — replace source of `--cell CELL_ID`. Outputs are cleared.
- `delete` — remove `--cell CELL_ID`.

## After running

Return the affected `cell_id`. If user is in a planner→executor flow, the executor agent reads this id back to run the new cell.
