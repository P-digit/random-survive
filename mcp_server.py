"""게임 엔진의 기능을 MCP 서버로 공개한다. (LLM_03 Tool/MCP 파트)

게임(app.py)과는 별개로 동작하며, 다른 MCP 클라이언트가 이 게임의 기능을 가져다 쓸 수 있다.

    fastmcp list mcp_server.py                 # 툴 목록 확인
    fastmcp call mcp_server.py random_location # 툴 직접 실행
    fastmcp run mcp_server.py                  # 서버 실행
"""
from fastmcp import FastMCP

from survival import climate, geo, knowledge, risk_model
from survival import weather as weather_api
from survival.events import BIOMES, classify_biome
from survival.gamemaster import get_client

mcp = FastMCP("랜덤 좌표 생존기")


@mcp.tool
def random_location() -> dict:
    """지구에서 랜덤한 육지 좌표를 하나 뽑고, 지명과 한국까지의 거리를 알려줍니다."""
    lat, lon, elevation = geo.pick_random_land()
    place = geo.reverse_geocode(lat, lon)
    return {
        "latitude": lat, "longitude": lon, "elevation_m": elevation,
        "place": place["name"] if place else "이름 모를 땅",
        "distance_to_korea_km": round(geo.distance_to_korea(lat, lon)),
    }


@mcp.tool
def get_weather(latitude: float, longitude: float) -> dict:
    """위도와 경도로 해당 위치의 현재 날씨, 기후대, 지형(바이옴)을 알려줍니다."""
    weather = weather_api.get_weather(latitude, longitude)
    weather.pop("hourly", None)
    zone = climate.get_climate(latitude, longitude, weather)
    weather["climate"] = climate.describe(zone)
    weather["biome"] = BIOMES[classify_biome(latitude, weather, zone)][0]
    return weather


@mcp.tool
def predict_survival_risk(latitude: float, longitude: float, health: float = 100,
                          satiety: float = 70, hydration: float = 70, energy: float = 80,
                          is_night: bool = False, in_wild: bool = True) -> dict:
    """해당 위치의 현재 날씨와 몸 상태(0~100)로 생존 위험 등급(안전/주의/위험)을 예측합니다."""
    weather = weather_api.get_weather(latitude, longitude)
    return risk_model.predict_risk(weather, health, satiety, hydration, energy, is_night, in_wild)


@mcp.tool
def search_survival_guide(query: str) -> list:
    """생존 지식 문서에서 질문과 관련된 내용을 검색합니다. 예: '뱀에 물렸을 때'"""
    return knowledge.search(get_client(), query)


if __name__ == "__main__":
    mcp.run()
