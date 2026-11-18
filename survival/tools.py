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
        "예: 물 1L를 마심 hydration +45, 넘어져 다침 health -10, 일해서 돈을 범 money +40. "
        "소지품을 먹거나 마셨다면 consumed_items 에 반드시 적는다(엔진이 기본 회복량을 보장한다: 물 1L +45, "
        "생수 한 병 +35, 빗물·샘물 +25, 비상식량 +40, 에너지바 +25 등). "
        "돈을 '쓰는' 것은 이 툴이 아니라 pay 로 처리한다.",
        {
            "health": {"type": "number", "description": "체력 변화량 (-40~+30)"},
            "satiety": {"type": "number", "description": "포만감 변화량 (-40~+60)"},
            "hydration": {"type": "number", "description": "수분 변화량 (-40~+60)"},
            "energy": {"type": "number", "description": "기력 변화량 (-40~+40)"},
            "money": {"type": "number",
                      "description": "돈의 변화(USD). +는 번 돈·받은 돈·주운 돈(한 번에 최대 +600), "
                                     "-는 잃은 돈(도둑맞음·빼앗김·벌금). 물건값으로 쓴 돈은 pay 로"},
            "money_source": {"type": "string", "enum": ["work", "gift", "found", "sold", "stolen", "lost", "none"],
                             "description": "money 가 0이 아닐 때 그 돈의 출처. work 일한 대가, gift 받음, found 주움, "
                                            "sold 물건을 팖, stolen 훔침(같은 턴에 범죄 판정 성공 필요), "
                                            "lost 잃음·빼앗김·벌금(-), none 변화 없음"},
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
        "장소와 지형, 동물, 사람은 소지품이 아니므로 넣지 않는다(발견한 사실만 서술한다). "
        "차·트럭·오토바이·보트 같은 탈것은 소지품이 아니라 acquire_vehicle 로 얻는다.",
        {
            "add": {"type": "array", "description": "새로 얻은 물건들. 없으면 빈 배열",
                    "items": {"type": "object", "additionalProperties": False,
                              "required": ["name", "carryable"],
                              "properties": {
                                  "name": {"type": "string", "description": "물건 이름. 수량이 있으면 '생수 2병'처럼 적는다"},
                                  "carryable": {"type": "boolean",
                                                "description": "혼자 들고 이동할 수 있는 물건이면 true, 아니면 false"}}}},
            "remove": {"type": "array", "items": {"type": "string"}, "description": "없어진 물건 이름들. 없으면 빈 배열"},
            "source": {"type": "string", "enum": ["found", "bought", "gift", "reward", "stolen", "none"],
                       "description": "add 한 물건을 어떻게 얻었나. found 주움·채집, bought 삼(같은 턴에 pay 필요), "
                                      "gift 누군가 줌, reward 일의 대가, stolen 훔침(같은 턴에 범죄 판정 성공 필요), "
                                      "none 얻은 것이 없음"},
            "giver": {"type": "string", "description": "gift·reward 일 때 준 사람(이름이나 역할). 아니면 빈 문자열"},
        },
    ),
    _function(
        "travel",
        "이 지역을 떠나 한국 방향으로 장거리 이동한다(수 km~수천 km). 플레이어가 이번 턴에 그런 이동을 지시했을 "
        "때만, 한 턴에 한 번만 호출한다. 주변에서 쉴 곳·물·먹을 것을 찾으며 자리를 옮기는 것은 travel 이 아니다"
        "(advance_time + set_scene). 도착한 곳의 장소유형(야생/마을/도시)은 엔진이 정해 돌려준다. "
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
            "success_money": {"type": "number",
                              "description": "성공하면 얻는 돈(USD). 지갑·금고를 훔치거나 협박해 받는 돈 등. 그 지역 형편에 "
                                             "맞는 구체적인 금액(최대 600). 돈과 무관하면 0. 성공하면 엔진이 바로 넣는다"},
            "victim": {"type": "string",
                       "description": "범죄의 피해자(이름이나 역할, 예: '트럭 기사'). 피해자가 없거나 범죄가 아니면 빈 문자열"},
            "success_items": {"type": "array", "items": {"type": "string"},
                              "description": "성공하면 얻는 들고 다닐 수 있는 물건들. 없으면 빈 배열. 탈것은 넣지 말고 "
                                             "acquire_vehicle 로"},
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
                                              "장소유형이 야생이면 마을·집·도로를 묘사하지 않는다(멀리 보이는 것이 단서라면 "
                                              "'far in the distance'로만). "
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
        "decline_offer",
        "플레이어가 [기회]의 제안을 거절하거나 무시하겠다고 분명히 말했을 때 호출한다(예: '상자는 열지 않는다', "
        "'트럭은 안 탄다'). 거절한 기회는 다시 받아들일 수 없다.",
        {"reason": {"type": "string", "description": "플레이어가 거절한 말을 한 문장으로"}},
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


# 플레이어 입력에 이런 말이 있어야 그 목적지로 이동한다 (GM이 '쉴 곳 찾기'를 마을 이동으로 바꾸지 못하게)
GO_WORDS = {
    "village": ("마을", "인가", "동네", "부락", "농가", "민가", "정착지", "사람 사는", "사람이 사는", "시골"),
    "city": ("도시", "시내", "시가지", "읍내"),
    "embassy": ("대사관", "영사관", "공관", "영사"),
    "airport": ("공항", "비행기", "항공"),
    "continue": ("계속 간다", "계속 가", "계속 걷", "이어서 간다", "이어 간다", "이어간다", "가던 길", "마저 간다",
                 "다시 출발", "출발한다", "출발하자"),
}
# 탈것을 '갖겠다'는 말 (태워 달라는 것과 구별). 범죄로 빼앗는 경우는 범죄 의도로 따로 판정한다
OWN_WORDS = ("산다", "사겠", "사자", "살게", "구입", "구매", "빌린", "빌려", "빌리", "렌트", "임대", "대여", "넘겨받",
             "물려받", "가져간", "가져가", "차지")
# 단서가 하나뿐일 때 '그쪽으로 간다'처럼 가리키는 말
POINTING_WORDS = ("그쪽", "저쪽", "그곳", "저곳", "거기", "저기", "소리나는", "소리가나는", "연기나는", "불빛이보이는")
COMPASS = ("북쪽", "북동쪽", "동쪽", "남동쪽", "남쪽", "남서쪽", "서쪽", "북서쪽")
STOPWORDS = ("멀리서", "멀리", "누군가", "가까이", "근처", "주변", "하나", "여러", "몇", "아주", "조금", "잠깐", "아직",
             "일정한", "선명하게", "한", "그", "이", "저")


def clue_words(lead):
    """단서를 가리키는 낱말: 이름과 내용의 명사 쪽 낱말(두 글자 이상, 동사·흔한 말 제외)과 방위."""
    words = []
    for raw in (lead["label"] + " " + lead["clue"]).split():
        w = raw.strip(".,!?\"'()“”")
        for josa in ("에서", "으로", "에게", "이", "가", "을", "를", "은", "는", "의", "에", "로", "와", "과", "도"):
            if w.endswith(josa) and len(w) - len(josa) >= 2:
                w = w[: -len(josa)]
                break
        if len(w) >= 2 and not w.endswith("다") and w not in STOPWORDS:
            words.append(w)
    return words + [lead["direction"]]


# 장거리 이동(travel): 이 지역을 떠나는 말. '이동', '돌아다닌다'처럼 그 자리 근처에서 움직이는 말은 넣지 않는다
TRAVEL_WORDS = {
    "walk": ("한국", "km", "킬로", "떠난다", "떠나자", "떠나겠", "출발한다", "출발하자", "출발하겠", "길을 따라", "도로를 따라", "강을 따라",
             "하루 종일 걷", "종일 걷", "북쪽으로", "북동쪽으로", "동쪽으로", "남동쪽으로", "남쪽으로", "남서쪽으로",
             "서쪽으로", "북서쪽으로"),
    "hitchhike": ("히치", "태워", "얻어 타", "얻어 탄", "얻어 탈", "얻어 탔", "차를 세", "엄지"),
    "bus": ("버스",), "train": ("기차", "열차"), "ship": ("배를", "배로", "배에", "여객선", "선박", "항구"),
    "flight": ("비행기", "항공", "탑승", "공항"),
    "drive": ("운전", "몰고", "몬다", "몰아", "타고 간다", "타고 달", "차로", "트럭으로", "오토바이로", "보트로"),
}
# 기회의 낱말과 함께 쓰여야 수락이 되는 행동 (마지막 글자는 받침이 붙어도 같은 말: '탄다', '탈게', '오른다')
from .intent import _pattern  # noqa: E402

ACCEPT_ACTIONS = _pattern(("타려", "타겠", "타자", "타고", "탄다", "탈게", "탔다", "탔어", "올라", "오르", "오른", "따라가", "따라간",
                           "가겠", "갈게", "가자", "간다", "연다", "열어", "열겠", "응하", "응한", "받는다", "받겠",
                           "들어가", "들어간", "부탁", "맡기"))
# 기회를 받아들인다는 분명한 표현. ('간다', '올라', '네'처럼 다른 말에도 흔히 들어가는 말은 넣지 않는다)
ACCEPT_WORDS = ("받아들", "수락", "승낙", "응한다", "응하겠", "응할게", "제안을받", "제안대로", "그러겠", "그러자고",
                "태워달", "태워주", "데려다달", "데려다주")


def gain_problem(state, source, giver=""):
    """판정 없이 범죄로 얻거나, 값을 내지 않고 산 것처럼 처리하는 것을 막는다. 문제가 없으면 None."""
    attempt = state.turn_flags.get("attempt") or {}
    if source == "stolen" and not (attempt.get("success") and attempt.get("illegal")):
        return ("훔친 것은 같은 턴에 attempt_action(crime 지정)으로 판정해 성공했을 때만 얻는다. 판정 없이 "
                "훔친 것으로 처리하지 마라.")
    if source == "bought" and not state.turn_flags.get("paid"):
        return "산 물건은 같은 턴에 pay 로 값을 먼저 내야 얻는다."
    if source in ("gift", "reward") and giver:
        person = state.find_character(giver)
        enemy = next((e for e in state.enemies_nearby() if e["name"] == (person or {}).get("name", giver)), None)
        if enemy:
            return f"{enemy['name']}은(는) 당신에게 원한이 있다({enemy['status'][:40]}…). 아무것도 주지 않는다."
    return None


def redone_offer(state):
    """플레이어가 이미 끝난 기회(예: 이미 연 보급 상자)를 다시 하려는가. 그렇다면 그 기록."""
    text = (state.turn_flags.get("player_text") or "").replace(" ", "")
    if not text:
        return None
    for done in reversed(state.closed_offers_here()):
        words = [w for w in clue_words({"label": done["accept"], "clue": "", "direction": ""}) if w]
        if any(w in text for w in words):
            return done
    return None


def redo_problem(state, name, args):
    """끝난 기회를 다시 하며 물건·회복·돈을 다시 얻으려 하면 막는다. 문제가 없으면 None."""
    done = redone_offer(state)
    if not done:
        return None
    if name == "update_inventory":
        gaining = bool(args.get("add")) and str(args.get("source", "found")) != "bought"
    else:
        gaining = float(args.get("money", 0) or 0) > 0 or (
            not args.get("consumed_items")
            and any(float(args.get(k, 0) or 0) > 0 for k in ("satiety", "hydration", "energy", "health")))
    if not gaining:
        return None
    return (f"{done['note']} 같은 기회('{done['accept']}')는 다시 할 수 없으니 물건·회복·돈을 다시 주지 마라. "
            "이미 끝났다는 것을 서술하라.")


def player_asked_for(state, name, args):
    """GM이 이동 툴을 쓸 때, 플레이어가 정말 그곳으로 가겠다고 했는지. (플레이어 입력이 없으면 허용)"""
    text = (state.turn_flags.get("player_text") or "").replace(" ", "")
    if not text:
        return True
    if name == "go_to":
        words = GO_WORDS.get(str(args.get("target", "")), ())
        return any(w.replace(" ", "") in text for w in words)
    if name == "travel":
        words = TRAVEL_WORDS.get(str(args.get("method", "")), ())
        return any(w.replace(" ", "") in text for w in words)
    if name == "accept_offer":
        if not state.offer:
            return True                  # 받아들일 제안이 없으면 accept_offer 가 '이미 지나갔다'고 알려 준다
        offer = state.offer
        # 분명한 수락 표현이 있거나, 그 기회의 낱말(트럭, 헬기, 초대…)과 '타다·오르다·따라가다' 같은 수락 행동이
        # 함께 있어야 한다. '트럭 기사에게 말을 건다'처럼 언급만 한 것은 수락이 아니다.
        if any(w in text for w in ACCEPT_WORDS):
            return True
        own = clue_words({"label": str(offer.get("accept", "")), "clue": "", "direction": ""})
        return any(w.replace(" ", "") in text for w in own if w) and bool(ACCEPT_ACTIONS.search(text))
    if name == "follow_lead":
        lead = state.find_lead(args.get("lead_id", ""))
        if lead is None:
            return True                  # 없는 단서는 엔진이 알아서 거절한다
        # 그 단서를 직접 가리키는 말이 있어야 한다: 단서의 낱말('엔진', '소리', '연기')이나 방위('동쪽').
        # '바위 쪽으로'처럼 아무 데나 붙는 말이나, '이동'의 '동' 같은 한 글자는 쓰지 않는다.
        if any(w.replace(" ", "") in text for w in clue_words(lead)):
            return True
        return len(state.leads) == 1 and any(w in text for w in POINTING_WORDS)
    return True


def execute_tool(state, name, arguments, client=None):
    """툴 이름과 JSON 인자를 받아 게임 상태에 반영하고, LLM에게 돌려줄 결과 문자열을 만든다."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except json.JSONDecodeError:
        return json.dumps({"error": "인자를 해석할 수 없음"}, ensure_ascii=False)

    try:
        if state.status != "playing" and name != "search_survival_guide":
            result = {"error": "게임이 이미 끝났다."}
        elif name == "attempt_action" and str(args.get("crime", "none")) != "none" \
                and state.turn_flags.get("crime_intent", ("explicit", ""))[0] == "none":
            result = {"error": "플레이어는 범죄를 의도하지 않았다. 이 행동을 범죄로 처리하지 마라. 합법적인 방법으로 "
                               "해석하라: 태워 달라고 부탁하기, 요금·품삯 흥정, 물건값 지불, 일을 돕고 대가 받기 등. "
                               "결과가 불확실하면 crime='none' 으로 다시 판정하라."}
        elif name == "acquire_vehicle" and state.turn_flags.get("player_text") \
                and state.turn_flags.get("crime_intent", ("explicit", ""))[0] == "none" \
                and not any(w in state.turn_flags["player_text"].replace(" ", "") for w in OWN_WORDS):
            result = {"success": False,
                      "error": "플레이어는 탈것을 갖겠다고 하지 않았다(빼앗기·사기·빌리기 아님). 태워 달라는 것이면 "
                               "accept_offer(기회가 있을 때)나 travel(method='hitchhike') 로 처리하라."}
        elif name in ("go_to", "follow_lead", "travel", "accept_offer") and not player_asked_for(state, name, args):
            result = {"error": "플레이어는 그곳으로 가겠다고 하지 않았다. 이동 툴을 쓰지 말고, 지금 있는 자리와 그 근처에서 "
                               "행동을 처리하라(쉴 곳·물·먹을 것을 주변에서 찾기 → advance_time, 찾은 곳으로 옮기면 "
                               "set_scene). 현재 장면과 장소유형은 그대로다."}
        elif name in ("advance_time", "travel", "follow_lead", "go_to") and state.turn_flags.get("travel", 0) >= 1:
            result = {"error": "이번 턴에는 이미 이동했다. 한 턴에는 플레이어가 지시한 행동 하나만 처리한다. "
                               "지금까지의 결과만 서술하고 플레이어의 다음 지시를 기다려라."}
        elif name == "advance_time" and state.turn_flags.get("time", 0) >= 1:
            result = {"error": "이번 턴의 시간은 이미 반영되었다. 추가로 시간을 흘리지 말고 결과를 서술하라."}
        elif name == "attempt_action":
            result = state.attempt(args.get("action", ""), args.get("difficulty", "normal"),
                                   str(args.get("crime", "none")), str(args.get("witnessed", "none")),
                                   bool(args.get("violent")), str(args.get("item", "")),
                                   bool(args.get("stealth")), float(args.get("success_money", 0) or 0),
                                   list(args.get("success_items") or []), str(args.get("victim", "")))
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
        elif name == "decline_offer":
            result = state.decline_offer()
        elif name in ("update_inventory", "update_status") and redo_problem(state, name, args):
            result = {"error": redo_problem(state, name, args)}
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
        elif name == "update_status" and float(args.get("money", 0) or 0) > 0 \
                and gain_problem(state, str(args.get("money_source", "none"))):
            result = {"error": gain_problem(state, str(args.get("money_source", "none"))),
                      "안내": "돈 변화를 빼고 다시 호출하라."}
        elif name == "update_inventory" and args.get("add") \
                and gain_problem(state, str(args.get("source", "found")), str(args.get("giver", ""))):
            result = {"error": gain_problem(state, str(args.get("source", "found")), str(args.get("giver", "")))}
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
