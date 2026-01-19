# Solar Price Automation Controller (Huawei FusionSolar)

## 📌 Overview

**Solar Price Automation Controller** is a Python-based automation tool that monitors electricity market prices in real time and automatically controls a Huawei inverter via the FusionSolar web platform.

The system periodically:
1. Scrapes hourly electricity prices from an online IBEX table,
2. Evaluates those prices against user-defined thresholds and time-of-day logic (including sunrise/sunset rules), and
3. Logs into Huawei FusionSolar and adjusts the inverter’s active power output accordingly.

The primary goal of the tool is to **reduce or stop grid export when electricity prices are unfavorable**, while allowing production when conditions are optimal.

---

## ⚙️ Core Functionality

### 🔍 Automated Price Monitoring
The script retrieves hourly electricity prices by:
- Loading the IBEX price table in a headless (or visible) Chrome browser via Selenium,
- Parsing the relevant price columns using BeautifulSoup,
- Selecting the correct price for the current hour based on IBEX’s column structure.

All fetched prices are:
- Displayed in a live Tkinter GUI log window, and  
- Streamed to a file: `prices_electricity.txt`

---

### 🧠 Smart Decision Logic

The automation makes decisions based on:
- Current electricity price,
- User-defined price threshold (`userPrice` in `credentials.json`),
- Current time of day,
- Sunrise and sunset times for Sofia,
- Whether it is a weekday or weekend.

#### Weekend behavior:
- If the current time is outside daylight hours → no action.
- If within daylight hours:
  - **Price above threshold → Turn ON inverter output**
  - **Price below threshold → Set inverter output to 0 (no grid export)**

#### Weekday behavior: (Current system is based on weekends OFF as required consumption during those hours but could be changed)
- Automatically turns the system **ON after sunrise on Monday**.
- Otherwise, it skips price-based switching during normal weekdays.

---

### 🔐 Automated Huawei FusionSolar Control

When a state change is required, the script:
1. Logs into FusionSolar using credentials from `credentials.json`,
2. Navigates to two specific inverter sites: (More could be added)
   - **BUILDING 1**
   - **BUILDING 2**
3. Adjusts the **Active Power Adjustment** setting:
   - Sets it to `0 kW` when prices are low (no grid export),
   - Sets it to user-defined values (`credentials["1"]`, `credentials["2"]`) when prices are high.

All actions are logged in real time in both:
- The GUI window, and  
- A persistent log file: `solar_price_checker_logs.txt`

---

## 🖥️ User Interface (GUI)

The application includes a Tkinter-based dashboard that:
- Shows a live, color-coded activity log,
- Displays status messages for:
  - Price checks,
  - Browser automation,
  - Login attempts,
  - Power adjustments,
  - Errors and retries.

---

## 🛠 Requirements

### System
- Windows 10 or 11  
- Python 3.10+  
- Google Chrome installed  

### Python Dependencies
Install with:
```bash
pip install selenium chromedriver-autoinstaller beautifulsoup4 suntime pytz

**credentials.json structure**
{
  "IBEX_URL": "https://example.com/price-table",
  "username": "your_fusionsolar_email",
  "password": "your_password",
  "userPrice": "150", // Allowed price
  "1": "5", // KW Value for BUILDING 1
  "2": "6" // KW Value for BUILDING 2
}

