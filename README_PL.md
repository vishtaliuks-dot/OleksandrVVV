# Florida Vape — żółto-biała wersja

## Pliki
- `bot.py` — bot Telegram + serwer Mini App. Token i adresy wpisuje się w sekcji KONFIGURACJA.
- `static/index.html` — responsywny interfejs żółto-biały.
- `requirements.txt` — biblioteki Python.
- `render.yaml` — przykładowa konfiguracja uruchomienia na Render.

## Konfiguracja
1. W `bot.py` wklej token otrzymany od `@BotFather` do `BOT_TOKEN`.
2. Utwórz usługę Web Service na Render z tego repozytorium.
3. W `APP_URL` wpisz dokładny publiczny adres HTTPS Render, np. `https://twoja-usluga.onrender.com`.
4. W `OPERATOR_IDS` wpisz swoje numeryczne Telegram ID, np. `[123456789]`, aby dostawać powiadomienia.
5. Ustaw Build Command: `pip install -r requirements.txt`.
6. Ustaw Start Command: `python bot.py`.
7. W Telegramie otwórz bota i wyślij `/start`.

**Bezpieczeństwo:** nie umieszczaj prawdziwego tokena w publicznym repozytorium. Jeśli kod jest publiczny, najbezpieczniej przechowywać token jako zmienną środowiskową w Render. Jeśli token został już opublikowany, unieważnij go w `@BotFather`.

## Ważne
To jest nowy szkielet aplikacji. W tabeli produktów dodano trzy przykładowe pozycje z ceną 0 i stanem 0 — uzupełnij dane przed użyciem. Funkcje panelu operatora ze starszej wersji nie są częścią tego uproszczonego zestawu. Przed wdrożeniem produkcyjnym należy dodać kryptograficzną weryfikację `Telegram WebApp initData` po stronie serwera.
