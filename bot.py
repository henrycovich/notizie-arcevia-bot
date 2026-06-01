import feedparser
import requests
import json
import os
import time
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup

# ============================================================
#  CONFIGURAZIONE — inserisci qui i tuoi dati
# ============================================================
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "IL_TUO_TOKEN_QUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "IL_TUO_CHAT_ID_QUI")

# File dove salviamo le notizie già inviate (evita duplicati)
SENT_FILE = "sent_news.json"

# ============================================================
#  FONTI DI NOTIZIE
# ============================================================
SOURCES = [
    {
        "name": "Vivere Senigallia",
        "type": "rss",
        "url": "https://www.viveresenigallia.it/rss/",
        "keyword": "arcevia",   # filtra solo notizie che contengono questa parola
        "emoji": "📰"
    },
    {
        "name": "Ancona Today",
        "type": "rss",
        "url": "https://www.anconatoday.it/rss/arcevia.xml",
        "keyword": None,  # già filtrato per Arcevia dall'URL
        "emoji": "🗞️"
    },
    {
        "name": "Cronache Ancona",
        "type": "rss",
        "url": "https://www.cronacheancona.it/categoria/comuni/arcevia/feed/",
        "keyword": None,
        "emoji": "📋"
    },
    {
        "name": "Corriere Adriatico",
        "type": "scraping",
        "url": "https://www.corriereadriatico.it/t/arcevia",
        "keyword": "arcevia",
        "emoji": "🗺️"
    },
]

# ============================================================
#  GESTIONE NOTIZIE GIÀ INVIATE
# ============================================================
def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r") as f:
            return json.load(f)
    return []

def save_sent(sent):
    with open(SENT_FILE, "w") as f:
        json.dump(sent[-500:], f)  # tieni solo le ultime 500

def make_id(url, title):
    return hashlib.md5(f"{url}{title}".encode()).hexdigest()

# ============================================================
#  LETTURA FEED RSS
# ============================================================
def fetch_rss(source):
    news = []
    try:
        feed = feedparser.parse(source["url"])
        for entry in feed.entries[:10]:  # ultimi 10 articoli
            title = entry.get("title", "")
            link  = entry.get("link", "")
            desc  = entry.get("summary", "")

            # Filtra per parola chiave se necessario
            if source["keyword"]:
                kw = source["keyword"].lower()
                if kw not in title.lower() and kw not in desc.lower():
                    continue

            news.append({
                "title": title,
                "link": link,
                "source": source["name"],
                "emoji": source["emoji"],
            })
    except Exception as e:
        print(f"[ERRORE RSS] {source['name']}: {e}")
    return news

# ============================================================
#  SCRAPING (per Corriere Adriatico)
# ============================================================
def fetch_scraping(source):
    news = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(source["url"], headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        # Cerca tutti i link articolo nella pagina
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            link  = a["href"]

            # Salta link troppo corti o di navigazione
            if len(title) < 20:
                continue
            if not link.startswith("http"):
                link = "https://www.corriereadriatico.it" + link

            kw = source["keyword"].lower()
            if kw not in title.lower() and kw not in link.lower():
                continue

            news.append({
                "title": title,
                "link": link,
                "source": source["name"],
                "emoji": source["emoji"],
            })

        # Rimuovi duplicati per link
        seen = set()
        unique = []
        for n in news:
            if n["link"] not in seen:
                seen.add(n["link"])
                unique.append(n)
        news = unique[:10]

    except Exception as e:
        print(f"[ERRORE SCRAPING] {source['name']}: {e}")
    return news

# ============================================================
#  INVIO MESSAGGIO TELEGRAM
# ============================================================
def send_telegram(title, link, source, emoji):
    text = (
        f"{emoji} <b>{source}</b>\n"
        f"📌 {title}\n"
        f"🔗 <a href='{link}'>Leggi l'articolo</a>"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code != 200:
            print(f"[ERRORE TELEGRAM] {r.text}")
        else:
            print(f"[INVIATO] {title[:60]}...")
    except Exception as e:
        print(f"[ERRORE INVIO] {e}")

# ============================================================
#  CICLO PRINCIPALE
# ============================================================
def check_news():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Controllo notizie...")
    sent = load_sent()
    new_count = 0

    for source in SOURCES:
        if source["type"] == "rss":
            articles = fetch_rss(source)
        else:
            articles = fetch_scraping(source)

        for article in articles:
            uid = make_id(article["link"], article["title"])
            if uid not in sent:
                send_telegram(
                    article["title"],
                    article["link"],
                    article["source"],
                    article["emoji"]
                )
                sent.append(uid)
                new_count += 1
                time.sleep(1)  # pausa tra un messaggio e l'altro

    save_sent(sent)
    print(f"[FINE] {new_count} nuove notizie inviate.")

# ============================================================
#  AVVIO
# ============================================================
if __name__ == "__main__":
    import sys
    once = "--once" in sys.argv  # GitHub Actions usa --once

    print("🤖 Bot Notizie Arcevia avviato!")
    if once:
        check_news()
    else:
        print("Controlla le notizie ogni ora. Premi Ctrl+C per fermare.\n")
        while True:
            check_news()
            print("Prossimo controllo tra 60 minuti...")
            time.sleep(3600)

# patch: support --once flag
import sys as _sys
if __name__ == "__main__" and "--once" in _sys.argv:
    pass  # handled below
