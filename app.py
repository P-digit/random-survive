"""랜덤 좌표 생존기 - 실행 파일.

    python app.py            # 내 컴퓨터에서만 접속
    python app.py --share    # 다른 사람도 접속할 수 있는 임시 공개 링크 생성 (시연용)

실행 후 터미널에 표시되는 주소(기본 http://127.0.0.1:7860)를 브라우저로 열면 된다.
"""
import argparse
import inspect

import gradio as gr

from survival import imagegen, risk_model, savegame
from survival.config import IMAGES_SUPPORTED, LLM_MODEL, REDRAW_DISTANCE_KM
from survival.llm import describe_provider, missing_key_message
from survival.gamemaster import get_client, run_turn
from survival.state import create_game
from survival.weather import weather_category
from survival.sound import soundscape, turn_sfx
from survival.ui import (CSS, INTRO_MESSAGE, TITLE_HTML, render_hud, render_location,
                         render_notices, render_sound_cue, sound_head, turn_summary)


def make(component, **kwargs):
    """Gradio 버전에 따라 없는 인자는 빼고 컴포넌트를 만든다. (5.x / 6.x 호환)"""
    allowed = inspect.signature(component.__init__).parameters
    return component(**{k: v for k, v in kwargs.items() if k in allowed})


def intro_chat():
    return [{"role": "assistant", "content": INTRO_MESSAGE}]


def view(state, chat, busy=False, quiet=False):
    """화면의 모든 출력 컴포넌트 값을 한 번에 만든다. (OUTPUTS 순서와 같아야 함)

    quiet: 이번 턴의 효과음을 울리지 않는다 (이어하기: 저장된 마지막 턴의 소리를 다시 울리지 않게)
    """
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
        render_hud(state) + sound_cue(state, quiet),   # 상태창에 소리 신호를 함께 싣는다
        render_location(state),
        state.image_path if state is not None else None,
        *buttons,
        gr.update(value="", interactive=playing and not busy, placeholder=placeholder),
        gr.update(value="🎲 새로 낙하" if state is not None else "🎲 낙하 시작", interactive=not busy),
        gr.update(visible=state is None and not busy and savegame.exists()),   # 이어하기 버튼
    )


def sound_cue(state, quiet=False):
    sfx = turn_sfx(state)
    if quiet:
        sfx["events"] = []      # nonce는 그대로 보내, 브라우저가 이 턴은 이미 지나간 것으로 안다
    return render_sound_cue(dict(soundscape(state), sfx=sfx))


def scene_key(state):
    return f"{state.place_name}|{state.scene_setting}|{state.scene_place}"


def image_update(state):
    """그림을 어떻게 갱신할지: 'new' 새로 그림 / 'edit' 같은 장면의 빛·날씨만 고침 / None 그대로.

    - 다른 곳으로 옮겼거나 장면이 바뀌었으면 새로 그린다.
    - 같은 곳에서 낮↔밤이나 비·눈·폭풍이 바뀌었으면, 야외는 이전 그림을 편집해 빛·날씨만 바꾼다.
      실내는 창밖 정도만 달라지므로 다시 그리지 않는다. 그래야 구성과 인물이 바뀌지 않는다.
    """
    if state.status == "dead":
        return None
    if (state.image_path is None or state.scene_dirty or state.image_scene != scene_key(state)
            or state.moved_since_image >= REDRAW_DISTANCE_KM):
        return "new"
    changed = (state.image_night != state.is_night
               or state.image_weather != weather_category(state.weather.get("code", 0)))
    if changed and not state.indoor:
        return "edit"
    return None


def needs_new_image(state):
    return image_update(state) is not None


def draw_scene(state):
    mode = image_update(state)
    if mode == "edit":
        # 편집도 그림을 다시 읽어 확인한다. 장면에 없던 건물이 생기면 그 편집본은 버린다(이전 그림 유지).
        path, seen = imagegen.checked_edit(get_client(), state, state.image_path)
        if path:
            state.image_path = path
            # 화면에 걸린 그림에 보이는 것은 GM도 알아야 한다 (그림에 보이면 들어가거나 다가갈 수 있다)
            state.scene_seen = list(dict.fromkeys(list(state.scene_seen) + list(seen or [])))[:10]
    elif mode == "new":
        path = imagegen.generate_scene(get_client(), state)
        if path:
            state.image_path = path
            # 실제로 그려진 것을 읽어 두었다가 다음 턴에 게임 마스터에게 알려 준다 (그림과 서술의 일치)
            state.scene_seen, state.scene_seen_en = imagegen.read_image(get_client(), path)
    state.scene_dirty = False
    state.moved_since_image = 0.0
    state.image_scene = scene_key(state)
    state.image_night = state.is_night
    state.image_weather = weather_category(state.weather.get("code", 0))
    savegame.save(state)


def new_game(use_image):
    """새 게임: 랜덤 좌표 → 날씨 조회 → GM의 첫 서술 → 장면 이미지."""
    use_image = use_image and IMAGES_SUPPORTED   # 그림을 못 그리는 공급자면 꺼 둔다
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
    use_image = use_image and IMAGES_SUPPORTED   # 그림을 못 그리는 공급자면 꺼 둔다
    state = savegame.load()
    if state is None:
        yield view(None, intro_chat() + [{"role": "assistant", "content": "⚠️ 이어할 수 있는 저장 파일이 없습니다."}])
        return
    notice = {"role": "assistant",
              "content": f"*💾 저장된 게임을 불러왔습니다 — {state.day}일차 {state.hour:02d}:00, {state.place_name}*"}
    redraw = use_image and needs_new_image(state)
    yield view(state, state.chat + [notice], busy=redraw, quiet=True)
    if redraw:
        draw_scene(state)
        yield view(state, state.chat + [notice], quiet=True)


def play(message, state, use_image):
    """한 턴 진행: 플레이어 행동 → GM 서술(+툴 호출) → 필요하면 장면 이미지 갱신."""
    use_image = use_image and IMAGES_SUPPORTED   # 그림을 못 그리는 공급자면 꺼 둔다
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
    style = {"css": CSS, "theme": gr.themes.Base(primary_hue="amber", neutral_hue="stone"), "head": sound_head()}
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
                use_image = gr.Checkbox(
                    value=IMAGES_SUPPORTED, interactive=IMAGES_SUPPORTED,
                    label="장면 이미지 생성 (끄면 더 빠르고 저렴)" if IMAGES_SUPPORTED
                    else f"장면 이미지 생성 ({describe_provider()}에서는 아직 지원하지 않음)")

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
    parser = argparse.ArgumentParser(description="랜덤 좌표 생존기")
    parser.add_argument("--share", action="store_true",
                        help="Gradio 공유 링크(https://xxxx.gradio.live)를 만들어 다른 사람도 접속하게 한다")
    args = parser.parse_args()
    if get_client() is None:
        print("⚠️  " + missing_key_message() + " (.env.example을 .env로 복사해서 쓰면 됩니다)")
    else:
        print(f"🤖 LLM: {describe_provider()} · {LLM_MODEL}"
              + ("" if IMAGES_SUPPORTED else " · 장면 그림은 이 공급자에서 아직 지원하지 않아 꺼집니다"))
    risk_model.load_model()   # 첫 실행 시 위험도 모델 학습 (몇 초)
    if args.share:
        # 접속자들이 저장 파일 하나를 함께 쓰면 서로의 게임을 덮어쓰게 되므로, 공유 중에는 저장을 끈다
        savegame.ENABLED = False
        print("🌐 공유 모드: 아래 'public URL' 주소를 전달하세요. 이 프로그램이 켜져 있는 동안만 접속됩니다.")
        print("   공유 모드에서는 자동 저장/이어하기가 꺼지고, 접속자 모두가 이 컴퓨터의 API 키를 사용합니다.")
    demo, launch_kwargs = build_app()
    demo.launch(share=args.share, **launch_kwargs)
