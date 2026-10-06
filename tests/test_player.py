from types import SimpleNamespace as NS
from ymd.player import Player, WAVE
from tests.fakes import FakeApi, FakeMpv


def make(**kw):
    api, mpv, n = FakeApi(**kw), FakeMpv(), []
    return Player(api, mpv, lambda: n.append(1)), api, mpv, n


async def pos(p, i):
    """Simulate mpv reporting position change."""
    p.mpv.pos = i
    await p.on_event({"event": "property-change", "name": "playlist-pos", "data": i})


async def test_likes_loads_window():
    p, api, mpv, _ = make()
    await p.start_likes()
    assert p.index == 0 and mpv.playlist == ["url0", "url1"] and p.loaded == [0, 1]
    assert p.state()["source"] == {"type": "likes", "title": "", "mood": ""}


async def test_play_middle_inserts_previous():
    p, api, mpv, _ = make()
    await p.start_likes()
    await p.play(2)
    assert mpv.playlist == ["url1", "url2", "url3"] and p.loaded == [1, 2, 3]
    await pos(p, 1)                      # mpv reports the shift after insert-at: no-op
    assert p.index == 2


async def test_next_from_media_keys_slides_window():
    p, api, mpv, _ = make()
    await p.start_likes(); await p.play(2)
    await pos(p, 2)                      # mpv-mpris "next"
    assert p.index == 3 and mpv.playlist == ["url2", "url3", "url4"] and p.loaded == [2, 3, 4]


async def test_prev_from_media_keys_slides_back():
    p, api, mpv, _ = make()
    await p.start_likes(); await p.play(2)
    await pos(p, 0)
    assert p.index == 1 and mpv.playlist == ["url0", "url1", "url2"] and p.loaded == [0, 1, 2]


async def test_next_at_end_of_likes_keeps_last():
    p, api, mpv, _ = make(likes=2)
    await p.start_likes(); await p.play(1)
    assert mpv.playlist == ["url0", "url1"] and p.loaded == [0, 1]
    await pos(p, 2)                      # out of range: ignored
    assert p.index == 1


async def test_wave_with_mood_feedback_and_skip():
    p, api, mpv, _ = make()
    await p.start_wave("calm")
    assert api.settings == [(WAVE, "calm", "default")]
    assert api.feedback[:2] == [(WAVE, "radioStarted", None), (WAVE, "trackStarted", "100:100")]
    await p.on_event({"event": "end-file", "reason": "stop"})
    await pos(p, 1)
    assert api.feedback[-2:] == [(WAVE, "skip", "100:100"), (WAVE, "trackStarted", "101:100")]


async def test_wave_eof_sends_finished():
    p, api, mpv, _ = make()
    await p.start_wave(None)
    assert api.settings == []
    await p.on_event({"event": "property-change", "name": "time-pos", "data": 180.0})
    await p.on_event({"event": "end-file", "reason": "eof"})
    await pos(p, 1)
    assert (WAVE, "trackFinished", "100:100") in api.feedback


async def test_error_end_does_not_send_finished():
    p, api, mpv, _ = make()
    await p.start_wave(None)
    await p.on_event({"event": "end-file", "reason": "error"})
    await pos(p, 1)
    kinds = [f[1] for f in api.feedback]
    assert "trackFinished" not in kinds and p.index == 1


async def test_wave_refills_when_near_end():
    p, api, mpv, _ = make()
    await p.start_wave(None)
    for i in range(1, 4):
        await pos(p, min(i, 2))
    assert api.rotor_calls[-1] == (WAVE, "104")
    assert len(p.queue) == 10


async def test_track_wave_uses_track_station_and_title():
    p, api, mpv, _ = make()
    await p.start_likes()
    await p.start_track_wave("3")
    assert api.rotor_calls[0] == ("track:3", None)
    assert p.state()["source"] == {"type": "track-wave", "title": "t3", "mood": ""}


async def test_like_toggles_and_dislike_in_wave_skips():
    p, api, mpv, _ = make()
    await p.start_wave(None)
    await p.like()
    assert api.liked_add == ["100"] and p.state()["track"]["liked"] is True
    await p.like()
    assert api.liked_add == [] and p.state()["track"]["liked"] is False
    await p.dislike()
    assert api.disliked == ["100"] and mpv.calls[-1] == ("playlist-next",)


async def test_search_and_play_from_results():
    p, api, mpv, _ = make()
    await p.search("кино")
    assert api.searched == [("кино", "track")]
    assert [r["id"] for r in p.state()["search"]["results"]] == ["900", "901"]
    await p.play_search(1)
    assert p.state()["source"] == {"type": "search", "title": "кино", "mood": ""}
    assert p.queue[p.index]["id"] == "901"


async def test_empty_search_clears():
    p, api, mpv, _ = make()
    await p.search("кино"); await p.search("   ")
    assert p.state()["search"] == {"text": "", "results": []} and len(api.searched) == 1


async def test_toggle_when_stopped_replays_current():
    p, api, mpv, _ = make()
    await p.start_likes(); await p.stop()
    assert mpv.playlist == []
    await p.toggle()
    assert mpv.playlist == ["url0", "url1"]


async def test_state_marks_playing_track():
    p, api, mpv, _ = make()
    await p.start_likes()
    await p.on_event({"event": "property-change", "name": "pause", "data": False})
    s = p.state()
    assert s["index"] == 0 and s["playing"] is True and s["track"]["title"] == "t0"
    assert s["moods"] == ["all", "fun", "active", "calm", "sad"]


# --- Fix round 1 tests ---


async def test_search_with_none_tracks():
    """search() guards when api returns tracks=None."""
    p, api, mpv, _ = make(search_tracks=NS(results=None))
    await p.search("test")
    assert p.state()["search"]["results"] == []


async def test_like_with_no_current_track():
    """like() returns without API call when index is invalid."""
    p, api, mpv, _ = make()
    p.queue = []
    p.index = -1
    await p.like()
    assert api.liked_add == []


async def test_dislike_with_no_current_track():
    """dislike() returns without API call when index is invalid."""
    p, api, mpv, _ = make()
    p.queue = []
    p.index = -1
    await p.dislike()
    assert api.disliked == [] and mpv.calls == []


async def test_best_link_none_skips_to_next_playable():
    """When best_link returns None, skip to next playable track."""
    p, api, mpv, _ = make(unavailable_ids={"0"})
    await p.start_likes()
    # Track 0 unavailable, skips to track 1
    assert p.index == 1 and p.loaded == [1, 2]
    assert mpv.playlist == ["url1", "url2"]
    assert p.error is None


async def test_race_condition_pos_during_loadfile_replace():
    """After play(i>0) with replace+insert-at, pos events read live position not event data."""
    import asyncio
    p, api, mpv, _ = make()
    await p.start_likes()
    # play(2): replace with index 2, insert-at 0 for index 1
    # This triggers replace (pos=0) then insert-at 0 (pos=1 now)
    await p.play(2)
    assert p.index == 2 and p.loaded == [1, 2, 3]
    # Verify that the fix works: if we emit a stale pos(0) event but mpv.pos is actually 1
    # (simulating the event arriving after the actual pos changed), it should use live pos
    mpv.pos = 1
    await p.on_event({"event": "property-change", "name": "playlist-pos", "data": 0})
    # Live pos 1 maps to loaded[1]=2, so index becomes 2
    assert p.index == 2  # No spurious backwards move


async def test_best_link_none_skips_multiple_unavailable():
    """When multiple tracks are unavailable, skip to next playable."""
    p, api, mpv, _ = make(unavailable_ids={"0", "1", "2"})
    await p.start_likes()
    # Tracks 0, 1, 2 are unavailable (preview-only); track 3 is available
    assert p.index == 3 and p.loaded == [3, 4]
    assert mpv.playlist == ["url3", "url4"]
    assert p.error is None


async def test_best_link_all_unavailable_sets_error():
    """When all remaining tracks are unavailable, set error."""
    p, api, mpv, _ = make(likes=2, unavailable_ids={"0", "1"})
    await p.start_likes()
    # All tracks unavailable
    assert p.error == "track unavailable" and mpv.playlist == []


async def test_pos_event_reads_live_position():
    """on_event reads live position via get_property, not stale event data."""
    p, api, mpv, _ = make()
    await p.start_likes()
    await p.play(2)
    # After play(2): index=2, loaded=[1,2,3], mpv.pos=0
    # Emit pos event with stale data but check that live pos is used
    # Set mpv.pos to 1 (live position after some user action)
    mpv.pos = 1
    await p.on_event({"event": "property-change", "name": "playlist-pos", "data": 0})
    # Live pos (1) maps to loaded[1]=2, so index should be 2, not affected by stale data (0)
    assert p.index == 2


async def test_pos_event_during_play_does_not_corrupt_window():
    """Concurrent pos event during play(2) with on_load hook must not corrupt window."""
    import asyncio
    p, api, mpv, _ = make()
    await p.start_likes()

    def hook():
        asyncio.create_task(p.on_event({"event": "property-change", "name": "playlist-pos", "data": 0}))

    mpv.on_load = hook
    await p.play(2)
    for _ in range(5):
        await asyncio.sleep(0)
    assert p.index == 2 and p.loaded == [1, 2, 3] and mpv.playlist == ["url1", "url2", "url3"]


async def test_pos_event_during_start_wave_no_spurious_feedback():
    """Wave start with pos event during loadfile has no spurious skip feedback."""
    import asyncio
    p, api, mpv, _ = make()

    def hook():
        asyncio.create_task(p.on_event({"event": "property-change", "name": "playlist-pos", "data": 0}))

    mpv.on_load = hook
    await p.start_wave(None)
    for _ in range(5):
        await asyncio.sleep(0)
    await p.play(2)
    for _ in range(5):
        await asyncio.sleep(0)
    # Only the explicit skip from play(2) switching from 100 to 102
    skip_feedbacks = [f for f in api.feedback if f[1] == "skip"]
    assert len(skip_feedbacks) == 1 and skip_feedbacks[0][2] == "100:100"
