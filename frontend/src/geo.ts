import { useCallback, useEffect, useState } from 'react';

export type Coords = {
  lat: number;
  lng: number;
};

export type GeoState = {
  coords: Coords | null;
  status: 'idle' | 'locating' | 'granted' | 'denied' | 'unsupported' | 'insecure';
  error: string | null;
};

const STORAGE_KEY = 'citycity_geo';
const EARTH_RADIUS_M = 6371000;
const SIGNIFICANT_MOVE_METERS = 100;

const GCJ_A = 6378245.0;
const GCJ_EE = 0.00669342162296594323;

function outOfChina(lat: number, lng: number): boolean {
  return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271;
}

function transformLat(x: number, y: number): number {
  let ret =
    -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0;
  ret += ((20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin((y / 3.0) * Math.PI)) * 2.0) / 3.0;
  ret += ((160.0 * Math.sin((y / 12.0) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30.0)) * 2.0) / 3.0;
  return ret;
}

function transformLng(x: number, y: number): number {
  let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0;
  ret += ((20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin((x / 3.0) * Math.PI)) * 2.0) / 3.0;
  ret += ((150.0 * Math.sin((x / 12.0) * Math.PI) + 300.0 * Math.sin((x / 30.0) * Math.PI)) * 2.0) / 3.0;
  return ret;
}

export function wgs84ToGcj02(lat: number, lng: number): Coords {
  if (outOfChina(lat, lng)) {
    return { lat, lng };
  }
  const dLat = transformLat(lng - 105.0, lat - 35.0);
  const dLng = transformLng(lng - 105.0, lat - 35.0);
  const radLat = (lat / 180.0) * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - GCJ_EE * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  const adjLat = (dLat * 180.0) / (((GCJ_A * (1 - GCJ_EE)) / (magic * sqrtMagic)) * Math.PI);
  const adjLng = (dLng * 180.0) / ((GCJ_A / sqrtMagic) * Math.cos(radLat) * Math.PI);
  return { lat: lat + adjLat, lng: lng + adjLng };
}

function toRad(value: number): number {
  return (value * Math.PI) / 180;
}

export function haversineMeters(a: Coords, b: Coords): number {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function formatDistance(meters: number): string {
  if (meters < 1000) {
    return `${Math.round(meters)}m`;
  }
  return `${(meters / 1000).toFixed(1)}km`;
}

export function postMinDistanceMeters(
  user: Coords,
  places: Array<{ lat: number; lng: number }>,
): number | null {
  const distances = places
    .filter((place) => place.lat && place.lng)
    .map((place) => haversineMeters(user, { lat: place.lat, lng: place.lng }));
  if (!distances.length) return null;
  return Math.min(...distances);
}

export function movedSignificantly(
  from: Coords | null,
  to: Coords,
  thresholdMeters = SIGNIFICANT_MOVE_METERS,
): boolean {
  if (!from) return true;
  return haversineMeters(from, to) >= thresholdMeters;
}

function writeCached(coords: Coords) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(coords));
  } catch {
    // ignore storage failures
  }
}

function readCached(): Coords | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof parsed?.lat === 'number' && typeof parsed?.lng === 'number') {
      return { lat: parsed.lat, lng: parsed.lng };
    }
  } catch {
    return null;
  }
  return null;
}

export function useGeolocation() {
  const [state, setState] = useState<GeoState>(() => {
    const cached = readCached();
    return {
      coords: cached,
      status: cached ? 'granted' : 'idle',
      error: null,
    };
  });

  const readPosition = useCallback((maximumAge: number) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setState((prev) => ({ ...prev, status: 'unsupported', error: '当前环境不支持定位' }));
      return;
    }
    if (typeof window !== 'undefined' && !window.isSecureContext) {
      setState((prev) => ({
        ...prev,
        status: 'insecure',
        error: '公网 HTTP 页面无法请求定位，请使用 HTTPS 或本机 localhost 调试',
      }));
      return;
    }
    setState((prev) => ({ ...prev, status: 'locating', error: null }));
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const coords = wgs84ToGcj02(position.coords.latitude, position.coords.longitude);
        writeCached(coords);
        setState({ coords, status: 'granted', error: null });
      },
      (error) => {
        setState((prev) => ({
          ...prev,
          coords: prev.coords,
          status: error.code === error.PERMISSION_DENIED ? 'denied' : prev.coords ? 'granted' : 'idle',
          error: error.code === error.PERMISSION_DENIED ? '已拒绝定位授权' : '定位失败，请重试',
        }));
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge },
    );
  }, []);

  const request = useCallback(() => {
    readPosition(60_000);
  }, [readPosition]);

  const refresh = useCallback(() => {
    readPosition(0);
  }, [readPosition]);

  useEffect(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return;
    if (typeof window !== 'undefined' && !window.isSecureContext) {
      setState((prev) => ({
        ...prev,
        status: 'insecure',
        error: '公网 HTTP 页面无法请求定位，请使用 HTTPS 或本机 localhost 调试',
      }));
      return;
    }
    if (!navigator.permissions?.query) {
      refresh();
      return;
    }
    navigator.permissions
      .query({ name: 'geolocation' as PermissionName })
      .then((result) => {
        if (result.state === 'denied') {
          setState((prev) => ({
            ...prev,
            status: 'denied',
            error: '定位授权被拒绝，请在浏览器站点设置中重新允许定位',
          }));
          return;
        }
        refresh();
      })
      .catch(() => refresh());
  }, [refresh]);

  return { ...state, request, refresh };
}
