import os
import sqlite3
import threading
import requests
from datetime import datetime
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.uix.progressbar import ProgressBar
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel, MDIcon
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText

# Import data manager functions
from data_manager import DB_PATH, update_database, add_to_portfolio, get_portfolio_trades, remove_from_portfolio

# Default Preset Parameters
DEFAULT_PARAMS = {
    'lookback': 40,
    'vol_mult': 2.2,
    'deliv_mult': 1.1,
    'turnover_min': 100_000_000.0,
    'sma_period': 150,
    'init_stop_pct': 0.025,
    'tight_trail_pct': 0.015
}

PARAMS = DEFAULT_PARAMS.copy()

KV = '''
MDScreen:
    md_bg_color: 0.058, 0.09, 0.165, 1

    MDBoxLayout:
        orientation: 'vertical'

        MDTopAppBar:
            type: "small"
            elevation: 4
            md_bg_color: 0.118, 0.161, 0.231, 1
            MDTopAppBarTitle:
                text: "[b]QUANT[color=#38BDF8]PULSE[/color][/b]"
                markup: True
                halign: "left"
            MDTopAppBarTrailingButtonContainer:
                MDActionTopAppBarButton:
                    id: view_toggle_icon
                    icon: "briefcase-outline"
                    on_release: app.toggle_portfolio_view()
                MDActionTopAppBarButton:
                    id: settings_toggle_icon
                    icon: "cog"
                    on_release: app.toggle_settings_view()
                MDActionTopAppBarButton:
                    icon: "refresh"
                    on_release: app.trigger_initial_sync()

        MDBoxLayout:
            orientation: 'vertical'
            padding: dp(15)
            spacing: dp(10)

            ScrollView:
                MDList:
                    id: main_container_list
                    spacing: dp(15)
                    adaptive_height: True

            MDBoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: dp(90)
                spacing: dp(6)

                ProgressBar:
                    id: progress_bar
                    max: 100
                    value: 0
                    size_hint_x: 1
                    size_hint_y: None
                    height: dp(4)

                MDLabel:
                    id: status_label
                    text: ""
                    font_style: "Body"
                    role: "small"
                    theme_text_color: "Custom"
                    text_color: 0.22, 0.74, 0.97, 1
                    halign: "center"
                    size_hint_y: None
                    height: "18dp"

                MDCard:
                    orientation: "horizontal"
                    padding: "10dp"
                    size_hint_y: None
                    height: "40dp"
                    elevation: 1
                    md_bg_color: 0.118, 0.161, 0.231, 1
                    radius: [8, 8, 8, 8]

                    MDLabel:
                        id: footer_date_label
                        text: "Dataset Range: Initializing..."
                        font_style: "Label"
                        role: "medium"
                        theme_text_color: "Secondary"
                        halign: "center"
'''

class AlgorithmTradesApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.raw_data_cache = []
        self.processed_data_cache = []
        self.available_dates = []
        self.showing_settings = False
        self.showing_portfolio = False
        self.status_timer = None
        
        self.week_display_limit = 10
        self.month_display_limit = 20

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Cyan"
        return Builder.load_string(KV)

    def on_start(self):
        self.render_splash_screen()
        Clock.schedule_once(lambda dt: self.trigger_initial_sync(), 0.5)

    def set_status(self, text):
        self.root.ids.status_label.text = text
        if self.status_timer:
            self.status_timer.cancel()
        self.status_timer = Clock.schedule_once(lambda dt: self.clear_status(), 5.0)

    def clear_status(self, *args):
        self.root.ids.status_label.text = ""

    def update_progress(self, val, text):
        self.root.ids.progress_bar.value = val
        self.set_status(text)

    def render_splash_screen(self):
        list_view = self.root.ids.main_container_list
        list_view.clear_widgets()

        splash_box = MDBoxLayout(
            orientation='vertical',
            spacing='20dp',
            padding='40dp',
            size_hint_y=None,
            height='450dp'
        )

        title_label = MDLabel(
            text="[b]QUANT[color=#38BDF8]PULSE[/color][/b]",
            markup=True,
            font_style="Display",
            role="large",
            halign="center",
            size_hint_y=None,
            height="80dp"
        )
        
        subtitle_label = MDLabel(
            text="Institutional Quantitative Terminal",
            font_style="Title",
            role="medium",
            theme_text_color="Secondary",
            halign="center",
            size_hint_y=None,
            height="30dp"
        )

        splash_box.add_widget(title_label)
        splash_box.add_widget(subtitle_label)
        list_view.add_widget(splash_box)

    def trigger_initial_sync(self):
        self.update_progress(10, "Checking local database...")
        threading.Thread(target=self.background_sync_and_load, daemon=True).start()

    def background_sync_and_load(self):
        try:
            # First-launch check: If database doesn't exist locally, download it from GitHub Release
            if not os.path.exists(DB_PATH):
                Clock.schedule_once(lambda dt: self.update_progress(15, "Downloading market database (First launch)..."))
                
                # TODO: Replace the URL below with your actual GitHub Release direct download link
                db_url = "https://github.com/tirthanand/quantpulse-app/releases/download/v1.0.0/paper_trading.db"
                
                db_dir = os.path.dirname(DB_PATH)
                if db_dir and not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)
                
                response = requests.get(db_url, stream=True)
                response.raise_for_status()
                with open(DB_PATH, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                Clock.schedule_once(lambda dt: self.update_progress(35, "Database download complete."))

            self.update_progress(45, "Syncing missing market data from NSE...")
            sync_result = update_database()
            print(f"Sync Log: {sync_result}")

            Clock.schedule_once(lambda dt: self.update_progress(60, "Loading database into memory..."))
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT SYMBOL, DATE, OPEN, HIGH, LOW, CLOSE, VOLUME, DELIV_QTY, DELIV_PER 
                FROM market_data 
                ORDER BY DATE ASC, SYMBOL ASC
            """)
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                Clock.schedule_once(lambda dt: self.finalize_ui_error("Database is empty."))
                return

            self.raw_data_cache = []
            date_set = set()
            for r in rows:
                sym, dt_str, opn, high, low, close, vol, d_qty, d_per = r
                dt_obj = datetime.strptime(dt_str, "%Y-%m-%d").date()
                date_set.add(dt_obj)
                self.raw_data_cache.append({
                    'SYMBOL': sym,
                    'DATE': dt_obj,
                    'OPEN': opn,
                    'HIGH': high,
                    'LOW': low,
                    'CLOSE': close,
                    'VOLUME': vol,
                    'DELIV_QTY': d_qty,
                    'DELIV_PER': d_per
                })

            Clock.schedule_once(lambda dt: self.update_progress(85, "Calculating quantitative indicators..."))
            self.processed_data_cache = self.precalculate_indicators(self.raw_data_cache)
            self.available_dates = sorted(list(date_set))

            min_date = self.available_dates[0]
            max_date = self.available_dates[-1]

            Clock.schedule_once(lambda dt: self.update_progress(100, "Dashboard updated successfully."))
            Clock.schedule_once(lambda dt: self.refresh_current_view())
            Clock.schedule_once(lambda dt: self.update_footer_range(min_date, max_date))

        except Exception as e:
            print(f"Pipeline Error: {e}")
            Clock.schedule_once(lambda dt: self.finalize_ui_error(f"Error: {str(e)}"))

    def precalculate_indicators(self, raw_data):
        # Group by symbol
        symbol_groups = {}
        for row in raw_data:
            sym = row['SYMBOL']
            if sym not in symbol_groups:
                symbol_groups[sym] = []
            symbol_groups[sym].append(row)

        lookback = PARAMS['lookback']
        vol_mult = PARAMS['vol_mult']
        deliv_mult = PARAMS['deliv_mult']
        turnover_min = PARAMS['turnover_min']
        sma_period = PARAMS['sma_period']

        processed_rows = []

        for sym, rows in symbol_groups.items():
            rows.sort(key=lambda x: x['DATE'])
            n = len(rows)
            for i in range(n):
                r = rows[i].copy()
                close = r['CLOSE']
                vol = r['VOLUME']
                deliv_p = r['DELIV_PER']

                # Prev Close & Turnover Proxy
                r['Prev_Close'] = rows[i-1]['CLOSE'] if i > 0 else close
                r['Turnover_Proxy'] = close * vol

                # 20-day Volume Average (shifted by 1)
                if i >= 20:
                    vol_window = [rows[j]['VOLUME'] for j in range(i - 20, i)]
                    r['Vol_Avg_20'] = sum(vol_window) / 20.0
                else:
                    r['Vol_Avg_20'] = 0.0

                # 20-day Delivery Average (shifted by 1)
                if i >= 20:
                    deliv_window = [rows[j]['DELIV_PER'] for j in range(i - 20, i)]
                    r['Deliv_Avg_20'] = sum(deliv_window) / 20.0
                else:
                    r['Deliv_Avg_20'] = 0.0

                # Lookback High (shifted by 2)
                if i >= lookback + 1:
                    high_window = [rows[j]['HIGH'] for j in range(i - lookback - 1, i - 1)]
                    r['High_Lookback'] = max(high_window)
                else:
                    r['High_Lookback'] = 0.0

                # SMA calculation
                if sma_period > 0:
                    if i >= sma_period - 1:
                        sma_window = [rows[j]['CLOSE'] for j in range(i - sma_period + 1, i + 1)]
                        r['SMA'] = sum(sma_window) / sma_period
                        macro_filter = close > r['SMA']
                    else:
                        r['SMA'] = 0.0
                        macro_filter = False  # Matches Pandas NaN behavior: insufficient history cannot clear SMA
                else:
                    r['SMA'] = 0.0
                    macro_filter = True

                # Signal Condition
                cond_price = r['Prev_Close'] > r['High_Lookback'] if r['High_Lookback'] > 0 else False
                cond_vol = vol > (vol_mult * r['Vol_Avg_20']) if r['Vol_Avg_20'] > 0 else False
                cond_deliv = deliv_p > (deliv_mult * r['Deliv_Avg_20']) if r['Deliv_Avg_20'] > 0 else False
                cond_turnover = r['Turnover_Proxy'] > turnover_min

                r['Signal'] = cond_price and cond_vol and cond_deliv and cond_turnover and macro_filter

                # Scores
                vol_score = (vol / r['Vol_Avg_20']) if r['Vol_Avg_20'] > 0 else 0.0
                deliv_score = (deliv_p / r['Deliv_Avg_20']) if r['Deliv_Avg_20'] > 0 else 0.0
                breakout_dist = ((r['Prev_Close'] - r['High_Lookback']) / r['High_Lookback']) if r['High_Lookback'] > 0 else 0.0
                r['Signal_Score'] = vol_score + deliv_score + breakout_dist

                processed_rows.append(r)

        return processed_rows

    def toggle_settings_view(self):
        self.showing_settings = not self.showing_settings
        self.showing_portfolio = False
        self.root.ids.settings_toggle_icon.icon = "view-dashboard" if self.showing_settings else "cog"
        self.root.ids.view_toggle_icon.icon = "briefcase-outline"
        self.refresh_current_view()

    def toggle_portfolio_view(self):
        self.showing_portfolio = not self.showing_portfolio
        self.showing_settings = False
        self.root.ids.view_toggle_icon.icon = "view-dashboard" if self.showing_portfolio else "briefcase-outline"
        self.root.ids.settings_toggle_icon.icon = "cog"
        self.refresh_current_view()

    def refresh_current_view(self):
        if self.showing_settings:
            self.render_settings_form()
        elif self.showing_portfolio:
            self.render_portfolio_view()
        else:
            self.render_full_dashboard()

    def render_settings_form(self):
        self.set_status("Adjust strategy parameters below.")
        list_view = self.root.ids.main_container_list
        list_view.clear_widgets()

        self.add_section_header("Strategy Parameter Tuning", "tune")

        self.tf_lookback = self.create_text_field("Lookback Window (5-150)", str(PARAMS['lookback']))
        self.tf_vol = self.create_text_field("Volume Multiplier", str(PARAMS['vol_mult']))
        self.tf_deliv = self.create_text_field("Delivery Multiplier", str(PARAMS['deliv_mult']))
        self.tf_turnover = self.create_text_field("Min Turnover (₹)", str(int(PARAMS['turnover_min'])))
        self.tf_sma = self.create_text_field("SMA Period (0 to 300)", str(PARAMS['sma_period']))
        self.tf_init_stop = self.create_text_field("Initial Stop Loss %", str(PARAMS['init_stop_pct'] * 100))
        self.tf_trail = self.create_text_field("Trailing Stop %", str(PARAMS['tight_trail_pct'] * 100))

        btn_box = MDBoxLayout(orientation='horizontal', spacing="10dp", size_hint_y=None, height="50dp")
        btn_reset = MDButton(MDButtonText(text="Reset Default"), style="text", on_release=lambda x: self.reset_to_defaults())
        btn_apply = MDButton(MDButtonText(text="Apply & Recalculate"), style="elevated", on_release=lambda x: self.apply_new_settings())

        btn_box.add_widget(btn_reset)
        btn_box.add_widget(btn_apply)
        list_view.add_widget(btn_box)

    def create_text_field(self, hint, val):
        list_view = self.root.ids.main_container_list
        tf = MDTextField(mode="outlined", text=val, size_hint_y=None, height="55dp")
        tf.add_widget(MDTextFieldHintText(text=hint))
        list_view.add_widget(tf)
        return tf

    def reset_to_defaults(self):
        PARAMS.update(DEFAULT_PARAMS)
        self.week_display_limit = 10
        self.month_display_limit = 20
        self.showing_settings = False
        self.root.ids.settings_toggle_icon.icon = "cog"
        self.update_progress(50, "Reset to defaults. Re-calculating...")
        threading.Thread(target=self.recalculate_background, daemon=True).start()

    def apply_new_settings(self):
        try:
            lookback = int(self.tf_lookback.text)
            sma_period = int(self.tf_sma.text)

            if not (5 <= lookback <= 150):
                self.set_status("Lookback must be between 5 and 150.")
                return
            if not (0 <= sma_period <= 300):
                self.set_status("SMA Period must be between 0 and 300.")
                return

            PARAMS['lookback'] = lookback
            PARAMS['vol_mult'] = float(self.tf_vol.text)
            PARAMS['deliv_mult'] = float(self.tf_deliv.text)
            PARAMS['turnover_min'] = float(self.tf_turnover.text)
            PARAMS['sma_period'] = sma_period
            PARAMS['init_stop_pct'] = float(self.tf_init_stop.text) / 100.0
            PARAMS['tight_trail_pct'] = float(self.tf_trail.text) / 100.0

            self.week_display_limit = 10
            self.month_display_limit = 20
            self.showing_settings = False
            self.root.ids.settings_toggle_icon.icon = "cog"
            self.update_progress(50, "Re-calculating with new parameters...")
            threading.Thread(target=self.recalculate_background, daemon=True).start()
        except ValueError:
            self.set_status("Invalid input values. Check numbers.")

    def recalculate_background(self):
        try:
            if self.raw_data_cache:
                self.processed_data_cache = self.precalculate_indicators(self.raw_data_cache)
                Clock.schedule_once(lambda dt: self.update_progress(100, "Dashboard updated successfully."))
                Clock.schedule_once(lambda dt: self.refresh_current_view())
        except Exception as e:
            print(f"Recalc Error: {e}")

    def calculate_trade_metrics(self, entry_price, exit_price):
        gross_pnl = exit_price - entry_price
        gross_pct = (gross_pnl / entry_price) * 100
        
        buy_val = entry_price
        sell_val = exit_price
        
        stt = 0.001 * (buy_val + sell_val)
        exchange_txn = 0.0000325 * (buy_val + sell_val)
        gst = 0.18 * exchange_txn
        sebi = 0.000001 * (buy_val + sell_val)
        stamp_duty = 0.00015 * buy_val
        
        total_charges = stt + exchange_txn + gst + sebi + stamp_duty
        net_pnl = gross_pnl - total_charges
        net_pct = (net_pnl / entry_price) * 100
        
        return gross_pct, net_pnl, net_pct

    def evaluate_trade_outcome(self, symbol, entry_date, entry_price):
        sym_rows = [r for r in self.processed_data_cache if r['SYMBOL'] == symbol and r['DATE'] >= entry_date]
        sym_rows.sort(key=lambda x: x['DATE'])
        if not sym_rows:
            gross_pct, net_pnl, net_pct = self.calculate_trade_metrics(entry_price, entry_price)
            return "Active", entry_price, gross_pct, net_pnl, net_pct

        peak_price = entry_price
        init_stop_pct = PARAMS['init_stop_pct']
        tight_trail_pct = PARAMS['tight_trail_pct']

        for row in sym_rows:
            d = row['DATE']
            if d == entry_date:
                if row['HIGH'] > peak_price:
                    peak_price = row['HIGH']
                continue

            current_low = row['LOW']
            current_high = row['HIGH']
            current_close = row['CLOSE']

            if current_high > peak_price:
                peak_price = current_high

            if peak_price > entry_price:
                raw_trail_sl = peak_price * (1.0 - tight_trail_pct)
                sl_price = max(entry_price, raw_trail_sl)
            else:
                sl_price = entry_price * (1.0 - init_stop_pct)

            if current_low <= sl_price or current_close < sl_price:
                gross_pct, net_pnl, net_pct = self.calculate_trade_metrics(entry_price, sl_price)
                return "Stop Hit", sl_price, gross_pct, net_pnl, net_pct

        latest_row = sym_rows[-1]
        exit_price = latest_row['CLOSE']
        gross_pct, net_pnl, net_pct = self.calculate_trade_metrics(entry_price, exit_price)
        return "Current Price (Active)", exit_price, gross_pct, net_pnl, net_pct

    def save_to_portfolio_action(self, symbol, entry_date, entry_price):
        date_str = entry_date.strftime('%Y-%m-%d')
        success = add_to_portfolio(symbol, date_str, entry_price)
        msg = f"Added {symbol} to portfolio!" if success else f"{symbol} already in portfolio."
        self.set_status(msg)

    def remove_from_portfolio_action(self, trade_id):
        remove_from_portfolio(trade_id)
        self.render_portfolio_view()

    def copy_signals_to_clipboard(self):
        if not self.available_dates:
            return
        latest_date = self.available_dates[-1]
        current_signals = [r for r in self.processed_data_cache if r['DATE'] == latest_date and r['Signal']]
        current_signals.sort(key=lambda x: x['Signal_Score'], reverse=True)

        if not current_signals:
            self.set_status("No signals available to copy.")
            return

        text_lines = [f"QuantPulse - {latest_date.strftime('%Y-%m-%d')}\n"]
        for idx, row in enumerate(current_signals, 1):
            symbol = row['SYMBOL']
            entry = row['OPEN'] if row['OPEN'] and row['OPEN'] > 0 else row['CLOSE']
            sl = entry * (1.0 - PARAMS['init_stop_pct'])
            text_lines.append(f"{idx}. {symbol} | Entry: ₹{entry:.2f} | SL: ₹{sl:.2f} | Score: {row['Signal_Score']:.2f}")

        Clipboard.copy("\n".join(text_lines))
        self.set_status("Copied all daily signals to clipboard!")

    def copy_single_signal_to_clipboard(self, symbol, entry, sl, score):
        text = f"QuantPulse Trade: {symbol} | Entry: ₹{entry:.2f} | SL: ₹{sl:.2f} | Score: {score:.2f}"
        Clipboard.copy(text)
        self.set_status(f"Copied signal for {symbol}!")

    def load_more_week(self):
        self.week_display_limit += 10
        self.render_full_dashboard()

    def load_more_month(self):
        self.month_display_limit += 10
        self.render_full_dashboard()

    def render_portfolio_view(self):
        self.set_status("Viewing saved virtual portfolio.")
        list_view = self.root.ids.main_container_list
        list_view.clear_widgets()

        self.add_section_header("Virtual Paper Trading Portfolio", "briefcase-outline")
        trades = get_portfolio_trades()

        if not trades:
            self.add_empty_notice("No saved trades in portfolio. Add picks from Current Day view!")
            return

        for trade_id, symbol, entry_date_str, entry_price, _ in trades:
            entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d').date()
            status, exit_p, gross_pct, net_pnl, net_pct = self.evaluate_trade_outcome(symbol, entry_date, entry_price)

            card = MDCard(
                orientation="vertical",
                padding="14dp",
                spacing="6dp",
                size_hint_y=None,
                height="145dp",
                elevation=2,
                md_bg_color=(0.118, 0.161, 0.231, 1),
                radius=[12, 12, 12, 12]
            )
            card_text = (
                f"[b]{symbol}[/b] (Added: {entry_date_str})\n"
                f"Entry: ₹{entry_price:.2f}  |  Current/Exit: ₹{exit_p:.2f}\n"
                f"Status: {status} ([color={'#10B981' if gross_pct >= 0 else '#EF4444'}]{gross_pct:+.2f}%[/color])\n"
                f"Net P&L: [color={'#10B981' if net_pnl >= 0 else '#EF4444'}]₹{net_pnl:+.2f} ({net_pct:+.2f}%)[/color]"
            )
            card.add_widget(MDLabel(text=card_text, markup=True, font_style="Body", role="medium", size_hint_y=None, height="85dp"))
            
            btn = MDButton(MDButtonText(text="Remove from Portfolio"), style="text", on_release=lambda x, tid=trade_id: self.remove_from_portfolio_action(tid))
            card.add_widget(btn)
            list_view.add_widget(card)

    def render_full_dashboard(self):
        list_view = self.root.ids.main_container_list
        list_view.clear_widgets()

        if not self.available_dates:
            return

        latest_date = self.available_dates[-1]

        latest_market = [r for r in self.processed_data_cache if r['DATE'] == latest_date]
        total_stocks = len(latest_market)
        sma_period = PARAMS['sma_period']
        
        if sma_period > 0:
            above_sma = sum(1 for r in latest_market if r['SMA'] > 0 and r['CLOSE'] > r['SMA'])
            breadth_pct = (above_sma / total_stocks) * 100 if total_stocks > 0 else 0.0
        else:
            breadth_pct = 0.0

        current_signals = [r for r in latest_market if r['Signal']]
        signal_count = len(current_signals)
        avg_score = sum(r['Signal_Score'] for r in current_signals) / signal_count if signal_count > 0 else 0.0

        summary_card = MDCard(
            orientation="vertical",
            padding="14dp",
            spacing="8dp",
            size_hint_y=None,
            height="125dp",
            elevation=3,
            radius=[12, 12, 12, 12],
            md_bg_color=(0.118, 0.161, 0.231, 1)
        )
        
        card_header_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height="30dp", spacing="8dp")
        card_header_box.add_widget(MDIcon(icon="chart-bar", theme_text_color="Custom", text_color=(0.22, 0.74, 0.97, 1), size_hint_x=None, width="24dp"))
        card_header_box.add_widget(MDLabel(text=f"[b]Market Sentiment ({latest_date.strftime('%Y-%m-%d')})[/b]", markup=True, font_style="Title", role="medium", theme_text_color="Primary"))
        summary_card.add_widget(card_header_box)

        summary_text = (
            f"• Market Breadth (> {sma_period} SMA): [b]{breadth_pct:.1f}%[/b] of stocks\n"
            f"• Breakouts Triggered: [b]{signal_count}[/b] symbols\n"
            f"• Avg Conviction Score: [b]{avg_score:.2f}[/b]"
        )
        summary_card.add_widget(MDLabel(text=summary_text, markup=True, font_style="Body", role="medium", size_hint_y=None, height="65dp"))
        list_view.add_widget(summary_card)

        # 1. CURRENT DAY SECTION
        header_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height="45dp", spacing="10dp")
        title_box = MDBoxLayout(orientation='horizontal', spacing="10dp", size_hint_x=0.7)
        title_box.add_widget(MDIcon(icon="crosshairs-gps", theme_text_color="Custom", text_color=(0.22, 0.74, 0.97, 1), size_hint_x=None, width="24dp"))
        title_box.add_widget(MDLabel(text="[b]Current Day Recommendations[/b]", markup=True, font_style="Title", role="large", theme_text_color="Primary"))
        
        header_box.add_widget(title_box)
        copy_btn = MDButton(MDButtonText(text="Copy All"), style="text", on_release=lambda x: self.copy_signals_to_clipboard())
        header_box.add_widget(copy_btn)
        list_view.add_widget(header_box)

        current_signals.sort(key=lambda x: x['Signal_Score'], reverse=True)

        if not current_signals:
            self.add_empty_notice("No recommendations for current day.")
        else:
            for idx, row in enumerate(current_signals, 1):
                symbol = row['SYMBOL']
                entry_price = row['OPEN'] if row['OPEN'] and row['OPEN'] > 0 else row['CLOSE']
                sl_price = entry_price * (1.0 - PARAMS['init_stop_pct'])
                score = row['Signal_Score']
                
                card = MDCard(
                    orientation="vertical",
                    padding="14dp",
                    spacing="6dp",
                    size_hint_y=None,
                    height="145dp",
                    elevation=2,
                    radius=[12, 12, 12, 12],
                    md_bg_color=(0.118, 0.161, 0.231, 1)
                )
                card_text = (
                    f"[b]{idx}. {symbol}[/b]\n"
                    f"Entry: ₹{entry_price:.2f}  |  Stop-Loss: ₹{sl_price:.2f}\n"
                    f"Conviction Score: {score:.2f}"
                )
                card.add_widget(MDLabel(text=card_text, markup=True, font_style="Body", role="medium", size_hint_y=None, height="65dp"))
                
                btn_box = MDBoxLayout(orientation='horizontal', spacing="8dp", size_hint_y=None, height="40dp")
                btn_portfolio = MDButton(
                    MDButtonText(text="Add to Portfolio"), 
                    style="elevated", 
                    size_hint_x=0.5, 
                    on_release=lambda x, s=symbol, d=latest_date, p=entry_price: self.save_to_portfolio_action(s, d, p)
                )
                btn_copy = MDButton(
                    MDButtonText(text="Copy Signal"), 
                    style="text", 
                    size_hint_x=0.5, 
                    on_release=lambda x, s=symbol, e=entry_price, sl=sl_price, sc=score: self.copy_single_signal_to_clipboard(s, e, sl, sc)
                )
                btn_box.add_widget(btn_portfolio)
                btn_box.add_widget(btn_copy)
                
                card.add_widget(btn_box)
                list_view.add_widget(card)

        # 2. PAST WEEK SECTION
        self.add_section_header("Past Week Recommendations", "calendar-week")
        past_week_dates = self.available_dates[-6:-1] if len(self.available_dates) >= 6 else self.available_dates[:-1]
        
        week_signals = [r for r in self.processed_data_cache if r['DATE'] in past_week_dates and r['Signal']]
        week_signals.sort(key=lambda x: x['DATE'], reverse=True)

        if not week_signals:
            self.add_empty_notice("No past week recommendations found.")
        else:
            visible_week = week_signals[:self.week_display_limit]
            for row in visible_week:
                entry_price = row['OPEN'] if row['OPEN'] and row['OPEN'] > 0 else row['CLOSE']
                status, exit_p, gross_pct, net_pnl, net_pct = self.evaluate_trade_outcome(row['SYMBOL'], row['DATE'], entry_price)

                card = MDCard(
                    orientation="vertical",
                    padding="14dp",
                    spacing="6dp",
                    size_hint_y=None,
                    height="125dp",
                    elevation=2,
                    radius=[12, 12, 12, 12],
                    md_bg_color=(0.118, 0.161, 0.231, 1)
                )
                card_text = (
                    f"[b]{row['SYMBOL']}[/b] ({row['DATE'].strftime('%Y-%m-%d')}) | Score: {row['Signal_Score']:.2f}\n"
                    f"Entry: ₹{entry_price:.2f}  |  Exit: ₹{exit_p:.2f}\n"
                    f"Status: {status} ([color={'#10B981' if gross_pct >= 0 else '#EF4444'}]{gross_pct:+.2f}%[/color])\n"
                    f"Net P&L: [color={'#10B981' if net_pnl >= 0 else '#EF4444'}]₹{net_pnl:+.2f} ({net_pct:+.2f}%)[/color]"
                )
                card.add_widget(MDLabel(text=card_text, markup=True, font_style="Body", role="medium", size_hint_y=None, height="95dp"))
                list_view.add_widget(card)

            if len(week_signals) > self.week_display_limit:
                list_view.add_widget(MDButton(MDButtonText(text="Load More (Past Week) ▼"), style="text", on_release=lambda x: self.load_more_week()))

        # 3. PAST MONTH SECTION
        self.add_section_header("Past Month Recommendations", "calendar-month")
        past_month_dates = self.available_dates[-26:-6] if len(self.available_dates) >= 26 else self.available_dates[:-6]

        month_signals = [r for r in self.processed_data_cache if r['DATE'] in past_month_dates and r['Signal']]
        month_signals.sort(key=lambda x: x['DATE'], reverse=True)

        if not month_signals:
            self.add_empty_notice("No past month recommendations found.")
        else:
            visible_month = month_signals[:self.month_display_limit]
            for row in visible_month:
                entry_price = row['OPEN'] if row['OPEN'] and row['OPEN'] > 0 else row['CLOSE']
                status, exit_p, gross_pct, net_pnl, net_pct = self.evaluate_trade_outcome(row['SYMBOL'], row['DATE'], entry_price)

                card = MDCard(
                    orientation="vertical",
                    padding="14dp",
                    spacing="6dp",
                    size_hint_y=None,
                    height="125dp",
                    elevation=2,
                    radius=[12, 12, 12, 12],
                    md_bg_color=(0.118, 0.161, 0.231, 1)
                )
                card_text = (
                    f"[b]{row['SYMBOL']}[/b] ({row['DATE'].strftime('%Y-%m-%d')}) | Score: {row['Signal_Score']:.2f}\n"
                    f"Entry: ₹{entry_price:.2f}  |  Exit: ₹{exit_p:.2f}\n"
                    f"Status: {status} ([color={'#10B981' if gross_pct >= 0 else '#EF4444'}]{gross_pct:+.2f}%[/color])\n"
                    f"Net P&L: [color={'#10B981' if net_pnl >= 0 else '#EF4444'}]₹{net_pnl:+.2f} ({net_pct:+.2f}%)[/color]"
                )
                card.add_widget(MDLabel(text=card_text, markup=True, font_style="Body", role="medium", size_hint_y=None, height="95dp"))
                list_view.add_widget(card)

            if len(month_signals) > self.month_display_limit:
                list_view.add_widget(MDButton(MDButtonText(text="Load More (Past Month) ▼"), style="text", on_release=lambda x: self.load_more_month()))

    def add_section_header(self, title_text, icon_name="folder"):
        list_view = self.root.ids.main_container_list
        header_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height="40dp", spacing="10dp")
        header_box.add_widget(MDIcon(icon=icon_name, theme_text_color="Custom", text_color=(0.22, 0.74, 0.97, 1), size_hint_x=None, width="24dp"))
        header_box.add_widget(MDLabel(text=f"[b]{title_text}[/b]", markup=True, font_style="Title", role="large", theme_text_color="Primary"))
        list_view.add_widget(header_box)

    def add_empty_notice(self, notice_text):
        list_view = self.root.ids.main_container_list
        notice_label = MDLabel(text=notice_text, font_style="Body", role="medium", size_hint_y=None, height="35dp", theme_text_color="Hint")
        list_view.add_widget(notice_label)

    def update_footer_range(self, min_date, max_date):
        self.root.ids.footer_date_label.text = f"Dataset Range: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}"

    def finalize_ui_error(self, error_msg):
        self.update_progress(100, error_msg)

if __name__ == "__main__":
    AlgorithmTradesApp().run()
