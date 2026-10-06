import tempfile
from pathlib import Path
import pytest
from types import SimpleNamespace as NS
from ymd.player import Player, WAVE
from tests.fakes import FakeApi, FakeMpv, track


def make(download=None, **kw):
    api, mpv, n = FakeApi(**kw), FakeMpv(), []
    p = Player(api, mpv, lambda: n.append(1), cache_dir=Path(tempfile.mkdtemp()) / "tracks",
               download=download or offline)
    return p, api, mpv, n


def offline(url, path):
    raise OSError("offline")


def fake_download(url, path):
    Path(path).write_bytes(b"x" * 10)


async def likes(p):
    await p.start_likes(); await p.play(0); await p.settle()


async def wave(p, mood):
    await p.start_wave(mood); await p.play(0); await p.settle()


async def pos(p, i):
    """Simulate mpv reporting position change."""
    p.mpv.pos = i
    await p.on_event({"event": "property-change", "name": "playlist-pos", "data": i})


async def test_likes_loads_window():
    p, api, mpv, _ = make()
    await likes(p)
    assert p.index == 0 and mpv.playlist == ["url0", "url1"] and p.loaded == [0, 1]
    assert p.state()["source"] == {"type": "likes", "title": "", "mood": ""}


async def test_play_middle_inserts_previous():
    p, api, mpv, _ = make()
    await likes(p)
    await p.play(2); await p.settle()
    assert mpv.playlist == ["url1", "url2", "url3"] and p.loaded == [1, 2, 3]
    await pos(p, 1)                      # mpv reports the shift after insert-at: no-op
    assert p.index == 2


async def test_next_from_media_keys_slides_window():
    p, api, mpv, _ = make()
    await likes(p); await p.play(2); await p.settle()
    await pos(p, 2)                      # mpv-mpris "next"
    assert p.index == 3 and mpv.playlist == ["url2", "url3", "url4"] and p.loaded == [2, 3, 4]


async def test_prev_from_media_keys_slides_back():
    p, api, mpv, _ = make()
    await likes(p); await p.play(2); await p.settle()
    await pos(p, 0)
    assert p.index == 1 and mpv.playlist == ["url0", "url1", "url2"] and p.loaded == [0, 1, 2]


async def test_next_at_end_of_likes_keeps_last():
    p, api, mpv, _ = make(likes=2)
    await likes(p); await p.play(1); await p.settle()
    assert mpv.playlist == ["url0", "url1"] and p.loaded == [0, 1]
    await pos(p, 2)                      # out of range: ignored
    assert p.index == 1


async def test_wave_with_mood_feedback_and_skip():
    p, api, mpv, _ = make()
    await wave(p, "calm")
    assert api.settings == [(WAVE, "calm", "default")]
    assert api.feedback[:2] == [(WAVE, "radioStarted", None), (WAVE, "trackStarted", "100:100")]
    await p.on_event({"event": "end-file", "reason": "stop"})
    await pos(p, 1)
    assert api.feedback[-2:] == [(WAVE, "skip", "100:100"), (WAVE, "trackStarted", "101:100")]


async def test_wave_eof_sends_finished():
    p, api, mpv, _ = make()
    await wave(p, None)
    assert api.settings == []
    await p.on_event({"event": "property-change", "name": "time-pos", "data": 180.0})
    await p.on_event({"event": "end-file", "reason": "eof"})
    await pos(p, 1)
    assert (WAVE, "trackFinished", "100:100") in api.feedback


async def test_error_end_does_not_send_finished():
    p, api, mpv, _ = make()
    await wave(p, None)
    await p.on_event({"event": "end-file", "reason": "error"})
    await pos(p, 1)
    kinds = [f[1] for f in api.feedback]
    assert "trackFinished" not in kinds and p.index == 1


async def test_wave_refills_when_near_end():
    p, api, mpv, _ = make()
    await wave(p, None)
    for i in range(1, 4):
        await pos(p, min(i, 2))
    assert api.rotor_calls[-1] == (WAVE, "104")
    assert len(p.queue) == 10


async def test_track_wave_uses_track_station_and_title():
    p, api, mpv, _ = make()
    await likes(p)
    await p.start_track_wave("3")
    assert api.rotor_calls[0] == ("track:3", None)
    assert p.state()["source"] == {"type": "track-wave", "title": "t3", "mood": ""}


async def test_like_toggles_and_dislike_in_wave_skips():
    p, api, mpv, _ = make()
    await wave(p, None)
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
    await p.play_search(1); await p.settle()
    assert p.state()["source"] == {"type": "search", "title": "кино", "mood": ""}
    assert p.queue[p.index]["id"] == "901"


async def test_empty_search_clears():
    p, api, mpv, _ = make()
    await p.search("кино"); await p.search("   ")
    assert p.state()["search"] == {"text": "", "results": []} and len(api.searched) == 1


async def test_toggle_when_stopped_replays_current():
    p, api, mpv, _ = make()
    await likes(p); await p.stop()
    assert mpv.playlist == []
    await p.toggle(); await p.settle()
    assert mpv.playlist == ["url0", "url1"]


async def test_state_marks_playing_track():
    p, api, mpv, _ = make()
    await likes(p)
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
    """like() returns without API call when nothing has played."""
    p, api, mpv, _ = make()
    await p.like()
    assert api.liked_add == []


async def test_dislike_with_no_current_track():
    """dislike() returns without API call when nothing has played."""
    p, api, mpv, _ = make()
    await p.dislike()
    assert api.disliked == [] and mpv.calls == []


async def test_best_link_none_skips_to_next_playable():
    """When best_link returns None, skip to next playable track."""
    p, api, mpv, _ = make(unavailable_ids={"0"})
    await likes(p)
    # Track 0 unavailable, skips to track 1
    assert p.index == 1 and p.loaded == [1, 2]
    assert mpv.playlist == ["url1", "url2"]
    assert p.error is None


async def test_best_link_none_skips_multiple_unavailable():
    """When multiple tracks are unavailable, skip to next playable."""
    p, api, mpv, _ = make(unavailable_ids={"0", "1", "2"})
    await likes(p)
    # Tracks 0, 1, 2 are unavailable (preview-only); track 3 is available
    assert p.index == 3 and p.loaded == [3, 4]
    assert mpv.playlist == ["url3", "url4"]
    assert p.error is None


async def test_best_link_all_unavailable_sets_error():
    """When all remaining tracks are unavailable, set error."""
    p, api, mpv, _ = make(likes=2, unavailable_ids={"0", "1"})
    await likes(p)
    # All tracks unavailable
    assert p.error == "track unavailable" and mpv.playlist == []


def interleave_once(p):
    """on_load hook: on the first loadfile, fire a playlist-pos event and let it run mid-play()."""
    import asyncio
    fired = []

    async def hook():
        if fired:
            return
        fired.append(1)
        # mpv.pos is transient here (0 right after `replace`, before `insert-at`)
        asyncio.create_task(p.on_event({"event": "property-change", "name": "playlist-pos", "data": 0}))
        for _ in range(3):
            await asyncio.sleep(0)
    return hook


async def test_pos_event_during_play_does_not_corrupt_window():
    """pos event mid-play() must read mpv's position under the lock, after the window is final."""
    p, api, mpv, _ = make()
    await likes(p)
    mpv.on_load = interleave_once(p)
    await p.play(2); await p.settle()
    import asyncio
    await asyncio.sleep(0)
    assert p.index == 2 and p.loaded == [1, 2, 3] and mpv.playlist == ["url1", "url2", "url3"]


async def test_pos_event_during_start_wave_no_spurious_feedback():
    """Same race while starting a wave: only the explicit skip from play(2) is reported."""
    import asyncio
    p, api, mpv, _ = make()
    mpv.on_load = interleave_once(p)
    await wave(p, None)
    await asyncio.sleep(0)
    await p.play(2); await p.settle()
    await asyncio.sleep(0)
    skips = [f for f in api.feedback if f[1] == "skip"]
    assert skips == [(WAVE, "skip", "100:100")]


async def test_wave_language_any():
    p, api, mpv, _ = make()
    await wave(p, "calm")
    assert api.languages == ["any"]


async def test_play_unpauses():
    p, api, mpv, _ = make()
    await likes(p)
    assert ("set_property", "pause", False) in mpv.calls


async def test_play_out_of_range_is_error():
    p, api, mpv, _ = make()
    await likes(p)
    for i in (-1, 5):
        mpv.calls.clear()
        await p.play(i); await p.settle()
        assert p.index == 0 and p.error == "nothing to play" and not mpv.calls


async def test_empty_likes_and_rotor():
    p, api, mpv, _ = make(likes=0)
    await likes(p)
    assert p.error == "nothing to play" and not mpv.calls
    p, api, mpv, _ = make(wave_batches=[[]])
    await wave(p, None)
    assert p.error == "nothing to play"
    p, api, mpv, _ = make()
    async def none(*a, **k): return None
    api.rotor_station_tracks = none
    await wave(p, None)
    assert p.error == "nothing to play"


async def test_reload_sends_no_skip():
    p, api, mpv, _ = make()
    await wave(p, None)
    api.feedback.clear()
    await p.reload(); await p.settle()
    assert [f[1] for f in api.feedback] == ["trackStarted"]


# --- v2 ---


async def test_play_sets_playing_without_pause_event():
    p, api, mpv, _ = make()
    await likes(p)
    assert p.state()["playing"] is True
    await p.stop()
    assert p.state()["playing"] is False


async def test_feedback_zero_seconds_sends_positive():
    p, api, mpv, _ = make()
    await wave(p, None)
    await p.play(1); await p.settle()          # time_pos is 0.0 here
    skip = [kw for (_, k, _), kw in zip(api.feedback, api.feedback_kw) if k == "skip"]
    assert skip and skip[0]["total_played_seconds"] == 0.1


async def test_feedback_failure_never_breaks_play():
    p, api, mpv, _ = make()
    await wave(p, None)
    api.feedback_error = RuntimeError("Some parts were not parsed")
    await p.play(2); await p.settle()
    assert p.index == 2 and p.error is None and mpv.playlist[1] == "url102"


async def test_failed_play_keeps_marker_on_audible_track():
    p, api, mpv, _ = make()
    await likes(p)
    async def boom(*a, **k): raise OSError("net")
    api.tracks_download_info = boom
    with pytest.raises(OSError):
        await p.play(3)
    assert p.index == 0
    unavailable, _a, _b, _c = make(likes=2, unavailable_ids={"1"})
    await unavailable.start_likes(); await unavailable.play(0); await unavailable.settle()
    await unavailable.play(1)
    assert unavailable.index == 0 and unavailable.error == "track unavailable"


async def test_play_notifies_before_network():
    p, api, mpv, n = make()
    await p.start_likes()
    seen = []
    orig = api.tracks_download_info
    async def spy(*a, **k):
        seen.append((p.index, len(n))); return await orig(*a, **k)
    api.tracks_download_info = spy
    notified = len(n)
    await p.play(2)
    assert seen[0] == (2, notified + 1)      # index set and notified first
    assert mpv.playlist == ["url2"]          # neighbours not loaded yet
    await p.settle()
    assert mpv.playlist == ["url1", "url2", "url3"]


async def test_sources_do_not_autoplay():
    p, api, mpv, _ = make()
    await p.start_likes(); await p.settle()
    assert mpv.calls == [] and p.index == -1 and len(p.queue) == 5
    await p.start_wave("calm"); await p.settle()
    assert mpv.calls == [] and api.feedback == [] and len(p.queue) == 5
    await p.play(0); await p.settle()           # radioStarted with the first play
    assert [f[1] for f in api.feedback] == ["radioStarted", "trackStarted"]


async def test_new_source_keeps_playing_window():
    p, api, mpv, _ = make()
    await likes(p)
    await p.start_wave(None)
    assert mpv.playlist == ["url0", "url1"] and p.loaded == [0, 1] and p.playing is True


async def test_track_wave_plays_immediately():
    p, api, mpv, _ = make()
    await p.start_track_wave("3")
    assert mpv.playlist[0] == "url100"


async def test_url_cache_and_error_drops_it():
    p, api, mpv, _ = make()
    calls = []
    orig = api.tracks_download_info
    async def spy(tid, **k):
        calls.append(tid); return await orig(tid, **k)
    api.tracks_download_info = spy
    await likes(p)
    n = len(calls)
    await p.play(0); await p.settle()
    assert len(calls) == n                      # all links cached
    await p.on_event({"event": "end-file", "reason": "error"})
    await p.play(0); await p.settle()
    assert calls.count("0") == 2                # refetched after the error


async def test_prefetches_index_plus_two():
    p, api, mpv, _ = make()
    await likes(p)
    assert "2" in p.urls


async def test_state_position_duration_and_seek():
    p, api, mpv, n = make()
    await likes(p)
    await p.on_event({"event": "property-change", "name": "duration", "data": 200.0})
    await p.on_event({"event": "property-change", "name": "time-pos", "data": 12.5})
    assert p.state()["position"] == 12.5 and p.state()["duration"] == 200.0
    await p.seek(50)
    assert ("seek", 50, "absolute") in mpv.calls and p.state()["position"] == 50


async def test_fade_in_option_and_fade_out_once():
    p, api, mpv, _ = make()
    await likes(p)
    assert ("loadfile", "url0", "replace", -1, "af=lavfi=[afade=t=in:d=3]") in mpv.calls
    await p.on_event({"event": "property-change", "name": "duration", "data": 200.0})
    for t in (100.0, 197.0, 198.0):
        await p.on_event({"event": "property-change", "name": "time-pos", "data": t})
    fo = [c for c in mpv.calls if c[:2] == ("af", "add")]
    assert len(fo) == 1 and "st=197.0" in fo[0][2]
    await pos(p, 1)                             # next track resets
    await p.on_event({"event": "property-change", "name": "duration", "data": 5.0})
    await p.on_event({"event": "property-change", "name": "time-pos", "data": 4.0})
    assert len([c for c in mpv.calls if c[:2] == ("af", "add")]) == 1   # short track: no fade


async def test_liked_track_cached_and_reused(tmp_path):
    p, api, mpv, _ = make(download=fake_download)
    await likes(p)
    f = p.cache_dir / "0.mp3"
    assert f.exists() and not list(p.cache_dir.glob("*.part"))
    await p.play(0); await p.settle()
    assert mpv.playlist[0] == str(f)


async def test_unliked_not_cached():
    p, api, mpv, _ = make(download=fake_download)
    await p.search("x"); await p.play_search(0); await p.settle()
    assert not p.cache_dir.exists() or not list(p.cache_dir.glob("*"))


def test_trim_removes_least_recently_used(tmp_path):
    import os
    from ymd import diskcache
    for i in range(3):
        f = tmp_path / f"{i}.mp3"; f.write_bytes(b"x" * 10); os.utime(f, (100 + i, 100 + i))
    os.utime(tmp_path / "0.mp3", (200, 200))     # 0 was played last
    diskcache.trim(tmp_path, limit=20)
    assert sorted(f.name for f in tmp_path.glob("*.mp3")) == ["0.mp3", "2.mp3"]


# --- fix round 1 ---


async def test_next_advances_when_after_play_failed():
    p, api, mpv, _ = make()
    await p.start_likes()
    async def boom(*a, **k): raise OSError("x")
    p._append_next = boom
    await p.play(0); await p.settle()
    assert p.loaded == [0]
    await p.next()
    assert p.index == 1 and mpv.playlist[0] == "url1"
    await p.prev()
    assert p.index == 0


async def test_eof_with_single_entry_advances():
    p, api, mpv, _ = make()
    await p.start_likes()
    async def boom(*a, **k): raise OSError("x")
    p._append_next = boom
    await p.play(0); await p.settle()
    await p.on_event({"event": "end-file", "reason": "eof"})
    assert p.index == 1 and mpv.playlist == ["url1"]


async def test_eof_with_neighbour_loaded_leaves_it_to_mpv():
    p, api, mpv, _ = make()
    await likes(p)
    await p.on_event({"event": "end-file", "reason": "eof"})
    assert p.index == 0


async def test_unpause_failure_keeps_window_consistent():
    p, api, mpv, _ = make()
    await likes(p)
    orig = mpv.command
    async def cmd(*a):
        if a[:2] == ("set_property", "pause"): raise OSError("x")
        return await orig(*a)
    mpv.command = cmd
    with pytest.raises(OSError):
        await p.play(3)
    mpv.command = orig
    await p.settle()
    assert p.index == 3 and p.loaded[p.loaded.index(3)] == 3 and mpv.playlist[p.loaded.index(3)] == "url3"


async def test_unavailable_keeps_old_neighbours():
    p, api, mpv, _ = make(likes=3, unavailable_ids={"2"})
    await likes(p)
    await p.play(2); await p.settle()
    assert p.error == "track unavailable" and p.index == 0 and mpv.playlist == ["url0", "url1"]


def test_trim_drops_stale_part_and_counts_fresh(tmp_path):
    import os
    from ymd import diskcache
    old = tmp_path / "a.part"; old.write_bytes(b"x"); os.utime(old, (1, 1))
    (tmp_path / "b.part").write_bytes(b"x" * 15)
    (tmp_path / "c.mp3").write_bytes(b"x" * 10)
    diskcache.trim(tmp_path, limit=20)
    assert not old.exists() and not (tmp_path / "c.mp3").exists() and (tmp_path / "b.part").exists()


# --- paginated sources ---


async def test_likes_first_page_then_more():
    p, api, mpv, n = make(likes=50)
    await p.start_likes()
    assert len(api.tracks_calls) == 1 and len(api.tracks_calls[0]) == 20 and len(p.queue) == 20
    assert p.state()["has_more"] is True and p.state()["loading"] is False
    await p.more(); await p.more()
    assert len(p.queue) == 50 and p.state()["has_more"] is False
    assert [len(c) for c in api.tracks_calls] == [20, 20, 10]
    await p.more()
    assert len(api.tracks_calls) == 3


async def test_source_switch_notifies_before_fetch():
    p, api, mpv, n = make(likes=50)
    await p.start_likes()
    seen = []
    orig = api.tracks
    async def spy(ids):
        seen.append((len(n), p.state()["loading"], list(p.queue))); return await orig(ids)
    api.tracks = spy
    p.likes_page1 = None
    before = len(n)
    await p.start_likes()
    assert seen[0][0] > before and seen[0][1] is True and seen[0][2] == []


async def test_back_to_likes_reuses_first_page():
    p, api, mpv, _ = make(likes=50)
    await p.start_likes(); await p.start_wave(None)
    api.tracks_calls.clear()
    await p.start_likes()
    assert api.tracks_calls == [] and len(p.queue) == 20


async def test_auto_advance_loads_next_page():
    p, api, mpv, _ = make(likes=50)
    await p.start_likes(); await p.play(19); await p.settle()
    assert len(p.queue) == 40 and p.loaded == [18, 19, 20]


async def test_like_updates_ids_and_offset():
    p, api, mpv, _ = make(likes=50)
    await p.start_likes(); await p.play(0); await p.settle()
    off = p.like_off
    api.liked_add = ["0"]
    await p.like()
    assert p.like_ids[0] == "1" and "0" not in p.like_ids   # was liked: removed
    assert p.like_off == off - 1


async def test_wave_more_and_search_more():
    p, api, mpv, _ = make()
    await p.start_wave(None)
    assert p.state()["has_more"] is True
    await p.more()
    assert len(p.queue) == 10
    s = NS(results=[NS(**vars(track(900 + i))) for i in range(2)], total=3)
    p2, api2, _m, _n = make(search_tracks=s)
    await p2.search("x")
    assert p2.state()["has_more"] is True
    await p2.more()
    assert len(p2.results) == 4 and api2.searched[-1] == ("x", "track", 1)


# --- audible track survives a source switch ---


async def test_source_switch_keeps_audible_track():
    p, api, mpv, _ = make()
    await likes(p)
    await p.start_wave(None)
    s = p.state()
    assert s["track"]["title"] == "t0" and s["playing"] is True and s["index"] == -1
    await p.seek(20)
    assert ("seek", 20, "absolute") in mpv.calls
    api.liked_add = ["0"]
    await p.like()
    assert s["track"]["liked"] is True and p.state()["track"]["liked"] is False   # acted on t0, not the queue


async def test_dislike_targets_audible_track():
    p, api, mpv, _ = make()
    await likes(p)
    await p.start_wave(None)
    await p.dislike()
    assert api.disliked == ["0"] and mpv.calls[-1] == ("playlist-next",)


# --- fix round 2 ---


async def test_stop_then_toggle_resumes_audible_track():
    p, api, mpv, _ = make()
    await likes(p); await p.play(2); await p.settle()
    await p.start_wave(None)                 # browsing another source
    await p.stop()
    await p.toggle(); await p.settle()
    assert mpv.playlist == ["url1", "url2", "url3"] and p.playing is True and p.state()["track"]["id"] == "2"
    mpv.calls.clear()
    await p.toggle()
    assert mpv.calls == [("get_property", "idle-active"), ("cycle", "pause")]


async def test_eof_when_neighbour_arrived_after_idle():
    p, api, mpv, _ = make()
    await likes(p)                            # loaded [0, 1]
    mpv.playlist = []                         # mpv hit EOF and went idle before the neighbour was appended
    await p.on_event({"event": "end-file", "reason": "eof"})
    assert p.index == 1 and mpv.playlist[0] == "url1"


async def test_station_more_is_capped_and_search_empty_page_ends():
    p, api, mpv, _ = make()
    await p.start_wave(None)
    p.queue.extend([p.queue[0]] * 100)
    assert p.state()["has_more"] is False
    s = NS(results=[track(900)], total=5)
    p2, api2, _m, _n = make(search_tracks=s)
    await p2.search("x")
    api2.search_tracks.results = []
    await p2.more()
    assert p2.state()["has_more"] is False


# --- v3: the browsed list is not the play queue ---


async def test_browsing_another_source_keeps_play_queue():
    p, api, mpv, _ = make(likes=10)
    await p.start_likes(); await p.play(3); await p.settle()
    calls = len(mpv.calls)
    await p.start_wave(None); await p.settle()
    assert mpv.calls[calls:] == [] and p.loaded == [2, 3, 4]          # switching sources never touches mpv
    assert p.state()["index"] == -1 and p.state()["track"]["id"] == "3"
    assert p.state()["source"]["type"] == "wave" and p.state()["play_source"]["type"] == "likes"
    await p.on_event({"event": "end-file", "reason": "eof"})
    await pos(p, 2)                                                   # mpv went on to its next entry
    assert p.now["id"] == "4" and mpv.playlist == ["url3", "url4", "url5"] and p.loaded == [3, 4, 5]
    assert p.state()["index"] == -1 and p.queue[0]["id"] == "100"      # still browsing the wave
    await p.start_likes()
    assert p.state()["index"] == 4 and p.queue is p.play_queue         # back to likes: marker on the audible row


async def test_eof_at_window_edge_while_browsing_plays_from_play_queue():
    p, api, mpv, _ = make(likes=10)
    await p.start_likes()
    async def boom(*a, **k): raise OSError("x")
    p._append_next = boom
    await p.play(3); await p.settle()
    await p.start_wave(None)
    await p.on_event({"event": "end-file", "reason": "eof"})
    assert p.now["id"] == "4" and mpv.playlist == ["url4"] and p.state()["index"] == -1


async def test_next_prev_while_browsing_move_within_play_queue():
    p, api, mpv, _ = make(likes=10)
    await p.start_likes(); await p.play(3); await p.settle()
    await p.start_wave(None)
    await p.next(); await pos(p, mpv.pos)
    assert p.now["id"] == "4"
    await p.prev(); await pos(p, mpv.pos)
    await p.prev(); await pos(p, mpv.pos)
    assert p.now["id"] == "2" and p.queue[0]["id"] == "100" and p.state()["index"] == -1
    await p.dislike(); await pos(p, mpv.pos)
    assert api.disliked == ["2"] and p.now["id"] == "3"


async def test_playing_a_browsed_row_switches_play_queue():
    p, api, mpv, _ = make(likes=10)
    await p.start_likes(); await p.play(3); await p.settle()
    await p.start_wave(None)
    await p.play(1); await p.settle()
    assert p.play_queue is p.queue and p.now["id"] == "101" and p.state()["index"] == 1
    assert p.state()["play_source"]["type"] == "wave" and mpv.playlist == ["url100", "url101", "url102"]
    assert [f[1] for f in api.feedback] == ["radioStarted", "trackStarted"]
    await p.start_likes()
    assert p.state()["index"] == -1 and p.now["id"] == "101"


async def test_failed_play_of_browsed_row_keeps_play_queue():
    p, api, mpv, _ = make(likes=10)
    await p.start_likes(); await p.play(3); await p.settle()
    await p.start_wave(None)
    async def boom(*a, **k): raise OSError("net")
    api.tracks_download_info = boom
    with pytest.raises(OSError):
        await p.play(0)
    assert p.play_source["type"] == "likes" and p.now["id"] == "3" and p.index == 3
    assert p.state()["index"] == -1


async def test_play_queue_keeps_its_mood_while_another_is_browsed():
    p, api, mpv, _ = make()
    await wave(p, "calm")
    await p.start_wave("fun")
    assert [s[1] for s in api.settings] == ["calm", "fun"]
    for i in range(1, 4):
        await pos(p, min(i, 2))                                       # the play queue refills
    assert [s[1] for s in api.settings] == ["calm", "fun", "calm"]
    await p.start_wave("calm")
    assert p.queue is p.play_queue and p.state()["index"] == p.index
