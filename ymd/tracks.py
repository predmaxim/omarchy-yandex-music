"""Track objects of yandex-music-api -> plain dicts for the state line."""


def info(t) -> dict:
    return {"id": str(t.id), "fid": str(t.track_id), "title": t.title or "",
            "artists": ", ".join(t.artists_name()), "album": t.albums[0].title if t.albums else "",
            "cover": f"https://{t.cover_uri.replace('%%', '200x200')}" if t.cover_uri else ""}


def best_link(infos) -> str | None:
    full = [i for i in infos if not i.preview]
    full.sort(key=lambda i: (i.codec == "mp3", i.bitrate_in_kbps), reverse=True)
    return full[0].direct_link if full else None
