"""게임 마스터(LLM)가 호출할 수 있는 툴 목록과 실제 실행 함수."""
import json

from . import knowledge
from .config import TRAVEL_RULES


def _function(name, description, properties):
    """Responses API 형식의 function tool 정의를 만든다. (strict 모드: 모든 인자 필수)"""
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties.keys()),
            "additionalProperties": False,
        },
    }


TOOLS = [
    _function(
        "advance_time",
        "플레이어의 행동에 걸린 시간을 흘려보낸다. 이동(travel)을 제외한 모든 행동에서 반드시 한 번 호출한다. "
        "시간에 따라 포만감·수분·기력이 자동으로 변하고, 야생에서는 지형과 날씨에 따라 체력이 깎인다.",
        {
            "hours": {"type": "number",
                      "description": "실제로 걸린 시간(시간 단위, 0.25~12). 기준: 대화·짧은 행동 0.25~0.5, "
                                     "불 피우기·쉘터 만들기 1~2, 물·식량 찾기 1~3, 휴식 1~3, 일하기 4~8, "
                                     "취침 6~8. 플레이어가 시간을 말했으면 그 시간을 쓴다."},
            "activity": {"type": "string",
                         "enum": ["rest", "sleep", "forage", "work", "explore", "other"],
                         "description": "행동 종류. rest 휴식, sleep 수면, forage 물·식량 구하기, work 일하기, explore 탐색, other 그 외"},
            "sheltered": {"type": "boolean",
                          "description": "이 시간 동안 불·쉘터·실내·차량 등으로 추위/더위/비를 피하고 있으면 true. "
                                         "그냥 야외에 노출되어 있으면 false."},
        },
    ),
    _function(
        "update_status",
        "행동이나 이벤트의 결과로 플레이어 수치를 변화시킨다. 변화가 없는 항목은 0을 넣는다. "
        "예: 물을 마심 hydration +30, 넘어져 다침 health -10, 일해서 돈을 범 money +40.",
        {
            "health": {"type": "number", "description": "체력 변화량 (-40~+30)"},
            "satiety": {"type": "number", "description": "포만감 변화량 (-40~+60)"},
            "hydration": {"type": "number", "description": "수분 변화량 (-40~+60)"},
            "energy": {"type": "number", "description": "기력 변화량 (-40~+40)"},
            "money": {"type": "number", "description": "소지금 변화량(USD). 한 번에 최대 +120"},
            "consumed_items": {"type": "array", "items": {"type": "string"},
                               "description": "이 행동으로 먹거나 마시거나 써서 없어진 소지품의 이름들. "
                                              "받아 둔 빗물, 딴 열매처럼 환경에서 얻어 소지품에 넣어 둔 것도 "
                                              "쓰면 반드시 여기에 적는다. 없으면 빈 배열"},
            "reason": {"type": "string", "description": "변화의 이유를 한 문장으로"},
        },
    ),
    _function(
        "update_inventory",
        "소지품을 추가하거나 제거한다. 물건을 얻거나, 잃어버리거나, 팔았을 때 호출한다. "
        "소지품은 손에 들거나 배낭에 넣어 가지고 다닐 수 있는 물건만 된다. 오두막·동굴·오아시스·개울 같은 "
        "장소와 지형, 차량, 동물, 사람은 소지품이 아니므로 넣지 않는다(발견한 사실만 서술한다).",
        {
            "add": {"type": "array", "description": "새로 얻은 물건들. 없으면 빈 배열",
                    "items": {"type": "object", "additionalProperties": False,
                              "required": ["name", "carryable"],
                              "properties": {
                                  "name": {"type": "string", "description": "물건 이름. 수량이 있으면 '생수 2병'처럼 적는다"},
                                  "carryable": {"type": "boolean",
                                                "description": "혼자 들고 이동할 수 있는 물건이면 true, 아니면 false"}}}},
            "remove": {"type": "array", "items": {"type": "string"}, "description": "없어진 물건 이름들. 없으면 빈 배열"},
        },
    ),
    _function(
        "travel",
        "한국 방향으로 이동한다. 플레이어가 이번 턴에 이동을 지시했을 때만, 한 턴에 한 번만 호출한다. "
        "성공 여부, 요금, 도착지는 게임 엔진이 결정하므로 결과를 보고 서술한다. "
        "수단별 조건: walk(어디서나, 최대 30km), hitchhike(어디서나, 최대 250km, 실패할 수 있음), "
        "bus(마을/도시, 최대 600km), train(도시, 최대 1500km), ship(도시, 최대 3000km), "
        "flight(도시, 항상 한국까지 직항이며 distance_km 은 무시됨, 가장 비쌈). "
        "이동은 호출 즉시 도착까지 끝난다. 이동 중인 장면에서 멈추지 말고 도착한 곳의 상황으로 서술을 끝낸다.",
        {
            "method": {"type": "string", "enum": list(TRAVEL_RULES.keys()), "description": "이동 수단"},
            "distance_km": {"type": "number", "description": "이동할 거리(km)"},
        },
    ),
    _function(
        "set_scene",
        "플레이어가 서 있는 구체적인 곳을 정한다. 이 내용 그대로 장면 이미지가 그려지므로, 서술과 그림이 "
        "어긋나지 않도록 서술에 등장시킨 건물·지형지물은 빠짐없이 여기에 적는다. "
        "게임 시작 턴과 travel 로 새 장소에 도착한 턴에는 반드시 호출한다. 그 밖에는 장면이 눈에 띄게 바뀌었을 때 호출한다. "
        "호출할 때: 실내로 들어감(오두막, 동굴, 집, 가게, 식당, 역·터미널·공항 대합실, 영사관 등), "
        "실내에서 밖으로 나옴, 같은 지역 안에서 풍경이 전혀 다른 곳으로 옮김(숲 속 → 강가, 골목 → 시장 광장). "
        "호출하지 않을 때: 같은 곳에 머물며 행동만 하는 경우.",
        {
            "setting": {"type": "string", "enum": ["outdoor", "indoor"], "description": "실외면 outdoor, 실내면 indoor"},
            "place": {"type": "string", "description": "장소의 짧은 한국어 이름. 예: '빈 오두막 안', '강가', '버스 터미널 대합실'. "
                                                       "같은 곳이면 이전과 똑같은 이름을 쓴다."},
            "description_en": {"type": "string",
                               "description": "그 장소에서 눈에 보이는 풍경을 영어로 2~3문장 묘사(그림 생성용). "
                                              "그 지역의 기후·계절·식생에 맞게, visible_features 를 모두 포함해서 쓴다. "
                                              "사물·구조·빛 위주로, 사람은 묘사하지 않는다. "
                                              "예: 'Inside a small abandoned log cabin, a rusty iron stove, "
                                              "a wooden bunk, frost on the single window.'"},
            "visible_features": {"type": "array", "items": {"type": "string"},
                                 "description": "그 장면에서 눈에 보이고 플레이어가 다가가거나 이용할 수 있는 주요 대상 2~5개 "
                                                "(한국어). 예: ['버려진 오두막', '얼어붙은 개울', '침엽수림']. "
                                                "여기에 적은 것은 실제로 존재하는 것으로 확정된다. "
                                                "건물이 없는 곳이면 건물을 적지 않는다."},
        },
    ),
    _function(
        "reject_event",
        "이번 턴에 주어진 [돌발 이벤트]나 [기회]가 현재 장면·상황에서 도저히 일어날 수 없을 때 호출해 취소한다. "
        "예: 건물 안에 있는데 '트럭이 멈춰 선다'. 취소한 이벤트는 서술에 넣지 않는다.",
        {"reason": {"type": "string", "description": "맞지 않는 이유를 한 문장으로"}},
    ),
    _function(
        "accept_offer",
        "[기회]로 주어진 대형 이벤트의 제안을 플레이어가 받아들였을 때 호출한다. 결과가 좋을지 나쁠지는 "
        "게임 엔진이 정해서 돌려준다(outcome). 나쁜 결과면 그대로 냉정하게 서술한다. 이때는 advance_time, travel 을 따로 호출하지 않는다. "
        "플레이어가 거절하거나 다른 행동을 하면 호출하지 않는다(기회는 사라진다).",
        {},
    ),
    _function(
        "search_survival_guide",
        "생존 지식 문서에서 관련 내용을 검색한다. 플레이어가 생존 방법을 묻거나, 위험한 상황"
        "(저체온증, 뱀, 탈수, 고산병, 여권 분실 등)의 올바른 대처가 결과에 영향을 줄 때 호출한다.",
        {
            "query": {"type": "string", "description": "검색할 내용. 예: '뱀에 물렸을 때 응급처치'"},
        },
    ),
]


def execute_tool(state, name, arguments, client=None):
    """툴 이름과 JSON 인자를 받아 게임 상태에 반영하고, LLM에게 돌려줄 결과 문자열을 만든다."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except json.JSONDecodeError:
        return json.dumps({"error": "인자를 해석할 수 없음"}, ensure_ascii=False)

    try:
        if state.status != "playing" and name != "search_survival_guide":
            result = {"error": "게임이 이미 끝났다."}
        elif name in ("advance_time", "travel") and state.turn_flags.get("travel", 0) >= 1:
            result = {"error": "이번 턴에는 이미 이동했다. 한 턴에는 플레이어가 지시한 행동 하나만 처리한다. "
                               "지금까지의 결과만 서술하고 플레이어의 다음 지시를 기다려라."}
        elif name == "advance_time" and state.turn_flags.get("time", 0) >= 1:
            result = {"error": "이번 턴의 시간은 이미 반영되었다. 추가로 시간을 흘리지 말고 결과를 서술하라."}
        elif name == "accept_offer":
            result = state.accept_offer()
        elif name == "set_scene":
            changed = state.set_scene(args.get("setting"), args.get("place"), args.get("description_en"),
                                      args.get("visible_features"))
            result = {"ok": True, "장면이_바뀜": changed}
        elif name == "reject_event":
            state.event = None
            if state.offer and state.offer.get("turn") == state.turn:
                state.offer = None
                state.last_major_turn = max(0, state.turn - 4)   # 조금 뒤에 다시 기회가 오게 한다
            result = {"ok": True}
        elif name == "advance_time":
            state.turn_flags["time"] = 1
            before = state.elapsed_hours
            state.pass_time(args.get("hours", 1), args.get("activity", "other"),
                            sheltered=bool(args.get("sheltered", False)))
            result = {"ok": True, "경과시간": round(state.elapsed_hours - before, 2)}
        elif name == "update_status":
            state.apply_delta(
                health=float(args.get("health", 0)), satiety=float(args.get("satiety", 0)),
                hydration=float(args.get("hydration", 0)), energy=float(args.get("energy", 0)),
                money=float(args.get("money", 0)), reason=str(args.get("reason", "")),
            )
            if float(args.get("satiety", 0)) > 0 or float(args.get("hydration", 0)) > 0:
                state.turn_flags["intake"] = True
            used = [n for n in args.get("consumed_items") or [] if state.consume_item(n)]
            result = {"ok": True, "사라진_소지품": used}
        elif name == "update_inventory":
            rejected = state.update_items(add=args.get("add"), remove=args.get("remove"))
            result = {"ok": True}
            if rejected:
                result["거부된_물건"] = rejected
                result["안내"] = "거부된 것은 소지품에 들어가지 않았다. 가진 것처럼 서술하지 마라."
        elif name == "travel":
            result = state.travel(args.get("method"), args.get("distance_km", 1))
            if result.get("success"):
                state.turn_flags["travel"] = 1
                result["안내"] = ("이동은 도착까지 이미 끝났다. set_scene 으로 도착지의 장면(기후·지형·장소유형에 맞게)을 "
                                "정한 뒤, 도착한 곳에서의 상황으로 서술을 마무리하라.")
        elif name == "search_survival_guide":
            docs = knowledge.search(client, str(args.get("query", "")))
            return json.dumps({"documents": docs}, ensure_ascii=False)
        else:
            result = {"error": f"알 수 없는 툴: {name}"}
    except Exception as e:  # 툴 하나가 실패해도 게임이 멈추지 않게 한다
        result = {"error": f"{type(e).__name__}: {e}"}

    # 툴 실행 후의 최신 상태를 함께 돌려줘서 LLM이 정확한 수치로 서술하게 한다
    result["현재상태"] = state.summary()
    if state.status == "dead":
        result["game_over"] = f"플레이어 사망: {state.death_reason}"
    elif state.status == "won":
        result["game_over"] = "플레이어가 한국에 도착했다. 귀환 성공!"
    return json.dumps(result, ensure_ascii=False)
