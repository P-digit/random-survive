"""엔진 구조 테스트: GameState가 기능별 모듈(믹스인)로 나뉜 뒤에도 하나의 객체처럼 동작하는지."""
import inspect

from survival import crime, inventory, journey, offers, state, travel
from survival.state import GameState
from tests.helpers import patch_everywhere


MIXINS = (inventory.InventoryMixin, crime.CrimeMixin, travel.TravelMixin, journey.JourneyMixin, offers.OfferMixin)
# 나누기 전 state.py의 GameState에 있던 메서드 (refactor/state-split 기준)
METHODS_BEFORE = ['_advance_journey', '_arrest', '_arrive_at_new_place', '_arrive_journey', '_check_death', '_close_offer', '_drive', '_finish_offer', '_go_airport_now', '_go_embassy_now', '_head_to_village', '_instant_offer', '_leg_mode', '_note_gain', '_place_new_location', '_record_crime', '_relocate', '_start_journey', '_tracked', 'accept_offer', 'acquire_vehicle', 'add_character', 'add_lead', 'apply_delta', 'arrest', 'attempt', 'begin_turn', 'biome_name', 'buy_ticket', 'closed_offers_here', 'consume_item', 'crime_aftermath', 'day', 'decline_offer', 'early', 'early_message', 'end_turn', 'enemies_nearby', 'event_context', 'expire_offer', 'fare', 'find_character', 'find_item', 'find_lead', 'find_ticket', 'find_ticket_by_item', 'follow_lead', 'go_to', 'guard_unrequested_move', 'hazard', 'hour', 'in_extreme_wild', 'indoor', 'is_night', 'mark_victim', 'notorious_here', 'offer_closed', 'offer_needs', 'pass_time', 'pay', 'place_changed', 'plan_offer', 'recently_expired', 'refresh_climate', 'refresh_risk', 'remember', 'repatriate', 'same_place', 'seek_help', 'set_scene', 'set_weather', 'settle_consumption', 'sip_item', 'summary', 'sync_weather', 'travel', 'update_items', 'visible_things', 'where']


def own_methods(cls):
    return {name for name, value in vars(cls).items() if inspect.isfunction(value) or isinstance(value, property)}


def test_game_state_is_built_from_the_mixins():
    assert GameState.__mro__[1:1 + len(MIXINS)] == MIXINS


def test_no_method_is_defined_twice():
    """같은 이름이 두 곳에 있으면 상속 순서에 따라 하나가 조용히 가려진다."""
    owners = {}
    for cls in (GameState,) + MIXINS:
        for name in own_methods(cls) - {"__init__", "__repr__", "__eq__"}:
            owners.setdefault(name, []).append(cls.__name__)
    duplicates = {name: where for name, where in owners.items() if len(where) > 1}
    assert not duplicates, duplicates


def test_every_method_from_before_the_split_still_exists():
    missing = [name for name in METHODS_BEFORE if not hasattr(GameState, name)]
    assert not missing, missing


def test_mixins_do_not_import_state():
    """믹스인이 state를 가져오면 순환 import가 된다(state가 믹스인을 가져온다)."""
    for module in (inventory, crime, travel, journey, offers):
        source = inspect.getsource(module)
        assert "from .state import" not in source and "import state" not in source, module.__name__


def test_patch_everywhere_reaches_moved_code(monkeypatch):
    fake = object()
    patched = patch_everywhere(monkeypatch, "get_weather", fake)
    assert {"survival.state", "survival.travel"} <= set(patched)
    assert state.get_weather is fake and travel.get_weather is fake
