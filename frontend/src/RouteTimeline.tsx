import { useState } from 'react';
import { Coords, formatDistance, haversineMeters } from './geo';
import { Place, RouteGroup } from './api';

type RouteTimelineProps = {
  routeGroups: RouteGroup[];
  userCoords: Coords | null;
  geoStatus: string;
  onRequestLocation: () => void;
};

const CATEGORY_LABELS: Record<string, string> = {
  restaurant: '美食',
  entertainment: '娱乐',
  shopping: '购物',
  tourism: '景点',
  sports: '运动',
  culture: '文化',
  nightlife: '夜生活',
  outdoor: '户外',
  wellness: '康养',
};

function categoryLabel(category?: string | null): string | null {
  if (!category) return null;
  return CATEGORY_LABELS[category] ?? null;
}

function totalPlaces(groups: RouteGroup[]): number {
  return groups.reduce((sum, group) => sum + group.places.length, 0);
}

export default function RouteTimeline({
  routeGroups,
  userCoords,
  geoStatus,
  onRequestLocation,
}: RouteTimelineProps) {
  const [open, setOpen] = useState(false);

  if (!routeGroups || routeGroups.length === 0) {
    return null;
  }

  const placeCount = totalPlaces(routeGroups);

  return (
    <section className={`route-block${open ? ' open' : ''}`}>
      <button
        type="button"
        className="route-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="route-toggle-main">
          <span className="route-toggle-icon">➡️</span>
          <span className="route-toggle-text">玩法路线</span>
          <span className="route-toggle-count">
            {routeGroups.length} 个玩法 · {placeCount} 个地点
          </span>
        </span>
        <span className="route-toggle-arrow">{open ? '收起' : '展开'}</span>
      </button>

      {open && (
        <div className="route-panel">
          <div className="route-loc-row">
            <button
              type="button"
              className={`route-loc-chip${userCoords ? ' active' : ''}`}
              onClick={onRequestLocation}
              disabled={geoStatus === 'locating'}
              title="点击定位，查看每个地点距你多远"
            >
              {userCoords
                ? '已按你的位置显示距离'
                : geoStatus === 'locating'
                  ? '定位中…'
                  : geoStatus === 'insecure'
                    ? '需 HTTPS 才能定位'
                    : geoStatus === 'denied'
                      ? '定位被拒绝'
                      : geoStatus === 'unsupported'
                        ? '当前环境不支持定位'
                        : '开启定位看距离'}
            </button>
          </div>

          <div className="route-groups">
            {routeGroups.map((group) => (
              <div className="route-group" key={`${group.section_index}-${group.section_label}`}>
                <div className="route-group-title">
                  <span className="route-group-badge">{group.section_label}</span>
                  {group.title && <span className="route-group-name">{group.title}</span>}
                </div>
                <ol className="route-pois">
                  {group.places.map((place: Place, index) => {
                    const distance = userCoords
                      ? haversineMeters(userCoords, { lat: place.lat, lng: place.lng })
                      : null;
                    const label = categoryLabel(place.category);
                    return (
                      <li className="route-poi" key={`${place.amap_poi_id ?? place.name}-${index}`}>
                        <span className="route-poi-dot">{index + 1}</span>
                        <div className="route-poi-info">
                          <div className="route-poi-line">
                            <span className="route-poi-name-row">
                              <span className="route-poi-name">{place.name}</span>
                              {label && <span className="route-poi-tag">{label}</span>}
                            </span>
                            {distance != null && (
                              <span className="route-poi-distance">距你 {formatDistance(distance)}</span>
                            )}
                          </div>
                          <div className="route-poi-sub">
                            {place.rating ? <span className="route-poi-rating">⭐ {place.rating}</span> : null}
                            {place.address && <span className="route-poi-addr">{place.address}</span>}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
