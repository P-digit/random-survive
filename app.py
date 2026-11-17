"""랜덤 좌표 생존기 - 실행 파일.

    python app.py

실행 후 터미널에 표시되는 주소(기본 http://127.0.0.1:7860)를 브라우저로 열면 된다.
"""
import inspect

import gradio as gr

from survival import imagegen, risk_model, savegame
from survival.config import OPENAI_API_KEY, REDRAW_DISTANCE_KM
from survival.gamemaster import get_client, run_turn
from survival.state import create_game
from survival.weather import weather_category
from survival.ui import (CSS, INTRO_MESSAGE, TITLE_HTML, render_hud, render_location,
                         render_notices, turn_summary)


def make(component, **kwargs):
    """Gradio 버전에 따라 없는 인자는 빼고 컴포넌트를 만든다. (5.x / 6.x 호환)"""
    allowed = inspect.signature(component.__init__).parameters
    return component(**{k: v for k, v in kwargs.items() if k in allowed})


def intro_chat():
    return [{"role": "assistant", "content": INTRO_MESSAGE}]


def view(state, chat, busy=False):
    """화면의 모든 출력 컴포넌트 값을 한 번에 만든다. (OUTPUTS 순서와 같아야 함)"""
    playing = state is not None and state.status == "playing"
    suggestions = state.suggestions if playing else []
    buttons = []
    for i in range(3):
        if i < len(suggestions):
            buttons.append(gr.update(value=suggestions[i], visible=True, interactive=not busy))
        else:
            buttons.append(gr.update(visible=False))
    if busy:
        placeholder = "진행 중..."
    elif playing:
        placeholder = "무엇을 할까요? 예) 강을 따라 하류로 내려간다"
    elif state is None:
        placeholder = "먼저 '낙하 시작'을 누르세요"
    else:
        placeholder = "게임이 끝났습니다. '낙하 시작'으로 다시 도전하세요"
    return (
        state,
        chat,
        render_hud(state),
        render_location(state),
        state.image_path if state is not None else None,
        *buttons,
        gr.update(value="", interactive=playing and not busy, placeholder=placeholder),
        gr.update(value="🎲 새로 낙하" if state is not None else "🎲 낙하 시작", interactive=not busy),
        gr.update(visible=state is None and not busy and savegame.exists()),   # 이어하기 버튼
    )


def needs_new_image(state):
    if state.status == "dead":
        return False
    return (state.image_path is None or state.scene_dirty
            or state.moved_since_image >= REDRAW_DISTANCE_KM
            or state.image_weather != weather_category(state.weather.get("code", 0)))  # 비·눈·폭풍이 시작/그침


def draw_scene(state):
    path = imagegen.generate_scene(get_client(), state)
    if path:
        state.image_path = path
        # 실제로 그려진 것을 읽어 두었다가 다음 턴에 게임 마스터에게 알려 준다 (그림과 서술의 일치)
        state.scene_seen = imagegen.describe_image(get_client(), path)
    state.scene_dirty = False
    state.moved_since_image = 0.0
    state.image_weather = weather_category(state.weather.get("code", 0))
    savegame.save(state)


def new_game(use_image):
    """새 게임: 랜덤 좌표 → 날씨 조회 → GM의 첫 서술 → 장면 이미지."""
    chat = [{"role": "assistant", "content": "🛰️ 무작위 좌표를 고르고 현지 날씨를 수신하는 중..."}]
    yield view(None, chat, busy=True)
    try:
        state = create_game()
        opening = run_turn(state, None)
    except Exception as e:
        chat = intro_chat() + [{"role": "assistant", "content": f"⚠️ 게임을 시작하지 못했습니다: {e}"}]
        yield view(None, chat)
        return
    state.chat = [{"role": "assistant", "content": opening}]
    savegame.save(state)   # 새 게임이 시작되면 이전 저장을 덮어쓴다
    yield view(state, state.chat, busy=use_image)
    if use_image:
        draw_scene(state)
        yield view(state, state.chat)


def resume_game(use_image):
    """자동 저장된 게임을 불러와 이어서 한다."""
    state = savegame.load()
    if state is None:
        yield view(None, intro_chat() + [{"role": "assistant", "content": "⚠️ 이어할 수 있는 저장 파일이 없습니다."}])
        return
    notice = {"role": "assistant",
              "content": f"*💾 저장된 게임을 불러왔습니다 — {state.day}일차 {state.hour:02d}:00, {state.place_name}*"}
    redraw = use_image and needs_new_image(state)
    yield view(state, state.chat + [notice], busy=redraw)
    if redraw:
        draw_scene(state)
        yield view(state, state.chat + [notice])


def play(message, state, use_image):
    """한 턴 진행: 플레이어 행동 → GM 서술(+툴 호출) → 필요하면 장면 이미지 갱신."""
    message = (message or "").strip()
    if state is None or state.status != "playing" or not message:
        yield view(state, state.chat if state is not None else intro_chat())
        return

    state.chat = state.chat + [{"role": "user", "content": message}]
    yield view(state, state.chat + [{"role": "assistant", "content": "..."}], busy=True)
    try:
        reply = run_turn(state, message)
        reply = render_notices(state.notices) + reply + turn_summary(state)
    except Exception as e:
        reply = f"⚠️ 오류가 발생했습니다. 다시 시도해 주세요. ({e})"
    state.chat = state.chat + [{"role": "assistant", "content": reply}]
    savegame.save(state)   # 매 턴 자동 저장 (게임이 끝났으면 저장 파일 삭제)

    redraw = use_image and needs_new_image(state)
    yield view(state, state.chat, busy=redraw)
    if redraw:
        draw_scene(state)
        yield view(state, state.chat)


def build_app():
    blocks_kwargs = {"title": "랜덤 좌표 생존기"}
    # Gradio 5는 css/theme를 Blocks에, Gradio 6은 launch에 넘긴다
    style = {"css": CSS, "theme": gr.themes.Base(primary_hue="amber", neutral_hue="stone")}
    css_in_launch = "css" in inspect.signature(gr.Blocks.launch).parameters
    if not css_in_launch:
        blocks_kwargs.update(style)

    with gr.Blocks(**blocks_kwargs) as demo:
        state = gr.State(None)
        gr.HTML(TITLE_HTML)

        with gr.Row():
            # 왼쪽: 장면 + 대화
            with gr.Column(scale=7):
                scene = make(gr.Image, label="현재 장면", show_label=False, interactive=False,
                             height=380, elem_id="scene", type="filepath")
                location = gr.HTML(render_location(None))
                chatbot = make(gr.Chatbot, value=intro_chat(), type="messages", height=430,
                               show_label=False, elem_id="log")
                with gr.Row(elem_id="actions"):
                    quick = [gr.Button("", visible=False) for _ in range(3)]
                msg = gr.Textbox(show_label=False, interactive=False, lines=1,
                                 placeholder="먼저 '낙하 시작'을 누르세요")
            # 오른쪽: 상태창
            with gr.Column(scale=4, min_width=320):
                start = gr.Button("🎲 낙하 시작", variant="primary", elem_id="start-btn")
                resume = gr.Button("💾 이어하기", visible=savegame.exists(), elem_id="resume-btn")
                hud = gr.HTML(render_hud(None))
                use_image = gr.Checkbox(value=True, label="장면 이미지 생성 (끄면 더 빠르고 저렴)")

        outputs = [state, chatbot, hud, location, scene, *quick, msg, start, resume]
        start.click(new_game, inputs=[use_image], outputs=outputs)
        resume.click(resume_game, inputs=[use_image], outputs=outputs)
        # 페이지를 새로고침하면 화면이 처음 상태로 돌아가므로, 이어하기 버튼을 다시 판단한다
        demo.load(lambda: gr.update(visible=savegame.exists()), outputs=[resume])
        msg.submit(play, inputs=[msg, state, use_image], outputs=outputs)
        for button in quick:
            button.click(play, inputs=[button, state, use_image], outputs=outputs)

    return demo, (style if css_in_launch else {})


if __name__ == "__main__":
    if not OPENAI_API_KEY:
        print("⚠️  OPENAI_API_KEY가 없거나 올바르지 않습니다. "
              ".env.example을 .env로 복사한 뒤 안내 문구를 지우고 실제 키를 입력하세요.")
    risk_model.load_model()   # 첫 실행 시 위험도 모델 학습 (몇 초)
    demo, launch_kwargs = build_app()
    demo.launch(**launch_kwargs)
