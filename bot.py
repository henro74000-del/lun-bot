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
    ("OLX Оренда", "https://www.olx.ua/uk/nedvizhimost/kvartiry/dolgosrochnaya-arenda-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private"),
    ("OLX Продаж", "https://www.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/khmelnitskiy/?search%5Bprivate_business%5D=private")
]

DIMRIA_SOURCES = [
    ("DIM.RIA Оренда", "https://dom.ria.com/uk/arenda-kvartir/khmelnytskyi/?from_owner=1&without_realtor=1"),
    ("DIM.RIA Продаж", "https://dom.ria.com/uk/prodazha-kvartir/khmelnytskyi/?from_owner=1&without_realtor=1")
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

def inspect_olx_page(url):
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            text = res.text

            title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', text, re.IGNORECASE)
            title = title_match.group(1).replace('- OLX.ua', '').replace('OLX.ua', '').strip() if title_match else "Квартира OLX"
            photo_url = extract_photo(text)

            clean_html = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            clean_html = re.sub(r'<style[^>]*>.*?</style>', '', clean_html, flags=re.DOTALL)

            price = "Не вказано"
            usd_matches = re.findall(r'(\$\s*[\d\s\xa0]{4,}|[\d\s\xa0]{4,}\s*\$)', clean_html)
            if usd_matches:
                price = usd_matches[0].replace('\xa0', ' ').strip()
            else:
                uah_matches = re.findall(r'([\d\s\xa0]{5,}(?:\.\d{2})?\s*(?:грн|\u20b4))', clean_html)
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

            return title, price, price_usd, extra_info, rooms_num, photo_url, text
    except Exception as e:
        log(f"⚠️ Помилка OLX сторінки {url}: {e}")
    return "Оголошення OLX", "Не вказано", 0, "", None, None, ""

def inspect_dimria_page(url):
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            text = res.text
            text_lower = text.lower()
            bad_phrases = ["перевірений рієлтор", "перевірене агентство", "архітек", "architek", "основа", "osnova", "комісія", "агентство нерухомості", "рієлтор"]
            for bad in bad_phrases:
                if bad in text_lower:
                    return True, "Не вказано", 0, None, ""

            photo_url = extract_photo(text)
            clean_html = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            price_match = re.search(r'(\$\s*[\d\s\xa0]{3,}|[\d\s\xa0]{3,}\s*\$|[\d\s\xa0]{4,}\s*(?:грн|\u20b4))', clean_html)
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Не вказано"
            price_usd = parse_price_usd(price)

            return False, price, price_usd, photo_url, text
    except Exception as e:
        log(f"⚠️ Помилка DIM.RIA {url}: {e}")
    return False, "Не вказано", 0, None, ""

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
                    "source": label,
                    "is_owner": True
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
                    "title": label,
                    "url": clean_url,
                    "price": "Не вказано",
                    "source": label,
                    "is_owner": True,
                    "extra": "",
                    "photo": None
                })
        except Exception as e:
            log(f"❌ Помилка DIM.RIA ({label}): {e}")
    return found

def search_in_db(user_text):
    db = load_ads_db()
    if not db:
        return "ℹ️ База поки порожня. Зачекайте першого повного сканування!"

    q = user_text.lower()
    
    # Визначаємо ціну
    max_price = None
    numbers = re.findall(r'\b\d+\b', q)
    for num in numbers:
        val = int(num)
        if val >= 10 and val <= 300:
            if any(k in q for k in ["к", "k", "тис", "$"]):
                max_price = val * 1000
        elif val >= 1000:
            max_price = val

    # Визначаємо кімнати (підтримуємо і 'к', і 'k')
    rooms_req = None
    if any(k in q for k in ["1к", "1k", "1-к", "1-k", "1 кімн", "однокімн"]): rooms_req = 1
    elif any(k in q for k in ["2к", "2k", "2-к", "2-k", "2 кімн", "двокімн"]): rooms_req = 2
    elif any(k in q for k in ["3к", "3k", "3-к", "3-k", "3 кімн", "трикімн"]): rooms_req = 3

    # Ключові слова (ігноруємо службові фрази)
    stop_words = ["знайди", "шукаю", "квартиру", "квартира", "хмельницькому", "1к", "2к", "3к", "1k", "2k", "3k"]
    keywords = [w for w in re.findall(r'[a-ua-яєіїґ0-9]+', q) if len(w) >= 3 and not w.isdigit() and w not in stop_words]

    matched = []
    for ad_id, ad in db.items():
        if ad.get("banned"):
            continue

        # Перевірка ціни
        if max_price and ad.get("price_usd", 0) > 0:
            if ad["price_usd"] > max_price:
                continue

        full_text = (ad.get("title", "") + " " + ad.get("page_text", "")).lower()

        # Перевірка кімнат
        if rooms_req:
            r_num = ad.get("rooms_num")
            if r_num:
                if r_num != rooms_req:
                    continue
            else:
                # Якщо кількість кімнат не була розпарсена — шукаємо в тексті
                room_patterns = {
                    1: ["1к", "1k", "1 кімн", "1-кімн", "однокімн"],
                    2: ["2к", "2k", "2 кімн", "2-кімн", "двокімн"],
                    3: ["3к", "3k", "3 кімн", "3-кімн", "трикімн"]
                }
                if not any(pat in full_text for pat in room_patterns[rooms_req]):
                    continue

        # Перевірка слів (район, вулиця тощо)
        if keywords:
            if not any(kw in full_text for kw in keywords):
                continue

        matched.append(ad)

    if not matched:
        return f"🤷‍♂️ На жаль, за запитом «<i>{user_text}</i>» нічого не знайшов. База ще поповнюється новими об'єктами!"

    # Сортування: спочатку ВЛАСНИКИ
    matched.sort(key=lambda x: 0 if x.get("is_owner", True) else 1)

    response = f"🔎 <b>[ПОШУК НА ЗАПИТ]</b> Результати за вашим проханням:\n<i>«{user_text}»</i>\n\n"
    for item in matched[:5]:
        photo_prefix = f'<a href="{item["photo"]}">&#8203;</a>' if item.get("photo") else ""
        type_badge = "👑 <b>ВЛАСНИК</b>" if item.get("is_owner", True) else "🤝 <b>СПІВПРАЦЯ / РІЄЛТОР</b>"
        extra_line = f"\nℹ️ <b>Деталі:</b> {item['extra']}" if item.get('extra') else ""
        
        response += (
            f"{photo_prefix}"
            f"{type_badge} ({item['source']})\n"
            f"📌 <b>{item['title']}</b>\n"
            f"💰 <b>Ціна:</b> {item['price']}"
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
    for item in all_items:
        ad_id = item["id"]
        if ad_id in db:
            continue

        if ad_id.startswith("olx_"):
            title, price, price_usd, extra_info, rooms_num, photo_url, text = inspect_olx_page(item["url"])
            item.update({
                "title": title, "price": price, "price_usd": price_usd, 
                "extra": extra_info, "rooms_num": rooms_num, "photo": photo_url, 
                "page_text": text[:1000], "is_owner": True
            })

        elif ad_id.startswith("dimria_"):
            is_realtor, price, price_usd, photo_url, text = inspect_dimria_page(item["url"])
            if is_realtor:
                log(f"🚫 [БАН] Рієлтор: {item['url']}")
                db[ad_id] = {"banned": True}
                save_ads_db(db)
                continue
            item.update({
                "price": price, "price_usd": price_usd, 
                "photo": photo_url, "page_text": text[:1000], "is_owner": True
            })

        db[ad_id] = item
        save_ads_db(db)
        new_count += 1

        if not first_run:
            photo_prefix = f'<a href="{item["photo"]}">&#8203;</a>' if item.get("photo") else ""
            type_badge = "👑 <b>ВЛАСНИК</b>" if item.get("is_owner", True) else "🤝 <b>СПІВПРАЦЯ / РІЄЛТОР</b>"
            extra_line = f"\nℹ️ <b>Деталі:</b> {item['extra']}" if item.get('extra') else ""

            msg = (
                f"{photo_prefix}"
                f"🚨 <b>[АВТО-РАДАР] Нове оголошення!</b>\n\n"
                f"{type_badge} ({item['source']})\n"
                f"📌 <b>{item['title']}</b>\n"
                f"💰 <b>Ціна:</b> {item['price']}"
                f"{extra_line}\n"
                f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
            )
            send_telegram(msg)

    if first_run:
        log(f"🔥 Базу вперше створено! Записано {len(db)} шт.")
        if force_test:
            send_telegram(f"✅ <b>[ТЕСТ]</b> Базу створено! Збережено {len(db)} об'єктів.")

    elif force_test and new_count == 0:
        send_telegram(f"ℹ️ <b>[ТЕСТ]</b> Бот v7.2 активний! Сканер та пошук працюють.")

    log(f"🏁 Завершено. Нових надіслано: {new_count}")

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
        self.wfile.write("Бот v7.2 активовано!".encode("utf-8"))

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

    log(f"🚀 Запуск сервера v7.2 на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
