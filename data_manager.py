import sqlite3
import csv
from datetime import date, timedelta, datetime
import time
import requests
import zipfile
import io

DB_PATH = "paper_trading.db"

def init_db():
    """Initializes the SQLite database with market_data and virtual_portfolio tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS market_data (
        SYMBOL TEXT,
        DATE DATE,
        OPEN REAL,
        HIGH REAL,
        LOW REAL,
        CLOSE REAL,
        VOLUME INTEGER,
        DELIV_QTY INTEGER,
        DELIV_PER REAL,
        PRIMARY KEY (SYMBOL, DATE)
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS virtual_portfolio (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        SYMBOL TEXT,
        ENTRY_DATE DATE,
        ENTRY_PRICE REAL,
        STATUS TEXT
    )
    ''')
    conn.commit()
    conn.close()

def add_to_portfolio(symbol, entry_date, entry_price):
    """Saves a stock pick to the virtual portfolio table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM virtual_portfolio WHERE SYMBOL = ? AND ENTRY_DATE = ?", (symbol, entry_date))
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO virtual_portfolio (SYMBOL, ENTRY_DATE, ENTRY_PRICE, STATUS) VALUES (?, ?, ?, ?)",
                           (symbol, entry_date, entry_price, "Active"))
            conn.commit()
            success = True
        else:
            success = False
    except Exception as e:
        print(f"DB Error adding to portfolio: {e}")
        success = False
    finally:
        conn.close()
    return success

def get_portfolio_trades():
    """Fetches all saved virtual trades."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT ID, SYMBOL, ENTRY_DATE, ENTRY_PRICE, STATUS FROM virtual_portfolio ORDER BY ENTRY_DATE DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def remove_from_portfolio(trade_id):
    """Removes a trade from the virtual portfolio."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM virtual_portfolio WHERE ID = ?", (trade_id,))
    conn.commit()
    conn.close()

def fetch_mto_data(target_date, session, headers):
    """Downloads and parses Security-wise Delivery Positions (MTO) for historical dates."""
    date_str_ddmmyyyy = target_date.strftime("%d%m%Y")
    mto_urls = [
        f"https://archives.nseindia.com/archives/equities/mto/MTO_{date_str_ddmmyyyy}.DAT",
        f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{date_str_ddmmyyyy}.DAT"
    ]
    
    for url in mto_urls:
        try:
            response = session.get(url, headers=headers, timeout=12)
            if response.status_code == 200:
                content = response.content.decode('utf-8', errors='ignore')
                data_lines = [l for l in content.splitlines() if l.startswith('20,')]
                if not data_lines:
                    continue
                
                mto_dict = {}
                for line in data_lines:
                    parts = line.split(',')
                    if len(parts) >= 7 and parts[3].strip().upper() == 'EQ':
                        try:
                            sym = parts[2].strip()
                            mto_dict[sym] = {
                                'DELIV_QTY': int(float(parts[5].strip())),
                                'DELIV_PER': float(parts[6].strip())
                            }
                        except ValueError:
                            continue
                if mto_dict:
                    return mto_dict
        except Exception:
            continue
    return None

def fetch_and_store_bhavcopy(target_date):
    """Fetches, processes, and stores equity bhavcopy and delivery data for a given date."""
    date_str_yyyymmdd = target_date.strftime("%Y%m%d")
    date_dash_str = target_date.strftime("%Y-%m-%d")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM market_data WHERE DATE = ?", (date_dash_str,))
    if cursor.fetchone()[0] > 0:
        conn.close()
        return True
    conn.close()

    if target_date.weekday() >= 5:  # Skip weekends
        return False

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive"
    }

    session = requests.Session()
    session.headers.update(headers)
    try:
        session.get("https://www.nseindia.com", timeout=8)
    except Exception:
        pass

    rows_to_insert = []
    has_delivery_in_bhav = False

    full_bhav_url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str_yyyymmdd}.csv"
    try:
        response = session.get(full_bhav_url, timeout=12)
        if response.status_code == 200:
            lines = response.content.decode('utf-8', errors='ignore').splitlines()
            reader = csv.DictReader(lines)
            fieldnames = [f.strip().upper() for f in reader.fieldnames] if reader.fieldnames else []
            
            sym_key = next((f for f in fieldnames if f in ['SYMBOL', 'TCKRSYMB']), None)
            series_key = next((f for f in fieldnames if f in ['SERIES', 'SCTYSRS']), None)
            open_key = next((f for f in fieldnames if f in ['OPEN_PRICE', 'OPEN', 'OPNPRIC']), None)
            high_key = next((f for f in fieldnames if f in ['HIGH_PRICE', 'HIGH', 'HGHPRIC']), None)
            low_key = next((f for f in fieldnames if f in ['LOW_PRICE', 'LOW', 'LWPRIC']), None)
            close_key = next((f for f in fieldnames if f in ['CLOSE_PRICE', 'CLOSE', 'CLSPRIC']), None)
            vol_key = next((f for f in fieldnames if f in ['TTL_TRADED_QTY', 'TOTTRDQTY', 'VOLUME', 'TTLTRADVOL', 'TTLTRADGVOL', 'TTL_TRADG_VOL']), None)
            deliv_qty_key = next((f for f in fieldnames if f in ['DELIV_QTY', 'DELIVQTY']), None)
            deliv_per_key = next((f for f in fieldnames if f in ['DELIV_PER', 'DELIVPER']), None)

            if sym_key and close_key:
                has_delivery_in_bhav = deliv_qty_key is not None
                for row in reader:
                    normalized_row = {k.strip().upper(): v for k, v in row.items()}
                    series = normalized_row.get(series_key, 'EQ').strip().upper() if series_key else 'EQ'
                    if series != 'EQ':
                        continue
                    try:
                        sym = normalized_row[sym_key].strip()
                        opn = float(normalized_row[open_key]) if open_key and normalized_row.get(open_key) else 0.0
                        high = float(normalized_row[high_key]) if high_key and normalized_row.get(high_key) else 0.0
                        low = float(normalized_row[low_key]) if low_key and normalized_row.get(low_key) else 0.0
                        close = float(normalized_row[close_key]) if close_key and normalized_row.get(close_key) else 0.0
                        vol = int(float(normalized_row[vol_key])) if vol_key and normalized_row.get(vol_key) else 0
                        deliv_q = int(float(normalized_row[deliv_qty_key])) if deliv_qty_key and normalized_row.get(deliv_qty_key) else 0
                        deliv_p = float(normalized_row[deliv_per_key]) if deliv_per_key and normalized_row.get(deliv_per_key) else 0.0

                        if sym and close > 0:
                            rows_to_insert.append((sym, date_dash_str, opn, high, low, close, vol, deliv_q, deliv_p))
                    except ValueError:
                        continue
    except Exception:
        pass

    if not rows_to_insert:
        udiff_url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str_yyyymmdd}_F_0000.csv.zip"
        try:
            response = session.get(udiff_url, timeout=12)
            if response.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                    with z.open(z.namelist()[0]) as f:
                        lines = f.read().decode('utf-8', errors='ignore').splitlines()
                        reader = csv.DictReader(lines)
                        for row in reader:
                            normalized_row = {k.strip().upper(): v for k, v in row.items()}
                            series = normalized_row.get('SERIES', 'EQ').strip().upper()
                            if series != 'EQ':
                                continue
                            try:
                                sym = normalized_row['SYMBOL'].strip()
                                opn = float(normalized_row.get('OPEN', 0))
                                high = float(normalized_row.get('HIGH', 0))
                                low = float(normalized_row.get('LOW', 0))
                                close = float(normalized_row.get('CLOSE', 0))
                                vol = int(float(normalized_row.get('TOTTRDQTY', 0)))
                                rows_to_insert.append((sym, date_dash_str, opn, high, low, close, vol, 0, 0.0))
                            except ValueError:
                                continue
        except Exception:
            pass

    mto_data = None
    if rows_to_insert and not has_delivery_in_bhav:
        mto_data = fetch_mto_data(target_date, session, headers)

    final_rows = []
    for r in rows_to_insert:
        sym, dt, opn, high, low, close, vol, dq, dp = r
        if mto_data and sym in mto_data:
            dq = mto_data[sym]['DELIV_QTY']
            dp = mto_data[sym]['DELIV_PER']
        final_rows.append((sym, dt, opn, high, low, close, vol, dq, dp))

    if final_rows:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.executemany('''
            INSERT OR REPLACE INTO market_data (SYMBOL, DATE, OPEN, HIGH, LOW, CLOSE, VOLUME, DELIV_QTY, DELIV_PER)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', final_rows)
        conn.commit()
        conn.close()
        return True

    return False

def update_database():
    """Maintains a rolling 500-day window & syncs missing dates."""
    init_db()
    today = date.today()
    cutoff_date = today - timedelta(days=500)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM market_data WHERE DATE < ?", (cutoff_date.strftime("%Y-%m-%d"),))
    conn.commit()

    cursor.execute("SELECT MAX(DATE) FROM market_data")
    result = cursor.fetchone()
    conn.close()
    
    if result and result[0]:
        start_date = datetime.strptime(result[0], "%Y-%m-%d").date() + timedelta(days=1)
    else:
        start_date = cutoff_date
        
    if start_date > today:
        return "Database is already up to date."

    current_date = start_date
    success_count = 0
    while current_date <= today:
        if current_date.weekday() < 5:
            if fetch_and_store_bhavcopy(current_date):
                success_count += 1
            time.sleep(0.3)
        current_date += timedelta(days=1)
        
    return f"Synced {success_count} new sessions."
