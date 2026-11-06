from types import SimpleNamespace
from src.core.models import PityState
from src.core.store import Store
from src.services.identity import avatar_bytes, display_name


def test_cumulative_pulls_survive_pity_reset_and_selector(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    store.save_state("qq", "12345", "char", PityState(pity5=0, pulls=80))
    state = PityState(pity5=10, pulls=310, totals={"standard": 310})
    store.save_state("qq", "12345", "standard", state.with_total("standard", 10))
    store.save_state("qq", "other", "char", PityState(pulls=999))
    assert store.total_pulls("qq", "12345") == 390
    store.close()


def test_non_qq_numeric_id_does_not_request_qq_avatar():
    event = SimpleNamespace(get_platform_name=lambda: "telegram", get_sender_id=lambda: "123456")
    assert avatar_bytes(event) is None


def test_nickname_falls_back_to_sender():
    event = SimpleNamespace(message_obj=SimpleNamespace(sender=SimpleNamespace(nickname="风玲")))
    assert display_name(event) == "风玲"
