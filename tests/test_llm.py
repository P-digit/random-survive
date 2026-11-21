"""LLM 공급자 어댑터(survival/llm.py) 테스트. 네트워크 없이 가짜 Chat Completions 클라이언트로 검증한다."""
from types import SimpleNamespace

import pytest

from survival import config, gamemaster, llm
from survival.tools import TOOLS
from tests import test_engine

game = test_engine.game   # 게임 상태 픽스처 재사용 (네트워크 호출을 가짜로 바꾼 상태)


class FakeMessage(SimpleNamespace):
    def model_dump(self, exclude_none=False):
        data = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments},
                 "extra_content": {"google": {"thought_signature": "SIG"}}}
                for c in self.tool_calls]
        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}
        return data


def tool_call(name, arguments, call_id="c1"):
    return SimpleNamespace(id=call_id, type="function", function=SimpleNamespace(name=name, arguments=arguments))


class FakeChat:
    """chat.completions.create 호출을 기록하고, 정해 둔 메시지를 차례로 돌려준다."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=lambda **k: None)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=self.replies.pop(0))])


def text(content):
    return FakeMessage(content=content, tool_calls=None)


def test_choose_provider():
    assert config.choose_provider(None, "sk-a", None) == "openai"
    assert config.choose_provider(None, None, "g") == "gemini"
    assert config.choose_provider(None, "sk-a", "g") == "openai"       # 둘 다 있으면 기존대로 OpenAI
    assert config.choose_provider("Gemini", "sk-a", "g") == "gemini"   # 직접 고르면 그대로
    assert config.choose_provider("unknown", None, None) == "openai"


def test_tool_schema_is_converted_to_chat_format():
    converted = llm.to_chat_tool(TOOLS[0])
    assert converted["type"] == "function"
    assert converted["function"]["name"] == TOOLS[0]["name"]
    assert converted["function"]["parameters"] == TOOLS[0]["parameters"]
    assert llm.to_chat_tool(converted) is converted      # 이미 바뀐 것은 그대로


def test_input_conversion():
    assert llm.to_messages("안녕") == [{"role": "user", "content": "안녕"}]
    msgs = llm.to_messages([
        {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        {"role": "user", "content": [{"type": "input_text", "text": "그림"},
                                     {"type": "input_image", "image_url": "data:image/png;base64,AA", "detail": "low"}]},
    ])
    assert msgs[0] == {"role": "tool", "tool_call_id": "c1", "content": "ok"}
    assert msgs[1]["content"] == [{"type": "text", "text": "그림"},
                                  {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]


def test_conversation_continues_with_previous_response_id():
    fake = FakeChat([FakeMessage(content=None, tool_calls=[tool_call("advance_time", '{"hours": 2}')]),
                     text("잠에서 깬다.")])
    client = llm.GeminiClient(fake, reasoning_effort="low")
    first = client.responses.create(model="m", instructions="GM", input="잔다", tools=TOOLS, max_output_tokens=900)
    assert first.output[0].type == "function_call" and first.output[0].call_id == "c1"
    assert first.output_text == ""
    assert fake.calls[0]["max_tokens"] == 900 + llm.THINKING_MARGIN
    assert fake.calls[0]["reasoning_effort"] == "low"
    assert fake.calls[0]["tools"][0]["function"]["name"] == TOOLS[0]["name"]

    second = client.responses.create(model="m", instructions="GM", previous_response_id=first.id,
                                     input=[{"type": "function_call_output", "call_id": "c1", "output": "2시간 지남"}])
    assert second.output_text == "잠에서 깬다."
    sent = fake.calls[1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "tool"]
    # Gemini의 thought_signature는 다음 요청에 그대로 돌려준다
    assert sent[2]["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "SIG"}}
    assert sent[3] == {"role": "tool", "tool_call_id": "c1", "content": "2시간 지남"}


def test_unknown_previous_response_raises():
    client = llm.GeminiClient(FakeChat([]))
    with pytest.raises(LookupError):
        client.responses.create(model="m", input="x", previous_response_id="sum_old_save")


def test_missing_tool_call_id_is_filled():
    call = tool_call("advance_time", '{"hours": 1}', call_id=None)
    fake = FakeChat([FakeMessage(content=None, tool_calls=[call]), text("끝")])
    client = llm.GeminiClient(fake)
    first = client.responses.create(model="m", input="쉰다")
    call_id = first.output[0].call_id
    assert call_id
    client.responses.create(model="m", previous_response_id=first.id,
                            input=[{"type": "function_call_output", "call_id": call_id, "output": "ok"}])
    sent = fake.calls[1]["messages"]
    assert sent[1]["tool_calls"][0]["id"] == call_id == sent[2]["tool_call_id"]


def test_history_is_trimmed_at_user_boundary():
    history = []
    for i in range(40):
        history += [{"role": "user", "content": f"u{i}"},
                    {"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}"}]},
                    {"role": "tool", "tool_call_id": f"c{i}", "content": "ok"}]
    trimmed = llm.trim_history(history, limit=10)
    assert len(trimmed) <= 10 and trimmed[0]["role"] == "user"
    assert trimmed[-1] == history[-1]


def test_store_is_bounded(monkeypatch):
    monkeypatch.setattr(llm, "STORE_LIMIT", 3)
    fake = FakeChat([text(str(i)) for i in range(5)])
    client = llm.GeminiClient(fake)
    ids = [client.responses.create(model="m", input="x").id for _ in range(5)]
    assert client.responses.history(ids[0]) == [] and client.responses.history(ids[-1])


def test_images_are_not_supported_on_gemini():
    client = llm.GeminiClient(FakeChat([]))
    with pytest.raises(NotImplementedError):
        client.images.generate(model="x", prompt="y")


def test_run_turn_through_gemini_adapter(game, monkeypatch):
    """게임 한 턴이 어댑터를 거쳐 '툴 호출 → 결과 전달 → 서술'로 끝까지 진행된다."""
    fake = FakeChat([
        FakeMessage(content=None, tool_calls=[tool_call("advance_time", '{"hours": 2, "activity": "forage"}')]),
        text("당신은 개울을 찾는다.\n▶ 불을 피운다\n▶ 잠을 잔다\n▶ 계속 걷는다"),
    ])
    client = llm.GeminiClient(fake)
    monkeypatch.setattr(gamemaster, "get_client", lambda: client)
    body = gamemaster.run_turn(game, "물을 찾는다")
    assert body == "당신은 개울을 찾는다."
    assert game.elapsed_hours == 2
    assert game.suggestions == ["불을 피운다", "잠을 잔다", "계속 걷는다"]
    assert client.responses.history(game.prev_response_id)[-1]["content"].startswith("당신은 개울")


def test_run_turn_recovers_when_history_is_lost(game, monkeypatch):
    """프로그램을 다시 켜서 이전 대화 기록이 없으면 줄거리를 넣어 새 대화로 이어간다."""
    fake = FakeChat([text("당신은 다시 길을 나선다.\n▶ 걷는다\n▶ 쉰다\n▶ 살핀다")])
    client = llm.GeminiClient(fake)
    monkeypatch.setattr(gamemaster, "get_client", lambda: client)
    game.prev_response_id = "resp_from_old_session"
    game.chat = [{"role": "user", "content": "북쪽으로 걷는다"}, {"role": "assistant", "content": "당신은 언덕을 넘는다."}]
    body = gamemaster.run_turn(game, "주변을 살펴본다")
    assert body == "당신은 다시 길을 나선다."
    assert len(fake.calls) == 1 and "[이전 줄거리" in fake.calls[0]["messages"][1]["content"]


def test_embedding_cache_is_per_model(monkeypatch, tmp_path):
    """공급자를 바꿔도 다른 모델의 임베딩 캐시를 쓰거나 덮어쓰지 않는다."""
    from survival import knowledge
    monkeypatch.setattr(knowledge, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(knowledge, "EMBEDDING_MODEL", "text-embedding-3-small")
    openai_path = knowledge.embed_cache_path()
    monkeypatch.setattr(knowledge, "EMBEDDING_MODEL", "gemini-embedding-001")
    gemini_path = knowledge.embed_cache_path()
    assert openai_path != gemini_path and gemini_path.parent == tmp_path
    assert knowledge.collection_name() == "survival_guide_gemini-embedding-001"


def test_store_is_safe_under_concurrent_turns():
    """공유 모드처럼 여러 스레드가 동시에 호출해도 기록이 깨지지 않는다."""
    import threading

    class EchoChat(FakeChat):
        def _create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=text(kwargs["messages"][-1]["content"]))])

    client = llm.GeminiClient(EchoChat([]))
    errors = []

    def player(n):
        try:
            rid = None
            for turn in range(30):
                rid = client.responses.create(model="m", input=f"p{n}-{turn}", previous_response_id=rid).id
            assert client.responses.history(rid)[-1]["content"] == f"p{n}-29"
        except Exception as e:   # pragma: no cover - 실패 시 원인 보고용
            errors.append(e)

    threads = [threading.Thread(target=player, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
