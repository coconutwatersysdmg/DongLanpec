# Impingement Plate Restore Parameters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore every impingement-plate type from authoritative tube-layout parameters instead of depending on incomplete calculation input JSON.

**Architecture:** Add one `TubeLayoutEditor` resolver that reads numeric values from the loaded parameter table first and legacy input keys second. Use its result for flat/arc calls and as the fallback for incomplete welded-plate records.

**Tech Stack:** Python 3.12, PyQt5, unittest/pytest

**Spec:** `docs/superpowers/specs/2026-11-02-impingement-plate-restore-params-design.md`

## Global Constraints

- Do not change database schemas or stored coordinate formats.
- Preserve legacy `input_json` compatibility.
- Do not modify unrelated dirty worktree files.

## Review Focus

- A zero azimuth from the parameter table remains a valid value.
- Missing parameter-table values fall back to both modern and legacy input keys.
- A malformed legacy value falls back safely instead of resetting unrelated parameters.
- Welded record-specific values remain higher priority than global parameter values.
- Tube pitch reads `换热管中心距 S`, with `LB_S` and `S` compatibility fallbacks.

---

### Task 1: Centralize and apply restore parameter resolution

**Files:**
- Modify: `modules/buguan/buguan_ziyong/My_Piping.py`
- Create: `tests/test_impingement_plate_restore_params.py`

**Interfaces:**
- Consumes: `TubeLayoutEditor._read_param_table_float(param_name)` and `self.input_json`.
- Produces: `TubeLayoutEditor._get_impingement_plate_restore_params() -> dict[str, float | None]`.

- [ ] **Step 1: Write the failing tests**

Test that the parameter table overrides missing/stale input JSON for all shared flat/arc/welded parameters, and that old input keys remain valid fallbacks.

- [ ] **Step 2: Verify RED**

Run: `D:\ProgramData\anaconda3\python.exe -m pytest tests/test_impingement_plate_restore_params.py -q`

Expected: FAIL because `_get_impingement_plate_restore_params` does not exist.

- [ ] **Step 3: Implement the minimal resolver and use it during restoration**

Add safe numeric parsing, parameter-table-first precedence, and welded-record fallback for missing width/azimuth/distance.

- [ ] **Step 4: Verify GREEN and regression suite**

Run the focused test, then `D:\ProgramData\anaconda3\python.exe -m pytest -q`.

Expected: all tests pass.

- [ ] **Step 5: Review the diff without committing**

Leave the changes in the user's existing dirty worktree for direct debugging.
