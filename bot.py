import os
import requests
import cloudscraper
import threading
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))
DB_FILE = "seen_ads.txt"

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

OLX_SOURCES = [
    ("OLX Оренда Квар.", "https://www.olx.ua/uk/nedvizhimost/kvartiry/dolgosrochnaya-arenda-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Продаж Квар.", "https://www.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private")
]

DIMRIA_SOURCES = [
    ("DIM.RIA Оренда", "https://dom.ria.com/uk/arenda-kvartir/khmelnitskiy/?without_realtor=1"),
    ("DIM.RIA Продаж", "https://dom.ria.com/uk/prodazha-kvartir/khmelnitskiy/?without_realtor=1")
]

def load_seen_ads():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return set(line.strip() for line in f if line.strip())
        except Exception as e:
            print(f"Помилка читання файлу: {e}")
    return set()

def save_seen_ad(ad_id):
    try:
        with open(DB_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ad_id}\n")
    except Exception as e:
        print(f"Помилка запису файлу: {e}")

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
            
            # Шукаємо посилання на оголошення
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if ".html" in href and ("/d/" in href or "obyavlenie" in href or "obyavlenye" in href):
                    clean_url = href if href.startswith("http") else f"https://www.olx.ua{href}"
                    ad_id = clean_url.split(".html")[0].split("-")[-1]
                    title = a.get_text(strip=True)
                    
                    if len(title) > 5 and not title.startswith("http") and "повідомлення" not in title.lower():
                        found.append({
                            "id": f"olx_{ad_id}",
                            "title": title,
                            "url": clean_url,
                            "source": f"{label} (Власник)"
                        })
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
                    
                    if len(title) > 3:
                        found.append({
                            "id": f"dimria_{ad_id}",
                            "title": title,
                            "url": clean_url,
                            "source": f"{label} (Власник)"
                        })
        except Exception as e:
            log(f"❌ Помилка DIM.RIA ({label}): {e}")
    return found

def run_hunter(force_test=False):
    seen_ads = load_seen_ads()
    first_run = (len(seen_ads) == 0)

    log(f"🔎 Сканування... В базі вже є {len(seen_ads)} збережених об'єктів.")
    all_items = scan_olx() + scan_dimria()
    log(f"📊 Знайдено на сайтах зараз: {len(all_items)}")

    if first_run:
        for item in all_items:
            save_seen_ad(item["id"])
        log(f"🔥 Базу вперше створено! Записано {len(all_items)} шт.")
        if force_test:
            send_telegram(f"✅ <b>[ТЕСТ]</b> Знайдено {len(all_items)} оголошень! Базу заповнено. Тепер чекаємо нових!")
        return

    new_count = 0
    for item in all_items:
        ad_id = item["id"]
        if ad_id in seen_ads:
            continue

        save_seen_ad(ad_id)
        seen_ads.add(ad_id)
        new_count += 1

        msg = (
            f"🎯 <b>{item['source']}</b>\n"
            f"📌 <b>{item['title']}</b>\n"
            f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
        )
        send_telegram(msg)

    if force_test and new_count == 0:
        send_telegram(f"ℹ️ <b>[ТЕСТ]</b> Знайдено {len(all_items)} актуальних хат. Усі вже в базі, чекаємо нових!")

    log(f"🏁 Завершено. Нових надіслано: {new_count}")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот налаштований і готовий до бою!".encode("utf-8"))

        t = threading.Thread(target=run_hunter, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    log(f"🚀 Запуск сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
