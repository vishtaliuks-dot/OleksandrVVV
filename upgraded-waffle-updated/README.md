# Zaktualizowany sklep Telegram

## Co zawiera
- Kategorie: Kartridze, Razki, Liquidy.
- Panel operatora w Mini App: dodawanie i usuwanie produktów.
- Produkty i kategorie zapisują się w SQLite.
- Zamówienia i powiadomienia kuriera zachowane.
- Dostęp do panelu operatora sprawdzany po Telegram ID na serwerze.

## Wgranie na GitHub
1. Zrób kopię aktualnego repozytorium.
2. Podmień `bot.py` i `requirements.txt`.
3. Podmień `static/index.html` plikiem z tego pakietu.
4. Dodaj `OPERATOR_IDS` w Render → Environment.
5. W Telegramie wyślij botowi `/myid`, skopiuj ID i wklej jako wartość `OPERATOR_IDS`.
6. Upewnij się, że `BOT_TOKEN` i `MINI_APP_URL` w Render są prawidłowe.
7. Zapisz zmienne i wykonaj redeploy.

## Ważne dla Render
SQLite musi być na trwałym dysku Render, jeśli produkty mają przetrwać redeploy. Utwórz Persistent Disk i ustaw `DB_PATH` na przykład na `/var/data/sklep.db` (ścieżka musi znajdować się w punkcie montowania dysku). Nie kasuj starej bazy, jeśli chcesz zachować wcześniejsze zamówienia.

## Panel operatora
Po uruchomieniu otwórz sklep przez Telegram. Operator z ID wpisanym w `OPERATOR_IDS` zobaczy sekcję „Panel operatora”. Pozostali klienci jej nie zobaczą, a serwer odrzuci ich próby dodawania i usuwania produktów.

## Uwaga
Początkowe siedem produktów jest przykładowo wpisanych do bazy przy jej pierwszym utworzeniu. Kategoria początkowa to „Liquidy”, a cena 0 oznacza, że operator powinien ustawić prawidłową cenę w panelu. Nie umieszczaj tokenu bota w plikach ani publicznym repozytorium.
