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

def inspect_olx_page(url):
    """ Отримує назву українською, долари (або грн), кімнати та площу з OLX """
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            text = res.text
            
            # Заголовок
            title_match = re.search(r'<h4[^>]*>(.*?)</h4>', text, re.DOTALL)
            if not title_match:
                title_match = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.DOTALL)
            
            title = title_match.group(1).strip() if title_match else "Оголошення OLX"
            title = re.sub(r'<[^>]+>', '', title).replace('- OLX.ua', '').strip()

            # Спочатку шукаємо ціну в ДОЛАРАХ ($)
            price_match = re.search(r'(\$[\s\d\xa0]+|[\d\s\xa0]+\s*\$)', text)
            if not price_match:
                # Якщо доларів немає — шукаємо в ГРИВНЯХ
                price_match = re.search(r'([\d\s\xa0]{2,}(?:\.\d{2})?\s*(?:грн|\u20b4))', text)
            
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Не вказано"

            # Кімнати та площа
            rooms_match = re.search(r'Кількість кімнат:\s*([^\n<]+)', text, re.IGNORECASE)
            area_match = re.search(r'Загальна площа:\s*([^\n<]+)', text, re.IGNORECASE)
            
            rooms = rooms_match.group(1).strip() if rooms_match else ""
            area = area_match.group(1).strip() if area_match else ""

            details = []
            if rooms: details.append(f"🚪 {rooms}")
            if area: details.append(f"📐 {area}")
            extra_info = " | ".join(details)

            return title, price, extra_info
    except Exception as e:
        log(f"⚠️ Помилка витягування OLX сторінки {url}: {e}")
    return "Оголошення OLX", "Не вказано", ""

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
                    return True, "Не вказано"

            # Шукаємо ціну ($ або грн)
            price_match = re.search(r'(\$[\s\d\xa0]+|[\d\s\xa0]+\s*\$|[\d\s\xa0]{2,}\s*(?:грн|\u20b4))', text)
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Не вказано"
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

                found.append({
                    "id": f"olx_{ad_id}",
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
                    "source": label,
                    "extra": ""
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
            send_telegram(f"✅ <b>[ТЕСТ]</b> Базу оновлено! Знайдено {len(all_items)} чистих об'єктів.")
        return

    new_count = 0
    for item in all_items:
        ad_id = item["id"]
        if ad_id in seen_ads:
            continue

        # Збір детальної інфи для OLX
        if ad_id.startswith("olx_"):
            title, price, extra_info = inspect_olx_page(item["url"])
            item["title"] = title
            item["price"] = price
            item["extra"] = extra_info

        # Перевірка та збір інфи для DIM.RIA
        elif ad_id.startswith("dimria_"):
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

        extra_line = f"\nℹ️ <b>Деталі:</b> {item['extra']}" if item.get('extra') else ""
        msg = (
            f"🎯 <b>{item['source']}</b>\n"
            f"📌 <b>{item['title']}</b>\n"
            f"💰 <b>Ціна:</b> {item['price']}"
            f"{extra_line}\n"
            f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
        )
        send_telegram(msg)

    if force_test and new_count == 0:
        send_telegram(f"ℹ️ <b>[ТЕСТ]</b> Бот v6.1 готовий! Долари та солов'їна мова активовані.")

    log(f"🏁 Завершено. Нових надіслано: {new_count}")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот v6.1 активовано!".encode("utf-8"))

        t = threading.Thread(target=run_hunter, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    log(f"🚀 Запуск сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
