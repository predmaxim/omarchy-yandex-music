from types import SimpleNamespace as NS
from ymd import tracks

def track(id_=1, album=7, title="Кукушка", artists=("Кино",), cover="avatars.yandex.net/x/%%"):
    return NS(id=id_, track_id=f"{id_}:{album}", title=title,
              artists_name=lambda: list(artists),
              albums=[NS(title="Звезда")], cover_uri=cover)

def test_info():
    assert tracks.info(track()) == {"id": "1", "fid": "1:7", "title": "Кукушка", "artists": "Кино",
                                    "album": "Звезда", "cover": "https://avatars.yandex.net/x/200x200"}

def test_info_without_album_and_cover():
    t = track(cover=None); t.albums = []
    assert tracks.info(t)["album"] == "" and tracks.info(t)["cover"] == ""

def test_best_link_prefers_full_mp3_highest_bitrate():
    infos = [NS(codec="mp3", bitrate_in_kbps=320, preview=True, direct_link="p"),
             NS(codec="aac", bitrate_in_kbps=256, preview=False, direct_link="a"),
             NS(codec="mp3", bitrate_in_kbps=192, preview=False, direct_link="m192"),
             NS(codec="mp3", bitrate_in_kbps=320, preview=False, direct_link="m320")]
    assert tracks.best_link(infos) == "m320"

def test_best_link_falls_back_to_any_full():
    assert tracks.best_link([NS(codec="aac", bitrate_in_kbps=64, preview=False, direct_link="a")]) == "a"
    assert tracks.best_link([]) is None
