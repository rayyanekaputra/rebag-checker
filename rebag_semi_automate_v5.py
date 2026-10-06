# =============================================================================
# REBAG VALIDATION AUTOMATION - SUMMARY & CHANGELOG
# =============================================================================
# OVERVIEW:
# Semi-automated Selenium script to validate "Rebag" (swap item) transactions
# between two internal web systems: Web A (PHP Rebag Log) and Web B (SAPWeb/DevExpress).
# Handles both Draft (filling) and Posted states, auto-detects column shifts,
# and validates data with susut (shrinkage) handling.
#
# WORKFLOW:
# 1. Opens Web A & Web B in separate tabs.
# 2. Auto-logs into both systems using local creds.json.
# 3. User navigates to the target detail page in Web A.
# 4. Press ENTER to trigger extraction.
# 5. Script auto-detects correct tabs, extracts data, compares fields, and prints results.
# 6. A verdict block (PASS/FAIL) is printed LAST, so you never need to scroll up.
# 7. Every check is appended to logs/rebag_YYYY-MM-DD.txt (one file per day).
# 8. Loop continues until user types 'quit'.
#
# CHANGELOG:
# [v1.0] Initial setup: Basic tab switching, hardcoded column indices (4,5,8,9)
# [v1.1] Fixed Web A tab detection: Replaced current_window_handle with URL pattern matching
# [v1.2] Added manual navigation flow: Input prompt waits for user to login & open detail page
# [v1.3] Added Draft/Posted state support: Implemented JSON fallback to DOM table scraping
# [v1.4] Fixed JSON parsing: Added robust string replacement for DevExpress pseudo-JSON
# [v1.5] Fixed column index mismatch: Implemented dynamic header scanning to detect # column shift
# [v1.6] Added susut handling: Detects shrinkage items, skips them in comparison, validates amount in Remarks
# [v1.7] UX improvements: Reminder banners, ENTER-to-continue loop, colored status output, error handling
# [v1.8] Fixed Item Remarks extraction mismatch: Decoupled visual column shifting from JSON payload indices
# [v1.9] Auto-Login added: Reads creds.json to automatically authenticate Web A and Web B on startup
# [v2.0] Refactor: everything is now in functions; one compare_section() replaces the two
#        copy-pasted Baku/Jadi blocks; every check produces a single `result` dict.
#        Duplicate item codes are now matched one-to-one (no more silent overwrite).
#        Items that exist in Web B but not in Web A are shown as warnings.
#        The extra "press ENTER after you're on the detail page" prompt before the loop
#        was removed (the loop prompt already does that, and it no longer crashes the script).
# [v2.1] Verdict block printed at the very bottom: PASS/FAIL, doc number, remarks, counts,
#        and only the problems.
# [v2.2] Daily log: logs/rebag_YYYY-MM-DD.txt, each check is appended as one entry.
# [v2.3] Driver health check before every check; if Chrome/driver died (e.g. PC went to sleep)
#        the browser is restarted and logged in again. Optional Windows sleep prevention.
#        The exception type is printed so we can learn what actually fails.
# [v2.4] Duplicate detection from the logs: "Re-check #n" for the same doc number, and a loud
#        "POSSIBLE DOUBLE REBAG" warning when a DIFFERENT doc number has identical content.
# =============================================================================

import atexit
import ctypes
import glob
import hashlib
import json
import os
import re
import time
import traceback
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

# For colored output
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# =============================================================================
# CONFIG  (edit these)
# =============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_PATH = r"D:\coding\rebag_semi_automate\selenium_profile"
CHROME_BINARY = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROMEDRIVER_PATH = r"D:\coding\rebag_semi_automate\chromedriver.exe"

WEB_A_URL = "http://192.168.1.14:8080/rebag/index.php"
WEB_B_URL = "https://sapweb.indoguna.co.id/WEB_MKS/"

CREDS_FILE = os.path.join(SCRIPT_DIR, "creds.json")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")

DETAIL_URL_PATTERN = "detail_rebag.php?no_doc="

# How many days back the duplicate check reads the logs.
DUPLICATE_LOOKBACK_DAYS = 30

# True = Windows will not go to sleep by itself while this script is open.
# (Does not stop lid-close / manual sleep / hibernate; the auto-restart covers those.)
PREVENT_SLEEP = True


# =============================================================================
# SLEEP PREVENTION (Windows only)
# =============================================================================
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def set_sleep_prevention(enable):
    if os.name != "nt":
        return
    try:
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if enable else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️  Could not change sleep setting: {e}{Style.RESET_ALL}")


# =============================================================================
# BROWSER / LOGIN
# =============================================================================
def load_creds():
    creds = {"user": "", "pass": ""}
    try:
        with open(CREDS_FILE, "r") as f:
            creds = json.load(f)
            print(f"{Fore.CYAN}🔑 Credentials loaded successfully from creds.json.{Style.RESET_ALL}")
    except FileNotFoundError:
        print(f"{Fore.YELLOW}⚠️  creds.json not found. Manual login will be required if sessions are expired.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}❌ Error reading creds.json: {e}{Style.RESET_ALL}")
    return creds


def start_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-component-update")
    options.add_argument("--disable-gpu")
    options.add_argument("--log-level=3")
    options.add_argument(f"--user-data-dir={PROFILE_PATH}")  # persistent profile
    options.binary_location = CHROME_BINARY                   # force offline native mode
    service = Service(executable_path=CHROMEDRIVER_PATH)
    return webdriver.Chrome(service=service, options=options)


def login_web_a(drv, creds):
    drv.get(WEB_A_URL)
    print(f"\n{Fore.CYAN}🌐 Accessing Web A...{Style.RESET_ALL}")
    if creds.get("user"):
        try:
            # Wait up to 5s to see if the login fields exist (bypassed if cache is active)
            user_input = WebDriverWait(drv, 5).until(
                EC.element_to_be_clickable((By.NAME, "username"))
            )
            user_input.click()
            user_input.clear()
            user_input.send_keys(creds["user"])

            pass_input = drv.find_element(By.NAME, "password")
            pass_input.click()
            pass_input.clear()
            pass_input.send_keys(creds["pass"])

            drv.find_element(By.XPATH, "//input[@type='submit' and @value='Login']").click()
            print(f"{Fore.GREEN}✓ Auto-logged into Web A.{Style.RESET_ALL}")
        except Exception:
            print(f"{Fore.YELLOW}ℹ️  Web A login bypassed (cached session active or element changed).{Style.RESET_ALL}")


def login_web_b(drv, creds):
    drv.execute_script("window.open('');")
    drv.switch_to.window(drv.window_handles[-1])
    drv.get(WEB_B_URL)
    print(f"{Fore.CYAN}🌐 Accessing Web B...{Style.RESET_ALL}")
    if creds.get("user"):
        try:
            # DevExpress login forms require explicit clicks to shift cursor focus
            user_input = WebDriverWait(drv, 5).until(
                EC.element_to_be_clickable((By.ID, "UserName_I"))
            )
            user_input.click()
            user_input.clear()
            user_input.send_keys(creds["user"])

            time.sleep(0.5)  # Brief pause for DevExpress JS events to shift focus

            pass_input = drv.find_element(By.ID, "Pwd_I")
            pass_input.click()
            pass_input.clear()
            pass_input.send_keys(creds["pass"])

            drv.find_element(By.ID, "btnLogin").click()
            print(f"{Fore.GREEN}✓ Auto-logged into Web B.{Style.RESET_ALL}")
            time.sleep(2)  # Give the dashboard a second to render after login
        except Exception:
            print(f"{Fore.YELLOW}ℹ️  Web B login bypassed (cached session active or element changed).{Style.RESET_ALL}")


def safe_quit(drv):
    try:
        drv.quit()
    except Exception:
        pass


def start_session(creds):
    """Start Chrome, log into Web A and Web B, focus Web A."""
    drv = start_driver()
    try:
        login_web_a(drv, creds)
        login_web_b(drv, creds)
        drv.switch_to.window(drv.window_handles[0])
    except Exception:
        safe_quit(drv)
        raise
    return drv


def start_session_with_retry(creds):
    """Like start_session, but lets the user retry (e.g. leftover Chrome locking the profile)."""
    while True:
        try:
            return start_session(creds)
        except Exception as e:
            first_line = (str(e).strip().splitlines() or [""])[0]
            print(f"{Fore.RED}❌ Could not start the browser: {type(e).__name__}: {first_line}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}   Close any leftover Chrome windows that use the automation profile, then retry.{Style.RESET_ALL}")
            answer = input("   Press ENTER to retry, or type 'quit' to exit: ").strip().lower()
            if answer == "quit":
                return None


def driver_alive(drv):
    """Cheap health check. Raises inside Selenium if the session/driver is dead."""
    try:
        return len(drv.window_handles) > 0
    except Exception:
        return False


def find_window(drv, predicate):
    for handle in drv.window_handles:
        try:
            drv.switch_to.window(handle)
            if predicate(drv.current_url):
                return handle
        except Exception:
            continue
    return None


# =============================================================================
# HELPERS: GRID EXTRACTION (Web B)
# =============================================================================
def extract_grid_data(drv, grid_id, col_indices):
    items = []
    skipped = 0

    try:
        pv_input = drv.find_element(By.ID, f"{grid_id}_DXBEPVInput")
        raw = pv_input.get_attribute("value")

        if raw:
            clean_raw = raw.strip()
            if clean_raw.startswith('(') and clean_raw.endswith(')'):
                clean_raw = clean_raw[1:-1]

            fixed = (clean_raw.replace("{'", '{"')
                              .replace("'}", '"}')
                              .replace("',", '",')
                              .replace(",'", ',"')
                              .replace(": None", ': null')
                              .replace(", None", ', null')
                              .replace(":None", ': null')
                              .replace(",None", ', null'))

            data = json.loads(fixed)

            for key, row in data.items():
                if not key.isdigit():
                    continue
                try:
                    kode = str(row.get(str(col_indices['code']), "") or "").strip()
                    nama = str(row.get(str(col_indices['name']), "") or "").strip()
                    uom = str(row.get(str(col_indices['uom']), "") or "").strip()
                    qty_val = row.get(str(col_indices['qty']), 0)

                    rem_val = row.get(str(col_indices['remarks']), "")
                    if isinstance(rem_val, (int, float)) or (isinstance(rem_val, str) and rem_val.replace(".", "").replace(",", "").replace("-", "").isdigit()):
                        candidates = [str(v).strip() for k, v in row.items() if k.isdigit() and v and not isinstance(v, (int, float))]
                        candidates = [c for c in candidates if c not in [kode, nama, uom] and not c.replace(".", "").replace(",", "").replace("-", "").isdigit()]
                        rem = candidates[0] if candidates else ""
                    else:
                        rem = str(rem_val or "").strip()

                    if qty_val is None:
                        qty = 0.0
                    elif isinstance(qty_val, (int, float)):
                        qty = float(qty_val)
                    else:
                        qty = float(str(qty_val).replace(",", ""))

                    if kode or qty != 0:
                        items.append((kode, nama, qty, uom, rem))
                except Exception:
                    skipped += 1
                    continue

            if skipped:
                print(f"  {Fore.YELLOW}⚠️ {skipped} row(s) in {grid_id} could not be read (JSON){Style.RESET_ALL}")
            if items:
                return items

    except Exception as e:
        print(f"  ⚠️ PVInput parse failed: {e}")

    print(f"  🔍 Falling back to DOM scrape for {grid_id}...")
    skipped = 0
    try:
        table = drv.find_element(By.ID, f"{grid_id}_DXMainTable")
        rows = table.find_elements(By.XPATH, ".//tr[contains(@class, 'dxgvDataRow') and not(contains(@class, 'dxgvEmptyDataRow'))]")

        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) <= max(col_indices.values()):
                skipped += 1
                continue

            try:
                kode = cells[col_indices['code']].text.strip()
                nama = cells[col_indices['name']].text.strip()
                uom = cells[col_indices['uom']].text.strip()
                rem = cells[col_indices['remarks']].text.strip()

                qty_text = cells[col_indices['qty']].text.strip().replace(",", "")
                qty = float(qty_text) if qty_text.replace(".", "").replace("-", "").isdigit() else 0.0

                if kode or qty != 0:
                    items.append((kode, nama, qty, uom, rem))
            except Exception:
                skipped += 1
                continue
        if skipped:
            print(f"  {Fore.YELLOW}⚠️ {skipped} row(s) in {grid_id} could not be read (DOM){Style.RESET_ALL}")
    except Exception as e:
        print(f"  ⚠️ DOM scrape failed: {e}")

    return items


def detect_grid_cols(drv, grid_id):
    try:
        header_table = drv.find_element(By.ID, f"{grid_id}_DXHeaderTable")
        header_cells = header_table.find_elements(By.XPATH, ".//td[contains(@class, 'dxgvHeader')]")
        if not header_cells:
            return {'code': 4, 'name': 5, 'uom': 8, 'qty': 9, 'remarks': 11}

        first_cell_text = header_cells[0].text.strip()

        if "Issue" in grid_id:
            if '#' in first_cell_text:
                # Draft Mode (+1 shift due to '#' column)
                return {'code': 5, 'name': 6, 'uom': 9, 'qty': 10, 'remarks': 11}
            else:
                # Posted Mode
                return {'code': 4, 'name': 5, 'uom': 8, 'qty': 9, 'remarks': 11}
        else:
            if '#' in first_cell_text:
                # Draft Mode (+1 shift due to '#' column)
                return {'code': 5, 'name': 6, 'uom': 9, 'qty': 10, 'remarks': 10}
            else:
                # Posted Mode
                return {'code': 4, 'name': 5, 'uom': 8, 'qty': 9, 'remarks': 10}

    except Exception as e:
        print(f"  ⚠️ Error detecting columns for {grid_id}: {e}")
        return {'code': 4, 'name': 5, 'uom': 8, 'qty': 9, 'remarks': 10}


# =============================================================================
# HELPERS: SUSUT
# =============================================================================
def is_susut_item(kode, nama):
    susut_keywords = ['susut', 'loss', 'shrink', 'waste', 'reject']
    name_lower = (nama or "").lower()
    kode_lower = (kode or "").lower()
    return any(kw in name_lower or kw in kode_lower for kw in susut_keywords)


def is_remarks_shrinkage_match(remarks_a, remarks_b, susut_items_a):
    susut_match = re.search(r'[Ss]usut[\s:]*([\d,\.]+)', remarks_b or "")
    if not susut_match:
        return False
    try:
        susut_b = float(susut_match.group(1).replace(",", ""))
    except Exception:
        return False
    total_susut_a = sum(item[2] for item in susut_items_a if is_susut_item(item[0], item[1]))
    return abs(total_susut_a - susut_b) < 0.01


# =============================================================================
# EXTRACTION: WEB A / WEB B
# =============================================================================
def extract_web_a(drv):
    doc_label = WebDriverWait(drv, 10).until(
        EC.presence_of_element_located((By.XPATH, "//label[@for='no_doc']"))
    )
    doc_text = doc_label.text.strip()
    m = re.search(r"MKUR20(\d+)", doc_text)
    doc_number = m.group(1) if m else "NOT FOUND"

    remarks_label = WebDriverWait(drv, 10).until(
        EC.presence_of_element_located((By.XPATH, "//label[@for='remarks']"))
    )
    remarks = remarks_label.text.replace("Remarks: ", "").strip()

    table = WebDriverWait(drv, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "table"))
    )
    rows = table.find_elements(By.TAG_NAME, "tr")[1:]

    baku, jadi = [], []
    for row in rows:
        cols = row.find_elements(By.TAG_NAME, "td")
        if len(cols) < 5:
            continue
        kode_item = cols[0].text.strip()
        nama_item = cols[1].text.strip()
        try:
            qty_in = float(cols[2].text.strip())
            qty_out = float(cols[3].text.strip())
        except ValueError:
            qty_in = qty_out = 0.0
        uom = cols[4].text.strip()

        rem = ""
        if len(cols) >= 6:
            rem = cols[5].text.strip()

        if qty_out > 0:
            baku.append((kode_item, nama_item, qty_out, uom, rem))
        if qty_in > 0:
            jadi.append((kode_item, nama_item, qty_in, uom, rem))

    return {"doc_number": doc_number, "remarks": remarks, "baku": baku, "jadi": jadi}


def extract_web_b(drv):
    WebDriverWait(drv, 10).until(EC.presence_of_element_located((By.ID, "RefNo_I")))

    try:
        status_val = drv.find_element(By.ID, "Status_I").get_attribute("value").strip()
        print(f"{Fore.YELLOW}ℹ️  Transaction Status: {status_val}{Style.RESET_ALL}")
    except Exception:
        status_val = "Unknown"

    doc_number = drv.find_element(By.ID, "RefNo_I").get_attribute("value").strip() if drv.find_elements(By.ID, "RefNo_I") else "NOT FOUND"
    remarks = drv.find_element(By.ID, "Remarks_I").get_attribute("value").strip() if drv.find_elements(By.ID, "Remarks_I") else "NOT FOUND"

    cols_baku = detect_grid_cols(drv, "gvRebagIssueDetail")
    cols_jadi = detect_grid_cols(drv, "gvRebagReceiptDetail")
    print(f"{Fore.CYAN}📐 Detected Columns -> Baku: {cols_baku} | Jadi: {cols_jadi}{Style.RESET_ALL}")

    baku = extract_grid_data(drv, "gvRebagIssueDetail", cols_baku)
    jadi = extract_grid_data(drv, "gvRebagReceiptDetail", cols_jadi)
    print(f"{Fore.GREEN}✓ Extracted {len(baku)} Bahan Baku | {len(jadi)} Bahan Jadi{Style.RESET_ALL}")

    return {"status": status_val, "doc_number": doc_number, "remarks": remarks, "baku": baku, "jadi": jadi}


# =============================================================================
# COMPARISON
# =============================================================================
def print_comparison(label, a, b, value_only=False):
    a_str, b_str = str(a).strip(), str(b).strip()
    same = a_str == b_str
    if not same and isinstance(a, (int, float)) and isinstance(b, (int, float)):
        same = abs(a - b) < 0.01
    if same:
        status = f"{Fore.GREEN}✓ Match{Style.RESET_ALL}"
        color = ""
    else:
        status = f"{Fore.RED}✗ Mismatch{Style.RESET_ALL}"
        color = Fore.RED
    if value_only:
        print(f"{label}: {color}{b_str}{Style.RESET_ALL} {status}")
    else:
        print(f"{label} | Web A: {a_str} | Web B: {color}{b_str}{Style.RESET_ALL} {status}")


def print_remarks_line(result):
    ra, rb, state = result["remarks_a"], result["remarks_b"], result["remarks_state"]
    if state == "match":
        print(f"Remarks | Web A: {ra} | Web B: {Fore.GREEN}{rb}{Style.RESET_ALL} {Fore.GREEN}✓ Match{Style.RESET_ALL}")
    elif state == "shrinkage":
        print(f"Remarks | Web A: {ra} | Web B: {Fore.GREEN}{rb}{Style.RESET_ALL} {Fore.GREEN}✓ Correct with shrinkage{Style.RESET_ALL}")
    else:
        print(f"Remarks | Web A: {ra} | Web B: {Fore.RED}{rb}{Style.RESET_ALL} {Fore.RED}✗ Mismatch{Style.RESET_ALL}")


def build_lookup(items_b):
    """code -> list of Web B items (a list, so duplicate codes are not overwritten)."""
    lookup = {}
    for item in items_b:
        lookup.setdefault(item[0], []).append(item)
    return lookup


def pick_b_item(lookup, kode_a, qty_a):
    """Take (and consume) the best Web B candidate for this Web A item."""
    candidates = lookup.get(kode_a, [])
    if not candidates:
        return None
    for i, cand in enumerate(candidates):
        if abs(cand[2] - qty_a) < 0.01:
            return candidates.pop(i)
    return candidates.pop(0)


def compare_section(label, title, items_a, items_b, remarks_b_str):
    """Compare one side (Baku or Jadi). Prints details and returns a summary dict."""
    print(f"{Fore.YELLOW}{title}{Style.RESET_ALL}")
    lookup = build_lookup(items_b)
    total = len([i for i in items_a if not is_susut_item(i[0], i[1])])
    matched = 0
    susut_count = 0
    problems, warnings, log_lines = [], [], []

    for i, a_item in enumerate(items_a):
        kode_a, nama_a, qty_a, uom_a, remark_a = a_item
        n = i + 1

        if is_susut_item(kode_a, nama_a):
            susut_count += 1
            print(f"{Fore.CYAN}{label} [{n}] (Susut - Expected){Style.RESET_ALL}")
            print(f"  Kode: {kode_a} | Nama: {nama_a} | Qty: {qty_a} {uom_a}")
            print(f"  Status: {Fore.YELLOW}ℹ️  Susut noted in Remarks{Style.RESET_ALL}\n")
            log_lines.append(f"  - [{n}] {kode_a} | {nama_a} | {qty_a} {uom_a} | SUSUT (skipped)")
            continue

        b_item = pick_b_item(lookup, kode_a, qty_a)
        found = b_item is not None
        if not found:
            b_item = ("—", "—", 0, "—", "")

        remark_found = (remark_a in remarks_b_str) if remark_a else True

        diffs = []
        if not found:
            diffs.append("Not found in Web B")
        else:
            if nama_a != b_item[1]:
                diffs.append(f"Nama: A='{nama_a}' B='{b_item[1]}'")
            if abs(qty_a - b_item[2]) >= 0.01:
                diffs.append(f"Qty: A={qty_a} B={b_item[2]}")
            if uom_a != b_item[3]:
                diffs.append(f"UoM: A='{uom_a}' B='{b_item[3]}'")
            if not remark_found:
                diffs.append(f"Item remark missing in Web B remarks: '{remark_a}'")

        match = not diffs
        if match:
            matched += 1
        else:
            problems.append(f"{label} [{n}] {kode_a}: " + "; ".join(diffs))

        status_icon = f"{Fore.GREEN}✓{Style.RESET_ALL}" if match else f"{Fore.RED}✗{Style.RESET_ALL}"
        color = Fore.GREEN if match else Fore.RED
        print(f"{color}{label} [{n}]{Style.RESET_ALL}")
        print_comparison("  Kode", kode_a, b_item[0], value_only=True)
        print_comparison("  Nama", nama_a, b_item[1], value_only=True)
        print_comparison("  Qty", qty_a, b_item[2], value_only=True)
        print_comparison("  UoM", uom_a, b_item[3], value_only=True)

        if remark_a:
            rem_status = (f"{Fore.GREEN}✓ Found in Web B TextBox{Style.RESET_ALL}" if remark_found
                          else f"{Fore.RED}✗ Missing from Web B TextBox{Style.RESET_ALL}")
            print(f"  Item Remarks Target: '{remark_a}' -> {rem_status}")

        print(f"  Status: {status_icon}\n")
        log_lines.append(f"  - [{n}] {kode_a} | {nama_a} | {qty_a} {uom_a} | "
                         + ("OK" if match else "MISMATCH: " + "; ".join(diffs)))

    # Anything left in Web B that no Web A item claimed
    for code, leftovers in lookup.items():
        for it in leftovers:
            if is_susut_item(it[0], it[1]):
                continue
            msg = f"{label}: extra in Web B, not in Web A -> {it[0]} | {it[1]} | {it[2]} {it[3]}"
            warnings.append(msg)
            print(f"{Fore.YELLOW}⚠️  {msg}{Style.RESET_ALL}")

    return {"label": label, "total": total, "matched": matched, "susut": susut_count,
            "problems": problems, "warnings": warnings, "log_lines": log_lines}


def compute_fingerprint(baku_a, jadi_a, remarks_a):
    """Content hash of a rebag, based on Web A (the source): items out/in + remarks."""
    def norm(tag, items):
        return sorted((tag, k.strip().upper(), round(q, 2), u.strip().upper()) for k, _n, q, u, _r in items)

    payload = json.dumps([
        norm("OUT", baku_a),
        norm("IN", jadi_a),
        re.sub(r"\s+", " ", remarks_a or "").strip().lower(),
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def build_result(a, b):
    """Run the comparison, print the detail, return one result dict."""
    print(f"\n{Fore.CYAN}📊 FINAL COMPARISON RESULTS{Style.RESET_ALL}")
    print("=" * 80)

    problems = []
    doc_a, doc_b = a["doc_number"], b["doc_number"]
    print_comparison("Document Number", doc_a, doc_b)
    if doc_a == "NOT FOUND":
        problems.append("Document number not found on Web A")
    elif doc_a.strip() != doc_b.strip():
        problems.append(f"Document number differs: A={doc_a} B={doc_b}")

    remarks_a_str = str(a["remarks"]).strip()
    remarks_b_str = str(b["remarks"]).strip()
    susut_items_a = [item for item in a["baku"] + a["jadi"] if is_susut_item(item[0], item[1])]
    if remarks_a_str == remarks_b_str:
        remarks_state = "match"
    elif is_remarks_shrinkage_match(a["remarks"], b["remarks"], susut_items_a):
        remarks_state = "shrinkage"
    else:
        remarks_state = "mismatch"
        problems.append("Remarks differ between Web A and Web B")

    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "doc_a": doc_a, "doc_b": doc_b, "status": b["status"],
        "remarks_a": remarks_a_str, "remarks_b": remarks_b_str, "remarks_state": remarks_state,
    }
    print_remarks_line(result)

    baku = compare_section("Bahan Baku", "\n📦 BAHAN BAKU (Qty Out) COMPARISON", a["baku"], b["baku"], remarks_b_str)
    jadi = compare_section("Bahan Jadi", "🎁 BAHAN JADI (Qty In) COMPARISON", a["jadi"], b["jadi"], remarks_b_str)

    if not a["baku"] and not a["jadi"]:
        problems.append("No items could be extracted from Web A")
    problems += baku["problems"] + jadi["problems"]

    result.update({
        "baku": baku, "jadi": jadi,
        "problems": problems,
        "warnings": baku["warnings"] + jadi["warnings"],
        "verdict": "PASS" if not problems else "FAIL",
        "fp": compute_fingerprint(a["baku"], a["jadi"], remarks_a_str),
        "has_items": bool(a["baku"] or a["jadi"]),
        "recheck_no": 1, "prev_same_doc": [], "dup_of": [], "today_no": None, "log_path": None,
    })
    return result


# =============================================================================
# DAILY LOG + DUPLICATE DETECTION
# =============================================================================
def _clean(value):
    """Keep header values safe for the ' | ' / '=' line format."""
    return str(value).replace("|", "/").replace("\n", " ").replace("\r", " ").strip()


def parse_entry_line(line):
    parts = line.strip().split(" | ")[1:]
    entry = {}
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            entry[k.strip()] = v.strip()
    return entry if "doc" in entry and "fp" in entry else None


def load_recent_entries(days):
    """Read '#ENTRY' header lines from the last `days` days of log files."""
    entries = []
    cutoff = datetime.now().date() - timedelta(days=max(days, 1))
    for path in sorted(glob.glob(os.path.join(LOG_DIR, "rebag_*.txt"))):
        m = re.search(r"rebag_(\d{4}-\d{2}-\d{2})\.txt$", path)
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#ENTRY |"):
                        entry = parse_entry_line(line)
                        if entry:
                            entries.append(entry)
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️  Could not read log {os.path.basename(path)}: {e}{Style.RESET_ALL}")
    return entries


def apply_duplicate_check(result):
    """Fill recheck / double-rebag info on the result by reading past logs."""
    try:
        entries = load_recent_entries(DUPLICATE_LOOKBACK_DAYS)
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️  Duplicate check skipped: {e}{Style.RESET_ALL}")
        return
    doc = result["doc_a"]
    today = datetime.now().strftime("%Y-%m-%d")
    result["today_no"] = len([e for e in entries if e.get("time", "").startswith(today)]) + 1

    if doc != "NOT FOUND":
        result["prev_same_doc"] = [e for e in entries if e.get("doc") == doc]
        result["recheck_no"] = len(result["prev_same_doc"]) + 1
        if result["has_items"]:
            seen, dups = set(), []
            for e in entries:
                if e.get("fp") == result["fp"] and e.get("doc") != doc and e.get("doc") not in seen:
                    seen.add(e.get("doc"))
                    dups.append(e)
            result["dup_of"] = dups


def build_log_text(result):
    dup_docs = ",".join(e.get("doc", "?") for e in result["dup_of"]) or "-"
    header = " | ".join([
        "#ENTRY",
        f"time={result['timestamp']}",
        f"doc={_clean(result['doc_a'])}",
        f"fp={result['fp']}",
        f"verdict={result['verdict']}",
        f"status={_clean(result['status'])}",
        f"recheck={result['recheck_no']}",
        f"dup={dup_docs}",
    ])
    lines = [
        header,
        "=" * 80,
        f"[{result['timestamp'][11:]}] Rebag {result['doc_a']} | Web B RefNo: {result['doc_b']} | "
        f"Status: {result['status']} | Verdict: {result['verdict']}",
        f"Remarks (A): {result['remarks_a']}",
        f"Remarks (B): {result['remarks_b']}",
        f"Remarks check: {result['remarks_state']}",
        f"Bahan Baku ({result['baku']['matched']}/{result['baku']['total']} matched):",
    ]
    lines += result["baku"]["log_lines"] or ["  (none)"]
    lines.append(f"Bahan Jadi ({result['jadi']['matched']}/{result['jadi']['total']} matched):")
    lines += result["jadi"]["log_lines"] or ["  (none)"]

    lines.append("Problems: " + ("none" if not result["problems"] else ""))
    lines += [f"  ! {p}" for p in result["problems"]]
    if result["warnings"]:
        lines.append("Warnings:")
        lines += [f"  ~ {w}" for w in result["warnings"]]
    if result["recheck_no"] > 1:
        prev = result["prev_same_doc"][-1]
        lines.append(f"Re-check #{result['recheck_no']} (previous: {prev.get('time', '?')} -> {prev.get('verdict', '?')})")
    for e in result["dup_of"]:
        lines.append(f"POSSIBLE DOUBLE REBAG: same content as doc {e.get('doc')} ({e.get('time', '?')}, {e.get('verdict', '?')})")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def append_log(result):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"rebag_{datetime.now().strftime('%Y-%m-%d')}.txt")
    with open(path, "a", encoding="utf-8") as f:
        f.write(build_log_text(result))
    return path


# =============================================================================
# VERDICT BLOCK (always printed last)
# =============================================================================
def print_verdict(result):
    ok = result["verdict"] == "PASS"
    color = Fore.GREEN if ok else Fore.RED
    bar = "═" * 80

    print(f"\n{color}{bar}{Style.RESET_ALL}")
    print(f"{color}{Style.BRIGHT}{'✅ PASS' if ok else '❌ FAIL'}  —  Rebag {result['doc_a']}  ({result['status']}){Style.RESET_ALL}")
    print(f"{color}{bar}{Style.RESET_ALL}")

    print_comparison("Document Number", result["doc_a"], result["doc_b"])
    print_remarks_line(result)

    baku, jadi = result["baku"], result["jadi"]
    print(f"Bahan Baku: {baku['matched']}/{baku['total']} matched"
          + (f" (+{baku['susut']} susut)" if baku["susut"] else "")
          + f"  |  Bahan Jadi: {jadi['matched']}/{jadi['total']} matched"
          + (f" (+{jadi['susut']} susut)" if jadi["susut"] else ""))

    if result["problems"]:
        print(f"{Fore.RED}Problems:{Style.RESET_ALL}")
        for p in result["problems"]:
            print(f"  {Fore.RED}✗ {p}{Style.RESET_ALL}")
    if result["warnings"]:
        print(f"{Fore.YELLOW}Warnings:{Style.RESET_ALL}")
        for w in result["warnings"]:
            print(f"  {Fore.YELLOW}⚠️  {w}{Style.RESET_ALL}")

    if result["recheck_no"] > 1:
        prev = result["prev_same_doc"][-1]
        print(f"{Fore.CYAN}ℹ️  Re-check #{result['recheck_no']} of this document "
              f"(previous: {prev.get('time', '?')} -> {prev.get('verdict', '?')}){Style.RESET_ALL}")
    for e in result["dup_of"]:
        print(f"{Fore.RED}{Style.BRIGHT}🚨 POSSIBLE DOUBLE REBAG: same items/qty/remarks as doc {e.get('doc')} "
              f"({e.get('time', '?')}, {e.get('verdict', '?')}){Style.RESET_ALL}")

    if result["log_path"]:
        print(f"{Fore.CYAN}📝 Logged as #{result['today_no']} today -> {os.path.relpath(result['log_path'], SCRIPT_DIR)}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}📝 Not logged (see warning above){Style.RESET_ALL}")
    print(f"{color}{bar}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}➡️  Next: Open the NEXT rebag in Web A, then press ENTER to continue{Style.RESET_ALL}")


# =============================================================================
# ONE FULL CHECK
# =============================================================================
def process_rebag(drv):
    # === RE-DETECT WINDOWS EACH ITERATION ===
    web_a_window = find_window(drv, lambda url: DETAIL_URL_PATTERN in url)
    if not web_a_window:
        raise Exception("Web A detail tab not found. Open detail_rebag.php?no_doc=... in Web A first.")

    web_b_window = find_window(drv, lambda url: "sapweb.indoguna.co.id" in url)
    if not web_b_window:
        drv.execute_script("window.open('');")
        web_b_window = drv.window_handles[-1]
        drv.switch_to.window(web_b_window)
        drv.get(WEB_B_URL)
        time.sleep(2)

    # STEP 1: Web A
    drv.switch_to.window(web_a_window)
    print(f"\n{Fore.CYAN}🔍 Extracting from Web A (Rebag Log)...{Style.RESET_ALL}")
    data_a = extract_web_a(drv)

    # STEP 2: Web B
    drv.switch_to.window(web_b_window)
    print(f"\n{Fore.CYAN}🔍 Extracting from Web B (SAPWeb)...{Style.RESET_ALL}")
    data_b = extract_web_b(drv)

    # STEP 3: Compare, check duplicates, log, then show the verdict LAST
    result = build_result(data_a, data_b)
    apply_duplicate_check(result)
    try:
        result["log_path"] = append_log(result)
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️  Could not write log: {type(e).__name__}: {e}{Style.RESET_ALL}")
    print_verdict(result)
    return result


# =============================================================================
# MAIN LOOP
# =============================================================================
def main():
    if PREVENT_SLEEP:
        set_sleep_prevention(True)
        atexit.register(set_sleep_prevention, False)
        print(f"{Fore.CYAN}💤 Sleep prevention ON (PC won't auto-sleep while this script is open).{Style.RESET_ALL}")

    creds = load_creds()
    drv = start_session_with_retry(creds)
    if drv is None:
        return

    print(f"\n{Fore.CYAN}✅ Setup complete. Open a rebag detail page in Web A (detail_rebag.php?no_doc=...), "
          f"then press ENTER. Type 'quit' to exit.{Style.RESET_ALL}")

    while True:
        print(f"\n{Fore.CYAN}{'═' * 80}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}⚠️  REMINDER: Don't forget to open the NEW rebag form in Web A before checking!{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'═' * 80}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}✅ Quick checklist:{Style.RESET_ALL}")
        print(f"   1. Web A: Navigate to detail_rebag.php?no_doc=MKUR...")
        print(f"   2. Web B: Ensure SAPWeb shows the matching RefNo")
        print(f"   3. Press ENTER when both are ready")
        print()

        user_input = input("\n[ENTER] Process rebag | 'quit' to exit: ").lower().strip()
        if user_input == "quit":
            break
        if user_input not in ["", "start"]:
            print("Invalid input. Press ENTER or type 'quit'.")
            continue

        # --- Health check: did Chrome/driver die while we were idle (sleep, crash)? ---
        if not driver_alive(drv):
            print(f"{Fore.RED}🔌 Lost connection to the browser (PC sleep? Chrome closed?). Restarting...{Style.RESET_ALL}")
            safe_quit(drv)
            drv = start_session_with_retry(creds)
            if drv is None:
                break
            print(f"{Fore.YELLOW}🔄 Browser restarted and logged in again. "
                  f"Open the rebag detail page in Web A, then press ENTER.{Style.RESET_ALL}")
            continue

        try:
            process_rebag(drv)
        except Exception as e:
            print(f"{Fore.RED}❌ Error ({type(e).__name__}): {e}{Style.RESET_ALL}")
            traceback.print_exc()
            if not driver_alive(drv):
                print(f"{Fore.YELLOW}🔌 The browser connection is gone. It will be restarted on the next ENTER.{Style.RESET_ALL}")
            elif type(e).__name__ == "TimeoutException":
                print(f"{Fore.YELLOW}ℹ️  Timed out waiting for the page. Is the right page open, and is "
                      f"Web B still logged in?{Style.RESET_ALL}")

    # Cleanup - browser stays open
    print(f"\n{Fore.CYAN}✅ Automation complete. Browser will remain open. Close it manually when done.{Style.RESET_ALL}")
    input("Press Enter to exit script...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.CYAN}Stopped by user (Ctrl+C).{Style.RESET_ALL}")