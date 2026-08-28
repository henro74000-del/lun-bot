import http.server
import os
import socketserver
import threading
import time
import requests
from bs4 import BeautifulSoup

# Міні-сервер, щоб Render бачив активність сервісу
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot sniper is running!")

    with socketserver.TCPServer(("", port), Handler) as httpd:
        httpd.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# --- ОСНОВНИЙ КОД БОТА ---
BOT_TOKEN = "8815805541:AAGwC_LXJI2vJwJ1E5bzhosKmF6lDvD5Bps"
CHAT_ID = "-5580190923"

CATEGORIES = {
    "🏢 ОРЕНДА (ВЛАСНИК)": "https://lun.ua/uk/%D0%BE%D1%80%D0%B5%D0%BD%D0%B4%D0%B0-%D0%BA%D0%B2%D0%B0%D1%80%D1%82%D0%B8%D1%80-%D1%85%D0%BC%D0%B5%D0%BB%D1%8C%D0%BD%D0%B8%D1%86%D1%8C%D0%BA%D0%B8%D0%B9/flats-bez-poserednykiv?sort=insert_time",
    "🔑 ПРОДАЖ КВАРТИРИ (ВЛАСНИК)": "https://lun.ua/uk/%D0%BF%D1%80%D0%BE%D0%B4%D0%B0%D0%B6-%D0%BA%D0%B2%D0%B0%D1%80%D1%82%D0%B8%D1%80-%D1%85%D0%BC%D0%B5%D0%BB%D1%8C%D0%BD%D0%B8%D1%86%D1%8C%D0%BA%D0%B8%D0%B9/flats-bez-poserednykiv?sort=insert_time",
    "🏡 ПРОДАЖ БУДИНКУ (ВЛАСНИК)": "https://lun.ua/uk/%D0%BF%D1%80%D0%BE%D0%B4%D0%B0%D0%B6-%D0%B1%D1%83%D0%B4%D0%B8%D0%BD%D0%BA%D1%96%D0%B2-%D1%85%D0%BC%D0%B5%D0%BB%D1%8C%D0%BD%D0%B8%D1%86%D1%8C%D0%BA%D0%B8%D0%B9/bez-poserednykiv?sort=insert_time"
}

seen_ads = set()

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        print("Телеграм каже:", r.status_code)
    except Exception as e:
        print("Помилка зв'язку з ТГ:", e)

print("🚀 Бот-снайпер запущений на Render!")
send_telegram("🫡 Бот-снайпер переїхав на Render і заступив на 24/7 чергування!")

while True:
    for cat_name, url in CATEGORIES.items():
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, "html.parser")

            links = soup.find_all("a", href=True)

            for link in links:
                href = link["href"]
                if "/realty/" in href:
                    full_url = href if href.startswith("http") else "https://lun.ua" + href

                    if full_url not in seen_ads:
                        if len(seen_ads) > 0:
                            msg = f"🔥 НОВЕ ОГОЛОШЕННЯ!\nКатегорія: {cat_name}\n\n🔗 {full_url}"
                            send_telegram(msg)
                            print(f"Знайдено: {cat_name} -> {full_url}")
                        
                        seen_ads.add(full_url)

        except Exception as e:
            print(f"Помилка сканування {cat_name}:", e)
        
        time.sleep(3)

    time.sleep(60)
