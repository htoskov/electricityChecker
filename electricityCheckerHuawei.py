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
import re
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
market_tz = pytz.timezone("Europe/Brussels")  # CET/CEST delivery time used by IBEX.
utc_tz = pytz.utc

sun = Sun(sofia_lat, sofia_lon)


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
CHROMEDRIVER_READY = False


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
# TIME HELPERS
# =========================

def get_sun_window(day=None):
    if day is None:
        day = datetime.now(sofia_tz).date()

    day_noon_local = sofia_tz.localize(datetime.combine(day, datetime.min.time()) + timedelta(hours=12))
    next_day_noon_local = day_noon_local + timedelta(days=1)
    day_noon_utc = day_noon_local.astimezone(utc_tz)
    next_day_noon_utc = next_day_noon_local.astimezone(utc_tz)

    sunrise = sun.get_sunrise_time(day_noon_utc).astimezone(sofia_tz)
    sunset = sun.get_sunset_time(next_day_noon_utc).astimezone(sofia_tz)

    return sunrise, sunset


def is_weekend(day=None):
    if day is None:
        day = datetime.now(sofia_tz).date()

    return day.weekday() in (5, 6)


def is_monday_sunrise_start_window(now=None):
    if now is None:
        now = datetime.now(sofia_tz)

    sunrise, _ = get_sun_window(now.date())
    start = sunrise + timedelta(hours=1)
    end = start + timedelta(minutes=30)

    return now.weekday() == 0 and start <= now < end


def is_outside_solar_hours(now=None):
    if now is None:
        now = datetime.now(sofia_tz)

    sunrise, sunset = get_sun_window(now.date())
    return now < sunrise or now >= sunset


def get_next_sunrise(now=None):
    if now is None:
        now = datetime.now(sofia_tz)

    for days_ahead in range(0, 8):
        candidate_day = now.date() + timedelta(days=days_ahead)
        sunrise, _ = get_sun_window(candidate_day)

        if sunrise > now:
            return sunrise

    return now + timedelta(hours=1)


# =========================
# SELENIUM HELPERS
# =========================

def get_driver():
    global CHROMEDRIVER_READY

    if not CHROMEDRIVER_READY:
        try:
            chromedriver_autoinstaller.install()
            CHROMEDRIVER_READY = True
        except Exception as e:
            log(f"[WARNING] ChromeDriver auto-install check failed: {e}. Trying existing driver.")

    options = Options()

    # For visible browser on Windows, keep this commented.
    # For server/headless mode, uncomment:
    # options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=options)
    return driver


def wait_for_document_ready(driver, timeout=30):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        return True
    except Exception:
        return False


def safe_get(driver, url, retries=5, wait_time=10, ready_timeout=30):
    for attempt in range(1, retries + 1):
        try:
            driver.get(url)
            wait_for_document_ready(driver, ready_timeout)
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
            element = WebDriverWait(driver, wait_time).until(
                EC.element_to_be_clickable((by, value))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time_module.sleep(0.5)

            try:
                element.click()
            except Exception:
                driver.execute_script("arguments[0].click();", element)

            return True
        except Exception:
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

        except Exception:
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


def get_target_delivery_date():
    return datetime.now(sofia_tz).date()


def format_ibex_date(value):
    return value.strftime("%d.%m.%Y")


def format_ibex_bulgarian_date(value):
    months = {
        1: "януари",
        2: "февруари",
        3: "март",
        4: "април",
        5: "май",
        6: "юни",
        7: "юли",
        8: "август",
        9: "септември",
        10: "октомври",
        11: "ноември",
        12: "декември",
    }

    return f"{value.day} {months[value.month]} {value.year}"


def parse_ibex_date(value):
    if value is None:
        return None

    txt = str(value).strip().replace("\xa0", " ")
    txt = re.sub(r"\s+", " ", txt)

    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(txt[:10], fmt).date()
        except ValueError:
            pass

    return None


def get_current_market_periods():
    bg_now = datetime.now(sofia_tz)
    market_now = bg_now.astimezone(market_tz)

    quarter_start = market_now.replace(
        minute=(market_now.minute // 15) * 15,
        second=0,
        microsecond=0
    )
    quarter_end = quarter_start + timedelta(minutes=15)
    hour_start = market_now.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + timedelta(hours=1)

    periods = [
        quarter_start.strftime("%H:%M"),
        f"{quarter_start:%H:%M} - {quarter_end:%H:%M}",
        f"{quarter_start:%H:%M}-{quarter_end:%H:%M}",
        f"{hour_start.hour} - {hour_end.hour}",
        f"{hour_start:%H} - {hour_end:%H}",
        f"{hour_start:%H:%M} - {hour_end:%H:%M}",
        f"{hour_start:%H:%M}-{hour_end:%H:%M}",
    ]

    return periods, market_now.strftime("%H:%M"), bg_now.strftime("%H:%M")


def row_matches_delivery_date(row, date_columns, target_date):
    if not date_columns:
        return True

    for col in date_columns:
        parsed_date = parse_ibex_date(row.get(col))
        if parsed_date == target_date:
            return True

    return False


def get_ibex_date_picker_date(driver):
    try:
        date_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "datePicker"))
        )
        return parse_ibex_date(date_input.get_attribute("value"))
    except Exception:
        return None


def wait_for_ibex_delivery_date(driver, target_date, timeout=15):
    end_time = time_module.time() + timeout

    while time_module.time() < end_time:
        current_date = get_ibex_date_picker_date(driver)

        if current_date == target_date:
            return True

        time_module.sleep(1)

    return False


def set_ibex_delivery_date_direct(driver, target_date):
    date_txt = format_ibex_date(target_date)

    try:
        date_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "datePicker"))
        )
        date_input.click()
        date_input.send_keys(Keys.CONTROL, "a")
        date_input.send_keys(Keys.BACKSPACE)
        date_input.send_keys(date_txt)
        date_input.send_keys(Keys.ENTER)

        if wait_for_ibex_delivery_date(driver, target_date, timeout=15):
            log(f"[INFO] IBEX delivery date set directly to {date_txt}.")
            return True

    except Exception as e:
        log(f"[WARNING] Direct IBEX date selection failed: {e}")

    return False


def ensure_ibex_delivery_date(driver):
    target_date = get_target_delivery_date()
    target_txt = format_ibex_date(target_date)
    current_date = get_ibex_date_picker_date(driver)

    if current_date is None:
        log("[WARNING] Could not read IBEX delivery date picker. Will parse rendered data only.")
        return False

    if current_date == target_date:
        log(f"[INFO] IBEX delivery date is already today: {target_txt}.")
        return True

    log(
        f"[WARNING] IBEX page opened delivery date {format_ibex_date(current_date)}, "
        f"but Bulgaria today is {target_txt}."
    )

    if current_date > target_date:
        days_back = min((current_date - target_date).days, 31)

        try:
            prev_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "prevDate"))
            )

            for _ in range(days_back):
                prev_button.click()
                time_module.sleep(2)

                if wait_for_ibex_delivery_date(driver, target_date, timeout=5):
                    log(f"[INFO] IBEX delivery date moved back to today: {target_txt}.")
                    return True

                prev_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "prevDate"))
                )

        except Exception as e:
            log(f"[WARNING] IBEX previous-date button failed: {e}")

    elif current_date < target_date:
        days_forward = min((target_date - current_date).days, 31)

        try:
            next_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "nextDate"))
            )

            for _ in range(days_forward):
                next_button.click()
                time_module.sleep(2)

                if wait_for_ibex_delivery_date(driver, target_date, timeout=5):
                    log(f"[INFO] IBEX delivery date moved forward to today: {target_txt}.")
                    return True

                next_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "nextDate"))
                )

        except Exception as e:
            log(f"[WARNING] IBEX next-date button failed: {e}")

    if set_ibex_delivery_date_direct(driver, target_date):
        return True

    log("[ERROR] Could not switch IBEX to today's delivery date.", tag="red")
    return False


def table_matches_delivery_date(table, target_date):
    table_text = table.get_text(" ", strip=True)
    target_values = {
        target_date.strftime("%d/%m/%Y"),
        target_date.strftime("%d.%m.%Y"),
        target_date.strftime("%Y-%m-%d"),
        format_ibex_bulgarian_date(target_date),
    }

    return any(value in table_text for value in target_values)


def row_matches_market_period(row_text, current_periods):
    normalized = re.sub(r"\s+", " ", row_text)

    for period in current_periods:
        pattern = rf"(?<!\d){re.escape(period)}(?!\d)"
        if re.search(pattern, normalized):
            return True

    return False


def choose_price_column(columns):
    preferred = [
        "price_eur",
        "eur/mwh",
        "euro/mwh",
        "eur",
        "евро/mwh",
        "евро",
        "price",
        "цена",
        "bgn/mwh",
    ]

    lowered = {str(col).strip().lower(): col for col in columns}

    for token in preferred:
        for lowered_col, original_col in lowered.items():
            if token in lowered_col:
                return original_col

    return None


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

    target_date = get_target_delivery_date()
    current_periods, market_now_txt, bg_now_txt = get_current_market_periods()

    log(f"[INFO] IBEX CET/CEST delivery time now: {market_now_txt}")
    log(f"[INFO] Looking for delivery date: {target_date.strftime('%d/%m/%Y')}")
    log(f"[INFO] Looking for current market periods: {', '.join(current_periods[:4])}")

    found_prices = []
    target_tables = []

    if get_ibex_date_picker_date(driver) == target_date:
        log("[INFO] IBEX page date picker confirms today's delivery date.")
    else:
        for table in html_tables:
            if table_matches_delivery_date(table, target_date):
                target_tables.append(table)

        if target_tables:
            html_tables = target_tables
        else:
            log("[WARNING] Could not identify an IBEX table dated today. Will inspect all rendered tables.")

    for table in html_tables:
        try:
            dfs = pd.read_html(StringIO(str(table)))
        except Exception:
            continue

        for df in dfs:
            df.columns = [str(c).strip() for c in df.columns]

            price_col = choose_price_column(df.columns)

            if not price_col:
                continue

            date_columns = [col for col in df.columns if "date" in col.lower()]

            for _, row in df.iterrows():
                row_text = " ".join([str(x).strip() for x in row.tolist()])

                if not row_matches_delivery_date(row, date_columns, target_date):
                    continue

                if row_matches_market_period(row_text, current_periods):
                    price = normalize_price(row[price_col])

                    if price is not None:
                        found_prices.append(price)

    if not found_prices:
        log("[ERROR] Could not find PRICE value for the current period and delivery date.", tag="red")
        return None

    current_price = found_prices[0]

    log(f"[INFO] Found current 15-min PRICE value: {current_price:.2f} EUR")

    return current_price


# =========================
# HUAWEI ACTIONS
# =========================

isOn = "First Run"


def login_to_huawei(driver):
    if not safe_get(driver, HUAWEI_URL, retries=5, wait_time=10, ready_timeout=45):
        return False

    if not safe_send_keys(driver, By.ID, "username", credentials["username"], retries=12, wait_time=15):
        log("[ERROR] Could not enter Huawei username.", tag="red")
        return False

    time_module.sleep(1)

    if not safe_send_keys(driver, By.ID, "value", credentials["password"], retries=12, wait_time=15):
        log("[ERROR] Could not enter Huawei password.", tag="red")
        return False

    time_module.sleep(1)

    if not safe_click(driver, By.CLASS_NAME, "loginBtn", retries=12, wait_time=15):
        log("[ERROR] Could not click Huawei login button.", tag="red")
        return False

    time_module.sleep(10)
    return True


def adjust_huawei_device(driver, device_url, target_kw, building_name):
    if not safe_get(driver, device_url, retries=5, wait_time=10, ready_timeout=45):
        return False

    dismiss_huawei_update_popup(driver)
    time_module.sleep(5)

    if not safe_click(driver, By.XPATH, "//span[@title='Active Power Adjustment']/button", retries=12, wait_time=15):
        log(f"[ERROR] Could not open Active Power Adjustment for {building_name}.", tag="red")
        return False

    time_module.sleep(5)

    if not safe_send_keys(driver, By.CLASS_NAME, "ant-input-number-input", target_kw, retries=12, wait_time=15):
        log(f"[ERROR] Could not enter target kW for {building_name}.", tag="red")
        return False

    time_module.sleep(5)

    if not safe_click(driver, By.XPATH, "//span[text()='Preset']/..", retries=12, wait_time=15):
        log(f"[ERROR] Could not click Preset for {building_name}.", tag="red")
        return False

    time_module.sleep(5)

    if not safe_click(driver, By.XPATH, "//span[text()='Execute']/..", retries=12, wait_time=15):
        log(f"[ERROR] Could not click Execute for {building_name}.", tag="red")
        return False

    time_module.sleep(10)

    if not safe_click(driver, By.XPATH, "//span[text()='OK']/..", retries=12, wait_time=15):
        log(f"[ERROR] Could not confirm OK for {building_name}.", tag="red")
        return False

    time_module.sleep(3)
    log(f"[INFO] {building_name} set to {target_kw}kW", tag="green")
    return True


def huaweiON(driver):
    global isOn

    try:
        if isOn == "ON":
            log("[INFO] Huawei already ON. Skipping...")
            return

        if not login_to_huawei(driver):
            return

        building_1_ok = adjust_huawei_device(
            driver,
            "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134714396/submatrix/details",
            credentials["1"],
            BUILDING_1_NAME,
        )
        building_2_ok = adjust_huawei_device(
            driver,
            "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134601162/submatrix/details",
            credentials["2"],
            BUILDING_2_NAME,
        )

        if building_1_ok and building_2_ok:
            log("[SUCCESS] Successful! System is ON", tag="green")
            isOn = "ON"
        else:
            log("[ERROR] Huawei ON action did not complete for all buildings.", tag="red")

    except Exception as e:
        log(f"[ERROR] huaweiON failed: {e}", tag="red")


def huaweiOFF(driver):
    global isOn

    try:
        if isOn == "OFF":
            log("[INFO] Huawei already OFF. Skipping...")
            return

        if not login_to_huawei(driver):
            return

        building_1_ok = adjust_huawei_device(
            driver,
            "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134714396/submatrix/details",
            "0",
            BUILDING_1_NAME,
        )
        building_2_ok = adjust_huawei_device(
            driver,
            "https://uni002eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-2-aaeafa18-4690-4f82-b58f-f69e775e788c#/view/device/NE=134601162/submatrix/details",
            "0",
            BUILDING_2_NAME,
        )

        if building_1_ok and building_2_ok:
            log("[SUCCESS] Successful! System is OFF", tag="green")
            isOn = "OFF"
        else:
            log("[ERROR] Huawei OFF action did not complete for all buildings.", tag="red")

    except Exception as e:
        log(f"[ERROR] huaweiOFF failed: {e}", tag="red")


# =========================
# MAIN LOOP
# =========================

def main():
    global loop_counter, dump_index

    now_bg = datetime.now(sofia_tz)
    current_hour = now_bg.hour
    current_minute = now_bg.minute
    today = now_bg.weekday()

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

    driver = None

    try:
        if today in (5, 6) and is_outside_solar_hours(now_bg):
            sunrise, sunset = get_sun_window(now_bg.date())
            log(
                f"[INFO] Weekend outside solar hours. "
                f"sunrise={sunrise.strftime('%H:%M')}, sunset={sunset.strftime('%H:%M')}. "
                "Skipping IBEX and Huawei until sunrise."
            )
            return

        if today not in (5, 6):
            if is_monday_sunrise_start_window(now_bg):
                log("[INFO] Monday after sunrise. Starting the systems for weekdays.")
                driver = get_driver()
                huaweiON(driver)
            else:
                log("[INFO] Today is a weekday. Skipping price-based IBEX/Huawei action.")
            return

        driver = get_driver()

        log("" + "=" * 79 + "\n[INFO] Checking prices...")

        ibex_ready = False

        for attempt in range(1, 3):
            if not safe_get(driver, URL, retries=3, wait_time=10, ready_timeout=45):
                log_price(None, context="LOAD-FAIL")
                return

            # Give the dynamic IBEX widgets time to pass their JS gate and render tables.
            time_module.sleep(8)
            ensure_ibex_delivery_date(driver)

            if wait_for_ibex_table(driver, 45):
                ibex_ready = True
                break

            log(f"[WARNING] IBEX table did not render on attempt {attempt}/2. Reloading page...")

        if not ibex_ready:
            log("[ERROR] IBEX table did not render after reload.", tag="red")
            log_price(None, context="TABLE-FAIL")
            return

        current_price = extract_current_price_from_ibex(driver)
        log_price(current_price, context="IMMEDIATE")

        if current_price is None:
            log("[WARNING] Current price unavailable. Skipping Huawei action.")
            return

        threshold = float(credentials["userPrice"])

        if current_price > threshold:
            log(f"[ACTION] Price {current_price:.2f} > threshold {threshold:.2f}. Turning ON Huawei.", tag="green")
            huaweiON(driver)
        else:
            log(f"[ACTION] Price {current_price:.2f} <= threshold {threshold:.2f}. Turning OFF Huawei.", tag="red")
            huaweiOFF(driver)

    except Exception as e:
        log(f"[ERROR] Unexpected error: {e}", tag="red")

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def wait_until_next_run():
    now = datetime.now(sofia_tz)

    if is_weekend(now.date()) and is_outside_solar_hours(now):
        next_run = get_next_sunrise(now)
        log(f"[INFO] Waiting until next sunrise check: {next_run.strftime('%Y-%m-%d %H:%M')}")
    elif now.minute < 30:
        next_run = now.replace(minute=30, second=0, microsecond=0)
        log(f"[INFO] Waiting until next 30-min check: {next_run.strftime('%H:%M')}")
    else:
        next_run = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        log(f"[INFO] Waiting until next 30-min check: {next_run.strftime('%H:%M')}")

    sleep_seconds = (next_run - now).total_seconds()

    time_module.sleep(sleep_seconds + 10)


def hourly_loop():
    while True:
        try:
            main()
        except Exception as e:
            log(f"[ERROR] Main loop crash: {e}", tag="red")

        wait_until_next_run()


# =========================
# START
# =========================

Thread(target=hourly_loop, daemon=True).start()
root.mainloop()
