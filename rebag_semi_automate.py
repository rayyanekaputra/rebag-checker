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
# 6. Loop continues until user types 'quit'.
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
# =============================================================================

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
import time
import json
import re
import os

# For colored output
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# Chrome options
options = webdriver.ChromeOptions()
options.add_argument("--disable-component-update")
options.add_argument("--disable-gpu")
options.add_argument("--log-level=3")

# Persistent Profile
profile_path = r"D:\coding\rebag_semi_automate\selenium_profile"
options.add_argument(f"--user-data-dir={profile_path}")

# Force Offline Native Mode
options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
service = Service(executable_path=r"D:\coding\rebag_semi_automate\chromedriver.exe") 

# Initialize browser
driver = webdriver.Chrome(service=service, options=options)

# URLs
web_a_url = "http://192.168.1.14:8080/rebag/index.php"
web_b_url = "https://sapweb.indoguna.co.id/WEB_MKS/"

# -----------------------------
# STEP 0: LOAD CREDENTIALS
# -----------------------------
creds = {"user": "", "pass": ""}
try:
    with open('creds.json', 'r') as f:
        creds = json.load(f)
        print(f"{Fore.CYAN}🔑 Credentials loaded successfully from creds.json.{Style.RESET_ALL}")
except FileNotFoundError:
    print(f"{Fore.YELLOW}⚠️  creds.json not found. Manual login will be required if sessions are expired.{Style.RESET_ALL}")
except Exception as e:
    print(f"{Fore.RED}❌ Error reading creds.json: {e}{Style.RESET_ALL}")
# -----------------------------
# STEP 0.1: AUTO-LOGIN WEB A
# -----------------------------
driver.get(web_a_url)
print(f"\n{Fore.CYAN}🌐 Accessing Web A...{Style.RESET_ALL}")
if creds.get("user"):
    try:
        # Wait up to 5s to see if the login fields exist (bypassed if cache is active)
        user_input_a = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.NAME, "username"))
        )
        user_input_a.click()
        user_input_a.clear()
        user_input_a.send_keys(creds["user"])
        
        pass_input_a = driver.find_element(By.NAME, "password")
        pass_input_a.click()
        pass_input_a.clear()
        pass_input_a.send_keys(creds["pass"])
        
        driver.find_element(By.XPATH, "//input[@type='submit' and @value='Login']").click()
        print(f"{Fore.GREEN}✓ Auto-logged into Web A.{Style.RESET_ALL}")
    except Exception:
        print(f"{Fore.YELLOW}ℹ️  Web A login bypassed (cached session active or element changed).{Style.RESET_ALL}")

# -----------------------------
# STEP 0.2: AUTO-LOGIN WEB B
# -----------------------------
driver.execute_script("window.open('');")
web_b_window = driver.window_handles[-1]
driver.switch_to.window(web_b_window)
driver.get(web_b_url)
print(f"{Fore.CYAN}🌐 Accessing Web B...{Style.RESET_ALL}")
if creds.get("user"):
    try:
        # DevExpress login forms require explicit clicks to shift cursor focus
        user_input_b = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "UserName_I"))
        )
        user_input_b.click()
        user_input_b.clear()
        user_input_b.send_keys(creds["user"])
        
        time.sleep(0.5) # Brief pause for DevExpress JS events to shift focus
        
        pass_input_b = driver.find_element(By.ID, "Pwd_I")
        pass_input_b.click()
        pass_input_b.clear()
        pass_input_b.send_keys(creds["pass"])
        
        driver.find_element(By.ID, "btnLogin").click()
        print(f"{Fore.GREEN}✓ Auto-logged into Web B.{Style.RESET_ALL}")
        time.sleep(2) # Give the dashboard a second to render after login
    except Exception:
        print(f"{Fore.YELLOW}ℹ️  Web B login bypassed (cached session active or element changed).{Style.RESET_ALL}")
# -----------------------------
# PROMPT USER FOR TARGET
# -----------------------------
driver.switch_to.window(driver.window_handles[0]) # Focus back on Web A
print(f"\n{Fore.CYAN}👉 Setup Complete. Please navigate to the desired detail page in Web A (detail_rebag.php?no_doc=...).{Style.RESET_ALL}")
print(f"{Fore.YELLOW}⏳ Waiting for you to select a document...{Style.RESET_ALL}")

# Wait for manual navigation
input("Press Enter here AFTER you're on the detail page: ")

# Now detect the correct tab by URL pattern
web_a_window = None
target_pattern = "detail_rebag.php?no_doc="

for handle in driver.window_handles:
    driver.switch_to.window(handle)
    if target_pattern in driver.current_url:
        web_a_window = handle
        print(f"{Fore.GREEN}✓ Found Web A tab: {driver.current_url}{Style.RESET_ALL}")
        break

if not web_a_window:
    print(f"{Fore.RED}✗ Detail tab not found. Available tabs:{Style.RESET_ALL}")
    for h in driver.window_handles:
        driver.switch_to.window(h)
        print(f"  - {driver.current_url}")
    raise Exception("Web A detail tab not found after manual navigation")

# Helper function 1
def extract_grid_data(driver, grid_id, col_indices):
    items = []
    
    try:
        pv_input = driver.find_element(By.ID, f"{grid_id}_DXBEPVInput")
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
                if not key.isdigit(): continue 
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
                    continue
                    
            if items: return items 
            
    except Exception as e:
        print(f"  ⚠️ PVInput parse failed: {e}")
        
    print(f"  🔍 Falling back to DOM scrape for {grid_id}...")
    try:
        table = driver.find_element(By.ID, f"{grid_id}_DXMainTable")
        rows = table.find_elements(By.XPATH, ".//tr[contains(@class, 'dxgvDataRow') and not(contains(@class, 'dxgvEmptyDataRow'))]")
        
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) <= max(col_indices.values()): continue
            
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
                continue
    except Exception as e:
        print(f"  ⚠️ DOM scrape failed: {e}")
        
    return items


#Helper function 2
def is_susut_item(kode, nama):
    susut_keywords = ['susut', 'loss', 'shrink', 'waste', 'reject']
    name_lower = (nama or "").lower()
    kode_lower = (kode or "").lower()
    return any(kw in name_lower or kw in kode_lower for kw in susut_keywords)


#Helper function 3
def is_remarks_shrinkage_match(remarks_a, remarks_b, susut_items_a):
    import re
    susut_match = re.search(r'[Ss]usut[\s:]*([\d,\.]+)', remarks_b or "")
    if not susut_match:
        return False
    try:
        susut_b = float(susut_match.group(1).replace(",", ""))
    except:
        return False
    total_susut_a = sum(item[2] for item in susut_items_a if is_susut_item(item[0], item[1]))
    return abs(total_susut_a - susut_b) < 0.01

# Main loop - continuous processing with ENTER key
print(f"\n{Fore.CYAN}✅ Setup complete. Press ENTER to process a rebag, or type 'quit' to exit.{Style.RESET_ALL}")

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

    try:
        # === RE-DETECT WINDOWS EACH ITERATION ===
        web_a_window = None
        target_pattern = "detail_rebag.php?no_doc="
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if target_pattern in driver.current_url:
                web_a_window = handle
                break
        if not web_a_window:
            raise Exception("Web A detail tab not found.")

        web_b_window = None
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if "sapweb.indoguna.co.id" in driver.current_url:
                web_b_window = handle
                break
        if not web_b_window:
            driver.execute_script("window.open('');")
            web_b_window = driver.window_handles[-1]
            driver.switch_to.window(web_b_window)
            driver.get(web_b_url)
            time.sleep(2)

        # -----------------------------
        # STEP 1: Extract from Web A
        # -----------------------------
        driver.switch_to.window(web_a_window)
        print(f"\n{Fore.CYAN}🔍 Extracting from Web A (Rebag Log)...{Style.RESET_ALL}")

        doc_label = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//label[@for='no_doc']"))
        )
        doc_text = doc_label.text.strip()
        doc_number_web_a = re.search(r"MKUR20(\d+)", doc_text)
        doc_number_web_a = doc_number_web_a.group(1) if doc_number_web_a else "NOT FOUND"

        remarks_label = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//label[@for='remarks']"))
        )
        remarks_web_a = remarks_label.text.replace("Remarks: ", "").strip()

        table = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "table"))
        )
        rows = table.find_elements(By.TAG_NAME, "tr")[1:]

        bahan_baku_web_a = []
        bahan_jadi_web_a = []

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
                bahan_baku_web_a.append((kode_item, nama_item, qty_out, uom, rem))
            if qty_in > 0:
                bahan_jadi_web_a.append((kode_item, nama_item, qty_in, uom, rem))

        # -----------------------------
        # STEP 2: Extract from Web B
        # -----------------------------
        driver.switch_to.window(web_b_window)
        print(f"\n{Fore.CYAN}🔍 Extracting from Web B (SAPWeb)...{Style.RESET_ALL}")

        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "RefNo_I")))

        try:
            status_val = driver.find_element(By.ID, "Status_I").get_attribute("value").strip()
            print(f"{Fore.YELLOW}ℹ️  Transaction Status: {status_val}{Style.RESET_ALL}")
        except:
            status_val = "Unknown"

        doc_number_web_b = driver.find_element(By.ID, "RefNo_I").get_attribute("value").strip() if driver.find_elements(By.ID, "RefNo_I") else "NOT FOUND"
        remarks_web_b = driver.find_element(By.ID, "Remarks_I").get_attribute("value").strip() if driver.find_elements(By.ID, "Remarks_I") else "NOT FOUND"

        # -----------------------------
        # DYNAMIC COLUMN DETECTION 
        # -----------------------------
        def detect_grid_cols(grid_id):
            try:
                header_table = driver.find_element(By.ID, f"{grid_id}_DXHeaderTable")
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

        # Auto-detect indices for both grids
        cols_baku = detect_grid_cols("gvRebagIssueDetail")
        cols_jadi = detect_grid_cols("gvRebagReceiptDetail")
        
        print(f"{Fore.CYAN}📐 Detected Columns -> Baku: {cols_baku} | Jadi: {cols_jadi}{Style.RESET_ALL}")

        # Extract data using dynamic indices
        bahan_baku_web_b = extract_grid_data(driver, "gvRebagIssueDetail", cols_baku)
        bahan_jadi_web_b = extract_grid_data(driver, "gvRebagReceiptDetail", cols_jadi)
        print(f"{Fore.GREEN}✓ Extracted {len(bahan_baku_web_b)} Bahan Baku | {len(bahan_jadi_web_b)} Bahan Jadi{Style.RESET_ALL}")

        # -----------------------------
        # STEP 3: Compare & Print Results
        # -----------------------------
        def print_comparison(label, a, b, value_only=False):
            a_str, b_str = str(a).strip(), str(b).strip()
            if a_str == b_str:
                status = f"{Fore.GREEN}✓ Match{Style.RESET_ALL}"
                color = ""
            else:
                status = f"{Fore.RED}✗ Mismatch{Style.RESET_ALL}"
                color = Fore.RED
            if value_only:
                print(f"{label}: {color}{b_str}{Style.RESET_ALL} {status}")
            else:
                print(f"{label} | Web A: {a_str} | Web B: {color}{b_str}{Style.RESET_ALL} {status}")

        print(f"\n{Fore.CYAN}📊 FINAL COMPARISON RESULTS{Style.RESET_ALL}")
        print("=" * 80)
        print_comparison("Document Number", doc_number_web_a, doc_number_web_b)

        # Main Document Remarks
        remarks_a_str = str(remarks_web_a).strip()
        remarks_b_str = str(remarks_web_b).strip()
        susut_items_a = [item for item in bahan_baku_web_a + bahan_jadi_web_a if is_susut_item(item[0], item[1])]
        
        if remarks_a_str == remarks_b_str:
            print(f"Remarks | Web A: {remarks_a_str} | Web B: {Fore.GREEN}{remarks_b_str}{Style.RESET_ALL} {Fore.GREEN}✓ Match{Style.RESET_ALL}")
        elif is_remarks_shrinkage_match(remarks_web_a, remarks_web_b, susut_items_a):
            print(f"Remarks | Web A: {remarks_a_str} | Web B: {Fore.GREEN}{remarks_b_str}{Style.RESET_ALL} {Fore.GREEN}✓ Correct with shrinkage{Style.RESET_ALL}")
        else:
            print(f"Remarks | Web A: {remarks_a_str} | Web B: {Fore.RED}{remarks_b_str}{Style.RESET_ALL} {Fore.RED}✗ Mismatch{Style.RESET_ALL}")

        # Bahan Baku comparison
        print(f"\n{Fore.YELLOW}📦 BAHAN BAKU (Qty Out) COMPARISON{Style.RESET_ALL}")
        baku_b_lookup = {item[0]: item for item in bahan_baku_web_b}  
        matched_baku = 0
        total_baku = len([i for i in bahan_baku_web_a if not is_susut_item(i[0], i[1])])

        for i, a_item in enumerate(bahan_baku_web_a):
            kode_a, nama_a, qty_a, uom_a, remark_a = a_item
            if is_susut_item(kode_a, nama_a):
                print(f"{Fore.CYAN}Bahan Baku [{i+1}] (Susut - Expected){Style.RESET_ALL}")
                print(f"  Kode: {kode_a} | Nama: {nama_a} | Qty: {qty_a} {uom_a}")
                print(f"  Status: {Fore.YELLOW}ℹ️  Susut noted in Remarks{Style.RESET_ALL}\n")
                continue

            b_item = baku_b_lookup.get(kode_a, ("—", "—", 0, "—", ""))
            remark_found_in_textbox = remark_a in remarks_b_str if remark_a else True
            
            match = (kode_a == b_item[0] and nama_a == b_item[1] and abs(qty_a - b_item[2]) < 0.01 and uom_a == b_item[3] and remark_found_in_textbox)
            if match: matched_baku += 1

            status_icon = f"{Fore.GREEN}✓{Style.RESET_ALL}" if match else f"{Fore.RED}✗{Style.RESET_ALL}"
            color = Fore.GREEN if match else Fore.RED
            print(f"{color}Bahan Baku [{i+1}]{Style.RESET_ALL}")
            print_comparison("  Kode", kode_a, b_item[0], value_only=True)
            print_comparison("  Nama", nama_a, b_item[1], value_only=True)
            print_comparison("  Qty", qty_a, b_item[2], value_only=True)
            print_comparison("  UoM", uom_a, b_item[3], value_only=True)
            
            if remark_a:
                rem_status = f"{Fore.GREEN}✓ Found in Web B TextBox{Style.RESET_ALL}" if remark_found_in_textbox else f"{Fore.RED}✗ Missing from Web B TextBox{Style.RESET_ALL}"
                print(f"  Item Remarks Target: '{remark_a}' -> {rem_status}")
            
            print(f"  Status: {status_icon}\n")

        # Bahan Jadi comparison
        print(f"{Fore.YELLOW}🎁 BAHAN JADI (Qty In) COMPARISON{Style.RESET_ALL}")
        jadi_b_lookup = {item[0]: item for item in bahan_jadi_web_b}  
        matched_jadi = 0
        total_jadi = len([i for i in bahan_jadi_web_a if not is_susut_item(i[0], i[1])])

        for i, a_item in enumerate(bahan_jadi_web_a):
            kode_a, nama_a, qty_a, uom_a, remark_a = a_item
            if is_susut_item(kode_a, nama_a):
                print(f"{Fore.CYAN}Bahan Jadi [{i+1}] (Susut - Expected){Style.RESET_ALL}")
                print(f"  Kode: {kode_a} | Nama: {nama_a} | Qty: {qty_a} {uom_a}")
                print(f"  Status: {Fore.YELLOW}ℹ️  Susut noted in Remarks{Style.RESET_ALL}\n")
                continue

            b_item = jadi_b_lookup.get(kode_a, ("—", "—", 0, "—", ""))
            remark_found_in_textbox = remark_a in remarks_b_str if remark_a else True
            
            match = (kode_a == b_item[0] and nama_a == b_item[1] and abs(qty_a - b_item[2]) < 0.01 and uom_a == b_item[3] and remark_found_in_textbox)
            if match: matched_jadi += 1

            status_icon = f"{Fore.GREEN}✓{Style.RESET_ALL}" if match else f"{Fore.RED}✗{Style.RESET_ALL}"
            color = Fore.GREEN if match else Fore.RED
            print(f"{color}Bahan Jadi [{i+1}]{Style.RESET_ALL}")
            print_comparison("  Kode", kode_a, b_item[0], value_only=True)
            print_comparison("  Nama", nama_a, b_item[1], value_only=True)
            print_comparison("  Qty", qty_a, b_item[2], value_only=True)
            print_comparison("  UoM", uom_a, b_item[3], value_only=True)
            
            if remark_a:
                rem_status = f"{Fore.GREEN}✓ Found in Web B TextBox{Style.RESET_ALL}" if remark_found_in_textbox else f"{Fore.RED}✗ Missing from Web B TextBox{Style.RESET_ALL}"
                print(f"  Item Remarks Target: '{remark_a}' -> {rem_status}")
                
            print(f"  Status: {status_icon}\n")

        # Summary
        print(f"\n{Fore.CYAN}📋 Summary:{Style.RESET_ALL}")
        print(f"   • Doc Number: {doc_number_web_b}")
        print(f"   • Status: {status_val}")
        print(f"   • Items matched: {matched_baku}/{total_baku} Bahan Baku")
        print(f"   • Items matched: {matched_jadi}/{total_jadi} Bahan Jadi")
        print()
        print(f"{Fore.YELLOW}➡️  Next: Open the NEXT rebag in Web A, then press ENTER to continue{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}❌ Error: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()

# Cleanup - browser stays open
print(f"\n{Fore.CYAN}✅ Automation complete. Browser will remain open. Close it manually when done.{Style.RESET_ALL}")
input("Press Enter to exit script...")