import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo, MenuButtonWebApp
from fastapi import FastAPI, Header, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MINI_APP_URL = os.getenv("MINI_APP_URL", "").strip().rstrip("/")
COURIER_USERNAME = os.getenv("COURIER_USERNAME", "florida_operator").strip().lstrip("@")
DB_PATH = os.getenv("DB_PATH", "sklep.db")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
OPERATOR_IDS = {int(x.strip()) for x in os.getenv("OPERATOR_IDS", "").split(",") if x.strip().isdigit()}
STATIC_DIR = Path(__file__).parent / "static"
STATIC_INDEX = STATIC_DIR / "index.html"
CATEGORIES = ("Kartridze", "Razki", "Liquidy")
ORDER_STATUSES = ("Nowe", "W realizacji", "Zakończone", "Anulowane")
MAX_IMAGE_BYTES = 5 * 1024 * 1024

if not BOT_TOKEN:
    raise RuntimeError("Brak BOT_TOKEN. Ustaw BOT_TOKEN w Render → Environment.")
if not MINI_APP_URL.startswith("https://"):
    raise RuntimeError("Brak poprawnego MINI_APP_URL. Ustaw pełny adres HTTPS usługi Render.")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR).mkdir(parents=True, exist_ok=True)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI(title="Florida Vape Mini App")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


def connect_db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def columns(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db():
    with connect_db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_day TEXT NOT NULL,
            city TEXT NOT NULL,
            products TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0,
            photo TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        # Add columns without deleting existing products or orders.
        product_cols = columns(con, "products")
        for name, definition in {
            "short_description": "TEXT NOT NULL DEFAULT ''",
            "description": "TEXT NOT NULL DEFAULT ''",
            "stock": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in product_cols:
                con.execute(f"ALTER TABLE products ADD COLUMN {name} {definition}")
        order_cols = columns(con, "orders")
        for name, definition in {
            "status": "TEXT NOT NULL DEFAULT 'Nowe'",
            "customer_name": "TEXT NOT NULL DEFAULT ''",
            "username": "TEXT NOT NULL DEFAULT ''",
            "total_price": "REAL NOT NULL DEFAULT 0",
        }.items():
            if name not in order_cols:
                con.execute(f"ALTER TABLE orders ADD COLUMN {name} {definition}")
        count = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            initial = [
                ("ELFLIQ - Blue Razz Lemonade", "Liquidy", 0, "https://www.liqua-online.com/2470-default_md/elfliq-blue-razz-lemonade-elfbar.webp", "", "", 0),
                ("ELFLIQ - Blueberry Rose Mint", "Liquidy", 0, "https://www.liqua-online.com/2478-default_md/elfliq-blueberry-elfbar.webp", "", "", 0),
                ("ELFLIQ - Cola", "Liquidy", 0, "https://www.liqua-online.com/2512-default_md/elfliq-cola-elfbar.webp", "", "", 0),
                ("ELFLIQ - Cool Mint", "Liquidy", 0, "https://www.liqua-online.com/2466-default_md/elfliq-spearmint-elfbar.webp", "", "", 0),
                ("ELFBULL Ice", "Liquidy", 0, "https://www.liqua-online.com/2489-default_md/elfliq-elfbull-ice-elfbar.webp", "", "", 0),
                ("ELFLIQ - Lemon Lime", "Liquidy", 0, "https://www.liqua-online.com/2500-default_md/elfliq-lemon-lime-elfbar.webp", "", "", 0),
                ("ELFLIQ - Strawberry Snow", "Liquidy", 0, "https://www.liqua-online.com/2453-default_md/elfliq-strawberry-ice-elfbar.webp", "", "", 0),
            ]
            con.executemany("INSERT INTO products(name,category,price,photo,short_description,description,stock) VALUES(?,?,?,?,?,?,?)", initial)


def validate_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Otwórz sklep przez Telegram.")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Nieprawidłowe dane Telegrama.")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="Nie udało się potwierdzić danych Telegrama.")
    try:
        auth_date = int(pairs.get("auth_date", "0") or "0")
    except ValueError:
        auth_date = 0
    if not auth_date or time.time() - auth_date > 86400:
        raise HTTPException(status_code=401, detail="Dane Telegrama wygasły. Otwórz sklep ponownie.")
    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="Nieprawidłowe dane użytkownika.")
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="Nie znaleziono użytkownika Telegrama.")
    return user


def require_operator(init_data: str) -> dict:
    user = validate_init_data(init_data)
    if int(user["id"]) not in OPERATOR_IDS:
        raise HTTPException(status_code=403, detail="Brak uprawnień operatora.")
    return user


class OrderRequest(BaseModel):
    init_data: str
    city: str = Field(min_length=1, max_length=100)
    product_ids: list[int] = Field(min_length=1, max_length=50)
    age_confirmed: bool = False


class ProductInput(BaseModel):
    init_data: str
    name: str = Field(min_length=1, max_length=160)
    category: str
    price: float = Field(ge=0, le=100000)
    photo: str = Field(default="", max_length=1000)
    short_description: str = Field(default="", max_length=240)
    description: str = Field(default="", max_length=4000)
    stock: int = Field(default=0, ge=0, le=1000000)


class OrderStatusInput(BaseModel):
    init_data: str
    status: str


@dp.message(CommandStart())
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛍️ Otwórz Florida Vape", web_app=WebAppInfo(url=MINI_APP_URL))]])
    await message.answer("Witaj w Florida Vape. Kliknij poniżej, aby otworzyć sklep.", reply_markup=keyboard)


@dp.message(Command("myid"))
async def myid(message: Message):
    await message.answer(f"Twoje numeryczne Telegram ID: {message.from_user.id}")


@dp.message(Command("health"))
async def health(message: Message):
    await message.answer("Florida Vape działa.")


@app.get("/")
async def home():
    if not STATIC_INDEX.exists():
        raise HTTPException(status_code=500, detail="Brak pliku static/index.html.")
    return FileResponse(str(STATIC_INDEX))


@app.get("/api/health")
async def api_health():
    return {"ok": True}


@app.get("/api/operator/check")
async def operator_check(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    user = require_operator(x_telegram_init_data)
    return {"ok": True, "operator_id": int(user["id"])}


@app.get("/api/products")
async def get_products():
    with connect_db() as con:
        rows = con.execute("SELECT id,name,category,price,photo,short_description,description,stock FROM products WHERE active=1 ORDER BY id").fetchall()
    return {"products": [dict(r) for r in rows], "categories": list(CATEGORIES)}


@app.get("/api/operator/products")
async def get_admin_products(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    require_operator(x_telegram_init_data)
    with connect_db() as con:
        rows = con.execute("SELECT id,name,category,price,photo,short_description,description,stock,active FROM products ORDER BY active DESC,id DESC").fetchall()
    return {"products": [dict(r) for r in rows]}


@app.post("/api/operator/upload-image")
async def upload_image(file: UploadFile = File(...), x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    require_operator(x_telegram_init_data)
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
    ext = allowed.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(status_code=400, detail="Wybierz zdjęcie JPG, PNG, WEBP lub GIF.")
    content = await file.read(MAX_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Zdjęcie musi mieć maksymalnie 5 MB.")
    filename = f"{uuid.uuid4().hex}{ext}"
    target = UPLOAD_DIR / filename
    target.write_bytes(content)
    return {"ok": True, "url": f"/uploads/{filename}"}


@app.post("/api/operator/products")
async def add_product(product: ProductInput):
    require_operator(product.init_data)
    if product.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Wybierz prawidłową kategorię.")
    photo = product.photo.strip()
    if photo and not photo.startswith(("https://", "http://", "/uploads/")):
        raise HTTPException(status_code=400, detail="Zdjęcie musi być przesłanym zdjęciem lub adresem http(s).")
    with connect_db() as con:
        cur = con.execute("INSERT INTO products(name,category,price,photo,short_description,description,stock,active) VALUES(?,?,?,?,?,?,?,1)",
            (product.name.strip(), product.category, product.price, photo, product.short_description.strip(), product.description.strip(), product.stock))
        new_id = cur.lastrowid
    return {"ok": True, "id": new_id}


@app.put("/api/operator/products/{product_id}")
async def update_product(product_id: int, product: ProductInput):
    require_operator(product.init_data)
    if product.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Wybierz prawidłową kategorię.")
    photo = product.photo.strip()
    if photo and not photo.startswith(("https://", "http://", "/uploads/")):
        raise HTTPException(status_code=400, detail="Nieprawidłowy adres zdjęcia.")
    with connect_db() as con:
        cur = con.execute("UPDATE products SET name=?,category=?,price=?,photo=?,short_description=?,description=?,stock=? WHERE id=?",
            (product.name.strip(), product.category, product.price, photo, product.short_description.strip(), product.description.strip(), product.stock, product_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Nie znaleziono produktu.")
    return {"ok": True}


@app.delete("/api/operator/products/{product_id}")
async def delete_product(product_id: int, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    require_operator(x_telegram_init_data)
    with connect_db() as con:
        cur = con.execute("UPDATE products SET active=0 WHERE id=? AND active=1", (product_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Nie znaleziono aktywnego produktu.")
    return {"ok": True}


class ProductDelete(BaseModel):
    init_data: str


@app.post("/api/operator/products/{product_id}/restore")
async def restore_product(product_id: int, payload: ProductDelete):
    require_operator(payload.init_data)
    with connect_db() as con:
        cur = con.execute("UPDATE products SET active=1 WHERE id=?", (product_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Nie znaleziono produktu.")
    return {"ok": True}


@app.get("/api/operator/orders")
async def get_orders(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    require_operator(x_telegram_init_data)
    with connect_db() as con:
        rows = con.execute("SELECT id,user_id,created_day,city,products,status,customer_name,username,total_price FROM orders ORDER BY id DESC LIMIT 200").fetchall()
    return {"orders": [dict(r) for r in rows]}


@app.patch("/api/operator/orders/{order_id}")
async def update_order_status(order_id: int, payload: OrderStatusInput):
    require_operator(payload.init_data)
    if payload.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Nieprawidłowy status zamówienia.")
    with connect_db() as con:
        cur = con.execute("UPDATE orders SET status=? WHERE id=?", (payload.status, order_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Nie znaleziono zamówienia.")
    return {"ok": True}


@app.post("/api/order")
async def create_order(order: OrderRequest):
    user = validate_init_data(order.init_data)
    if not order.age_confirmed:
        raise HTTPException(status_code=400, detail="Potwierdź wymagany wiek.")
    if not order.city.strip():
        raise HTTPException(status_code=400, detail="Wybierz miasto.")
    ids = list(dict.fromkeys(order.product_ids))
    placeholders = ",".join("?" for _ in ids)
    with connect_db() as con:
        rows = con.execute(f"SELECT id,name,price,stock FROM products WHERE active=1 AND id IN ({placeholders})", ids).fetchall()
        by_id = {int(r["id"]): r for r in rows}
        if len(by_id) != len(ids):
            raise HTTPException(status_code=400, detail="Jeden z produktów jest już niedostępny.")
        if any(int(by_id[i]["stock"]) <= 0 for i in ids):
            raise HTTPException(status_code=400, detail="Jeden z produktów jest niedostępny w magazynie.")
        names = [by_id[i]["name"] for i in ids]
        total = sum(float(by_id[i]["price"]) for i in ids)
        day = time.strftime("%Y-%m-%d", time.localtime())
        count = con.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND created_day=?", (int(user["id"]), day)).fetchone()[0]
        if count >= 2:
            raise HTTPException(status_code=429, detail="Dzienny limit zamówień został osiągnięty.")
        # Update stock only after validating all products.
        for i in ids:
            con.execute("UPDATE products SET stock=stock-1 WHERE id=? AND stock>0", (i,))
        customer_name = " ".join([user.get("first_name", ""), user.get("last_name", "")]).strip()
        username = user.get("username", "")
        cur = con.execute("INSERT INTO orders(user_id,created_day,city,products,status,customer_name,username,total_price) VALUES(?,?,?,?,?,?,?,?)",
            (int(user["id"]), day, order.city.strip()[:100], "\n".join(names), "Nowe", customer_name, username, total))
        order_id = cur.lastrowid
    message_text = (f"🛒 FLORIDA VAPE — NOWE ZAMÓWIENIE #{order_id}\n\nKlient: {customer_name or 'Nie podano'}\nTelegram: @{username if username else 'brak username'}\nID klienta: {user['id']}\nMiasto: {order.city.strip()}\nWartość: {total:.2f} zł\n\nProdukty:\n" + "\n".join("• " + n for n in names))
    for operator_id in OPERATOR_IDS:
        try:
            await bot.send_message(operator_id, message_text)
        except Exception as exc:
            print(f"Nie udało się powiadomić operatora {operator_id}: {exc!r}")
    return {"ok": True, "order_id": order_id, "courier_url": f"https://t.me/{COURIER_USERNAME}"}


async def run_web():
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")), log_level="info")
    await uvicorn.Server(config).serve()


async def main():
    init_db()
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Sklep", web_app=WebAppInfo(url=MINI_APP_URL)))
    except Exception as exc:
        print(f"Nie udało się ustawić przycisku menu: {exc!r}")
    await asyncio.gather(dp.start_polling(bot), run_web())


if __name__ == "__main__":
    asyncio.run(main())
