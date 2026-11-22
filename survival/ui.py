"""화면 꾸미기: CSS와 화면 조각(상단 상태줄·신체 수치·알림·정보 탭·지도) HTML 생성.

화면은 한 화면에 모두 들어오게 짠다 (넓은 화면에서는 페이지 자체가 스크롤되지 않는다):

    ┌ 상단 상태줄: 제목 · 날짜/시각 · 날씨 · 한국까지 · 돈 · 수배 ★ · 낙하/이어하기 ─────────────┐
    │ 장면 그림          │ 이야기(대화 로그, 이 안에서만 스크롤)   │ 탭: 상황(지도) / 소지품 / 기록 │
    │ 위치               │ 지금 결정할 일(기회·경찰·의뢰)           │                                │
    │ 신체 수치          │ 추천 행동 1·2·3 + 입력창                 │                                │
    └────────────────────┴──────────────────────────────────────────┴────────────────────────────────┘

좁은 화면(휴대폰)에서는 세로로 쌓고 평소처럼 스크롤한다.
"""
import json
from html import escape
from pathlib import Path

from . import geo
from .config import EARLY_GAME_HOURS, SEOUL, TRAVEL_RULES

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
  --layout-gap: 10px; --block-padding: 0px;
}
body, .gradio-container {
  background: radial-gradient(1200px 600px at 20% -10%, #1a2219 0%, var(--bg) 60%) fixed !important;
  color: var(--text); font-family: 'IBM Plex Sans KR', system-ui, sans-serif !important;
}
.gradio-container { max-width: 1800px !important; margin: 0 auto !important; padding: 10px 14px !important; }
footer { display: none !important; }
.gradio-container .html-container { padding: 0 !important; }
.gradio-container .block:has(> .html-container), .gradio-container .block:has(.prose) { border: 0; background: none; }

/* ---------- 상단 상태줄 ---------- */
#topbar { align-items: center; gap: 10px; flex-wrap: wrap; }
#topbar > * { min-width: 0; }
#title { font-family: 'Black Han Sans', sans-serif; font-size: 24px; color: var(--amber); white-space: nowrap;
  text-shadow: 0 0 18px #f2a93b40; line-height: 1.1; }
#title small { display: block; font-family: 'JetBrains Mono', monospace; font-size: 9px; letter-spacing: 2px;
  color: var(--muted); text-shadow: none; }
#title-wrap { flex: 0 0 auto !important; width: auto !important; }
#strip-wrap { flex: 1 1 auto !important; }
.strip { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.stat { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 10px; background: var(--panel);
  border: 1px solid var(--line); white-space: nowrap; font-size: 13px; color: var(--muted); }
.stat b { font-family: 'JetBrains Mono', monospace; font-size: 17px; color: var(--text); font-weight: 700; }
.stat .day { font-family: 'Black Han Sans', sans-serif; font-size: 20px; color: var(--amber); font-weight: 400; }
.stat .mini { width: 70px; height: 6px; border-radius: 99px; background: #0b0e0b; border: 1px solid var(--line); overflow: hidden; }
.stat .mini i { display: block; height: 100%; background: var(--amber); }
.stat.money b { color: var(--amber); }
.stat.wanted { border-color: var(--red); color: var(--red); }
.stat.wanted b { color: var(--red); letter-spacing: 1px; }
.stat.wanted.chase { animation: siren 1s infinite; }
.stat.idle { color: var(--muted); }
#topbar button { flex: 0 0 auto !important; min-width: 0 !important; white-space: nowrap; padding: 8px 16px; }
#start-btn { font-family: 'Black Han Sans', sans-serif; font-size: 17px; letter-spacing: 1px; }
#resume-btn { border: 1px solid var(--green) !important; color: var(--green) !important; }
#image-toggle { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; background: none; border: 0; }
#image-toggle label { white-space: nowrap; font-size: 12px; padding: 6px 10px; }

/* ---------- 장면 + 위치 + 신체 수치 (왼쪽) ---------- */
#scene { border: 1px solid var(--line); border-radius: 10px 10px 0 0; overflow: hidden; background: #0a0c0a; }
#scene img { object-fit: cover; width: 100%; height: 100%; }
.loc { background: var(--panel); border: 1px solid var(--line); border-top: 2px solid var(--amber);
  border-radius: 0 0 10px 10px; padding: 8px 12px; }
.loc .name { font-size: 16px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.loc .coord { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--muted); margin-top: 2px; }
.loc .badges { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.badge { display: inline-block; padding: 1px 9px; border-radius: 99px; font-size: 12px;
  border: 1px solid var(--line); background: var(--panel-2); color: var(--text); white-space: nowrap; }
.badge.amber { border-color: var(--amber); color: var(--amber); }
.badge.red { border-color: var(--red); color: var(--red); }

/* ---------- 이야기 (가운데) ---------- */
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

/* 추천 행동: 숫자 키 1·2·3으로도 누를 수 있다 (keys.js) */
#actions { counter-reset: act; gap: 8px; }
#actions button { counter-increment: act; font-size: 14px; min-height: 42px; height: auto; white-space: normal;
  word-break: keep-all; line-height: 1.35; padding: 7px 10px 7px 34px; text-align: left; position: relative;
  border: 1px solid var(--line); transition: border-color .15s, transform .15s; }
#actions button::before { content: counter(act); position: absolute; left: 9px; top: 50%; transform: translateY(-50%);
  width: 18px; height: 18px; border-radius: 5px; border: 1px solid var(--amber); color: var(--amber);
  font-family: 'JetBrains Mono', monospace; font-size: 11px; line-height: 16px; text-align: center; }
#actions button:hover { border-color: var(--amber); transform: translateY(-1px); }
#actions button.pressed { border-color: var(--amber); background: #2c2413; }
#msg textarea { font-size: 15px; }

/* ---------- 지금 결정할 일: 기회·경찰·의뢰 (가운데, 행동 버튼 바로 위) ---------- */
.alerts { display: flex; flex-direction: column; gap: 8px; }
.alert { border-radius: 10px; padding: 10px 14px; border: 1px solid var(--amber); background: #2c241366; }
.alert h4 { margin: 0 0 4px; font-family: 'Black Han Sans', sans-serif; font-weight: 400; font-size: 16px;
  letter-spacing: 1px; color: var(--amber); }
.alert .what { font-size: 14px; line-height: 1.55; color: var(--text); }
.alert .row { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 4px; font-size: 13px; }
.alert .gain { color: var(--green); font-weight: 600; }
.alert .warn { color: var(--amber); }
.alert .hint { font-size: 12px; color: var(--muted); }
.alert.offer { border-color: var(--green); background: #14261acc; animation: glow 1.6s infinite; }
.alert.offer h4 { color: var(--green); }
.alert.mission { border-color: var(--violet); background: #1f1a2bcc; }
.alert.mission h4 { color: var(--violet); }
.alert.police { border-color: var(--red); background: #2a1415e6; animation: siren 1s infinite; }
.alert.police h4 { color: var(--red); }
.odds { display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px; margin-top: 6px; }
.odds div { text-align: center; padding: 4px 2px; border-radius: 6px; background: #0b0e0bcc; font-size: 12px;
  color: var(--text); border: 1px solid var(--line); }
.odds b { display: block; font-family: 'JetBrains Mono', monospace; font-size: 14px; }
.odds .hi b { color: var(--green); } .odds .mid b { color: var(--amber); } .odds .lo b { color: var(--red); }
.odds .na { opacity: .45; }
.banner { text-align: center; padding: 12px; border-radius: 10px; font-family: 'Black Han Sans', sans-serif;
  font-size: 24px; letter-spacing: 2px; }
.banner.dead { background: #2a1415; border: 1px solid var(--red); color: var(--red); }
.banner.won { background: #14261a; border: 1px solid var(--green); color: var(--green); }
.banner small { display: block; font-family: 'IBM Plex Sans KR', sans-serif; font-size: 12px;
  letter-spacing: 0; color: var(--muted); margin-top: 4px; }

/* ---------- 카드 (공통) ---------- */
.hud { display: flex; flex-direction: column; gap: 8px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
.card h4 { margin: 0 0 6px; font-size: 11px; letter-spacing: 2px; color: var(--muted);
  font-family: 'JetBrains Mono', monospace; font-weight: 400; display: flex; justify-content: space-between; }
.card.vitals { padding: 8px 12px; }
.bar-row { display: grid; grid-template-columns: 62px 1fr 30px 36px; align-items: center; gap: 8px; margin: 5px 0;
  font-size: 13px; color: var(--text); }
.bar { height: 10px; background: #0b0e0b; border: 1px solid var(--line); border-radius: 99px; overflow: hidden; }
.bar > i { display: block; height: 100%; border-radius: 99px; transition: width .5s ease; }
.bar-row .num { font-family: 'JetBrains Mono', monospace; font-size: 12px; text-align: right; color: var(--muted); }
.low { animation: pulse 1.2s infinite; }
/* 지난 턴의 수치 변화: 증가는 초록, 감소는 빨강 */
.delta { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 700;
  text-align: right; animation: pop .6s ease-out; white-space: nowrap; }
.delta.up { color: var(--green); }
.delta.down { color: var(--red); }
.delta.inline { margin-left: 4px; font-size: 12px; }
@keyframes pop { 0% { transform: translateY(6px) scale(1.5); opacity: 0; } 100% { transform: none; opacity: 1; } }
.bar-row.changed-up .bar { box-shadow: 0 0 0 1px var(--green); }
.bar-row.changed-down .bar { box-shadow: 0 0 0 1px var(--red); }
.hazard { font-size: 13px; line-height: 1.6; color: var(--text); }
.sub { font-size: 12px; color: var(--muted); line-height: 1.5; }
.card.extreme { border-color: var(--red); background: #1f1516; }
.card.extreme h4 { color: var(--red); }
.dist { font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 700; color: var(--text); }
.dist small { font-size: 12px; color: var(--muted); font-weight: 400; }
.route { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); }
.risk { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; }
.risk div { text-align: center; padding: 4px 0; border-radius: 6px; font-size: 12px;
  background: var(--panel-2); color: var(--muted); border: 1px solid transparent; }
.risk div b { display: block; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 400; }
.risk .on0 { border-color: var(--green); color: var(--green); }
.risk .on1 { border-color: var(--amber); color: var(--amber); }
.risk .on2 { border-color: var(--red); color: var(--red); background: #2a1415; }
.money { font-family: 'JetBrains Mono', monospace; font-size: 20px; color: var(--amber); font-weight: 700; }
.chips { display: flex; flex-wrap: wrap; gap: 5px; }
.chip { font-size: 12px; padding: 3px 9px; border-radius: 6px; background: var(--panel-2);
  border: 1px solid var(--line); color: var(--text); }
.chip.hot { border-color: var(--red); color: #f3a3a5; }
.fares, .stats { border: 0 !important; margin: 0 !important; }
.fares tr, .stats tr, .fares td, .stats td { border: 0 !important; background: none !important; }
.fares { width: 100%; border-collapse: collapse; font-size: 12px; }
.fares td { padding: 3px 0; color: var(--muted); border: none; background: none; }
.fares td:last-child { text-align: right; font-family: 'JetBrains Mono', monospace; }
.fares tr.ok td { color: var(--text); }
.fares tr.ok td:first-child::before { content: '● '; color: var(--green); }
.fares tr.no td:first-child::before { content: '○ '; }
.empty { color: var(--muted); font-size: 13px; line-height: 1.8; }

/* 지도 */
.map svg { display: block; width: 100%; height: auto; border-radius: 8px; background: #0a0f0b;
  border: 1px solid var(--line); }
.map .legend { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 6px; font-size: 11px; color: var(--muted); }
.map .legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }

/* 업적 */
.ach { display: grid; grid-template-columns: repeat(2, 1fr); gap: 5px; }
.ach div { padding: 6px 8px; border-radius: 8px; border: 1px solid var(--line); background: var(--panel-2);
  font-size: 12px; line-height: 1.35; color: var(--muted); }
.ach div b { display: block; font-size: 13px; }
.ach div.on { border-color: var(--amber); background: #2c2413; color: var(--text); }
.ach div.on b { color: var(--amber); }
.ach div.off { opacity: .55; }
.stats { width: 100%; border-collapse: collapse; font-size: 12px; }
.stats td { padding: 2px 0; border: none; background: none; color: var(--muted); }
.stats td:last-child { text-align: right; color: var(--text); font-family: 'JetBrains Mono', monospace; }

/* 정보 탭 */
#panel-tabs { background: none; border: 0; }
#panel-tabs button[role="tab"] { font-size: 14px; padding: 6px 12px; }

@keyframes glow { 50% { box-shadow: 0 0 14px #6fcf7f55; } }
@keyframes pulse { 50% { opacity: .45; } }
@keyframes siren { 0%, 100% { box-shadow: 0 0 12px #e5484d88; } 50% { box-shadow: 0 0 12px #5bb8f088; } }

/* 위급할 때 화면 가장자리: 몸이 위험하면 붉게 맥박, 경찰이 쫓으면 경광등 */
body:has(.vitals.critical) .gradio-container::after, body:has(.alert.police) .gradio-container::after {
  content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 40; }
body:has(.vitals.critical) .gradio-container::after { box-shadow: inset 0 0 90px #e5484d70; animation: pulse 1.4s infinite; }
body:has(.alert.police) .gradio-container::after { animation: edge-siren 1s infinite; }
@keyframes edge-siren { 0%, 100% { box-shadow: inset 0 0 80px #e5484d66; } 50% { box-shadow: inset 0 0 80px #5bb8f066; } }

/* ---------- 한 화면에 맞추기 (넓은 화면) ----------
   바깥 틀은 FRAME_CSS(<head>)가 화면 높이에 맞추고, 여기서는 상단 줄을 뺀 나머지 높이를 가운데 줄(#main-row)이
   정확히 채우게 한다. 긴 내용은 각 칸 안에서만 스크롤된다. */
@media (max-width: 999px) {
  #scene { height: 260px; }
  #actions { flex-direction: column; }
  #actions button { width: 100%; }
  #strip-wrap { flex-basis: 100% !important; }
}
@media (min-width: 1000px) {
  #topbar { flex: 0 0 auto; flex-wrap: nowrap; }
  #actions { flex-wrap: nowrap; }
  #topbar .strip { flex-wrap: nowrap; overflow: hidden; }
  #main-row { flex: 1 1 auto; min-height: 0; flex-wrap: nowrap; align-items: stretch; }
  #left-col, #center-col, #right-col { min-height: 0; flex-wrap: nowrap; overflow: hidden; }
  #left-col { gap: 0 !important; }
  #left-col > #scene { flex: 1 1 0; min-height: 120px; height: auto !important; }
  #left-col > *, #center-col > * { flex-shrink: 0; }
  #left-col > #loc-wrap { margin-bottom: 10px; }
  #center-col > #log { flex: 1 1 0; min-height: 140px; height: auto !important; }
  #center-col > #alerts-wrap { max-height: 45%; overflow-y: auto !important; }
  #right-col > #panel-tabs { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
  #panel-tabs > .tabitem, #panel-tabs [role="tabpanel"] { flex: 1 1 auto; min-height: 0; overflow-y: auto;
    padding: 6px 2px 0 0 !important; }
}
@media (min-width: 1000px) and (max-width: 1500px) {
  .stat .feel, .stat .mini, #title small { display: none; }
  .stat { padding: 5px 9px; gap: 6px; }
  #title { font-size: 20px; }
}
/* 키가 작은 노트북 화면: 조금 더 촘촘하게 */
@media (min-width: 1000px) and (max-height: 760px) {
  .bar-row { margin: 3px 0; }
  #title small { display: none; }
  .stat { padding: 4px 10px; }
  #log .message, #log .bubble-wrap { font-size: 14px; line-height: 1.65; }
}

/* 배경 소리 켜기/끄기와 크기 (static/sound.js가 만든다) */
#rs-sound-controls { position: fixed; right: 16px; bottom: 16px; z-index: 50; display: flex; gap: 8px;
  align-items: center; padding: 6px 10px; border: 1px solid var(--line); border-radius: 999px;
  background: var(--panel); color: var(--text); font-size: 13px; box-shadow: 0 4px 16px rgba(0,0,0,.35); }
#rs-sound-controls button { background: none; border: 0; color: inherit; cursor: pointer; font: inherit; padding: 2px 4px; }
#rs-sound-controls input { width: 90px; accent-color: var(--amber); }
#rs-sound-controls input:disabled { opacity: .4; }
/* 상단 줄에 자리를 잡으면 떠 있지 않고 줄 안에 놓인다 */
#rs-sound-slot #rs-sound-controls { position: static; box-shadow: none; padding: 5px 10px; }
#rs-sound-slot #rs-sound-controls input { width: 70px; }
#sound-wrap { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
"""

# Gradio는 사용자 CSS의 @media 안 규칙을 '.gradio-container .contain' 아래로 한정해 버려서, 그 바깥의 틀
# (body, .gradio-container, .main, .wrap, .contain)은 CSS 인자로는 고칠 수 없다. 그래서 <head>에 직접 넣는다.
FRAME_CSS = """
@media (min-width: 1000px) {
  body { overflow: hidden; }
  .gradio-container { height: 100vh !important; min-height: 0 !important; padding: 8px 12px !important; }
  .gradio-container > .main { padding: 0 !important; flex-direction: column !important; flex: 1 1 auto !important;
    min-height: 0 !important; }
  .gradio-container > .main > .wrap, .gradio-container > .main > .wrap > .contain,
  .gradio-container > .main > .wrap > .contain > .column {
    flex: 1 1 auto !important; min-height: 0 !important; display: flex !important; flex-direction: column !important; }
}
"""

TITLE_HTML = '<div id="title">랜덤 좌표 생존기<small>RANDOM DROP · GET BACK TO KOREA</small></div>'

INTRO_MESSAGE = (
    "**당신은 지구 어딘가에 떨어집니다.**\n\n"
    "좌표는 무작위, 날씨는 그곳의 *실제 현재 날씨*입니다. "
    "가진 것은 물 한 병과 에너지바, 라이터, 칼, 여권, 배터리가 얼마 남지 않은 스마트폰, 그리고 50달러뿐.\n\n"
    "- 하고 싶은 행동을 자유롭게 입력하거나, 아래 추천 행동 버튼(키보드 **1·2·3**)을 누르세요.\n"
    "- 체력이 0이 되면 사망, **한국에 도착하면 승리**입니다.\n"
    "- 모든 행동에는 시간이 흐르고, 수치가 변하면 초록(+)·빨강(-)으로 표시됩니다.\n"
    "- 설원·사막·고산·열대우림은 **극한 지형**입니다. 불과 쉘터 없이 버티면 오래 못 갑니다.\n"
    "- 마을과 도시를 찾아 돈을 벌고, 버스·기차·배·비행기를 타고 돌아오세요.\n"
    "- 가끔 **큰 기회**(구조대, 장거리 트럭, 영사관의 도움 등)나 의뢰, 경찰이 나타납니다. "
    "이야기 아래 상자에 무엇을 고를 수 있는지와 확률이 나옵니다.\n"
    "- 오른쪽 탭에서 **지도**, 소지품, 업적을 볼 수 있습니다.\n"
    "- 진행 상황은 매 턴 자동 저장됩니다. 껐다 켜도 **이어하기**로 계속할 수 있습니다.\n\n"
    "준비되면 위쪽의 **🎲 낙하 시작**을 누르세요."
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




# ---------- 상단 상태줄 ----------
def render_topbar(state):
    """맨 위 한 줄: 날짜·시각, 날씨, 한국까지 남은 거리, 돈, 수배."""
    if state is None:
        return ('<div class="strip"><span class="stat idle">🛰️ 낙하 대기 중 · 좌표 미정 — '
                '<b style="font-size:13px">🎲 낙하 시작</b>을 누르세요</span></div>')
    w, d = state.weather, state.delta
    progress = 0 if state.start_distance <= 0 else (1 - state.distance / state.start_distance) * 100
    sky = "🌌" if state.is_night and w.get("code") in (0, 1) else w["emoji"]
    parts = [
        '<div class="strip">',
        f'<span class="stat"><span class="day">DAY {state.day}</span>'
        f'<b>{"🌙" if state.is_night else "🌞"} {state.hour:02d}:00</b>'
        + (f'<span class="delta up inline" style="color:var(--amber)">+{_hours_text(d["hours"])}</span>'
           if d.get("hours", 0) > 0 else "") + '</span>',
        f'<span class="stat" title="{escape(w["description"])} · 습도 {w["humidity"]:.0f}% · 바람 {w["wind_speed"]:.0f}km/h">'
        f'{sky} <b>{w["temperature"]:.0f}°C</b><span class="feel">체감 {w["feels_like"]:.0f}°</span></span>',
        f'<span class="stat">🇰🇷 <b>{state.distance:,.0f}</b>km'
        f'{_delta(d.get("distance", 0), inline=True, good_when_up=False)}'
        f'<span class="mini"><i style="width:{max(2, progress):.0f}%"></i></span></span>',
        f'<span class="stat money">💵 <b>${state.money:,.0f}</b>{_delta(d.get("money", 0), inline=True)}</span>',
    ]
    if state.wanted >= 1 or state.pursuit:
        from .police import STAGE_NAMES, stars
        chase = " chase" if state.pursuit else ""
        parts.append(f'<span class="stat wanted{chase}">🚨 <b>{stars(state.wanted)}</b>{STAGE_NAMES[state.heat]}</span>')
    parts.append('</div>')
    return "".join(parts)


# ---------- 위치 (장면 그림 아래) ----------
def render_location(state):
    """장면 그림 아래의 위치 표시줄."""
    if state is None:
        return ('<div class="loc"><div class="name">위치 미확인</div>'
                '<div class="coord">--.----°, --.----°</div></div>')
    ns = "N" if state.lat >= 0 else "S"
    ew = "E" if state.lon >= 0 else "W"
    climate = f' · {escape(state.climate["label"])} · {escape(state.climate["season"])}' if state.climate else ""
    return (
        '<div class="loc">'
        f'<div class="name" title="{escape(state.place_name)}">📍 {escape(state.place_name)}</div>'
        f'<div class="coord">{abs(state.lat):.4f}°{ns}, {abs(state.lon):.4f}°{ew}'
        f' · 고도 {state.weather["elevation"]:.0f}m{climate}</div>'
        '<div class="badges">'
        + (f'<span class="badge">{"🏠" if state.indoor else "🧭"} {escape(state.scene_place)}</span>'
           if state.scene_place else "")
        + f'<span class="badge">지형: {escape(state.biome_name)}</span>'
        f'<span class="badge amber">장소: {escape(state.place_type)}</span></div></div>'
    )


# ---------- 신체 수치 ----------
CRITICAL = {"health": 25, "hydration": 15, "satiety": 10}   # 이보다 낮으면 화면 가장자리가 붉게 맥박친다


def is_critical(state):
    return state.status == "playing" and any(getattr(state, k) < v for k, v in CRITICAL.items())


def render_vitals(state):
    if state is None:
        return ('<div class="card vitals"><h4>VITALS</h4>'
                '<div class="empty">낙하하면 체력·포만감·수분·기력이 이곳에 표시됩니다.</div></div>')
    d = state.delta
    critical = " critical" if is_critical(state) else ""
    return (f'<div class="card vitals{critical}"><h4><span>VITALS</span>'
            + ('<span style="color:var(--red)">⚠ 위급</span>' if critical else "") + '</h4>'
            + _bar("❤️ 체력", state.health, "var(--red)", d.get("health", 0))
            + _bar("🍖 포만감", state.satiety, "var(--amber)", d.get("satiety", 0))
            + _bar("💧 수분", state.hydration, "var(--blue)", d.get("hydration", 0))
            + _bar("⚡ 기력", state.energy, "var(--violet)", d.get("energy", 0))
            + '</div>')


# ---------- 지금 결정할 일 (행동 버튼 바로 위) ----------
def _odds_class(chance):
    if chance is None:
        return ""
    return "hi" if chance >= 0.55 else "mid" if chance >= 0.3 else "lo"


def render_alerts(state):
    """게임 끝 배너, 경찰(대응별 성공 확률), 큰 기회, 의뢰 제안. 없으면 빈 문자열."""
    if state is None:
        return ""
    parts = []
    if state.status == "dead":
        parts.append(f'<div class="banner dead">YOU DIED<small>{state.day}일차 · '
                     f'한국까지 {state.distance:,.0f}km를 남기고 쓰러졌다 — 위의 🎲 새로 낙하로 다시 도전</small></div>')
    elif state.status == "won":
        parts.append(f'<div class="banner won">귀환 성공<small>{state.day}일 만에 '
                     f'{state.start_distance:,.0f}km를 돌아왔다 — 결산은 이야기 맨 아래에</small></div>')
    if state.status != "playing":
        return '<div class="alerts">' + "".join(parts) + '</div>'

    if state.pursuit:
        p = state.pursuit
        cells = ""
        for o in state.police_odds():
            value = "확정" if o["chance"] is None else f'{o["chance"] * 100:.0f}%'
            na = " na" if o["chance"] == 0 else ""
            cells += f'<div class="{_odds_class(o["chance"])}{na}">{escape(o["label"])}<b>{value}</b></div>'
        parts.append(f'<div class="alert police"><h4>🚨 {"추격" if p["kind"] == "chase" else "검문"} — '
                     f'{escape(p["who"])}</h4>'
                     '<div class="hint">다음 행동으로 대응하세요. 엔진이 아래 확률로 판정합니다 '
                     '(자수는 확실히 붙잡히지만 처벌이 가볍습니다).</div>'
                     f'<div class="odds">{cells}</div></div>')

    if state.offer:
        o = state.offer
        keep = ("거절하거나 그 자리를 떠나기 전까지 남아 있습니다 · 한 번만 열 수 있습니다" if o.get("id") == "supply"
                else "다음 행동에서 받아들이지 않으면 사라집니다")
        parts.append(f'<div class="alert offer"><h4>✨ 기회</h4><div class="what">{escape(o["text"])}</div>'
                     f'<div class="row"><span class="gain">▲ {escape(o["detail"])}</span>'
                     + (f'<span class="warn">⚠ {escape(o["risk"])}</span>' if o.get("risk") else "")
                     + f'</div><div class="hint">{keep} → “{escape(o["accept"])}”</div></div>')

    if state.mission_offer:
        m = state.mission_offer
        smuggle = m["kind"] == "smuggle"
        parts.append(f'<div class="alert mission"><h4>📦 의뢰 제안 — {escape(m["giver"])}</h4>'
                     f'<div class="what">{escape(m["item"])}을(를) <b>{escape(m["target"])}</b>까지 '
                     f'({escape(m.get("direction") or "")} 약 {m["km"]:,}km, {m["hours"]}시간 안에)</div>'
                     f'<div class="row"><span class="gain">보수 ${m["reward"]:,}</span>'
                     + ('<span class="warn">⚠ 밀수 — 나라를 넘을 때 세관·국경에서 걸릴 수 있음</span>' if smuggle else "")
                     + '</div><div class="hint">받으려면 “의뢰를 맡겠다”, 아니면 다른 행동을 하세요.</div></div>')
    return '<div class="alerts">' + "".join(parts) + '</div>' if parts else ""


# ---------- 지도 ----------
MAP_ASPECT = 2.0          # 지도의 가로:세로
MAP_MIN_SPAN = 60         # 가장 많이 확대해도 경도 60도 폭은 보여 준다
MAP_PAD = 8               # 관심 지점 둘레의 여백(도)


LAND_PATH = Path(__file__).resolve().parent.parent / "data" / "world_land.json"
_land = None


def land_rings():
    """육지 윤곽 [(경도 범위, 위도 범위, 점들)] — Natural Earth 110m(퍼블릭 도메인)을 단순화한 것. 없으면 빈 목록."""
    global _land
    if _land is None:
        try:
            rings = json.loads(LAND_PATH.read_text(encoding="utf-8"))
        except Exception:
            rings = []
        _land = [((min(p[0] for p in r), max(p[0] for p in r)), (min(p[1] for p in r), max(p[1] for p in r)), r)
                 for r in rings]
    return _land


def _land_paths(west, north, width, height):
    """지도 범위에 걸치는 육지만 SVG 경로로. 서울 기준으로 펼친 경도라서 각 윤곽을 0°와 +360° 두 자리에 놓아 본다."""
    south, east = north - height, west + width
    out = []
    for (lo, hi), (bottom, top), ring in land_rings():
        if top < south or bottom > north:
            continue
        for shift in (0, 360):
            if hi + shift < west or lo + shift > east:
                continue
            out.append("M" + "L".join(f"{x + shift:g},{-y:g}" for x, y in ring) + "Z")
    return "".join(out)


def _unwrap(lon):
    """서울 기준으로 경도를 펼친다: 알래스카(-150°)는 서울(127°)의 동쪽 210°로 그려 날짜변경선에서 끊기지 않게."""
    while lon < SEOUL[1] - 180:
        lon += 360
    while lon > SEOUL[1] + 180:
        lon -= 360
    return lon


def map_frame(points):
    """관심 지점(현재 위치·서울·발자취·목적지)을 모두 담는 지도 범위: (서쪽 경도, 북쪽 위도, 폭, 높이)."""
    lons = [_unwrap(lon) for _, lon in points]
    lats = [lat for lat, _ in points]
    west, east = min(lons) - MAP_PAD, max(lons) + MAP_PAD
    south, north = min(lats) - MAP_PAD, max(lats) + MAP_PAD
    width = min(360, max(east - west, (north - south) * MAP_ASPECT, MAP_MIN_SPAN))   # 지구 한 바퀴보다 넓게는 안 본다
    height = width / MAP_ASPECT
    cx, cy = (west + east) / 2, (south + north) / 2
    north = min(90, cy + height / 2)
    if north - height < -90:
        north = -90 + height
    return cx - width / 2, north, width, height


def render_map(state):
    """세계 지도(도시 점으로 대륙 윤곽을 그린다) 위에 서울, 현재 위치, 지나온 길, 목적지를 표시한다."""
    from . import places
    trail = [tuple(p) for p in state.stats.get("trail", [])]
    here = (state.lat, state.lon)
    targets = []
    if state.mission:
        targets.append(("mission", state.mission["lat"], state.mission["lon"], state.mission["target"]))
    if state.journey:
        targets.append(("journey", state.journey["lat"], state.journey["lon"], state.journey["label"]))
    west, north, width, height = map_frame([here, SEOUL] + trail + [(t[1], t[2]) for t in targets])
    s = width / 100                                   # 점·선 굵기를 지도 배율에 맞춘다

    def xy(lat, lon):
        return f"{_unwrap(lon):.2f},{-lat:.2f}"

    land = f'<path d="{_land_paths(west, north, width, height)}" fill="#1f2b21" stroke="#34463a" stroke-width="{0.2 * s:.2f}"/>'
    dots = "".join(f'<circle cx="{_unwrap(c["lon"]):.2f}" cy="{-c["lat"]:.2f}" r="{0.45 * s:.2f}"/>'
                   for c in places.CITY_LIST)
    path = ""
    if len(trail) > 1:
        path = (f'<polyline points="{" ".join(xy(*p) for p in trail + [here])}" fill="none" stroke="#f2a93b" '
                f'stroke-width="{0.45 * s:.2f}" stroke-linejoin="round" opacity=".9"/>')
    marks = ""
    for kind, lat, lon, label in targets:
        color = "#b79cf2" if kind == "mission" else "#5bb8f0"
        r = 1.1 * s
        x, y = _unwrap(lon), -lat
        marks += (f'<path d="M{x:.2f},{y - r:.2f} L{x + r:.2f},{y:.2f} L{x:.2f},{y + r:.2f} L{x - r:.2f},{y:.2f}Z" '
                  f'fill="{color}"><title>{escape(label)}</title></path>')
    seoul = (f'<line x1="{_unwrap(state.lon):.2f}" y1="{-state.lat:.2f}" x2="{SEOUL[1]:.2f}" y2="{-SEOUL[0]:.2f}" '
             f'stroke="#6fcf7f" stroke-width="{0.25 * s:.2f}" stroke-dasharray="{s:.2f} {s:.2f}" opacity=".6"/>'
             f'<circle cx="{SEOUL[1]:.2f}" cy="{-SEOUL[0]:.2f}" r="{1.2 * s:.2f}" fill="#6fcf7f"><title>서울</title></circle>')
    me = (f'<circle cx="{_unwrap(state.lon):.2f}" cy="{-state.lat:.2f}" r="{1.3 * s:.2f}" fill="#e5484d" '
          f'stroke="#fff" stroke-width="{0.3 * s:.2f}"><title>현재 위치</title></circle>'
          f'<circle cx="{_unwrap(state.lon):.2f}" cy="{-state.lat:.2f}" r="{1.3 * s:.2f}" fill="none" '
          f'stroke="#e5484d" stroke-width="{0.3 * s:.2f}"><animate attributeName="r" from="{1.3 * s:.2f}" '
          f'to="{4 * s:.2f}" dur="1.6s" repeatCount="indefinite"/><animate attributeName="opacity" from="1" to="0" '
          f'dur="1.6s" repeatCount="indefinite"/></circle>')
    legend = ('<span><i style="background:#e5484d"></i>나</span><span><i style="background:#6fcf7f"></i>서울</span>'
              + ('<span><i style="background:#f2a93b"></i>지나온 길</span>' if path else "")
              + ('<span><i style="background:#b79cf2"></i>의뢰 목적지</span>' if state.mission else "")
              + ('<span><i style="background:#5bb8f0"></i>가는 곳</span>' if state.journey else ""))
    return (f'<div class="card map"><h4><span>MAP</span><span>{state.distance:,.0f}km 남음</span></h4>'
            f'<svg viewBox="{west:.2f} {-north:.2f} {width:.2f} {height:.2f}" preserveAspectRatio="xMidYMid slice" '
            f'role="img" aria-label="지도">{land}<g fill="#4d6650">{dots}</g>{path}{seoul}{marks}{me}</svg>'
            f'<div class="legend">{legend}</div></div>')


# ---------- 정보 탭: 상황 ----------
def render_status(state):
    if state is None:
        return ('<div class="hud"><div class="card"><h4>STATUS</h4>'
                '<div class="empty">아직 낙하 전입니다.<br>게임을 시작하면 지도와 남은 거리, 수배, 의뢰, '
                '주변 환경과 위험도가 이곳에 표시됩니다.</div></div></div>')
    parts = ['<div class="hud">', render_map(state)]
    d = state.delta

    # 남은 거리 + 지금 하고 있는 일
    progress = 0 if state.start_distance <= 0 else (1 - state.distance / state.start_distance) * 100
    route = (f'<div class="dist">{state.distance:,.0f} <small>km 남음</small>'
             f'{_delta(d.get("distance", 0), inline=True, good_when_up=False, unit="km")}</div>'
             f'<div class="bar" style="margin:6px 0 4px"><i style="width:{max(2, progress):.0f}%;background:var(--amber)"></i></div>'
             f'<div class="route"><span>출발 {state.start_distance:,.0f}km</span><span>🇰🇷 서울</span></div>')
    if state.early and state.status == "playing":
        route += (f'<div class="hazard" style="margin-top:6px">🧭 초반 탐색 중 · 약 '
                  f'{max(1, round(EARLY_GAME_HOURS - state.elapsed_hours))}시간 뒤부터 도시·공항·공관으로 갈 수 있음</div>')
    if state.journey:
        route += (f'<div class="hazard" style="margin-top:6px">🚶 <b>{escape(state.journey["label"])}</b>(으)로 가는 중 · '
                  f'약 {geo.haversine_km(state.lat, state.lon, state.journey["lat"], state.journey["lon"]):,.0f}km 남음</div>')
    if state.mission:
        m = state.mission
        km = geo.haversine_km(state.lat, state.lon, m["lat"], m["lon"])
        route += (f'<div class="hazard" style="margin-top:6px">📦 <b>{escape(m["target"])}</b>까지 {escape(m["item"])} · '
                  f'약 {km:,.0f}km · ${m["reward"]:,} · {max(0, m["deadline"] - state.elapsed_hours):.0f}시간 남음'
                  + (' · <b style="color:var(--red)">밀수</b>' if m["kind"] == "smuggle" else "") + '</div>')
    parts.append(f'<div class="card"><h4>ROUTE TO KOREA</h4>{route}</div>')

    # 수배도
    if state.wanted >= 1 or state.pursuit:
        from .police import STAGE_NAMES, stars
        change = d.get("wanted", 0)       # 수배도는 오르는 게 나쁜 것이므로 색을 뒤집는다
        rows = (f'<div class="hazard">🚨 <b>{stars(state.wanted)}</b> {STAGE_NAMES[state.heat]}'
                + (' · <span class="badge">변장 중</span>' if state.disguised else "")
                + (' · <span class="badge red">경찰이 쫓는 중</span>' if state.pursuit else "") + "</div>")
        rows += (_bar("🚨 수배", state.wanted, "var(--red)", change)
                 .replace(_delta(change), _delta(change, good_when_up=False))
                 .replace("changed-up", "changed-tmp").replace("changed-down", "changed-up")
                 .replace("changed-tmp", "changed-down"))
        rows += '<div class="sub">숨어 지내거나(방을 빌리면 더 빨리) 변장하면 수배도가 내려갑니다.</div>'
        parts.append(f'<div class="card"><h4>OUTLAW</h4>{rows}</div>')

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
                     '<div class="sub">그쪽으로 가면 정체를 확인할 수 있습니다</div></div>')

    # ML 위험도 + 기후
    cells = ""
    for i, label in enumerate(["안전", "주의", "위험"]):
        on = f' class="on{i}"' if state.risk["level"] == i else ""
        cells += f'<div{on}>{label}<b>{state.risk["probs"][i] * 100:.0f}%</b></div>'
    climate = ""
    c = state.climate
    if c:
        numbers = (f'연평균 {c["t_ann"]:.0f}°C · 가장 추운 달 {c["t_cold"]:.0f}°C · 가장 더운 달 {c["t_warm"]:.0f}°C · '
                   f'연강수량 {c["p_ann"]:,}mm' if "t_ann" in c else "기록을 불러오지 못해 위도와 날씨로 추정")
        climate = (f'<div class="hazard" style="margin-top:8px"><b>{escape(c["label"])}</b> · 지금은 {escape(c["season"])}</div>'
                   f'<div class="sub">{numbers}</div>')
    w = state.weather
    parts.append(f'<div class="card"><h4>RISK · ML 예측</h4><div class="risk">{cells}</div>'
                 f'<div class="sub" style="margin-top:6px">{escape(w["description"])} · 습도 {w["humidity"]:.0f}% · '
                 f'바람 {w["wind_speed"]:.0f}km/h</div>{climate}</div>')
    parts.append('</div>')
    return "".join(parts)


# ---------- 정보 탭: 소지품 ----------
def render_bag(state):
    if state is None:
        return '<div class="hud"><div class="card"><h4>INVENTORY</h4><div class="empty">낙하 전입니다.</div></div></div>'
    d = state.delta
    parts = ['<div class="hud">']
    contraband = set(state.stolen_items)
    plain, hot = '<span class="chip">', '<span class="chip hot" title="장물·밀수품: 체포되면 압수">'
    chips = "".join((hot if str(i) in contraband else plain) + f'{escape(str(i))}</span>'
                    for i in state.items) or '<span class="empty">빈손</span>'
    parts.append(f'<div class="card"><h4><span>INVENTORY</span><span>{len(state.items)}개</span></h4>'
                 f'<div class="money">$ {state.money:,.0f}{_delta(d.get("money", 0), inline=True)}</div>'
                 f'<div class="chips" style="margin-top:8px">{chips}</div>'
                 + ('<div class="sub" style="margin-top:6px">붉은 테두리: 장물·밀수품 (체포되면 압수)</div>'
                    if contraband & set(map(str, state.items)) else "") + '</div>')

    # 탈것
    if state.vehicle:
        v = state.vehicle
        stolen = ' <span class="badge red">도난 차량</span>' if v.get("stolen") else ""
        fuel = (f'남은 연료로 약 {v["range_km"]:,}km' if v.get("fuel", True)
                else f'연료 필요 없음(한 번에 약 {v["range_km"]:,}km)')
        parts.append(f'<div class="card"><h4>VEHICLE</h4><div class="hazard">🚙 <b>{escape(v["name"])}</b>{stolen}</div>'
                     f'<div class="sub">{fuel} · {"바다도 건널 수 있음" if v.get("sea") else "육로만"}</div></div>')

    # 일의 기술 + 빌린 방
    from .economy import JOBS
    skills = [f"{JOBS[k][0]} Lv{v}" for k, v in state.skills.items() if v and k in JOBS]
    room = state.lodging if state.lodging and state.elapsed_hours < state.lodging.get("until", 0) else None
    if skills or room:
        rows = ""
        if skills:
            rows += f'<div class="sub">💼 {escape(" · ".join(skills))}</div>'
        if room:
            left = (room["until"] - state.elapsed_hours) / 24
            rows += (f'<div class="sub">🛏 {escape(room["place"])}의 빌린 방 · {left:.1f}일 남음'
                     + (' · <b>지금 은신 중</b>' if state.in_lodging else "") + "</div>")
        parts.append(f'<div class="card"><h4>LIFE</h4>{rows}</div>')

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
    parts.append(f'<div class="card"><h4>TRANSPORT · 여기서 탈 수 있는 것 ●</h4><table class="fares">{rows}</table></div>')
    parts.append('</div>')
    return "".join(parts)


# ---------- 정보 탭: 기록 ----------
def render_record(state):
    from .achievements import ACHIEVEMENTS, load_hall, HALL_ENABLED
    got = set(state.achievements) if state is not None else set()
    hall = load_hall() if HALL_ENABLED else {}
    cells = ""
    for key, title, desc, _ in ACHIEVEMENTS:
        cls = "on" if key in got else "off"
        mark = "🏆 " if key in got else ("🎖 " if key in hall else "🔒 ")
        cells += f'<div class="{cls}" title="{escape(desc)}"><b>{mark}{escape(title)}</b>{escape(desc)}</div>'
    parts = ['<div class="hud">',
             f'<div class="card"><h4><span>ACHIEVEMENTS · 이번 판</span><span>{len(got)}/{len(ACHIEVEMENTS)}</span></h4>'
             f'<div class="ach">{cells}</div>'
             + (f'<div class="sub" style="margin-top:6px">🎖 지난 판들에서 연 업적 · 명예의 전당 {len(hall)}/{len(ACHIEVEMENTS)}</div>'
                if hall else "") + '</div>']
    if state is not None:
        st = state.stats
        rows = [("생존", f"{state.day}일 ({st.get('turns', 0)}턴)"),
                ("이동", f"{st.get('km', 0):,}km · 나라 {len(st.get('countries', []))}곳"),
                ("번 돈 / 쓴 돈", f"${st.get('earned', 0):,.0f} / ${st.get('spent', 0):,.0f}"),
                ("일 · 판 물건", f"{st.get('work_hours', 0):g}시간 · {st.get('sold', 0)}개"),
                ("범죄 · 따돌림 · 체포", f"{st.get('crimes', 0)} · {st.get('escapes', 0)} · {st.get('arrests', 0)}"),
                ("의뢰 완수", f"{st.get('missions', 0)}번")]
        parts.append('<div class="card"><h4>THIS RUN</h4><table class="stats">'
                     + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows) + '</table></div>')
    parts.append('</div>')
    return "".join(parts)


def render_hud(state):
    """정보 탭 세 개를 한 번에 (테스트·디버깅용)."""
    return render_status(state) + render_bag(state) + render_record(state)


# ---------- 배경 소리 · 단축키 ----------
STATIC_DIR = Path(__file__).resolve().parent / "static"
SOUND_JS_PATH = STATIC_DIR / "sound.js"
KEYS_JS_PATH = STATIC_DIR / "keys.js"


def page_head():
    """페이지 <head>에 넣을 것: 화면 틀 CSS, 소리 엔진과 키보드 단축키 스크립트."""
    return f"<style>{FRAME_CSS}</style>" + "".join("<script>\n" + path.read_text(encoding="utf-8") + "\n</script>"
                   for path in (SOUND_JS_PATH, KEYS_JS_PATH))


def render_sound_cue(cue):
    """소리 신호를 화면에 싣는다. 보이지 않는 요소이고, sound.js가 값이 바뀌는 것을 감지해 소리를 바꾼다."""
    data = escape(json.dumps(cue, ensure_ascii=False, separators=(",", ":")), quote=True)
    return f'<div id="rs-sound-cue" hidden data-cue="{data}"></div>'
