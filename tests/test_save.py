"""자동 저장과 이어하기 (survival/savegame.py) 테스트."""
from types import SimpleNamespace

from survival import gamemaster, savegame


def test_save_and_resume(game, monkeypatch, tmp_path):
    monkeypatch.setattr(savegame, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(savegame, "SAVE_PATH", tmp_path / "autosave.json")
    assert savegame.load() is None and not savegame.exists()
    game.begin_turn()
    game.pass_time(3, "explore")
    game.update_items(add=["마른 장작"])
    game.chat = [{"role": "assistant", "content": "시작"}, {"role": "user", "content": "걷는다"}]
    game.prev_response_id = "resp_x"
    game.end_turn()
    savegame.save(game)

    loaded = savegame.load()
    assert loaded is not None and loaded is not game
    for key in ("lat", "lon", "health", "hydration", "elapsed_hours", "items", "chat",
                "prev_response_id", "distance", "turn", "delta"):
        assert getattr(loaded, key) == getattr(game, key), key
    loaded.pass_time(1, "rest")            # 불러온 상태로 계속 진행할 수 있다

    game.status = "dead"
    savegame.save(game)                    # 게임이 끝나면 저장 파일이 지워진다
    assert not savegame.exists()


def test_resume_with_expired_conversation(game, monkeypatch):
    """저장된 대화 ID가 만료됐으면 최근 줄거리를 넣어 새 대화로 이어간다."""
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if kwargs.get("previous_response_id") == "expired":
            raise RuntimeError("Previous response not found")
        return SimpleNamespace(id="new", output=[], output_text="당신은 다시 눈을 뜬다.")

    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=fake_create)))
    game.prev_response_id = "expired"
    game.chat = [{"role": "assistant", "content": "당신은 동굴에서 불을 피웠다."}]
    gamemaster.run_turn(game, "주변을 살펴본다")
    assert len(calls) == 2 and calls[1]["previous_response_id"] is None
    assert "이전 줄거리" in calls[1]["input"] and "동굴" in calls[1]["input"]
    assert game.prev_response_id == "new"


def test_saving_can_be_disabled_for_share_mode(game, monkeypatch, tmp_path):
    monkeypatch.setattr(savegame, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(savegame, "SAVE_PATH", tmp_path / "autosave.json")
    savegame.save(game)
    assert savegame.exists()
    monkeypatch.setattr(savegame, "ENABLED", False)      # python app.py --share
    assert not savegame.exists() and savegame.load() is None
    game.health = 1
    savegame.save(game)                                  # 저장하지도, 기존 파일을 건드리지도 않는다
    monkeypatch.setattr(savegame, "ENABLED", True)
    assert savegame.load().health == 100
