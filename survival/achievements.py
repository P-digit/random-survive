"""여정 기록과 업적: 턴마다 그 턴의 기록(turn_flags)에서 통계를 모으고, 조건을 채우면 업적을 연다.

통계는 한 곳(`record_turn`, `GameState.end_turn`에서 부름)에서만 모은다. 게임이 끝나면 이번 판의 결산을 보여 주고,
업적은 판이 바뀌어도 남는 '명예의 전당'(saves/hall_of_fame.json)에 쌓인다.
"""
import datetime
import json

from .config import SAVE_DIR
from .police import heat_stage

HALL_PATH = SAVE_DIR / "hall_of_fame.json"
HALL_ENABLED = True          # 공유 모드에서는 끈다 (savegame.ENABLED 와 함께)


def _s(state, key, default=0):
    return state.stats.get(key, default)


# (id, 제목, 설명, 조건)
ACHIEVEMENTS = (
    ("first_steps", "첫 발걸음", "처음으로 다른 곳으로 이동했다", lambda st: _s(st, "km") > 0),
    ("long_haul", "대장정", "누적 3,000km를 이동했다", lambda st: _s(st, "km") >= 3000),
    ("globetrotter", "국경 없는 사람", "세 나라 이상을 지났다", lambda st: len(_s(st, "countries", [])) >= 3),
    ("escape_artist", "탈주 전문가", "경찰을 세 번 따돌렸다", lambda st: _s(st, "escapes") >= 3),
    ("most_wanted", "전국 수배", "수배 ★5까지 올라갔다", lambda st: _s(st, "max_heat") >= 5),
    ("jailbird", "감옥 동기", "두 번 체포됐다", lambda st: _s(st, "arrests") >= 2),
    ("working_class", "노동의 가치", "모두 24시간 일했다", lambda st: _s(st, "work_hours") >= 24),
    ("hustler", "장사꾼", "물건을 다섯 개 팔았다", lambda st: _s(st, "sold") >= 5),
    ("jackpot", "잭팟", "도박에서 잭팟을 터뜨렸다", lambda st: _s(st, "jackpots") >= 1),
    ("movie_star", "영화 같은 인생", "극적인 성공을 세 번 거뒀다", lambda st: _s(st, "criticals") >= 3),
    ("collector", "탈것 수집가", "탈것을 세 대 손에 넣었다", lambda st: _s(st, "vehicles") >= 3),
    ("errand_runner", "심부름꾼", "의뢰를 세 번 완수했다", lambda st: _s(st, "missions") >= 3),
    ("smuggler", "밀수꾼", "밀수품을 국경 너머로 무사히 전했다", lambda st: _s(st, "smuggled") >= 1),
    ("survivor", "생존왕", "10일차까지 살아남았다", lambda st: st.day >= 10 and st.status != "dead"),
    ("law_abiding", "모범 시민", "범죄를 한 번도 저지르지 않고 귀환했다",
     lambda st: st.status == "won" and _s(st, "crimes") == 0),
    ("rich_return", "금의환향", "$1,000 이상을 가지고 귀환했다", lambda st: st.status == "won" and st.money >= 1000),
    ("speedrun", "총알 귀환", "5일 안에 귀환했다", lambda st: st.status == "won" and st.day <= 5),
    ("bare_feet", "두 발로", "탈것을 한 번도 갖지 않고 귀환했다",
     lambda st: st.status == "won" and _s(st, "vehicles") == 0),
)
TITLES = {key: (title, desc) for key, title, desc, _ in ACHIEVEMENTS}


def record_turn(state):
    """이번 턴의 기록을 통계에 더하고, 새로 연 업적을 돌려준다 (turn_flags.achievements 에도 남긴다)."""
    st, flags = state.stats, state.turn_flags
    st["turns"] = st.get("turns", 0) + 1
    moved = flags.get("moved")
    if moved:
        st["km"] = st.get("km", 0) + moved.get("km", 0)
        if moved.get("how") == "도보":
            st["walked_km"] = st.get("walked_km", 0) + moved.get("km", 0)
    countries = st.setdefault("countries", [])
    if state.country_code and state.country_code not in countries:
        countries.append(state.country_code)
    st["earned"] = round(st.get("earned", 0) + (flags.get("earned") or 0), 2)
    st["spent"] = round(st.get("spent", 0) + (flags.get("paid") or 0), 2)
    attempt = flags.get("attempt") or {}
    if attempt.get("illegal"):
        st["crimes"] = st.get("crimes", 0) + 1
    if attempt.get("critical"):
        st["criticals"] = st.get("criticals", 0) + 1
    police = flags.get("police") or {}
    if police.get("phase") == "resolved" and police.get("outcome") in ("escaped", "lost"):
        st["escapes"] = st.get("escapes", 0) + 1
    if flags.get("arrested"):
        st["arrests"] = st.get("arrests", 0) + 1
    if flags.get("vehicle"):
        st["vehicles"] = st.get("vehicles", 0) + 1
    if flags.get("border"):
        st["borders"] = st.get("borders", 0) + 1
    economy = flags.get("economy") or {}
    if economy.get("kind") == "work":
        st["work_hours"] = st.get("work_hours", 0) + economy["hours"]
    elif economy.get("kind") == "sell":
        st["sold"] = st.get("sold", 0) + 1
    elif economy.get("kind") == "gamble" and economy.get("jackpot"):
        st["jackpots"] = st.get("jackpots", 0) + 1
    mission = flags.get("mission") or {}
    if mission.get("phase") == "done":
        st["missions"] = st.get("missions", 0) + 1
        if mission.get("kind") == "smuggle":
            st["smuggled"] = st.get("smuggled", 0) + 1
    st["max_heat"] = max(st.get("max_heat", 0), heat_stage(state.wanted))
    st["peak_money"] = max(st.get("peak_money", 0), state.money)

    unlocked = [key for key, _, _, check in ACHIEVEMENTS if key not in state.achievements and check(state)]
    if unlocked:
        state.achievements.extend(unlocked)
        flags["achievements"] = unlocked
        add_to_hall(unlocked)
    return unlocked


def add_to_hall(keys):
    """명예의 전당: 판이 바뀌어도 남는 업적 기록. 저장에 실패해도 게임은 계속된다."""
    if not HALL_ENABLED or not keys:
        return
    try:
        hall = load_hall()
        today = datetime.date.today().isoformat()
        for key in keys:
            entry = hall.setdefault(key, {"count": 0, "first": today})
            entry["count"] += 1
        HALL_PATH.parent.mkdir(exist_ok=True)
        HALL_PATH.write_text(json.dumps(hall, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print(f"[업적] 명예의 전당 저장 실패: {e}")


def load_hall():
    try:
        return json.loads(HALL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_summary(state):
    """게임이 끝났을 때 보여 줄 이번 판의 결산 (마크다운)."""
    st = state.stats
    verdict = "🇰🇷 귀환 성공" if state.status == "won" else "💀 여정의 끝"
    lines = [f"### {verdict} — 여정 결산", ""]
    if state.status == "dead" and state.death_reason:
        lines += [f"*{state.death_reason}*", ""]
    lines += [
             "| 기록 | |", "|---|---|",
             f"| 생존 | {state.day}일 ({st.get('turns', 0)}턴) |",
             f"| 이동 | {st.get('km', 0):,}km (걸어서 {st.get('walked_km', 0):,}km) · 나라 {len(st.get('countries', []))}곳 · "
             f"국경 {st.get('borders', 0)}번 |",
             f"| 돈 | 번 돈 ${st.get('earned', 0):,.0f} · 쓴 돈 ${st.get('spent', 0):,.0f} · 최고 ${st.get('peak_money', 0):,.0f} |",
             f"| 일 | {st.get('work_hours', 0):g}시간 · 판 물건 {st.get('sold', 0)}개 |",
             f"| 범죄 | {st.get('crimes', 0)}번 · 최고 수배 {'★' * st.get('max_heat', 0) or '없음'} · "
             f"따돌림 {st.get('escapes', 0)}번 · 체포 {st.get('arrests', 0)}번 |",
             f"| 탈것·의뢰 | 탈것 {st.get('vehicles', 0)}대 · 의뢰 {st.get('missions', 0)}번 완수 |"]
    if state.achievements:
        lines += ["", f"**🏆 이번 판의 업적 ({len(state.achievements)}/{len(ACHIEVEMENTS)})**", ""]
        lines += [f"- **{TITLES[k][0]}** — {TITLES[k][1]}" for k in state.achievements if k in TITLES]
    hall = load_hall() if HALL_ENABLED else {}
    if hall:
        lines += ["", f"*명예의 전당: 지금까지 {len(hall)}/{len(ACHIEVEMENTS)}개의 업적을 열었습니다.*"]
    return "\n".join(lines)
