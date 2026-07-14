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
