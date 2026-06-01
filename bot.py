import feedparser
import requests
import sqlite3
import hashlib
import os
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup

# ============================================================
#  CONFIGURAZIONE — inserisci qui i tuoi dati
# ============================================================
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "IL_TUO_TOKEN_QUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "IL_TUO_CHAT_ID_QUI")

DB_PATH = "news.db"

# ============================================================
#  FONTI DI NOTIZIE
# ============================================================
SOURCES = [
    {
        "name": "Vivere Senigallia",
        "type": "rss",
        "url": "https://www.viveresenigallia.it/rss/",
        "keyword": "arcevia",
        "emoji": "📰"
    },
    {
        "name": "Ancona Today",
        "type": "rss",
        "url": "https://www.anconatoday.it/rss/arcevia.xml",
        "keyword": None,
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
#  DATABASE SQLite
# ============================================================
class DB:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sent (
                id       TEXT PRIMARY KEY,
                title    TEXT,
                source   TEXT,
                sent_at  TEXT
            )
        """)
        self.conn.commit()

    def is_sent(self, url, title):
        """Restituisce (uid, già_inviato)."""
        uid = hashlib.md5(f"{url}{title}".encode()).hexdigest()
        row = self.conn.execute(
            "SELECT 1 FROM sent WHERE id = ?", (uid,)
        ).fetchone()
        return uid, bool(row)

    def mark_sent(self, uid, title, source):
        self.conn.execute(
            "INSERT OR IGNORE INTO sent (id, title, source, sent_at) VALUES (?, ?, ?, ?)",
            (uid, title, source, datetime.now().isoformat())
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

# ============================================================
#  LETTURA FEED RSS
# ============================================================
def fetch_rss(source):
    news = []
    try:
        feed = feedparser.parse(source["url"])
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            link  = entry.get("link", "")
            desc  = entry.get("summary", "")

            if source["keyword"]:
                kw = source["keyword"].lower()
                if kw not in title.lower() and kw not in desc.lower():
                    continue

            news.append({
                "title":    title,
                "link":     link,
                "source":   source["name"],
                "emoji":    source["emoji"],
                "pub_date": entry.get("published", ""),
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

        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            link  = a["href"]

            if len(title) < 20:
                continue
            if not link.startswith("http"):
                link = "https://www.corriereadriatico.it" + link

            kw = source["keyword"].lower()
            if kw not in title.lower() and kw not in link.lower():
                continue

            news.append({
                "title":    title,
                "link":     link,
                "source":   source["name"],
                "emoji":    source["emoji"],
                "pub_date": "",
            })

        # Rimuovi duplicati per link
        seen, unique = set(), []
        for n in news:
            if n["link"] not in seen:
                seen.add(n["link"])
                unique.append(n)
        news = unique[:10]

    except Exception as e:
        print(f"[ERRORE SCRAPING] {source['name']}: {e}")
    return news

# ============================================================
#  FORMATTAZIONE DATA
# ============================================================
def format_date(pub_date):
    """Converte la data RSS in formato leggibile (es. '01 giu 2025')."""
    if not pub_date:
        return ""
    try:
        dt = parsedate_to_datetime(pub_date)
        mesi = {
            "Jan": "gen", "Feb": "feb", "Mar": "mar", "Apr": "apr",
            "May": "mag", "Jun": "giu", "Jul": "lug", "Aug": "ago",
            "Sep": "set", "Oct": "ott", "Nov": "nov", "Dec": "dic"
        }
        data_en = dt.strftime("%d %b %Y")
        for en, it in mesi.items():
            data_en = data_en.replace(en, it)
        return data_en
    except Exception:
        return ""

# ============================================================
#  INVIO MESSAGGIO TELEGRAM — singola notizia
# ============================================================
def send_telegram(title, link, source, emoji, pub_date=""):
    date_str = format_date(pub_date)
    footer   = f"📅 {date_str}  ·  " if date_str else ""

    text = (
        f"<b>{emoji} {source}</b>\n"
        f"\n"
        f"{title}\n"
        f"\n"
        f"<i>{footer}<a href='{link}'>Leggi l'articolo →</a></i>"
    )
    _send_raw(text)

# ============================================================
#  INVIO MESSAGGIO RIEPILOGO ORARIO
# ============================================================
def send_summary(new_count, sources_summary):
    if new_count == 0:
        return

    ora   = datetime.now().strftime("%H:%M")
    lines = [f"📬 <b>{new_count} nuove notizie da Arcevia</b>  —  ore {ora}\n"]
    for nome, count in sources_summary.items():
        if count > 0:
            lines.append(f"  • {nome}: {count}")

    _send_raw("\n".join(lines))

# ============================================================
#  INVIO RAW
# ============================================================
def _send_raw(text):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id":                  TELEGRAM_CHAT_ID,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code != 200:
            print(f"[ERRORE TELEGRAM] {r.text}")
    except Exception as e:
        print(f"[ERRORE INVIO] {e}")

# ============================================================
#  CICLO PRINCIPALE
# ============================================================
def check_news():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Controllo notizie...")
    db        = DB()
    new_count = 0
    sources_summary = {}

    for source in SOURCES:
        articles = fetch_rss(source) if source["type"] == "rss" else fetch_scraping(source)

        source_count = 0
        for article in articles:
            uid, already_sent = db.is_sent(article["link"], article["title"])
            if not already_sent:
                send_telegram(
                    article["title"],
                    article["link"],
                    article["source"],
                    article["emoji"],
                    article.get("pub_date", ""),
                )
                db.mark_sent(uid, article["title"], article["source"])
                print(f"[INVIATO] {article['title'][:60]}...")
                new_count    += 1
                source_count += 1
                time.sleep(1)

        sources_summary[source["name"]] = source_count

    send_summary(new_count, sources_summary)
    db.close()
    print(f"[FINE] {new_count} nuove notizie inviate.")

# ============================================================
#  AVVIO
# ============================================================
if __name__ == "__main__":
    import sys
    once = "--once" in sys.argv

    print("🤖 Bot Notizie Arcevia avviato!")
    if once:
        check_news()
    else:
        print("Controlla le notizie ogni ora. Premi Ctrl+C per fermare.\n")
        while True:
            check_news()
            print("Prossimo controllo tra 60 minuti...")
            time.sleep(3600)
