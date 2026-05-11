from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import json
import re

# For colored output
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# Chrome options
options = webdriver.ChromeOptions()
options.add_argument("--disable-component-update")  # Disable telemetry
options.add_argument("--disable-gpu")
options.add_argument("--log-level=3")  # Only severe errors

# Initialize browser
driver = webdriver.Chrome(options=options)

# URLs
web_a_url = "http://192.168.1.14:8080/rebag/index.php"
web_b_url = "https://sapweb.indoguna.co.id/WEB_MKS/"
# Open Web A (entry point)
driver.get(web_a_url)  # http://192.168.1.14:8080/rebag/index.php
print(f"\n{Fore.CYAN}👉 Web A opened. Please LOGIN and navigate to the detail page (detail_rebag.php?no_doc=...).{Style.RESET_ALL}")
print(f"{Fore.YELLOW}⏳ Waiting for you to finish...{Style.RESET_ALL}")

# Wait for manual login/navigation
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
    # Fallback: check all tabs again and print what we see
    print(f"{Fore.RED}✗ Detail tab not found. Available tabs:{Style.RESET_ALL}")
    for h in driver.window_handles:
        driver.switch_to.window(h)
        print(f"  - {driver.current_url}")
    raise Exception("Web A detail tab not found after manual navigation")

# Open Web B in new tab
driver.execute_script("window.open('');")
web_b_window = driver.window_handles[-1]
driver.switch_to.window(web_b_window)
driver.get(web_b_url)
# Wait for SAPWeb to load (adjust if login is required)
time.sleep(3)

# Helper function
def extract_grid_data(driver, grid_id, col_indices):
    """Extract grid data from SAPWeb - works for Draft AND Posted status"""
    items = []
    try:
        # Method 1: Hidden PVInput (primary)
        pv_input = driver.find_element(By.ID, f"{grid_id}_DXBEPVInput")
        raw = pv_input.get_attribute("value")
        if not raw:
            return items
        
        # Robust pseudo-JSON to JSON conversion
        fixed = (raw.replace("{'", '{"')
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
                
                # Safe qty parsing: handle number, string, or null
                if qty_val is None:
                    qty = 0.0
                elif isinstance(qty_val, (int, float)):
                    qty = float(qty_val)
                else:
                    qty_str = str(qty_val).replace(",", "").strip()
                    qty = float(qty_str) if qty_str else 0.0
                
                if kode or qty != 0:
                    items.append((kode, nama, qty, uom))
            except Exception as e:
                print(f"  ⚠️ Row parse error ({key}): {e}")
                continue
        if items:
            return items
    except Exception as e:
        print(f"  ⚠️ PVInput method failed: {e}")
    
    # Method 2: Fallback to DOM table
    try:
        table = driver.find_element(By.ID, f"{grid_id}_DXMainTable")
        rows = table.find_elements(By.XPATH, ".//tr[contains(@class, 'dxgvDataRow') and not(contains(@style, 'display:none'))]")
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) <= max(col_indices.values()):
                continue
            try:
                kode = cells[col_indices['code']].text.strip()
                nama = cells[col_indices['name']].text.strip()
                uom = cells[col_indices['uom']].text.strip()
                qty_text = cells[col_indices['qty']].text.strip().replace(",", "")
                qty = float(qty_text) if qty_text else 0.0
                if kode or qty != 0:
                    items.append((kode, nama, qty, uom))
            except Exception:
                continue
    except Exception:
        pass
    
    return items

#Helper function 2
def is_susut_item(kode, nama):
    """Check if an item represents shrinkage/loss (susut)"""
    susut_keywords = ['susut', 'loss', 'shrink', 'waste', 'reject']
    name_lower = (nama or "").lower()
    kode_lower = (kode or "").lower()
    return any(kw in name_lower or kw in kode_lower for kw in susut_keywords)


#Helper function 3
def is_remarks_shrinkage_match(remarks_a, remarks_b, susut_items_a):
    """
    Check if Remarks mismatch is just due to susut notation.
    Returns True if Web B remarks contains susut value that matches total susut from Web A.
    """
    import re
    # Extract susut value from Web B remarks (e.g., "Susut 14.77" or "susut: 14.77")
    susut_match = re.search(r'[Ss]usut[\s:]*([\d,\.]+)', remarks_b or "")
    if not susut_match:
        return False
    try:
        susut_b = float(susut_match.group(1).replace(",", ""))
    except:
        return False
    # Calculate total susut from Web A items
    total_susut_a = sum(item[2] for item in susut_items_a if is_susut_item(item[0], item[1]))
    # Allow small floating point difference
    return abs(total_susut_a - susut_b) < 0.01

# ... [keep all imports, helpers, and setup code exactly as you have] ...

# Main loop - continuous processing with ENTER key
print(f"\n{Fore.CYAN}✅ Setup complete. Press ENTER to process a rebag, or type 'quit' to exit.{Style.RESET_ALL}")

while True:
    # === REMINDER BANNER ===
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
        
        # Find Web A tab
        web_a_window = None
        target_pattern = "detail_rebag.php?no_doc="
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if target_pattern in driver.current_url:
                web_a_window = handle
                break
        if not web_a_window:
            raise Exception("Web A detail tab not found.")

        # Find or create Web B tab
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
            if qty_out > 0:
                bahan_baku_web_a.append((kode_item, nama_item, qty_out, uom))
            if qty_in > 0:
                bahan_jadi_web_a.append((kode_item, nama_item, qty_in, uom))

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

        COLS = {'code': 4, 'name': 5, 'uom': 8, 'qty': 9}
        bahan_baku_web_b = extract_grid_data(driver, "gvRebagIssueDetail", COLS)
        bahan_jadi_web_b = extract_grid_data(driver, "gvRebagReceiptDetail", COLS)
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

        # Remarks with shrinkage handling
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
        baku_b_lookup = {item[0]: item for item in bahan_baku_web_b}  # 🔑 KEY BY CODE ONLY
        matched_baku = 0
        total_baku = len([i for i in bahan_baku_web_a if not is_susut_item(i[0], i[1])])

        for i, a_item in enumerate(bahan_baku_web_a):
            kode_a, nama_a, qty_a, uom_a = a_item
            if is_susut_item(kode_a, nama_a):
                print(f"{Fore.CYAN}Bahan Baku [{i+1}] (Susut - Expected){Style.RESET_ALL}")
                print(f"  Kode: {kode_a} | Nama: {nama_a} | Qty: {qty_a} {uom_a}")
                print(f"  Status: {Fore.YELLOW}ℹ️  Susut noted in Remarks{Style.RESET_ALL}\n")
                continue

            # Find by Code only → shows actual Web B values for comparison
            b_item = baku_b_lookup.get(kode_a, ("—", "—", 0, "—"))
            match = (kode_a == b_item[0] and nama_a == b_item[1] and abs(qty_a - b_item[2]) < 0.01 and uom_a == b_item[3])
            if match: matched_baku += 1

            status_icon = f"{Fore.GREEN}✓{Style.RESET_ALL}" if match else f"{Fore.RED}✗{Style.RESET_ALL}"
            color = Fore.GREEN if match else Fore.RED
            print(f"{color}Bahan Baku [{i+1}]{Style.RESET_ALL}")
            print_comparison("  Kode", kode_a, b_item[0], value_only=True)
            print_comparison("  Nama", nama_a, b_item[1], value_only=True)
            print_comparison("  Qty", qty_a, b_item[2], value_only=True)
            print_comparison("  UoM", uom_a, b_item[3], value_only=True)
            print(f"  Status: {status_icon}\n")

        # Bahan Jadi comparison
        print(f"{Fore.YELLOW}🎁 BAHAN JADI (Qty In) COMPARISON{Style.RESET_ALL}")
        jadi_b_lookup = {item[0]: item for item in bahan_jadi_web_b}  # 🔑 KEY BY CODE ONLY
        matched_jadi = 0
        total_jadi = len([i for i in bahan_jadi_web_a if not is_susut_item(i[0], i[1])])

        for i, a_item in enumerate(bahan_jadi_web_a):
            kode_a, nama_a, qty_a, uom_a = a_item
            if is_susut_item(kode_a, nama_a):
                print(f"{Fore.CYAN}Bahan Jadi [{i+1}] (Susut - Expected){Style.RESET_ALL}")
                print(f"  Kode: {kode_a} | Nama: {nama_a} | Qty: {qty_a} {uom_a}")
                print(f"  Status: {Fore.YELLOW}ℹ️  Susut noted in Remarks{Style.RESET_ALL}\n")
                continue

            b_item = jadi_b_lookup.get(kode_a, ("—", "—", 0, "—"))
            match = (kode_a == b_item[0] and nama_a == b_item[1] and abs(qty_a - b_item[2]) < 0.01 and uom_a == b_item[3])
            if match: matched_jadi += 1

            status_icon = f"{Fore.GREEN}✓{Style.RESET_ALL}" if match else f"{Fore.RED}✗{Style.RESET_ALL}"
            color = Fore.GREEN if match else Fore.RED
            print(f"{color}Bahan Jadi [{i+1}]{Style.RESET_ALL}")
            print_comparison("  Kode", kode_a, b_item[0], value_only=True)
            print_comparison("  Nama", nama_a, b_item[1], value_only=True)
            print_comparison("  Qty", qty_a, b_item[2], value_only=True)
            print_comparison("  UoM", uom_a, b_item[3], value_only=True)
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
# Do NOT call driver.quit() if you want browser to stay open