import os
import re
import requests
import cloudscraper
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))
DB_FILE = "seen_ads.txt"

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

OLX_SOURCES = [
    ("OLX Оренда", "https://www.olx.ua/uk/nedvizhimost/kvartiry/dolgosrochnaya-arenda-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Продаж", "https://www.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private")
]

DIMRIA_SOURCES = [
    ("DIM.RIA Оренда", "https://dom.ria.com/uk/arenda-kvartir/khmelnytskyi/?from_owner=1&without_realtor=1"),
    ("DIM.RIA Продаж", "https://dom.ria.com/uk/prodazha-kvartir/khmelnytskyi/?from_owner=1&without_realtor=1")
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

def inspect_dimria_page(url):
    """ Перевіряє рієлторів ТА шукає ціну на сторінці DIM.RIA """
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            text = res.text
            text_lower = text.lower()
            bad_phrases = [
                "перевірений рієлтор", "перевірене агентство", 
                "архітек", "architek", "основа", "osnova",
                "комісія", "агентство нерухомості", "рієлтор"
            ]
            for bad in bad_phrases:
                if bad in text_lower:
                    return True, None

            # Витягаємо ціну
            price_match = re.search(r'([\d\s]{2,}\s*(?:\$|грн|\u20b4))', text)
            price = price_match.group(1).strip() if price_match else "Не вказано"
            return False, price
    except Exception as e:
        log(f"⚠️ Помилка перевірки сторінки {url}: {e}")
    return False, "Не вказано"

def scan_olx():
    found = []
    for label, url in OLX_SOURCES:
        try:
            res = scraper.get(url, timeout=15)
            log(f"🌐 [OLX] {label} -> HTTP {res.status_code}")
            if res.status_code != 200:
                continue

            clean_text = res.text.replace('\\/', '/').replace('\\u002F', '/')
            raw_links = re.findall(r'/(?:uk/)?d/[^\s"\'\\<>#]+?\.html', clean_text)

            for href in set(raw_links):
                clean_url = f"https://www.olx.ua{href}"
                ad_id = clean_url.split(".html")[0].split("-")[-1]
                slug = clean_url.split("/")[-1].replace(".html", "").replace(f"-{ad_id}", "")
                title = slug.replace("-", " ").capitalize()

                # Шукаємо ціну поруч із посиланням в HTML
                pos = clean_text.find(href)
                price = "Не вказано"
                if pos != -1:
                    snippet = clean_text[max(0, pos-200):min(len(clean_text), pos+600)]
                    p_match = re.search(r'(\d[\d\s]*\s*(?:грн|\$))', snippet, re.IGNORECASE)
                    if p_match:
                        price = p_match.group(1).strip()

                found.append({
                    "id": f"olx_{ad_id}",
                    "title": title if len(title) > 3 else label,
                    "url": clean_url,
                    "price": price,
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

            clean_text = res.text.replace('\\/', '/').replace('\\u002F', '/')
            raw_links = re.findall(r'/(?:uk/)?realty-[^\s"\'\\<>#]+?\.html', clean_text)

            for href in set(raw_links):
                href_formatted = href if href.startswith("/uk/") else f"/uk{href}"
                clean_url = f"https://dom.ria.com{href_formatted}"
                ad_id = clean_url.split("-")[-1].replace(".html", "")

                found.append({
                    "id": f"dimria_{ad_id}",
                    "title": label,
                    "url": clean_url,
                    "price": "Не вказано",
                    "source": label
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
            send_telegram(f"✅ <b>[ТЕСТ]</b> Базу оновлено! Знайдено {len(all_items)} чистих об'єктів з цінниками.")
        return

    new_count = 0
    for item in all_items:
        ad_id = item["id"]
        if ad_id in seen_ads:
            continue

        # Перевірка та збір ціни для DIM.RIA
        if ad_id.startswith("dimria_"):
            is_realtor, price = inspect_dimria_page(item["url"])
            if is_realtor:
                log(f"🚫 [БАН] Знайдено замаскованого рієлтора: {item['url']}")
                save_seen_ad(ad_id)
                seen_ads.add(ad_id)
                continue
            item["price"] = price

        save_seen_ad(ad_id)
        seen_ads.add(ad_id)
        new_count += 1

        msg = (
            f"🎯 <b>{item['source']}</b>\n"
            f"📌 <b>{item['title']}</b>\n"
            f"💰 <b>Ціна:</b> {item['price']}\n"
            f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
        )
        send_telegram(msg)

    if force_test and new_count == 0:
        send_telegram(f"ℹ️ <b>[ТЕСТ]</b> Детектор цін та рієлторів у порядку! Усі {len(all_items)} об'єктів перевірено.")

    log(f"🏁 Завершено. Нових надіслано: {new_count}")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Ціни додано в сповіщення!".encode("utf-8"))

        t = threading.Thread(target=run_hunter, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    log(f"🚀 Запуск сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
