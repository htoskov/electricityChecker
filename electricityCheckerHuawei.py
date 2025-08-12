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
    output_box.insert(tk.END, text + "\n", tag)
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
global counterUntilDelete

counterUntilDelete = 1
isOn = "First Run"

def main():      
    current_hour = datetime.now().hour
    current_minute = datetime.now().minute
    global counterUntilDelete
    if counterUntilDelete == 20:
        counterUntilDelete = 1
        output_box.delete("1.0", tk.END)
        log(f"[INFO] Deleting all logs to prevent crashes. (20/20)")
        log(R)
    else:
        log(f"[INFO] Logs will be deleted after 20 total loops to prevent crashes [{counterUntilDelete}/20]")

    log(f"[INFO] Current hour: {current_hour}")
    driver = get_driver()
    counterUntilDelete += 1

    log("\n" + "="*70 + "\n[INFO] Checking prices...\n")

    try:
        if not safe_get(driver, URL):
            driver.quit()
            return
        
        # Find the table with electricity prices
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        table = soup.find('table', {'id': 'wpdtSimpleTable-33'})
        if not table:
            log("[ERROR] Table not found. Retrying next cycle...")
            driver.quit()
            return
        else:
            log("[SUCCESS] IBEX Price Table located.")

        rows = table.find('tbody').find_all('tr')
        selected_prices = []

        for i in range(0, len(rows), 2):
            try:
                if (current_hour == 0) or (current_hour <= 23 and current_hour >= 14):
                    last_col = rows[i].find_all('td')[-2].text.strip() # IBEX Second last column
                    price = float(last_col.replace(',', '').replace('лв.', ''))
                    selected_prices.append(price)
                elif current_hour <= 13 and current_hour >= 1:
                    last_col = rows[i].find_all('td')[-1].text.strip() # IBEX Last column
                    price = float(last_col.replace(',', '').replace('лв.', ''))
                    selected_prices.append(price)
            except (IndexError, ValueError):
                selected_prices.append(None)

        # Logic to check the current hour's price
        today = datetime.today().weekday()
        if today == 5 or today == 6:
            if current_hour > int(sunset_hour) or current_hour < int(sunrise_hour):
                log(f"[INFO] Current hour ({current_hour}) is after sunset ({sunset_hour}:{sunset_minute}) or before sunrise ({sunrise_hour}:{sunrise_minute}).")
            elif current_hour == int(sunset_hour) and current_minute >= int(sunset_minute):
                log(f"[INFO] Current time is after sunset ({sunset_hour}:{sunset_minute}).")
            elif current_hour == int(sunrise_hour) and current_minute < int(sunrise_minute):
                log(f"[INFO] Current time is before sunrise ({sunrise_hour}:{sunrise_minute}).")
            else:
                    if current_hour <= len(selected_prices):
                        if current_hour == 0:
                            current_price = selected_prices[len(selected_prices)-1]
                            log(current_price)
                        else:
                            current_price = selected_prices[current_hour - 1] # +1 because the selected_prices list is in CET timezone which is 1 hour behind.
                        log(f"[INFO] Current hour ({current_hour}) price: {current_price} лв. (Bulgarian Time)")

                        if current_price is not None:
                            if current_price > int(credentials["userPrice"]):
                                log(f"[ACTION] Price high. Turning ON Huawei.", tag="green")
                                huaweiON(driver)
                            else:
                                log(f"[ACTION] Price low. Turning OFF Huawei.", tag="red")
                                huaweiOFF(driver)
                        else:
                            log("[WARNING] No valid price for current hour.")
                    else:
                        print(len(selected_prices))
                        log("[WARNING] Not enough hourly data.")
        else:
            # Check if today is monday and check if current hour is sunrise hour to start the systems
            # Incase systems were turned off during the weekend they will start on monday sunrise
            if (today == 0 and current_hour == (int(sunrise_hour) + 1)):
                log(f"[INFO] Today is Monday. Starting the systems for the weekdays.")
                huaweiON(driver)
            else:
                log(f"Test")
            log(f"[INFO] Today is a weekday. Skipping price check.")
        log(f"\n[INFO] Next check scheduled...")

    except Exception as e:
        log(f"[ERROR] Unexpected error: {e}", tag="red")

    finally:
        driver.quit()

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