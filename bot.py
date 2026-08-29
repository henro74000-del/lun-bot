import os
import time
import json
import requests
from bs4 import BeautifulSoup

# Отримуємо ключі з налаштувань Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# Сторінка оренди квартир у Хмельницькому від власників
URL = "https://lun.ua/uk/%D0%BE%D1%80%D0%B5%D0%BD%D0%B4%D0%B0-%D0%BA%D0%B2%D0%B0%D1%80%D1%82%D0%B8%D1%80-%D1%85%D0%BC%D0%B5%D0%BB%D1%8C%D0%BD%D0%B8%D1%86%D1%8C%D0%BA%D0%B8%D0%B9-%D0%B1%D0%B5%D0%B7-%D0%BF%D0%BE%D1%81%D0%B5%D1%80%D0%B5%D0%B4%D0%BD%D0%B8%D0%BA%D1%96%D0%B2"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

SEEN_FILE = "seen_ads.txt"

def load_seen_ids():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_seen_id(ad_id):
    with open(SEEN_FILE, "a") as f:
        f.write(f"{ad_id}\n")

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Помилка: Не вказано BOT_TOKEN або CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Помилка відправки в ТГ: {e}")

def parse_lun():
    seen_ids = load_seen_ids()
    is_first_run = len(seen_ids) == 0

    print("🔎 Запуск сканування ЛУН через JSON...")

    try:
        res = requests.get(URL, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            print(f"Помилка доступу до ЛУН: HTTP {res.status_code}")
            return

        soup = BeautifulSoup(res.text, "html.parser")
        script_tag = soup.find("script", id="NEXT_DATA")

        if not script_tag:
            print("⚠️ Не знайдено блок NEXT_DATA")
            return

        data = json.loads(script_tag.string)
        
        # Рекурсивний пошук масивів оголошень у структурі JSON
        realties = []
        def extract_items(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ["items", "realties", "results"] and isinstance(v, list):
                        realties.extend(v)
                    else:
                        extract_items(v)
            elif isinstance(obj, list):
                for item in obj:
                    extract_items(item)

        extract_items(data)

        new_count = 0
        for item in realties:
            if not isinstance(item, dict):
                continue
            
            ad_id = str(item.get("id") or item.get("id_slug") or item.get("url", ""))
            if not ad_id:
                continue

            if ad_id in seen_ids:
                continue

            seen_ids.add(ad_id)
            save_seen_id(ad_id)

            # Якщо це найперший запуск — просто запам'ятовуємо старі хати без спаму в ТГ
            if is_first_run:
                continue

            # Збираємо дані для повідомлення
            title = item.get("title") or item.get("heading") or "Квартира від власника"
            price = item.get("price") or item.get("price_uah") or "Ціна не вказана"
            if isinstance(price, dict):
                price = f"{price.get('value', '')} {price.get('currency', 'грн')}"

            link = item.get("url") or item.get("link") or ""
            if link and not link.startswith("http"):
                link = f"https://lun.ua{link}"

            msg = (
                f"🎯 <b>Знайдено нову квартиру!</b>\n\n"
                f"🏠 <b>{title}</b>\n"
                f"💵 <b>Ціна:</b> {price}\n"
                f"🔗 <a href='{link}'>Відкрити на ЛУН</a>"
            )
            send_telegram(msg)
            new_count += 1

        if is_first_run:
            print(f"✅ Базу ініціалізовано. Запам'ятовано {len(seen_ids)} існуючих оголошень.")
            send_telegram("🎯 <b>Бот-снайпер переведений на JSON-тепловізор 2.0!</b> Тепер жодна хата не проскочить.")
        else:
            print(f"✅ Сканування завершено. Нових оголошень: {new_count}")

    except Exception as e:
        print(f"Помилка при скануванні: {e}")

if name == "main":
    parse_lun()
