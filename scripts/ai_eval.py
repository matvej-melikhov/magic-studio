"""A/B-сравнение и метрики промптов AI-помощника.

Прогоняет фиксированный набор входов через старые и новые промпты на живой
модели, пишет пары ответов в markdown-отчёт и считает автоматические
метрики по новым ответам:

1. Форматная валидность: нет ```-обёрток, вступлений «Вот…», HTML вне
   белого списка разметки.
2. Следование инструкции: format не меняет слова; rewrite держит объём
   и не тащит окружение из контекста; generate по умолчанию короткий
   и без непрошеных эмодзи.
3. Стабильность: повторные прогоны format почти совпадают (низкая t).
4. Скорость: время до первого токена и токены/сек (справочно).

Запуск из корня репозитория:  python3 scripts/ai_eval.py [файл-отчёта]
(модель и ключ берутся из .env, как у сервера)
"""

import difflib
import re
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import requests

import core

# ── Старые промпты (до доработки) — для сравнения ───
OLD_GUIDE = """Ты работаешь с Rich Markdown — форматом постов Telegram (Bot API 10.1).
Доступная разметка:
- Заголовки: # … ###### (шесть уровней)
- **жирный**, _курсив_, ~~зачёркнутый~~, <u>подчёркнутый</u>, ==выделение маркером==, ||спойлер||
- `код в строке` и блоки кода ```язык … ```
- Формулы LaTeX: $x^2$ в строке, $$…$$ блоком (сырой LaTeX, без экранирования)
- Цитаты: > текст; выносная цитата: <aside>текст<cite>Автор</cite></aside>
- Списки: -, 1., чекбоксы - [ ] / - [x]
- Таблицы GFM, разделитель ---, сноски [^1] с определением [^1]: текст
- Свёртка: <details><summary>Заголовок</summary>текст</details>
- Подпись поста: <footer>текст</footer>
- Медиа только блочными строками: ![](https://… "Подпись")
Важно: одиночный перенос строки склеивается в пробел — абзацы разделяй пустой строкой.
Отвечай ТОЛЬКО готовым текстом поста, без пояснений, без обёртки ```markdown."""

OLD_PROMPTS = {
    "rewrite": OLD_GUIDE + "\n\nЗадача: перепиши присланный фрагмент — сделай его яснее "
        "и живее, сохранив смысл, язык, тон и уже имеющуюся разметку. "
        "Не добавляй ничего от себя и не комментируй.",
    "format": OLD_GUIDE + "\n\nЗадача: оформи присланный сырой текст разметкой Rich Markdown. "
        "Сам текст не переписывай. Добавляй разметку только там, где она реально улучшает "
        "читаемость: перечисления — в списки, имена переменных и команд — в `код`, "
        "формулы — в $…$/$$…$$, крупные смысловые части — под заголовки. "
        "Если тексту разметка не нужна — верни его без изменений.",
    "generate": OLD_GUIDE + "\n\nЗадача: напиши пост для Telegram-канала по запросу "
        "пользователя. Пиши на языке запроса, структурируй разметкой там, где это уместно.\n"
        "По умолчанию пиши КОРОТКО: 2–3 предложения, без заголовков и списков — "
        "как обычный пост в канале. Развёрнутый длинный текст пиши только если "
        "пользователь прямо просит об этом («подробно», «длинный пост», "
        "«со списком», указывает объём и т.п.).",
}

# ── Тестовые входы ──────────────────────────────────
FRAG = ("Также хотелось бы отметить тот факт, что в рамках проведённых работ "
        "нами была осуществлена оптимизация скорости загрузки главной страницы, "
        "которая теперь производится значительно быстрее, чем это было ранее.")

POST_CTX = f"""## Итоги недели

Мы выкатили тёмную тему и починили экспорт.

{core.FRAG_OPEN}{FRAG}{core.FRAG_CLOSE}

На следующей неделе займёмся уведомлениями — следите за новостями."""

# ── Автоматические проверки ─────────────────────────
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿]")
# теги вне белого списка разметки (в т.ч. любые с атрибутами вроде style=)
BAD_HTML_RE = re.compile(
    r"<(?!/?(?:u|s|b|i|sub|sup|cite|mark|ins|em|strong|aside|details|summary|footer|tg-)\b[^ >]*>)[a-zA-Z]")


def words(text: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]+", text.lower())


def check_clean(resp: str, **_) -> list[tuple[str, bool, str]]:
    """Общая валидность: без мусора и чужого HTML."""
    return [
        ("нет ```-обёртки", not resp.startswith("```") and not resp.rstrip().endswith("```"),
         resp[:40]),
        ("нет вступления «Вот…»", not re.match(r"\s*(Вот|Конечно|Держи|Готово)\b", resp),
         resp[:40]),
        ("нет HTML вне белого списка", not BAD_HTML_RE.search(resp),
         (BAD_HTML_RE.search(resp) or [""])[0] if BAD_HTML_RE.search(resp) else ""),
    ]


def check_words_preserved(resp: str, src: str, **_) -> list:
    """format: слова исходника не переписаны (допуск 5% на артефакты списков)."""
    a, b = words(src), words(resp)
    missing = len([w for w in a if w not in b])
    ok = missing <= max(1, len(a) * 0.05)
    return [("слова не изменены", ok, f"потеряно {missing}/{len(a)}")]


def check_length_ratio(resp: str, src: str, lo=0.5, hi=1.6, **_) -> list:
    r = len(resp) / max(1, len(src))
    return [(f"объём {lo}–{hi}×", lo <= r <= hi, f"{r:.2f}×")]


def check_no_context_leak(resp: str, **_) -> list:
    leaked = [s for s in ("Итоги недели", "тёмную тему", "уведомлениями") if s in resp]
    return [("нет утечки окружения", not leaked, ", ".join(leaked))]


def check_short(resp: str, max_sentences=4, **_) -> list:
    n = len([s for s in re.split(r"[.!?…]+\s", resp.strip()) if s.strip()])
    return [(f"коротко (≤{max_sentences} предл.)", n <= max_sentences, f"{n} предл.")]


def check_no_emoji(resp: str, **_) -> list:
    found = EMOJI_RE.findall(resp)
    return [("нет непрошеных эмодзи", not found, "".join(found[:5]))]


CASES = [
    {
        "name": "rewrite: канцелярит-фрагмент в середине поста",
        "action": "rewrite", "text": FRAG, "context": POST_CTX,
        "checks": [check_clean, check_length_ratio, check_no_context_leak],
    },
    {
        "name": "rewrite: отдельный вялый анонс",
        "action": "rewrite",
        "text": ("Доводим до вашего сведения, что запись на курс будет открыта "
                 "в ближайший понедельник. Количество мест является ограниченным."),
        "context": None,
        "checks": [check_clean, check_length_ratio],
    },
    {
        "name": "format: сырой текст с шагами и командами",
        "action": "format",
        "text": ("Как поднять проект локально. Сначала клонируете репозиторий. Потом "
                 "копируете env.example в .env и вписываете туда токен бота. Дальше "
                 "ставите зависимости pip install -r requirements.txt и запускаете "
                 "python3 app/server.py. Редактор откроется на localhost:8080. Если "
                 "порт занят поменяйте переменную PORT."),
        "context": None,
        "checks": [check_clean, check_words_preserved],
        "stability": True,   # дополнительно: 2 повторных прогона на совпадение
    },
    {
        "name": "format: короткий текст, разметка не нужна",
        "action": "format",
        "text": "Сегодня без новостей. Завтра расскажу про большой релиз.",
        "context": None,
        "checks": [check_clean, check_words_preserved,
                   lambda resp, **kw: [("разметка не добавлена",
                                        not re.search(r"[*=#>`_~]", resp), resp[:60])]],
    },
    {
        "name": "generate: короткий запрос",
        "action": "generate",
        "text": "пост о том, что завтра в 12:00 стрим с разбором нового редактора",
        "context": None,
        "checks": [check_clean, check_short, check_no_emoji],
    },
    {
        "name": "generate: просят подробно со списком",
        "action": "generate",
        "text": "подробный пост со списком: 4 совета как писать посты, которые дочитывают",
        "context": None,
        "checks": [check_clean,
                   lambda resp, **kw: [("есть список", bool(re.search(r"^[-1]", resp, re.M)),
                                        "")]],
    },
]


def run_old(action: str, text: str) -> str:
    headers = ({"Authorization": f"Bearer {core.OLLAMA_API_KEY}"}
               if core.OLLAMA_API_KEY else {})
    resp = requests.post(
        f"{core.OLLAMA_URL}/api/chat", headers=headers,
        json={
            "model": core.AI_MODEL, "stream": False, "think": False,
            "messages": [
                {"role": "system", "content": OLD_PROMPTS[action]},
                {"role": "user", "content": text},
            ],
            "options": {"temperature": 0.7, "num_ctx": 8192},
        },
        timeout=300)
    resp.raise_for_status()
    return (resp.json().get("message") or {}).get("content", "").strip()


def run_new(action: str, text: str, context: str | None):
    """Возвращает (текст, время до первого токена, длительность)."""
    out, t0, ttft = [], time.monotonic(), None
    for chunk in core.ai_stream(action, text, context):
        if "error" in chunk:
            return f"[ОШИБКА] {chunk['error']}", 0.0, 0.0
        if chunk.get("t"):
            if ttft is None:
                ttft = time.monotonic() - t0
            out.append(chunk["t"])
    return "".join(out).strip(), ttft or 0.0, time.monotonic() - t0


def main():
    report = [f"# A/B промптов AI-помощника\n\nМодель: {core.AI_MODEL} через {core.OLLAMA_URL}\n"]
    results = []           # (case, check, ok, detail)
    for i, case in enumerate(CASES, 1):
        print(f"[{i}/{len(CASES)}] {case['name']}…", flush=True)
        old = run_old(case["action"], case["text"])
        new, ttft, dur = run_new(case["action"], case["text"], case["context"])
        for check in case["checks"]:
            for name, ok, detail in check(new, src=case["text"]):
                results.append((case["name"], name, ok, detail))
        if case.get("stability"):
            again, _, _ = run_new(case["action"], case["text"], case["context"])
            sim = difflib.SequenceMatcher(None, new, again).ratio()
            results.append((case["name"], "стабильность повтора ≥0.85",
                            sim >= 0.85, f"{sim:.2f}"))
        speed = f"{len(new) / max(dur, 0.01):.0f} симв/с, первый токен {ttft:.1f}с"
        report.append(
            f"\n## {i}. {case['name']}\n\n"
            f"**Вход:**\n```\n{case['text']}\n```\n\n"
            f"**Было (старые промпты):**\n```\n{old}\n```\n\n"
            f"**Стало (новые промпты):** _{speed}_\n```\n{new}\n```\n")

    # ── таблица метрик ──
    passed = sum(1 for *_, ok, _ in results if ok)
    lines = ["\n## Метрики (новые промпты)\n",
             "| Кейс | Проверка | Результат | Детали |", "|---|---|---|---|"]
    for case_name, check_name, ok, detail in results:
        lines.append(f"| {case_name[:40]} | {check_name} | "
                     f"{'✅' if ok else '❌'} | {detail} |")
    lines.append(f"\n**Итого: {passed}/{len(results)}**")
    report.extend(lines)

    out_path = sys.argv[1] if len(sys.argv) > 1 else "ai_eval_report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print()
    for case_name, check_name, ok, detail in results:
        mark = "✅" if ok else "❌"
        print(f"  {mark} {case_name[:44]:46} {check_name:28} {detail}")
    print(f"\nИтого: {passed}/{len(results)}   Отчёт: {out_path}")


if __name__ == "__main__":
    main()
