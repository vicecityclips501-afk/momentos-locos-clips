"""Acceso a la API de Twitch (Helix): juego, streamers y clips."""
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.twitch.tv/helix"


class Twitch:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=20,
        )
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def _get(self, path, params):
        r = requests.get(
            f"{API}/{path}",
            params=params,
            headers={"Client-Id": self.client_id, "Authorization": f"Bearer {self.token}"},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    def game_id(self, name: str) -> str:
        data = self._get("games", {"name": name})["data"]
        if not data:
            raise RuntimeError(f"Twitch no encuentra el juego '{name}'")
        return data[0]["id"]

    def user_ids(self, logins):
        ids = {}
        logins = [l.strip().lower() for l in logins if l.strip()]
        for i in range(0, len(logins), 100):
            chunk = logins[i:i + 100]
            for u in self._get("users", [("login", l) for l in chunk])["data"]:
                ids[u["login"]] = u["id"]
        return ids

    def _clips(self, params, pages=3):
        out, cursor = [], None
        for _ in range(pages):
            p = dict(params, first=100)
            if cursor:
                p["after"] = cursor
            res = self._get("clips", p)
            out.extend(res["data"])
            cursor = res.get("pagination", {}).get("cursor")
            if not cursor:
                break
        return out

    @staticmethod
    def _since(hours):
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def clips_de_streamer(self, broadcaster_id, game_id, hours):
        clips = self._clips({"broadcaster_id": broadcaster_id, "started_at": self._since(hours)}, pages=2)
        return [c for c in clips if c.get("game_id") == game_id]

    def clips_del_juego(self, game_id, hours, idioma=None):
        """Para DESCUBRIR streamers (no para publicar): clips más vistos del juego."""
        clips = self._clips({"game_id": game_id, "started_at": self._since(hours)}, pages=10)
        if idioma:
            clips = [c for c in clips if (c.get("language") or "").startswith(idioma)]
        return clips

    def directos(self, game_id, idioma, cuantos=30):
        """Streamers jugando ahora a ese juego en ese idioma, de más a menos espectadores."""
        res = self._get("streams", {"game_id": game_id, "language": idioma, "first": 100})["data"]
        return [(s["user_id"], s["user_login"]) for s in res[:cuantos]]
