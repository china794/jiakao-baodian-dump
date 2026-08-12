"""驾考宝典数据浏览器 - 路线视频数据准备
harvested/route-video/all-data.json (12MB, 2217 place / 6115 路线)
-> frontend/route_index.json  轻量索引: 城市 -> [{placeName, areaCode, videos:[{name, previewUrl, duration, viewCount, videoImage}]}]

用法: python frontend/prep_route.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "harvested" / "route-video" / "all-data.json"
OUT = Path(__file__).resolve().parent / "route_index.json"

def main():
    d = json.load(open(SRC, encoding="utf8"))
    # 按 cityCode 分组
    cities = {}
    n_video = 0
    for k, v in d.items():
        city_code = str(v.get("cityCode") or k.split("/")[0])
        city_name = v.get("cityName") or ""
        place = {
            "placeId": v.get("placeId"),
            "placeName": v.get("placeName") or "",
            "areaName": v.get("areaName") or "",
            "areaCode": v.get("areaCode"),
            "price": v.get("price"),
            "cityPrice": v.get("cityPrice"),
            "videos": [],
        }
        for x in v.get("list", []):
            if x.get("previewUrl"):
                place["videos"].append({
                    "name": x.get("name"),
                    "previewUrl": x.get("previewUrl"),
                    "duration": x.get("duration"),
                    "viewCount": x.get("viewCount"),
                    "image": x.get("videoImage"),
                    "desc": x.get("desc"),
                    "carGear": x.get("carGear"),
                })
                n_video += 1
        cities.setdefault(city_code, {"cityName": city_name, "places": []})
        cities[city_code]["places"].append(place)

    OUT.write_text(json.dumps(cities, ensure_ascii=False), encoding="utf8")
    print(f"路线索引: {len(cities)} 城市 / {sum(len(c['places']) for c in cities.values())} place / {n_video} 视频")
    print(f"输出: {OUT}")

if __name__ == "__main__":
    main()
