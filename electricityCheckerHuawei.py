from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, TimeoutException
import chromedriver_autoinstaller
from bs4 import BeautifulSoup
import json
import time as time_module
from datetime import datetime, timedelta, time
from suntime import Sun
import pytz
from threading import Thread
import tkinter as tk
from tkinter import scrolledtext
import os
import subprocess

sofia_lat = 42.69
sofia_lon = 23.32
sofia_tz = pytz.timezone("Europe/Sofia")
utc_tz = pytz.utc
sun = Sun(sofia_lat, sofia_lon)
today_utc = datetime.now(utc_tz)
sunrise_utc = sun.get_sunrise_time(today_utc)
sunset_utc = sun.get_sunset_time(today_utc)
sunrise_local = sunrise_utc.astimezone(sofia_tz)
sunset_local = sunset_utc.astimezone(sofia_tz)

# Convert sunrise and sunset times to Sofia timezone
sunrise_hour = sunrise_local.strftime("%H")
sunrise_minute = sunrise_local.strftime("%M")
sunset_hour = sunset_local.strftime("%H")
sunset_minute = sunset_local.strftime("%M")

# Find the path to the credentials.json file
script_dir = os.path.dirname(os.path.abspath(__file__))
credentials_path = os.path.join(script_dir, 'credentials.json')


# --- Logging to file (streaming) ---
LOG_FILE_PATH = os.path.join(script_dir, "solar_price_checker_logs.txt")

# Open once, append mode, line-buffered (flushes on each newline)
log_file = open(LOG_FILE_PATH, "a", encoding="utf-8", buffering=1)

# Loop bookkeeping
loop_counter = 0       # counts loops within the current "dump"
dump_index = 1         # how many dumps we've completed/separated
DUMP_SIZE = 48         # number of loops per dump


# --- Prices file (streaming) ---
PRICE_FILE_PATH = os.path.join(script_dir, "prices_electricity.txt")
price_file = open(PRICE_FILE_PATH, "a", encoding="utf-8", buffering=1)  # line-buffered


R = r"""
/////////////////////////////////////////////////////////////////////////////////////////////////
//     ___  ___  _      _   ___   ___ ___ ___ ___ ___    ___ _  _ ___ ___ _  _____ ___       ///
//    / __|/ _ \| |    /_\ | _ \ | _ \ _ \_ _/ __| __|  / __| || | __/ __| |/ / __| _ \     ///
//    \__ \ (_) | |__ / _ \|   / |  _/   /| | (__| _|  | (__| __ | _| (__| ' <| _||   /    ///
//    |___/\___/|____/_/ \_\_|_\ |_| |_|_\___\___|___|  \___|_||_|___\___|_|\_\___|_|_\   ///      
//                                                                                       ///                                    
///////////////////////////////////////////////////////////////////////////////////////////
                                                                                  
"""

# Load credentials from JSON file
with open(credentials_path, encoding="utf-8") as f:
    credentials = json.load(f)

# IBEX URL
URL = credentials["IBEX_URL"]

# GUI Initialization
root = tk.Tk()
root.title("Solar Price Checker")
root.geometry("750x600")
root.configure(bg="#1e1e1e")
login_frame = tk.Frame(root, bg="#1e1e1e")
login_frame.pack(pady=10)

output_box = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Consolas", 10), bg="#1e1e1e", fg="white", insertbackground="white")
output_box.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

output_box.tag_config("green", foreground="lime")
output_box.tag_config("red", foreground="red")
output_box.tag_config("white", foreground="white")

def log(text, tag="white"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # GUI
    output_box.insert(tk.END, text + "\n", tag)
    output_box.see(tk.END)
    # File (real-time, line-buffered)
    log_file.write(f"[{timestamp}] {text}\n")


def write_dump_separator(kind="START"):
    # kind can be "START" or "END" — here used only for GUI display
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = (
        "\n"
        "===============================================================================\n"
        f"==  {kind} OF DUMP #{dump_index}  @ {stamp}\n"
        "===============================================================================\n"
    )
    # GUI only
    output_box.insert(tk.END, sep, "white")
    output_box.see(tk.END)

log(R)

def get_driver():
    chromedriver_autoinstaller.install()
    version_info = subprocess.check_output(['chromedriver', '--version']).decode('utf-8')
    log(f"[INFO] Installed ChromeDriver version: {version_info.strip()}")
    options = Options()
#   options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    return driver

# Function to safely get a URL with retries
def safe_get(driver, url, retries=480, wait_time=60):
    for attempt in range(1, retries + 1):
        try:
            driver.get(url)
            log(f"[INFO] Loaded URL: {url}")
            return True
        except WebDriverException:
            log(f"[WARNING] Failed to load {url} (Attempt {attempt}/{retries}). Retrying in {wait_time} sec...", tag="red")
            time_module.sleep(wait_time)
    log(f"[ERROR] Could not load {url} after {retries} attempts.", tag="red")
    return False

# Function to click elements with retries
def safe_click(driver, by, value, retries=10, wait_time=10):
    for attempt in range(1, retries + 1):
        try:
            WebDriverWait(driver, wait_time).until(EC.element_to_be_clickable((by, value))).click()
            return True
        except (TimeoutException, WebDriverException):
            log(f"[WARNING] Failed to click {value} (Attempt {attempt}/{retries}). Retrying...", tag="red")
            time_module.sleep(5)
    log(f"[ERROR] Could not click {value} after {retries} attempts.", tag="red")
    return False


def log_price(price, context="CURRENT"):
    now_bg = datetime.now(sofia_tz)
    date_hour = now_bg.strftime("%d/%m/%Y %H:00")
    price_txt = "N/A" if price is None else f"{price:.2f} лв."
    price_file.write(f"[{date_hour}] Electricity price: {price_txt}\n")

# Function to send keys with retries
def safe_send_keys(driver, by, value, keys, retries=10, wait_time=10):
    for attempt in range(1, retries + 1):
        try:
            time_module.sleep(3)  # Wait for the element to be ready
            WebDriverWait(driver, wait_time).until(EC.presence_of_element_located((by, value))).send_keys(keys)
            return True
        except (TimeoutException, WebDriverException):
            log(f"[WARNING] Failed to send keys to {value} (Attempt {attempt}/{retries}). Retrying...", tag="red")
            time_module.sleep(5)
    log(f"[ERROR] Could not send keys to {value} after {retries} attempts.", tag="red")
    return False

# ---- Main Logic ----
global isOn

isOn = "First Run"

def main():      
    current_hour = datetime.now().hour
    current_minute = datetime.now().minute
    global loop_counter, dump_index
    loop_counter += 1

    if loop_counter == 1:
        # Starting a new dump window
        write_dump_separator("START")

    log(f"[INFO] Loop [{loop_counter}/{DUMP_SIZE}] in current dump window.")

    if loop_counter >= DUMP_SIZE:
        # Close out this dump window
        write_dump_separator("END")
        dump_index += 1
        loop_counter = 0  # will become 1 at the top of next main() call

        # "Begin again": clear GUI to keep it light, reprint banner
        output_box.delete("1.0", tk.END)
        log(f"[INFO] Cleared GUI log area to keep memory low. Beginning dump #{dump_index}...")
        log(R)


    log(f"[INFO] Current hour: {current_hour}")
    driver = get_driver()

    log("\n" + "="*70 + "\n[INFO] Checking prices...\n")

    try:
        if not safe_get(driver, URL):
            log_price(None, context="LOAD-FAIL")  # ensure a line for this hour
            driver.quit()
            return
     
        # Find the table with electricity prices
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        table = soup.find('table', {'id': 'wpdtSimpleTable-33'})
        if not table:
            log("[ERROR] Table not found. Retrying next cycle...")
            log_price(None, context="TABLE-NOT-FOUND")  # still write the hourly line
            driver.quit()
            return
        else:
            log("[SUCCESS] IBEX Price Table located.")

        rows = table.find('tbody').find_all('tr')
        selected_prices = []

        for i in range(0, len(rows), 2):
            try:
                if (current_hour == 0) or (14 <= current_hour <= 23):
                    last_col = rows[i].find_all('td')[-2].text.strip()  # IBEX second-last column
                    price = float(last_col.replace(',', '').replace('лв.', ''))
                    selected_prices.append(price)
                elif 1 <= current_hour <= 13:
                    last_col = rows[i].find_all('td')[-1].text.strip()  # IBEX last column
                    price = float(last_col.replace(',', '').replace('лв.', ''))
                    selected_prices.append(price)
                else:
                    selected_prices.append(None)
            except (IndexError, ValueError):
                selected_prices.append(None)

        # --- IMMEDIATE current-hour price determination (before weekend/weekday checks) ---
        if selected_prices:
            if current_hour == 0:
                # 00:00 -> last element
                current_price = selected_prices[-1]
            elif current_hour - 1 < len(selected_prices):
                current_price = selected_prices[current_hour - 1]

        # Stream to prices file right away
        log_price(current_price, context="IMMEDIATE")

        # Also show in GUI for visibility
        if current_price is not None:
            log(f"[INFO] Current hour ({current_hour}) price: {current_price} лв.")
        else:
            log("[WARNING] Current hour price unavailable.")

        today = datetime.today().weekday()
        if today in (5, 6):  # weekend
            if current_hour > int(sunset_hour) or current_hour < int(sunrise_hour):
                log(f"[INFO] Current hour ({current_hour}) is after sunset ({sunset_hour}:{sunset_minute}) or before sunrise ({sunrise_hour}:{sunrise_minute}).")
            elif current_hour == int(sunset_hour) and current_minute >= int(sunset_minute):
                log(f"[INFO] Current time is after sunset ({sunset_hour}:{sunset_minute}).")
            elif current_hour == int(sunrise_hour) and current_minute < int(sunrise_minute):
                log(f"[INFO] Current time is before sunrise ({sunrise_hour}:{sunrise_minute}).")
            else:
                if current_price is not None:
                    log(f"[INFO] Current hour ({current_hour}) price: {current_price} лв. (Bulgarian Time)")
                    if current_price > int(credentials["userPrice"]):
                        log(f"[ACTION] Price high. Turning ON Huawei.", tag="green")
                        huaweiON(driver)
                    else:
                        log(f"[ACTION] Price low. Turning OFF Huawei.", tag="red")
                        huaweiOFF(driver)
                else:
                    log("[WARNING] No valid price for current hour.")
        else:
            # Weekday: Monday sunrise auto-start
            if (today == 0 and current_hour == (int(sunrise_hour) + 1)):
                log(f"[INFO] Today is Monday. Starting the systems for the weekdays.")
                huaweiON(driver)
            else:
                log(f"[INFO] Today is a weekday. Skipping price check.")

    except Exception as e:
        log(f"[ERROR] Unexpected error: {e}", tag="red")

def huaweiON(driver):
    global isOn
    if isOn == "ON":
        log("[INFO] Huawei already ON. Skipping...")
        return

    if not safe_get(driver, "https://eu5.fusionsolar.huawei.com/"):
        driver.quit()
        return

    safe_send_keys(driver, By.ID, "username", credentials["username"])
    time_module.sleep(1)
    safe_send_keys(driver, By.ID, "value", credentials["password"])
    time_module.sleep(1)
    safe_click(driver, By.CLASS_NAME, "loginBtn")
    time_module.sleep(5)

    # Proizvodstveni Sgradi
    if safe_get(driver, "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134714396/submatrix/details"):
        safe_click(driver, By.XPATH, "//span[@title='Active Power Adjustment']/button")
        time_module.sleep(5)
        safe_send_keys(driver, By.CLASS_NAME, "ant-input-number-input", credentials["1"])
        time_module.sleep(5)
        safe_click(driver, By.XPATH, "//span[text()='Preset']/..")
        time_module.sleep(5)
        safe_click(driver, By.XPATH, "//span[text()='Execute']/..")
        time_module.sleep(10)
        safe_click(driver, By.XPATH, "//span[text()='OK']/..")
        time_module.sleep(3)
        log(f"[INFO] Proizvodstveni Sgradi set to {credentials['1']}kW")

    # Novi Skladove
    if safe_get(driver, "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134601162/submatrix/details"):
        safe_click(driver, By.XPATH, "//span[@title='Active Power Adjustment']/button")
        time_module.sleep(5)
        safe_send_keys(driver, By.CLASS_NAME, "ant-input-number-input", credentials["2"])
        time_module.sleep(5)
        safe_click(driver, By.XPATH, "//span[text()='Preset']/..")
        time_module.sleep(5)
        safe_click(driver, By.XPATH, "//span[text()='Execute']/..")
        time_module.sleep(10)
        safe_click(driver, By.XPATH, "//span[text()='OK']/..")
        time_module.sleep(3)
        log(f"[INFO] Novi Skladove set to {credentials['2']}kW")
        log(f"[SUCCESS] Automation successful! System is ON", tag="green")
    isOn = "ON"
    driver.quit()

def huaweiOFF(driver):
    global isOn
    if isOn == "OFF":
        log("[INFO] Huawei already OFF. Skipping...")
        return

    if not safe_get(driver, "https://eu5.fusionsolar.huawei.com/"):
        driver.quit()
        return

    safe_send_keys(driver, By.ID, "username", credentials["username"])
    time_module.sleep(1)
    safe_send_keys(driver, By.ID, "value", credentials["password"])
    time_module.sleep(1)
    safe_click(driver, By.CLASS_NAME, "loginBtn")
    time_module.sleep(10)

    # Proizvodstveni Sgradi
    if safe_get(driver, "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134714396/submatrix/details"):
        safe_click(driver, By.XPATH, "//span[@title='Active Power Adjustment']/button")
        time_module.sleep(5)
        safe_send_keys(driver, By.CLASS_NAME, "ant-input-number-input", "0")
        time_module.sleep(5)
        safe_click(driver, By.XPATH, "//span[text()='Preset']/..")
        time_module.sleep(5)
        safe_click(driver, By.XPATH, "//span[text()='Execute']/..")
        time_module.sleep(10)
        safe_click(driver, By.XPATH, "//span[text()='OK']/..")
        time_module.sleep(3)
        log("[INFO] Proizvodstveni Sgradi set to 0kW")

    # Novi Skladove
    if safe_get(driver, "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134601162/submatrix/details"):
        safe_click(driver, By.XPATH, "//span[@title='Active Power Adjustment']/button")
        time_module.sleep(5)
        safe_send_keys(driver, By.CLASS_NAME, "ant-input-number-input", "0")
        time_module.sleep(5)
        safe_click(driver, By.XPATH, "//span[text()='Preset']/..")
        time_module.sleep(5)
        safe_click(driver, By.XPATH, "//span[text()='Execute']/..")
        time_module.sleep(10)
        safe_click(driver, By.XPATH, "//span[text()='OK']/..")
        time_module.sleep(3)
        log("[INFO] Novi Skladove set to 0kW")
        log(f"[SUCCESS] Automation successful! System is OFF", tag="green")

    isOn = "OFF"
    driver.quit()

# Function to wait until the next hour
def wait_until_next_hour():
    now = datetime.now()
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    sleep_seconds = (next_hour - now).total_seconds()
    if int(now.hour) == int(sunrise_hour):
        log(f"[INFO] Waiting for sunrise at {sunrise_hour}:{sunrise_minute}")
        sunrise_time = datetime.combine(datetime.today(), time(int(sunrise_hour), int(sunrise_minute)))
        reference_time = datetime.combine(datetime.today(), time(int(sunrise_hour), 0))
        sleep_seconds = (sunrise_time - reference_time).total_seconds()
    time_module.sleep(sleep_seconds)

# Function to run the main function every hour
def hourly_loop():
    while True:
        try:
            main()
        except Exception as e:
            log(f"[ERROR] Main loop crash: {e}", tag="red")
        wait_until_next_hour()

# ---- Start program ----
Thread(target=hourly_loop, daemon=True).start()
root.mainloop()