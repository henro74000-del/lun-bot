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
    payload = {
        "chat_id": CHAT_ID, 
        "text": text, 
        "parse_mode": "HTML",
        "disable_web_page_preview": False  # Дозволяє Телеграму показувати прев'ю фото!
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        log(f"❌ Помилка Telegram: {e}")
        return False

def extract_photo(text):
    """ Шукає головне фото сторінки у мета-тезі og:image """
    img_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', text, re.IGNORECASE)
    if not img_match:
        img_match = re.search(r'<meta\s+name="og:image"\s+content="([^"]+)"', text, re.IGNORECASE)
    return img_match.group(1) if img_match else None

def inspect_olx_page(url):
    """ Отримує заголовок, ціну, деталі ТА ФОТО з OLX """
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            text = res.text

            # 1. Заголовок
            title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', text, re.IGNORECASE)
            title = title_match.group(1).replace('- OLX.ua', '').replace('OLX.ua', '').strip() if title_match else "Квартира OLX"

            # 2. Фото
            photo_url = extract_photo(text)

            # 3. Очищення від скриптів для ціни
            clean_html = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            clean_html = re.sub(r'<style[^>]*>.*?</style>', '', clean_html, flags=re.DOTALL)

            # 4. Ціна
            price = "Не вказано"
            usd_matches = re.findall(r'(\$\s*[\d\s\xa0]{4,}|[\d\s\xa0]{4,}\s*\$)', clean_html)
            if usd_matches:
                price = usd_matches[0].replace('\xa0', ' ').strip()
            else:
                uah_matches = re.findall(r'([\d\s\xa0]{5,}(?:\.\d{2})?\s*(?:грн|\u20b4))', clean_html)
                if uah_matches:
                    price = uah_matches[0].replace('\xa0', ' ').strip()

            # 5. Кімнати та площа
            rooms_match = re.search(r'Кількість кімнат:\s*([^\n<]+)', text, re.IGNORECASE)
            area_match = re.search(r'Загальна площа:\s*([^\n<]+)', text, re.IGNORECASE)

            rooms = rooms_match.group(1).strip() if rooms_match else ""
            area = area_match.group(1).strip() if area_match else ""

            details = []
            if rooms: details.append(f"🚪 {rooms}")
            if area: details.append(f"📐 {area}")
            extra_info = " | ".join(details)

            return title, price, extra_info, photo_url
    except Exception as e:
        log(f"⚠️ Помилка OLX сторінки {url}: {e}")
    return "Оголошення OLX", "Не вказано", "", None

def inspect_dimria_page(url):
    """ Перевіряє рієлторів, шукає ціну ТА ФОТО на DIM.RIA """
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
                    return True, "Не вказано", None

            photo_url = extract_photo(text)

            clean_html = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            price_match = re.search(r'(\$\s*[\d\s\xa0]{3,}|[\d\s\xa0]{3,}\s*\$|[\d\s\xa0]{4,}\s*(?:грн|\u20b4))', clean_html)
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Не вказано"
            
            return False, price, photo_url
    except Exception as e:
        log(f"⚠️ Помилка DIM.RIA {url}: {e}")
    return False, "Не вказано", None

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
                    "extra": "",
                    "photo": None
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

        # Збір детальної інфи та фото для OLX
        if ad_id.startswith("olx_"):
            title, price, extra_info, photo_url = inspect_olx_page(item["url"])
            item["title"] = title
            item["price"] = price
            item["extra"] = extra_info
            item["photo"] = photo_url

        # Збір детальної інфи та фото для DIM.RIA
        elif ad_id.startswith("dimria_"):
            is_realtor, price, photo_url = inspect_dimria_page(item["url"])
            if is_realtor:
                log(f"🚫 [БАН] Знайдено замаскованого рієлтора: {item['url']}")
                save_seen_ad(ad_id)
                seen_ads.add(ad_id)
                continue
            item["price"] = price
            item["photo"] = photo_url

        save_seen_ad(ad_id)
        seen_ads.add(ad_id)
        new_count += 1

        # Формуємо приховане посилання для фото вгорі
        photo_prefix = f'<a href="{item["photo"]}">&#8203;</a>' if item.get("photo") else ""
        extra_line = f"\nℹ️ <b>Деталі:</b> {item['extra']}" if item.get('extra') else ""

        msg = (
            f"{photo_prefix}"
            f"🎯 <b>{item['source']}</b>\n"
            f"📌 <b>{item['title']}</b>\n"
            f"💰 <b>Ціна:</b> {item['price']}"
            f"{extra_line}\n"
            f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
        )
        send_telegram(msg)

    if force_test and new_count == 0:
        send_telegram(f"ℹ️ <b>[ТЕСТ]</b> Бот v6.3 готовий! Тепер із картинками та фото-прев'ю.")

    log(f"🏁 Завершено. Нових надіслано: {new_count}")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот v6.3 з фото активовано!".encode("utf-8"))

        t = threading.Thread(target=run_hunter, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    log(f"🚀 Запуск сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
