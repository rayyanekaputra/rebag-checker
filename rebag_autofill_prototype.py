# =============================================================================
# REBAG AUTO-FILL (PROTOTYPE, NOT WIRED IN, UNTESTED)
# =============================================================================
# Separate experiment: reads the open Web A detail page and types it into a NEW
# SAPWeb rebag, then runs the v5 check on the result. Never posts.
# Reuses login / extraction / comparison / logging from rebag_semi_automate_v5.py.
# Selectors come from a Chrome Recorder capture of a Draft (see the comment below).
# Batch mode ('batch'): lists every rebag in the Web A list (index_rebag.php) whose Status B1
# is not Selesai/Cancel, then fills, checks, waits for the operator to post, and closes the tabs,
# one rebag at a time.
# Run: python rebag_autofill_prototype.py   (Windows, company network only)
# =============================================================================
import re
import time
import traceback

from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from colorama import Fore, Style

from rebag_semi_automate_v5 import (
    DETAIL_URL_PATTERN, DUPLICATE_LOOKBACK_DAYS, apply_duplicate_check, append_log,
    build_result, detect_grid_cols, driver_alive, extract_web_a, extract_web_b, find_window,
    is_susut_item, load_creds, load_recent_entries, print_verdict, start_session_with_retry,
)

WEB_B_NEW_REBAG_URL = "https://sapweb.indoguna.co.id/WEB_MKS/Rebag/Detail"  # blank new-rebag form


def finish_check(data_a, data_b):
    """Same as the end of v5 process_rebag: compare, duplicates, log, verdict LAST."""
    result = build_result(data_a, data_b)
    apply_duplicate_check(result)
    try:
        result["log_path"] = append_log(result)
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️  Could not write log: {type(e).__name__}: {e}{Style.RESET_ALL}")
    print_verdict(result)
    return result


# Recorded flow (Chrome Recorder, Draft page):
#   RefNo_I, Remarks_I -> btnAdd -> btnAddItem{Issue,Receipt}Detail opens the item picker
#   gvCflItemInventoryListRebag{Issue,Receipt}: filter row editor DXFREditorcol1_I (item code),
#   tick DXSelBtn<n>_D, then gvCflItemInventoryRebag{Issue,Receipt}Choose
#   -> btnUpdate -> click the qty cell, type into <grid>_DXEditor<qty>_I -> btnUpdate.
#   Posting (btnMenuOther) is left to the operator.
FILL_SIDES = {
    "baku": ("btnAddItemIssueDetail", "gvCflItemInventoryListRebagIssue",
             "gvCflItemInventoryRebagIssueChoose", "gvRebagIssueDetail"),
    "jadi": ("btnAddItemReceiptDetail", "gvCflItemInventoryListRebagReceipt",
             "gvCflItemInventoryRebagReceiptChoose", "gvRebagReceiptDetail"),
}


def wait_dx_idle(drv, timeout=20):
    """Wait until no DevExpress loading panel is visible (callbacks finished)."""
    time.sleep(0.4)
    end = time.time() + timeout
    while time.time() < end:
        busy = drv.execute_script(
            "return Array.from(document.querySelectorAll(\"[id$='_LP'], .dxlpLoadingPanel, "
            ".dxgvLoadingPanel, .dxlpLoadingPanelWithContent\")).some(e => e.offsetParent !== null);")
        if not busy:
            time.sleep(0.3)
            return
        time.sleep(0.3)
    raise RuntimeError(f"SAPWeb still busy after {timeout}s")


def safe_click(drv, el):
    drv.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
    try:
        el.click()
    except ElementClickInterceptedException:
        # A DevExpress layout box sits over the element; click it from JS instead.
        drv.execute_script("arguments[0].click();", el)


def dx_click(drv, el_id, timeout=15):
    el = WebDriverWait(drv, timeout).until(EC.element_to_be_clickable((By.ID, el_id)))
    safe_click(drv, el)
    wait_dx_idle(drv)


def dx_type(drv, el_id, text, then=Keys.TAB, timeout=15):
    el = WebDriverWait(drv, timeout).until(EC.element_to_be_clickable((By.ID, el_id)))
    safe_click(drv, el)
    el.send_keys(Keys.CONTROL, "a")
    el.send_keys(text)
    if then:
        el.send_keys(then)
    wait_dx_idle(drv)


def data_rows(drv, grid_id):
    """[(row_index, row_element)] for the grid's data rows (id '<grid>_DXDataRow<n>')."""
    out = []
    for row in drv.find_elements(By.CSS_SELECTOR, f"#{grid_id} tr.dxgvDataRow, #{grid_id} tr[id*='_DXDataRow']"):
        m = re.search(r"_DXDataRow(-?\d+)$", row.get_attribute("id") or "")
        if m and row.is_displayed() and all(m.group(1) != n for n, _ in out):
            out.append((m.group(1), row))
    return out


def pick_items(drv, side, codes):
    """Open the item picker for one side, tick every code, then Choose."""
    add_btn, picker, choose_btn, _ = FILL_SIDES[side]
    dx_click(drv, add_btn)
    filter_id = f"{picker}_DXFREditorcol1_I"
    for kode in codes:
        dx_type(drv, filter_id, kode, then=Keys.ENTER)
        end, found = time.time() + 10, None
        while time.time() < end and found is None:
            for n, row in data_rows(drv, picker):
                try:
                    if any(td.text.strip() == kode for td in row.find_elements(By.TAG_NAME, "td")):
                        found = n
                        break
                except Exception:
                    pass  # grid re-rendered under us, try again
            if found is None:
                time.sleep(0.5)
        if found is None:
            raise RuntimeError(f"{side}: item {kode} not found in the SAPWeb item picker")
        dx_click(drv, f"{picker}_DXSelBtn{found}_D")
        print(f"   {Fore.GREEN}✓ picked {kode}{Style.RESET_ALL}")
    dx_click(drv, choose_btn)


def set_grid_qtys(drv, side, items):
    """Type each item's qty into the detail grid (rows matched by code, duplicates in order)."""
    grid = FILL_SIDES[side][3]
    cols = detect_grid_cols(drv, grid)
    todo = [(kode, qty) for kode, _nama, qty, _uom, _rem in items]
    rows = data_rows(drv, grid)
    if len(rows) != len(todo):
        raise RuntimeError(f"{side}: grid has {len(rows)} row(s), expected {len(todo)}")
    for n, _ in rows:
        cell = drv.find_element(By.CSS_SELECTOR, f"#{grid}_DXDataRow{n} > td:nth-of-type({cols['code'] + 1})")
        kode = cell.text.strip()
        match = next((t for t in todo if t[0] == kode), None)
        if match is None:
            raise RuntimeError(f"{side}: grid row {n} has unexpected item '{kode}'")
        todo.remove(match)
        safe_click(drv, drv.find_element(By.CSS_SELECTOR, f"#{grid}_DXDataRow{n} > td:nth-of-type({cols['qty'] + 1})"))
        dx_type(drv, f"{grid}_DXEditor{cols['qty']}_I", f"{match[1]:.4f}", then=None)
        safe_click(drv, drv.find_element(By.ID, "Remarks_I"))  # leave the cell so the edit is kept
        wait_dx_idle(drv)
        print(f"   {Fore.GREEN}✓ {kode} qty {match[1]:.4f}{Style.RESET_ALL}")


def fill_plan(data_a):
    """Items to type into SAPWeb. Returns (plan, blockers, notes)."""
    plan, blockers, notes = {}, list(data_a["read_errors"]), []
    if data_a["doc_number"] == "NOT FOUND":
        blockers.append("Web A doc number not found")
    if not data_a["balance"].startswith("Balanced"):
        blockers.append(f"Web A is not balanced ({data_a['balance'] or 'no status'})")
    for side in ("baku", "jadi"):
        items = [it for it in data_a[side] if not is_susut_item(it[0], it[1])]
        codes = [it[0] for it in items]
        if len(set(codes)) != len(codes):
            blockers.append(f"{side}: same item code twice; fill this one by hand")
        if not items:
            blockers.append(f"{side}: no items")
        for it in items:
            if it[4]:
                notes.append(f"{it[0]} has Keterangan '{it[4]}', type it in SAPWeb yourself")
        plan[side] = items
    return plan, blockers, notes


def show_plan(data_a, plan, notes):
    print(f"\n{Fore.CYAN}{Style.BRIGHT}Will create in SAPWeb:{Style.RESET_ALL}")
    print(f"   Ref No : {data_a['doc_number']}")
    print(f"   Remarks: {data_a['remarks']}")
    for side, title in (("baku", "Bahan Baku"), ("jadi", "Bahan Jadi")):
        print(f"   {title}:")
        for kode, nama, qty, uom, _rem in plan[side]:
            print(f"      {kode:<14} {qty:>12.4f} {uom:<4} {nama}")
    for n in notes:
        print(f"{Fore.YELLOW}⚠️  {n}{Style.RESET_ALL}")

    prev = [e for e in load_recent_entries(DUPLICATE_LOOKBACK_DAYS) if e.get("doc") == data_a["doc_number"]]
    if prev:
        print(f"{Fore.RED}{Style.BRIGHT}🚨 Doc {data_a['doc_number']} is already in the logs "
              f"({prev[-1].get('time', '?')}, {prev[-1].get('verdict', '?')}). It may already exist in SAPWeb.{Style.RESET_ALL}")


def open_new_form(drv):
    drv.get(WEB_B_NEW_REBAG_URL)
    WebDriverWait(drv, 20).until(EC.presence_of_element_located((By.ID, "RefNo_I")))
    wait_dx_idle(drv)


def fill_and_check(drv, data_a, plan):
    """Type the plan into the blank SAPWeb form in the current tab, save, then run the v5 check."""
    print(f"\n{Fore.CYAN}✍️  Filling SAPWeb...{Style.RESET_ALL}")
    try:
        dx_type(drv, "RefNo_I", data_a["doc_number"])
        dx_type(drv, "Remarks_I", data_a["remarks"])
        dx_click(drv, "btnAdd_CD")
        print(f"   {Fore.GREEN}✓ header added{Style.RESET_ALL}")
        for side in ("baku", "jadi"):
            pick_items(drv, side, [it[0] for it in plan[side]])
        dx_click(drv, "btnUpdate_CD")
        for side in ("baku", "jadi"):
            set_grid_qtys(drv, side, plan[side])
        dx_click(drv, "btnUpdate_CD")
    except Exception as e:
        print(f"{Fore.RED}❌ Fill stopped ({type(e).__name__}): {e}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   SAPWeb is left as it is. Finish or delete the draft by hand, "
              f"then check it with v5 (runner.bat).{Style.RESET_ALL}")
        return None

    print(f"{Fore.GREEN}✓ Filled. Checking the result...{Style.RESET_ALL}")
    time.sleep(1)
    data_b = extract_web_b(drv)
    return finish_check(data_a, data_b)


def fill_rebag(drv):
    web_a_window = find_window(drv, lambda url: DETAIL_URL_PATTERN in url)
    if not web_a_window:
        raise Exception("Web A detail tab not found. Open detail_rebag.php?no_doc=... in Web A first.")
    print(f"\n{Fore.CYAN}🔍 Reading Web A (Rebag Log)...{Style.RESET_ALL}")
    data_a = extract_web_a(drv)
    plan, blockers, notes = fill_plan(data_a)
    show_plan(data_a, plan, notes)
    if blockers:
        for b in blockers:
            print(f"{Fore.RED}❌ {b}{Style.RESET_ALL}")
        print(f"{Fore.RED}Not filling.{Style.RESET_ALL}")
        return None
    if input("\nType 'yes' to create this rebag in SAPWeb: ").strip().lower() != "yes":
        print("Cancelled.")
        return None

    web_b_window = find_window(drv, lambda url: "sapweb.indoguna.co.id" in url)
    if not web_b_window:
        drv.execute_script("window.open('');")
        web_b_window = drv.window_handles[-1]
    drv.switch_to.window(web_b_window)
    open_new_form(drv)
    result = fill_and_check(drv, data_a, plan)
    if result:
        print(f"{Fore.YELLOW}👉 Not posted. Review SAPWeb, then post it yourself.{Style.RESET_ALL}")
    return result


# =============================================================================
# BATCH: every unfinished rebag in the Web A list, one at a time
# =============================================================================
# index_rebag.php is a client-side DataTable (#rebagTable) behind a From/To date form
# (startDate / endDate, defaults to today). Columns: No, Tanggal, No. Dokumen, Nama Item,
# Cek (Lihat link), Status B1, Oleh, Diedit. Pages via #rebagTable_next ('disabled' on the last).
LIST_URL = "http://192.168.1.14:8080/rebag/index_rebag.php"
DONE_STATUSES = ("selesai", "cancel")


def ask_date(label, default):
    while True:
        text = input(f"{label} (YYYY-MM-DD) [{default}]: ").strip() or default
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return text
        print("Use the format YYYY-MM-DD.")


def list_pending(drv, start, end):
    """[(doc, status, nama, url)] for rows whose Status B1 is not Selesai/Cancel, all pages."""
    drv.get(LIST_URL)
    WebDriverWait(drv, 15).until(EC.presence_of_element_located((By.ID, "startDate")))
    # Date inputs depend on the Windows locale when typed, so set the values directly.
    drv.execute_script("document.getElementById('startDate').value = arguments[0];"
                       "document.getElementById('endDate').value = arguments[1];"
                       "document.getElementById('startDate').form.submit();", start, end)
    WebDriverWait(drv, 15).until(EC.presence_of_element_located((By.ID, "rebagTable_next")))

    headers = [th.text.strip().lower() for th in drv.find_elements(By.CSS_SELECTOR, "#rebagTable thead th")]
    try:
        i_doc, i_status, i_nama = headers.index("no. dokumen"), headers.index("status b1"), headers.index("nama item")
    except ValueError:
        raise RuntimeError(f"Web A list columns changed: {headers}")

    rows, seen, page = [], set(), 1
    while True:
        for tr in drv.find_elements(By.CSS_SELECTOR, "#rebagTable tbody tr"):
            tds = tr.find_elements(By.TAG_NAME, "td")
            if len(tds) <= i_status:
                continue  # "No data available" row
            doc = tds[i_doc].text.strip()
            links = tr.find_elements(By.CSS_SELECTOR, f"a[href*='{DETAIL_URL_PATTERN}']")
            if not doc or doc in seen:
                continue
            seen.add(doc)
            rows.append((doc, tds[i_status].text.strip(), tds[i_nama].text.strip(),
                         links[0].get_attribute("href") if links else ""))
        nxt = drv.find_element(By.ID, "rebagTable_next")
        if "disabled" in (nxt.get_attribute("class") or ""):
            break
        page += 1
        if page > 200:
            raise RuntimeError("Web A list: more than 200 pages, stopping")
        safe_click(drv, nxt)
        time.sleep(0.3)

    print(f"{Fore.CYAN}ℹ️  Read {len(rows)} rebag(s) on {page} page(s).{Style.RESET_ALL}")
    pending = [r for r in rows if r[1].lower() not in DONE_STATUSES]
    for doc, _st, _nm, url in pending:
        if not url:
            raise RuntimeError(f"Web A list: no Lihat link for {doc}")
    return pending


def ask_choice(prompt, choices):
    while True:
        ans = input(prompt).strip().lower()
        if ans in choices:
            return ans
        print(f"Type one of: {', '.join(c or 'ENTER' for c in choices)}")


def web_b_status(drv):
    drv.refresh()
    WebDriverWait(drv, 20).until(EC.presence_of_element_located((By.ID, "Status_I")))
    wait_dx_idle(drv)
    return drv.find_element(By.ID, "Status_I").get_attribute("value").strip()


def web_a_status(drv):
    drv.refresh()
    labels = WebDriverWait(drv, 10).until(
        EC.presence_of_all_elements_located((By.XPATH, "//label[@for='status']")))
    return labels[0].text.replace("Status:", "").strip()


def close_tabs(drv, handles, back_to):
    for h in handles:
        if h in drv.window_handles:
            drv.switch_to.window(h)
            drv.close()
    drv.switch_to.window(back_to)


def batch_one(drv, doc, url, list_window):
    """Fill, check, wait for posting, close. Returns 'done', 'skip' or 'stop'."""
    drv.switch_to.new_window("tab")
    a_window = drv.current_window_handle
    drv.get(url)
    print(f"\n{Fore.CYAN}🔍 Reading Web A {doc}...{Style.RESET_ALL}")
    data_a = extract_web_a(drv)
    plan, blockers, notes = fill_plan(data_a)
    show_plan(data_a, plan, notes)
    if blockers:
        for b in blockers:
            print(f"{Fore.RED}❌ {b}{Style.RESET_ALL}")
        ans = ask_choice("\nCan't fill this one. [ENTER] skip | 'stop': ", ("", "stop"))
        close_tabs(drv, [a_window], list_window)
        return "stop" if ans == "stop" else "skip"
    ans = ask_choice("\nType 'yes' to create it in SAPWeb | 'skip' | 'stop': ", ("yes", "skip", "stop"))
    if ans != "yes":
        close_tabs(drv, [a_window], list_window)
        return ans

    drv.switch_to.new_window("tab")
    b_window = drv.current_window_handle
    open_new_form(drv)
    result = fill_and_check(drv, data_a, plan)
    if result is None or result["verdict"] != "PASS":
        print(f"{Fore.RED}{Style.BRIGHT}👉 Not ready to post. Both tabs stay open so you can fix it by hand.{Style.RESET_ALL}")
        ans = ask_choice("[ENTER] skip to the next rebag | 'stop': ", ("", "stop"))
        drv.switch_to.window(list_window)
        return "stop" if ans == "stop" else "skip"

    print(f"{Fore.YELLOW}{Style.BRIGHT}👉 Review and POST it in SAPWeb (the newest tab).{Style.RESET_ALL}")
    while True:
        ans = ask_choice("[ENTER] when posted | 'skip' (leave tabs open) | 'stop': ", ("", "skip", "stop"))
        if ans:
            drv.switch_to.window(list_window)
            return ans
        drv.switch_to.window(b_window)
        try:
            status_b = web_b_status(drv)
        except Exception as e:
            print(f"{Fore.RED}❌ Could not read SAPWeb status ({type(e).__name__}): {e}{Style.RESET_ALL}")
            continue
        if "post" not in status_b.lower():
            print(f"{Fore.RED}❌ SAPWeb status is '{status_b}', not Posted yet.{Style.RESET_ALL}")
            continue
        print(f"{Fore.GREEN}✓ SAPWeb status: {status_b}{Style.RESET_ALL}")
        break

    drv.switch_to.window(a_window)
    try:
        status_a = web_a_status(drv)
        if status_a.lower() == "selesai":
            print(f"{Fore.GREEN}✓ Web A status: {status_a}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}⚠️  Web A status is '{status_a}', not Selesai yet. Check it later.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️  Could not read Web A status ({type(e).__name__}): {e}{Style.RESET_ALL}")
    close_tabs(drv, [b_window, a_window], list_window)
    return "done"


def run_batch(drv):
    today = time.strftime("%Y-%m-%d")
    start = ask_date("From", today)
    end = ask_date("To", start)
    list_window = find_window(drv, lambda url: "192.168.1.14:8080/rebag" in url)
    if list_window:
        drv.switch_to.window(list_window)
    else:
        drv.switch_to.new_window("tab")
        list_window = drv.current_window_handle
    print(f"\n{Fore.CYAN}🔍 Reading the Web A rebag list {start} to {end}...{Style.RESET_ALL}")
    pending = list_pending(drv, start, end)
    if not pending:
        print(f"{Fore.GREEN}✓ Nothing to rebag: every rebag is Selesai or Cancel.{Style.RESET_ALL}")
        return

    counts = {}
    for _doc, status, _nm, _url in pending:
        counts[status or "(blank)"] = counts.get(status or "(blank)", 0) + 1
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{len(pending)} rebag(s) to do: "
          + ", ".join(f"{n} {st}" for st, n in counts.items()) + Style.RESET_ALL)
    for i, (doc, status, nama, _url) in enumerate(pending, start=1):
        print(f"   {i:>3}. {doc:<18} {status or '(blank)':<12} {nama}")
    if ask_choice("\n[ENTER] start | 'cancel': ", ("", "cancel")):
        return

    done, skipped = [], []
    for i, (doc, _st, _nm, url) in enumerate(pending, start=1):
        print(f"\n{Fore.CYAN}{Style.BRIGHT}===== {i}/{len(pending)}: {doc} ====={Style.RESET_ALL}")
        if not driver_alive(drv):
            print(f"{Fore.RED}🔌 Browser connection lost. Restart the script.{Style.RESET_ALL}")
            skipped.extend(d for d, *_ in pending[i - 1:])
            break
        try:
            outcome = batch_one(drv, doc, url, list_window)
        except Exception as e:
            print(f"{Fore.RED}❌ Error on {doc} ({type(e).__name__}): {e}{Style.RESET_ALL}")
            traceback.print_exc()
            outcome = ask_choice("[ENTER] skip to the next rebag | 'stop': ", ("", "stop")) or "skip"
            if list_window in drv.window_handles:
                drv.switch_to.window(list_window)
        (done if outcome == "done" else skipped).append(doc)
        if outcome == "stop":
            skipped.extend(d for d, *_ in pending[i:])
            break

    print(f"\n{Fore.CYAN}{Style.BRIGHT}Batch finished: {len(done)} posted, {len(skipped)} not done.{Style.RESET_ALL}")
    if skipped:
        print(f"{Fore.YELLOW}⚠️  Not done: {', '.join(skipped)}{Style.RESET_ALL}")


def main():
    creds = load_creds()
    drv = start_session_with_retry(creds)
    if drv is None:
        return
    print(f"\n{Fore.CYAN}Open a Web A detail page and press ENTER, or type 'batch' for every "
          f"unfinished rebag in the Web A list. 'quit' to exit.{Style.RESET_ALL}")
    while True:
        cmd = input("\n[ENTER] Fill SAPWeb | 'batch' | 'quit' to exit: ").strip().lower()
        if cmd == "quit":
            break
        if cmd not in ("", "batch"):
            print("Invalid input. Press ENTER, or type 'batch' or 'quit'.")
            continue
        if not driver_alive(drv):
            print(f"{Fore.RED}🔌 Browser connection lost. Restart the script.{Style.RESET_ALL}")
            break
        try:
            run_batch(drv) if cmd == "batch" else fill_rebag(drv)
        except Exception as e:
            print(f"{Fore.RED}❌ Error ({type(e).__name__}): {e}{Style.RESET_ALL}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
