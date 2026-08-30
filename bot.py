import os
import requests
import threading
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))

# 1. OLX (Суто приватні особи)
OLX_URLS = [
    ("OLX Оренда Квартир", "https://www.olx.ua/uk/nedvizhimost/kvartiry/dolgosrochnaya-arenda-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Продаж Квартир", "https://www.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Оренда Будинків", "https://www.olx.ua/uk/nedvizhimost/doma/arenda-domov/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Продаж Будинків", "https://www.olx.ua/uk/nedvizhimost/doma/prodazha-domov/khmelnitskiy/?search%5Bprivate_business%5D=private")
]

# 2. DIM.RIA (Суто від власників / без ріелторів)
DIMRIA_URLS = [
    ("DIM.RIA Оренда Квартир", "https://dom.ria.com/uk/orenda-kvartyr/khmelnitskiy/?without_realtor=1"),
    ("DIM.RIA Продаж Квартир", "https://dom.ria.com/uk/prodazh-kvartyr/khmelnitskiy/?without_realtor=1"),
    ("DIM.RIA Оренда Будинків", "https://dom.ria.com/uk/orenda-budynkiv/khmelnitskiy/?without_realtor=1"),
    ("DIM.RIA Продаж Будинків", "https://dom.ria.com/uk/prodazh-budynkiv/khmelnitskiy/?without_realtor=1")
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "uk-UA,uk;q=0.9"
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
        return res.status_code == 200
    except Exception as e:
        log(f"❌ Помилка Telegram: {e}")
        return False

def scan_olx(force_test=False):
    found = []
    for label, url in OLX_URLS:
        try:
            res = requests.get(url, headers=HEADERS, timeout=12)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            cards = soup.find_all("div", data_testid="l-card") or soup.find_all("a", href=True)
            for card in cards:
                a_tag = card if card.name == "a" else card.find("a", href=True)
                if not a_tag:
                    continue
                href = a_tag["href"]
                if "/d/uk/obyavlenie/" in href or "/d/obyavlenie/" in href:
                    clean_url = href if href.startswith("http") else f"https://www.olx.ua{href}"
                    ad_id = clean_url.split(".html")[0].split("-")[-1]
                    title_elem = card.find("h6") or card.find("h4")
                    title = title_elem.get_text(strip=True) if title_elem else label
                    price_elem = card.find("p", data_testid="ad-price")
                    price = price_elem.get_text(strip=True) if price_elem else "Дивись на OLX"
                    found.append({"id": f"olx_{ad_id}", "title": title, "price": price, "url": clean_url, "source": "OLX"})
        except Exception as e:
            log(f"Помилка OLX ({label}): {e}")
    return found

def scan_dimria(force_test=False):
    found = []
    for label, url in DIMRIA_URLS:
        try:
            res = requests.get(url, headers=HEADERS, timeout=12)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            links = soup.find_all("a", href=True)
            for a in links:
                href = a["href"]
                if "/uk/realty-" in href or "/realty-" in href:
                    clean_url = href if href.startswith("http") else f"https://dom.ria.com{href}"
                    ad_id = clean_url.split("-")[-1].replace(".html", "")
                    title = a.get_text(strip=True) or label
                    found.append({"id": f"dimria_{ad_id}", "title": title, "price": "Власник (DIM.RIA)", "url": clean_url, "source": "DIM.RIA"})
        except Exception as e:
            log(f"Помилка DIM.RIA ({label}): {e}")
    return found

def run_hunter(force_test=False):
    if force_test:
        send_telegram("🚀 <b>[ТЕСТ ДВОСТВОЛКИ]</b> Бот заряджений на OLX + DIM.RIA (тільки ВЛАСНИКИ)!")

    log("🔎 Запуск сканування OLX + DIM.RIA...")
    all_items = scan_olx(force_test) + scan_dimria(force_test)
    log(f"📊 Всього знайдено оголошень від власників: {len(all_items)}")

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
            f"💵 {item['price']}\n"
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
        self.wfile.write("Двостволка OLX + DIM.RIA працює!".encode("utf-8"))

        t = threading.Thread(target=run_hunter, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    log(f"🚀 Запуск веб-сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
