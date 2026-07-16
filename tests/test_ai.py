"""AI-помощник: сборка сообщений (few-shot + контекст) и чистка стрима."""

import core


# ── build_ai_messages ───────────────────────────────

def test_messages_structure():
    msgs = core.build_ai_messages("rewrite", "текст")
    assert msgs[0]["role"] == "system"
    # few-shot пары: user/assistant чередуются, последний — запрос пользователя
    roles = [m["role"] for m in msgs[1:]]
    assert roles == ["user", "assistant"] * len(core.AI_ACTIONS["rewrite"]["examples"]) + ["user"]
    assert msgs[-1]["content"] == "текст"


def test_messages_with_context():
    ctx = f"начало {core.FRAG_OPEN}фрагмент{core.FRAG_CLOSE} конец"
    msgs = core.build_ai_messages("rewrite", "фрагмент", context=ctx)
    last = msgs[-1]["content"]
    assert ctx in last
    assert last.startswith("Пост целиком")


def test_every_action_has_prompt_examples_options():
    for action, conf in core.AI_ACTIONS.items():
        assert conf["system"], action
        assert len(conf["examples"]) >= 1, action
        assert "temperature" in conf["options"], action


# ── тон (rewrite/generate) ──────────────────────────

def test_tone_preset_applied_to_rewrite_and_generate():
    for action in ("rewrite", "generate"):
        msgs = core.build_ai_messages(action, "текст", tone="business")
        assert core.AI_TONES["business"] in msgs[0]["content"]


def test_tone_not_applied_to_format():
    msgs = core.build_ai_messages("format", "текст", tone="business")
    assert core.AI_TONES["business"] not in msgs[0]["content"]


def test_tone_custom_text():
    msgs = core.build_ai_messages("generate", "текст", tone="с сарказмом")
    assert "с сарказмом" in msgs[0]["content"]


def test_tone_empty_changes_nothing():
    with_none = core.build_ai_messages("generate", "текст", tone=None)
    with_empty = core.build_ai_messages("generate", "текст", tone="  ")
    assert with_none[0]["content"] == with_empty[0]["content"]
    assert with_none[-1]["content"] == with_empty[-1]["content"] == "текст"


def test_tone_reminder_in_user_message():
    # подпись тона дублируется в конце запроса — рядом с местом генерации
    msgs = core.build_ai_messages("generate", "текст", tone="business")
    assert core.AI_TONE_LABELS["business"] in msgs[-1]["content"]
    # и при правке фрагмента с контекстом тоже
    ctx = f"начало {core.FRAG_OPEN}фрагмент{core.FRAG_CLOSE} конец"
    msgs = core.build_ai_messages("rewrite", "фрагмент", context=ctx, tone="expert")
    assert core.AI_TONE_LABELS["expert"] in msgs[-1]["content"]


def test_tone_reminder_not_in_format():
    msgs = core.build_ai_messages("format", "текст", tone="business")
    assert msgs[-1]["content"] == "текст"


def test_generate_default_example_has_no_markup():
    # первый few-shot пример generate — обычный текст: именно он задаёт
    # дефолт «без разметки», который ломался жирным в каждом посте
    first_answer = core.AI_ACTIONS["generate"]["examples"][0][1]
    assert not any(m in first_answer for m in ("**", "==", "#"))


# ── посты-референсы (rewrite/generate) ──────────────

def test_refs_added_to_generate():
    msgs = core.build_ai_messages("generate", "текст", refs=["Первый пост", "Второй пост"])
    system = msgs[0]["content"]
    assert "Первый пост" in system and "Второй пост" in system


def test_refs_not_added_to_format():
    msgs = core.build_ai_messages("format", "текст", refs=["Первый пост"])
    assert "Первый пост" not in msgs[0]["content"]


def test_refs_limited_and_truncated():
    long_post = "я" * (core.AI_REFS_CHARS + 500)
    msgs = core.build_ai_messages(
        "generate", "текст", refs=[long_post, "б", "в", "лишний четвёртый"])
    system = msgs[0]["content"]
    assert "лишний четвёртый" not in system            # больше AI_REFS_MAX не берём
    assert "я" * core.AI_REFS_CHARS in system
    assert "я" * (core.AI_REFS_CHARS + 1) not in system  # каждый режется по длине


def test_refs_empty_changes_nothing():
    plain = core.build_ai_messages("generate", "текст")
    with_empty = core.build_ai_messages("generate", "текст", refs=[])
    with_blank = core.build_ai_messages("generate", "текст", refs=["", "   "])
    assert plain[0]["content"] == with_empty[0]["content"] == with_blank[0]["content"]


# ── _clean_stream ───────────────────────────────────

def clean(parts):
    return "".join(core._clean_stream(iter(parts)))


def test_clean_passthrough():
    assert clean(["Обычный ", "текст ", "поста."]) == "Обычный текст поста."


def test_clean_strips_lead_phrase():
    assert clean(["Вот улучшенный текст:\n", "Сам ", "пост."]) == "Сам пост."


def test_clean_strips_markdown_fence():
    assert clean(["```markdown\n", "Пост.", "\n```"]) == "Пост."


def test_clean_strips_phrase_and_fence():
    assert clean(["Конечно! Вот пост:\n```\nПост.\n```"]) == "Пост."


def test_clean_keeps_inner_fences():
    # ```-блоки внутри поста (код) не трогаем — срезается только обёртка
    src = "Текст.\n```python\nprint(1)\n```\nЕщё текст."
    assert clean([src]) == src


def test_clean_short_answer():
    # ответ короче буфера префикса — чистка на финальном сбросе
    assert clean(["Ок."]) == "Ок."


def test_clean_streaming_chunks():
    # мусор рвётся между чанками — буфер должен его собрать
    parts = ["Вот ваш ", "текст:\n", "Насто", "ящий пост ", "длиннее ста двадцати символов, "
             "чтобы буфер префикса гарантированно закрылся и поток пошёл насквозь."]
    assert clean(parts).startswith("Настоящий пост")
