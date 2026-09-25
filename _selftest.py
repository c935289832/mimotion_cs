# -*- coding: utf8 -*-
# 一次性自检：在真实 US runner 上验证 proxy_pool 构建 + login 走代理直连小米。
# 不使用任何真实账号，用假账号只为证明请求经代理到达了 api-user.huami.com。
import sys
import time

# main.py 顶部会读取 sys.argv[3]/[4]，导入前先塞占位参数
sys.argv = ["x", "dummy@example.com", "wrongpass", "False", "NO", "tok", "0", "uid"]

import proxy_pool
import main

t0 = time.time()
pool = proxy_pool.build_pool(top_n=120)
print(f"POOL_SIZE={len(pool)}  用时={time.time() - t0:.0f}s")
for p in pool[:15]:
    print("  ", p)

if pool:
    print("\n=== 用假账号 + 池内第一个代理跑一遍 login()（期望 None,None，但能证明请求经代理到达小米）===")
    lt, uid = main.login("dummy@example.com", "wrongpass", pool[0])
    print("LOGIN_WIRE_RESULT:", lt, uid)
