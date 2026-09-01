import os
import re
import json
import time
import requests
import cloudscraper
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))
DB_FILE = "ads_db.json"

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

OLX_SOURCES = [
    ("OLX Оренда", "https://www.olx.ua/uk/nedvizhimost/kvartiry/dolgosrochnaya-arenda-kvartir/khmelnitskiy/"),
    ("OLX Продаж", "https://www.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/khmelnitskiy/")
]

DIMRIA_SOURCES = [
    ("DIM.RIA Оренда", "https://dom.ria.com/uk/arenda-kvartir/khmelnytskyi/"),
    ("DIM.RIA Продаж", "https://dom.ria.com/uk/prodazha-kvartir/khmelnytskyi/")
]

def load_ads_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Помилка читання бази: {e}")
    return {}

def save_ads_db(db):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Помилка збереження бази: {e}")

def log(msg):
    print(msg, flush=True)

def setup_webhook():
    if not BOT_TOKEN:
        return
    webhook_url = "https://lun-bot.onrender.com/webhook"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
    try:
        requests.get(url, timeout=10)
        log("📡 Telegram Webhook успішно налаштовано!")
    except Exception as e:
        log(f"⚠️ Не вдалося встановити Webhook: {e}")

def send_telegram(text, target_chat_id=None):
    cid = target_chat_id or CHAT_ID
    if not BOT_TOKEN or not cid:
        log("❌ ПОМИЛКА: BOT_TOKEN або CHAT_ID порожні!")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": cid, 
        "text": text, 
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        log(f"❌ Помилка Telegram: {e}")
        return False

def parse_price_usd(price_str):
    if "$" in price_str:
        digits = re.sub(r'[^\d]', '', price_str)
        return int(digits) if digits else 0
    elif "грн" in price_str or "₴" in price_str:
        digits = re.sub(r'[^\d]', '', price_str)
        if digits:
            return int(int(digits) / 41.5)
    return 0

def extract_photo(text):
    img_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', text, re.IGNORECASE)
    if not img_match:
        img_match = re.search(r'<meta\s+name="og:image"\s+content="([^"]+)"', text, re.IGNORECASE)
    return img_match.group(1) if img_match else None

def clean_html_to_text(html):
    # Очищаємо скрипти, стилі та HTML теги для якісного пошуку
    clean = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL)
    clean = re.sub(r'<style[^>]*>.*?</style>', ' ', clean, flags=re.DOTALL)
    clean = re.sub(r'<[^>]+>', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:5000]

def check_if_realtor(text):
    text_lower = text.lower()
    realtor_words = ["агентство", "комісія", "ріелтор", "рієлтор", "послуги агента", "ан ", "агенція"]
    for word in realtor_words:
        if word in text_lower:
            return True
    return False

def inspect_olx_page(url):
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            text = res.text

            title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', text, re.IGNORECASE)
            title = title_match.group(1).replace('- OLX.ua', '').replace('OLX.ua', '').strip() if title_match else "Квартира OLX"
            photo_url = extract_photo(text)

            clean_text = clean_html_to_text(text)

            price = "Не вказано"
            usd_matches = re.findall(r'(\$\s*[\d\s\xa0]{4,}|[\d\s\xa0]{4,}\s*\$)', clean_text)
            if usd_matches:
                price = usd_matches[0].replace('\xa0', ' ').strip()
            else:
                uah_matches = re.findall(r'([\d\s\xa0]{5,}(?:\.\d{2})?\s*(?:грн|\u20b4))', clean_text)
                if uah_matches:
                    price = uah_matches[0].replace('\xa0', ' ').strip()

            rooms_match = re.search(r'Кількість кімнат:\s*([^\n<]+)', text, re.IGNORECASE)
            area_match = re.search(r'Загальна площа:\s*([^\n<]+)', text, re.IGNORECASE)

            rooms = rooms_match.group(1).strip() if rooms_match else ""
            area = area_match.group(1).strip() if area_match else ""

            details = []
            if rooms: details.append(f"🚪 {rooms}")
            if area: details.append(f"📐 {area}")
            extra_info = " | ".join(details)

            rooms_num = int(re.sub(r'[^\d]', '', rooms)) if re.search(r'\d+', rooms) else None
            price_usd = parse_price_usd(price)
            is_realtor = check_if_realtor(clean_text)

            return title, price, price_usd, extra_info, rooms_num, photo_url, clean_text, not is_realtor
    except Exception as e:
        log(f"⚠️ Помилка OLX сторінки {url}: {e}")
    return "Оголошення OLX", "Не вказано", 0, "", None, None, "", True

def inspect_dimria_page(url):
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            text = res.text
            photo_url = extract_photo(text)
            clean_text = clean_html_to_text(text)
            
            title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', text, re.IGNORECASE)
            title = title_match.group(1).replace('- DOM.RIA', '').strip() if title_match else "Квартира DIM.RIA"

            price_match = re.search(r'(\$\s*[\d\s\xa0]{3,}|[\d\s\xa0]{3,}\s*\$|[\d\s\xa0]{4,}\s*(?:грн|\u20b4))', clean_text)
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Не вказано"
            price_usd = parse_price_usd(price)
            
            is_realtor = check_if_realtor(clean_text)

            return title, price, price_usd, photo_url, clean_text, not is_realtor
    except Exception as e:
        log(f"⚠️ Помилка DIM.RIA {url}: {e}")
    return "Оголошення DIM.RIA", "Не вказано", 0, None, "", True

def scan_olx():
    found = []
    for label, url in OLX_SOURCES:
        try:
            res = scraper.get(url, timeout=15)
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
                    "source": label
                })
        except Exception as e:
            log(f"❌ Помилка OLX ({label}): {e}")
    return found

def scan_dimria():
    found = []
    for label, url in DIMRIA_SOURCES:
        try:
            res = scraper.get(url, timeout=15)
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
                    "url": clean_url,
                    "source": label
                })
        except Exception as e:
            log(f"❌ Помилка DIM.RIA ({label}): {e}")
    return found

def search_in_db(user_text):
    db = load_ads_db()
    if not db:
        return "ℹ️ База поки порожня. Зачекайте першого повного сканування!"

    q = user_text.lower().strip()
    
    # 1. Визначення максимальної ціни
    max_price = None
    numbers = re.findall(r'\b\d+\b', q)
    for num in numbers:
        val = int(num)
        if val >= 10 and val <= 300:
            if any(k in q for k in ["к", "k", "тис", "$"]):
                max_price = val * 1000
        elif val >= 1000:
            max_price = val

    # 2. Визначення кількості кімнат
    rooms_req = None
    if re.search(r'\b(1|1к|1k|1-к|1-k|однокімн|1-кімн)\b', q): rooms_req = 1
    elif re.search(r'\b(2|2к|2k|2-к|2-k|двокімн|2-кімн)\b', q): rooms_req = 2
    elif re.search(r'\b(3|3к|3k|3-к|3-k|трикімн|3-кімн)\b', q): rooms_req = 3

    # 3. Виділення ключових слів (наприклад "молодіж", "гречани")
    stop_words = ["знайди", "шукаю", "квартиру", "квартира", "хмельницькому", "1к", "2к", "3к", "1k", "2k", "3k"]
    raw_words = re.findall(r'[a-ua-яєіїґ0-9]+', q)
    keywords = [w for w in raw_words if len(w) >= 2 and not w.isdigit() and w not in stop_words]

    matched = []
    for ad_id, ad in db.items():
        if ad.get("banned"):
            continue

        if max_price and ad.get("price_usd", 0) > 0:
            if ad["price_usd"] > max_price:
                continue

        full_text = (ad.get("title", "") + " " + ad.get("page_text", "") + " " + ad.get("extra", "") + " " + ad.get("url", "")).lower()

        # Фільтр кімнат
        if rooms_req:
            r_num = ad.get("rooms_num")
            if r_num:
                if r_num != rooms_req:
                    continue
            else:
                room_patterns = {
                    1: [r'\b1\s*[-–]?\s*к', r'1k', r'1 кімн', r'однокімн'],
                    2: [r'\b2\s*[-–]?\s*к', r'2k', r'2 кімн', r'двокімн'],
                    3: [r'\b3\s*[-–]?\s*к', r'3k', r'3 кімн', r'трикімн']
                }
                if not any(re.search(pat, full_text) for pat in room_patterns[rooms_req]):
                    continue

        # Фільтр ключових слів
        if keywords:
            if not any(kw in full_text for kw in keywords):
                continue

        matched.append(ad)

    if not matched:
        return f"🤷‍♂️ На жаль, за запитом «<i>{user_text}</i>» нічого не знайшов."

    # Сортуємо: Власники на початку
    matched.sort(key=lambda x: 0 if x.get("is_owner", True) else 1)

    response = f"🔎 <b>[ПОШУК НА ЗАПИТ]</b> Результати:\n<i>«{user_text}»</i>\n\n"
    for item in matched[:5]:
        photo_prefix = f'<a href="{item["photo"]}">&#8203;</a>' if item.get("photo") else ""
        type_badge = "👑 <b>ВЛАСНИК</b>" if item.get("is_owner", True) else "🤝 <b>СПІВПРАЦЯ / РІЄЛТОР</b>"
        extra_line = f"\nℹ️ <b>Деталі:</b> {item['extra']}" if item.get('extra') else ""
        
        response += (
            f"{photo_prefix}"
            f"{type_badge} ({item['source']})\n"
            f"📌 <b>{item.get('title', 'Квартира')}</b>\n"
            f"💰 <b>Ціна:</b> {item.get('price', 'Не вказано')}"
            f"{extra_line}\n"
            f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>\n\n"
        )
    return response

def run_hunter(force_test=False):
    db = load_ads_db()
    first_run = (len(db) == 0)

    log(f"🔎 Сканування... В базі є {len(db)} об'єктів.")
    all_items = scan_olx() + scan_dimria()

    new_count = 0
    new_owners_count = 0

    for item in all_items:
        ad_id = item["id"]
        if ad_id in db:
            continue

        if ad_id.startswith("olx_"):
            title, price, price_usd, extra_info, rooms_num, photo_url, text, is_owner = inspect_olx_page(item["url"])
            item.update({
                "title": title, "price": price, "price_usd": price_usd, 
                "extra": extra_info, "rooms_num": rooms_num, "photo": photo_url, 
                "page_text": text, "is_owner": is_owner
            })

        elif ad_id.startswith("dimria_"):
            title, price, price_usd, photo_url, text, is_owner = inspect_dimria_page(item["url"])
            item.update({
                "title": title, "price": price, "price_usd": price_usd, 
                "photo": photo_url, "page_text": text, "is_owner": is_owner, "extra": ""
            })

        db[ad_id] = item
        save_ads_db(db)
        new_count += 1

        if not first_run and item.get("is_owner", True):
            new_owners_count += 1
            photo_prefix = f'<a href="{item["photo"]}">&#8203;</a>' if item.get("photo") else ""
            type_badge = "👑 <b>ВЛАСНИК</b>"
            extra_line = f"\nℹ️ <b>Деталі:</b> {item['extra']}" if item.get('extra') else ""

            msg = (
                f"{photo_prefix}"
                f"🚨 <b>[АВТО-РАДАР] Нове оголошення!</b>\n\n"
                f"{type_badge} ({item['source']})\n"
                f"📌 <b>{item.get('title', 'Квартира')}</b>\n"
                f"💰 <b>Ціна:</b> {item.get('price', 'Не вказано')}"
                f"{extra_line}\n"
                f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
            )
            send_telegram(msg)

    if first_run:
        log(f"🔥 Базу вперше створено! Записано {len(db)} шт.")
        if force_test:
            send_telegram(f"✅ <b>[ТЕСТ]</b> Базу створено! Збережено {len(db)} об'єктів.")

    elif force_test and new_owners_count == 0:
        send_telegram(f"ℹ️ <b>[ТЕСТ]</b> Бот v7.5 активний! Пошук по текстах та кімнатах виправлено.")

    log(f"🏁 Завершено. Нових хат: {new_count} (з них Власників надіслано: {new_owners_count})")

def background_loop():
    while True:
        try:
            run_hunter()
        except Exception as e:
            log(f"⚠️ Помилка у циклі сканування: {e}")
        time.sleep(300)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот v7.5 активовано!".encode("utf-8"))

        if force_test:
            t = threading.Thread(target=run_hunter, kwargs={"force_test": True})
            t.daemon = True
            t.start()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        self.send_response(200)
        self.end_headers()

        try:
            update = json.loads(body.decode('utf-8'))
            if "message" in update and "text" in update["message"]:
                text = update["message"]["text"]
                chat_id = update["message"]["chat"]["id"]

                if text.startswith("🚨") or text.startswith("🔎") or text.startswith("✅") or text.startswith("ℹ️"):
                    return

                reply = search_in_db(text)
                send_telegram(reply, target_chat_id=chat_id)
        except Exception as e:
            log(f"⚠️ Помилка обробки Webhook: {e}")

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    setup_webhook()
    
    bg_thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()

    log(f"🚀 Запуск сервера v7.5 на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
