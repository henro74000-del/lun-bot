import os
import json
import requests
import threading
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))

URL = "https://lun.ua/uk/%D0%BE%D1%80%D0%B5%D0%BD%D0%B4%D0%B0-%D0%BA%D0%B2%D0%B0%D1%80%D1%82%D0%B8%D1%80-%D1%85%D0%BC%D0%B5%D0%BB%D1%8C%D0%BD%D0%B8%D1%86%D1%8C%D0%BA%D0%B8%D0%B9"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9"
}

def log(msg):
    print(msg, flush=True)

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        log("❌ ПОМИЛКА: BOT_TOKEN або CHAT_ID порожні в Render Environment Variables!")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        log(f"📬 Відповідь Telegram API: status={res.status_code}, body={res.text}")
        return res.status_code == 200
    except Exception as e:
        log(f"❌ Помилка з'єднання з Telegram: {e}")
        return False

def parse_lun(force_test=False):
    if force_test:
        log("🧪 Тестовий запуск! Надсилаємо прямий тест у Telegram...")
        send_telegram("🚀 <b>[ТЕСТ ЗВ'ЯЗКУ]</b> Якщо ти це бачиш — бот і Telegram на одній хвилі!")

    try:
        log("🔎 Робимо запит до ЛУН...")
        res = requests.get(URL, headers=HEADERS, timeout=15)
        log(f"🌐 ЛУН відповів кодом: HTTP {res.status_code}")

        if res.status_code != 200:
            log(f"⚠️ ЛУН заблокував запит (код {res.status_code})")
            return

        soup = BeautifulSoup(res.text, "html.parser")
        realties = []

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
                log(f"Помилка декодування JSON: {e}")

        if not realties:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/uk/" in href and ("оренда" in href or "квартира" in href or "realty" in href):
                    clean_url = href if href.startswith("http") else f"https://lun.ua{href}"
                    ad_id = clean_url.split("?")[0].rstrip("/").split("/")[-1]
                    if len(ad_id) > 3:
                        realties.append({
                            "id": ad_id,
                            "title": a.get_text(strip=True) or "Квартира у Хмельницькому",
                            "price": "Дивись на сайті",
                            "url": clean_url
                        })

        log(f"📊 Знайдено оголошень: {len(realties)}")

        if realties and force_test:
            item = realties[0]
            title = item.get("title") or "Квартира в оренду"
            price = item.get("price") or "Дивись на ЛУН"
            link = item.get("url") or item.get("link") or URL
            send_telegram(f"🏠 <b>Знайдено першу хату:</b>\n{title}\n💵 {price}\n🔗 {link}")

    except Exception as e:
        log(f"❌ Загальна помилка: {e}")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        force_test = self.path.startswith("/test")
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Тест запущено! Дивись логи в Render.".encode("utf-8"))

        t = threading.Thread(target=parse_lun, kwargs={"force_test": force_test})
        t.daemon = True
        t.start()

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    log(f"🚀 Запуск веб-сервера на порту {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler)
    server.serve_forever()
