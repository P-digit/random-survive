"""자유 행동 판정·범죄 의도·수배·체포 (survival/crime.py, intent.py) 테스트."""
import json
import random
from types import SimpleNamespace

import pytest

from survival import gamemaster, geo, state as state_module
from survival.intent import crime_intent
from survival.state import GameState
from tests.helpers import call, fake_weather, fix_roll


def test_hijack_truck_then_drive(game, monkeypatch):
    game.begin_turn()
    game.offer = {"id": "trucker", "text": "트럭", "accept": "", "detail": "", "turn": game.turn}
    assert call(game, "acquire_vehicle", kind="truck", name="화물 트럭")["success"] is False   # 시도 없이 못 얻는다

    fix_roll(monkeypatch, 0.0)                                       # 주사위: 성공
    out = call(game, "attempt_action", action="트럭 기사를 기절시킨다", difficulty="hard",
               crime="차량 절도", witnessed="victim", violent=True, item="다용도 칼", stealth=False)
    assert out["success"] and out["chance"] == "50%" and game.wanted == 16   # hard 35% + 칼 15%, 20×1.3×0.6
    assert "error" in call(game, "attempt_action", action="또", difficulty="easy", crime="none",
                           witnessed="none", violent=False, item="", stealth=False)    # 한 턴에 한 번
    got = call(game, "acquire_vehicle", kind="truck", name="화물 트럭")
    assert got["success"] and game.vehicle["stolen"] and game.offer is None
    titles = [n["title"] for n in gamemaster.collect_notices(game)]
    assert any(t.startswith("🎲") and "성공" in t for t in titles) and any(t.startswith("🚙") for t in titles)

    game.begin_turn()                                                # 야생에서도 운전해서 갈 수 있다
    fuel, before = game.vehicle["range_km"], game.distance
    out = call(game, "travel", method="drive", distance_km=200)
    assert out["success"] and before - game.distance == pytest.approx(200, abs=3)
    assert game.vehicle["range_km"] == fuel - 200 and game.money == 50


def test_failed_attack_hurts_and_raises_wanted(game, monkeypatch):
    game.begin_turn()
    fix_roll(monkeypatch, 0.99)                                      # 주사위: 실패
    out = call(game, "attempt_action", action="기사를 제압한다", difficulty="very_hard",
               crime="폭행", witnessed="bystanders", violent=True, item="", stealth=False)
    assert out["success"] is False and game.health == 70 and game.wanted == 35
    assert call(game, "acquire_vehicle", kind="truck", name="")["success"] is False


def test_chance_modifiers():
    weak = GameState(lat=0, lon=0, place_name="x", weather=fake_weather(), biome="forest",
                     health=30, energy=10, start_hour=23)
    weak.begin_turn = lambda: None
    weak.turn_flags = {}
    random.seed(0)
    out = weak.attempt("창고에 몰래 들어간다", "normal", crime="주거·건물 침입", witnessed="none",
                       violent=False, item="", stealth=True)
    assert out["chance"] == "40%"                                     # 60 - 15 - 15 + 10(밤)


def test_wanted_consequences(game, monkeypatch):
    game.begin_turn()
    game.place_type, game.money, game.wanted = "도시", 3000, 80
    game.vehicle = {"kind": "car", "name": "훔친 차", "speed": 70, "range_km": 300, "sea": False, "stolen": True}
    assert call(game, "buy_ticket", method="flight", distance_km=1)["success"]
    game.flags["at_airport"] = True
    fix_roll(monkeypatch, 0.1)                                       # 0.1 < 0.8 → 공항에서 붙잡힘
    hours = game.elapsed_hours
    out = call(game, "travel", method="flight", distance_km=1)
    assert out["arrested"] and game.status == "playing"
    assert game.vehicle is None and game.tickets == [] and not any("항공권" in i for i in game.items)
    assert game.elapsed_hours - hours == 24 and game.wanted < 40 and game.money < 2000

    game.wanted = 60                                                 # 수배 중이면 도시에서 경찰 이벤트
    game.offer, game.last_major_turn = None, game.turn + 100
    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    assert game.event and "경찰" in game.event["text"]

    game.wanted = 30
    game.pass_time(5, "rest")
    assert game.wanted == pytest.approx(28.5)                        # 시간이 지나면 내려간다
    game.wanted = 0
    assert call(game, "arrest", reason="검문")["success"] is False    # 수배가 없으면 체포도 없다


def test_wanted_only_for_witnessed_crimes(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)                                       # 성공
    game.begin_turn()
    game.attempt("늑대를 칼로 쫓아낸다", "hard", crime="none", witnessed="bystanders", violent=True)
    assert game.wanted == 0                                          # 범죄가 아니면 수배 없음
    game.begin_turn()
    out = game.attempt("잠든 사이 지갑을 훔친다", "normal", crime="절도", witnessed="none")
    assert game.wanted == 0 and "목격자 없음" in out["엔진이_적용한_결과"][0]
    game.begin_turn()
    game.attempt("시장에서 빵을 훔친다", "normal", crime="절도", witnessed="bystanders")
    assert game.wanted == 16                                         # 20 × 0.8 × 1.0
    game.begin_turn()
    game.attempt("버스 무임승차", "easy", crime="무임승차", witnessed="victim")
    assert game.wanted == 16 + 5                                     # 20 × 0.4 × 0.6 = 4.8 → 5
    fix_roll(monkeypatch, 0.99)                                      # 실패하면 아무도 없었어도 들킨다
    game.begin_turn()
    game.attempt("창고 자물쇠를 딴다", "hard", crime="주거·건물 침입", witnessed="none")
    assert game.wanted == 21 + 13                                    # 35 × 0.6 × 0.6 = 12.6 → 13


def test_theft_reward_is_applied_by_engine(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)                                       # 성공
    game.begin_turn()
    out = call(game, "attempt_action", action="옆 사람의 지갑을 훔친다", difficulty="normal", crime="절도",
               witnessed="none", violent=False, item="", stealth=True, success_money=320,
               success_items=["가죽 지갑", "픽업트럭"])
    assert out["success"] and game.money == 50 + 320 and "가죽 지갑" in game.items
    assert not any("트럭" in i for i in game.items) and out["거부된_물건"]       # 탈것은 소지품이 아니다
    assert any("+$320" in n["text"] for n in gamemaster.collect_notices(game))
    game.end_turn(0.5)
    assert game.delta["money"] == 320                                # 상태창에도 +320

    fix_roll(monkeypatch, 0.99)                                      # 실패하면 아무것도 얻지 못한다
    game.begin_turn()
    game.attempt("금고를 턴다", "hard", crime="절도", witnessed="none", success_money=500)
    assert game.money == 370


def test_crime_intent_classification():
    assert crime_intent("트럭을 타려고 시도한다")[0] == "none"
    assert crime_intent("트럭을 타려고 시도한다", ["트럭을 훔칠까?", "물을 찾는다"])[0] == "context"
    assert crime_intent("트럭을 타려고 시도한다", ["지갑을 훔친다"])[0] == "none"          # 다른 대상
    assert crime_intent("트럭에 올라탄다", [], ["트럭을 훔칠 방법을 생각한다"])[0] == "context"
    for text in ["차량을 빼앗는다", "트럭 기사를 기절시킨다", "몰래 짐칸에 숨어 탄다", "무임승차를 한다",
                 "기사를 속여서 태워 달라고 한다", "가게 물건을 슬쩍한다"]:
        assert crime_intent(text)[0] == "explicit", text
    for text in ["구멍으로 안을 훔쳐본다", "멧돼지의 공격을 피한다", "속이 안 좋아 쉰다", "기사에게 태워 달라고 부탁한다"]:
        assert crime_intent(text)[0] == "none", text


TRUCK_OFFER = {"id": "trucker", "text": "장거리 화물 트럭이 멈춰 선다. 기사는 마을까지 간다며 태워 주겠다고 한다.",
               "accept": "트럭에 올라탄다", "hours": 0, "stats": {}, "items": [], "money": 0, "risk": "",
               "detail": "근처 마을(약 25km)까지 이동",
               "bad": {"chance": 0}, "move": {"to": "city_or_village", "max_km": 500, "speed": 60},
               "dest": {"type": "city_or_village", "name": "근처 마을", "label": "근처 마을", "lat": 47.1,
                        "lon": 104.1, "km": 25, "place": "마을"}}


def gm_tries_to_steal(monkeypatch, game, player_text):
    """GM이 '트럭 절도 → 트럭 획득'을 시도하고, 거절되면 '제안 수락'으로 바꾸는 상황을 흉내 낸다."""
    calls = []
    steal = {"action": "트럭을 빼앗는다", "difficulty": "hard", "crime": "차량 절도", "witnessed": "victim",
             "violent": True, "item": "", "stealth": False, "success_money": 0, "success_items": [],
             "victim": "트럭 기사"}

    def fake_create(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return SimpleNamespace(id="r1", output_text="", output=[
                SimpleNamespace(type="function_call", name="attempt_action", call_id="a", arguments=json.dumps(steal)),
                SimpleNamespace(type="function_call", name="acquire_vehicle", call_id="b",
                                arguments='{"kind": "truck", "name": "화물 트럭"}')])
        if len(calls) == 2 and any("error" in json.loads(o["output"]) for o in kw["input"]):
            return SimpleNamespace(id="r2", output_text="", output=[
                SimpleNamespace(type="function_call", name="accept_offer", call_id="c", arguments="{}")])
        return SimpleNamespace(id="r3", output=[], output_text="당신은 트럭에 오른다.")

    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=fake_create)))
    fix_roll(monkeypatch, 0.0)
    game.offer = dict(TRUCK_OFFER, turn=game.turn + 1)       # 이번 턴에 유효한 제안
    gamemaster.run_turn(game, player_text)
    return calls


def test_reported_case_riding_is_not_stealing(game, monkeypatch):
    """보고된 상황: '트럭을 타려고 시도한다' → 절도가 되면 안 되고, 기사의 제안을 받아들인 것이 된다."""
    game.suggestions = ["트럭 기사에게 말을 건다", "트럭을 타려고 시도한다", "물을 찾는다"]
    calls = gm_tries_to_steal(monkeypatch, game, "트럭을 타려고 시도한다")
    first = [json.loads(o["output"]) for o in calls[1]["input"]]
    assert "범죄를 의도하지 않았다" in first[0]["error"] and first[1]["success"] is False
    assert game.vehicle is None and game.wanted == 0 and not any(c.get("status") for c in game.characters)
    assert game.place_type == "마을"                                          # 대신 트럭을 얻어 타고 마을로
    assert "범죄 의도가 없다" in calls[0]["input"]


def test_crime_allowed_with_context_or_explicit_order(game, monkeypatch):
    game.suggestions = ["트럭을 훔칠까?", "기사에게 부탁한다", "물을 찾는다"]       # 앞서 범죄를 고려했다
    calls = gm_tries_to_steal(monkeypatch, game, "트럭을 타려고 시도한다")
    assert "앞서 같은 대상에 대한 범죄를 고려했다" in calls[0]["input"]
    assert game.vehicle and game.vehicle["stolen"] and game.wanted > 0

    other = GameState(lat=46.9, lon=103.8, place_name="몽골", weather=fake_weather(), biome="forest",
                      distance=geo.distance_to_korea(46.9, 103.8))
    other.suggestions = ["물을 찾는다"]
    gm_tries_to_steal(monkeypatch, other, "트럭을 빼앗는다")                      # 직접 지시
    assert other.vehicle and other.vehicle["stolen"]


def test_world_remembers_the_crime(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    game.add_character("아메드", "트럭 기사", "50대, 콧수염")
    game.offer = dict(TRUCK_OFFER, turn=game.turn)
    out = game.attempt("트럭 기사를 기절시킨다", "hard", crime="차량 절도", witnessed="victim", violent=True,
                       victim="트럭 기사")
    assert out["success"]
    game.acquire_vehicle("truck", "화물 트럭")
    driver = game.find_character("트럭 기사")
    assert driver["name"] == "아메드" and "쓰러져" in driver["status"] and "빼앗겼다" in driver["status"]
    assert game.offer is None                                                 # 태워 주겠다던 제안은 끝났다
    assert any(f["scope"] == "always" and "차량 절도" in f["text"] for f in game.facts)
    text = gamemaster.build_input(game, "트럭 기사에게 말을 건다")
    assert "아메드 (트럭 기사)" in text and "상태: 당신에게" in text and "돕지 않" in text

    game.end_turn(0.5)
    game.begin_turn()                                                         # 현장에 머물면 반응이 온다
    assert game.event and "아메드" not in game.event["text"] and "트럭 기사" in game.event["text"]

    game.begin_turn()
    game.turn_flags["player_text"] = "트럭을 몰고 떠난다"
    call(game, "travel", method="drive", distance_km=50)                     # 현장을 떠나면 끝
    assert game.crime_scene is None


def test_failed_crime_makes_victim_hostile(game, monkeypatch):
    fix_roll(monkeypatch, 0.99)
    game.begin_turn()
    game.attempt("상인의 지갑을 훔친다", "normal", crime="절도", witnessed="none", victim="시장 상인")
    merchant = game.find_character("시장 상인")
    assert "알아챘다" in merchant["status"] and "적대" in merchant["status"]

    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    game.attempt("잠든 여행자의 지갑을 훔친다", "normal", crime="절도", witnessed="none", victim="잠든 여행자")
    assert "모른다" in game.find_character("잠든 여행자")["status"]
    assert game.crime_scene["witnessed"] == "none"
    monkeypatch.setattr(state_module, "roll_event", lambda *a, **k: None)
    game.end_turn(0.5)
    game.begin_turn()
    assert game.event is None                                                  # 아무도 못 봤으면 현장 반응도 없다


def test_no_vehicle_ownership_from_a_ride_request(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    game.turn_flags["player_text"] = "트럭을 타려고 시도한다"
    game.turn_flags["crime_intent"] = crime_intent("트럭을 타려고 시도한다")
    game.attempt("기사를 설득한다", "normal")                               # 합법적인 시도는 성공해도
    out = call(game, "acquire_vehicle", kind="truck", name="화물 트럭")
    assert out["success"] is False and game.vehicle is None               # 트럭이 내 것이 되지는 않는다
    game.begin_turn()
    game.turn_flags["player_text"] = "주인에게 돈을 주고 오토바이를 산다"
    game.turn_flags["crime_intent"] = crime_intent(game.turn_flags["player_text"])
    game.attempt("오토바이 값을 흥정한다", "normal")
    assert call(game, "acquire_vehicle", kind="motorbike", name="낡은 오토바이")["success"]
    assert game.vehicle and not game.vehicle["stolen"]


def test_stolen_money_not_auto_added_without_intent(game):
    game.begin_turn()
    game.turn_flags["crime_intent"] = ("none", "")
    assert gamemaster.auto_money(game, "당신은 그의 지갑에서 $200를 훔쳤다.") == 0 and game.money == 50
    assert gamemaster.auto_money(game, "일을 도와 $30를 받았다.") == 30


def test_more_crimes_are_recognized():
    for text in ["노점에 불을 지른다", "경찰에게 뇌물을 준다", "여권을 위조한다", "남의 밭에서 감자를 캐 간다",
                 "주차된 오토바이 시동을 걸어 몰고 간다", "주인 몰래 빵을 챙긴다", "돈을 내지 않고 물을 들고 간다",
                 "밀수품을 나른다", "창고에 불을 질렀다"]:
        assert crime_intent(text)[0] == "explicit", text
    for text in ["모닥불에 불을 피운다", "마른 풀로 불을 지핀다", "배낭에서 물을 꺼내 마신다", "남의 도움을 받아 길을 찾는다",
                 "감자를 캐 간다", "내 짐을 챙겨 떠난다", "가도 되는지 물어본다", "소리를 지른다", "몰래 다가가 살펴본다",
                 "강가로 간다", "사기가 떨어진다"]:
        assert crime_intent(text)[0] == "none", text
    from survival.config import CRIMES
    assert {"방화", "뇌물", "위조", "밀수"} <= set(CRIMES)


def test_gains_need_an_honest_source(game, monkeypatch):
    game.place_type = "마을"
    game.begin_turn()
    out = call(game, "update_inventory", remove=[], add=[{"name": "빵", "carryable": True}], source="stolen", giver="")
    assert "error" in out and "빵" not in game.items                          # 판정 없이 훔친 것은 안 된다
    out = call(game, "update_inventory", remove=[], add=[{"name": "빵", "carryable": True}], source="bought", giver="")
    assert "error" in out                                                     # 값을 안 냈다
    call(game, "pay", amount=2, purpose="빵")
    assert "error" not in call(game, "update_inventory", remove=[], add=[{"name": "빵", "carryable": True}],
                               source="bought", giver="")
    out = call(game, "update_status", health=0, satiety=0, hydration=0, energy=0, money=100, money_source="stolen",
               consumed_items=[], reason="지갑")
    assert "error" in out and game.money == 48                                # 훔친 돈도 판정 없이는 안 된다

    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    game.attempt("시장 상인의 빵을 훔친다", "normal", crime="절도", witnessed="bystanders", victim="시장 상인",
                 success_items=["바게트"])
    assert "바게트" in game.items and "바게트" in game.stolen_items          # 판정에 성공한 장물
    out = call(game, "update_inventory", remove=[], add=[{"name": "사과", "carryable": True}], source="gift",
               giver="시장 상인")
    assert "원한" in out["error"]                                             # 피해자는 아무것도 주지 않는다


def test_crime_aftermath_carries_forward(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)
    game.place_type, game.place_name = "마을", "몽골, 어느 마을"
    game.begin_turn()
    game.add_character("아메드", "트럭 기사", "50대")
    game.attempt("트럭 기사를 기절시킨다", "hard", crime="차량 절도", witnessed="bystanders", violent=True,
                 victim="트럭 기사")
    game.acquire_vehicle("truck", "화물 트럭")
    assert game.notorious and game.enemies[0]["name"] == "아메드"
    notes = game.crime_aftermath()
    assert any("수배도" in n for n in notes) and any("현장" in n for n in notes) and any("훔친 것" in n for n in notes)
    assert any("범죄자로 알려져" in n for n in notes)

    game.end_turn(0.5)
    game.begin_turn()                                                         # 다음 턴: 반드시 반응
    assert game.event and "트럭 기사" in game.event["text"]
    game.set_scene("indoor", "트럭 운전석", "Inside the truck cab.", ["운전대"])   # 장면이 바뀌어도
    text = gamemaster.build_input(game, "숨을 고른다")
    assert "[당신에게 원한이 있는 사람" in text and "아메드" in text and "[범죄의 여파" in text

    game.pass_time(3, "rest")                                                 # 기절한 기사는 두어 시간 뒤 깨어난다
    game.end_turn(0)
    game.begin_turn()
    assert "정신을 차리고" in game.event["text"]

    game.begin_turn()
    game.turn_flags["player_text"] = "트럭을 몰고 떠난다"
    call(game, "travel", method="drive", distance_km=100)                    # 멀리 떠나면 현장·원한은 멀어진다
    assert game.crime_scene is None and not game.enemies_nearby() and not game.notorious_here()
    assert any("훔친 것" in n for n in game.crime_aftermath())               # 훔친 트럭은 여전히 여파로 남는다


def test_notorious_town_reacts_and_does_not_help(game, monkeypatch):
    game.place_type = "마을"
    game.notorious = [{"place": "몽골", "lat": game.lat, "lon": game.lon, "crime": "강도", "turn": 1}]
    fix_roll(monkeypatch, 0.0)
    monkeypatch.setattr(state_module, "roll_major_event",
                        lambda *a, **k: {"id": "korean", "text": "한국인이 초대한다", "accept": "초대를 받아들인다",
                                         "move": {}, "stats": {}, "items": [], "money": 50, "hours": 1, "risk": "",
                                         "bad": {"chance": 0}})
    game.turn, game.last_major_turn = 20, 0
    game.begin_turn()
    assert game.offer is None and "알아보고" in game.event["text"]


def test_arrest_confiscates_stolen_goods(game):
    game.wanted = 40
    game.items.append("훔친 시계")
    game.stolen_items = ["훔친 시계"]
    game.begin_turn()
    game.arrest("검문")
    assert "훔친 시계" not in game.items and game.stolen_items == []
