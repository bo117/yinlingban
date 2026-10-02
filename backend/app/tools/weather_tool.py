# -*- coding: utf-8 -*-
"""
天气查询工具（角色2：郝英博）

对应任务 3.3：集成天气 API，实现实时天气和未来预报查询，
             数字人结合天气给出穿衣、出行建议

数据源：Open-Meteo（开源免费、无需 API Key、支持中文城市名查询）
  - 地理编码：https://geocoding-api.open-meteo.com/v1/search
  - 天气预报：https://api.open-meteo.com/v1/forecast

网络现实：Open-Meteo 是境外服务，国内网络偶发抖动 —— 所有 GET 都带一次自动重试，
保证评委面前的演示单发不挂（两次都失败才走降级话术）。
"""
import asyncio

import httpx

from app import config
from app.core.http_pool import get_client

# Open-Meteo 天气代码 → 中文描述
WEATHER_CODE_MAP = {
    0: ("晴", "sun"), 1: ("晴间多云", "sun-cloud"), 2: ("多云", "cloud"), 3: ("阴", "cloud"),
    45: ("有雾", "fog"), 48: ("有雾凇", "fog"),
    51: ("小毛毛雨", "rain"), 53: ("毛毛雨", "rain"), 55: ("大毛毛雨", "rain"),
    61: ("小雨", "rain"), 63: ("中雨", "rain"), 65: ("大雨", "rain"),
    66: ("冻雨", "rain"), 67: ("大冻雨", "rain"),
    71: ("小雪", "snow"), 73: ("中雪", "snow"), 75: ("大雪", "snow"), 77: ("雪粒", "snow"),
    80: ("小阵雨", "rain"), 81: ("阵雨", "rain"), 82: ("强阵雨", "rain"),
    85: ("小阵雪", "snow"), 86: ("大阵雪", "snow"),
    95: ("雷阵雨", "storm"), 96: ("雷阵雨伴冰雹", "storm"), 99: ("强雷雨伴冰雹", "storm"),
}



async def _get_with_retry(url: str, params: dict) -> httpx.Response:
    """GET 一次失败（超时/连接错）时隔 0.8 秒重试一次；两次都失败才抛给降级话术"""
    last_exc: Exception = None
    for attempt in range(2):
        try:
            return await get_client("weather", config.WEATHER_TIMEOUT).get(url, params=params)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e
            if attempt == 0:
                await asyncio.sleep(0.8)
    raise last_exc


# ============================================================
# 城市地理编码
# ============================================================
async def geocode_city(city: str) -> dict:
    """城市名 → 经纬度（Open-Meteo 地理编码，支持中文）"""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city, "count": 1, "language": "zh", "format": "json"}
    r = await _get_with_retry(url, params)
    r.raise_for_status()
    results = r.json().get("results") or []
    if not results:
        return {}
    first = results[0]
    return {
        "name": first.get("name", city),
        "lat": first["latitude"],
        "lon": first["longitude"],
        "admin": first.get("admin1", ""),
    }


# ============================================================
# 天气查询
# ============================================================
# 天气结果的进程内缓存：老人常连续问天气，同城市 10 分钟内直接复用
# （失败结果不缓存，方便"稍后再问"时重新请求）
_WEATHER_CACHE: dict = {}
_WEATHER_CACHE_TTL = 600


async def get_weather(city: str = None, user_city: str = "") -> dict:
    """
    查询实时天气 + 未来三天预报 + 适老化建议

    返回：
      {
        "success": True, "city": "北京",
        "current": {"temp": 12, "feels": 10, "desc": "晴", "wind": 2.1, "humidity": 40},
        "daily": [{"date": "…", "max": 15, "min": 5, "precip_prob": 10, "desc": "晴"}],
        "advice": {"穿衣": "…", "出行": "…"},
        "message": "给老人念的完整话术"
      }
    失败时返回 success=False 和中文错误原因
    """
    import time as _time

    city = city or user_city or config.DEFAULT_CITY

    # 先查缓存：同城市 10 分钟内的结果直接复用（省两次网络往返）
    _now = _time.time()
    _hit = _WEATHER_CACHE.get(city)
    if _hit and _now - _hit[0] < _WEATHER_CACHE_TTL:
        return _hit[1]

    try:
        # 1. 城市定位
        geo = await geocode_city(city)
        if not geo:
            return _fail(f"没有找到「{city}」这个地方的天气，换个城市名试试？")
        display_name = f"{geo['admin']}{geo['name']}" if geo.get("admin") else geo["name"]

        # 2. 查天气（当前 + 3天预报）
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": geo["lat"], "longitude": geo["lon"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 3, "timezone": "auto",
        }
        r = await _get_with_retry(url, params)
        r.raise_for_status()
        data = r.json()

        cur = data["current"]
        desc, _ = WEATHER_CODE_MAP.get(cur.get("weather_code", 0), ("未知", ""))
        current = {
            "temp": round(cur["temperature_2m"]),
            "feels": round(cur["apparent_temperature"]),
            "desc": desc,
            "wind": round(cur.get("wind_speed_10m", 0), 1),
            "humidity": cur.get("relative_humidity_2m", 0),
        }

        daily = []
        for i in range(len(data["daily"]["time"])):
            d_desc, _ = WEATHER_CODE_MAP.get(data["daily"]["weather_code"][i], ("未知", ""))
            daily.append({
                "date": data["daily"]["time"][i],
                "max": round(data["daily"]["temperature_2m_max"][i]),
                "min": round(data["daily"]["temperature_2m_min"][i]),
                "precip_prob": data["daily"]["precipitation_probability_max"][i],
                "desc": d_desc,
            })

        # 3. 生成穿衣/出行建议
        advice = _build_advice(current, daily)

        # 4. 组装给老人听的话术
        tomorrow = daily[1] if len(daily) > 1 else daily[0]
        msg = (
            f"{display_name}现在{current['desc']}，气温{current['temp']}度，"
            f"体感{current['feels']}度。明天{tomorrow['desc']}，"
            f"{tomorrow['min']}到{tomorrow['max']}度。{advice['穿衣']}{advice['出行']}"
        )
        result = {
            "success": True, "city": display_name,
            "current": current, "daily": daily, "advice": advice,
            "message": msg,
        }
        if len(_WEATHER_CACHE) >= 32:  # 防多城市查询下无限膨胀
            _WEATHER_CACHE.clear()
        _WEATHER_CACHE[city] = (_now, result)  # 成功才缓存
        return result
    except httpx.TimeoutException:
        return _fail("天气查询超时了，网络有点慢，您稍后再问我一遍。")
    except httpx.ConnectError:
        return _fail("现在连不上天气服务，可能是网络问题，稍后再试试。")
    except Exception as e:
        return _fail(f"天气查询出了点问题（{e}），稍后再试试。")


def _fail(reason: str) -> dict:
    return {"success": False, "message": reason}


# ============================================================
# 适老化建议生成
# ============================================================
def _build_advice(current: dict, daily: list) -> dict:
    """根据温度/降水/风生成穿衣与出行建议（通俗口语）"""
    temp = current["temp"]
    desc = current["desc"]
    wind = current.get("wind", 0)

    # 穿衣建议
    if temp <= 0:
        dress = "天很冷，出门要穿厚棉袄、戴帽子围巾，小心别冻着。"
    elif temp <= 8:
        dress = "外面冷，羽绒服或厚棉衣穿好，护住膝盖和腰。"
    elif temp <= 15:
        dress = "有点凉，穿个厚外套加毛衣正合适。"
    elif temp <= 22:
        dress = "天气不冷不热，长袖衣裤加件薄外套就好。"
    elif temp <= 28:
        dress = "天气挺暖和，穿轻薄透气的衣裳就行。"
    else:
        dress = "天热，穿凉快透气的衣裳，上午十点前、下午四点后再出门。"

    # 出行建议
    tips = []
    precip = max((d.get("precip_prob", 0) for d in daily[1:]), default=0)
    if "雨" in desc or precip >= 60:
        tips.append("这两天可能有雨，出门记得带伞，路滑走慢点。")
    if "雪" in desc:
        tips.append("下雪天路滑，尽量别出门，有事等雪停了再办。")
    if wind >= 6:
        tips.append("风大，出门当心着凉，帽子戴好。")
    if temp >= 33:
        tips.append("天太热，少出门多喝水，当心中暑。")
    if temp <= 0 and "晴" in desc:
        tips.append("天冷出太阳，晒晒太阳挺舒服，就是别站风口里。")
    if not tips:
        tips.append("天气不错，适合出门走走，散散步。")
    return {"穿衣": dress, "出行": "".join(tips)}
