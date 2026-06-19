from app.services.series_generation_status import queue_covers_all_eligible_characters


def test_queue_covers_all_when_no_character_ids_filter() -> None:
    payload = {"characters": [{"id": 1}, {"id": 2}, {"id": 3}]}
    assert queue_covers_all_eligible_characters(None, payload)


def test_queue_covers_all_when_exact_character_ids() -> None:
    payload = {"characters": [{"id": 1}, {"id": 2}]}
    assert queue_covers_all_eligible_characters([1, 2], payload)


def test_queue_partial_when_subset_character_ids() -> None:
    payload = {"characters": [{"id": 1}, {"id": 2}, {"id": 3}]}
    assert not queue_covers_all_eligible_characters([1, 2], payload)
