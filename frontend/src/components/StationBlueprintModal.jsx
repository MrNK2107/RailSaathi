import React, { useState, useEffect } from "react";
import {
  Compass,
  Accessibility,
  Footprints,
  AlertTriangle,
  CheckCircle2,
  X,
  Layers,
  Info,
  Sparkles,
} from "lucide-react";

export default function StationBlueprintModal({
  isOpen,
  onClose,
  initialStation = "chennai_central",
  initialTargetPlatform = "10",
  onLaunchAR = null,
}) {
  const [stationData, setStationData] = useState(null);
  const [, setLoading] = useState(true);
  const [mobility, setMobility] = useState("wheelchair"); // 'wheelchair' | 'avoid_stairs' | 'normal'
  const [selectedSource, setSelectedSource] = useState("ent_wall_tax");
  const [selectedTarget, setSelectedTarget] = useState("platform_10");
  const [routeResult, setRouteResult] = useState(null);
  const [, setRouteLoading] = useState(false);
  const [selectedTab, setSelectedTab] = useState("map"); // 'map' | 'turns' | 'amenities'

  // Default coordinate space for Chennai Central blueprint
  const mapW = stationData?.map?.width || 1821;
  const mapH = stationData?.map?.height || 864;

  useEffect(() => {
    if (isOpen) {
      loadStationBlueprint();
    }
  }, [isOpen, initialStation]);

  useEffect(() => {
    if (stationData) {
      calculateIndoorRoute();
    }
  }, [mobility, selectedSource, selectedTarget, stationData]);

  // Sync initial platform
  useEffect(() => {
    if (initialTargetPlatform) {
      const pfNodeId = `platform_${initialTargetPlatform}`;
      setSelectedTarget(pfNodeId);
    }
  }, [initialTargetPlatform]);

  const loadStationBlueprint = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/stations/${initialStation}`);
      if (res.ok) {
        const d = await res.json();
        setStationData(d);
      }
    } catch (e) {
      console.error("Failed to load blueprint:", e);
    } finally {
      setLoading(false);
    }
  };

  const calculateIndoorRoute = async () => {
    setRouteLoading(true);
    try {
      const payload = {
        station_id: initialStation,
        source: selectedSource,
        destination: selectedTarget,
        preferences: {
          wheelchair: mobility === "wheelchair",
          avoid_stairs: mobility === "avoid_stairs" || mobility === "wheelchair",
          require_verified_accessibility: mobility === "wheelchair",
        },
        apply_disruptions: true,
      };

      const res = await fetch("/api/navigation/route", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      setRouteResult(data);
    } catch (e) {
      console.error("Route calculation error:", e);
    } finally {
      setRouteLoading(false);
    }
  };

  if (!isOpen) return null;

  // Convert normalized [0..1] coordinates to SVG pixels
  const toPx = (normPt) => {
    if (!normPt || normPt.length < 2) return [0, 0];
    return [normPt[0] * mapW, normPt[1] * mapH];
  };

  // Convert geometry polyline array to SVG path 'd' attribute
  const generateSvgPath = (points) => {
    if (!points || points.length < 2) return "";
    return points
      .map((p, idx) => {
        const [x, y] = toPx(p);
        return `${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");
  };

  const entrances = (stationData?.nodes || []).filter((n) => n.type === "entrance");
  const platforms = (stationData?.nodes || []).filter((n) => n.type === "platform");
  const otherDestinations = (stationData?.nodes || []).filter((n) =>
    ["toilet", "ticket_counter", "concourse", "shop"].includes(n.type)
  );

  return (
    <div style={styles.backdrop}>
      <div style={styles.sheet}>
        {/* Header */}
        <div style={styles.header}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={styles.headerIcon}>
              <Layers size={18} color="#38bdf8" />
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={styles.kicker}>PILLAR 5 INDOOR ARCHITECTURE</span>
                <span style={styles.badgeGov}>SOUTHERN RAILWAY MAS</span>
              </div>
              <h3 style={styles.title}>2D Station Blueprint & Accessibility Route</h3>
            </div>
          </div>
          <button onClick={onClose} style={styles.closeBtn}>
            <X size={20} color="#94a3b8" />
          </button>
        </div>

        {/* Mobility Mode Selector (Pillar 5 Inclusive Design) */}
        <div style={styles.mobilityBar}>
          <button
            onClick={() => setMobility("wheelchair")}
            style={{
              ...styles.mobilityBtn,
              ...(mobility === "wheelchair" ? styles.mobilityBtnActiveWheelchair : {}),
            }}
          >
            <Accessibility size={14} />
            <span>Wheelchair / Step-Free</span>
          </button>

          <button
            onClick={() => setMobility("avoid_stairs")}
            style={{
              ...styles.mobilityBtn,
              ...(mobility === "avoid_stairs" ? styles.mobilityBtnActiveAvoid : {}),
            }}
          >
            <Footprints size={14} />
            <span>Avoid Stairs</span>
          </button>

          <button
            onClick={() => setMobility("normal")}
            style={{
              ...styles.mobilityBtn,
              ...(mobility === "normal" ? styles.mobilityBtnActiveNormal : {}),
            }}
          >
            <Compass size={14} />
            <span>Standard Walk</span>
          </button>
        </div>

        {/* Route Selectors (Source Entrance & Destination Platform) */}
        <div style={styles.selectorsRow}>
          <div style={styles.selectorItem}>
            <label htmlFor="blueprint-from" style={styles.selectorLabel}>FROM ENTRANCE</label>
            <select
              id="blueprint-from"
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              style={styles.selectInput}
            >
              {entrances.map((ent) => (
                <option key={ent.id} value={ent.id}>
                  {ent.name} {ent.id === "ent_wall_tax" ? "♿ (Step-Free Ramp)" : ent.id === "ent_jn_road" ? "⚠️ (Stairs)" : ""}
                </option>
              ))}
            </select>
          </div>

          <div style={styles.selectorItem}>
            <label htmlFor="blueprint-to" style={styles.selectorLabel}>TO PLATFORM / DESTINATION</label>
            <select
              id="blueprint-to"
              value={selectedTarget}
              onChange={(e) => setSelectedTarget(e.target.value)}
              style={styles.selectInput}
            >
              <optgroup label="Platforms">
                {platforms.map((pf) => (
                  <option key={pf.id} value={pf.id}>
                    {pf.name}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Amenities & Facilities">
                {otherDestinations.map((od) => (
                  <option key={od.id} value={od.id}>
                    {od.name} ({od.type})
                  </option>
                ))}
              </optgroup>
            </select>
          </div>
        </div>

        {/* Route Status / Warning Banner */}
        {routeResult?.status === "no_route" && (
          <div style={styles.alertBlocked}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
              <AlertTriangle size={18} color="#f43f5e" style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <strong style={{ color: "#fff", fontSize: "0.82rem" }}>
                  Stair Barrier Detected on Route
                </strong>
                <p style={{ color: "#fca5a5", fontSize: "0.72rem", margin: "3px 0 6px 0", lineHeight: 1.35 }}>
                  {routeResult.explanation ||
                    "This entrance includes stairs that are not wheelchair-accessible."}
                </p>
                <button
                  onClick={() => setSelectedSource("ent_wall_tax")}
                  style={styles.btnSwitchAccessible}
                >
                  <Accessibility size={12} />
                  <span>Switch to Wall Tax Rd (Step-Free Accessible Entrance)</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* View Tabs */}
        <div style={styles.tabBar}>
          <button
            onClick={() => setSelectedTab("map")}
            style={{ ...styles.tabBtn, ...(selectedTab === "map" ? styles.tabBtnActive : {}) }}
          >
            Blueprint Map
          </button>
          <button
            onClick={() => setSelectedTab("turns")}
            style={{ ...styles.tabBtn, ...(selectedTab === "turns" ? styles.tabBtnActive : {}) }}
          >
            Turn Instructions ({routeResult?.instructions?.length || 0})
          </button>
          <button
            onClick={() => setSelectedTab("amenities")}
            style={{ ...styles.tabBtn, ...(selectedTab === "amenities" ? styles.tabBtnActive : {}) }}
          >
            Along The Way ({routeResult?.along_the_way?.length || 0})
          </button>
        </div>

        {/* TAB 1: BLUEPRINT MAP SVG VIEWER */}
        {selectedTab === "map" && (
          <div style={styles.mapContainer}>
            <div style={styles.blueprintFrame}>
              <svg
                viewBox={`0 0 ${mapW} ${mapH}`}
                style={styles.svgMap}
                preserveAspectRatio="xMidYMid meet"
              >
                {/* Station architectural blueprint background image */}
                <image
                  href="/data/stations/chennai_central/map.png"
                  width={mapW}
                  height={mapH}
                  opacity="0.88"
                />

                {/* Base Walkway Network */}
                {stationData?.edges?.map((edge) => {
                  const pathStr = generateSvgPath(edge.geometry);
                  const isBlocked = edge.has_steps && mobility === "wheelchair";
                  return (
                    <path
                      key={edge.id}
                      d={pathStr}
                      stroke={isBlocked ? "rgba(244, 63, 94, 0.4)" : "rgba(255, 255, 255, 0.15)"}
                      strokeWidth={isBlocked ? "3" : "2"}
                      strokeDasharray={edge.path_type === "stairs" ? "4 4" : "none"}
                      fill="none"
                    />
                  );
                })}

                {/* Computed Active Route Overlay Polyline */}
                {routeResult?.status === "ok" && routeResult.geometry && (
                  <path
                    d={generateSvgPath(routeResult.geometry)}
                    stroke={mobility === "wheelchair" ? "#10b981" : "#38bdf8"}
                    strokeWidth="8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                    style={{
                      filter: `drop-shadow(0 0 6px ${mobility === "wheelchair" ? "#10b981" : "#38bdf8"})`,
                    }}
                  />
                )}

                {/* Nodes on Map */}
                {stationData?.nodes?.map((node) => {
                  const [cx, cy] = toPx(node.position);
                  const isSource = node.id === selectedSource;
                  const isTarget = node.id === selectedTarget;
                  const isPlatform = node.type === "platform";
                  const isEntrance = node.type === "entrance";

                  if (isSource) {
                    return (
                      <g key={node.id} transform={`translate(${cx}, ${cy})`}>
                        <circle r="18" fill="rgba(16, 185, 129, 0.3)" />
                        <circle r="10" fill="#10b981" stroke="#fff" strokeWidth="2" />
                        <text y="-14" textAnchor="middle" fill="#6ee7b7" fontSize="20" fontWeight="900">
                          START: {node.name.split("(")[0]}
                        </text>
                      </g>
                    );
                  }

                  if (isTarget) {
                    return (
                      <g key={node.id} transform={`translate(${cx}, ${cy})`}>
                        <circle r="20" fill="rgba(245, 158, 11, 0.35)" />
                        <circle r="12" fill="#f59e0b" stroke="#fff" strokeWidth="2" />
                        <text y="-16" textAnchor="middle" fill="#fbbf24" fontSize="22" fontWeight="900">
                          DEST: {node.name}
                        </text>
                      </g>
                    );
                  }

                  if (isPlatform) {
                    return (
                      <g key={node.id} transform={`translate(${cx}, ${cy})`}>
                        <rect x="-8" y="-8" width="16" height="16" rx="4" fill="#3b82f6" />
                        <text y="20" textAnchor="middle" fill="#93c5fd" fontSize="16" fontWeight="700">
                          {node.name.replace("Platform ", "P")}
                        </text>
                      </g>
                    );
                  }

                  if (isEntrance) {
                    return (
                      <circle
                        key={node.id}
                        cx={cx}
                        cy={cy}
                        r="6"
                        fill="#64748b"
                        stroke="#fff"
                        strokeWidth="1.5"
                      />
                    );
                  }

                  return null;
                })}
              </svg>
            </div>

            {/* Quick Metrics Floating Bar */}
            {routeResult?.status === "ok" && (
              <div style={styles.metricsBar}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div>
                    <span style={styles.metricLabel}>ROUTE DISTANCE</span>
                    <div style={styles.metricVal}>
                      {routeResult.distance_m
                        ? `${Math.round(routeResult.distance_m)}m`
                        : `${routeResult.geometry?.length * 8 || 120}m`}
                    </div>
                  </div>
                  <div style={styles.dividerV} />
                  <div>
                    <span style={styles.metricLabel}>EST. WALKING TIME</span>
                    <div style={styles.metricVal}>
                      {routeResult.estimated_duration_s
                        ? `${Math.ceil(routeResult.estimated_duration_s / 60)} min`
                        : "2 min"}
                    </div>
                  </div>
                  <div style={styles.dividerV} />
                  <div>
                    <span style={styles.metricLabel}>ACCESSIBILITY</span>
                    <div style={{ ...styles.metricVal, color: "#10b981" }}>
                      {mobility === "wheelchair" ? "Step-Free 100%" : "Walkable"}
                    </div>
                  </div>
                </div>

                {onLaunchAR && (
                  <button
                    onClick={() => {
                      onClose();
                      onLaunchAR("Platform Route", "Follow Blueprint AR", 30);
                    }}
                    style={styles.btnLaunchARMini}
                  >
                    <Compass size={13} />
                    <span>View in AR</span>
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {/* TAB 2: TURN INSTRUCTIONS */}
        {selectedTab === "turns" && (
          <div style={styles.scrollList}>
            {routeResult?.instructions && routeResult.instructions.length > 0 ? (
              routeResult.instructions.map((inst, idx) => (
                <div key={idx} style={styles.turnCard}>
                  <div style={styles.turnNum}>{idx + 1}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ color: "#fff", fontSize: "0.82rem", fontWeight: 700 }}>
                      {inst.text || inst.action}
                    </div>
                    {inst.distance_m && (
                      <span style={{ fontSize: "0.68rem", color: "#94a3b8" }}>
                        Walk {Math.round(inst.distance_m)}m
                      </span>
                    )}
                  </div>
                  {inst.step_free && (
                    <span style={styles.badgeStepFree}>Step-Free</span>
                  )}
                </div>
              ))
            ) : (
              <div style={styles.emptyState}>
                <CheckCircle2 size={24} color="#10b981" />
                <span>Direct concourse connection to target buffer.</span>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: ALONG THE WAY AMENITIES */}
        {selectedTab === "amenities" && (
          <div style={styles.scrollList}>
            {routeResult?.along_the_way && routeResult.along_the_way.length > 0 ? (
              routeResult.along_the_way.map((item, idx) => (
                <div key={idx} style={styles.amenityRow}>
                  <div style={styles.amenityIconBox}>
                    <Sparkles size={14} color="#38bdf8" />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ color: "#fff", fontSize: "0.82rem", fontWeight: 700 }}>
                      {item.name}
                    </div>
                    <span style={{ fontSize: "0.68rem", color: "#64748b" }}>
                      {item.type} • {Math.round(item.progress * 100)}% along path
                    </span>
                  </div>
                  <span style={styles.onRouteTag}>
                    {item.on_route ? "On Route" : "Nearby"}
                  </span>
                </div>
              ))
            ) : (
              <div style={styles.emptyState}>
                <Info size={20} color="#64748b" />
                <span>No facilities directly intersecting this walkway segment.</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const styles = {
  backdrop: {
    position: "fixed",
    inset: 0,
    backgroundColor: "rgba(0, 0, 0, 0.8)",
    backdropFilter: "blur(10px)",
    zIndex: 900,
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "center",
  },
  sheet: {
    width: "100%",
    maxWidth: "500px",
    backgroundColor: "#080c14",
    borderTopLeftRadius: "22px",
    borderTopRightRadius: "22px",
    border: "1px solid rgba(255, 255, 255, 0.12)",
    height: "92vh",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  header: {
    padding: "14px 16px",
    borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  headerIcon: {
    width: "32px",
    height: "32px",
    borderRadius: "8px",
    backgroundColor: "rgba(56, 189, 248, 0.15)",
    border: "1px solid rgba(56, 189, 248, 0.3)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  kicker: {
    fontSize: "0.6rem",
    fontWeight: 800,
    color: "#64748b",
    textTransform: "uppercase",
  },
  badgeGov: {
    fontSize: "0.58rem",
    fontWeight: 800,
    backgroundColor: "rgba(16, 185, 129, 0.15)",
    color: "#6ee7b7",
    padding: "1px 5px",
    borderRadius: "3px",
  },
  title: {
    fontSize: "0.95rem",
    fontWeight: 800,
    color: "#fff",
    margin: "2px 0 0 0",
  },
  closeBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    padding: "4px",
  },
  mobilityBar: {
    display: "flex",
    gap: "6px",
    padding: "8px 14px",
    backgroundColor: "rgba(255, 255, 255, 0.02)",
    borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
  },
  mobilityBtn: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "4px",
    padding: "6px 8px",
    borderRadius: "8px",
    fontSize: "0.68rem",
    fontWeight: 700,
    color: "#94a3b8",
    backgroundColor: "rgba(255, 255, 255, 0.03)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    cursor: "pointer",
  },
  mobilityBtnActiveWheelchair: {
    backgroundColor: "rgba(16, 185, 129, 0.18)",
    borderColor: "rgba(16, 185, 129, 0.5)",
    color: "#10b981",
  },
  mobilityBtnActiveAvoid: {
    backgroundColor: "rgba(56, 189, 248, 0.18)",
    borderColor: "rgba(56, 189, 248, 0.5)",
    color: "#38bdf8",
  },
  mobilityBtnActiveNormal: {
    backgroundColor: "rgba(255, 255, 255, 0.12)",
    borderColor: "rgba(255, 255, 255, 0.25)",
    color: "#fff",
  },
  selectorsRow: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "8px",
    padding: "8px 14px",
    backgroundColor: "rgba(0, 0, 0, 0.25)",
    borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
  },
  selectorItem: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
  },
  selectorLabel: {
    fontSize: "0.58rem",
    fontWeight: 800,
    color: "#64748b",
  },
  selectInput: {
    backgroundColor: "rgba(255, 255, 255, 0.06)",
    border: "1px solid rgba(255, 255, 255, 0.12)",
    borderRadius: "6px",
    color: "#e2e8f0",
    fontSize: "0.72rem",
    padding: "6px 8px",
    outline: "none",
  },
  alertBlocked: {
    margin: "8px 14px",
    padding: "10px 12px",
    backgroundColor: "rgba(244, 63, 94, 0.1)",
    border: "1px solid rgba(244, 63, 94, 0.35)",
    borderRadius: "10px",
  },
  btnSwitchAccessible: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    marginTop: "4px",
    backgroundColor: "#10b981",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    padding: "4px 8px",
    fontSize: "0.68rem",
    fontWeight: 800,
    cursor: "pointer",
  },
  tabBar: {
    display: "flex",
    borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
    padding: "0 14px",
  },
  tabBtn: {
    flex: 1,
    padding: "8px 6px",
    background: "none",
    border: "none",
    borderBottom: "2px solid transparent",
    color: "#64748b",
    fontSize: "0.72rem",
    fontWeight: 700,
    cursor: "pointer",
  },
  tabBtnActive: {
    color: "#38bdf8",
    borderBottomColor: "#38bdf8",
  },
  mapContainer: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    position: "relative",
  },
  blueprintFrame: {
    flex: 1,
    overflow: "auto",
    backgroundColor: "#04070d",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "10px",
  },
  svgMap: {
    width: "100%",
    height: "100%",
    maxHeight: "450px",
    borderRadius: "8px",
    backgroundColor: "#060911",
  },
  metricsBar: {
    padding: "10px 14px",
    backgroundColor: "rgba(10, 16, 26, 0.95)",
    borderTop: "1px solid rgba(255, 255, 255, 0.08)",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  metricLabel: {
    fontSize: "0.56rem",
    color: "#64748b",
    fontWeight: 800,
    display: "block",
  },
  metricVal: {
    fontSize: "0.88rem",
    fontWeight: 800,
    color: "#fff",
  },
  dividerV: {
    width: "1px",
    height: "20px",
    backgroundColor: "rgba(255, 255, 255, 0.1)",
  },
  btnLaunchARMini: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    backgroundColor: "rgba(56, 189, 248, 0.15)",
    border: "1px solid rgba(56, 189, 248, 0.4)",
    borderRadius: "8px",
    color: "#38bdf8",
    padding: "6px 10px",
    fontSize: "0.72rem",
    fontWeight: 800,
    cursor: "pointer",
  },
  scrollList: {
    flex: 1,
    overflowY: "auto",
    padding: "14px",
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  turnCard: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "10px 12px",
    backgroundColor: "rgba(255, 255, 255, 0.03)",
    border: "1px solid rgba(255, 255, 255, 0.06)",
    borderRadius: "10px",
  },
  turnNum: {
    width: "22px",
    height: "22px",
    borderRadius: "50%",
    backgroundColor: "rgba(56, 189, 248, 0.15)",
    color: "#38bdf8",
    fontSize: "0.72rem",
    fontWeight: 900,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  badgeStepFree: {
    fontSize: "0.6rem",
    backgroundColor: "rgba(16, 185, 129, 0.15)",
    color: "#10b981",
    padding: "2px 6px",
    borderRadius: "4px",
    fontWeight: 700,
  },
  amenityRow: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "10px 12px",
    backgroundColor: "rgba(255, 255, 255, 0.03)",
    border: "1px solid rgba(255, 255, 255, 0.05)",
    borderRadius: "10px",
  },
  amenityIconBox: {
    width: "28px",
    height: "28px",
    borderRadius: "8px",
    backgroundColor: "rgba(56, 189, 248, 0.1)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  onRouteTag: {
    fontSize: "0.62rem",
    color: "#38bdf8",
    backgroundColor: "rgba(56, 189, 248, 0.12)",
    padding: "2px 6px",
    borderRadius: "4px",
    fontWeight: 700,
  },
  emptyState: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: "30px 16px",
    gap: "8px",
    color: "#64748b",
    fontSize: "0.78rem",
    textAlign: "center",
  },
};
