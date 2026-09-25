# -*- coding: utf8 -*-
"""
proxy_pool.py —— 免费代理池自愈模块（配合 mimotion 刷步数使用）

流程：
  1) fetch_archive() : 从 checker.net 拉取当天全部候选代理（原始 ip:port，约 1.8 万）
  2) grade()         : 一次性全部提交给 checker.net 打分测活，读 NDJSON 结果流，
                       得到"活着 + 评分 sc + 国家 cc"的代理，按分数从高到低排序
  3) xiaomi_reachable: 只对分数最高的前若干个，实测能否连通 api-user.huami.com
  4) build_pool()    : 编排以上步骤，产出一个"小米可用"的 http 代理 URL 列表

要点：
  - checker.net 打分是拿通用站点测的，只代表代理"活着/快/匿名"，不代表能连小米，
    所以第 3 步必须对 api-user.huami.com 做真实连通性筛选。
  - 全程不需要 API key；单次 check 最多 3 万个，1.8 万个约 20~30 秒出全量结果。
"""
import concurrent.futures
import json
import secrets
import time
import urllib.request

CHECKER_BASE = "https://checker.net"
XIAOMI_PROBE = "https://api-user.huami.com/"  # 正常返回 404 即算可达
_HDRS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://checker.net",
    "Referer": "https://checker.net/",
    "User-Agent": "Mozilla/5.0",
}


def _uuid7():
    """生成 RFC 9562 UUIDv7（checker.net 的 requestId 要求 v7）。"""
    ts = int(time.time() * 1000)
    ts_hex = format(ts, "012x")
    rnd = secrets.token_bytes(10)
    g3 = format(0x7000 | (int.from_bytes(rnd[0:2], "big") & 0x0FFF), "04x")
    g4 = format(0x8000 | (int.from_bytes(rnd[2:4], "big") & 0x3FFF), "04x")
    return f"{ts_hex[:8]}-{ts_hex[8:12]}-{g3}-{g4}-{rnd[4:10].hex()}"


def _http_json(url, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_HDRS, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_archive(date=None):
    """拉取当天候选代理列表 -> ['ip:port', ...]"""
    if date is None:
        date = time.strftime("%Y-%m-%d")
    d = _http_json(f"{CHECKER_BASE}/v1/landing/archive/{date}", timeout=60)
    return d.get("data", {}).get("proxyList", []) or []


def grade(dsn_list, services=("google",), timeout=8, read_timeout=180):
    """
    提交 dsn_list 给 checker.net 打分测活，读 NDJSON 结果流。
    返回按分数降序的存活代理: [{'dsn','scheme','sc','cc'}, ...]
    """
    rid = _uuid7()
    body = {
        "dsnList": list(dsn_list),
        "services": list(services),
        "checkType": "soft",
        "timeout": timeout,
        "archiveEnabled": False,
    }
    _http_json(f"{CHECKER_BASE}/v1/landing/check/{rid}", "POST", body, timeout=60)

    alive = []
    req = urllib.request.Request(
        f"{CHECKER_BASE}/v1/landing/check/result/{rid}/stream", headers=_HDRS)
    deadline = time.time() + read_timeout
    with urllib.request.urlopen(req, timeout=read_timeout) as r:
        for raw in r:
            if time.time() > deadline:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            http_ok = bool((o.get("http") or {}).get("s"))
            socks_ok = bool((o.get("socks") or {}).get("s"))
            if not (http_ok or socks_ok):
                continue
            det = (o.get("http") or {}).get("d") or (o.get("socks") or {}).get("d") or {}
            alive.append({
                "dsn": o.get("dsn"),
                "scheme": "http" if http_ok else "socks5",
                "sc": o.get("sc") or 0,
                "cc": det.get("cc", "?"),
            })
    alive.sort(key=lambda x: x["sc"], reverse=True)
    return alive

def xiaomi_reachable(proxy_url, timeout=8):
    """通过该代理访问 api-user.huami.com 根路径，拿到 200/404 即算可达且未被限流。"""
    import requests
    try:
        r = requests.get(XIAOMI_PROBE,
                         proxies={"http": proxy_url, "https": proxy_url},
                         timeout=timeout)
        return r.status_code in (200, 404)
    except Exception:
        return False


def build_pool(top_n=120, verify=True, max_workers=30, date=None, log=print):
    """
    产出"小米可用"的 http 代理 URL 列表（按 checker 分数从高到低，保留能连通小米的）。
      top_n : 取分数最高的前 top_n 个做小米连通性验证
      verify: False 则直接返回按分排序的候选，不做小米验证
    """
    archive = fetch_archive(date)
    log(f"[代理池] 候选 {len(archive)} 个，提交 checker.net 打分测活…")
    if not archive:
        return []
    alive = grade(archive)
    log(f"[代理池] 存活 {len(alive)} 个；取分数最高的 {min(top_n, len(alive))} 个验证小米连通性")
    candidates = [f'{e["scheme"]}://{e["dsn"]}' for e in alive[:top_n]]
    if not verify:
        return candidates
    pool = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for proxy, ok in zip(candidates, ex.map(xiaomi_reachable, candidates)):
            if ok:
                pool.append(proxy)
    log(f"[代理池] 小米可用 {len(pool)} 个")
    return pool


if __name__ == "__main__":
    t0 = time.time()
    p = build_pool(top_n=120)
    print(f"\n=== 小米可用代理 {len(p)} 个，总耗时 {time.time() - t0:.0f}s ===")
    for x in p[:25]:
        print("  ", x)

