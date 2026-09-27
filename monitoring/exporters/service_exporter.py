#!/usr/bin/env python3
"""Lightweight Prometheus exporter: Pi-hole v6 API + AmneziaWG (awg show dump)."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import geoip_names

LISTEN = os.environ.get("EXPORTER_LISTEN", "0.0.0.0:9101")
PIHOLE_URL = os.environ.get("PIHOLE_URL", "http://127.0.0.1:61864").rstrip("/")
PIHOLE_PASSWORD = os.environ.get("PIHOLE_PASSWORD", "")
AWG_CONTAINER = os.environ.get("AWG_CONTAINER", "amnezia-awg2")
AWG_IFACE = os.environ.get("AWG_IFACE", "awg0")
COLLECT_INTERVAL_SEC = float(os.environ.get("COLLECT_INTERVAL_SEC", "15"))

_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists() and not PIHOLE_PASSWORD:
    for line in _env_file.read_text().splitlines():
        if line.startswith("FTLCONF_webserver_api_password="):
            PIHOLE_PASSWORD = line.split("=", 1)[1].strip()

_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "body": b"# HELP service_exporter_up Exporter process up\n# TYPE service_exporter_up gauge\nservice_exporter_up 1\n"}
_sid: str | None = None
_sid_exp = 0.0

# Pi-hole v6 /api/stats/summary returns 24h-windowed values; feeding them to
# Prometheus as counters makes rate() spike to value/range on every window slide.
# True monotonic counters are built from /api/history 10-min buckets instead.
_HIST_KEYS = ("total", "blocked", "cached", "forwarded")
_hist_state: dict = {"last_ts": None, "cum": {k: 0.0 for k in _HIST_KEYS}}
# Delta-accumulators for windowed values that have no bucket API (per upstream/type/status).
_mono_state: dict = {}


def _esc(label: str) -> str:
    return (
        label.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def _metric(lines: list[str], name: str, value, labels: dict | None = None, help_text: str = "", typ: str = "gauge"):
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {typ}")
    if labels:
        lab = ",".join(f'{k}="{_esc(str(v))}"' for k, v in labels.items())
        lines.append(f"{name}{{{lab}}} {value}")
    else:
        lines.append(f"{name} {value}")


def _http_json(method: str, path: str, body: dict | None = None, sid: str | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{PIHOLE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if sid:
        req.add_header("X-FTL-SID", sid)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def _pihole_sid() -> str | None:
    global _sid, _sid_exp
    now = time.time()
    if _sid and now < _sid_exp - 60:
        return _sid
    if not PIHOLE_PASSWORD:
        return None
    try:
        data = _http_json("POST", "/api/auth", {"password": PIHOLE_PASSWORD})
        _sid = data["session"]["sid"]
        _sid_exp = now + float(data["session"].get("validity", 1800))
        return _sid
    except Exception:
        _sid = None
        return None


def _mono(name: str, labels: tuple, value: float) -> float:
    """Accumulate a windowed gauge into a monotonic counter.

    Keeps the last emitted total and adds only positive deltas; a downward
    jump (window slide / restart) does not decrement the series.
    """
    key = (name, labels)
    prev = _mono_state.get(key)
    tot = _mono_state.get(("__tot__", key), 0.0)
    if prev is None:
        delta = 0.0  # first observation only establishes the baseline
    else:
        delta = max(0.0, float(value) - prev)
    _mono_state[key] = float(value)
    _mono_state[("__tot__", key)] = tot + delta
    return tot + delta


def collect_pihole(lines: list[str]) -> None:
    sid = _pihole_sid()
    if not sid:
        _metric(lines, "pihole_up", 0, help_text="Pi-hole API reachable", typ="gauge")
        return
    try:
        summary = _http_json("GET", "/api/stats/summary", sid=sid)
        metrics = _http_json("GET", "/api/info/metrics", sid=sid)
        upstreams = _http_json("GET", "/api/stats/upstreams", sid=sid)
        top_clients = _http_json("GET", "/api/stats/top_clients", sid=sid)
        top_domains = _http_json("GET", "/api/stats/top_domains", sid=sid)
        ftl = _http_json("GET", "/api/info/ftl", sid=sid)
        history = _http_json("GET", "/api/history", sid=sid).get("history") or []
    except Exception:
        _metric(lines, "pihole_up", 0, help_text="Pi-hole API reachable", typ="gauge")
        return

    _metric(lines, "pihole_up", 1, help_text="Pi-hole API reachable", typ="gauge")
    q = summary.get("queries", {})
    c = summary.get("clients", {})
    g = summary.get("gravity", {})

    # Build true monotonic counters from 10-min history buckets (prometheus needs
    # counters that never decrease; summary values slide with the 24h window).
    buckets = sorted(history, key=lambda b: b.get("timestamp") or 0)
    for b in buckets:
        ts = b.get("timestamp")
        if ts is None or ts <= (_hist_state["last_ts"] or 0):
            continue
        for k in _HIST_KEYS:
            _hist_state["cum"][k] += float(b.get(k) or 0)
        _hist_state["last_ts"] = ts
    cum = _hist_state["cum"]

    _metric(lines, "pihole_queries_total", cum["total"], help_text="DNS queries total (monotonic, from history buckets)", typ="counter")
    _metric(lines, "pihole_queries_blocked_total", cum["blocked"], help_text="Blocked queries (monotonic)", typ="counter")
    _metric(lines, "pihole_queries_cached_total", cum["cached"], help_text="Cached queries (monotonic)", typ="counter")
    _metric(lines, "pihole_queries_forwarded_total", cum["forwarded"], help_text="Forwarded queries (monotonic)", typ="counter")
    # Windowed gauges keep their original names/semantics
    _metric(lines, "pihole_queries_24h", q.get("total", 0), help_text="Queries in last 24h (windowed gauge)")
    _metric(lines, "pihole_queries_unique_domains", q.get("unique_domains", 0), help_text="Unique domains in window")
    _metric(lines, "pihole_percent_blocked", q.get("percent_blocked", 0), help_text="Percent blocked in window")
    _metric(lines, "pihole_query_frequency", q.get("frequency", 0), help_text="Queries per second (FTL estimate)")
    _metric(lines, "pihole_clients_active", c.get("active", 0), help_text="Active clients")
    _metric(lines, "pihole_clients_total", c.get("total", 0), help_text="Known clients")
    _metric(lines, "pihole_gravity_domains", g.get("domains_being_blocked", 0), help_text="Gravity domains")
    _metric(lines, "pihole_gravity_last_update", g.get("last_update", 0), help_text="Gravity last update unix")
    denom = float(cum["cached"]) + float(cum["forwarded"])
    hit = (float(cum["cached"]) / denom) if denom else 0.0
    _metric(lines, "pihole_cache_hit_ratio", hit, help_text="Cached / (cached+forwarded), monotonic basis")

    for t, v in (q.get("types") or {}).items():
        _metric(lines, "pihole_query_types_total", _mono("pihole_query_types_total", (t,), v), {"type": t}, typ="counter")
    for s, v in (q.get("status") or {}).items():
        _metric(lines, "pihole_query_status_total", _mono("pihole_query_status_total", (s,), v), {"status": s}, typ="counter")
    for r, v in (q.get("replies") or {}).items():
        _metric(lines, "pihole_query_replies_total", v, {"reply": r}, typ="counter")

    dns = (metrics.get("metrics") or {}).get("dns") or {}
    cache = dns.get("cache") or {}
    _metric(lines, "pihole_dns_cache_size", cache.get("size", 0), help_text="DNS cache size")
    _metric(lines, "pihole_dns_cache_inserted_total", cache.get("inserted", 0), help_text="Cache inserts", typ="counter")
    _metric(lines, "pihole_dns_cache_evicted_total", cache.get("evicted", 0), help_text="Cache evictions", typ="counter")
    _metric(lines, "pihole_dns_cache_expired_total", cache.get("expired", 0), help_text="Cache expired", typ="counter")
    for item in cache.get("content") or []:
        name = item.get("name", "OTHER")
        cnt = item.get("count") or {}
        _metric(lines, "pihole_dns_cache_entries", cnt.get("valid", 0), {"type": name, "state": "valid"})
        _metric(lines, "pihole_dns_cache_entries", cnt.get("stale", 0), {"type": name, "state": "stale"})

    replies = dns.get("replies") or {}
    for k, v in replies.items():
        _metric(lines, "pihole_dns_reply_path_total", v, {"path": k}, typ="counter")

    for u in upstreams.get("upstreams") or []:
        ip = u.get("ip") or "unknown"
        name = u.get("name") or ip
        _metric(lines, "pihole_upstream_queries_total", _mono("pihole_upstream_queries_total", (ip, name), u.get("count", 0)), {"upstream": ip, "name": name}, typ="counter")
        stats = u.get("statistics") or {}
        _metric(lines, "pihole_upstream_response_seconds", stats.get("response", 0), {"upstream": ip, "name": name})

    for cl in (top_clients.get("clients") or [])[:15]:
        cip = cl.get("ip") or "unknown"
        resolved = geoip_names.resolve_client(cip, cl.get("name") or "")
        _metric(
            lines,
            "pihole_top_client_queries",
            cl.get("count", 0),
            {
                "client": cip,
                "name": resolved.get("name") or cip,
                "role": resolved.get("role") or "",
                "peer": resolved.get("peer") or "",
                "country": resolved.get("countryCode") or "",
                "city": resolved.get("city") or "",
                "geo": resolved.get("geo") or "",
                "endpoint_ip": resolved.get("endpoint_ip") or "",
            },
        )
    for d in (top_domains.get("domains") or [])[:15]:
        _metric(lines, "pihole_top_domain_queries", d.get("count", 0), {"domain": d.get("domain") or "unknown"})

    fi = ftl.get("ftl") or {}
    _metric(lines, "pihole_ftl_cpu_percent", fi.get("%cpu", 0), help_text="FTL CPU percent")
    _metric(lines, "pihole_ftl_mem_percent", fi.get("%mem", 0), help_text="FTL memory percent")
    _metric(lines, "pihole_ftl_uptime_seconds", (fi.get("uptime") or 0) / 1000.0 if fi.get("uptime", 0) > 1e6 else fi.get("uptime", 0))
    db = fi.get("database") or {}
    _metric(lines, "pihole_lists_total", db.get("lists", 0), help_text="Blocklists count")


def collect_awg(lines: list[str]) -> None:
    # WireGuard/AmneziaWG practices:
    # - online = handshake age <= 180s (3m keepalive window)
    # - stale = 180s..900s (half-dead tunnel)
    # - never = handshake == 0
    ONLINE_MAX = 180
    STALE_MAX = 900
    names = {}  # Names are sourced from Amnezia clientsTable by public key.
    by_pubkey = geoip_names.load_clients_table(AWG_CONTAINER)
    geoip_names.AWG_DIRECTORY.clear()

    try:
        out = subprocess.check_output(
            ["docker", "exec", AWG_CONTAINER, "awg", "show", AWG_IFACE, "dump"],
            text=True,
            timeout=8,
        )
    except Exception:
        _metric(lines, "awg_up", 0, help_text="AmneziaWG interface scrape OK", typ="gauge")
        return

    rows = [r for r in out.strip().splitlines() if r.strip()]
    if not rows:
        _metric(lines, "awg_up", 0, help_text="AmneziaWG interface scrape OK", typ="gauge")
        return

    _metric(lines, "awg_up", 1, help_text="AmneziaWG interface scrape OK", typ="gauge")
    iface = rows[0].split("\t")
    if len(iface) >= 3 and iface[2].isdigit():
        _metric(lines, "awg_listen_port", int(iface[2]), help_text="AWG listen port")

    now = int(time.time())
    peers_total = peers_online = peers_stale = peers_never = 0
    rx_sum = tx_sum = 0
    parsed = []

    for row in rows[1:]:
        p = row.split("\t")
        if len(p) < 8:
            continue
        peers_total += 1
        pubkey = p[0]
        endpoint = "" if p[2] in ("(none)", "(null)", "") else p[2]
        allowed = p[3].split(",")[0]
        peer = allowed.split("/")[0] if allowed else pubkey[:8]
        friendly = geoip_names.peer_name(peer, names, pubkey=pubkey, by_pubkey=by_pubkey)
        endpoint_ip = endpoint.rsplit(":", 1)[0] if endpoint else ""
        try:
            handshake = int(p[4])
        except ValueError:
            handshake = 0
        try:
            rx = int(p[5])
            tx = int(p[6])
        except ValueError:
            rx = tx = 0
        rx_sum += rx
        tx_sum += tx

        if handshake <= 0:
            peers_never += 1
            online = stale = 0
            age = -1
        else:
            age = now - handshake
            online = 1 if age <= ONLINE_MAX else 0
            stale = 1 if ONLINE_MAX < age <= STALE_MAX else 0
            peers_online += online
            peers_stale += stale

        parsed.append(
            {
                "peer": peer,
                "friendly": friendly,
                "allowed": allowed,
                "pubkey": pubkey[:16],
                "endpoint": endpoint or "none",
                "endpoint_ip": endpoint_ip,
                "online": online,
                "stale": stale,
                "age": age,
                "handshake": handshake,
                "rx": rx,
                "tx": tx,
            }
        )

    geos = geoip_names.geo_lookup([p["endpoint_ip"] for p in parsed if p["endpoint_ip"]])

    for p in parsed:
        g = geos.get(p["endpoint_ip"], {})
        labels = {"peer": p["peer"], "friendly_name": p["friendly"]}
        _metric(lines, "awg_peer_online", p["online"], labels, typ="gauge")
        _metric(lines, "awg_peer_stale", p["stale"], labels, typ="gauge")
        _metric(lines, "awg_peer_handshake_age_seconds", p["age"], labels, typ="gauge")
        _metric(lines, "awg_peer_handshake_unixtime", p["handshake"], labels, typ="gauge")
        _metric(lines, "awg_peer_receive_bytes_total", p["rx"], labels, typ="counter")
        _metric(lines, "awg_peer_transmit_bytes_total", p["tx"], labels, typ="counter")

        inv = {
            "peer": p["peer"],
            "friendly_name": p["friendly"],
            "allowed_ips": p["allowed"],
            "public_key": p["pubkey"],
            "endpoint": p["endpoint"],
            "endpoint_ip": p["endpoint_ip"] or "none",
            "country": g.get("countryCode") or "",
            "city": g.get("city") or "",
            "isp": g.get("isp") or "",
            "geo": g.get("geo") or "",
        }
        _metric(lines, "awg_peer_info", 1, inv, typ="gauge")

        # directory for Pi-hole enrichment + ip_info metrics
        tunnel_meta = {
            "name": p["friendly"],
            "role": "awg-tunnel",
            "peer": p["peer"],
            "endpoint_ip": p["endpoint_ip"],
            "country": g.get("country") or "",
            "countryCode": g.get("countryCode") or "",
            "city": g.get("city") or "",
            "isp": g.get("isp") or "",
            "geo": g.get("geo") or "",
        }
        geoip_names.AWG_DIRECTORY[p["peer"]] = tunnel_meta
        _metric(
            lines,
            "ip_info",
            1,
            {
                "ip": p["peer"],
                "name": p["friendly"],
                "role": "awg-tunnel",
                "peer": p["peer"],
                "country": g.get("countryCode") or "",
                "city": g.get("city") or "",
                "isp": g.get("isp") or "",
                "geo": g.get("geo") or "",
            },
            typ="gauge",
        )
        if p["endpoint_ip"] and geoip_names.is_public_ip(p["endpoint_ip"]):
            geoip_names.AWG_DIRECTORY[p["endpoint_ip"]] = {
                "name": p["friendly"],
                "role": "awg-endpoint",
                "peer": p["peer"],
                "endpoint_ip": p["endpoint_ip"],
                "country": g.get("country") or "",
                "countryCode": g.get("countryCode") or "",
                "city": g.get("city") or "",
                "isp": g.get("isp") or "",
                "geo": g.get("geo") or "",
            }
            _metric(
                lines,
                "ip_info",
                1,
                {
                    "ip": p["endpoint_ip"],
                    "name": p["friendly"],
                    "role": "awg-endpoint",
                    "peer": p["peer"],
                    "country": g.get("countryCode") or "",
                    "city": g.get("city") or "",
                    "isp": g.get("isp") or "",
                    "geo": g.get("geo") or "",
                },
                typ="gauge",
            )

    _metric(lines, "awg_peers_total", peers_total, help_text="Configured peers")
    _metric(lines, "awg_peers_online", peers_online, help_text="Peers with handshake <= 180s")
    _metric(lines, "awg_peers_stale", peers_stale, help_text="Peers with handshake 180-900s")
    _metric(lines, "awg_peers_never_connected", peers_never, help_text="Peers with no handshake")
    _metric(lines, "awg_peers_online_ratio", (peers_online / peers_total) if peers_total else 0, help_text="Online peers / total")
    _metric(lines, "awg_receive_bytes_total", rx_sum, help_text="Interface RX bytes sum", typ="counter")
    _metric(lines, "awg_transmit_bytes_total", tx_sum, help_text="Interface TX bytes sum", typ="counter")


def _parse_docker_size(s: str) -> float:
    s = (s or "0").strip()
    if not s or s == "0":
        return 0.0
    units = {"B": 1, "kB": 1e3, "KB": 1e3, "KiB": 1024, "MB": 1e6, "MiB": 1024**2, "GB": 1e9, "GiB": 1024**3, "TB": 1e12, "TiB": 1024**4}
    for u in ("TiB", "GiB", "MiB", "KiB", "TB", "GB", "MB", "kB", "KB", "B"):
        if s.endswith(u):
            return float(s[: -len(u)]) * units[u]
    return float(s)


def collect_container_health(lines: list[str]) -> None:
    wanted = [
        "pihole",
        "pihole-webproxy",
        "amnezia-awg2",
        "vk-turn-proxy",
        "prometheus",
        "grafana",
        "node-exporter",
        "service-exporter",
        "x-ui",
    ]
    try:
        out = subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.State}}"],
            text=True,
            timeout=8,
        )
    except Exception:
        return
    seen = {}
    for row in out.splitlines():
        parts = row.split("\t")
        if len(parts) >= 3:
            seen[parts[0]] = parts[2]
    # x-ui may be intentionally stopped — do not count as outage
    expected = [n for n in wanted if n != "x-ui"]
    down = 0
    for name in wanted:
        state = seen.get(name, "missing")
        up = 1 if state == "running" else 0
        if name in expected and up == 0:
            down += 1
        _metric(lines, "container_service_up", up, {"name": name}, typ="gauge")
    _metric(lines, "container_services_down", down, help_text="Expected services not running (excl. x-ui)")

    # docker stats — reliable container CPU/RAM when cAdvisor fails
    try:
        stats = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}|{{.BlockIO}}|{{.PIDs}}"],
            text=True,
            timeout=8,
        )
    except Exception:
        return
    for row in stats.splitlines():
        parts = row.split("|")
        if len(parts) < 6:
            continue
        name, cpu, mem, netio, blkio, pids = parts
        try:
            cpu_v = float(cpu.strip().rstrip("%") or 0)
        except ValueError:
            cpu_v = 0.0
        mem_used = mem_limit = 0.0
        if "/" in mem:
            a, b = mem.split("/", 1)
            mem_used = _parse_docker_size(a.strip())
            mem_limit = _parse_docker_size(b.strip())
        rx = tx = 0.0
        if "/" in netio:
            a, b = netio.split("/", 1)
            rx = _parse_docker_size(a.strip())
            tx = _parse_docker_size(b.strip())
        try:
            pids_v = int(pids.strip() or 0)
        except ValueError:
            pids_v = 0
        labels = {"name": name}
        _metric(lines, "docker_container_cpu_percent", cpu_v, labels)
        _metric(lines, "docker_container_memory_bytes", mem_used, labels)
        _metric(lines, "docker_container_memory_limit_bytes", mem_limit, labels)
        _metric(lines, "docker_container_network_rx_bytes", rx, labels, typ="gauge")
        _metric(lines, "docker_container_network_tx_bytes", tx, labels, typ="gauge")
        _metric(lines, "docker_container_pids", pids_v, labels)


def render() -> bytes:
    lines: list[str] = []
    # AWG first — fills geoip_names.AWG_DIRECTORY for Pi-hole enrichment
    t0 = time.time()
    collect_awg(lines)
    collect_pihole(lines)
    collect_container_health(lines)
    elapsed = time.time() - t0
    _metric(lines, "service_exporter_collect_seconds", round(elapsed, 3), help_text="Last full collect duration")
    _metric(lines, "service_exporter_up", 1, help_text="Exporter process up")
    lines.append("")
    return ("\n".join(lines)).encode()


def _collector_loop() -> None:
    while True:
        try:
            body = render()
            with _lock:
                _cache["body"] = body
                _cache["ts"] = time.time()
        except Exception as exc:
            print(f"collect error: {exc}", flush=True)
        time.sleep(COLLECT_INTERVAL_SEC)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        with _lock:
            body = _cache["body"]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass


def main():
    # Warm cache once before accepting scrapes
    try:
        body = render()
        with _lock:
            _cache["body"] = body
            _cache["ts"] = time.time()
    except Exception as exc:
        print(f"initial collect error: {exc}", flush=True)

    threading.Thread(target=_collector_loop, name="collector", daemon=True).start()
    host, port_s = LISTEN.rsplit(":", 1)
    server = ThreadingHTTPServer((host, int(port_s)), Handler)
    print(f"service-exporter listening on {LISTEN}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
