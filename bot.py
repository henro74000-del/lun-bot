import os
import requests
import threading
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))

# OLX & DIM.RIA (Власники)
SOURCES = [
    ("OLX Оренда Квар.", "https://www.olx.ua/uk/nedvizhimost/kvartiry/dolgosrochnaya-arenda-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private", "olx"),
    ("OLX Продаж Квар.", "https://www.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private", "olx"),
    ("DIM.RIA Оренда", "https://dom.ria.com/uk/orenda-kvartyr/khmelnitskiy/?without_realtor=1", "dimria"),
    ("DIM.RIA Продаж", "https://dom.ria.com/uk/prodazh-kvartyr/khmelnitskiy/?without_realtor=1", "dimria")
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"
}

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
        log(f"📬 Telegram API: code={res.status_code}")
        return res.status_code == 200
    except Exception as e:
        log(f"❌ Помилка Telegram: {e}")
        return False

def scan_site(label, url, site_type):
    found = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        log(f"🌐 [{label}] Відповідь сайту: HTTP {res.status_code}")
        if res.status_code != 200:
            return found

        soup = BeautifulSoup(res.text, "html.parser")

        if site_type == "olx":
            # Пошук усіх карт оголошень на OLX
            cards = soup.find_all("div", data_testid="l-card") or soup.find_all("a", href=True)
            for card in cards:
                a_tag = card if card.name == "a" else card.find("a", href=True)
                if not a_tag:
                    continue
                href = a_tag.get("href", "")
                if "/d/uk/obyavlenie/" in href or "/d/obyavlenie/" in href or "olx.ua/d/" in href:
                    clean_url = href if href.startswith("http") else f"https://www.olx.ua{href}"
                    ad_id = clean_url.split(".html")[0].split("-")[-1]
                    title_elem = card.find("h6") or card.find("h4")
                    title = title_elem.get_text(strip=True) if title_elem else label
                    found.append({"id": f"olx_{ad_id}", "title": title, "url": clean_url, "source": "OLX"})

        elif site_type == "dimria":
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/realty-" in href:
                    clean_url = href if href.startswith("http") else f"https://dom.ria.com{href}"
                    ad_id = clean_url.split("-")[-1].replace(".html", "")
                    title = a.get_text(strip=True) or label
                    found.append({"id": f"dimria_{ad_id}", "title": title, "url": clean_url, "source": "DIM.RIA"})

    except Exception as e:
        log(f"❌ Помилка під час сканування [{label}]: {e}")

    log(f"🔍 [{label}] Знайдено сирих посилань: {len(found)}")
    return found

def run_hunter(force_test=False):
    if force_test:
        log("🧪 Тестовий виклик...")
        send_telegram("🚀 <b>[ТЕСТ ДВОСТВОЛКИ]</b> Бот працює! Скануємо OLX + DIM.RIA...")

    log("🔎 Запуск перевірки сайтів...")
    all_items = []
    for label, url, site_type in SOURCES:
        all_items.extend(scan_site(label, url, site_type))

    log(f"📊 Всього унікальних об'єктів: {len(all_items)}")

    new_count = 0
    for item in all_items:
        ad_id = item["id"]
        if ad_id in SEEN_ADS:
            continue
        
        SEEN_ADS.add(ad_id)
        new_count += 1

        msg = (
            f"🎯 <b>ВЛАСНИК [{item['source']}]</b>\n"
            f"📌 <b>{item['title']}</b>\n"
            f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
        )

        if force_test and new_count == 1:
            send_telegram(msg)
        elif not force_test:
            send_telegram(msg)

    log(f"🏁 Сканування завершено. Надіслано нових: {new_count}")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Сканер OLX + DIM.RIA запущено!".encode("utf-8"))

        t = threading.Thread(target=run_hunter, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    log(f"🚀 Запуск веб-сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
