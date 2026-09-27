"""IP naming (from AWG peers) + GeoIP lookup with disk cache."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GEO_CACHE_PATH = BASE_DIR / "geoip-cache.json"
PEERS_PATH = BASE_DIR / "awg-peers.json"
GEO_TTL_SEC = int(os.environ.get("GEOIP_CACHE_TTL", "86400"))

# Filled each AWG scrape: public/tunnel IP -> meta
AWG_DIRECTORY: dict[str, dict] = {}


def load_peer_names() -> dict[str, str]:
    """Static override map: tunnel IP -> display name (optional)."""
    try:
        raw = json.loads(PEERS_PATH.read_text())
    except Exception:
        return {}
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[k] = str(v.get("name") or k)
        else:
            out[k] = str(v)
    return out


def load_clients_table(container: str = "amnezia-awg2") -> dict[str, str]:
    """pubkey -> clientName from Amnezia clientsTable inside AWG container."""
    path = os.environ.get("AWG_CLIENTS_TABLE", "/opt/amnezia/awg/clientsTable")
    try:
        raw = subprocess.check_output(
            ["docker", "exec", container, "cat", path],
            text=True,
            timeout=5,
        )
        rows = json.loads(raw)
    except Exception:
        return {}
    out: dict[str, str] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        pk = str(row.get("clientId") or "").strip()
        ud = row.get("userData") or {}
        name = str((ud.get("clientName") if isinstance(ud, dict) else "") or "").strip()
        if pk and name:
            out[pk] = name
    return out


def peer_name(
    peer_ip: str,
    names: dict[str, str] | None = None,
    pubkey: str = "",
    by_pubkey: dict[str, str] | None = None,
) -> str:
    """Prefer static IP override, then Amnezia clientName by pubkey, else IP."""
    names = names if names is not None else load_peer_names()
    if peer_ip in names and names[peer_ip] and not str(names[peer_ip]).startswith("peer-"):
        return names[peer_ip]
    if by_pubkey and pubkey:
        for key in (pubkey, pubkey[:16]):
            if key in by_pubkey:
                return by_pubkey[key]
        # full-key match if dump truncated
        for pk, nm in by_pubkey.items():
            if pubkey and (pk.startswith(pubkey) or pubkey.startswith(pk[:16])):
                return nm
    if peer_ip in names:
        return names[peer_ip]
    return peer_ip


def _load_geo_cache() -> dict:
    try:
        return json.loads(GEO_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_geo_cache(cache: dict) -> None:
    try:
        GEO_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    except Exception:
        pass


def is_public_ip(ip: str) -> bool:
    if not ip or ":" in ip:
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return False
    a, b = nums[0], nums[1]
    if a == 10 or a == 127 or a >= 224:
        return False
    if a == 192 and b == 168:
        return False
    if a == 172 and 16 <= b <= 31:
        return False
    if a == 169 and b == 254:
        return False
    return True


def geo_lookup(ips: list[str]) -> dict[str, dict]:
    """ip-api.com batch + on-disk cache. No MaxMind account required."""
    cache = _load_geo_cache()
    now = time.time()
    out: dict[str, dict] = {}
    miss: list[str] = []
    empty = {"country": "", "countryCode": "", "region": "", "city": "", "isp": "", "as": "", "geo": ""}

    for ip in sorted({i for i in ips if i}):
        if not is_public_ip(ip):
            out[ip] = dict(empty)
            continue
        ent = cache.get(ip)
        if ent and now - float(ent.get("ts", 0)) < GEO_TTL_SEC:
            out[ip] = ent
        else:
            miss.append(ip)

    if miss:
        try:
            req = urllib.request.Request(
                "http://ip-api.com/batch?fields=status,message,country,countryCode,regionName,city,isp,org,as,query",
                data=json.dumps([{"query": i} for i in miss]).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            rows = json.load(urllib.request.urlopen(req, timeout=10))
            for row in rows:
                ip = row.get("query") or ""
                if row.get("status") != "success":
                    out[ip] = dict(empty)
                    continue
                city = row.get("city") or ""
                cc = row.get("countryCode") or ""
                country = row.get("country") or ""
                geo = ", ".join(x for x in (city, cc or country) if x)
                ent = {
                    "ts": now,
                    "country": country,
                    "countryCode": cc,
                    "region": row.get("regionName") or "",
                    "city": city,
                    "isp": row.get("isp") or row.get("org") or "",
                    "as": row.get("as") or "",
                    "geo": geo,
                }
                cache[ip] = ent
                out[ip] = ent
            _save_geo_cache(cache)
        except Exception:
            for ip in miss:
                out.setdefault(ip, dict(empty))
    return out


_docker_map_cache: dict[str, str] = {}
_docker_map_ts = 0.0
DOCKER_MAP_TTL = int(os.environ.get("DOCKER_NAME_CACHE_TTL", "120"))


def docker_name_map(force: bool = False) -> dict[str, str]:
    global _docker_map_cache, _docker_map_ts
    now = time.time()
    if not force and _docker_map_cache and now - _docker_map_ts < DOCKER_MAP_TTL:
        return _docker_map_cache

    mapping: dict[str, str] = {
        "127.0.0.1": "localhost",
        "::1": "localhost",
        "::": "pi.hole",
    }
    try:
        nets = subprocess.check_output(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            text=True,
            timeout=5,
        ).splitlines()
        for net in nets:
            if not net or net in ("none", "host"):
                continue
            raw = subprocess.check_output(
                [
                    "docker",
                    "network",
                    "inspect",
                    net,
                    "--format",
                    '{{range .Containers}}{{.Name}} {{.IPv4Address}}\n{{end}}',
                ],
                text=True,
                timeout=5,
            )
            for line in raw.splitlines():
                line = line.strip()
                if " " not in line or "/" not in line:
                    continue
                name, cidr = line.split(" ", 1)
                ip = cidr.split("/")[0]
                mapping[ip] = name
    except Exception:
        pass
    # Prefer human aliases for this host's DNS/VPN path (override raw docker names)
    mapping.update(
        {
            "172.29.172.1": "docker-gateway",
            "172.29.172.2": "pihole-webproxy",
            "172.29.172.3": "amnezia-awg2 (VPN NAT)",
            "172.29.172.10": "pihole",
        }
    )
    _docker_map_cache = mapping
    _docker_map_ts = now
    return mapping


def resolve_client(ip: str, pihole_name: str = "") -> dict:
    """Resolve display name / geo / role for any client IP."""
    docker = docker_name_map()
    meta = {
        "ip": ip,
        "name": pihole_name or ip,
        "role": "unknown",
        "peer": "",
        "country": "",
        "countryCode": "",
        "city": "",
        "isp": "",
        "geo": "",
        "endpoint_ip": "",
    }
    if ip in AWG_DIRECTORY:
        d = AWG_DIRECTORY[ip]
        meta.update({k: d.get(k, meta.get(k)) for k in meta if k in d or k in ("name", "role", "peer", "country", "countryCode", "city", "isp", "geo", "endpoint_ip")})
        return meta
    if ip in docker:
        meta["name"] = docker[ip]
        meta["role"] = "docker"
        return meta
    if pihole_name:
        meta["name"] = pihole_name
        meta["role"] = "dns-client"
    return meta
