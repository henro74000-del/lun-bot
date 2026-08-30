import os
import requests
import cloudscraper
import threading
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

OLX_SOURCES = [
    ("OLX Оренда Квар.", "https://www.olx.ua/uk/nedvizhimost/kvartiry/dolgosrochnaya-arenda-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Продаж Квар.", "https://www.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Оренда Буд.", "https://www.olx.ua/uk/nedvizhimost/doma/arenda-domov/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Продаж Буд.", "https://www.olx.ua/uk/nedvizhimost/doma/prodazha-domov/khmelnitskiy/?search%5Bprivate_business%5D=private")
]

DIMRIA_SOURCES = [
    ("DIM.RIA Оренда Квар.", "https://dom.ria.com/uk/orenda-kvartyr/khmelnytskyi/?without_realtor=1"),
    ("DIM.RIA Продаж Квар.", "https://dom.ria.com/uk/prodazh-kvartyr/khmelnytskyi/?without_realtor=1")
]

SEEN_ADS = set()
IS_WARMED_UP = False

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
            # Шукаємо картки оголошень на OLX
            cards = soup.find_all("div", {"data-testid": "l-card"})
            
            for card in cards:
                a = card.find("a", href=True)
                if not a:
                    continue
                href = a["href"]
                clean_url = href if href.startswith("http") else f"https://www.olx.ua{href}"
                ad_id = clean_url.split(".html")[0].split("-")[-1]

                # Заголовок (часто містить кількість кімнат та район)
                title_el = card.find("h6") or card.find("h4")
                title = title_el.get_text(strip=True) if title_el else label

                # Ціна
                price_el = card.find("p", {"data-testid": "ad-price"})
                price = price_el.get_text(strip=True) if price_el else "Ціна не вказана"

                found.append({
                    "id": f"olx_{ad_id}",
                    "title": title,
                    "price": price,
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
            # Шукаємо посилання на об'єкти
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/realty-" in href or "/uk/realty-" in href:
                    clean_url = href if href.startswith("http") else f"https://dom.ria.com{href}"
                    ad_id = clean_url.split("-")[-1].replace(".html", "")
                    title = a.get_text(strip=True) or label
                    
                    # Шукаємо ціну поруч у картці
                    card = a.find_parent("section") or a.find_parent("div")
                    price = "Ціна в оголошенні"
                    if card:
                        price_el = card.find("b", class_="size22") or card.find("span", class_="price")
                        if price_el:
                            price = price_el.get_text(strip=True)

                    if len(title) > 3:
                        found.append({
                            "id": f"dimria_{ad_id}",
                            "title": title,
                            "price": price,
                            "url": clean_url,
                            "source": f"{label} (Власник)"
                        })
        except Exception as e:
            log(f"❌ Помилка DIM.RIA ({label}): {e}")
    return found

def run_hunter(force_test=False):
    global IS_WARMED_UP
    log("🔎 Початок сканування...")
    all_items = scan_olx() + scan_dimria()
    log(f"📊 Всього проскановано об'єктів: {len(all_items)}")

    if not IS_WARMED_UP:
        for item in all_items:
            SEEN_ADS.add(item["id"])
        IS_WARMED_UP = True
        log(f"🔥 Прогрів завершено! Запам'ятали {len(SEEN_ADS)} оголошень з цінами.")
        if force_test:
            send_telegram(f"✅ <b>[ТЕСТ УСПІШНИЙ]</b>\nБот тепер витягує <b>ЦІНУ</b> та <b>ОПИС</b>!\nВсього знайдено: {len(all_items)} об'єктів.")
        return

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
            f"💵 <b>Ціна: {item['price']}</b>\n"
            f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
        )
        send_telegram(msg)

    log(f"🏁 Завершено. Надіслано НОВИХ: {new_count}")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот навчився читати ціни!".encode("utf-8"))

        t = threading.Thread(target=run_hunter, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    log(f"🚀 Запуск сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
