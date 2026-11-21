"""소지품·먹고 마시기·돈 (survival/inventory.py) 테스트."""
import json
from types import SimpleNamespace

from survival import gamemaster
from survival.inventory import consumable_effect, liquid_ml, partial_portion, with_volume
from survival.state import GameState
from tests.helpers import call, desert_noon, fake_weather, reply_with


def test_inventory(game):
    game.update_items(add=["마른 장작"], remove=["물"])
    assert "마른 장작" in game.items
    assert not any("물 1L" == item for item in game.items)


def test_inventory_rejects_places_and_impossible_items(game):
    game.begin_turn()
    out = call(game, "update_inventory", remove=[], add=[
        {"name": "빈 오두막", "carryable": True},        # 키워드로 거부
        {"name": "텔레포트기", "carryable": True},       # 존재할 수 없는 물건
        {"name": "버려진 낙타", "carryable": False},     # LLM이 스스로 들 수 없다고 판단
        {"name": "마른 장작", "carryable": True}])
    assert len(out["거부된_물건"]) == 3
    assert "마른 장작" in game.items
    assert not any(w in " ".join(game.items) for w in ("오두막", "텔레포트", "낙타"))


def test_consumables_disappear_when_used(game):
    game.begin_turn()
    game.update_items(add=["빗물(1회분)"])
    out = call(game, "update_status", health=0, satiety=0, hydration=30, energy=0, money=0,
               consumed_items=["빗물"], reason="받아 둔 빗물을 마셨다")
    assert out["사라진_소지품"] == ["빗물"]
    assert not any("빗물" in i for i in game.items) and "물 1L" in game.items   # 생수병은 그대로
    assert game.consume_item("에너지바") and "에너지바 1개" in game.items       # 수량은 하나씩 줄어든다
    assert game.consume_item("에너지바") and not any("에너지바" in i for i in game.items)


def test_auto_consume_when_llm_forgets(game):
    game.begin_turn()
    game.update_items(add=["야생 열매"])
    game.turn_flags.update(intake=True, consumed=False)
    gamemaster.auto_consume(game, "야생 열매를 먹는다")
    assert "야생 열매" not in game.items


def test_tickets_cannot_be_conjured_as_items(game):
    game.begin_turn()
    out = call(game, "update_inventory", remove=[], add=[{"name": "한국행 비행기 티켓", "carryable": True}])
    assert out["거부된_물건"] and not any("티켓" in i for i in game.items)
    assert call(game, "buy_ticket", method="flight", distance_km=1)["success"] is False   # 야생에서는 못 산다
    assert call(game, "buy_ticket", method="walk", distance_km=1)["success"] is False


def test_pay_and_auto_charge(game, monkeypatch):
    game.begin_turn()
    assert call(game, "pay", amount=8, purpose="생수 2병")["success"] and game.money == 42
    assert call(game, "pay", amount=100, purpose="숙박")["success"] is False and game.money == 42
    assert gamemaster.auto_charge(game, "당신은 $5를 내고 빵을 산다.") == 0      # 이미 냈으면 중복 차감 없음

    game.begin_turn()                                               # GM이 pay 를 빠뜨린 경우
    assert gamemaster.auto_charge(game, "주인에게 $12를 건네고 방 열쇠를 받는다.") == 12 and game.money == 30
    game.begin_turn()
    assert gamemaster.auto_charge(game, "노인이 당신에게 $20를 주었다.") == 0     # 받은 돈은 차감하지 않음
    assert gamemaster.auto_charge(game, "15달러를 지불했다") == 15 and game.money == 15
    game.end_turn(0.5)
    assert game.delta["money"] == -15                               # 상태창에도 -15 로 표시된다

    reply = SimpleNamespace(id="r", output=[], output_text="당신은 $7를 내고 물 한 병을 산다.")
    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=lambda **k: reply)))
    gamemaster.run_turn(game, "물을 산다")
    assert game.money == 8


def test_vehicles_never_enter_inventory(game):
    game.begin_turn()
    out = call(game, "update_inventory", remove=[], add=[
        {"name": "트럭 기사의 화물 트럭", "carryable": True}, {"name": "오토바이", "carryable": True},
        {"name": "낙타", "carryable": True}, {"name": "트럭 열쇠", "carryable": True}])
    assert len(out["거부된_물건"]) == 3 and "acquire_vehicle" in out["거부된_물건"][0]
    assert game.items[-1] == "트럭 열쇠"                              # 열쇠는 들고 다닐 수 있다


def test_money_from_narration_is_applied(game):
    game.begin_turn()
    assert gamemaster.auto_money(game, "지갑 안에는 $280가 들어 있었고, 당신은 그 돈을 챙겼다.") == 280
    assert game.money == 330
    game.begin_turn()
    assert gamemaster.auto_money(game, "소매치기에게 $40를 빼앗겼다.") == -40 and game.money == 290
    game.begin_turn()
    call(game, "update_status", health=0, satiety=0, hydration=0, energy=0, money=50,
         consumed_items=[], reason="일당")
    assert gamemaster.auto_money(game, "일당으로 $50를 받았다.") == 0 and game.money == 340   # 이미 반영됨
    game.begin_turn()
    assert gamemaster.auto_money(game, "$5000를 주웠다") == 600                               # 상한


def test_drinking_in_the_desert_raises_hydration(game, monkeypatch):
    desert_noon(game)
    game.hydration = 50
    # GM이 서술만 하고 아무 툴도 부르지 않은 경우 (보고된 증상)
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="당신은 물을 들이켠다."))
    gamemaster.run_turn(game, "가지고 있는 물을 마신다")
    assert "물 1L" not in game.items and game.hydration > 50 + 35          # +45, 15분 동안 -3.6
    assert game.delta["hours"] == 0.25
    from survival.ui import turn_summary
    assert "💧 수분 +45 (물)" in turn_summary(game) and "더위" in turn_summary(game)


def test_gm_gives_too_little_or_only_removes_item(game, monkeypatch):
    desert_noon(game)
    game.hydration = 50
    call_small = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_status", call_id="a", arguments=json.dumps(
            {"health": 0, "satiety": 0, "hydration": 5, "energy": 0, "money": 0, "money_source": "none",
             "consumed_items": ["물 1L"], "reason": "물을 마심"}))])
    reply_with(monkeypatch, call_small, SimpleNamespace(id="r2", output=[], output_text="당신은 물을 마신다."))
    gamemaster.run_turn(game, "물을 마신다")
    assert game.hydration >= 50 + 45 - 4                                   # GM이 +5만 줘도 +45 보장

    other = GameState(lat=23, lon=11, place_name="사막", weather=fake_weather(), biome="desert")
    desert_noon(other)
    other.hydration = 40
    only_remove = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_inventory", call_id="a", arguments=json.dumps(
            {"add": [], "remove": ["물 1L"], "source": "none", "giver": ""}))])
    reply_with(monkeypatch, only_remove, SimpleNamespace(id="r2", output=[], output_text="물을 다 마셨다."))
    gamemaster.run_turn(other, "물을 마신다")
    assert other.hydration >= 40 + 45 - 4 and "물 1L" not in other.items


def test_eating_food_and_not_double_counting(game, monkeypatch):
    game.satiety = 30
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="당신은 에너지바를 씹는다."))
    gamemaster.run_turn(game, "에너지바를 먹는다")
    assert "에너지바 1개" in game.items and game.satiety >= 30 + 25 - 1        # 하나만 먹는다
    game.satiety = 30
    big = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_status", call_id="a", arguments=json.dumps(
            {"health": 0, "satiety": 40, "hydration": 0, "energy": 0, "money": 0, "money_source": "none",
             "consumed_items": ["에너지바"], "reason": "든든히 먹음"}))])
    reply_with(monkeypatch, big, SimpleNamespace(id="r2", output=[], output_text="배가 부르다."))
    gamemaster.run_turn(game, "에너지바를 먹는다")
    assert 30 + 40 - 1 <= game.satiety <= 30 + 40                           # GM이 더 주면 그대로, 겹쳐 더하지 않는다


def test_river_water_is_not_taken_from_inventory(game, monkeypatch):
    game.hydration = 40
    river = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_status", call_id="a", arguments=json.dumps(
            {"health": 0, "satiety": 0, "hydration": 30, "energy": 0, "money": 0, "money_source": "none",
             "consumed_items": [], "reason": "개울물을 끓여 마심"}))])
    reply_with(monkeypatch, river, SimpleNamespace(id="r2", output=[], output_text="개울물을 마신다."))
    gamemaster.run_turn(game, "개울물을 끓여 마신다")
    assert "물 1L" in game.items                                           # 가진 물은 그대로
    assert gamemaster.estimate_time("에너지바를 먹고 잔다") == (7.0, "sleep")   # 먹고 자면 잠이 우선


def test_volume_helpers():
    assert liquid_ml("물 1L") == 1000 and liquid_ml("생수 500ml") == 500 and liquid_ml("물 1.5L") == 1500
    assert liquid_ml("에너지바 2개") is None and liquid_ml("스마트폰(배터리 30%)") is None
    assert with_volume("물 1L", 750) == "물 750ml" and with_volume("물 2L", 1500) == "물 1.5L"
    assert consumable_effect("물 1L") == ("hydration", 45)                  # 기존 값 그대로
    assert consumable_effect("물 500ml") == ("hydration", 22)               # 용량에 비례
    assert consumable_effect("물 250ml") == ("hydration", 11)


def test_partial_portion_wording():
    assert partial_portion("가진 물을 조금 마신다", 1000) == 250
    assert partial_portion("물을 한 모금 마신다", 1000) == 250
    assert partial_portion("물을 아껴서 마신다", 1000) == 250
    assert partial_portion("물을 반만 마신다", 1000) == 500
    assert partial_portion("물을 절반 마신다", 600) == 300
    assert partial_portion("물을 마신다", 1000) is None
    assert partial_portion("물을 마시고 조금 쉰다", 1000) is None           # '조금'이 쉬는 것에 붙음
    assert partial_portion("반드시 물을 마신다", 1000) is None
    assert partial_portion("모금함 옆에서 물을 마신다", 1000) is None
    assert partial_portion("물을 조금 마신다", 250) is None                 # 남은 게 한 모금뿐이면 다 마신다


def test_sipping_keeps_the_rest_when_gm_does_nothing(game, monkeypatch):
    """보고된 증상: GM이 툴 없이 서술만 해도 '조금 마신다'면 남은 물이 남는다."""
    game.hydration = 50
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="당신은 물을 한 모금 마신다."))
    gamemaster.run_turn(game, "가진 물을 조금 마신다")
    assert "물 750ml" in game.items and "물 1L" not in game.items
    assert 50 + 11 - 2 <= game.hydration <= 50 + 11                        # 250ml 만큼만
    from survival.ui import turn_summary
    assert "💧 수분 +11 (물)" in turn_summary(game)


def test_sipping_caps_gm_gain_and_reports_remaining(game, monkeypatch):
    """GM이 물 한 병을 다 마신 만큼(+45) 줘도 반만 마셨으면 반만큼만 오르고, 남은 물을 툴 결과로 알려 준다."""
    game.hydration = 40
    big = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_status", call_id="a", arguments=json.dumps(
            {"health": 0, "satiety": 0, "hydration": 45, "energy": 0, "money": 0, "money_source": "none",
             "consumed_items": ["물 1L"], "reason": "물을 마심"}))])
    reply_with(monkeypatch, big, SimpleNamespace(id="r2", output=[], output_text="물을 반쯤 마신다."))
    gamemaster.run_turn(game, "물을 반만 마신다")
    assert "물 500ml" in game.items
    assert 40 + 22 - 2 <= game.hydration <= 40 + 23
    game.turn_flags = {"player_text": "물을 한 모금 마신다"}
    result = call(game, "update_status", health=0, satiety=0, hydration=30, energy=0, money=0,
                  money_source="none", consumed_items=["물 500ml"], reason="한 모금")
    assert result["일부만_마심"] == ["물 500ml → 물 250ml (250ml 마심)"] and result["사라진_소지품"] == []
    assert "물 250ml" in game.items


def test_gm_removing_bottle_on_a_sip_leaves_the_rest(game, monkeypatch):
    """GM이 '물 1L'을 지우기만 해도, 조금 마셨으면 남은 물을 남긴다. GM이 직접 남은 양을 넣으면 그대로 따른다."""
    game.hydration = 40
    only_remove = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_inventory", call_id="a", arguments=json.dumps(
            {"add": [], "remove": ["물 1L"], "source": "none", "giver": ""}))])
    reply_with(monkeypatch, only_remove, SimpleNamespace(id="r2", output=[], output_text="목을 축인다."))
    gamemaster.run_turn(game, "물을 조금 마신다")
    assert "물 750ml" in game.items and game.hydration >= 40 + 11 - 2

    game.items = ["물 1L"]
    game.turn_flags = {"player_text": "물을 조금 마신다"}
    game.update_items(add=["물 800ml"], remove=["물 1L"])
    assert game.items == ["물 800ml"]


def test_full_drink_still_empties_the_bottle(game, monkeypatch):
    game.hydration = 40
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="물을 다 마신다."))
    gamemaster.run_turn(game, "물을 전부 마신다")
    assert not any(liquid_ml(i) for i in game.items) and game.hydration >= 40 + 45 - 2


def test_full_drink_of_measured_water_caps_gm_gain(game, monkeypatch):
    """남은 물 375ml(기본 +17)를 다 마실 때 GM이 +35를 줘도 1.2배(+20)까지만. 강물처럼 용량을 모르는 것은 GM을 따른다."""
    game.items = ["물 375ml"]
    game.hydration = 40
    game.turn_flags = {"player_text": "남은 물을 전부 마신다"}
    call(game, "update_status", health=0, satiety=0, hydration=35, energy=0, money=0, money_source="none",
         consumed_items=["물 375ml"], reason="다 마심")
    assert game.hydration == 40 + 20 and game.items == []
    game.turn_flags = {"player_text": "개울물을 끓여 마신다"}
    call(game, "update_status", health=0, satiety=0, hydration=30, energy=0, money=0, money_source="none",
         consumed_items=[], reason="개울물")
    assert game.hydration == 60 + 30
