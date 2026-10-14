# AGENTS.md — rebag-checker

Guide for AI coding agents (Claude Code, Gemini, Codex, etc.) working on this repo.

## What this is

A semi-automated Selenium script that checks **Rebag** (item swap / repack) transactions
by comparing two internal web systems that should hold the same data:

| | System | Tech | URL |
|---|---|---|---|
| **Web A** | Rebag Log (the source of truth) | Plain PHP + HTML table | `http://192.168.1.14:8080/rebag/index.php` → `detail_rebag.php?no_doc=MKUR20...` |
| **Web B** | SAPWeb | ASP.NET + DevExpress controls | `https://sapweb.indoguna.co.id/WEB_MKS/` |

The operator opens a rebag detail page in Web A and the matching document in Web B, presses
ENTER, and the script pulls data from both, compares it, prints a PASS/FAIL verdict **last**
(no scrolling), and appends the result to a daily log.

Domain terms (Indonesian):
- **Bahan Baku** = raw material, i.e. items going **out** (Web A `qty_out`, Web B `gvRebagIssueDetail`)
- **Bahan Jadi** = finished goods, i.e. items coming **in** (Web A `qty_in`, Web B `gvRebagReceiptDetail`)
- **Susut** = shrinkage/loss. Susut items are skipped in item matching; their total qty is
  checked against a `Susut <n>` amount in the Web B remarks.
- **Kode / Nama / Qty / UoM** = item code / name / quantity / unit of measure.
- **Draft** vs **Posted** = Web B document status. Draft grids have an extra `#` column, which
  shifts the column indices by one.

## Files

- `rebag_semi_automate_v5.py` — **the current version. All changes go here** unless told otherwise.
- `rebag_autofill_prototype.py` — **separate auto-fill tool** (works in production, first
  confirmed 2026-10-14). Reads the open Web A detail page, creates the matching rebag in SAPWeb,
  then runs the v5 check on it. Keep it a separate file: don't merge it into v5 or wire it into
  `runner.bat` unless the user asks. It imports login/extraction/compare/log functions from v5,
  so renaming or changing the signature of those v5 functions breaks it.
- `rebag_semi_automate_v1..v4.py`, `old_and_working.py` — historical versions, kept for reference.
  Don't edit them, and don't "fix" them to match v5.
- `runner.bat` — Windows launcher (activates `.venv`, runs v5). Update the filename here if a new version is created.
- `installer_package_python.bat` — creates `.venv` and installs `requirements.txt`.
- `chromedriver.exe` — bundled driver (offline use; must match the installed Chrome's major version).
- `logs/rebag_YYYY-MM-DD.txt` — daily check logs (also the data for duplicate detection).
- `creds.json` — **gitignored**, `{"user": "...", "pass": "..."}`, the same login for both systems.
- `selenium_profile/` — gitignored persistent Chrome profile (keeps sessions/cookies).

## Runtime environment

- Runs on **Windows**, paths hardcoded in the CONFIG block (`D:\coding\rebag_semi_automate\...`,
  `C:\Program Files\Google\Chrome\...`). The repo may be edited on Linux, where the script
  **cannot run**: both sites are on the company network and the paths are Windows-only.
  Don't try to run it end-to-end. A syntax check is fine:
  `python -m py_compile rebag_semi_automate_v5.py`.
- Python + `selenium==4.43.0`, `colorama`. Pinned in `requirements.txt`.
- Windows sleep prevention uses `ctypes.windll` (guarded with `os.name == "nt"`).

## How v5 is organized

Top to bottom, in sections marked with `# ===` banners:

1. **CONFIG** — paths, URLs, `DUPLICATE_LOOKBACK_DAYS`, `PREVENT_SLEEP`.
2. **Sleep prevention** — `SetThreadExecutionState`.
3. **Browser / login** — `start_driver`, `login_web_a`, `login_web_b`, `start_session_with_retry`,
   `driver_alive` (health check before each run; restarts Chrome after PC sleep), `find_window`
   (picks tabs by URL, not by handle order).
4. **Web B grid extraction** — `extract_grid_data` reads the DevExpress `<grid>_DXBEPVInput`
   hidden field (Python-ish pseudo-JSON, cleaned up with string replacements), then falls back to
   scraping `<grid>_DXMainTable` rows. `detect_grid_cols` chooses column indices from the header
   (`#` first column means Draft).
5. **Susut helpers** — keyword detection and checking the remarks amount.
6. **Extraction** — `extract_web_a` and `extract_web_b` each return
   `{doc_number, remarks, baku, jadi[, status]}`; items are tuples `(kode, nama, qty, uom, remark)`.
7. **Comparison** — `compare_section` (one function for Baku and Jadi; duplicate codes matched
   one-to-one via `build_lookup`/`pick_b_item`; leftover Web B items become warnings).
   `build_result` produces the single `result` dict that everything downstream uses.
8. **Log + duplicate detection** — each log entry starts with a machine-readable
   `#ENTRY | time=... | doc=... | fp=... | verdict=... | status=... | recheck=... | dup=...` line.
   `fp` is a content hash of Web A data. Same doc again → "Re-check #n". Different doc, same fp →
   "POSSIBLE DOUBLE REBAG".
9. **Verdict block** — `print_verdict`, always the last thing printed.
10. **`process_rebag` / `main`** — the ENTER loop.

## Selectors (the fragile part)

Everything depends on these. Whenever one changes, update the code **and this table**.

**Web A**
- Login: `name=username`, `name=password`, `//input[@type='submit' and @value='Login']`
- Doc no: `//label[@for='no_doc']`, regex `MKUR20(\d+)` → the digits are the doc number
- Remarks: `//label[@for='remarks']` (with the `"Remarks: "` prefix stripped)
- Items: first `.table`, `./tbody/tr` only (the `<tfoot>` has Total / Status Balance rows);
  td `0`=kode `1`=nama `2`=qty_in `3`=qty_out `4`=uom `5`=remark/Keterangan (optional).
  For admins, td `6`=Avg HPP and `7`=New Price are also shown (ignored by the script).
- Qty format: plain decimals, no thousands separator, empty side is `0.0000` (e.g. `1084.8800`).
  `parse_qty` accepts only that format (blank counts as 0); anything else is a FAIL problem.
  Prices use the Indonesian format (`Rp 123.115,37`), so never reuse qty parsing on them.
- Status Balance: `./tfoot//span[contains(@class,'badge')]`, e.g. `Balanced (0)`. Anything not
  starting with "Balanced" becomes a warning (not a FAIL).

**Web B (DevExpress, ids end in `_I` for the input)**
- Login: `UserName_I`, `Pwd_I`, `btnLogin` (needs clicks + a short sleep to move focus)
- Header: `RefNo_I` (doc no), `Remarks_I`, `Status_I`
- Grids: `gvRebagIssueDetail` (Baku), `gvRebagReceiptDetail` (Jadi); suffixes `_DXBEPVInput`,
  `_DXMainTable`, `_DXHeaderTable`; data rows `tr.dxgvDataRow`
- Column indices (`code/name/uom/qty/remarks`):
  - Issue: Posted `4/5/8/9/11`, Draft `5/6/9/10/11`
  - Receipt: Posted `4/5/8/9/10`, Draft `5/6/9/10/10`
  - JSON payload indices and visual column indices are **not** always the same (see v1.8 in the
    changelog). The remarks fallback in `extract_grid_data` exists for this reason.

**Web B auto-fill** (used by `rebag_autofill_prototype.py`, taken from a Chrome Recorder capture)
- New blank form: `WEB_MKS/Rebag/Detail` (opened directly, no menu clicks)
- Header: type `RefNo_I` (Web A doc digits, without `MKUR20`) and `Remarks_I` (Web A remarks
  as-is), then `btnAdd_CD`
- Item picker: `btnAddItemIssueDetail` / `btnAddItemReceiptDetail` open
  `gvCflItemInventoryListRebagIssue` / `...Receipt`. Filter row `<picker>_DXFREditorcol1_I`
  (item code, then Enter), tick `<picker>_DXSelBtn<n>_D` on the row whose cell equals the code
  exactly, then `gvCflItemInventoryRebagIssueChoose` / `...ReceiptChoose`. All items of one side
  are ticked in one picker visit.
- Save: `btnUpdate_CD`. Qty: click `<grid>_DXDataRow<n> > td` at the Draft qty column, type into
  `<grid>_DXEditor<qty>_I`, click `Remarks_I` to leave the cell, then `btnUpdate_CD` again.
- Posting is `btnMenuOther` → Set → Post. **The script never posts**; the operator does.
- Layout boxes can cover buttons (`ElementClickInterceptedException`), so every click goes
  through `safe_click` (scroll into view, then fall back to a JS click).
- Busy wait: `wait_dx_idle` polls until no DevExpress loading panel (`[id$='_LP']`,
  `.dxlpLoadingPanel`, `.dxgvLoadingPanel`) is visible.
- Flow: ENTER → read Web A → show the plan → operator types `yes` → fill → v5 check + log +
  verdict. It refuses to fill if Web A isn't Balanced, a qty is unreadable, a side is empty, or
  a code appears twice on one side. Susut items are not added (they go in the remarks). Item
  Keterangan is not typed; it shows a warning instead. It warns loudly if the doc is already in
  the logs. Keep the `yes` confirmation unless the user asks to remove it.

## How selectors are discovered (current workflow)

The author has no access to the sites' source. Selectors come from **pasting the rendered
HTML/ASP markup of each page** (after load: Draft and Posted, Web A and Web B) into a chat
and reading it. Things to know when you get pasted HTML:
- Read ids, classes, and column order from the markup. Don't guess. If something you need isn't
  in what was pasted, ask for that part (for example the grid header row, or the `DXBEPVInput` value).
- Draft and Posted pages are different. Get both before changing column logic.
- Pasted HTML may contain real business data and session tokens. Don't commit it to the repo
  unless the user asks, and if they do, strip tokens/ViewState first.
- **Chrome DevTools Recorder** (F12 → ⋮ → More tools → Recorder → Export JSON) is the best way
  to capture a click path. It records ids/aria/xpath selectors for every step, including
  popups. The auto-fill was built from one. It records **everything typed, including
  passwords**: log in before you start recording. Recordings stay out of git
  (`SAPWEB for CLAUDE.json` is in `.gitignore`; add new recording names there too). When reading one,
  never repeat typed credentials back.
- Recordings show clicks, not page structure. For grids and fields, ask for the HTML as well.
- The plan is to automate HTML capture later (for example, dumping `page_source` to a file on
  each run). Keep that in mind, but don't build it unless asked.

## Conventions

- **Versioning:** the file header holds an OVERVIEW, WORKFLOW, and CHANGELOG. Any behavior
  change adds a `[vX.Y]` changelog line (the latest is v2.5 inside the v5 file). A big rewrite
  becomes a new `rebag_semi_automate_vN.py` (and `runner.bat` gets updated). Small fixes stay
  in v5.
- **Ask before building.** When the user describes a big new direction ("fully automate"),
  propose a plan and wait. Don't implement it in the same turn, and put experiments in a
  separate file instead of v5.
- **Style:** plain functions, no classes, no new dependencies without asking. Short
  `drv` for the driver. Console output uses colorama + emoji with a consistent meaning:
  ✓/✗ match/mismatch, ⚠️ warning, ℹ️ info, 🔍 extracting, ❌ error.
- **Output:** the verdict block must stay the **last** thing printed per check.
- **Log format is an interface.** `parse_entry_line` reads old logs for duplicate detection.
  Only add new `key=value` fields to the `#ENTRY` line. Don't rename or remove existing ones, and
  don't change the `fp` computation (that would break duplicate detection against past logs).
- **Failures must be loud.** A comparison that can't read data must produce a problem/FAIL,
  never a silent PASS. Catch exceptions where the code can continue, and print the exception type.
- **Secrets:** never print, log, or commit `creds.json` contents.
- **User-facing text** is English (domain words like Bahan Baku/Susut stay Indonesian).
