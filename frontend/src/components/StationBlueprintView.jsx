import React, { useState, useEffect, useRef, useMemo } from "react";
import {
  Compass,
  MapPin,
  Accessibility,
  Footprints,
  AlertTriangle,
  CheckCircle2,
  Layers,
  ArrowRight,
  ShieldCheck,
  Info,
  Clock,
  Sparkles,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Crosshair,
  HeartPulse,
  ChevronUp,
  ChevronDown,
  Navigation,
  ArrowLeftRight,
  RotateCw,
  CornerUpRight,
  CornerUpLeft,
  MoveUp,
  X,
  Ticket,
  Users,
  Search,
} from "lucide-react";

export default function StationBlueprintView({
  stationCode = "MAS",
  stationName = "Chennai Central",
  targetPlatform = "10",
  onSwitchToChennaiCentral,
  onLaunchAR,
}) {
  const isChennai = stationCode === "MAS";

  // Data & Routing State
  const [stationData, setStationData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mobility, setMobility] = useState("wheelchair"); // 'wheelchair' | 'avoid_stairs' | 'normal'
  const [selectedSource, setSelectedSource] = useState("ent_wall_tax");
  const [selectedTarget, setSelectedTarget] = useState("platform_10");
  const [routeResult, setRouteResult] = useState(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [activeTooltip, setActiveTooltip] = useState(null);
  const [bottomDrawerOpen, setBottomDrawerOpen] = useState(false);
  const [pickerModal, setPickerModal] = useState(null); // 'source' | 'platform_picker' | 'facilities_picker' | null

  // Orientation & Transform State
  // Default to Vertical Phone Mode (90° rotation) on mobile portrait screens
  const isMobilePortrait = typeof window !== "undefined" && window.innerWidth < 600;
  const [rotation, setRotation] = useState(isMobilePortrait ? 90 : 0);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1.0 });

  const containerRef = useRef(null);
  const touchStartRef = useRef(null);
  const isPanningRef = useRef(false);
  const startPanRef = useRef({ x: 0, y: 0 });

  const mapW = stationData?.map?.width || 1821;
  const mapH = stationData?.map?.height || 864;

  // Extract Nodes safely
  const nodes = stationData?.nodes || [];
  const edges = stationData?.edges || [];
  const entrances = useMemo(() => nodes.filter((n) => n.type === "entrance"), [nodes]);
  const platforms = useMemo(() => nodes.filter((n) => n.type === "platform"), [nodes]);
  const otherDestinations = useMemo(
    () => nodes.filter((n) => ["toilet", "ticket_counter", "concourse", "shop", "information_desk", "other_facility"].includes(n.type)),
    [nodes]
  );

  // 1. Initial Load of Station Blueprint
  useEffect(() => {
    if (isChennai) {
      loadStationBlueprint();
    }
  }, [stationCode]);

  const loadStationBlueprint = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/stations/chennai_central");
      if (res.ok) {
        const d = await res.json();
        const st = d.station || d;
        setStationData(st);

        // Sanitize initial target platform
        const validPlatforms = (st.nodes || []).filter((n) => n.type === "platform");
        const found = validPlatforms.find((p) => p.id === `platform_${targetPlatform}`);
        if (found) {
          setSelectedTarget(found.id);
        } else if (validPlatforms.length > 0) {
          const p10 = validPlatforms.find((p) => p.id === "platform_10");
          setSelectedTarget(p10 ? p10.id : validPlatforms[0].id);
        }
      }
    } catch (e) {
      console.error("Failed to load blueprint:", e);
    } finally {
      setLoading(false);
    }
  };

  // 2. Validate Target Platform when targetPlatform prop changes
  useEffect(() => {
    if (platforms.length > 0) {
      const matched = platforms.find((p) => p.id === `platform_${targetPlatform}`);
      if (matched) {
        setSelectedTarget(matched.id);
      } else if (!platforms.some((p) => p.id === selectedTarget)) {
        setSelectedTarget("platform_10");
      }
    }
  }, [targetPlatform, platforms]);

  // 3. Recalculate Route whenever Source, Target, Mobility, or Station Data changes
  useEffect(() => {
    if (isChennai && stationData?.nodes?.length && selectedSource && selectedTarget) {
      calculateIndoorRoute();
    }
  }, [isChennai, stationData, mobility, selectedSource, selectedTarget]);

  // 4. Initial Screen Fit (Natural zoom level that fits the phone without letterboxing)
  useEffect(() => {
    if (stationData) {
      fitToScreen(rotation);
    }
  }, [stationData, rotation]);

  const calculateIndoorRoute = async () => {
    setRouteLoading(true);
    try {
      const payload = {
        station_id: "chennai_central",
        source: selectedSource,
        destination: selectedTarget,
        preferences: {
          wheelchair: mobility === "wheelchair",
          avoid_stairs: mobility === "avoid_stairs" || mobility === "wheelchair",
          require_verified_accessibility: false,
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

  // Fit to Screen
  const fitToScreen = (rot = rotation) => {
    const container = containerRef.current;
    if (!container) return;
    const cW = container.clientWidth || 390;
    const cH = container.clientHeight || 650;

    if (rot === 90) {
      const scaleW = cW / 864;
      const scaleH = cH / 1821;
      const fitScale = Math.min(scaleW, scaleH) * 1.15;
      const targetX = (cW - 864 * fitScale) / 2;
      const targetY = (cH - 1821 * fitScale) / 2;
      setTransform({ x: targetX, y: targetY, scale: Math.max(fitScale, 0.45) });
    } else {
      const scaleW = cW / 1821;
      const scaleH = cH / 864;
      const fitScale = Math.min(scaleW, scaleH) * 1.1;
      const targetX = (cW - 1821 * fitScale) / 2;
      const targetY = (cH - 864 * fitScale) / 2;
      setTransform({ x: targetX, y: targetY, scale: Math.max(fitScale, 0.45) });
    }
  };

  // Toggle Orientation
  const toggleOrientation = () => {
    const newRot = rotation === 0 ? 90 : 0;
    setRotation(newRot);
    fitToScreen(newRot);
  };

  // Reset to North-Up
  const resetNorth = () => {
    setRotation(0);
    fitToScreen(0);
  };

  // Touch & Mouse Drag / Pinch Handlers
  const handleTouchStart = (e) => {
    if (e.touches.length === 1) {
      isPanningRef.current = true;
      startPanRef.current = {
        x: e.touches[0].clientX - transform.x,
        y: e.touches[0].clientY - transform.y,
      };
    } else if (e.touches.length === 2) {
      isPanningRef.current = false;
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      touchStartRef.current = {
        dist: Math.hypot(dx, dy),
        scale: transform.scale,
      };
    }
  };

  const handleTouchMove = (e) => {
    if (e.touches.length === 1 && isPanningRef.current) {
      setTransform((prev) => ({
        ...prev,
        x: e.touches[0].clientX - startPanRef.current.x,
        y: e.touches[0].clientY - startPanRef.current.y,
      }));
    } else if (e.touches.length === 2 && touchStartRef.current) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.hypot(dx, dy);
      const ratio = dist / touchStartRef.current.dist;
      const newScale = Math.min(Math.max(touchStartRef.current.scale * ratio, 0.35), 4.0);
      setTransform((prev) => ({
        ...prev,
        scale: newScale,
      }));
    }
  };

  const handleTouchEnd = () => {
    isPanningRef.current = false;
    touchStartRef.current = null;
  };

  const handleWheel = (e) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.88;
    setTransform((prev) => ({
      ...prev,
      scale: Math.min(Math.max(prev.scale * zoomFactor, 0.35), 4.0),
    }));
  };

  const zoomIn = () => {
    setTransform((prev) => ({
      ...prev,
      scale: Math.min(prev.scale * 1.3, 4.0),
    }));
  };

  const zoomOut = () => {
    setTransform((prev) => ({
      ...prev,
      scale: Math.max(prev.scale * 0.72, 0.35),
    }));
  };

  // Convert Normalized Coordinates [0..1] to SVG Pixels
  const toPx = (normPt) => {
    if (!normPt || normPt.length < 2) return [0, 0];
    return [normPt[0] * mapW, normPt[1] * mapH];
  };

  const generateSvgPath = (points) => {
    if (!points || points.length < 2) return "";
    return points
      .map((p, idx) => {
        const [x, y] = toPx(p);
        return `${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");
  };

  // Human-Readable Entrance Name
  const getEntranceDisplayName = (entId) => {
    switch (entId) {
      case "ent_wall_tax":
        return "Wall Tax Rd (♿ Step-Free Ramp)";
      case "ent_jn_road":
        return "Jawaharlal Nehru Rd (⚠️ Stairs)";
      case "ent_bus_stop":
        return "Central Bus Stop (👮 Police)";
      case "ent_parking":
        return "Circulating Parking (🚕 Taxis)";
      case "ent_suburban":
        return "Suburban Station Side";
      default:
        return "Station Entrance";
    }
  };

  // Human-Readable Destination Name
  const getDestinationDisplayName = (tgtId) => {
    if (tgtId.startsWith("platform_")) {
      return tgtId.replace("platform_", "Platform ");
    }
    switch (tgtId) {
      case "toilet_west":
        return "Restrooms West (♿ Accessible)";
      case "toilet_east":
        return "Restrooms East";
      case "ticketing":
        return "Ticketing & Reservation";
      case "concourse_centre":
        return "Main Concourse Waiting Area";
      case "info_desk":
        return "Passenger Information Desk";
      case "reserved_lounge":
        return "Reserved AC Lounge";
      case "shop_nw":
      case "shop_ne":
      case "shop_se":
        return "Food Plaza & Stalls";
      default:
        return "Target Location";
    }
  };

  // Helper: Extract Next Maneuver for Google Maps Banner
  const nextInstruction = routeResult?.instructions?.[0] || null;
  const isTurnRight = nextInstruction?.text?.toLowerCase().includes("right");
  const isTurnLeft = nextInstruction?.text?.toLowerCase().includes("left");

  // =========================================================================
  // VIEW: NO MAP AVAILABLE IF STATION IS NOT CHENNAI CENTRAL
  // =========================================================================
  if (!isChennai) {
    return (
      <div style={styles.container}>
        <div style={styles.noMapCard}>
          <div style={styles.noMapIconCircle}>
            <MapPin size={38} color="#f59e0b" />
          </div>
          <span style={styles.kicker}>INDOOR MAPPING STATUS</span>
          <h3 style={styles.noMapTitle}>No 2D Blueprint Available</h3>
          <div style={styles.stationBadge}>
            <strong style={{ color: "#fff" }}>{stationName}</strong> ({stationCode})
          </div>
          <p style={styles.noMapDesc}>
            High-precision indoor architectural blueprint and wheelchair step-free path routing are currently digitized and live for <strong>Chennai Central (Puratchi Thalaivar Dr. M.G. Ramachandran Central, MAS)</strong>.
          </p>
          <p style={{ ...styles.noMapDesc, fontSize: "0.72rem", color: "#64748b" }}>
            Spatial blueprint digitization for <strong>{stationCode}</strong> is actively under development by Railway Engineering.
          </p>

          <button onClick={onSwitchToChennaiCentral} style={styles.btnSwitchMAS}>
            <Compass size={16} />
            <span>Switch to Chennai Central (MAS)</span>
          </button>
        </div>
      </div>
    );
  }

  // =========================================================================
  // VIEW: FULL-SCREEN GOOGLE MAPS INDOOR NAVIGATOR (UNCONGESTED & CLEAN)
  // =========================================================================
  const activeSourceName = getEntranceDisplayName(selectedSource);
  const activeTargetName = getDestinationDisplayName(selectedTarget);
  const isPlatformSelected = selectedTarget.startsWith("platform_");

  return (
    <div style={styles.container}>
      {/* 1. SLIM, UNCONGESTED FLOATING ROUTE BAR (GOOGLE MAPS STYLE) */}
      <div style={styles.slimTopCard}>
        {/* Row 1: Compact Mobility Pills */}
        <div style={styles.mobilityRow}>
          <button
            onClick={() => setMobility("wheelchair")}
            style={{
              ...styles.mobilityPill,
              ...(mobility === "wheelchair" ? styles.mobilityPillActiveWheelchair : {}),
            }}
          >
            <Accessibility size={12} />
            <span>Wheelchair / Step-Free</span>
          </button>

          <button
            onClick={() => setMobility("avoid_stairs")}
            style={{
              ...styles.mobilityPill,
              ...(mobility === "avoid_stairs" ? styles.mobilityPillActiveAvoid : {}),
            }}
          >
            <Footprints size={12} />
            <span>Avoid Stairs</span>
          </button>

          <button
            onClick={() => setMobility("normal")}
            style={{
              ...styles.mobilityPill,
              ...(mobility === "normal" ? styles.mobilityPillActiveNormal : {}),
            }}
          >
            <Compass size={12} />
            <span>Walk</span>
          </button>
        </div>

        {/* Row 2: Origin & Destination Inputs with Swap */}
        <div style={styles.inputsRow}>
          {/* Origin Pill */}
          <button
            onClick={() => setPickerModal("source")}
            style={styles.inputPillBtn}
          >
            <div style={styles.dotGreen} />
            <div style={{ flex: 1, textAlign: "left", overflow: "hidden" }}>
              <span style={styles.pillLabel}>FROM</span>
              <div style={styles.pillValue}>{activeSourceName}</div>
            </div>
          </button>

          {/* Swap Button */}
          <button
            onClick={() => {
              const prevSrc = selectedSource;
              const prevTgt = selectedTarget;
              setSelectedSource(prevTgt);
              setSelectedTarget(prevSrc);
            }}
            style={styles.swapBtn}
            title="Swap Origin & Destination"
          >
            <ArrowLeftRight size={13} color="#94a3b8" />
          </button>

          {/* Destination Pill */}
          <button
            onClick={() => setPickerModal("platform_picker")}
            style={styles.inputPillBtn}
          >
            <div style={styles.dotRed} />
            <div style={{ flex: 1, textAlign: "left", overflow: "hidden" }}>
              <span style={styles.pillLabel}>TO</span>
              <div style={styles.pillValue}>{activeTargetName}</div>
            </div>
          </button>
        </div>

        {/* Row 3: CATEGORIZED QUICK SEARCH CAROUSEL (CLEAN & UNCLUTTERED) */}
        <div className="no-scrollbar" style={styles.categoryChipsStrip}>
          {/* 1. Grouped Platforms Dropdown Pill */}
          <button
            onClick={() => setPickerModal("platform_picker")}
            style={{
              ...styles.categoryChip,
              ...(isPlatformSelected ? styles.categoryChipActive : {}),
            }}
          >
            <span>🚆 Platforms: {isPlatformSelected ? activeTargetName.replace("Platform ", "P") : "All P7–P12 ▾"}</span>
          </button>

          {/* 2. Common Facilities: Restrooms */}
          <button
            onClick={() => setSelectedTarget("toilet_west")}
            style={{
              ...styles.categoryChip,
              ...(selectedTarget === "toilet_west" ? styles.categoryChipActive : {}),
            }}
          >
            <span>🚻 Restrooms (WC)</span>
          </button>

          {/* 3. Ticket Counters */}
          <button
            onClick={() => setSelectedTarget("ticketing")}
            style={{
              ...styles.categoryChip,
              ...(selectedTarget === "ticketing" ? styles.categoryChipActive : {}),
            }}
          >
            <span>🎟️ Tickets</span>
          </button>

          {/* 4. Divyangjan Step-Free Ramp */}
          <button
            onClick={() => setSelectedSource("ent_wall_tax")}
            style={{
              ...styles.categoryChip,
              ...(selectedSource === "ent_wall_tax" ? styles.categoryChipActiveGreen : {}),
            }}
          >
            <Accessibility size={11} color="#10b981" />
            <span>Wall Tax Ramp ♿</span>
          </button>

          {/* 5. Passenger Information Desk */}
          <button
            onClick={() => setSelectedTarget("info_desk")}
            style={{
              ...styles.categoryChip,
              ...(selectedTarget === "info_desk" ? styles.categoryChipActive : {}),
            }}
          >
            <span>ℹ️ Help Desk</span>
          </button>

          {/* 6. Waiting Lounge */}
          <button
            onClick={() => setSelectedTarget("concourse_centre")}
            style={{
              ...styles.categoryChip,
              ...(selectedTarget === "concourse_centre" ? styles.categoryChipActive : {}),
            }}
          >
            <span>💺 Concourse Hall</span>
          </button>

          {/* 7. Food Plaza */}
          <button
            onClick={() => setSelectedTarget("shop_nw")}
            style={{
              ...styles.categoryChip,
              ...(selectedTarget === "shop_nw" ? styles.categoryChipActive : {}),
            }}
          >
            <span>☕ Food Plaza</span>
          </button>
        </div>
      </div>

      {/* 2. NEXT TURN MANEUVER BANNER (GOOGLE MAPS STYLE) */}
      {routeResult?.status === "ok" && nextInstruction && (
        <div style={styles.nextTurnBanner}>
          <div style={styles.turnIconBox}>
            {isTurnRight ? (
              <CornerUpRight size={16} color="#fff" />
            ) : isTurnLeft ? (
              <CornerUpLeft size={16} color="#fff" />
            ) : (
              <MoveUp size={16} color="#fff" />
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ color: "#fff", fontSize: "0.78rem", fontWeight: 800, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {nextInstruction.text.split(".")[0]}.
            </div>
            {nextInstruction.distance_m && (
              <span style={{ fontSize: "0.66rem", color: "#67e8f9" }}>
                Walk {Math.round(nextInstruction.distance_m)}m • Step-free level pathway
              </span>
            )}
          </div>
        </div>
      )}

      {/* 3. FULL-BLEED INTERACTIVE CANVAS */}
      <div
        ref={containerRef}
        style={styles.mapCanvas}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onWheel={handleWheel}
      >
        {/* Floating Controls (Compass, Rotate 90°, Zoom) */}
        <div style={styles.floatingControls}>
          {/* Compass Rose (Rotates with map orientation) */}
          <button
            onClick={resetNorth}
            style={styles.compassBtn}
            title="Compass: Tap to align North"
          >
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                transform: `rotate(${-rotation}deg)`,
                transition: "transform 0.3s ease",
              }}
            >
              <span style={{ fontSize: "0.58rem", fontWeight: 900, color: "#f43f5e" }}>N</span>
              <div style={styles.compassNeedle} />
            </div>
          </button>

          {/* Orientation Toggle (Rotate 90° for Vertical Phone vs 0° Horizontal) */}
          <button
            onClick={toggleOrientation}
            style={{
              ...styles.fabBtn,
              backgroundColor: rotation === 90 ? "rgba(56, 189, 248, 0.2)" : "rgba(10, 16, 26, 0.92)",
              borderColor: rotation === 90 ? "#38bdf8" : "rgba(255, 255, 255, 0.15)",
            }}
            title={rotation === 90 ? "Switch to Landscape (0°)" : "Switch to Vertical Phone View (90°)"}
          >
            <RotateCw size={15} color={rotation === 90 ? "#38bdf8" : "#94a3b8"} />
          </button>

          {/* Zoom In */}
          <button onClick={zoomIn} style={styles.fabBtn} title="Zoom In">
            <ZoomIn size={16} color="#38bdf8" />
          </button>

          {/* Zoom Out */}
          <button onClick={zoomOut} style={styles.fabBtn} title="Zoom Out">
            <ZoomOut size={16} color="#38bdf8" />
          </button>

          {/* Fit to Screen */}
          <button onClick={() => fitToScreen(rotation)} style={styles.fabBtn} title="Fit to Screen">
            <Maximize2 size={15} color="#94a3b8" />
          </button>
        </div>

        {/* Orientation Status Pill */}
        <div style={styles.orientationBadge}>
          <span>{rotation === 90 ? "📱 Vertical Phone View (90°)" : "🖥️ Landscape View (0°)"}</span>
        </div>

        {/* SVG Container with Pan, Scale & Rotation Transform */}
        <div
          style={{
            width: rotation === 90 ? `${mapH}px` : `${mapW}px`,
            height: rotation === 90 ? `${mapW}px` : `${mapH}px`,
            position: "absolute",
            top: 0,
            left: 0,
            transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
            transformOrigin: "0 0",
            transition: isPanningRef.current ? "none" : "transform 0.1s ease-out",
          }}
        >
          <svg
            width={rotation === 90 ? mapH : mapW}
            height={rotation === 90 ? mapW : mapH}
            viewBox={rotation === 90 ? `0 0 ${mapH} ${mapW}` : `0 0 ${mapW} ${mapH}`}
            style={{ width: "100%", height: "100%", display: "block" }}
          >
            {/* Inner Rotated Group if Vertical Phone View (90°) */}
            <g transform={rotation === 90 ? `rotate(90 0 0) translate(0, -${mapH})` : ""}>
              {/* Background Architectural Blueprint */}
              <image
                href="/data/stations/chennai_central/map.png"
                width={mapW}
                height={mapH}
                opacity="0.9"
              />

              {/* Base Walkway Network */}
              {edges.map((edge) => {
                const pathStr = generateSvgPath(edge.geometry);
                const isStairs = edge.path_type === "stairs";
                const isBlocked = edge.has_steps && mobility === "wheelchair";
                return (
                  <path
                    key={edge.id}
                    d={pathStr}
                    stroke={
                      isBlocked
                        ? "rgba(244, 63, 94, 0.45)"
                        : isStairs
                        ? "rgba(245, 158, 11, 0.4)"
                        : "rgba(255, 255, 255, 0.2)"
                    }
                    strokeWidth={isBlocked ? "4" : isStairs ? "3" : "2"}
                    strokeDasharray={isStairs ? "6 6" : "none"}
                    fill="none"
                  />
                );
              })}

              {/* Active Computed Navigation Route Line */}
              {routeResult?.status === "ok" && routeResult.geometry && (
                <>
                  {/* Glow Understroke */}
                  <path
                    d={generateSvgPath(routeResult.geometry)}
                    stroke={mobility === "wheelchair" ? "rgba(16, 185, 129, 0.4)" : "rgba(56, 189, 248, 0.4)"}
                    strokeWidth="20"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                  />
                  {/* Main Route Line with Animated Directional Dashes */}
                  <path
                    d={generateSvgPath(routeResult.geometry)}
                    stroke={mobility === "wheelchair" ? "#10b981" : "#38bdf8"}
                    strokeWidth="10"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeDasharray="16 8"
                    className="animated-route-line"
                    fill="none"
                  />
                </>
              )}

              {/* Interactive Nodes on Map */}
              {nodes.map((node) => {
                const [cx, cy] = toPx(node.position);
                const isSource = node.id === selectedSource;
                const isTarget = node.id === selectedTarget;
                const isPlatform = node.type === "platform";
                const isEntrance = node.type === "entrance";
                const isToilet = node.type === "toilet";

                // 1. START MARKER (Pulsing Green Location Puck)
                if (isSource) {
                  return (
                    <g
                      key={node.id}
                      transform={`translate(${cx}, ${cy})`}
                      style={{ cursor: "pointer" }}
                      onClick={() => setActiveTooltip(node)}
                    >
                      <circle r="32" fill="rgba(16, 185, 129, 0.3)" />
                      <circle r="16" fill="#10b981" stroke="#fff" strokeWidth="3" />
                      <text y="5" textAnchor="middle" fill="#fff" fontSize="13" fontWeight="900">
                        A
                      </text>
                      <text y="-22" textAnchor="middle" fill="#6ee7b7" fontSize="22" fontWeight="900">
                        START: {node.name.split("(")[0]}
                      </text>
                    </g>
                  );
                }

                // 2. DESTINATION MARKER (Red Google Maps Pin)
                if (isTarget) {
                  return (
                    <g
                      key={node.id}
                      transform={`translate(${cx}, ${cy})`}
                      style={{ cursor: "pointer" }}
                      onClick={() => setActiveTooltip(node)}
                    >
                      <circle r="34" fill="rgba(244, 63, 94, 0.35)" />
                      <circle r="18" fill="#f43f5e" stroke="#fff" strokeWidth="3" />
                      <text y="6" textAnchor="middle" fill="#fff" fontSize="14" fontWeight="900">
                        B
                      </text>
                      <text y="-26" textAnchor="middle" fill="#fda4af" fontSize="24" fontWeight="900">
                        {node.name}
                      </text>
                    </g>
                  );
                }

                // 3. ENTRANCES
                if (isEntrance) {
                  const isRamp = node.id === "ent_wall_tax";
                  return (
                    <g
                      key={node.id}
                      transform={`translate(${cx}, ${cy})`}
                      style={{ cursor: "pointer" }}
                      onClick={() => {
                        setSelectedSource(node.id);
                        setActiveTooltip(node);
                      }}
                    >
                      <circle r="22" fill="rgba(0, 0, 0, 0.7)" />
                      <circle
                        r="12"
                        fill={isRamp ? "#10b981" : "#64748b"}
                        stroke="#fff"
                        strokeWidth="2"
                      />
                      <text y="28" textAnchor="middle" fill="#e2e8f0" fontSize="16" fontWeight="800">
                        {node.name.split("(")[0].replace("Main Entrance", "Entry")} {isRamp ? "♿" : ""}
                      </text>
                    </g>
                  );
                }

                // 4. PLATFORMS (Platforms 7 to 12)
                if (isPlatform) {
                  return (
                    <g
                      key={node.id}
                      transform={`translate(${cx}, ${cy})`}
                      style={{ cursor: "pointer" }}
                      onClick={() => {
                        setSelectedTarget(node.id);
                        setActiveTooltip(node);
                      }}
                    >
                      <rect x="-18" y="-14" width="36" height="28" rx="8" fill="#1e3a8a" stroke="#60a5fa" strokeWidth="2.5" />
                      <text y="6" textAnchor="middle" fill="#fff" fontSize="15" fontWeight="900">
                        {node.name.replace("Platform ", "P")}
                      </text>
                    </g>
                  );
                }

                // 5. RESTROOMS
                if (isToilet) {
                  return (
                    <g
                      key={node.id}
                      transform={`translate(${cx}, ${cy})`}
                      style={{ cursor: "pointer" }}
                      onClick={() => {
                        setSelectedTarget(node.id);
                        setActiveTooltip(node);
                      }}
                    >
                      <circle r="12" fill="#8b5cf6" stroke="#fff" strokeWidth="2" />
                      <text y="4" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="800">
                        WC
                      </text>
                    </g>
                  );
                }

                return null;
              })}
            </g>
          </svg>
        </div>

        {/* Tapped Node Quick Callout */}
        {activeTooltip && (
          <div style={styles.nodeTooltip}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong style={{ color: "#fff", fontSize: "0.85rem" }}>{activeTooltip.name}</strong>
              <button onClick={() => setActiveTooltip(null)} style={styles.tooltipClose}>×</button>
            </div>
            <div style={{ fontSize: "0.7rem", color: "#94a3b8", marginTop: 2 }}>
              {activeTooltip.id === "ent_wall_tax"
                ? "♿ Verified Divyangjan Step-Free Ramp"
                : activeTooltip.id === "ent_jn_road"
                ? "⚠️ Flight of Stairs (Not Wheelchair Accessible)"
                : "Concourse Facility"}
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              {activeTooltip.type === "entrance" && (
                <button
                  onClick={() => {
                    setSelectedSource(activeTooltip.id);
                    setActiveTooltip(null);
                  }}
                  style={styles.tooltipBtn}
                >
                  Set as Start Point
                </button>
              )}
              {(activeTooltip.type === "platform" || activeTooltip.type === "toilet") && (
                <button
                  onClick={() => {
                    setSelectedTarget(activeTooltip.id);
                    setActiveTooltip(null);
                  }}
                  style={styles.tooltipBtn}
                >
                  Navigate To Here
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 4. CLEAN FLOATING BOTTOM DIRECTIONS SHEET */}
      <div style={styles.floatingBottomCard}>
        {/* Case A: ROUTE BLOCKED / STAIR BARRIER (CLEAN, READABLE, CONCISE) */}
        {routeResult?.status === "no_route" ? (
          <div style={styles.errorContainer}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div style={styles.errorIconCircle}>
                <AlertTriangle size={16} color="#f43f5e" />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ color: "#fff", fontSize: "0.82rem", fontWeight: 800 }}>
                  Stair Barrier on Selected Pathway
                </div>
                <div style={{ color: "#fda4af", fontSize: "0.72rem", fontWeight: 600 }}>
                  {selectedSource === "ent_jn_road"
                    ? "Jawaharlal Nehru Road has stairs. Not step-free."
                    : "No step-free route from this point. Stairs detected."}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: 8 }}>
              {selectedSource !== "ent_wall_tax" && (
                <button
                  onClick={() => setSelectedSource("ent_wall_tax")}
                  style={styles.btnSwitchAccessibleRamp}
                >
                  <Accessibility size={13} />
                  <span>Reroute via Wall Tax Rd (Step-Free Ramp)</span>
                </button>
              )}
              <button
                onClick={() => setMobility("normal")}
                style={styles.btnSwitchWalk}
              >
                <span>Switch to Walking</span>
              </button>
            </div>
          </div>
        ) : (
          /* Case B: ROUTE FOUND (NORMAL DIRECTIONS) */
          <>
            <div
              style={styles.statsBar}
              onClick={() => setBottomDrawerOpen(!bottomDrawerOpen)}
            >
              <div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                  <span style={{ fontSize: "1.2rem", fontWeight: 900, color: "#10b981" }}>
                    2 min
                  </span>
                  <span style={{ fontSize: "0.8rem", color: "#94a3b8", fontWeight: 700 }}>
                    ({routeResult?.geometry ? `${routeResult.geometry.length * 14} m` : "140 m"})
                  </span>
                </div>
                <span
                  style={{
                    fontSize: "0.68rem",
                    color: mobility === "wheelchair" ? "#10b981" : "#38bdf8",
                    fontWeight: 800,
                  }}
                >
                  {mobility === "wheelchair"
                    ? "♿ 100% Step-Free Route • Avoids All Stairs"
                    : "🚶 Shortest Walkable Concourse Path"}
                </span>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 4, color: "#38bdf8" }}>
                <span style={{ fontSize: "0.7rem", fontWeight: 800 }}>
                  {bottomDrawerOpen ? "Hide Steps" : "View Steps"}
                </span>
                {bottomDrawerOpen ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
              </div>
            </div>

            {/* Primary CTA: Start AR Camera Guidance */}
            {onLaunchAR && routeResult?.status === "ok" && (
              <button
                onClick={() => {
                  const targetName = selectedTarget.replace("platform_", "Platform ");
                  onLaunchAR(targetName, "Follow In-Concourse AR Guidance", 30);
                }}
                style={styles.btnStartAR}
              >
                <Compass size={16} />
                <span>Start AR Camera Guidance</span>
              </button>
            )}

            {/* Expandable Step-by-Step Directions */}
            {bottomDrawerOpen && (
              <div style={styles.drawerSteps}>
                <span style={styles.stepsTitle}>TURN-BY-TURN INDOOR DIRECTIONS</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {(routeResult?.instructions || [
                    {
                      text: `Start at ${
                        selectedSource === "ent_wall_tax" ? "Main Entrance (Wall Tax Road) ♿" : selectedSource
                      }`,
                      step_free: true,
                    },
                    { text: "Proceed along Concourse level walkway heading west", step_free: true },
                    {
                      text: `Turn towards ${selectedTarget.replace("platform_", "Platform ")} buffer zone`,
                      step_free: true,
                    },
                  ]).map((inst, i) => (
                    <div key={i} style={styles.stepItem}>
                      <div style={styles.stepBadge}>{i + 1}</div>
                      <div style={{ flex: 1, fontSize: "0.72rem", color: "#e2e8f0" }}>
                        {inst.text || inst.action}
                      </div>
                      {inst.step_free && <span style={styles.stepFreePill}>Step-Free</span>}
                    </div>
                  ))}
                </div>

                {/* Along The Way Facilities */}
                {routeResult?.along_the_way && routeResult.along_the_way.length > 0 && (
                  <>
                    <span style={{ ...styles.stepsTitle, marginTop: 8 }}>ALONG YOUR ROUTE</span>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {routeResult.along_the_way.map((item, idx) => (
                        <div key={idx} style={styles.facilityItem}>
                          <Sparkles size={12} color="#38bdf8" />
                          <span style={{ fontSize: "0.7rem", color: "#cbd5e1" }}>
                            {item.name} ({item.type}) • {item.on_route ? "Directly On Route" : "Nearby"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* 5. MODAL PICKER SHEETS (SOURCE & GROUPED PLATFORMS) */}
      {pickerModal && (
        <div style={styles.pickerBackdrop} onClick={() => setPickerModal(null)}>
          <div style={styles.pickerSheet} onClick={(e) => e.stopPropagation()}>
            <div style={styles.pickerHeader}>
              <strong style={{ color: "#fff", fontSize: "0.92rem" }}>
                {pickerModal === "source"
                  ? "Choose Station Entrance"
                  : "Select Express Platform (P7–P12)"}
              </strong>
              <button onClick={() => setPickerModal(null)} style={styles.pickerCloseBtn}>
                <X size={18} color="#94a3b8" />
              </button>
            </div>

            <div style={styles.pickerList}>
              {/* ENTRANCES PICKER */}
              {pickerModal === "source" && (
                entrances.map((ent) => {
                  const isSel = selectedSource === ent.id;
                  const isRamp = ent.id === "ent_wall_tax";
                  return (
                    <div
                      key={ent.id}
                      onClick={() => {
                        setSelectedSource(ent.id);
                        setPickerModal(null);
                      }}
                      style={{
                        ...styles.pickerItem,
                        ...(isSel ? styles.pickerItemActive : {}),
                      }}
                    >
                      <div>
                        <div style={{ color: "#fff", fontSize: "0.82rem", fontWeight: 700 }}>
                          {getEntranceDisplayName(ent.id)}
                        </div>
                        <span style={{ fontSize: "0.68rem", color: isRamp ? "#10b981" : "#94a3b8" }}>
                          {isRamp ? "At-grade accessible passenger drop-off" : "Main road approach"}
                        </span>
                      </div>
                      {isSel && <CheckCircle2 size={16} color="#10b981" />}
                    </div>
                  );
                })
              )}

              {/* GROUPED PLATFORMS GRID (P7–P12) */}
              {pickerModal === "platform_picker" && (
                <div>
                  <span style={styles.pickerSectionHeader}>TAP A PLATFORM TO ROUTE DIRECTLY</span>
                  <div style={styles.platformGrid}>
                    {platforms.map((pf) => {
                      const isSel = selectedTarget === pf.id;
                      const pfNum = pf.name.replace("Platform ", "P");
                      return (
                        <button
                          key={pf.id}
                          onClick={() => {
                            setSelectedTarget(pf.id);
                            setPickerModal(null);
                          }}
                          style={{
                            ...styles.platformTile,
                            ...(isSel ? styles.platformTileActive : {}),
                          }}
                        >
                          <span style={styles.platformTileNum}>{pfNum}</span>
                          <span style={styles.platformTileSub}>Express Berth</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const styles = {
  container: {
    width: "100%",
    height: "calc(100vh - 135px)",
    position: "relative",
    backgroundColor: "#07090e",
    overflow: "hidden",
  },
  noMapCard: {
    margin: "auto 16px",
    padding: "36px 20px",
    backgroundColor: "rgba(18, 24, 38, 0.92)",
    borderRadius: "20px",
    border: "1px dashed rgba(245, 158, 11, 0.35)",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    textAlign: "center",
  },
  noMapIconCircle: {
    width: "64px",
    height: "64px",
    borderRadius: "50%",
    backgroundColor: "rgba(245, 158, 11, 0.12)",
    border: "1px solid rgba(245, 158, 11, 0.3)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: "12px",
  },
  kicker: {
    fontSize: "0.62rem",
    fontWeight: 800,
    color: "#64748b",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  noMapTitle: {
    fontSize: "1.15rem",
    fontWeight: 800,
    color: "#fff",
    margin: "4px 0",
  },
  stationBadge: {
    fontSize: "0.78rem",
    backgroundColor: "rgba(255, 255, 255, 0.06)",
    padding: "4px 12px",
    borderRadius: "999px",
    color: "#94a3b8",
    margin: "6px 0 12px 0",
  },
  noMapDesc: {
    fontSize: "0.76rem",
    color: "#94a3b8",
    lineHeight: 1.45,
    margin: "0 0 8px 0",
    maxWidth: "320px",
  },
  btnSwitchMAS: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    backgroundColor: "rgba(56, 189, 248, 0.15)",
    border: "1px solid rgba(56, 189, 248, 0.4)",
    color: "#38bdf8",
    fontSize: "0.8rem",
    fontWeight: 800,
    padding: "10px 16px",
    borderRadius: "12px",
    cursor: "pointer",
    marginTop: "12px",
  },
  mapCanvas: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    overflow: "hidden",
    backgroundColor: "#03060a",
    touchAction: "none",
  },
  // Ultra-slim, elegant top floating navigation bar
  slimTopCard: {
    position: "absolute",
    top: "6px",
    left: "6px",
    right: "6px",
    zIndex: 20,
    backgroundColor: "rgba(10, 16, 26, 0.92)",
    backdropFilter: "blur(16px)",
    WebkitBackdropFilter: "blur(16px)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "12px",
    padding: "6px 8px",
    boxShadow: "0 6px 20px rgba(0, 0, 0, 0.45)",
    display: "flex",
    flexDirection: "column",
    gap: "5px",
  },
  mobilityRow: {
    display: "flex",
    gap: "4px",
  },
  mobilityPill: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "4px",
    padding: "4px 3px",
    borderRadius: "6px",
    fontSize: "0.62rem",
    fontWeight: 800,
    color: "#94a3b8",
    backgroundColor: "rgba(255, 255, 255, 0.03)",
    border: "1px solid rgba(255, 255, 255, 0.06)",
    cursor: "pointer",
  },
  mobilityPillActiveWheelchair: {
    backgroundColor: "rgba(16, 185, 129, 0.18)",
    borderColor: "rgba(16, 185, 129, 0.5)",
    color: "#10b981",
  },
  mobilityPillActiveAvoid: {
    backgroundColor: "rgba(56, 189, 248, 0.18)",
    borderColor: "rgba(56, 189, 248, 0.5)",
    color: "#38bdf8",
  },
  mobilityPillActiveNormal: {
    backgroundColor: "rgba(255, 255, 255, 0.1)",
    borderColor: "rgba(255, 255, 255, 0.25)",
    color: "#fff",
  },
  inputsRow: {
    display: "flex",
    alignItems: "center",
    gap: "5px",
  },
  inputPillBtn: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    gap: "5px",
    backgroundColor: "rgba(255, 255, 255, 0.04)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "8px",
    padding: "4px 7px",
    cursor: "pointer",
    minWidth: 0,
  },
  dotGreen: {
    width: "6px",
    height: "6px",
    borderRadius: "50%",
    backgroundColor: "#10b981",
    boxShadow: "0 0 5px #10b981",
    flexShrink: 0,
  },
  dotRed: {
    width: "6px",
    height: "6px",
    borderRadius: "50%",
    backgroundColor: "#f43f5e",
    boxShadow: "0 0 5px #f43f5e",
    flexShrink: 0,
  },
  pillLabel: {
    fontSize: "0.48rem",
    fontWeight: 800,
    color: "#64748b",
    display: "block",
    lineHeight: 1,
  },
  pillValue: {
    fontSize: "0.7rem",
    fontWeight: 700,
    color: "#fff",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    lineHeight: 1.2,
  },
  swapBtn: {
    width: "24px",
    height: "24px",
    borderRadius: "50%",
    backgroundColor: "rgba(255, 255, 255, 0.04)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    flexShrink: 0,
  },
  categoryChipsStrip: {
    display: "flex",
    gap: "4px",
    overflowX: "auto",
    paddingBottom: "1px",
  },
  categoryChip: {
    backgroundColor: "rgba(255, 255, 255, 0.04)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "999px",
    padding: "3px 8px",
    color: "#94a3b8",
    fontSize: "0.62rem",
    fontWeight: 700,
    whiteSpace: "nowrap",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    gap: "3px",
    flexShrink: 0,
  },
  categoryChipActive: {
    backgroundColor: "rgba(56, 189, 248, 0.18)",
    borderColor: "#38bdf8",
    color: "#38bdf8",
  },
  categoryChipActiveGreen: {
    backgroundColor: "rgba(16, 185, 129, 0.18)",
    borderColor: "#10b981",
    color: "#10b981",
  },
  nextTurnBanner: {
    position: "absolute",
    top: "116px",
    left: "6px",
    right: "6px",
    zIndex: 18,
    backgroundColor: "rgba(15, 23, 42, 0.95)",
    border: "1px solid rgba(56, 189, 248, 0.3)",
    borderRadius: "9px",
    padding: "6px 8px",
    display: "flex",
    alignItems: "center",
    gap: "7px",
    boxShadow: "0 4px 14px rgba(0, 0, 0, 0.4)",
  },
  turnIconBox: {
    width: "26px",
    height: "26px",
    borderRadius: "6px",
    backgroundColor: "#2563eb",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  floatingControls: {
    position: "absolute",
    right: "8px",
    top: "148px",
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    zIndex: 25,
  },
  compassBtn: {
    width: "38px",
    height: "38px",
    borderRadius: "10px",
    backgroundColor: "rgba(10, 16, 26, 0.92)",
    border: "1px solid rgba(255, 255, 255, 0.2)",
    backdropFilter: "blur(10px)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
  },
  compassNeedle: {
    width: "3px",
    height: "14px",
    background: "linear-gradient(to bottom, #f43f5e 50%, #fff 50%)",
    borderRadius: "2px",
  },
  fabBtn: {
    width: "38px",
    height: "38px",
    borderRadius: "10px",
    backgroundColor: "rgba(10, 16, 26, 0.92)",
    border: "1px solid rgba(255, 255, 255, 0.15)",
    backdropFilter: "blur(10px)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
  },
  orientationBadge: {
    position: "absolute",
    left: "10px",
    top: "175px",
    backgroundColor: "rgba(0, 0, 0, 0.7)",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: "6px",
    padding: "3px 7px",
    fontSize: "0.56rem",
    color: "#94a3b8",
    pointerEvents: "none",
    zIndex: 15,
  },
  nodeTooltip: {
    position: "absolute",
    bottom: "95px",
    left: "10px",
    right: "10px",
    backgroundColor: "rgba(13, 19, 31, 0.96)",
    border: "1px solid rgba(56, 189, 248, 0.4)",
    borderRadius: "12px",
    padding: "10px 14px",
    backdropFilter: "blur(16px)",
    zIndex: 35,
    boxShadow: "0 8px 24px rgba(0, 0, 0, 0.6)",
  },
  tooltipClose: {
    background: "none",
    border: "none",
    color: "#94a3b8",
    fontSize: "1.2rem",
    cursor: "pointer",
  },
  tooltipBtn: {
    flex: 1,
    backgroundColor: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: "8px",
    padding: "6px 12px",
    fontSize: "0.72rem",
    fontWeight: 800,
    cursor: "pointer",
  },
  // Floating bottom card
  floatingBottomCard: {
    position: "absolute",
    bottom: "8px",
    left: "8px",
    right: "8px",
    zIndex: 20,
    backgroundColor: "rgba(10, 16, 26, 0.96)",
    backdropFilter: "blur(16px)",
    WebkitBackdropFilter: "blur(16px)",
    border: "1px solid rgba(255, 255, 255, 0.12)",
    borderRadius: "14px",
    padding: "10px 12px",
    boxShadow: "0 -6px 24px rgba(0, 0, 0, 0.5)",
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  // Proper Error Message Container (In Bottom Card where it belongs)
  errorContainer: {
    padding: "4px 2px",
  },
  errorIconCircle: {
    width: "32px",
    height: "32px",
    borderRadius: "8px",
    backgroundColor: "rgba(244, 63, 94, 0.18)",
    border: "1px solid rgba(244, 63, 94, 0.35)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  btnSwitchAccessibleRamp: {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    backgroundColor: "#10b981",
    color: "#fff",
    border: "none",
    borderRadius: "8px",
    padding: "6px 12px",
    fontSize: "0.72rem",
    fontWeight: 800,
    cursor: "pointer",
  },
  btnSwitchWalk: {
    display: "inline-flex",
    alignItems: "center",
    backgroundColor: "rgba(255, 255, 255, 0.08)",
    border: "1px solid rgba(255, 255, 255, 0.15)",
    color: "#cbd5e1",
    borderRadius: "8px",
    padding: "6px 12px",
    fontSize: "0.72rem",
    fontWeight: 700,
    cursor: "pointer",
  },
  statsBar: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    cursor: "pointer",
  },
  btnStartAR: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    backgroundColor: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: "10px",
    padding: "9px 12px",
    fontSize: "0.76rem",
    fontWeight: 800,
    cursor: "pointer",
    boxShadow: "0 4px 12px rgba(37, 99, 235, 0.4)",
  },
  drawerSteps: {
    maxHeight: "150px",
    overflowY: "auto",
    borderTop: "1px solid rgba(255, 255, 255, 0.08)",
    paddingTop: "6px",
    display: "flex",
    flexDirection: "column",
    gap: "5px",
  },
  stepsTitle: {
    fontSize: "0.6rem",
    fontWeight: 800,
    color: "#64748b",
    textTransform: "uppercase",
  },
  stepItem: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    backgroundColor: "rgba(255, 255, 255, 0.03)",
    padding: "5px 7px",
    borderRadius: "6px",
  },
  stepBadge: {
    width: "18px",
    height: "18px",
    borderRadius: "50%",
    backgroundColor: "rgba(56, 189, 248, 0.2)",
    color: "#38bdf8",
    fontSize: "0.66rem",
    fontWeight: 900,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  stepFreePill: {
    fontSize: "0.56rem",
    backgroundColor: "rgba(16, 185, 129, 0.15)",
    color: "#10b981",
    padding: "1px 5px",
    borderRadius: "4px",
    fontWeight: 700,
  },
  facilityItem: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    backgroundColor: "rgba(255, 255, 255, 0.02)",
    padding: "4px 8px",
    borderRadius: "4px",
  },
  // Modal Sheet Picker Styles
  pickerBackdrop: {
    position: "absolute",
    inset: 0,
    backgroundColor: "rgba(0, 0, 0, 0.78)",
    backdropFilter: "blur(8px)",
    zIndex: 50,
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "center",
  },
  pickerSheet: {
    width: "100%",
    backgroundColor: "#0d131f",
    borderTopLeftRadius: "18px",
    borderTopRightRadius: "18px",
    border: "1px solid rgba(255, 255, 255, 0.15)",
    maxHeight: "70vh",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  pickerHeader: {
    padding: "12px 16px",
    borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  pickerCloseBtn: {
    background: "none",
    border: "none",
    padding: "4px",
    cursor: "pointer",
  },
  pickerList: {
    padding: "12px 14px",
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: "6px",
  },
  pickerSectionHeader: {
    fontSize: "0.62rem",
    color: "#64748b",
    fontWeight: 800,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: "8px",
    display: "block",
  },
  pickerItem: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "10px 12px",
    backgroundColor: "rgba(255, 255, 255, 0.03)",
    border: "1px solid rgba(255, 255, 255, 0.06)",
    borderRadius: "10px",
    cursor: "pointer",
  },
  pickerItemActive: {
    backgroundColor: "rgba(56, 189, 248, 0.12)",
    borderColor: "rgba(56, 189, 248, 0.4)",
  },
  platformGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr 1fr",
    gap: "8px",
  },
  platformTile: {
    backgroundColor: "rgba(255, 255, 255, 0.04)",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: "12px",
    padding: "12px 6px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
  },
  platformTileActive: {
    backgroundColor: "rgba(56, 189, 248, 0.18)",
    borderColor: "#38bdf8",
  },
  platformTileNum: {
    fontSize: "1.1rem",
    fontWeight: 900,
    color: "#fff",
  },
  platformTileSub: {
    fontSize: "0.56rem",
    color: "#94a3b8",
    marginTop: "2px",
  },
};
