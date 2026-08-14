import math


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371000.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def distance_from_user_meters(user_location: dict[str, float] | None, lat: float, lng: float) -> float | None:
    if not user_location:
        return None
    user_lat = user_location.get("lat")
    user_lng = user_location.get("lng")
    if user_lat is None or user_lng is None or not lat or not lng:
        return None
    return haversine_meters(float(user_lat), float(user_lng), lat, lng)


def method_max_distance_meters(method, user_location: dict[str, float] | None) -> float | None:
    distances = []
    for step in method.steps:
        distance = distance_from_user_meters(user_location, step.poi.latitude, step.poi.longitude)
        if distance is not None:
            distances.append(distance)
    return max(distances) if distances else None
