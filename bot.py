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

def send_telegram_msg(text, target_chat_id=None):
    cid = target_chat_id or CHAT_ID
    if not BOT_TOKEN or not cid:
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

def send_telegram_photo(photo_url, caption, target_chat_id=None):
    cid = target_chat_id or CHAT_ID
    if not BOT_TOKEN or not cid:
        return False
    if not photo_url:
        return send_telegram_msg(caption, target_chat_id=cid)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": cid,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            return True
        else:
            return send_telegram_msg(caption, target_chat_id=cid)
    except Exception as e:
        log(f"⚠️ Помилка відправки фото: {e}")
        return send_telegram_msg(caption, target_chat_id=cid)

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
    clean = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL)
    clean = re.sub(r'<style[^>]*>.*?</style>', ' ', clean, flags=re.DOTALL)
    clean = re.sub(r'<[^>]+>', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:5000]

def check_if_realtor(raw_html, clean_text, title=""):
    text_lower = (title + " " + clean_text + " " + raw_html).lower()
    
    # 1. Детект кодів об'єктів агентств на початку заголовка (наприклад: "46204 !", "ID 12345")
    if re.search(r'^\s*\d{4,6}\b', title) or re.search(r'\b(код|id)\s*[:#]?\s*\d{4,6}\b', text_lower):
        return True

    # 2. Список агентств та слів-маркерів
    realtor_words = [
        "агентство", "комісія", "ріелтор", "рієлтор", "послуги агента", 
        "агенція", "маклер", "посередник", "представник агенції",
        "основа", "osnova", "оператор нерухомості"
    ]
    for word in realtor_words:
        if word in text_lower:
            return True

    # 3. Перевірка на бізнес-аккаунт від OLX
    if '"usertype":"business"' in text_lower or 'user_type_business' in text_lower or '"isbusiness":true' in text_lower:
        return True

    # 4. Тільки якщо НІЧОГО з перерахованого вище не знайшли — віримо плашці "Приватна особа"
    if 'приватна особа' in text_lower or '"usertype":"private"' in text_lower or 'user_type_private' in text_lower:
        return False

    return False

def inspect_olx_page(url):
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            raw_html = res.text
            title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', raw_html, re.IGNORECASE)
            title = title_match.group(1).replace('- OLX.ua', '').replace('OLX.ua', '').strip() if title_match else "Квартира OLX"
            photo_url = extract_photo(raw_html)
            clean_text = clean_html_to_text(raw_html)

            price = "Не вказано"
            usd_matches = re.findall(r'(\$\s*[\d\s\xa0]{4,}|[\d\s\xa0]{4,}\s*\$)', clean_text)
            if usd_matches:
                price = usd_matches[0].replace('\xa0', ' ').strip()
            else:
                uah_matches = re.findall(r'([\d\s\xa0]{5,}(?:\.\d{2})?\s*(?:грн|\u20b4))', clean_text)
                if uah_matches:
                    price = uah_matches[0].replace('\xa0', ' ').strip()

            rooms_match = re.search(r'Кількість кімнат:\s*([^\n<]+)', raw_html, re.IGNORECASE)
            area_match = re.search(r'Загальна площа:\s*([^\n<]+)', raw_html, re.IGNORECASE)

            rooms = rooms_match.group(1).strip() if rooms_match else ""
            area = area_match.group(1).strip() if area_match else ""

            details = []
            if rooms: details.append(f"🚪 {rooms}")
            if area: details.append(f"📐 {area}")
            extra_info = " | ".join(details)

            rooms_num = int(re.sub(r'[^\d]', '', rooms)) if re.search(r'\d+', rooms) else None
            price_usd = parse_price_usd(price)
            is_realtor = check_if_realtor(raw_html, clean_text, title=title)

            return title, price, price_usd, extra_info, rooms_num, photo_url, clean_text, not is_realtor
    except Exception as e:
        log(f"⚠️ Помилка OLX сторінки {url}: {e}")
    return "Оголошення OLX", "Не вказано", 0, "", None, None, "", False

def inspect_dimria_page(url):
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            raw_html = res.text
            photo_url = extract_photo(raw_html)
            clean_text = clean_html_to_text(raw_html)
            
            title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', raw_html, re.IGNORECASE)
            title = title_match.group(1).replace('- DOM.RIA', '').strip() if title_match else "Квартира DIM.RIA"

            price_match = re.search(r'(\$\s*[\d\s\xa0]{3,}|[\d\s\xa0]{3,}\s*\$|[\d\s\xa0]{4,}\s*(?:грн|\u20b4))', clean_text)
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Не вказано"
            price_usd = parse_price_usd(price)
            
            is_realtor = check_if_realtor(raw_html, clean_text, title=title)

            return title, price, price_usd, photo_url, clean_text, not is_realtor
    except Exception as e:
        log(f"⚠️ Помилка DIM.RIA {url}: {e}")
    return "Оголошення DIM.RIA", "Не вказано", 0, None, "", False

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
    
    only_owners = any(w in q for w in ["власник", "приватна", "без комісії", "від власника"])
    only_rent = "оренд" in q
    only_sale = "продаж" in q or "купівл" in q

    max_price = None
    numbers = re.findall(r'\b\d+\b', q)
    for num in numbers:
        val = int(num)
        if val >= 10 and val <= 300:
            if any(k in q for k in ["к", "k", "тис", "$"]):
                max_price = val * 1000
        elif val >= 1000:
            max_price = val

    rooms_req = None
    if re.search(r'\b(1|1к|1k|1-к|1-k|однокімн|1-кімн)\b', q): rooms_req = 1
    elif re.search(r'\b(2|2к|2k|2-к|2-k|двокімн|2-кімн)\b', q): rooms_req = 2
    elif re.search(r'\b(3|3к|3k|3-к|3-k|трикімн|3-кімн)\b', q): rooms_req = 3

    meta_words = [
        "знайди", "шукаю", "квартиру", "квартира", "хмельницькому", 
        "1к", "2к", "3к", "1k", "2k", "3k", "оренда", "продаж", 
        "свіжі", "нові", "день", "сьогодні", "власник", "без комісії", 
        "приватна", "від власника"
    ]
    raw_words = re.findall(r'[a-ua-яєіїґ0-9]+', q)
    keywords = [w for w in raw_words if len(w) >= 2 and not w.isdigit() and w not in meta_words]

    matched = []
    for ad_id, ad in db.items():
        if ad.get("banned"):
            continue

        if only_rent and "Оренда" not in ad.get("source", ""):
            continue
        if only_sale and "Продаж" not in ad.get("source", ""):
            continue

        if only_owners and not ad.get("is_owner", False):
            continue

        if max_price and ad.get("price_usd", 0) > 0:
            if ad["price_usd"] > max_price:
                continue

        if rooms_req:
            r_num = ad.get("rooms_num")
            if r_num:
                if r_num != rooms_req:
                    continue
            else:
                full_text_tmp = (ad.get("title", "") + " " + ad.get("page_text", "")).lower()
                room_patterns = {
                    1: [r'\b1\s*[-–]?\s*к', r'1k', r'1 кімн', r'однокімн'],
                    2: [r'\b2\s*[-–]?\s*к', r'2k', r'2 кімн', r'двокімн'],
                    3: [r'\b3\s*[-–]?\s*к', r'3k', r'3 кімн', r'трикімн']
                }
                if not any(re.search(pat, full_text_tmp) for pat in room_patterns[rooms_req]):
                    continue

        if keywords:
            full_text = (ad.get("title", "") + " " + ad.get("page_text", "") + " " + ad.get("extra", "")).lower()
            if not all(kw in full_text for kw in keywords):
                continue

        matched.append(ad)

    if not matched:
        filter_type = " [ТІЛЬКИ ВЛАСНИКИ]" if only_owners else ""
        return f"🤷‍♂️ За запитом «<i>{user_text}</i>»{filter_type} нічого не знайдено."

    matched.sort(key=lambda x: 0 if x.get("is_owner", False) else 1)

    response = f"🔎 <b>[ПОШУК НА ЗАПИТ]</b> Результати:\n<i>«{user_text}»</i>\n\n"
    for item in matched[:5]:
        type_badge = "👑 <b>ВЛАСНИК</b>" if item.get("is_owner", False) else "🤝 <b>СПІВПРАЦЯ / РІЄЛТОР</b>"
        extra_line = f"\nℹ️ <b>Деталі:</b> {item['extra']}" if item.get('extra') else ""
        
        response += (
            f"{type_badge} ({item['source']})\n"
            f"📌 <b>{item.get('title', 'Квартира')}</b>\n"
            f"💰 <b>Ціна:</b> {item.get('price', 'Не вказано')}"
            f"{extra_line}\n"
            f"🔗 <a href='{item['url']}'>Відкрити оголошення на OLX/DIM.RIA</a>\n\n"
        )
    return response

def run_hunter():
    db = load_ads_db()
    initial_db_size = len(db)
    is_warmup = (initial_db_size < 20)

    log(f"🔎 Сканування... В базі є {initial_db_size} об'єктів.")
    all_items = scan_olx() + scan_dimria()

    new_items_this_run = []

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
        new_items_this_run.append(item)

    save_ads_db(db)

    new_owners = [it for it in new_items_this_run if it.get("is_owner", False)]

    log(f"🏁 Знайдено нових: {len(new_items_this_run)} (з них Власників: {len(new_owners)})")

    if is_warmup:
        log("🛡 Розігрів бази: сповіщення вимкнено.")
        return

    if len(new_owners) > 3:
        log(f"🛡 Запобіжник: масовий завантаж ({len(new_owners)} шт). Без PUSH у ТГ.")
    else:
        for item in new_owners:
            type_badge = "👑 <b>ВЛАСНИК</b>"
            extra_line = f"\nℹ️ <b>Деталі:</b> {item['extra']}" if item.get('extra') else ""

            msg = (
                f"🚨 <b>[АВТО-РАДАР] Нове оголошення!</b>\n\n"
                f"{type_badge} ({item['source']})\n"
                f"📌 <b>{item.get('title', 'Квартира')}</b>\n"
                f"💰 <b>Ціна:</b> {item.get('price', 'Не вказано')}"
                f"{extra_line}\n"
                f"🔗 <a href='{item['url']}'>Відкрити оголошення</a>"
            )
            
            if item.get("photo"):
                send_telegram_photo(item["photo"], msg)
            else:
                send_telegram_msg(msg)

def background_loop():
    while True:
        try:
            run_hunter()
        except Exception as e:
            log(f"⚠️ Помилка сканування: {e}")
        time.sleep(300)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот v8.3 активовано!".encode("utf-8"))

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
                send_telegram_msg(reply, target_chat_id=chat_id)
        except Exception as e:
            log(f"⚠️ Помилка Webhook: {e}")

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    setup_webhook()
    
    bg_thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()

    log(f"🚀 Запуск сервера v8.3 на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
