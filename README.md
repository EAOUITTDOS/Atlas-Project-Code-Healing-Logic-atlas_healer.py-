# Atlas cold-healing proof of concept

This standalone Python tool rebuilds the reproducibility checks shown in the
terminal transcript. It is intentionally conservative: it inspects source but
never executes it, installs packages, restarts services, or modifies the input
file.

## What it checks

- Notebook/IPython shell and magic lines such as `!pip install numpy`, which
  are not valid portable Python script statements.
- Absolute filesystem paths embedded in Python string constants.
- Python syntax errors after accounting for notebook escape lines.

## Safe healing behavior

`--heal` creates a separate `<name>_healed.py` copy and comments out notebook
shell/magic lines as provenance. It does not silently rewrite absolute paths:
a path such as `/home/user/desktop/my_data.csv` might not map to the same data
on another machine, so the report recommends using a configurable or
project-relative path and verifying the data file. Syntax errors also require
human review rather than speculative repair. The original source is preserved.

## Usage

```bash
python3 atlas_healer.py atlas_test.py
python3 atlas_healer.py atlas_test.py --heal
python3 atlas_healer.py atlas_test.py --heal --output build/atlas_test_healed.py
python3 atlas_healer.py atlas_test.py --json
python3 -m unittest discover -s tests -v
```

The scan returns exit status `0` only when the scanned result has valid Python
syntax and no findings; `1` means findings need attention; `2` means the input
could not be read or processed.

The original PDF mentioned in the request was not attached to this session.
This implementation is based on the terminal transcript supplied here and
should be checked against that PDF before being treated as a faithful
reconstruction of the full original design.
