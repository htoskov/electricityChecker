from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.keys import Keys

import chromedriver_autoinstaller
from bs4 import BeautifulSoup
import json
import time as time_module
from datetime import datetime, timedelta
from suntime import Sun
import pytz
from threading import Thread
import tkinter as tk
from tkinter import scrolledtext
import os
import pandas as pd
from io import StringIO


# =========================
# CONFIG / TIMEZONE SETUP
# =========================

sofia_lat = 42.69
sofia_lon = 23.32

sofia_tz = pytz.timezone("Europe/Sofia")
market_tz = pytz.timezone("Europe/Brussels")  # CET/CEST market time used by IBEX
utc_tz = pytz.utc

sun = Sun(sofia_lat, sofia_lon)

today_utc = datetime.now(utc_tz)
sunrise_utc = sun.get_sunrise_time(today_utc)
sunset_utc = sun.get_sunset_time(today_utc)

sunrise_local = sunrise_utc.astimezone(sofia_tz)
sunset_local = sunset_utc.astimezone(sofia_tz)

sunrise_hour = sunrise_local.strftime("%H")
sunrise_minute = sunrise_local.strftime("%M")
sunset_hour = sunset_local.strftime("%H")
sunset_minute = sunset_local.strftime("%M")


script_dir = os.path.dirname(os.path.abspath(__file__))
credentials_path = os.path.join(script_dir, "credentials.json")

with open(credentials_path, encoding="utf-8") as f:
    credentials = json.load(f)

URL = credentials["IBEX_URL"]
HUAWEI_URL = credentials["HUAWEI_URL"]
BUILDING_1_NAME = credentials["BUILDING_1_NAME"]
BUILDING_2_NAME = credentials["BUILDING_2_NAME"]

# =========================
# LOG FILES
# =========================

LOG_FILE_PATH = os.path.join(script_dir, "solar_price_checker_logs.txt")
log_file = open(LOG_FILE_PATH, "a", encoding="utf-8", buffering=1)

PRICE_FILE_PATH = os.path.join(script_dir, "prices_electricity.txt")
price_file = open(PRICE_FILE_PATH, "a", encoding="utf-8", buffering=1)

loop_counter = 0
dump_index = 1
DUMP_SIZE = 48


R = r"""
/////////////////////////////////////////////////////////////////////////////////////////////////
//     ___  ___  _      _   ___   ___ ___ ___ ___ ___    ___ _  _ ___ ___ _  _____ ___       ///
//    / __|/ _ \| |    /_\ | _ \ | _ \ _ \_ _/ __| __|  / __| || | __/ __| |/ / __| _ \     ///
//    \__ \ (_) | |__ / _ \|   / |  _/   /| | (__| _|  | (__| __ | _| (__| ' <| _||   /    ///
//    |___/\___/|____/_/ \_\_|_\ |_| |_|_\___\___|___|  \___|_||_|___\___|_|\_\___|_|_\   ///      
//                                                                                       ///                                    
///////////////////////////////////////////////////////////////////////////////////////////
"""


# =========================
# GUI
# =========================

root = tk.Tk()
root.title("Solar Price Checker")
root.geometry("750x600")
root.configure(bg="#1e1e1e")

login_frame = tk.Frame(root, bg="#1e1e1e")
login_frame.pack(pady=10)

output_box = scrolledtext.ScrolledText(
    root,
    wrap=tk.WORD,
    font=("Consolas", 10),
    bg="#1e1e1e",
    fg="white",
    insertbackground="white",
)
output_box.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

output_box.tag_config("green", foreground="lime")
output_box.tag_config("red", foreground="red")
output_box.tag_config("white", foreground="white")

def dismiss_huawei_update_popup(driver):
    try:
        time_module.sleep(3)

        buttons = driver.find_elements(
            By.XPATH,
            "//button[.//span[contains(normalize-space(),'Do Not Show Again')]]"
        )

        visible_buttons = [btn for btn in buttons if btn.is_displayed() and btn.is_enabled()]

        if not visible_buttons:
            log("[INFO] No update popup found.")
            return False

        try:
            visible_buttons[0].click()
        except Exception:
            driver.execute_script("arguments[0].click();", visible_buttons[0])

        log("[INFO] Huawei popup dismissed.")
        time_module.sleep(2)
        return True

    except Exception as e:
        log(f"[INFO] No clickable Huawei popup found. Continuing normally.")
        return False

def log(text, tag="white"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        output_box.insert(tk.END, text + "\n", tag)
        output_box.see(tk.END)
    except Exception:
        pass

    log_file.write(f"[{timestamp}] {text}\n")


def write_dump_separator(kind="Number of"):
    global dump_index

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = (
        "\n"
        "===============================================================================\n"
        f"{kind} run {dump_index} @ {stamp}\n"
        "===============================================================================\n"
    )

    try:
        output_box.insert(tk.END, sep, "white")
        output_box.see(tk.END)
    except Exception:
        pass


log(R)


# =========================
# SELENIUM HELPERS
# =========================

def get_driver():
    chromedriver_autoinstaller.install()

    options = Options()

    # For visible browser on Windows, keep this commented.
    # For server/headless mode, uncomment:
    # options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=options)
    return driver


def safe_get(driver, url, retries=5, wait_time=10):
    for attempt in range(1, retries + 1):
        try:
            driver.get(url)
            log(f"[INFO] Loaded URL: {url}")
            return True
        except WebDriverException as e:
            log(
                f"[WARNING] Failed to load {url} "
                f"(Attempt {attempt}/{retries}). Error: {e}. Retrying in {wait_time} sec...",
                tag="red",
            )
            time_module.sleep(wait_time)

    log(f"[ERROR] Could not load {url} after {retries} attempts.", tag="red")
    return False


def safe_click(driver, by, value, retries=10, wait_time=10):
    for attempt in range(1, retries + 1):
        try:
            WebDriverWait(driver, wait_time).until(
                EC.element_to_be_clickable((by, value))
            ).click()
            return True
        except (TimeoutException, WebDriverException):
            log(
                f"[WARNING] Failed to click {value} "
                f"(Attempt {attempt}/{retries}). Retrying...",
                tag="red",
            )
            time_module.sleep(5)

    log(f"[ERROR] Could not click {value} after {retries} attempts.", tag="red")
    return False


def safe_send_keys(driver, by, value, keys, retries=10, wait_time=10):
    for attempt in range(1, retries + 1):
        try:
            time_module.sleep(2)
            element = WebDriverWait(driver, wait_time).until(
                EC.element_to_be_clickable((by, value))
            )

            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            element.click()

            # Properly clear preset value like 0, old kW, etc.
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(Keys.BACKSPACE)

            # Extra JS clear for stubborn Ant Design inputs
            driver.execute_script("""
                arguments[0].value = '';
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, element)

            element.send_keys(str(keys))
            return True

        except (TimeoutException, WebDriverException):
            log(
                f"[WARNING] Failed to send keys to {value} "
                f"(Attempt {attempt}/{retries}). Retrying...",
                tag="red",
            )
            time_module.sleep(5)

    log(f"[ERROR] Could not send keys to {value} after {retries} attempts.", tag="red")
    return False

# =========================
# PRICE PARSING
# =========================

def log_price(price, context="CURRENT"):
    now_bg = datetime.now(sofia_tz)
    date_time = now_bg.strftime("%d/%m/%Y %H:%M")
    price_txt = "N/A" if price is None else f"{price:.2f} EUR."
    price_file.write(f"[{date_time}] Electricity price: {price_txt} ({context})\n")


def normalize_price(value):
    if value is None:
        return None

    txt = str(value).strip()
    txt = txt.replace("\xa0", " ")
    txt = txt.replace("EUR.", "")
    txt = txt.replace("BGN/MWh", "")
    txt = txt.replace("EUR/MWh", "")
    txt = txt.replace(" ", "")

    # European decimal comma support
    if "," in txt and "." in txt:
        # Example: 1,234.56
        txt = txt.replace(",", "")
    elif "," in txt:
        # Example: 123,45
        txt = txt.replace(",", ".")

    try:
        return float(txt)
    except ValueError:
        return None


def get_current_15min_market_time():
    bg_now = datetime.now(sofia_tz)
    market_now = bg_now.astimezone(market_tz)

    current_q = market_now.replace(
        minute=(market_now.minute // 15) * 15,
        second=0,
        microsecond=0
    ).strftime("%H:%M")

    return current_q, market_now.strftime("%H:%M"), bg_now.strftime("%H:%M")


def wait_for_ibex_table(driver, timeout=30):
    """
    Wait for IBEX page to render at least one table.
    """
    end_time = time_module.time() + timeout

    while time_module.time() < end_time:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        tables = soup.find_all("table")

        if tables:
            return tables

        time_module.sleep(1)

    return []


def extract_current_price_from_ibex(driver):
    soup = BeautifulSoup(driver.page_source, "html.parser")

    html_tables = soup.find_all("table")
    if not html_tables:
        log("[ERROR] No tables found on IBEX page.", tag="red")
        return None

    current_q, market_now_txt, bg_now_txt = get_current_15min_market_time()

    log(f"[INFO] IBEX market time now: {market_now_txt}")
    log(f"[INFO] Looking for current 15-min period: {current_q}")

    found_prices = []

    for table in html_tables:
        try:
            dfs = pd.read_html(StringIO(str(table)))
        except Exception:
            continue

        for df in dfs:
            df.columns = [str(c).strip() for c in df.columns]

            price_columns = [
                col for col in df.columns
                if (
                    "price" in col.lower()
                    or "цена" in col.lower()
                    or "bgn/mwh" in col.lower()
                    or "eur/mwh" in col.lower()
                )
            ]

            if not price_columns:
                continue

            price_col = price_columns[0]

            for _, row in df.iterrows():
                row_text = " ".join([str(x).strip() for x in row.tolist()])

                if current_q in row_text:
                    price = normalize_price(row[price_col])

                    if price is not None:
                        found_prices.append(price)

    if not found_prices:
        log(f"[ERROR] Could not find PRICE value for {current_q}.", tag="red")
        return None

    current_price = found_prices[0]

    log(f"[INFO] Found current 15-min PRICE value: {current_price:.2f} EUR")

    return current_price


# =========================
# HUAWEI ACTIONS
# =========================

isOn = "First Run"


def huaweiON(driver):
    global isOn

    try:
        if isOn == "ON":
            log("[INFO] Huawei already ON. Skipping...")
            return

        if not safe_get(driver, HUAWEI_URL):
            return
        

        safe_send_keys(driver, By.ID, "username", credentials["username"])
        time_module.sleep(1)

        safe_send_keys(driver, By.ID, "value", credentials["password"])
        time_module.sleep(1)

        safe_click(driver, By.CLASS_NAME, "loginBtn")
        time_module.sleep(8)

        if safe_get(
            driver,
            "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134714396/submatrix/details",
        ):
            dismiss_huawei_update_popup(driver)
            time_module.sleep(3)
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
            log(f"[INFO] {BUILDING_1_NAME} set to {credentials['1']}kW", tag="green")

        if safe_get(
            driver,
            "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134601162/submatrix/details",
        ):
            dismiss_huawei_update_popup(driver)
            time_module.sleep(3)
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
            log(f"[INFO] {BUILDING_2_NAME} set to {credentials['2']}kW", tag="green")
            log("[SUCCESS] Successful! System is ON", tag="green")

        isOn = "ON"

    except Exception as e:
        log(f"[ERROR] huaweiON failed: {e}", tag="red")


def huaweiOFF(driver):
    global isOn

    try:
        if isOn == "OFF":
            log("[INFO] Huawei already OFF. Skipping...")
            return

        if not safe_get(driver, HUAWEI_URL):
            return

        safe_send_keys(driver, By.ID, "username", credentials["username"])
        time_module.sleep(1)

        safe_send_keys(driver, By.ID, "value", credentials["password"])
        time_module.sleep(1)

        safe_click(driver, By.CLASS_NAME, "loginBtn")
        time_module.sleep(10)

        if safe_get(
            driver,
            "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134714396/submatrix/details",
        ):
            dismiss_huawei_update_popup(driver)
            time_module.sleep(3)
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
            log(F"[INFO] {BUILDING_1_NAME} set to 0kW", tag="green")

        if safe_get(
            driver,
            "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134601162/submatrix/details",
        ):
            dismiss_huawei_update_popup(driver)
            time_module.sleep(3)
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
            log(F"[INFO] {BUILDING_2_NAME} set to 0kW", tag="green")
            log("[SUCCESS] Successful! System is OFF", tag="green")

        isOn = "OFF"

    except Exception as e:
        log(f"[ERROR] huaweiOFF failed: {e}", tag="red")


# =========================
# MAIN LOOP
# =========================

def main():
    global loop_counter, dump_index

    current_hour = datetime.now(sofia_tz).hour
    current_minute = datetime.now(sofia_tz).minute

    loop_counter += 1

    if loop_counter == 1:
        write_dump_separator("Number of")

    log(f"[INFO] [{loop_counter}/{DUMP_SIZE}] before window clear.")

    if loop_counter >= DUMP_SIZE:
        write_dump_separator("END")
        dump_index += 1
        loop_counter = 0

        try:
            output_box.delete("1.0", tk.END)
        except Exception:
            pass

        log(f"[INFO] Cleared GUI log area. Beginning dump #{dump_index}...")
        log(R)

    log(f"[INFO] Current Bulgaria time: {current_hour:02d}:{current_minute:02d}")

    driver = get_driver()

    try:
        log("" + "=" * 79 + "\n[INFO] Checking prices...")

        if not safe_get(driver, URL):
            log_price(None, context="LOAD-FAIL")
            return

        # Give dynamic page a little time after load
        time_module.sleep(5)

        current_price = extract_current_price_from_ibex(driver)
        log_price(current_price, context="IMMEDIATE")

        if current_price is None:
            log("[WARNING] Current price unavailable. Skipping Huawei action.")
            return

        today = datetime.now(sofia_tz).weekday()

        if today in (5, 6):  # Saturday/Sunday
            after_sunset = (
                current_hour > int(sunset_hour)
                or (current_hour == int(sunset_hour) and current_minute >= int(sunset_minute))
            )
            before_sunrise = (
                current_hour < int(sunrise_hour)
                or (current_hour == int(sunrise_hour) and current_minute < int(sunrise_minute))
            )

            if after_sunset or before_sunrise:
                log(
                    f"[INFO] Current time is outside solar hours "
                    f"sunrise={sunrise_hour}:{sunrise_minute}, sunset={sunset_hour}:{sunset_minute}."
                )
                return

            threshold = float(credentials["userPrice"])

            if current_price > threshold:
                log(f"[ACTION] Price {current_price:.2f} > threshold {threshold:.2f}. Turning ON Huawei.", tag="green")
                huaweiON(driver)
            else:
                log(f"[ACTION] Price {current_price:.2f} <= threshold {threshold:.2f}. Turning OFF Huawei.", tag="red")
                huaweiOFF(driver)

        else:
            # Weekday: Monday sunrise auto-start
            if today == 0 and current_hour == (int(sunrise_hour) + 1):
                log("[INFO] Monday after sunrise. Starting the systems for weekdays.")
                huaweiON(driver)
            else:
                log("[INFO] Today is a weekday. Skipping price-based Huawei action.")

    except Exception as e:
        log(f"[ERROR] Unexpected error: {e}", tag="red")

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def wait_until_next_30min():
    now = datetime.now(sofia_tz)

    if now.minute < 30:
        next_run = now.replace(minute=30, second=0, microsecond=0)
    else:
        next_run = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    sleep_seconds = (next_run - now).total_seconds()

    log(f"[INFO] Waiting until next 30-min check: {next_run.strftime('%H:%M')}")
    time_module.sleep(sleep_seconds + 10)


def hourly_loop():
    while True:
        try:
            main()
        except Exception as e:
            log(f"[ERROR] Main loop crash: {e}", tag="red")

        wait_until_next_30min()


# =========================
# START
# =========================

Thread(target=hourly_loop, daemon=True).start()
root.mainloop()
