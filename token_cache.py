# -*- coding: utf8 -*-
"""
token_cache.py —— 跨运行复用 login_token 的加密缓存

目的：登录第一步 registrations/tokens 是被小米限流(429)的接口。把首次登录拿到的
     login_token 存下来，后续运行直接用它换 app_token（get_app_token 走的是没被限流的
     account-cn.huami.com），从而跳过被限流的登录接口，既快又稳。

安全：仓库是公开的，绝不能存明文 token。用 GitHub Secret `TOKEN_CACHE_KEY` 派生对称密钥
     (Fernet) 加密整个缓存文件；账号名只存 sha256 哈希。未配置密钥或未装 cryptography 时，
     自动降级为"不缓存"，完全不影响原有流程。
"""
import base64
import hashlib
import json
import os
import time

CACHE_FILE = "token_cache.bin"
_KEY_ENV = "TOKEN_CACHE_KEY"


def _fernet():
    key = os.environ.get(_KEY_ENV)
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    # 由任意口令派生出合法的 Fernet key（32 字节，urlsafe base64）
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _user_key(user):
    # 不落明文账号名，用哈希当键
    return hashlib.sha256(str(user).encode("utf-8")).hexdigest()[:16]

def load():
    """读取并解密缓存 -> dict；无密钥/无文件/解密失败都返回空 dict。"""
    f = _fernet()
    if not f or not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "rb") as fh:
            return json.loads(f.decrypt(fh.read()).decode("utf-8"))
    except Exception:
        return {}


def save(cache):
    """加密写回缓存文件；无密钥则跳过（不生成明文文件）。"""
    f = _fernet()
    if not f:
        return
    try:
        with open(CACHE_FILE, "wb") as fh:
            fh.write(f.encrypt(json.dumps(cache).encode("utf-8")))
    except Exception as e:
        print(f"[token 缓存] 保存失败：{e}")


def get(cache, user, max_age_days=20):
    """取该账号未过期的缓存项 -> {'login_token','userid','ts'} 或 None。"""
    if not cache:
        return None
    e = cache.get(_user_key(user))
    if not e:
        return None
    if time.time() - e.get("ts", 0) > max_age_days * 86400:
        return None
    return e


def put(cache, user, login_token, userid):
    if cache is None:
        return
    cache[_user_key(user)] = {
        "login_token": login_token,
        "userid": userid,
        "ts": int(time.time()),
    }
