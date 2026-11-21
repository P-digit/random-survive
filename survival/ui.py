"""화면 꾸미기: CSS와 HUD(상태창) HTML 생성."""
import json
from html import escape
from pathlib import Path

from . import geo
from .config import EARLY_GAME_HOURS, TRAVEL_RULES

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=IBM+Plex+Sans+KR:wght@400;500;600&family=JetBrains+Mono:wght@400;700&display=swap');

:root, .dark, .gradio-container {
  --bg: #0e110f; --panel: #161b17; --panel-2: #1d241e; --line: #2c372e;
  --text: #dfe5d8; --muted: #8a9686; --amber: #f2a93b; --red: #e5484d;
  --green: #6fcf7f; --blue: #5bb8f0; --violet: #b79cf2;
  --body-background-fill: var(--bg); --background-fill-primary: var(--panel);
  --background-fill-secondary: var(--panel-2); --block-background-fill: var(--panel);
  --block-border-color: var(--line); --border-color-primary: var(--line);
  --body-text-color: var(--text); --body-text-color-subdued: var(--muted);
  --block-label-text-color: var(--muted); --block-title-text-color: var(--muted);
  --input-background-fill: #10140f; --input-border-color: var(--line);
  --input-placeholder-color: #5f6b5d;
  --button-secondary-background-fill: var(--panel-2);
  --button-secondary-background-fill-hover: #263027;
  --button-secondary-text-color: var(--text); --button-secondary-border-color: var(--line);
  --button-primary-background-fill: var(--amber);
  --button-primary-background-fill-hover: #ffc061;
  --button-primary-text-color: #1a1305; --button-primary-border-color: var(--amber);
  --color-accent: var(--amber); --color-accent-soft: #2c2413;
  --checkbox-label-background-fill: var(--panel-2); --checkbox-label-text-color: var(--text);
  --block-radius: 10px; --radius-lg: 10px;
}
body, .gradio-container {
  background: radial-gradient(1200px 600px at 20% -10%, #1a2219 0%, var(--bg) 60%) fixed !important;
  color: var(--text); font-family: 'IBM Plex Sans KR', system-ui, sans-serif !important;
}
.gradio-container { max-width: 1320px !important; margin: 0 auto !important; }
footer { display: none !important; }

/* ---------- 제목 ---------- */
#title { text-align: center; padding: 18px 0 6px; }
#title h1 { font-family: 'Black Han Sans', sans-serif; font-size: 44px; font-weight: 400;
  letter-spacing: 2px; margin: 0; color: var(--amber); text-shadow: 0 0 24px #f2a93b40; }
#title p { margin: 4px 0 0; color: var(--muted); font-family: 'JetBrains Mono', monospace;
  font-size: 12px; letter-spacing: 3px; }

/* ---------- 장면 이미지 ---------- */
#scene { border: 1px solid var(--line); border-radius: 10px 10px 0 0; overflow: hidden;
  background: #0a0c0a; min-height: 260px; }
#scene img { object-fit: cover; width: 100%; }
.loc { display: flex; justify-content: space-between; align-items: center; gap: 12px;
  background: var(--panel); border: 1px solid var(--line); border-top: 2px solid var(--amber);
  border-radius: 0 0 10px 10px; padding: 10px 16px; }
.loc .name { font-size: 18px; font-weight: 600; color: var(--text); }
.loc .coord { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--muted); }
.badge { display: inline-block; padding: 2px 10px; border-radius: 99px; font-size: 12px;
  border: 1px solid var(--line); background: var(--panel-2); color: var(--text); margin-left: 6px;
  white-space: nowrap; }
.badge.amber { border-color: var(--amber); color: var(--amber); }

/* ---------- 대화 로그 ---------- */
#log { border: 1px solid var(--line) !important; background: #121612 !important; }
#log .message, #log .bubble-wrap { font-size: 15px; line-height: 1.75; }
/* 중요 알림: 대화창 안의 눈에 띄는 상자 (인용문 + 제목 단계로 종류를 구분) */
#log blockquote { margin: 2px 0 14px; padding: 10px 14px; border-radius: 8px;
  border: 1px solid var(--amber); border-left: 5px solid var(--amber); background: #2c241366;
  color: var(--text); font-size: 14px; line-height: 1.6; }
#log blockquote p { margin: 4px 0 0; }
#log blockquote h3, #log blockquote h4, #log blockquote h5, #log blockquote h6 {
  margin: 0; font-family: 'Black Han Sans', sans-serif; font-weight: 400; font-size: 18px;
  letter-spacing: 1px; color: var(--amber); }
#log blockquote:has(h3) { border-color: var(--green); background: #14261acc; animation: glow 1.6s 3; }
#log blockquote:has(h3) h3 { color: var(--green); }
#log blockquote:has(h4) { border-color: var(--red); background: #2a1415cc; }
#log blockquote:has(h4) h4 { color: var(--red); }
#log blockquote:has(h6) { border-color: var(--green); background: #14261a99; }
#log blockquote:has(h6) h6 { color: var(--green); }
#log blockquote strong { background: none; padding: 0; }
/* GM이 굵게 표시한 핵심 구절 */
#log strong { color: var(--amber); font-weight: 600; background: #f2a93b1f;
  padding: 1px 5px; border-radius: 4px; }
#log em { color: var(--muted); font-style: normal; font-size: 13px;
  font-family: 'JetBrains Mono', monospace; }
#actions button { font-size: 14px; min-height: 44px; height: auto; white-space: normal; word-break: keep-all;
  line-height: 1.4; padding: 8px 12px; text-align: center; border: 1px solid var(--line);
  transition: border-color .15s, transform .15s; }
#actions button:hover { border-color: var(--amber); transform: translateY(-1px); }
#start-btn { font-family: 'Black Han Sans', sans-serif; font-size: 18px; letter-spacing: 1px; }

/* ---------- HUD ---------- */
.hud { display: flex; flex-direction: column; gap: 10px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.card h4 { margin: 0 0 8px; font-size: 11px; letter-spacing: 2px; color: var(--muted);
  font-family: 'JetBrains Mono', monospace; font-weight: 400; }
.clock { display: flex; justify-content: space-between; align-items: baseline; }
.clock .day { font-family: 'Black Han Sans', sans-serif; font-size: 26px; color: var(--amber); }
.clock .time { font-family: 'JetBrains Mono', monospace; font-size: 18px; color: var(--text); }
.weather { display: flex; align-items: center; gap: 10px; margin-top: 6px; }
.weather .emoji { font-size: 30px; }
.weather .temp { font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 700; color: var(--text); }
.weather .sub { font-size: 12px; color: var(--muted); line-height: 1.5; }
.bar-row { display: grid; grid-template-columns: 62px 1fr 30px 40px; align-items: center; gap: 8px; margin: 7px 0; font-size: 13px; color: var(--text); }
.bar { height: 10px; background: #0b0e0b; border: 1px solid var(--line); border-radius: 99px; overflow: hidden; }
.bar > i { display: block; height: 100%; border-radius: 99px; transition: width .5s ease; }
.bar-row .num { font-family: 'JetBrains Mono', monospace; font-size: 12px; text-align: right; color: var(--muted); }
.low { animation: pulse 1.2s infinite; }
/* 지난 턴의 수치 변화: 증가는 초록, 감소는 빨강 */
.delta { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 700;
  text-align: right; animation: pop .6s ease-out; white-space: nowrap; }
.delta.up { color: var(--green); }
.delta.down { color: var(--red); }
.delta.inline { margin-left: 8px; font-size: 14px; }
@keyframes pop { 0% { transform: translateY(6px) scale(1.5); opacity: 0; } 100% { transform: none; opacity: 1; } }
.bar-row.changed-up .bar { box-shadow: 0 0 0 1px var(--green); }
.bar-row.changed-down .bar { box-shadow: 0 0 0 1px var(--red); }
.elapsed { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--amber);
  border: 1px solid var(--amber); border-radius: 99px; padding: 1px 8px; margin-left: 8px; }
.hazard { font-size: 13px; line-height: 1.6; color: var(--text); }
.card.offer { border-color: var(--green); background: #14261a; animation: glow 1.6s infinite; }
.card.offer h4 { color: var(--green); }
.card.offer .what { font-size: 14px; line-height: 1.6; color: var(--text); }
.card.offer .gain { margin-top: 6px; font-size: 13px; color: var(--green); font-weight: 600; }
.card.offer .warn { margin-top: 4px; font-size: 13px; color: var(--amber); }
.card.offer .hint { margin-top: 6px; font-size: 11px; color: var(--muted); }
@keyframes glow { 50% { box-shadow: 0 0 14px #6fcf7f55; } }
#resume-btn { border: 1px solid var(--green) !important; color: var(--green) !important; }
.card.extreme { border-color: var(--red); background: #1f1516; }
.card.extreme h4 { color: var(--red); }
@keyframes pulse { 50% { opacity: .45; } }
.route { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.dist { font-family: 'JetBrains Mono', monospace; font-size: 24px; font-weight: 700; color: var(--text); }
.dist small { font-size: 12px; color: var(--muted); font-weight: 400; }
.risk { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; }
.risk div { text-align: center; padding: 6px 0; border-radius: 6px; font-size: 12px;
  background: var(--panel-2); color: var(--muted); border: 1px solid transparent; }
.risk div b { display: block; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 400; }
.risk .on0 { border-color: var(--green); color: var(--green); }
.risk .on1 { border-color: var(--amber); color: var(--amber); }
.risk .on2 { border-color: var(--red); color: var(--red); background: #2a1415; }
.money { font-family: 'JetBrains Mono', monospace; font-size: 20px; color: var(--amber); font-weight: 700; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 12px; padding: 3px 9px; border-radius: 6px; background: var(--panel-2);
  border: 1px solid var(--line); color: var(--text); }
.fares { width: 100%; border-collapse: collapse; font-size: 12px; }
.fares td { padding: 3px 0; color: var(--muted); border: none; }
.fares td:last-child { text-align: right; font-family: 'JetBrains Mono', monospace; }
.fares tr.ok td { color: var(--text); }
.fares tr.ok td:first-child::before { content: '● '; color: var(--green); }
.fares tr.no td:first-child::before { content: '○ '; }
.banner { text-align: center; padding: 16px; border-radius: 10px; font-family: 'Black Han Sans', sans-serif;
  font-size: 24px; letter-spacing: 2px; }
.banner.dead { background: #2a1415; border: 1px solid var(--red); color: var(--red); }
.banner.won { background: #14261a; border: 1px solid var(--green); color: var(--green); }
.banner small { display: block; font-family: 'IBM Plex Sans KR', sans-serif; font-size: 12px;
  letter-spacing: 0; color: var(--muted); margin-top: 4px; }
.empty { color: var(--muted); font-size: 13px; line-height: 1.8; }

/* 배경 소리 켜기/끄기와 크기 (static/sound.js가 만든다) */
#rs-sound-controls { position: fixed; right: 16px; bottom: 16px; z-index: 50; display: flex; gap: 8px;
  align-items: center; padding: 6px 10px; border: 1px solid var(--line); border-radius: 999px;
  background: var(--panel); color: var(--text); font-size: 13px; box-shadow: 0 4px 16px rgba(0,0,0,.35); }
#rs-sound-controls button { background: none; border: 0; color: inherit; cursor: pointer; font: inherit; padding: 2px 4px; }
#rs-sound-controls input { width: 90px; accent-color: var(--amber); }
#rs-sound-controls input:disabled { opacity: .4; }
"""

TITLE_HTML = """
<div id="title">
  <h1>랜덤 좌표 생존기</h1>
  <p>RANDOM DROP · REAL WEATHER · GET BACK TO KOREA</p>
</div>
"""

INTRO_MESSAGE = (
    "**당신은 지구 어딘가에 떨어집니다.**\n\n"
    "좌표는 무작위, 날씨는 그곳의 *실제 현재 날씨*입니다. "
    "가진 것은 물 한 병과 에너지바, 라이터, 칼, 여권, 배터리가 얼마 남지 않은 스마트폰, 그리고 50달러뿐.\n\n"
    "- 하고 싶은 행동을 자유롭게 입력하거나, 아래 추천 행동 버튼을 누르세요.\n"
    "- 체력이 0이 되면 사망, **한국에 도착하면 승리**입니다.\n"
    "- 모든 행동에는 시간이 흐르고, 수치가 변하면 상태창에 초록(+)·빨강(-)으로 표시됩니다.\n"
    "- 설원·사막·고산·열대우림은 **극한 지형**입니다. 불과 쉘터 없이 버티면 오래 못 갑니다.\n"
    "- 마을과 도시를 찾아 돈을 벌고, 버스·기차·배·비행기를 타고 돌아오세요.\n\n"
    "- 가끔 **큰 기회**(구조대, 장거리 트럭, 영사관의 도움 등)가 찾아옵니다. 놓치면 사라지지만, "
    "**받아들인다고 항상 좋게 끝나지는 않습니다.**\n"
    "- 진행 상황은 매 턴 자동 저장됩니다. 껐다 켜도 **이어하기**로 계속할 수 있습니다.\n\n"
    "준비되면 오른쪽의 **🎲 낙하 시작**을 누르세요."
)


def _delta(change, inline=False, good_when_up=True, unit=""):
    """수치 변화 표시. 좋아진 쪽은 초록(+), 나빠진 쪽은 빨강(-)."""
    if abs(change) < 0.5:
        return "" if inline else '<span class="delta"></span>'
    kind = "up" if (change > 0) == good_when_up else "down"
    extra = " inline" if inline else ""
    return f'<span class="delta {kind}{extra}">{change:+,.0f}{unit}</span>'


def _bar(label, value, color, change=0.0):
    low = " low" if value < 25 else ""
    changed = "" if abs(change) < 0.5 else (" changed-up" if change > 0 else " changed-down")
    return (f'<div class="bar-row{changed}"><span>{label}</span>'
            f'<div class="bar{low}"><i style="width:{value:.0f}%;background:{color}"></i></div>'
            f'<span class="num">{value:.0f}</span>{_delta(change)}</div>')


def _hours_text(hours):
    if hours < 1:
        return f"{hours * 60:.0f}분"
    return f"{hours:.0f}시간" if abs(hours - round(hours)) < 0.05 else f"{hours:.1f}시간"


# 알림 종류 → 마크다운 제목 단계 (CSS에서 색을 구분한다: h3 초록 강조, h4 빨강, h5 주황, h6 초록)
NOTICE_HEADING = {"offer": "###", "danger": "####", "bad": "####", "info": "#####", "good": "######"}


def render_notices(notices):
    """이번 턴의 중요 알림을 대화창용 마크다운(인용 상자)으로 만든다."""
    blocks = []
    for notice in notices or []:
        lines = [f"> {NOTICE_HEADING.get(notice['kind'], '#####')} {notice['title']}", ">"]
        lines += [f"> {line}  " for line in str(notice["text"]).split("\n") if line.strip()]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n\n" if blocks else "")


def consumption_summary(state):
    """먹고 마신 턴에 수분·포만감이 왜 그만큼 변했는지: '💧 수분 +45 (물 1L) · -4 (시간·더위)'."""
    eaten = state.turn_flags.get("eaten") or []
    if not eaten:
        return ""
    gains = state.turn_flags.get("gm_gain") or {}
    drain = state.turn_flags.get("drain") or {}
    parts = []
    for stat, icon, label in (("hydration", "💧", "수분"), ("satiety", "🍖", "포만감")):
        items = [e["item"] for e in eaten if e["stat"] == stat]
        if not items:
            continue
        line = f"{icon} {label} +{gains.get(stat, 0):.0f} ({', '.join(items)})"
        if drain.get(stat, 0) >= 0.5:
            line += f" · -{drain[stat]:.0f} (시간·{'더위' if state.weather.get('feels_like', 15) >= 30 else '활동'})"
        parts.append(line)
    return " / ".join(parts)


def turn_summary(state):
    """대화창에 붙이는 한 줄 요약: 이번 턴에 흐른 시간과 현재 시각, 먹고 마신 것의 효과."""
    hours = state.delta.get("hours", 0)
    if hours <= 0:
        return ""
    eat = consumption_summary(state)
    return f"\n\n*⏱ {_hours_text(hours)} 경과 → {state.day}일차 {state.hour:02d}:00*" + (f"  \n*{eat}*" if eat else "")


def render_location(state):
    """장면 이미지 아래의 위치 표시줄."""
    if state is None:
        return ('<div class="loc"><div><div class="name">위치 미확인</div>'
                '<div class="coord">--.----°, --.----°</div></div></div>')
    ns = "N" if state.lat >= 0 else "S"
    ew = "E" if state.lon >= 0 else "W"
    return (
        '<div class="loc"><div>'
        f'<div class="name">📍 {escape(state.place_name)}</div>'
        f'<div class="coord">{abs(state.lat):.4f}°{ns}, {abs(state.lon):.4f}°{ew}'
        f' · 고도 {state.weather["elevation"]:.0f}m</div>'
        + (f'<div class="coord">{escape(state.climate["label"])} · {escape(state.climate["season"])}</div>'
           if state.climate else "")
        + '</div>'
        '<div>'
        + (f'<span class="badge">{"🏠" if state.indoor else "🧭"} {escape(state.scene_place)}</span>'
           if state.scene_place else "")
        + f'<span class="badge">지형: {escape(state.biome_name)}</span>'
        f'<span class="badge amber">장소: {escape(state.place_type)}</span></div></div>'
    )


def render_hud(state):
    """오른쪽 상태창 전체."""
    if state is None:
        return ('<div class="hud"><div class="card"><h4>STATUS</h4>'
                '<div class="empty">아직 낙하 전입니다.<br>게임을 시작하면 이곳에 '
                '시간·날씨·체력·위험도·남은 거리가 표시됩니다.</div></div></div>')
    w = state.weather
    d = state.delta
    parts = ['<div class="hud">']

    if state.status == "dead":
        parts.append(f'<div class="banner dead">YOU DIED<small>{state.day}일차 · '
                     f'한국까지 {state.distance:,.0f}km를 남기고 쓰러졌다</small></div>')
    elif state.status == "won":
        parts.append(f'<div class="banner won">귀환 성공<small>{state.day}일 만에 '
                     f'{state.start_distance:,.0f}km를 돌아왔다</small></div>')

    # 대형 이벤트(기회)
    if state.offer and state.status == "playing":
        o = state.offer
        parts.append(f'<div class="card offer"><h4>OPPORTUNITY · 기회</h4>'
                     f'<div class="what">{escape(o["text"])}</div>'
                     f'<div class="gain">▲ 잘 풀리면: {escape(o["detail"])}</div>'
                     + (f'<div class="warn">⚠ {escape(o["risk"])}</div>' if o.get("risk") else "")
                     + f'<div class="hint">{"거절하거나 그 자리를 떠나기 전까지 남아 있습니다 · 한 번만 열 수 있습니다" if o.get("id") == "supply" else "다음 행동에서 받아들이지 않으면 사라집니다"} → “{escape(o["accept"])}”</div></div>')

    # 시간 + 날씨
    parts.append(
        '<div class="card"><div class="clock">'
        f'<span class="day">DAY {state.day}</span>'
        f'<span class="time">{"🌙" if state.is_night else "🌞"} {state.hour:02d}:00'
        + (f'<span class="elapsed">+{_hours_text(d["hours"])}</span>' if d.get("hours", 0) > 0 else "")
        + '</span></div>'
        f'<div class="weather"><span class="emoji">{"🌌" if state.is_night and w.get("code") in (0, 1) else w["emoji"]}</span>'
        f'<span class="temp">{w["temperature"]:.0f}°C</span>'
        f'<span class="sub">{escape(w["description"])} · 체감 {w["feels_like"]:.0f}°C<br>'
        f'습도 {w["humidity"]:.0f}% · 바람 {w["wind_speed"]:.0f}km/h</span></div></div>'
    )

    # 남은 거리
    progress = 0 if state.start_distance <= 0 else (1 - state.distance / state.start_distance) * 100
    parts.append(
        '<div class="card"><h4>ROUTE TO KOREA</h4>'
        f'<div class="dist">{state.distance:,.0f} <small>km 남음</small>'
        f'{_delta(d.get("distance", 0), inline=True, good_when_up=False, unit="km")}</div>'
        f'<div class="bar" style="margin:8px 0 6px"><i style="width:{max(2, progress):.0f}%;background:var(--amber)"></i></div>'
        f'<div class="route"><span>출발 {state.start_distance:,.0f}km</span><span>🇰🇷 서울</span></div>'
        + (f'<div class="hazard" style="margin-top:6px">🧭 초반 탐색 중 · 약 '
           f'{max(1, round(EARLY_GAME_HOURS - state.elapsed_hours))}시간 뒤부터 도시·공항·공관으로 갈 수 있음</div>'
           if state.early and state.status == "playing" else "")
        + (f'<div class="hazard" style="margin-top:6px">🚶 <b>{escape(state.journey["label"])}</b>(으)로 가는 중 · '
           f'약 {geo.haversine_km(state.lat, state.lon, state.journey["lat"], state.journey["lon"]):,.0f}km 남음</div>'
           if state.journey else "")
        + '</div>'
    )

    # 신체 수치
    parts.append('<div class="card"><h4>VITALS</h4>'
                 + _bar("❤️ 체력", state.health, "var(--red)", d.get("health", 0))
                 + _bar("🍖 포만감", state.satiety, "var(--amber)", d.get("satiety", 0))
                 + _bar("💧 수분", state.hydration, "var(--blue)", d.get("hydration", 0))
                 + _bar("⚡ 기력", state.energy, "var(--violet)", d.get("energy", 0))
                 + '</div>')

    # 환경 위험 (야생일 때)
    if state.place_type == "야생":
        extreme = " extreme" if state.hazard["extreme"] else ""
        title = "ENVIRONMENT · 극한 지형" if extreme else "ENVIRONMENT"
        parts.append(f'<div class="card{extreme}"><h4>{title}</h4>'
                     f'<div class="hazard">{escape(state.hazard["desc"])}</div></div>')

    # 단서 (아직 확인하지 않은 '저쪽의 무언가')
    if state.leads and state.status == "playing":
        rows = "".join(f'<div class="hazard">🧭 <b>{escape(l["label"])}</b> · {escape(l["direction"])} 약 {l["km"]}km</div>'
                       for l in state.leads)
        parts.append(f'<div class="card"><h4>CLUES · 단서</h4>{rows}'
                     '<div class="weather"><span class="sub">그쪽으로 가면 정체를 확인할 수 있습니다</span></div></div>')

    # 탈것 + 수배도
    if state.vehicle or state.wanted >= 1 or state.pursuit:
        rows = ""
        if state.vehicle:
            v = state.vehicle
            stolen = ' <span class="badge" style="border-color:var(--red);color:var(--red)">도난 차량</span>' \
                if v.get("stolen") else ""
            fuel = (f'남은 연료로 약 {v["range_km"]:,}km' if v.get("fuel", True)
                    else f'연료 필요 없음(한 번에 약 {v["range_km"]:,}km)')
            rows += (f'<div class="hazard">🚙 <b>{escape(v["name"])}</b>{stolen}</div>'
                     f'<div class="weather"><span class="sub">{fuel} · '
                     f'{"바다도 건널 수 있음" if v.get("sea") else "육로만"}</span></div>')
        if state.wanted >= 1:
            change = d.get("wanted", 0)       # 수배도는 오르는 게 나쁜 것이므로 색을 뒤집는다
            from .police import STAGE_NAMES, stars
            rows += (f'<div class="hazard">🚨 <b>{stars(state.wanted)}</b> {STAGE_NAMES[state.heat]}'
                     + (' · <span class="badge">변장 중</span>' if state.disguised else "")
                     + (' · <span class="badge" style="border-color:var(--red);color:var(--red)">경찰이 쫓는 중</span>'
                        if state.pursuit else "") + "</div>")
            rows += (_bar("🚨 수배", state.wanted, "var(--red)", change)
                     .replace(_delta(change), _delta(change, good_when_up=False))
                     .replace("changed-up", "changed-tmp").replace("changed-down", "changed-up")
                     .replace("changed-tmp", "changed-down"))
        parts.append(f'<div class="card"><h4>OUTLAW</h4>{rows}</div>')

    # 일의 기술 + 빌린 방
    from .economy import JOBS
    skills = [f"{JOBS[k][0]} Lv{v}" for k, v in state.skills.items() if v]
    room = state.lodging if state.lodging and state.elapsed_hours < state.lodging.get("until", 0) else None
    if skills or room:
        rows = ""
        if skills:
            rows += f'<div class="weather"><span class="sub">💼 {escape(" · ".join(skills))}</span></div>'
        if room:
            left = (room["until"] - state.elapsed_hours) / 24
            rows += (f'<div class="weather"><span class="sub">🛏 {escape(room["place"])}의 빌린 방 · {left:.1f}일 남음'
                     + (' · <b>지금 은신 중</b>' if state.in_lodging else "") + "</span></div>")
        parts.append(f'<div class="card"><h4>LIFE</h4>{rows}</div>')

    # 기후
    c = state.climate
    if c:
        numbers = (f'연평균 {c["t_ann"]:.0f}°C · 가장 추운 달 {c["t_cold"]:.0f}°C · 가장 더운 달 {c["t_warm"]:.0f}°C'
                   f'<br>연강수량 {c["p_ann"]:,}mm' if "t_ann" in c else "기록을 불러오지 못해 위도와 날씨로 추정")
        parts.append(f'<div class="card"><h4>CLIMATE</h4><div class="hazard">'
                     f'<b>{escape(c["label"])}</b> · 지금은 {escape(c["season"])}</div>'
                     f'<div class="weather"><span class="sub">{numbers}</span></div></div>')

    # ML 위험도
    cells = ""
    for i, label in enumerate(["안전", "주의", "위험"]):
        on = f' class="on{i}"' if state.risk["level"] == i else ""
        cells += f'<div{on}>{label}<b>{state.risk["probs"][i] * 100:.0f}%</b></div>'
    parts.append(f'<div class="card"><h4>RISK · ML 예측</h4><div class="risk">{cells}</div></div>')

    # 소지금 + 소지품
    chips = "".join(f'<span class="chip">{escape(str(i))}</span>' for i in state.items) \
        or '<span class="empty">빈손</span>'
    parts.append(f'<div class="card"><h4>INVENTORY</h4><div class="money">$ {state.money:,.0f}{_delta(d.get("money", 0), inline=True)}</div>'
                 f'<div class="chips" style="margin-top:8px">{chips}</div></div>')

    # 이동 수단
    rows = ""
    for key, rule in TRAVEL_RULES.items():
        usable = state.place_type in rule["places"]
        if key == "flight":
            price = f'한국까지 ${state.fare(key, state.distance):,.0f}'
        elif rule["per_km"] == 0:
            price = f'무료 · 최대 {rule["max_km"]}km'
        else:
            price = f'100km당 ${rule["per_km"] * 100:.0f} · 최대 {rule["max_km"]:,}km'
        ticket = state.find_ticket(key)
        if ticket:
            price = f'🎫 예약됨 · {"한국까지" if key == "flight" else str(ticket["km"]) + "km"}'
        rows += f'<tr class="{"ok" if usable else "no"}"><td>{rule["label"]}</td><td>{price}</td></tr>'
    if state.vehicle:
        rows = (f'<tr class="ok"><td>{escape(state.vehicle["name"])} (보유)</td>'
                f'<td>무료 · 최대 {state.vehicle["range_km"]:,}km</td></tr>') + rows
    parts.append(f'<div class="card"><h4>TRANSPORT</h4><table class="fares">{rows}</table></div>')

    parts.append('</div>')
    return "".join(parts)


# ---------- 배경 소리 ----------
SOUND_JS_PATH = Path(__file__).resolve().parent / "static" / "sound.js"


def sound_head():
    """페이지 <head>에 넣을 소리 엔진 스크립트."""
    return "<script>\n" + SOUND_JS_PATH.read_text(encoding="utf-8") + "\n</script>"


def render_sound_cue(cue):
    """소리 신호를 화면에 싣는다. 보이지 않는 요소이고, sound.js가 값이 바뀌는 것을 감지해 소리를 바꾼다."""
    data = escape(json.dumps(cue, ensure_ascii=False, separators=(",", ":")), quote=True)
    return f'<div id="rs-sound-cue" hidden data-cue="{data}"></div>'
