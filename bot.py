import os
import requests
import cloudscraper
import threading
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))

# Спеціальний скрапер для обходу Cloudflare (403)
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

OLX_SOURCES = [
    ("OLX Оренда Квар.", "https://www.olx.ua/uk/nedvizhimost/kvartiry/dolgosrochnaya-arenda-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Продаж Квар.", "https://www.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private")
]

# Точні робочі посилання для DIM.RIA
DIMRIA_SOURCES = [
    ("DIM.RIA Оренда", "https://dom.ria.com/uk/orenda-kvartyr/khmelnytskyi/?without_realtor=1"),
    ("DIM.RIA Продаж", "https://dom.ria.com/uk/prodazh-kvartyr/khmelnytskyi/?without_realtor=1")
]

SEEN_ADS = set()

def log(msg):
    print(msg, flush=True)

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        log("❌ ПОМИЛКА: BOT_TOKEN або CHAT_ID порожні!")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        log(f"❌ Помилка Telegram: {e}")
        return False

def scan_olx():
    found = []
    for label, url in OLX_SOURCES:
        try:
            res = scraper.get(url, timeout=15)
            log(f"🌐 [OLX] {label} -> HTTP {res.status_code}")
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/d/uk/obyavlenie/" in href or "/d/obyavlenie/" in href:
                    clean_url = href if href.startswith("http") else f"https://www.olx.ua{href}"
                    ad_id = clean_url.split(".html")[0].split("-")[-1]
                    title = a.get_text(strip=True) or label
                    if len(title) > 3:
                        found.append({"id": f"olx_{ad_id}", "title": title, "url": clean_url, "source": "OLX (Власник)"})
        except Exception as e:
            log(f"❌ Помилка OLX ({label}): {e}")
    return found

def scan_dimria():
    found = []
    for label, url in DIMRIA_SOURCES:
        try:
            res = scraper.get(url, timeout=15)
            log(f"🌐 [DIM.RIA] {label} -> HTTP {res.status_code}")
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/realty-" in href or "/uk/realty-" in href:
                    clean_url = href if href.startswith("http") else f"https://dom.ria.com{href}"
                    ad_id = clean_url.split("-")[-1].replace(".html", "")
                    title = a.get_text(strip=True) or label
                    found.append({"id": f"dimria_{ad_id}", "title": title, "url": clean_url, "source": "DIM.RIA (Власник)"})
        except Exception as e:
            log(f"❌ Помилка DIM.RIA ({label}): {e}")
    return found

def run_hunter(force_test=False):
    if force_test:
        send_telegram("🚀 <b>[ТЕСТ]</b> Скануємо OLX + DIM.RIA з маскуванням під браузер...")

    log("🔎 Початок сканування...")
    all_items = scan_olx() + scan_dimria()
    log(f"📊 Всього витягнуто об'єктів: {len(all_items)}")

    new_count = 0
    for item in all_items:
        ad_id = item["id"]
        if ad_id in SEEN_ADS:
            continue

        SEEN_ADS.add(ad_id)
        new_count += 1

        msg = (
            f"🎯 <b>{item['source']}</b>\n"
            f"📌 <b>{item['title']}</b>\n"
            f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
        )

        if force_test and new_count == 1:
            send_telegram(msg)
        elif not force_test:
            send_telegram(msg)

    log(f"🏁 Завершено. Нових надсилань: {new_count}")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот оновлено! Cloudscraper підключено.".encode("utf-8"))

        t = threading.Thread(target=run_hunter, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    log(f"🚀 Запуск сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
