"""한 화면 UI: 상단 줄·신체 수치·알림(경찰 확률·의뢰 제안)·지도·정보 탭, 화면 출력 개수."""
import pytest

from survival import achievements, ui
from survival.achievements import record_trail
from survival.config import SEOUL


def test_every_panel_renders_before_the_game_starts():
    for render in (ui.render_topbar, ui.render_location, ui.render_vitals, ui.render_status, ui.render_bag,
                   ui.render_record):
        assert render(None)
    assert ui.render_alerts(None) == ""               # 낙하 전에는 결정할 일이 없다 (상자를 숨긴다)


def test_every_panel_renders_mid_game(game):
    game.wanted, game.money = 45, 120
    html = ui.render_topbar(game)
    assert "DAY" in html and "★★★" in html and "$120" in html
    assert "MAP" in ui.render_status(game) and "INVENTORY" in ui.render_bag(game)
    assert ui.render_alerts(game) == ""


def test_view_matches_the_screen_outputs(game, monkeypatch):
    """view()가 돌려주는 값의 개수가 화면의 출력 컴포넌트 수와 같아야 한다 (순서가 어긋나면 화면이 깨진다)."""
    import importlib
    import sys
    monkeypatch.delitem(sys.modules, "app", raising=False)     # 다른 테스트가 가짜 gradio로 불러 둔 app을 버린다
    app = importlib.import_module("app")
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")     # 화면을 만들 때 Gradio가 통계를 보내지 않게
    demo, _ = app.build_app()
    fns = demo.fns.values() if isinstance(demo.fns, dict) else demo.fns
    turn_outputs = {len(fn.outputs) for fn in fns if fn.name in ("new_game", "resume_game", "play")}
    assert turn_outputs == {len(app.view(None, app.intro_chat()))} == {len(app.view(game, []))}


def test_police_alert_shows_the_odds_of_each_response(game):
    game.wanted, game.money = 45, 10
    game.pursuit = {"stage": 3, "turn": game.turn, "who": "순찰차", "kind": "chase", "stolen_vehicle": False}
    odds = {o["kind"]: o["chance"] for o in game.police_odds()}
    assert odds["flee"] == game.police_chance("flee")[0]
    assert odds["bribe"] == 0.0                        # 뇌물 $80이 없다
    assert odds["surrender"] is None                   # 자수는 확률이 아니라 확정
    html = ui.render_alerts(game)
    assert "alert police" in html and "추격" in html and "자수" in html and "뇌물 $80" in html
    assert f'{odds["hide"] * 100:.0f}%' in html


def test_no_odds_without_police(game):
    assert game.police_odds() == []


def test_mission_offer_and_big_offer_are_shown_above_the_actions(game):
    game.mission_offer = {"kind": "smuggle", "giver": "밀수꾼", "item": "밀수품 꾸러미", "target": "베이징",
                          "lat": 39.9, "lon": 116.4, "country": "cn", "km": 1160, "direction": "남동",
                          "reward": 614, "hours": 47, "turn": game.turn}
    game.offer = {"id": "trucker", "text": "트럭 기사가 태워 주겠다고 한다", "detail": "600km", "accept": "트럭에 탄다"}
    html = ui.render_alerts(game)
    assert "의뢰 제안" in html and "베이징" in html and "$614" in html and "밀수" in html
    assert "기회" in html and "트럭에 탄다" in html


def test_game_over_banner(game):
    game.status = "dead"
    assert "YOU DIED" in ui.render_alerts(game)
    game.status = "won"
    assert "귀환 성공" in ui.render_alerts(game)


@pytest.mark.parametrize("stat, value, critical", [("health", 20, True), ("hydration", 10, True),
                                                    ("satiety", 5, True), ("health", 30, False)])
def test_critical_vitals_light_up_the_screen_edge(game, stat, value, critical):
    setattr(game, stat, value)
    assert ui.is_critical(game) is critical
    assert ("vitals critical" in ui.render_vitals(game)) is critical


def test_trail_records_moves_and_skips_tiny_steps(game):
    game.stats = {}
    record_trail(game)
    game.lat += 0.01                                   # 1km 남짓: 새 점을 찍지 않는다
    record_trail(game)
    assert len(game.stats["trail"]) == 1
    game.lat += 1
    record_trail(game)
    assert len(game.stats["trail"]) == 2


def test_trail_is_thinned_but_keeps_both_ends(game):
    game.stats = {"trail": [[float(i % 80), float(i)] for i in range(achievements.TRAIL_MAX)]}
    first = game.stats["trail"][0]
    game.lat, game.lon = -40.0, -70.0
    record_trail(game)
    trail = game.stats["trail"]
    assert len(trail) <= achievements.TRAIL_MAX // 2 + 2
    assert trail[0] == first and trail[-1] == [-40.0, -70.0]


def test_map_does_not_break_at_the_date_line():
    """알래스카(-150°)는 서울 동쪽에 붙여 그린다: 지도가 지구 반대편까지 늘어나지 않는다."""
    west, north, width, height = ui.map_frame([(64.8, -147.7), SEOUL])
    assert width < 160 and west <= SEOUL[1] and west + width >= 360 - 147.7
    assert height == pytest.approx(width / ui.MAP_ASPECT)


def test_map_frame_stays_on_the_globe():
    west, north, width, height = ui.map_frame([(-50.0, -70.0), SEOUL])
    assert north <= 90 and north - height >= -90


def test_map_draws_land_trail_and_targets(game):
    game.stats["trail"] = [[game.lat - 3, game.lon - 3], [game.lat, game.lon]]
    game.mission = {"kind": "deliver", "item": "소포", "target": "베이징", "lat": 39.9, "lon": 116.4,
                    "reward": 100, "deadline": 99, "giver": "주인"}
    html = ui.render_map(game)
    assert ui.land_rings() and "<polyline" in html and "의뢰 목적지" in html and "지나온 길" in html
    assert '<path d="M' in html                         # 육지 윤곽


def test_contraband_is_marked_in_the_bag(game):
    game.items.append("금목걸이")
    game.stolen_items.append("금목걸이")
    assert 'class="chip hot"' in ui.render_bag(game)


def test_record_tab_lists_every_achievement(game):
    game.achievements = ["first_steps"]
    html = ui.render_record(game)
    assert html.count('class="on"') == 1 and html.count('class="off"') == len(achievements.ACHIEVEMENTS) - 1
