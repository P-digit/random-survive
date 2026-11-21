"""게임 상태의 두 기록 dict에 들어가는 키 목록.

- `GameState.turn_flags` (TurnFlags): 이번 턴에 일어난 일. `begin_turn`마다 비워진다.
  엔진(state, tools)이 쓰고, GM 입력·알림(gamemaster), 상태창(ui), 효과음(sound)이 함께 읽는다.
- `GameState.flags` (PlaceFlags): 이동하기 전까지 유지되는 지금 장소의 사정.

키를 문자열로 주고받기 때문에 오탈자가 있어도 오류 없이 조용히 동작이 깨진다(`flags.get("arested")`는 그냥 None).
새 키를 쓰려면 여기에 먼저 적는다. tests/test_flags.py가 코드에서 쓰는 모든 키가 여기에 있는지, 여기 있는 키가
실제로 쓰이는지 검사한다.
"""
from typing import TypedDict


class TurnFlags(TypedDict, total=False):
    # --- 플레이어 입력 ---
    player_text: str              # 이번 턴의 입력 (시작 턴은 "")
    prev_suggestions: list        # 지난 턴의 추천 행동 3개
    crime_intent: str             # 입력의 범죄 의도 판정 (intent.crime_intent)
    pre_offer: dict               # GM 호출 전에 엔진이 판정한 기회 행동 {kind: accept/redo, message, accept}

    # --- 툴 남용 방지 (한 턴에 한 번) ---
    travel: int                   # 이번 턴에 장거리 이동을 했으면 1
    time: int                     # 이번 턴에 시간을 흘렸으면 1

    # --- 먹고 마시기 ---
    intake: bool                  # 수분·포만감이 올랐다 (무언가 먹거나 마셨다)
    consumed: bool                # 소지품이 줄었다
    eaten: list                   # 먹고 마신 것 [{item, stat, amount, partial?, measured?}]
    partial: list                 # 일부만 마신 기록 ["물 1L → 물 750ml (250ml 마심)"]
    removed_items: list           # GM이 지운 소지품 이름
    gm_gain: dict                 # GM이 직접 올려 준 수치 {stat: 양}
    drain: dict                   # 시간 경과로 빠진 수치 {satiety, hydration} (턴 요약용)

    # --- 돈 ---
    paid: float                   # 이번 턴에 쓴 돈
    earned: float                 # 이번 턴에 번 돈
    money_log: list               # GM 툴로 움직인 돈 [{amount: +번 돈/-쓴 돈, why}] (서술에 없으면 알림)

    # --- 사건 (알림·효과음) ---
    attempt: dict                 # 판정 결과 {action, chance, success, effects, ...}
    moved: dict                   # 이동 {how, km, cost, ticket}
    ticket: dict                  # 표 구매 {item, price, sponsored?}
    vehicle: dict                 # 탈것 확보 {name, range_km, stolen?, ...}
    arrested: dict                # 체포 {where, fine, lost}
    new_lead: str                 # 새로 생긴 단서 id
    lead_result: dict             # 단서를 따라가 정체 확인 {label, scene, text, hours, danger}
    offer_result: dict            # 기회를 받아들인 결과 {bad, title, text}
    offer_declined: dict          # 기회 거절 {accept, text}
    offer_expired: dict           # 기회가 지나감 {accept, exit}
    scene_changed: bool           # 장면(set_scene)이 바뀌었다
    police: dict                  # 경찰 {phase: spotted(등장)/resolved(대응 판정), who, action, outcome, chance, effects}
    laying_low: bool              # 플레이어가 숨어 지낸다 (수배도가 더 빨리 내려간다)
    disguise: dict                # 변장 시도 결과 {ok, with(쓴 물건) / why(못 한 이유)}
    economy: dict                 # 일·판매·숙소·도박 결과 {kind: work/sell/room/gamble, amount, ...}
    border: dict                  # 자기 탈것으로 국경을 넘음 {from, to, stopped(경비대와 마주침)}
    achievements: list            # 이번 턴에 새로 연 업적 id
    mission: dict                 # 의뢰 {phase: offered/passed/accepted/done/failed, kind, target, reward, ...}


class PlaceFlags(TypedDict, total=False):
    on_road: bool                 # 차가 다니는 도로 위 (히치하이킹이 쉬워진다)
    can_call: bool                # 전화가 터진다
    at_airport: bool              # 국제공항에 있다
    at_embassy: bool              # 한국 공관에 있다
    embassy_contacted: bool       # 공관과 연락이 닿았다
    embassy_visited: bool         # 공관을 방문했다
    repatriation: bool            # 공관의 귀국 지원을 받는 중


TURN_FLAG_KEYS = frozenset(TurnFlags.__annotations__)
PLACE_FLAG_KEYS = frozenset(PlaceFlags.__annotations__)
