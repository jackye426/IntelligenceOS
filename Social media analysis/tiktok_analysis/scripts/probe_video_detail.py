import json
import re
import urllib.request

URL = "https://www.tiktok.com/@docmap/video/7630900114982210838"
req = urllib.request.Request(
    URL, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
)
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
m = re.search(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([^<]+)</script>', html
)
data = json.loads(m.group(1))
scope = data["__DEFAULT_SCOPE__"]
# common paths
for path_hint in ["webapp.video-detail", "webapp.item-info", "seo.abtest"]:
    parts = path_hint.split(".")
    cur = scope
    ok = True
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            ok = False
            break
    if ok:
        print(path_hint, "keys:", list(cur.keys())[:25] if isinstance(cur, dict) else type(cur))

# dump small slice of webapp
print("__DEFAULT_SCOPE__ keys", list(scope.keys()))
vd = scope.get("webapp.video-detail", {})
print("video-detail keys", list(vd.keys()) if isinstance(vd, dict) else vd)
if isinstance(vd, dict) and "itemInfo" in vd:
    st = vd["itemInfo"].get("itemStruct", {})
    print("itemStruct keys sample", list(st.keys())[:50])
    for k in ("stats", "statsV2", "desc", "textExtra", "author", "comments"):
        if k in st:
            v = st[k]
            if k == "comments":
                print("comments type", type(v), "len", len(v) if isinstance(v, list) else v)
                if isinstance(v, list) and v:
                    print("first comment keys", v[0].keys() if isinstance(v[0], dict) else v[0])
            else:
                print(k, v)
