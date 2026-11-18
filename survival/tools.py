"""게임 마스터(LLM)가 호출할 수 있는 툴 목록과 실제 실행 함수."""
import json

from . import knowledge
from .config import CRIMES, TRAVEL_RULES


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
        "예: 물을 마심 hydration +30, 넘어져 다침 health -10, 일해서 돈을 범 money +40. "
        "돈을 '쓰는' 것은 이 툴이 아니라 pay 로 처리한다.",
        {
            "health": {"type": "number", "description": "체력 변화량 (-40~+30)"},
            "satiety": {"type": "number", "description": "포만감 변화량 (-40~+60)"},
            "hydration": {"type": "number", "description": "수분 변화량 (-40~+60)"},
            "energy": {"type": "number", "description": "기력 변화량 (-40~+40)"},
            "money": {"type": "number", "description": "번 돈(USD, 0 이상). 한 번에 최대 +120. 쓴 돈은 pay 로"},
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
        "'예약한_교통편'에 해당 교통편의 표가 있으면 요금 없이 그 표로 탑승하고 표는 사라진다. "
        "수단별 조건: walk(어디서나, 최대 30km), hitchhike(어디서나, 최대 250km, 실패할 수 있음), "
        "bus(마을/도시, 최대 600km), train(도시, 최대 1500km), ship(도시, 최대 3000km), "
        "drive(보유한 탈것이 있을 때 어디서나, 요금 없음, 남은 연료만큼), "
        "flight(도시, 항상 한국까지 직항이며 distance_km 은 무시됨, 가장 비쌈). "
        "이동은 호출 즉시 도착까지 끝난다. 이동 중인 장면에서 멈추지 말고 도착한 곳의 상황으로 서술을 끝낸다.",
        {
            "method": {"type": "string", "enum": list(TRAVEL_RULES.keys()) + ["drive"],
                       "description": "이동 수단. drive 는 플레이어가 손에 넣은 탈것('보유_탈것')을 직접 모는 것"},
            "distance_km": {"type": "number", "description": "이동할 거리(km)"},
        },
    ),
    _function(
        "attempt_action",
        "결과가 불확실한 행동을 판정한다. 싸움, 제압, 절도, 차량 탈취, 무단 침입, 협박, 사기, 몰래 숨어 타기, "
        "위험한 등반·도하, 설득하기 어려운 흥정 등 성공이 보장되지 않는 행동은 반드시 이 툴로 판정한다. "
        "성공 확률은 엔진이 계산하고 주사위도 엔진이 굴린다. GM은 결과를 미리 정하지 말고 돌려받은 success 대로 서술한다. "
        "한 턴에 한 번만 호출한다.",
        {
            "action": {"type": "string", "description": "시도하는 행동을 짧게. 예: '트럭 기사를 기절시킨다'"},
            "difficulty": {"type": "string", "enum": ["easy", "normal", "hard", "very_hard"],
                           "description": "상황에 따른 난이도. 상대가 경계 중이거나, 무장했거나, 여럿이거나, 플레이어가 "
                                          "맨손이면 어렵게 매긴다. 예: 방심한 사람의 물건 슬쩍하기 normal, "
                                          "깨어 있는 트럭 기사를 맨손으로 제압 hard, 무장 경비원 제압 very_hard"},
            "crime": {"type": "string", "enum": list(CRIMES.keys()),
                      "description": "현실에서 범죄로 처벌받는 행동일 때만 그 종류를 고른다. 범죄가 아니면 none. "
                                     "동물과 싸우기, 정당방위, 야생에서 채집·사냥, 버려진 빈집에서 비 피하기, "
                                     "흥정, 히치하이킹, 위험한 등반은 범죄가 아니다."},
            "witnessed": {"type": "string", "enum": ["none", "victim", "bystanders"],
                          "description": "범죄를 누가 보았나. none: 아무도 못 봄(잠든 사이, 아무도 없는 곳, 들키지 않음), "
                                         "victim: 피해자만 봄(얼굴을 보았거나 알아챔), bystanders: 주변 사람·CCTV·경비가 봄. "
                                         "범죄가 아니면 none."},
            "violent": {"type": "boolean", "description": "몸싸움·폭력이 따르는 행동이면 true (실패하면 다친다)"},
            "item": {"type": "string", "description": "이 시도에 쓰는 소지품 이름(다용도 칼 등). 없으면 빈 문자열"},
            "stealth": {"type": "boolean", "description": "몰래 하는 행동이면 true (밤이면 유리하다)"},
        },
    ),
    _function(
        "add_lead",
        "서술 속에서 '저쪽에 무언가 있다'는 새 단서를 만들었을 때 호출한다(멀리 들리는 소리, 연기, 불빛, 바퀴 자국, "
        "길 표시, 가축 떼, 강물 등). 엔진이 그 정체와 방향·거리를 정해 [단서] 목록에 올린다. 이미 목록에 있는 단서는 "
        "다시 만들지 않는다. 정체는 플레이어가 따라가서 확인하기 전까지 서술에서 밝히지 않는다.",
        {
            "kind": {"type": "string", "enum": ["engine", "smoke", "light", "settlement", "tracks", "power", "river",
                                                 "trail", "herd", "chainsaw", "caravan", "signal", "water"],
                     "description": "engine 엔진 소리, smoke 연기, light 밤의 불빛, settlement 멀리 보이는 마을, "
                                    "tracks 바퀴·발자국, power 송전탑·전선, river 강·하천, trail 사람이 낸 길·표시·지도, "
                                    "herd 가축 떼·방울 소리, chainsaw 벌목 소리, caravan 대상 행렬, "
                                    "signal 휴대폰 신호, water 물이 있다는 표시"},
            "clue": {"type": "string", "description": "플레이어가 보고 들은 것 그대로 짧게. 예: '북쪽 언덕 너머 개 짖는 소리'"},
        },
    ),
    _function(
        "follow_lead",
        "플레이어가 [단서] 목록에 있는 단서 쪽으로 가려 할 때 호출한다(소리 나는 쪽으로 간다, 연기를 향해 걷는다 등). "
        "미리 정해 둔 정체가 그 방향·거리에 반드시 있고, 엔진이 걸린 시간·장소·장면을 처리한다. "
        "이때는 advance_time, travel, set_scene 을 따로 호출하지 않는다.",
        {"lead_id": {"type": "string", "description": "[단서] 목록의 id. 예: 'L3'"}},
    ),
    _function(
        "remember",
        "이후 이야기가 어긋나지 않도록 확정된 사실을 기록한다. 약속(\"내일 아침 6시에 트럭이 떠난다\"), "
        "인물(\"여관 주인 아흐메드는 영어를 조금 한다\"), 장소(\"마을 동쪽 끝에 버스 정류장이 있다\"), "
        "상태(\"오두막 문은 부서져 있다\")처럼 나중에 다시 나올 수 있는 것만 적는다.",
        {
            "fact": {"type": "string", "description": "한 문장으로 된 사실"},
            "scope": {"type": "string", "enum": ["here", "always"],
                      "description": "here: 이 장소에서만 의미 있음(멀리 이동하면 잊음), always: 게임 내내 유효"},
        },
    ),
    _function(
        "go_to",
        "플레이어가 목적지를 정해 가려 할 때 호출한다. 엔진이 지금 있는 곳과 가진 수단(걷기, 탈것, 버스, 기차, 돈)으로 "
        "현실적으로 갈 수 있는 만큼만 이동시킨다. 곧장 갈 수 없는 곳이면 먼저 갈 수 있는 곳부터 간다"
        "(야생에서 공관을 찾으면 먼저 가장 가까운 마을로, 마을에서 공항을 찾으면 먼저 도시로). "
        "한 턴에 다 못 가면 중간 지점에서 멈추고, 다음 턴에 플레이어가 계속 가겠다고 하면 target='continue'. "
        "이때는 advance_time, travel 을 따로 호출하지 않는다.",
        {"target": {"type": "string", "enum": ["village", "city", "embassy", "airport", "continue"],
                    "description": "village 가장 가까운 마을, city 가장 가까운 도시, embassy 한국 공관, "
                                   "airport 국제공항, continue 진행 중인 여정을 이어 감"}},
    ),
    _function(
        "seek_help",
        "공관 안에서 플레이어가 한국으로 돌아가고 싶다고 할 때 호출한다. 가족 송금(신속해외송금)으로 한국행 "
        "항공권이 마련된다. (공관·공항으로 가는 것은 go_to 를 쓴다)",
        {"kind": {"type": "string", "enum": ["repatriation"], "description": "repatriation 귀국 항공권 지원"}},
    ),
    _function(
        "add_character",
        "이 장소에서 이름이나 역할이 있는 인물을 처음 등장시킬 때 호출한다(영사, 여관 주인, 트럭 기사 등). "
        "이미 [등장인물]에 있는 사람은 다시 만들지 말고 같은 이름·역할·생김새로 계속 등장시킨다.",
        {
            "name": {"type": "string", "description": "이름 또는 부르는 말. 예: '김민수 영사', '여관 주인 아흐메드'"},
            "role": {"type": "string", "description": "역할. 예: '영사과 담당 영사'"},
            "look": {"type": "string", "description": "겉모습 한 줄. 예: '40대, 회색 양복, 안경'"},
        },
    ),
    _function(
        "pay",
        "플레이어가 돈을 쓸 때 반드시 호출한다: 물건·음식·물 사기, 숙박비, 뇌물, 택시·나룻배 삯, 수수료, 벌금 등. "
        "(교통편 표는 buy_ticket, 정해진 노선 이동 요금은 travel 이 알아서 받는다.) 돈이 모자라면 실패하며, "
        "그때는 사지 못했다고 서술한다. 서술에 값을 적었다면 같은 금액으로 호출한다.",
        {
            "amount": {"type": "number", "description": "낼 금액(USD). 그 지역 물가에 맞게"},
            "purpose": {"type": "string", "description": "무엇에 쓰는지. 예: '생수 2병'"},
        },
    ),
    _function(
        "acquire_vehicle",
        "플레이어가 탈것(차·트럭·오토바이·보트)을 손에 넣었을 때 호출한다. 같은 턴에 attempt_action 이 성공했어야 한다 "
        "(탈취, 훔치기, 흥정해서 사기 등). 이후 플레이어는 travel(method='drive') 로 직접 몰고 이동할 수 있다. "
        "장면에 실제로 있던 탈것만 얻을 수 있다.",
        {
            "kind": {"type": "string", "enum": ["car", "truck", "motorbike", "boat"], "description": "탈것 종류"},
            "name": {"type": "string", "description": "짧은 한국어 이름. 예: '낡은 화물 트럭'"},
        },
    ),
    _function(
        "arrest",
        "수배 중인 플레이어가 경찰·군인·경비에게 붙잡혔을 때 호출한다(검문에서 걸림, 도주 실패 등). "
        "엔진이 구금 하루, 벌금, 탈것·표 압수를 적용한다. 수배도가 0이면 쓸 수 없다.",
        {"reason": {"type": "string", "description": "붙잡힌 상황. 예: '마을 검문소'"}},
    ),
    _function(
        "buy_ticket",
        "플레이어가 버스·기차·배·비행기의 표를 사거나 예약할 때 호출한다. 요금 계산과 결제, 표 지급은 게임 엔진이 "
        "한다(update_status 로 돈을 빼거나 update_inventory 로 표를 넣지 않는다). 표는 '예약한_교통편'에 기록되어 "
        "탈 때까지 유지된다. 이 툴은 표만 사는 것이며 이동하지 않는다. 플레이어가 표를 사면서 바로 타겠다고 하면 "
        "buy_ticket 없이 travel 만 호출해도 된다.",
        {
            "method": {"type": "string", "enum": ["bus", "train", "ship", "flight"], "description": "교통편"},
            "distance_km": {"type": "number", "description": "이동할 거리(km). flight 는 항상 한국까지이므로 무시된다"},
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
                               "description": "그 장소에서 눈에 보이는 풍경을 영어로만 2~3문장 묘사(그림 생성용, 한글 금지). "
                                              "표지판·간판이 있다면 그 나라 언어로 쓰여 있다고 적는다. "
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
        elif name in ("advance_time", "travel", "follow_lead", "go_to") and state.turn_flags.get("travel", 0) >= 1:
            result = {"error": "이번 턴에는 이미 이동했다. 한 턴에는 플레이어가 지시한 행동 하나만 처리한다. "
                               "지금까지의 결과만 서술하고 플레이어의 다음 지시를 기다려라."}
        elif name == "advance_time" and state.turn_flags.get("time", 0) >= 1:
            result = {"error": "이번 턴의 시간은 이미 반영되었다. 추가로 시간을 흘리지 말고 결과를 서술하라."}
        elif name == "attempt_action":
            result = state.attempt(args.get("action", ""), args.get("difficulty", "normal"),
                                   str(args.get("crime", "none")), str(args.get("witnessed", "none")),
                                   bool(args.get("violent")), str(args.get("item", "")),
                                   bool(args.get("stealth")))
        elif name == "add_lead":
            lead = state.add_lead(args.get("kind"), str(args.get("clue", "")))
            result = ({"ok": True, "단서": f"{lead['id']} {lead['label']} — {lead['direction']}, 약 {lead['km']}km "
                                            "(정체는 따라가기 전까지 밝히지 않는다)"} if lead else {"error": "알 수 없는 단서 종류"})
        elif name == "follow_lead":
            result = state.follow_lead(args.get("lead_id", ""))
        elif name == "remember":
            state.remember(str(args.get("fact", "")), str(args.get("scope", "here")))
            result = {"ok": True}
        elif name == "go_to":
            result = state.go_to(str(args.get("target", "")))
        elif name == "seek_help":
            result = state.seek_help(str(args.get("kind", "")))
        elif name == "add_character":
            person = state.add_character(args.get("name", ""), args.get("role", ""), args.get("look", ""))
            result = {"ok": True, "인물": person} if person else {"error": "이름이 필요하다"}
        elif name == "pay":
            result = state.pay(args.get("amount", 0), str(args.get("purpose", "")))
        elif name == "acquire_vehicle":
            result = state.acquire_vehicle(args.get("kind"), args.get("name", ""))
        elif name == "arrest":
            result = state.arrest(str(args.get("reason", "")))
        elif name == "buy_ticket":
            result = state.buy_ticket(args.get("method"), args.get("distance_km", 1))
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
