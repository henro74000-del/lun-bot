import os
import json
import requests
import threading
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))

# Хмарна база пам'яті
DB_URL = "https://kvdb.io/8N9z2XmQpL4vW1yK7jR3tA/seen_ads_khm"
URL = "https://lun.ua/uk/%D0%BE%D1%80%D0%B5%D0%BD%D0%B4%D0%B0-%D0%BA%D0%B2%D0%B0%D1%80%D1%82%D0%B8%D1%80-%D1%85%D0%BC%D0%B5%D0%BB%D1%8C%D0%BD%D0%B8%D1%86%D1%8C%D0%BA%D0%B8%D0%B9"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8"
}

def load_seen_ids():
    try:
        res = requests.get(DB_URL, timeout=5)
        if res.status_code == 200 and res.text:
            return set(res.text.split(","))
    except Exception as e:
        print(f"Помилка хмари: {e}")
    return set()

def save_seen_ids(seen_set):
    try:
        data_to_save = ",".join(list(seen_set)[-200:])
        requests.post(DB_URL, data=data_to_save, timeout=5)
    except Exception as e:
        print(f"Помилка збереження: {e}")

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Помилка: Не вказано BOT_TOKEN або CHAT_ID в Render Environment!")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"📬 Telegram статус: {res.status_code}")
        return res.status_code == 200
    except Exception as e:
        print(f"❌ Помилка ТГ: {e}")
        return False

def parse_lun(force_test=False):
    seen_ids = load_seen_ids()
    is_first_run = (len(seen_ids) == 0)

    print(f"🔎 [Сканування] Хмарна база містить {len(seen_ids)} бачених оголошень.")

    try:
        res = requests.get(URL, headers=HEADERS, timeout=15)
        print(f"🌐 Відповідь ЛУН: HTTP {res.status_code}")

        if res.status_code != 200:
            if force_test:
                send_telegram(f"⚠️ <b>Тест зв'язку:</b> Сервер ЛУН повернув HTTP {res.status_code}")
            return

        soup = BeautifulSoup(res.text, "html.parser")
        realties = []

        # Спосіб 1: JSON __NEXT_DATA__
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag and script_tag.string:
            try:
                data = json.loads(script_tag.string)
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
            except Exception as e:
                print(f"Помилка JSON: {e}")

        # Спосіб 2: Прямі посилання з HTML
        if not realties:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/uk/" in href and ("оренда" in href or "квартира" in href or "realty" in href):
                    clean_url = href if href.startswith("http") else f"https://lun.ua{href}"
                    ad_id = clean_url.split("?")[0].rstrip("/").split("/")[-1]
                    if len(ad_id) > 3:
                        realties.append({
                            "id": ad_id,
                            "title": a.get_text(strip=True) or "Квартира в Хмельницькому",
                            "price": "Дивись на сайті",
                            "url": clean_url
                        })

        if not realties:
            print("⚠️ Не вдалося витягнути оголошення.")
            if force_test:
                send_telegram("🔔 <b>[ТЕСТ ЗВ'ЯЗКУ]</b> Бот бачить Telegram! Але ЛУН приховав списки.")
            return

        print(f"📊 Знайдено {len(realties)} оголошень на сторінці.")

        new_count = 0
        for item in realties:
            if not isinstance(item, dict):
                continue

            ad_id = str(item.get("id") or item.get("id_slug") or item.get("url", ""))
            if not ad_id:
                continue

            if ad_id in seen_ids and not force_test:
                continue

            seen_ids.add(ad_id)

            if is_first_run and not force_test:
                continue

            title = item.get("title") or item.get("heading") or "Квартира від власника"
            price = item.get("price") or item.get("price_uah") or "Дивись на сайті"
            if isinstance(price, dict):
                price = f"{price.get('value', '')} {price.get('currency', 'грн')}"

            link = item.get("url") or item.get("link") or ""
            if link and not link.startswith("http"):
                link = f"https://lun.ua{link}"

            msg = (
                f"🎯 <b>{'[ТЕСТ] ' if force_test else ''}Знайдено квартиру!</b>\n\n"
                f"🏠 <b>{title}</b>\n"
                f"💵 <b>Ціна:</b> {price}\n"
                f"🔗 <a href='{link}'>Відкрити на ЛУН</a>"
            )
            send_telegram(msg)
            new_count += 1

            if force_test:
                break

        save_seen_ids(seen_ids)

        if is_first_run and not force_test:
            send_telegram("🛡️ <b>Бот-снайпер заступив на варту!</b>")
        else:
            print(f"✅ Сканування завершено. Нових хат відправлено: {new_count}")

    except Exception as e:
        print(f"❌ Помилка в parse_lun: {e}")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")

        # МИТТЄВА ВІДПОВІДЬ (щоб Render не сумував)
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

        msg = "🚀 Тест запущено! Перевіряй ТГ." if force_test else "✅ Бот працює 24/7!"
        self.wfile.write(msg.encode("utf-8"))

        # Запускаємо важку роботу у фоні
        t = threading.Thread(target=parse_lun, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    print(f"🚀 Запуск веб-сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
