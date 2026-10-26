import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, MenuButtonWebApp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn

# ===================== KONFIGURACJA =====================
# Wklej token od @BotFather pomiędzy cudzysłowy.
BOT_TOKEN = "WKLEJ_TUTAJ_TOKEN_OD_BOTFATHER"

# Wklej publiczny adres HTTPS swojej usługi Render.
APP_URL = "https://TWOJ-SERWIS.onrender.com"
MINI_APP_URL = APP_URL
COURIER_USERNAME = "florida_dostawa"  # bez znaku @
OPERATOR_IDS = []  # np. [123456789] — wpisz swoje numeryczne Telegram ID
DB_PATH = os.getenv("DB_PATH", "florida_vape.db")
# ========================================================

BASE_DIR = Path(__file__).resolve().parent
STATIC_FILE = BASE_DIR / "static" / "index.html"
CATEGORIES = ["Kartridze", "Razki", "Liquidy"]

if BOT_TOKEN == "WKLEJ_TUTAJ_TOKEN_OD_BOTFATHER":
    raise RuntimeError("Otwórz bot.py i wklej token od @BotFather do BOT_TOKEN.")
if not MINI_APP_URL.startswith("https://") or "TWOJ-SERWIS" in MINI_APP_URL:
    raise RuntimeError("Wklej prawdziwy adres HTTPS Render do APP_URL w bot.py.")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
app = FastAPI(title="Florida Vape Mini App")


def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, category TEXT NOT NULL, price REAL NOT NULL DEFAULT 0,
            photo TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
            stock INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            created_day TEXT NOT NULL, city TEXT NOT NULL, products TEXT NOT NULL,
            customer_name TEXT NOT NULL, username TEXT NOT NULL, total REAL NOT NULL
        )""")
        count = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            starter = [
                ("Produkt 1 — uzupełnij nazwę", "Kartridze", 0, "", "Dodaj opis produktu", 0),
                ("Produkt 2 — uzupełnij nazwę", "Razki", 0, "", "Dodaj opis produktu", 0),
                ("Produkt 3 — uzupełnij nazwę", "Liquidy", 0, "", "Dodaj opis produktu", 0),
            ]
            con.executemany(
                "INSERT INTO products(name,category,price,photo,description,stock) VALUES(?,?,?,?,?,?)",
                starter,
            )


@dp.message(CommandStart())
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛍️ Otwórz Florida Vape", web_app=WebAppInfo(url=MINI_APP_URL))
    ]])
    await message.answer(
        "Witaj w Florida Vape!\nKliknij przycisk poniżej, aby otworzyć sklep.",
        reply_markup=keyboard,
    )


@dp.message(Command("myid"))
async def myid(message: Message):
    await message.answer(f"Twoje Telegram ID: {message.from_user.id}")


@app.get("/")
async def home():
    if not STATIC_FILE.exists():
        raise HTTPException(status_code=500, detail="Brakuje pliku static/index.html")
    return FileResponse(STATIC_FILE)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/products")
async def products():
    with db() as con:
        rows = con.execute(
            "SELECT id,name,category,price,photo,description,stock FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
    return {"products": [dict(r) for r in rows], "categories": CATEGORIES}


class OrderRequest(BaseModel):
    init_data: str = ""
    city: str = Field(min_length=1, max_length=100)
    product_ids: list[int] = Field(min_length=1, max_length=30)
    age_confirmed: bool = False


@app.post("/api/order")
async def order(payload: OrderRequest):
    if not payload.age_confirmed:
        raise HTTPException(status_code=400, detail="Potwierdź wymagany wiek.")
    if not payload.init_data:
        raise HTTPException(status_code=401, detail="Otwórz sklep przez Telegram, aby złożyć zamówienie.")
    # Telegram WebApp initData is passed to the order handler for identity.
    # For production, validate initData cryptographically before accepting orders.
    from urllib.parse import parse_qs
    import urllib.parse
    try:
        pairs = parse_qs(payload.init_data, keep_blank_values=True)
        user_raw = pairs.get("user", ["{}"])[0]
        user = json.loads(user_raw)
        user_id = int(user["id"])
    except Exception:
        raise HTTPException(status_code=401, detail="Nie udało się odczytać danych Telegrama.")
    ids = list(dict.fromkeys(payload.product_ids))
    with db() as con:
        day = time.strftime("%Y-%m-%d", time.localtime())
        if con.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND created_day=?", (user_id, day)).fetchone()[0] >= 2:
            raise HTTPException(status_code=429, detail="Wykorzystano dzienny limit 2 zamówień.")
        marks = ",".join("?" for _ in ids)
        rows = con.execute(
            f"SELECT id,name,price,stock FROM products WHERE active=1 AND id IN ({marks})", ids
        ).fetchall()
        found = {r["id"]: r for r in rows}
        if len(found) != len(ids):
            raise HTTPException(status_code=400, detail="Produkt nie jest już dostępny.")
        if any(found[i]["stock"] <= 0 for i in ids):
            raise HTTPException(status_code=400, detail="Brak produktu w magazynie.")
        names = [found[i]["name"] for i in ids]
        total = sum(float(found[i]["price"]) for i in ids)
        for i in ids:
            con.execute("UPDATE products SET stock=stock-1 WHERE id=? AND stock>0", (i,))
        name = " ".join([user.get("first_name", ""), user.get("last_name", "")]).strip()
        username = user.get("username", "")
        cur = con.execute(
            "INSERT INTO orders(user_id,created_day,city,products,customer_name,username,total) VALUES(?,?,?,?,?,?,?)",
            (user_id, day, payload.city, "\n".join(names), name, username, total),
        )
        order_id = cur.lastrowid

    text = (
        f"🛍️ FLORIDA VAPE — ZAMÓWIENIE #{order_id}\n\n"
        f"Klient: {name or 'nie podano'}\n"
        f"Telegram: @{username or 'brak'}\nID: {user_id}\n"
        f"Miasto: {payload.city}\nSuma: {total:.2f} zł\n\n"
        + "\n".join("• " + n for n in names)
    )
    for operator_id in OPERATOR_IDS:
        try:
            await bot.send_message(operator_id, text)
        except Exception as exc:
            print("Nie udało się wysłać powiadomienia:", exc)
    return {"ok": True, "order_id": order_id, "courier_url": f"https://t.me/{COURIER_USERNAME}"}


async def run_web():
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")), log_level="info")
    await uvicorn.Server(config).serve()


async def main():
    init_db()
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Sklep", web_app=WebAppInfo(url=MINI_APP_URL))
        )
    except Exception as exc:
        print("Nie udało się ustawić menu Mini App:", exc)
    await asyncio.gather(dp.start_polling(bot), run_web())


if __name__ == "__main__":
    asyncio.run(main())
