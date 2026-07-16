"""Доменная логика студии: Telegram Bot API, медиа, AI, планировщик.

HTTP-слой живёт в server.py и импортирует всё отсюда. BOT_USERNAME
заполняется сервером при старте (getMe) — читать через core.BOT_USERNAME.
"""

import json
import logging
import os
import re
import socket
import time
import requests

import storage
from env_utils import load_env
from s3_utils import S3Storage

load_env()

s3 = S3Storage()

BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_KEY")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

PORT = int(os.environ.get("PORT", "8080"))
# фронтенд и PWA-статика лежат в web/ рядом с пакетом app/
WEB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
EDITOR_FILE = os.path.join(WEB_DIR, "editor.html")
# React-сборка (Vite): если dist/ есть — отдаём SPA, иначе старый editor.html
DIST_DIR = os.path.join(WEB_DIR, "dist")
DIST_INDEX = os.path.join(DIST_DIR, "index.html")
LOGIN_CODES_FILE = "login_codes.json"

log = logging.getLogger("editor-server")

BOT_USERNAME = ""  # заполняется в main() из getMe

# Плейсхолдер картинки в markdown-черновике
TG_FILE_RE = re.compile(r"tg-file://([A-Za-z0-9_-]+)")

# Одноразовый хостинг-трамплин: перезаливка медиа, которые серверы Telegram
# не могут скачать сами (файлы из хранилища Telegram; S3 — только если
# включён S3_TRAMPOLINE=1, это нужно для недоступных Telegram хостингов
# вроде Selectel; Yandex Object Storage доступен напрямую)
LITTERBOX_API = "https://litterbox.catbox.moe/resources/internals/api.php"
S3_TRAMPOLINE = os.environ.get("S3_TRAMPOLINE", "0") == "1"

# Через сколько секунд зависший «sending» считается прерванным
SENDING_STALE_AFTER = 180

# ── AI-помощник: Ollama ─────────────────────────────
# Без ключа — локальный демон (OLLAMA_URL=http://localhost:11434).
# С OLLAMA_API_KEY — облако ollama.com напрямую, демон не нужен:
#   OLLAMA_URL=https://ollama.com  OLLAMA_API_KEY=<ключ из settings/keys>
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "gemma4:12b-mlx")

# ── Промпты AI-помощника ────────────────────────────
# Каждое действие — свой system-промпт, few-shot примеры (пары user/assistant
# в истории чата: для моделей 12–32B это главный рычаг качества, особенно
# с экзотической разметкой вроде ==маркера== и ||спойлера||) и свои
# параметры сэмплирования: точечным правкам — низкая температура.

AI_FORMAT_GUIDE = """Доступная разметка Rich Markdown (Telegram Bot API 10.1) — и когда её применять:
- Заголовки # … ###### — только чтобы разбить длинный пост (от 4 абзацев) на смысловые блоки. В коротком посте не нужны.
- **жирный** — 1–2 самых важных факта на весь пост (дата, число, ключевой вывод). Не для целых предложений.
- _курсив_ — лёгкий смысловой акцент или термин, вводимый впервые.
- ~~зачёркнутый~~ — то, что отменено или устарело (было → стало).
- <u>подчёркнутый</u> — редко, для одного термина, который нужно выделить иначе, чем жирным.
- ==выделение маркером== — то, что читатель должен запомнить и унести с собой (вывод, правило, цифра).
- ||спойлер|| — ответ на загадку, интригу или неожиданный поворот, который не должен быть виден сразу.
- `код в строке` — имена команд, файлов, переменных, путей.
- блок кода ```язык … ``` — фрагмент кода длиннее одной команды.
- Формулы LaTeX: $x^2$ в строке для короткого выражения, $$…$$ блоком для формулы, которая заслуживает отдельной строки.
- <sub>текст</sub> / <sup>текст</sup> — подстрочный/надстрочный индекс (химические формулы, степени, сноски-цифры).
- > текст — короткая цитата внутри абзаца.
- <aside>текст<cite>Автор</cite></aside> — выносная цитата или ключевая мысль поста, оформленная как отдельный блок.
- Списки -, 1. — перечисление из 3+ однородных пунктов. Чекбоксы - [ ] / - [x] — только для реального чек-листа действий.
- --- — разделитель между несвязанными смысловыми блоками поста (не между обычными абзацами). Именно три дефиса: одиночное тире — или подчёркивание разделителем не являются.
- Таблицы GFM (разделитель ---) — сравнение нескольких значений по нескольким признакам; не для двух-трёх фактов подряд.
- Сноски [^1] с определением [^1]: текст — уточнение, которое отвлекает от основного текста, если вставить его инлайном.
- <details><summary>Заголовок</summary>текст</details> — длинные необязательные подробности (полный список, инструкция), которые не все читатели захотят разворачивать.
- <footer>текст</footer> — подпись поста или дисклеймер в конце (хэштеги, источник, «реклама»).
- [текст](https://…) — гиперссылка, если в запросе или исходном тексте есть конкретный адрес.
Одиночный перенос строки склеивается в пробел — абзацы разделяются пустой строкой.
Теги пиши в точности как в списке выше — без атрибутов, стилей и выдуманных вариантов.
Никогда не придумывай и не добавляй от себя медиа ![](...), коллаж <tg-collage>, слайд-шоу <tg-slideshow>, карту <tg-map> или дату-время tg://time — эти элементы требуют реальных ссылок, координат или времени от пользователя, которых у тебя нет."""

_ANSWER_RULE = ("В ответе — ТОЛЬКО готовый текст: без пояснений, без вступлений "
                "вроде «Вот текст:», без обёртки ```.")

# Маркеры фрагмента внутри полного поста (контекст правки)
FRAG_OPEN, FRAG_CLOSE = "<<<", ">>>"

# Пресеты тона для generate/rewrite (format слова не меняет — тон там
# неприменим). Каждый пресет — конкретные признаки + пример звучания:
# для модели 12–32B короткая инструкция «пиши дружелюбно» тонет за
# few-shot примерами, а образец фразы в нужном тоне — нет.
AI_TONES: dict[str, str] = {
    "business": (
        "ТОН ПОСТА — ДЕЛОВОЙ. Сдержанно и официально: без эмодзи, без "
        "восклицаний, без разговорных словечек. Нейтральная лексика "
        "(«сообщаем», «доступно», «подробности»), короткие точные факты.\n"
        "Пример звучания: «Завтра выйдет обновление редактора. Основные "
        "изменения касаются работы с медиа. Подробности — в следующем посте.»"
    ),
    "casual": (
        "ТОН ПОСТА — НЕФОРМАЛЬНЫЙ. Пиши как в личном блоге, будто "
        "рассказываешь приятелю: можно на «ты», разговорные обороты, "
        "лёгкий юмор, живые связки («кстати», «короче», «честно говоря»).\n"
        "Пример звучания: «Короче, завтра выкатываем обнову редактора — "
        "медиа наконец работают по-человечески. Увидите — оцените.»"
    ),
    "friendly": (
        "ТОН ПОСТА — ДРУЖЕЛЮБНЫЙ. Тепло и приветливо, на «вы», как письмо "
        "заботливого автора своим подписчикам: мягкие формулировки, "
        "можно обратиться к читателям, поблагодарить, пожелать хорошего.\n"
        "Пример звучания: «Друзья, завтра вас ждёт обновление редактора! "
        "Мы постарались сделать работу с медиа приятнее. Спасибо, что вы "
        "с нами.»"
    ),
    "expert": (
        "ТОН ПОСТА — ЭКСПЕРТНЫЙ. Уверенно и по существу, как специалист "
        "для специалистов: точные термины, конкретика, причины и цифры "
        "вместо оценок, ни воды, ни восторгов.\n"
        "Пример звучания: «В завтрашнем обновлении переработан пайплайн "
        "медиа: загрузка идёт напрямую в хранилище, превью рендерится на "
        "клиенте — это убирает двойную перезаливку файлов.»"
    ),
}

# Короткая метка тона — дублируется в конце запроса: напоминание рядом
# с местом генерации работает надёжнее, чем абзац в начале system-промпта
AI_TONE_LABELS: dict[str, str] = {
    "business": "деловой, без эмоций и восклицаний",
    "casual": "неформальный, разговорный",
    "friendly": "дружелюбный и тёплый",
    "expert": "экспертный, конкретика без воды",
}


# Посты-референсы: сколько берём и до скольких символов режем каждый —
# три поста по 1200 символов укладываются в num_ctx с запасом под сам пост
AI_REFS_MAX = 3
AI_REFS_CHARS = 1200

# Целевой объём generate по умолчанию — медиана длины опубликованных постов
# канала; без публикаций — AI_DEFAULT_WORDS. Границы отсекают выбросы
# (посты-«тесты» из пары слов и разовые лонгриды).
AI_DEFAULT_WORDS = 100
AI_WORDS_MIN, AI_WORDS_MAX = 40, 300
_MIN_SAMPLE_WORDS = 20   # короче — тестовые посты и голые медиа, не считаем


# Пользователь сам задал объём в запросе — дефолтную подпись не добавляем
_EXPLICIT_LEN_RE = re.compile(
    r"\d+\s*(?:слов|знак|символ|предложен|абзац)"
    r"|коротк|кратк|длинн|подробн|развёрнут|лонгрид"
    r"|пар[уа]\s+(?:слов|предложений|абзацев)",
    re.IGNORECASE,
)


def typical_post_words(posts: list[str]) -> int:
    """Типичная длина поста канала в словах (медиана, с ограничением)."""
    counts = sorted(n for p in posts
                    if p and (n := len(re.findall(r"\S+", p))) >= _MIN_SAMPLE_WORDS)
    if not counts:
        return AI_DEFAULT_WORDS
    median = counts[len(counts) // 2]
    return max(AI_WORDS_MIN, min(AI_WORDS_MAX, median))


def _refs_instruction(refs: list[str] | None) -> str:
    """Примеры постов канала как образец авторского стиля."""
    posts = [(r or "").strip()[:AI_REFS_CHARS]
             for r in (refs or [])[:AI_REFS_MAX] if (r or "").strip()]
    if not posts:
        return ""
    body = "\n\n---\n\n".join(posts)
    return (
        "Ниже — посты этого канала. Держись их манеры: та же длина, "
        "тот же тон, та же плотность разметки, похожие обороты и способ "
        "обращаться к читателю. Содержание не копируй — это образец "
        "стиля, а не источник фактов.\n\n"
        f"---\n\n{body}\n\n---"
    )


def _tone_instruction(tone: str | None) -> str:
    """Инструкция по тону: пресет из AI_TONES или произвольное описание."""
    tone = (tone or "").strip()
    if not tone:
        return ""
    preset = AI_TONES.get(tone)
    if preset:
        return preset
    return f"Тон и стиль поста: {tone[:200]}."

AI_ACTIONS = {
    "rewrite": {
        "system": (
            "Ты — редактор постов Telegram-канала. Тебе присылают текст, "
            "ты возвращаешь его улучшенную версию.\n\n"
            "Правила:\n"
            "1. Сохраняй смысл, язык, тон и голос автора. Убирай канцелярит, "
            "воду и повторы; делай фразы короче и живее.\n"
            "2. Сохраняй имеющуюся разметку. Новую не добавляй.\n"
            f"3. Если прислан пост целиком, а фрагмент помечен {FRAG_OPEN} и "
            f"{FRAG_CLOSE} — перепиши ТОЛЬКО фрагмент и верни только его, "
            "без маркеров. Он должен гладко стыковаться с окружающим текстом.\n"
            "4. Объём результата — примерно как у исходника.\n"
            f"5. {_ANSWER_RULE}"
        ),
        "examples": [
            (
                "Наша компания рада сообщить вам о том, что в ближайшее время "
                "нами будет произведён запуск нового продукта, который сможет "
                "помочь вам в решении ваших повседневных задач.",
                "Мы запускаем новый продукт — он возьмёт на себя ваши "
                "повседневные задачи.",
            ),
            (
                f"Пост целиком, фрагмент помечен {FRAG_OPEN} и {FRAG_CLOSE}:\n\n"
                "Утром вышло обновление 2.0.\n\n"
                f"{FRAG_OPEN}Также хотелось бы отметить тот факт, что старые "
                f"конфиги в целом продолжат своё функционирование.{FRAG_CLOSE}\n\n"
                "Подробности — в чейнджлоге.\n\n"
                "Верни ТОЛЬКО обработанный фрагмент — без маркеров и без "
                "остального текста поста.",
                "Старые конфиги продолжат работать.",
            ),
        ],
        "options": {"temperature": 0.25, "num_predict": 2048},
    },
    "format": {
        "system": (
            "Ты — верстальщик постов Telegram. Тебе присылают сырой текст, "
            "ты возвращаешь его с разметкой, НЕ меняя сами слова.\n\n"
            + AI_FORMAT_GUIDE + "\n\n"
            "Правила:\n"
            "1. Слова и их порядок не менять. Можно только добавить разметку "
            "и поправить разбиение на абзацы.\n"
            "2. Размечай только то, что улучшает читаемость: перечисления → "
            "списки, команды и имена файлов → `код`, формулы → $…$. "
            "**Жирный** — максимум 1–2 фразы и только в длинных постах "
            "(от четырёх абзацев). Заголовок # — только если первая строка "
            "текста явно заголовочная.\n"
            "3. Не переусердствуй: лучше меньше разметки, чем больше. "
            "Короткий текст в 1–3 предложения почти никогда не нуждается "
            "в разметке — верни его как есть.\n"
            "ПЛОХО (перегружено): \"# 🚀 Установка простая!\\n\\n**Сначала** "
            "вы **клонируете** репозиторий, потом **ставите** зависимости "
            "командой **npm install** и **запускаете** **npm start**.\\n\\n"
            "✅ Всё, **сервер работает**!\" — жирный в каждой фразе, "
            "заголовок и эмодзи там, где для них нет повода.\n"
            "ХОРОШО (умеренно): \"Установка простая:\\n\\n1. Клонируете "
            "репозиторий\\n2. Ставите зависимости: `npm install`\\n3. "
            "Запускаете `npm start`\\n\\nВсё, сервер работает.\" — разметка "
            "только там, где она реально помогает считать структуру.\n"
            f"4. {_ANSWER_RULE}"
        ),
        "examples": [
            (
                "Установка простая. Сначала клонируете репозиторий, потом "
                "ставите зависимости командой npm install и запускаете "
                "npm start. Всё, сервер работает.",
                "Установка простая:\n\n"
                "1. Клонируете репозиторий\n"
                "2. Ставите зависимости: `npm install`\n"
                "3. Запускаете `npm start`\n\n"
                "Всё, сервер работает.",
            ),
            (
                "Сегодня без новостей, просто хорошего вам дня.",
                "Сегодня без новостей, просто хорошего вам дня.",
            ),
        ],
        "options": {"temperature": 0.2, "num_predict": 2048},
    },
    "generate": {
        "system": (
            "Ты — автор постов Telegram-канала. По запросу пользователя "
            "пишешь готовый пост.\n\n"
            "Правила:\n"
            "1. Язык поста = язык запроса.\n"
            "2. Объём по умолчанию — примерно __WORDS__ слов: столько обычно "
            "занимает пост в этом канале. Заголовки и списки в посте такого "
            "размера не нужны. Если пользователь сам задал объём («коротко», "
            "«пара предложений», «подробно», «длинный», «со списком», "
            "конкретное число) — его просьба важнее этого правила.\n"
            "3. Разметка зависит от длины поста и от содержания.\n"
            "Короткий пост (до 3 абзацев): если в нём есть конкретный факт, "
            "который читателю нельзя пропустить (дата, время, цена, число, "
            "дедлайн), — выдели его **жирным**, один раз. Нет такого факта — "
            "обычный текст без разметки: выделение общих слов только "
            "раздражает.\n"
            "Длинный пост (от 4 абзацев) без разметки — сплошная «простыня», "
            "её бросают читать. Здесь разметка ОБЯЗАТЕЛЬНА, но дозированно: "
            "2–3 подзаголовка ##, один-два **жирных** акцента на ключевых "
            "фактах, ==маркер== на главном выводе. Эмодзи — только если "
            "просят.\n"
            "ПЛОХО (короткий, перегружен): \"# 🔥 Большая новость!\\n\\n"
            "Завтра выходит **обновление**! Мы **починили** всё, что вы "
            "**ждали**, и добавили ==кучу== **фишек**! 🚀\" — жирный и эмодзи "
            "в каждой фразе превращают пост в спам.\n"
            "ХОРОШО (короткий): \"Завтра выкатываем большое обновление бота. "
            "Починили всё, на что вы жаловались. Следите за новостями — "
            "будет подробный разбор.\" — выделять нечего, обычный текст.\n"
            "ПЛОХО (длинный): жирная фраза в каждом абзаце и заголовок над "
            "каждым вторым — текст рябит, акценты обесцениваются.\n"
            "ХОРОШО (длинный): пара подзаголовков на весь текст, один жирный "
            "факт, один ==маркер== на выводе — взгляду есть за что "
            "зацепиться, но текст остаётся текстом.\n"
            f"4. {_ANSWER_RULE}\n\n"
            + AI_FORMAT_GUIDE
        ),
        "examples": [
            # пара примеров дефолтного объёма (~AI_DEFAULT_WORDS слов) учит
            # условию: есть факт-цифра → один акцент, нет факта → без разметки.
            # Длину модель тоже держит по примерам, а не по числу в правиле
            (
                "пост о том, что завтра выйдет большое обновление бота",
                "Завтра выкатываем большое обновление бота. Главное, что "
                "изменится: починили отложенную отправку, из-за которой посты "
                "иногда уходили с опозданием, ускорили загрузку медиа и "
                "переработали вставку ссылок — превью теперь подтягивается "
                "сразу. Ещё добавили пару вещей, о которых вы не просили, но "
                "которые давно напрашивались: тёмную тему в настройках и "
                "дубль поста одной кнопкой.\n\n"
                "Обновление прилетит всем автоматически в течение дня, ничего "
                "делать не нужно. Если после апдейта что-то поведёт себя "
                "странно — напишите в комментариях, такое чиним в первую "
                "очередь. Подробный разбор всех изменений выйдет отдельным "
                "постом на выходных.",
            ),
            (
                "пост с итогами года для канала про дизайн",
                "Год получился насыщенным. Канал вырос **с двух до пятнадцати "
                "тысяч подписчиков**, а из экспериментального формата "
                "разборов выросла постоянная рубрика — судя по репостам, "
                "любимая. Спасибо за каждый комментарий: половина тем "
                "родилась именно из них.\n\n"
                "Что дальше: в январе вернёмся к еженедельным разборам, "
                "позовём практикующих дизайнеров с гостевыми постами и "
                "наконец доделаем гайд по портфолио, который откладывали "
                "весь декабрь. Если каких-то тем в этом году не хватало — "
                "напишите под этим постом, соберём план на квартал вместе.",
            ),
            (
                "пост: запись на вебинар закроется в пятницу в 18:00",
                "Успейте записаться на вебинар — приём заявок закроется "
                "**в пятницу в 18:00**. Дальше только следующий поток, "
                "а он не раньше осени.",
            ),
            (
                "подробный пост со списком: 3 причины вести телеграм-канал",
                "## Зачем вести телеграм-канал\n\n"
                "Если давно думаете начать — вот три причины перестать "
                "откладывать:\n\n"
                "1. **Прямой контакт с аудиторией.** Никаких алгоритмов "
                "ленты: подписчик видит каждый пост.\n"
                "2. **Минимум формата.** Не нужны обложки и монтаж — "
                "достаточно текста, который есть что сказать.\n"
                "3. **Архив мыслей.** Канал незаметно превращается в базу "
                "знаний, на которую удобно ссылаться.\n\n"
                "Начните с одного поста в неделю — этого достаточно.",
            ),
            # эталон длинного поста БЕЗ списка: подзаголовки, дозированные
            # акценты, маркер на выводе — иначе модель выдаёт «простыню»
            (
                "длинный пост слов на 250: как выбрать первую камеру "
                "и не переплатить",
                "## С чего начать\n\n"
                "Первая камера — почти всегда переплата за страх. Кажется, "
                "что чем дороже корпус, тем лучше снимки, поэтому новички "
                "берут технику «на вырост» и годами не используют половину "
                "функций. Правда в том, что на старте разница между камерой "
                "за 50 и за 150 тысяч видна в таблице характеристик, а не "
                "на фотографиях.\n\n"
                "Сначала определитесь, что вы снимаете. Портреты, "
                "путешествия, предметка для магазина — под каждую задачу "
                "свои требования, универсального «лучшего» варианта нет. "
                "**Для девяти новичков из десяти хватает базовой "
                "беззеркалки с китовым объективом** — она легче, дешевле "
                "и прощает ошибки.\n\n"
                "## На чём нельзя экономить\n\n"
                "Единственная статья расходов, которую не стоит резать, — "
                "стекло. Объектив живёт десятилетиями и переезжает с камеры "
                "на камеру, а корпуса устаревают за три-четыре года. Лучше "
                "простая камера со светосильным объективом, чем топовый "
                "корпус с тёмным китом.\n\n"
                "И не покупайте ничего, пока не подержали в руках: камера, "
                "которую неудобно держать, останется дома — сколько бы "
                "мегапикселей в ней ни было.\n\n"
                "==Итог: простой корпус, вложиться в объектив, проверить "
                "эргономику вживую.==",
            ),
        ],
        # 2048 токенов ≈ 800 русских слов: просьба о более длинном посте
        # упрётся в потолок — осознанный компромисс против залипания модели
        "options": {"temperature": 0.8, "num_predict": 2048},
    },
}

# Общие параметры Ollama: контекст с запасом под промпт с примерами и длинный
# пост; keep_alive держит модель в памяти — без него первый запрос после
# пятиминутной паузы упирается в холодную загрузку весов
AI_NUM_CTX = 16384
AI_KEEP_ALIVE = -1


def build_ai_messages(action: str, text: str, context: str | None = None,
                       tone: str | None = None,
                       refs: list[str] | None = None,
                       target_words: int | None = None) -> list[dict]:
    """Собирает историю чата: system + few-shot примеры + запрос.

    context — пост целиком с фрагментом, помеченным FRAG_OPEN/FRAG_CLOSE
    (правка выделенного): модель видит окружение и стыкует стиль.
    tone — пресет тона или произвольное описание.
    refs — markdown прошлых постов канала как образец авторского стиля.
    target_words — целевой объём generate по умолчанию (медиана длины
    постов канала, см. typical_post_words).
    tone и refs только для rewrite/generate: format не меняет слова,
    поэтому стиль там неприменим.
    """
    conf = AI_ACTIONS[action]
    system = conf["system"].replace(
        "__WORDS__", str(target_words or AI_DEFAULT_WORDS))
    tone_applies = action in ("rewrite", "generate")
    if tone_applies:
        for extra in (_tone_instruction(tone), _refs_instruction(refs)):
            if extra:
                system = f"{system}\n\n{extra}"
    messages = [{"role": "system", "content": system}]
    for user, assistant in conf["examples"]:
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant})
    if context:
        content = (
            f"Пост целиком, фрагмент помечен {FRAG_OPEN} и {FRAG_CLOSE}:\n\n{context}\n\n"
            f"Верни ТОЛЬКО обработанный фрагмент — без маркеров и без "
            f"остального текста поста."
        )
    else:
        content = text
    # Напоминания рядом с запросом: инструкция в начале system-промпта
    # к моменту генерации «выветривается», подпись возле запроса — нет
    tone_clean = (tone or "").strip()
    if tone_applies and tone_clean:
        label = AI_TONE_LABELS.get(tone_clean, tone_clean[:200])
        content = f"{content}\n\nТон ответа: {label}."
    # Дефолтный объём — только когда пользователь не задал свой: подпись
    # в хвосте запроса весит больше текста самого запроса и перебивала бы
    # явное «объём примерно 1000 слов» из его середины
    if action == "generate" and not _EXPLICIT_LEN_RE.search(text):
        content = (f"{content}\n\nОбъём: примерно "
                   f"{target_words or AI_DEFAULT_WORDS} слов.")
    messages.append({"role": "user", "content": content})
    return messages


# Мусорные вступления, которые модели любят добавлять вопреки промпту
_LEAD_JUNK = re.compile(
    r"^\s*(?:```[a-zA-Z]*\n|(?:Вот|Конечно|Держи|Готово|Пожалуйста)[^\n]{0,80}:\s*\n+)+"
)
_TAIL_JUNK = re.compile(r"\s*```\s*$")
_LEAD_HOLD = 96   # сколько символов придержать для чистки префикса
_TAIL_HOLD = 8    # хвост под финальную ```-обёртку

# Модель иногда выдумывает тегам атрибуты (<footer źródło="…">) — срезаем
# у тегов, которые в нашем формате атрибутов не имеют. Теги с легитимными
# атрибутами (<a name>, <tg-map lat…>, <details open>) не трогаем: при
# rewrite они могут прийти из текста самого пользователя.
_BAD_TAG_ATTRS = re.compile(
    r"<(/?)(footer|aside|cite|u|sub|sup|summary)\s[^<>]*>", re.IGNORECASE)
# …а иногда теряет «>» у открывающего тега: «<footer\nтекст\n</footer>».
# Рендерер понимает footer/aside только однострочными — пересобираем блок.
_BROKEN_TAG_BLOCK = re.compile(
    r"<(footer|aside)\s+([^<>]*?)\s*(</\1>)", re.IGNORECASE | re.DOTALL)
_TAG_HOLD = 120   # держим незакрытый «<…» не дольше этого

# «Разделитель» из тире/подчёркиваний на своей строке — модель рисует его
# вместо --- каждый раз новым юникодным символом (—, –, ―, −, ─, _, ⸺…);
# строка с текстом («— Привет») не трогается. Паддинг — любой пробельный,
# кроме переноса, ПЛЮС невидимые format-символы (zero-width space, word
# joiner, BOM): юникод не считает их пробелами, а модель их иногда сеет —
# такая строка выглядит одиноким тире, но под «чистый» паттерн не подпадала.
_DASHLIKE = r"_‐-―−─-┃⸺⸻﹘－＿"
_PAD = r"(?:[^\S\n]|[\u200b-\u200f\u2060\ufeff])"
_FAKE_DIVIDER = re.compile(
    rf"(\n){_PAD}*[{_DASHLIKE}]{{1,3}}{_PAD}*(?=\n|$)")
# незавершённая строка, которая ещё может оказаться таким разделителем
_DIVIDER_TAIL = re.compile(rf"^{_PAD}*[{_DASHLIKE}]{{0,3}}{_PAD}*$")


def _fix_tags(s: str, at_line_start: bool = True) -> str:
    s = _BROKEN_TAG_BLOCK.sub(lambda m: f"<{m.group(1)}>"
                              + " ".join(m.group(2).split())
                              + m.group(3), s)
    s = _BAD_TAG_ATTRS.sub(r"<\1\2>", s)
    # паттерн разделителя заякорен на \n: кусок стрима может начинаться
    # посреди строки, и «^» ловил бы хвост чужой строки («сказал —»)
    if at_line_start:
        return _FAKE_DIVIDER.sub(r"\1---", "\n" + s)[1:]
    return _FAKE_DIVIDER.sub(r"\1---", s)


def _clean_stream(parts):
    """Срезает из потока токенов мусорные префиксы и ```-обёртки.

    Начало придерживается до _LEAD_HOLD символов (или первого \\n\\n) —
    достаточно, чтобы вступление «Вот текст:» и ```-забор попали в буфер
    целиком; хвост в _TAIL_HOLD символов выдаётся после конца потока.
    Незакрытый тег «<…» придерживается до появления «>», чтобы чистка
    атрибутов видела тег целиком, а не порванным между чанками.
    """
    buf, lead_done, line_start = "", False, True
    for part in parts:
        # юникодные разделители строк (LS/PS) — в обычные переносы, иначе
        # строчные паттерны (разделители, footer) их не видят
        buf += part.replace("\u2028", "\n").replace("\u2029", "\n\n")
        if not lead_done:
            if len(buf) < _LEAD_HOLD and "\n\n" not in buf:
                continue
            buf = _LEAD_JUNK.sub("", buf)
            lead_done = True
        if len(buf) > _TAIL_HOLD:
            cut = len(buf) - _TAIL_HOLD
            # первый «<» после последнего «>» — начало недописанного тега
            # (или сломанного блока): держим его целиком, чтобы _fix_tags
            # видел тег не порванным между чанками
            lt = buf.find("<", buf.rfind(">", 0, cut) + 1, cut)
            if lt != -1 and cut - lt < _TAG_HOLD:
                cut = lt
            # не рвать строку, которая ещё может оказаться псевдоразделителем
            nl = buf.rfind("\n", 0, cut)
            if _DIVIDER_TAIL.match(buf[nl + 1:cut]):
                cut = nl + 1 if nl != -1 else 0
            if cut:
                piece = _fix_tags(buf[:cut], line_start)
                line_start = piece.endswith("\n")
                yield piece
                buf = buf[cut:]
    if not lead_done:
        buf = _LEAD_JUNK.sub("", buf)
    buf = _TAIL_JUNK.sub("", buf)
    buf = _fix_tags(buf, line_start)
    if buf:
        yield buf


def ai_stream(action: str, text: str, context: str | None = None,
              tone: str | None = None, refs: list[str] | None = None,
              target_words: int | None = None):
    """Генератор чанков ответа модели: {'t': текст} | {'error': …} | {'done': True}."""
    conf = AI_ACTIONS.get(action)
    if not conf:
        yield {"error": "Неизвестное действие."}
        return
    headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else {}
    try:
        with requests.post(
            f"{OLLAMA_URL}/api/chat",
            headers=headers,
            json={
                "model": AI_MODEL,
                "stream": True,
                "think": False,
                "keep_alive": AI_KEEP_ALIVE,
                "messages": build_ai_messages(action, text, context, tone,
                                              refs, target_words),
                "options": {**conf["options"], "num_ctx": AI_NUM_CTX},
            },
            stream=True,
            timeout=300,
        ) as resp:
            if not resp.ok:
                yield {"error": f"Ollama: {resp.status_code} {resp.text[:200]}"}
                return

            def tokens():
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise RuntimeError(f"Ollama: {chunk['error']}")
                    part = (chunk.get("message") or {}).get("content", "")
                    if part:
                        yield part
                    if chunk.get("done"):
                        break

            for part in _clean_stream(tokens()):
                yield {"t": part}
        yield {"done": True}
    except RuntimeError as e:
        yield {"error": str(e)}
    except requests.RequestException as e:
        yield {"error": ("Ollama недоступен — запустите `ollama serve` "
                         f"({e.__class__.__name__})")}


def consume_login_code(code: str) -> dict | None:
    """Проверяет код из login_codes.json (пишет bot.py) и гасит его."""
    try:
        codes = json.load(open(LOGIN_CODES_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = codes.pop(code, None)
    if not entry or entry.get("expires", 0) < time.time():
        return None
    tmp = LOGIN_CODES_FILE + ".tmp"
    json.dump(codes, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, LOGIN_CODES_FILE)
    return entry


def api_call(method: str, files=None, **params):
    if files:
        resp = requests.post(f"{API_URL}/{method}", data=params, files=files, timeout=120)
    else:
        resp = requests.post(f"{API_URL}/{method}", json=params, timeout=60)
    data = resp.json()
    if data.get("ok"):
        return True, data.get("result")
    return False, data.get("description", "unknown error")


def verify_channel_admin(username: str, user_id) -> tuple[bool, str | dict]:
    """Проверяет, что канал существует, бот в нём есть, а user_id — админ."""
    ok, chat = api_call("getChat", chat_id=username)
    if not ok:
        return False, f"Канал не найден или бот не добавлен: {chat}"
    ok, admins = api_call("getChatAdministrators", chat_id=username)
    if not ok:
        return False, f"Не удалось проверить администраторов: {admins}"
    if not any(a.get("user", {}).get("id") == int(user_id) for a in admins):
        return False, "Вы не администратор этого канала."
    return True, chat


def _upload_litterbox(filename: str, blob: bytes) -> tuple[bool, str]:
    try:
        resp = requests.post(
            LITTERBOX_API,
            data={"reqtype": "fileupload", "time": "1h"},
            files={"fileToUpload": (filename, blob)},
            timeout=120,
        )
    except requests.RequestException as e:
        return False, f"litterbox недоступен: {e}"
    if not resp.ok or not resp.text.startswith("http"):
        return False, f"litterbox: {resp.status_code}"
    return True, resp.text.strip()


def _upload_uguu(filename: str, blob: bytes) -> tuple[bool, str]:
    try:
        resp = requests.post(
            "https://uguu.se/upload",
            files={"files[]": (filename, blob)},
            timeout=120,
        )
        data = resp.json()
        url = data["files"][0]["url"]
    except (requests.RequestException, ValueError, KeyError, IndexError) as e:
        return False, f"uguu недоступен: {e}"
    return True, url


def trampoline_upload(filename: str, blob: bytes) -> tuple[bool, str]:
    """Заливает файл на одноразовый хостинг; при сбое пробует запасной."""
    errors = []
    for uploader in (_upload_litterbox, _upload_uguu):
        ok, result = uploader(filename, blob)
        if ok:
            return True, result
        errors.append(result)
        log.warning("Трамплин не сработал: %s", result)
    return False, "Хостинги-трамплины недоступны: " + "; ".join(errors)


def store_image(chat_id: int, filename: str, blob: bytes) -> tuple[bool, str]:
    """Кладёт картинку в хранилище Telegram, возвращает (ok, file_id|ошибка).

    Файл отправляется документом (без пережатия) в чат пользователя и сразу
    удаляется — file_id остаётся действительным.
    """
    ok, msg = api_call(
        "sendDocument",
        chat_id=chat_id,
        disable_notification=True,
        files={"document": (filename, blob)},
    )
    if not ok:
        return False, msg
    file_id = msg["document"]["file_id"]
    api_call("deleteMessage", chat_id=chat_id, message_id=msg["message_id"])
    return True, file_id


def resolve_media(markdown: str) -> tuple[bool, str]:
    """Готовит медиа к публикации: недоступные для Telegram источники
    (наш S3 и хранилище Telegram) перезаливаются на трамплин."""
    error = None

    def to_trampoline(filename: str, blob: bytes, original: str) -> str:
        nonlocal error
        ok, url = trampoline_upload(filename, blob)
        if not ok:
            error = url
            return original
        return url

    def repl_tg_file(match):
        nonlocal error
        ok, info = api_call("getFile", file_id=match.group(1))
        if not ok:
            error = f"Картинка недоступна: {info}"
            return match.group(0)
        resp = requests.get(f"{FILE_URL}/{info['file_path']}", timeout=120)
        if not resp.ok:
            error = f"Не удалось скачать картинку из Telegram: {resp.status_code}"
            return match.group(0)
        name = os.path.basename(info["file_path"])
        return to_trampoline(name, resp.content, match.group(0))

    resolved = TG_FILE_RE.sub(repl_tg_file, markdown)

    if s3.configured and s3.public_base and S3_TRAMPOLINE:
        s3_url_re = re.compile(re.escape(s3.public_base) + r"/[^\s\)\"]+")

        def repl_s3(match):
            nonlocal error
            url = match.group(0)
            resp = requests.get(url, timeout=120)
            if not resp.ok:
                error = f"Не удалось скачать из S3: {resp.status_code}"
                return url
            return to_trampoline(os.path.basename(url), resp.content, url)

        resolved = s3_url_re.sub(repl_s3, resolved)

    if error:
        return False, error
    return True, resolved


# Кэш картинок кастомных эмодзи: id -> (bytes, content-type)
EMOJI_CACHE: dict[str, tuple[bytes, str]] = {}


def fetch_emoji_image(emoji_id: str) -> tuple[bytes, str] | None:
    """Скачивает превью кастомного эмодзи через Bot API (с кэшем в памяти)."""
    if emoji_id in EMOJI_CACHE:
        return EMOJI_CACHE[emoji_id]
    ok, stickers = api_call("getCustomEmojiStickers", custom_emoji_ids=[emoji_id])
    if not ok or not stickers:
        return None
    st = stickers[0]
    # у анимированных (tgs/webm) берём статичную миниатюру
    if (st.get("is_animated") or st.get("is_video")) and st.get("thumbnail"):
        file_id = st["thumbnail"]["file_id"]
    else:
        file_id = st["file_id"]
    ok, info = api_call("getFile", file_id=file_id)
    if not ok:
        return None
    resp = requests.get(f"{FILE_URL}/{info['file_path']}", timeout=60)
    if not resp.ok:
        return None
    ext = os.path.splitext(info["file_path"])[1].lower()
    ctype = {".webp": "image/webp", ".png": "image/png",
             ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext)
    if not ctype:  # .tgs без миниатюры и прочая экзотика — не рисуем
        return None
    EMOJI_CACHE[emoji_id] = (resp.content, ctype)
    return EMOJI_CACHE[emoji_id]


def check_token_leak(sent_message: dict):
    """Проверяет, что исходные URL медиа не попали в доставленное сообщение."""
    if "api.telegram.org/file" in json.dumps(sent_message):
        log.warning(
            "ВНИМАНИЕ: исходный URL медиа (с токеном) виден в отправленном "
            "сообщении! Нужно менять схему хранения картинок."
        )


def send_post(markdown: str, target) -> tuple[bool, str | dict]:
    """Публикует rich-пост. Возвращает (True, Message) или (False, ошибка)."""
    try:
        ok, resolved = resolve_media(markdown)
        if not ok:
            return False, resolved
        ok, result = api_call(
            "sendRichMessage", chat_id=target, rich_message={"markdown": resolved}
        )
        if not ok:
            return False, result
        check_token_leak(result)
        return True, result
    except Exception as e:
        log.exception("send_post %s", target)
        return False, f"Ошибка отправки: {e}"


def edit_post(markdown: str, target, message_id: int) -> tuple[bool, str]:
    """Редактирует уже опубликованный rich-пост."""
    try:
        ok, resolved = resolve_media(markdown)
        if not ok:
            return False, resolved
        ok, result = api_call(
            "editMessageText",
            chat_id=target,
            message_id=message_id,
            rich_message={"markdown": resolved},
        )
        if not ok:
            return False, result
        return True, "ok"
    except Exception as e:
        log.exception("edit_post %s/%s", target, message_id)
        return False, f"Ошибка редактирования: {e}"


def scheduler_loop():
    """Фоновый цикл: публикует отложенные посты, у которых подошло время."""
    while True:
        time.sleep(15)
        try:
            due = storage.sched_take_due(SENDING_STALE_AFTER)
            for post in due:
                # ошибка одного поста не должна ронять обработку остальных
                try:
                    ok, result = send_post(post["markdown"], post["target"])
                except Exception as e:
                    ok, result = False, f"Внутренняя ошибка: {e}"
                message_id = result.get("message_id") if ok else None
                storage.sched_finish(post, ok, "" if ok else str(result), message_id)
                log.info("Отложенный пост %s → %s: %s",
                         post["id"], post["target"], "ok" if ok else result)
        except Exception:
            log.exception("Ошибка планировщика")


def local_ips() -> list[str]:
    """IP-адреса локальных сетей (VPN-интерфейсы вроде 198.18.x.x отсеиваются)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    lan = [ip for ip in sorted(ips)
           if ip.startswith(("192.168.", "10.")) or
           (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)]
    return lan or ["127.0.0.1"]
