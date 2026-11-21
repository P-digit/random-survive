"""LLM 공급자 연결: OpenAI 또는 Google Gemini.

게임 코드는 OpenAI Responses API 모양(`client.responses.create(...)`, `previous_response_id`)으로 짜여 있다.
Gemini는 OpenAI 호환 주소로 Chat Completions만 지원하므로, 여기서 Responses API 모양을 흉내 내는 어댑터를
만들어 같은 코드가 그대로 돌아가게 한다.

- 대화 이어가기: Responses API는 서버가 이전 대화를 기억하지만, Chat Completions는 매번 전체 대화를 보내야
  한다. 어댑터가 응답 id별로 대화 기록을 메모리에 보관하고, `previous_response_id`로 이어 붙인다.
- 기록이 없으면(프로그램을 다시 켠 뒤 이어하기 등) LookupError를 낸다. `gamemaster.run_turn`은 이때 최근 줄거리를
  넣어 새 대화로 이어가므로 게임은 계속된다.
- 장면 그림: `client.images.generate/edit`(OpenAI Images API 모양)를 Gemini 그림 모델(`google-genai`)로 그린다.
"""
import base64
import threading
import uuid
from collections import OrderedDict
from types import SimpleNamespace

from .config import (GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_REASONING_EFFORT, LLM_PROVIDER,
                     OPENAI_API_KEY)

HISTORY_LIMIT = 60        # 대화 하나에 보관하는 메시지 수 (넘으면 오래된 턴부터 버린다)
STORE_LIMIT = 512         # 보관하는 응답 수 (넘으면 오래된 것부터 버린다. 서술 보정 같은 일회성 호출도 들어간다)
THINKING_MARGIN = 1024    # Gemini는 생각(thinking) 토큰도 출력 한도에 포함하므로 여유를 둔다


def to_chat_tool(tool):
    """Responses API 형식의 툴 정의를 Chat Completions 형식으로 바꾼다."""
    if tool.get("type") != "function" or "function" in tool:
        return tool
    function = {k: tool[k] for k in ("name", "description", "parameters", "strict") if k in tool}
    return {"type": "function", "function": function}


def _content_part(part):
    kind = part.get("type")
    if kind in ("input_text", "output_text", "text"):
        return {"type": "text", "text": part.get("text", "")}
    if kind == "input_image":
        return {"type": "image_url", "image_url": {"url": part.get("image_url", "")}}
    return part


def to_messages(input):
    """Responses API의 input(문자열 또는 항목 목록)을 Chat Completions 메시지 목록으로 바꾼다."""
    if input is None:
        return []
    if isinstance(input, str):
        return [{"role": "user", "content": input}]
    messages = []
    for item in input:
        if item.get("type") == "function_call_output":
            messages.append({"role": "tool", "tool_call_id": item["call_id"],
                             "content": str(item.get("output", ""))})
            continue
        content = item.get("content", "")
        if isinstance(content, list):
            content = [_content_part(p) for p in content]
        messages.append({"role": item.get("role", "user"), "content": content})
    return messages


def trim_history(messages, limit=HISTORY_LIMIT):
    """기록이 길면 앞쪽을 버린다. 툴 호출과 그 결과가 갈라지지 않도록 사용자 메시지에서 끊는다."""
    if len(messages) <= limit:
        return messages
    start = len(messages) - limit
    while start < len(messages) and messages[start].get("role") != "user":
        start += 1
    return messages[start:] if start < len(messages) else messages[-1:]


def _assistant_message(message):
    """모델의 응답 메시지를 다음 요청에 그대로 돌려줄 수 있는 dict로 만든다.

    Gemini는 툴 호출에 thought_signature(extra_content)를 붙이고, 다음 요청에 그대로 돌려받아야 한다.
    """
    data = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else dict(message)
    data["role"] = "assistant"
    for key in ("refusal", "audio", "annotations", "function_call"):
        data.pop(key, None)
    if not data.get("tool_calls"):
        data.pop("tool_calls", None)
        data.setdefault("content", "")
    return data


class ChatResponses:
    """`client.responses.create`를 흉내 낸다. 안에서는 Chat Completions를 부른다."""

    def __init__(self, chat_client, reasoning_effort=None):
        self._chat = chat_client
        self._reasoning_effort = reasoning_effort
        self._store = OrderedDict()
        self._lock = threading.Lock()   # 공유 모드에서는 여러 접속자의 턴이 동시에 돈다

    def history(self, response_id):
        with self._lock:
            return list(self._store.get(response_id, []))

    def create(self, model, input=None, instructions=None, tools=None, previous_response_id=None,
               max_output_tokens=None, **_ignored):
        history = []
        if previous_response_id:
            with self._lock:
                if previous_response_id not in self._store:
                    raise LookupError(f"이전 대화({previous_response_id})를 찾을 수 없습니다.")
                history = list(self._store[previous_response_id])
        history += to_messages(input)
        messages = ([{"role": "system", "content": instructions}] if instructions else []) + history

        kwargs = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = [to_chat_tool(t) for t in tools]
        if max_output_tokens:
            kwargs["max_tokens"] = max_output_tokens + (THINKING_MARGIN if self._reasoning_effort != "none" else 0)
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
        completion = self._chat.chat.completions.create(**kwargs)
        if not completion.choices:
            raise RuntimeError("LLM이 빈 응답을 돌려주었습니다.")
        message = completion.choices[0].message

        output = []
        for i, call in enumerate(getattr(message, "tool_calls", None) or []):
            call_id = getattr(call, "id", None) or f"call_{uuid.uuid4().hex[:12]}_{i}"
            if getattr(call, "id", None) != call_id:
                call.id = call_id          # id가 없으면 만들어 기록과 툴 결과를 이어 준다
            output.append(SimpleNamespace(type="function_call", name=call.function.name,
                                          arguments=call.function.arguments or "{}", call_id=call_id))
        text = message.content or ""
        if text:
            output.append(SimpleNamespace(type="message", content=text))

        response_id = f"chat_{uuid.uuid4().hex}"
        saved = trim_history(history + [_assistant_message(message)])
        with self._lock:
            self._store[response_id] = saved
            while len(self._store) > STORE_LIMIT:
                self._store.popitem(last=False)
        return SimpleNamespace(id=response_id, output=output, output_text=text)


ASPECT_RATIOS = {"1536x1024": "3:2", "1024x1536": "2:3", "1024x1024": "1:1"}


def image_mime(data):
    """그림 바이트의 형식 (Gemini는 JPEG, OpenAI는 PNG를 돌려준다)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class GeminiImages:
    """`client.images.generate / edit`를 흉내 낸다. 안에서는 Gemini 그림 모델(generate_content)을 부른다.

    결과는 OpenAI와 같은 모양(`result.data[0].b64_json`)으로 돌려준다. quality 같은 OpenAI 전용 인자는 무시한다.
    """

    def __init__(self, genai_client):
        self._genai = genai_client

    def _draw(self, model, contents, size):
        if self._genai is None:
            raise RuntimeError("google-genai 패키지가 없어 그림을 그릴 수 없습니다.")
        from google.genai import types
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=ASPECT_RATIOS.get(size, "3:2")))
        response = self._genai.models.generate_content(model=model, contents=contents, config=config)
        for candidate in getattr(response, "candidates", None) or []:
            for part in getattr(getattr(candidate, "content", None), "parts", None) or []:
                data = getattr(getattr(part, "inline_data", None), "data", None)
                if data:
                    return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(data).decode())])
        reason = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
        raise RuntimeError(f"그림이 오지 않았습니다{f' (차단: {reason})' if reason else ''}.")

    def generate(self, model, prompt, size="1536x1024", **_ignored):
        return self._draw(model, prompt, size)

    def edit(self, model, image, prompt, size="1536x1024", **_ignored):
        from google.genai import types
        data = image.read() if hasattr(image, "read") else bytes(image)
        return self._draw(model, [types.Part.from_bytes(data=data, mime_type=image_mime(data)), prompt], size)


class GeminiClient:
    """Gemini를 OpenAI 클라이언트처럼 쓰게 해 주는 묶음: responses·images(어댑터), embeddings(호환 주소)."""

    def __init__(self, chat_client, reasoning_effort=None, genai_client=None):
        self.responses = ChatResponses(chat_client, reasoning_effort)
        self.embeddings = chat_client.embeddings
        self.images = GeminiImages(genai_client)


def make_client(provider=LLM_PROVIDER):
    """설정된 공급자의 클라이언트를 만든다. 키가 없으면 None."""
    from openai import OpenAI
    if provider == "gemini":
        if not GEMINI_API_KEY:
            return None
        try:
            from google import genai
            genai_client = genai.Client(api_key=GEMINI_API_KEY)
        except ImportError:      # 글은 그대로 되고, 그림만 그리지 못한다
            print("⚠️  google-genai 패키지가 없어 장면 그림을 그릴 수 없습니다: pip install -r requirements.txt")
            genai_client = None
        return GeminiClient(OpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL), GEMINI_REASONING_EFFORT,
                            genai_client)
    if not OPENAI_API_KEY:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)


def describe_provider():
    return {"openai": "OpenAI", "gemini": "Google Gemini"}.get(LLM_PROVIDER, LLM_PROVIDER)


def missing_key_message():
    key = "GEMINI_API_KEY" if LLM_PROVIDER == "gemini" else "OPENAI_API_KEY"
    return (f"{describe_provider()} API 키가 없거나 올바르지 않습니다. 프로젝트 폴더의 .env 파일에 "
            f"{key}=... 형태로 실제 키를 넣고 프로그램을 다시 실행하세요.")
