import React, { useState, useEffect, useRef } from "react";
import {
  Compass,
  Train,
  Clock,
  Layers,
  ArrowRight,
  Radio,
  X,
  Navigation,
  MapPin,
  Calendar,
  Route,
  ArrowLeftRight,
  Sparkles,
  Accessibility,
  Eye,
  Camera,
  Car,
  Footprints,
  ShieldCheck,
  CheckCircle2,
  ChevronRight,
  Layers3,
  Info,
  Search,
  ShieldAlert,
  Map,
  Target,
  MessageSquare,
} from "lucide-react";

import StationBlueprintView from "./components/StationBlueprintView";
import EmergencyHelpModal from "./components/EmergencyHelpModal";
import TicketPlanningModule from "./components/TicketPlanningModule";

// Use relative API_BASE so requests go through Vite HTTPS reverse proxy without mixed-content errors
const API_BASE = "";


const PRESET_STATIONS = [
  { code: "MAS", name: "Chennai Central" },
  { code: "VLCY", name: "Velachery MRTS" },
  { code: "NDLS", name: "New Delhi" },
  { code: "CSMT", name: "Mumbai CSMT" },
  { code: "HWH", name: "Howrah Jn" },
  { code: "SBC", name: "KSR Bengaluru" },
  { code: "CNB", name: "Kanpur Central" },
  { code: "PUNE", name: "Pune Jn" },
  { code: "BSB", name: "Varanasi Jn" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("planner"); // 'planner' | 'wayfinder' | 'blueprint' | 'board'
  const [activeJourney, setActiveJourney] = useState(null); // Set ONLY when passenger clicks Navigate in Planner

  // Global Station Selection (Default: Chennai Central MAS)
  const [stationCode, setStationCode] = useState("MAS");
  const [stationName, setStationName] = useState("Chennai Central");
  const [stationTrains, setStationTrains] = useState([]);
  const [stepFreeOnly, setStepFreeOnly] = useState(false);

  // --- PILLAR 3: TURN-BY-TURN STEPPER STATE ---
  // Steps: 0: Entry Point, 1: Security Screening, 2: Bridge/FOB Crossing, 3: Coach Door
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [stationTopology, setStationTopology] = useState(null);
  const [selectedGate, setSelectedGate] = useState(null);
  const [selectedTrain, setSelectedTrain] = useState(null);
  const [targetCoach, setTargetCoach] = useState("B4");
  const [coachAnalysis, setCoachAnalysis] = useState(null);

  // --- PILLAR 1: PLANNER STATE (Default: MAS to SBC) ---
  const [plannerSubMode, setPlannerSubMode] = useState("goal"); // 'goal' | 'guidance' | 'direct'
  const [planFrom, setPlanFrom] = useState("MAS");
  const [planFromName, setPlanFromName] = useState("Chennai Central");
  const [planTo, setPlanTo] = useState("SBC");
  const [planToName, setPlanToName] = useState("KSR Bengaluru");
  const [planTrains, setPlanTrains] = useState([]);
  const [planLoading, setPlanLoading] = useState(false);
  const [locating, setLocating] = useState(false);
  const [detectedStationMsg, setDetectedStationMsg] = useState(null);

  // Modals
  const [forecastModal, setForecastModal] = useState(null);
  const [forecastLoadingTrain, setForecastLoadingTrain] = useState(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchTarget, setSearchTarget] = useState("global"); // 'global' | 'planFrom' | 'planTo'
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [emergencyModalOpen, setEmergencyModalOpen] = useState(false);

  // --- AR HUD & PROXIMITY SENSORS ---
  const [arOpen, setArOpen] = useState(false);
  const [arTarget, setArTarget] = useState({ title: "Station Entrance", sub: "Walk Ahead", bearing: 30 });
  const [deviceHeading, setDeviceHeading] = useState(0);
  const [camPermError, setCamPermError] = useState(null);
  const [stationCoords, setStationCoords] = useState({ lat: 13.0825, lon: 80.2750 });
  const [userDistanceToStation, setUserDistanceToStation] = useState(null);
  const [tooFarModal, setTooFarModal] = useState(null);
  const [isDemoSimulation, setIsDemoSimulation] = useState(false);
  const videoRef = useRef(null);
  const streamRef = useRef(null);

  // Initial Load: Mount on Planner and fetch initial journey options
  useEffect(() => {
    loadStation(stationCode);
    fetchJourneyPlan(planFrom, planTo);
  }, []);

  const loadStationTopology = async (code, currentPf = null) => {
    try {
      const res = await fetch(`${API_BASE}/stations/${code}/navigation`);
      if (res.ok) {
        const topo = await res.json();
        setStationTopology(topo);
        const pfStr = currentPf ? String(currentPf) : (topo.default_platform || "1");
        const bestGate = topo.entries?.find((e) => e.recommended_for_platforms?.includes(pfStr)) || topo.entries?.[0] || null;
        setSelectedGate(bestGate);
        return topo;
      }
    } catch (e) {
      console.error("Failed to load topology:", e);
    }
    return null;
  };

  const loadStation = async (code) => {
    try {
      loadStationTopology(code);
      const res = await fetch(`${API_BASE}/stations/${code}/live?hours=2`);
      if (res.ok) {
        const d = await res.json();
        setStationTrains(d.trains || []);
        if (d.latitude && d.longitude) {
          setStationCoords({ lat: d.latitude, lon: d.longitude });
        }
        setStationName(d.station_name || code);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchCoachPosition = async (train, coach) => {
    if (!train) return;
    const comp = train.coach_composition || "ENG-LPR-A3-A2-A1-H1-PC-B11-B10-B9-B8-B7-B6-B5-B4-B3-B2-B1-LPR";
    try {
      const r = await fetch(`${API_BASE}/trains/rake-position?coach_composition=${encodeURIComponent(comp)}&target_coach=${encodeURIComponent(coach)}`);
      if (r.ok) {
        const d = await r.json();
        setCoachAnalysis(d);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Planner
  const fetchJourneyPlan = async (from, to) => {
    setPlanLoading(true);
    try {
      const res = await fetch(`${API_BASE}/plan/journey?from_station=${from}&to_station=${to}`);
      if (res.ok) {
        const d = await res.json();
        setPlanTrains(d.trains || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setPlanLoading(false);
    }
  };

  const handleNavigateFromPlanner = async (tr) => {
    let pf = tr.platform && tr.platform !== "0" && tr.platform !== "--" ? String(tr.platform) : null;
    const topo = await loadStationTopology(planFrom, pf);
    if (!pf) {
      pf = topo?.default_platform || topo?.entries?.[0]?.recommended_for_platforms?.[0] || "1";
    }

    const journey = {
      train_number: tr.train_number,
      train_name: tr.train_name,
      from_code: planFrom,
      from_name: planFromName,
      to_code: planTo,
      to_name: planToName,
      departure_time: tr.departure_time,
      arrival_time: tr.arrival_time,
      duration: tr.duration,
      platform: pf,
      coach: targetCoach || "B4",
    };
    setActiveJourney(journey);
    setSelectedTrain({
      ...tr,
      platform: pf,
    });
    setStationCode(planFrom);
    setStationName(planFromName);
    loadStation(planFrom);
    fetchCoachPosition(tr, targetCoach || "B4");
    setCurrentStepIndex(0);
    setActiveTab("wayfinder");
  };

  // Delay Forecast
  const fetchDelayForecast = async (train) => {
    setForecastLoadingTrain(train.train_number);
    try {
      const dest = train.to_station_code || train.destination_code || "CNB";
      const url = `${API_BASE}/predict/delay?train_number=${train.train_number}&train_name=${encodeURIComponent(train.train_name)}&train_type=${encodeURIComponent(train.train_type || 'EXPRESS')}&current_delay=${encodeURIComponent(train.delay_arrival || 'RT')}&destination=${dest}`;
      const res = await fetch(url);
      if (res.ok) {
        setForecastModal(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setForecastLoadingTrain(null);
    }
  };

  // Search
  useEffect(() => {
    if (searchQuery.trim().length < 2) return;
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API_BASE}/stations/search?q=${encodeURIComponent(searchQuery)}`);
        if (r.ok) setSearchResults((await r.json()).results || []);
      } catch (e) {
        console.error(e);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [searchQuery]);

  // GPS Auto-Detect Nearest Station
  const autoDetectLocation = () => {
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your mobile browser");
      return;
    }
    setLocating(true);
    setDetectedStationMsg(null);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const lat = pos.coords.latitude;
          const lon = pos.coords.longitude;
          const res = await fetch(`${API_BASE}/stations/nearest?lat=${lat}&lon=${lon}`);
          if (res.ok) {
            const data = await res.json();
            const nearest = data.nearest;
            if (nearest) {
              setPlanFrom(nearest.code);
              setPlanFromName(nearest.name);
              // Auto-sync current station context for Wayfinder & Live Board
              setStationCode(nearest.code);
              setStationName(nearest.name);
              loadStation(nearest.code);
              fetchJourneyPlan(nearest.code, planTo);
              setDetectedStationMsg(`📍 Auto-detected nearest: ${nearest.name} (${nearest.code}) • ${nearest.distance_km} km away`);
            }
          } else {
            setDetectedStationMsg("No railway stations identified near current GPS coordinates.");
          }
        } catch (err) {
          console.error("GPS station lookup error", err);
          setDetectedStationMsg("Failed to query nearest station.");
        } finally {
          setLocating(false);
        }
      },
      (err) => {
        console.warn("Geolocation error", err);
        setLocating(false);
        setDetectedStationMsg("GPS permission denied or unavailable. Tap 'FROM' to pick manually.");
      },
      { timeout: 10000, enableHighAccuracy: true }
    );
  };

  const handleStationSelect = (s) => {
    if (s.latitude && s.longitude) {
      setStationCoords({ lat: s.latitude, lon: s.longitude });
    }
    if (searchTarget === "planFrom") {
      setPlanFrom(s.code);
      setPlanFromName(s.name);
      // Auto-update station location context
      setStationCode(s.code);
      setStationName(s.name);
      loadStation(s.code);
      fetchJourneyPlan(s.code, planTo);
    } else if (searchTarget === "planTo") {
      setPlanTo(s.code);
      setPlanToName(s.name);
      fetchJourneyPlan(planFrom, s.code);
    } else {
      setStationCode(s.code);
      setStationName(s.name);
      loadStation(s.code);
    }
    setSearchOpen(false);
    setSearchQuery("");
  };

  const calcDistanceKm = (lat1, lon1, lat2, lon2) => {
    if (!lat1 || !lon1 || !lat2 || !lon2) return 0;
    const R = 6371; // km
    const dLat = ((lat2 - lat1) * Math.PI) / 180;
    const dLon = ((lon2 - lon1) * Math.PI) / 180;
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos((lat1 * Math.PI) / 180) *
        Math.cos((lat2 * Math.PI) / 180) *
        Math.sin(dLon / 2) *
        Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  };

  // Distance-Aware AR Launch Check
  const checkDistanceAndLaunchAR = (title, sub, bearing = 40) => {
    if (!navigator.geolocation) {
      launchAR(title, sub, bearing);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const uLat = pos.coords.latitude;
        const uLon = pos.coords.longitude;
        const sLat = stationCoords.lat || 28.6423;
        const sLon = stationCoords.lon || 77.2200;
        const distKm = calcDistanceKm(uLat, uLon, sLat, sLon);
        setUserDistanceToStation(distKm);

        if (distKm > 1.5) {
          // User is far from the station! Cannot guide indoor concourse
          setTooFarModal({
            distanceKm: distKm.toFixed(1),
            stationName: stationName,
            stationCode: stationCode,
            coords: { lat: sLat, lon: sLon },
            pendingTarget: { title, sub, bearing },
          });
        } else {
          // Inside 1.5km station perimeter
          setIsDemoSimulation(false);
          launchAR(title, sub, bearing);
        }
      },
      (err) => {
        console.warn("GPS lookup unavailable for distance check, falling back to direct AR", err);
        launchAR(title, sub, bearing);
      },
      { timeout: 5000, enableHighAccuracy: true }
    );
  };


  // AR Launch
  const launchAR = (title, sub, bearing = 40) => {
    setArTarget({ title, sub, bearing });
    setCamPermError(null);
    setArOpen(true);

    if (navigator.mediaDevices?.getUserMedia) {
      navigator.mediaDevices
        .getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
        .then((stream) => {
          streamRef.current = stream;
          if (videoRef.current) videoRef.current.srcObject = stream;
        })
        .catch((e) => {
          console.warn("Camera fallback active:", e);
          setCamPermError("Camera requires HTTPS or permission. Sensor HUD simulator active.");
        });
    } else {
      setCamPermError("Camera not available. Sensor HUD simulator active.");
    }

    const handleOrientation = (e) => {
      if (e.alpha !== null) setDeviceHeading(Math.round(e.alpha));
    };
    window.addEventListener("deviceorientation", handleOrientation, true);
  };

  const closeAR = () => {
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
    setArOpen(false);
  };

  // Turn-by-turn Navigation Flow Content Definition
  const assignedPlatform = activeJourney?.platform || selectedTrain?.platform || stationTopology?.default_platform || "1";
  const assignedTrainName = activeJourney
    ? `${activeJourney.train_number} ${activeJourney.train_name}`
    : selectedTrain
    ? `${selectedTrain.train_number} ${selectedTrain.train_name}`
    : "";
  const targetCoachDistance = coachAnalysis?.target_coach_info?.distance_from_engine_meters || 334;

  const activeGate = selectedGate || stationTopology?.entries?.[0] || {
    gate_id: "GATE_MAIN",
    gate_name: "Main Entrance",
    landmarks: "Main Station Approach",
    recommended_for_platforms: ["1", "2"],
    amenities: ["Baggage Scanner", "Ticket Counters"]
  };

  const activeFob = stationTopology?.foot_over_bridges?.[0] || {
    fob_name: "Central Foot-Over-Bridge (Step-Free)",
    connects_platforms: `Platforms to Platform ${assignedPlatform}`,
    has_ramps: true,
    has_lifts: true,
  };

  const STEPS = [
    {
      id: 0,
      title: "Arrival: Pick Entry Gate",
      badge: "Curbside Drop-off",
      distance: "At Station Perimeter",
      actionText: "AR Point to Gate",
      render: () => {
        const entries = stationTopology?.entries || [
          {
            gate_id: "GATE_MAIN",
            gate_name: "Main Entrance",
            landmarks: `${stationName} Main Road`,
            recommended_for_platforms: ["1", "2"]
          }
        ];
        return (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <p style={t.descMuted}>Where did you get dropped off or park at {stationName}?</p>
            <div style={{ display: "grid", gridTemplateColumns: entries.length > 2 ? "1fr" : "1fr 1fr", gap: 8 }}>
              {entries.map((gate) => {
                const isSelected = activeGate?.gate_id === gate.gate_id;
                return (
                  <button
                    key={gate.gate_id}
                    onClick={() => setSelectedGate(gate)}
                    style={{
                      ...t.entryChoiceCard,
                      ...(isSelected ? t.entryChoiceActive : {}),
                    }}
                  >
                    <Car size={18} color={isSelected ? "#38bdf8" : "#94a3b8"} />
                    <strong style={{ fontSize: "0.82rem", color: "#fff", marginTop: 4, textAlign: "left" }}>
                      {gate.gate_name}
                    </strong>
                    <span style={{ fontSize: "0.68rem", color: "#94a3b8", textAlign: "left", lineHeight: 1.3 }}>
                      {gate.landmarks}
                    </span>
                    <span style={{
                      ...t.recommendedPill,
                      ...(isSelected ? {} : { backgroundColor: "rgba(255,255,255,0.06)", color: "#94a3b8" })
                    }}>
                      Best for PF {gate.recommended_for_platforms?.join(", ")}
                    </span>
                  </button>
                );
              })}
            </div>

            <div style={t.instructionBox}>
              <MapPin size={16} color="#38bdf8" style={{ flexShrink: 0 }} />
              <span style={{ fontSize: "0.78rem", color: "#e2e8f0" }}>
                Your train is on <strong>Platform {assignedPlatform}</strong>. Entering through{" "}
                <strong>{activeGate?.gate_name}</strong> gives you the most direct path!
              </span>
            </div>
          </div>
        );
      },
    },
    {
      id: 1,
      title: "Security: Baggage Screening",
      badge: activeGate?.gate_name?.split("(")?.[0]?.trim() || "Ground Concourse",
      distance: "Walk 35m Ahead",
      actionText: "AR Point to Scanner",
      render: () => (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <p style={t.descMuted}>Mandatory security checkpoint at {activeGate?.gate_name}.</p>
          <div style={t.checkpointCard}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={t.iconBoxTeal}>
                <ShieldCheck size={20} color="#10b981" />
              </div>
              <div>
                <strong style={{ color: "#fff", fontSize: "0.9rem" }}>
                  {activeGate?.amenities?.[0] || "Baggage Scanner (Express Lane)"}
                </strong>
                <div style={{ fontSize: "0.72rem", color: "#94a3b8" }}>
                  {activeGate?.amenities?.slice(1)?.join(" • ") || "Average wait: < 2 minutes"}
                </div>
              </div>
            </div>
            <span style={t.tagGreen}>Open</span>
          </div>

          <div style={t.instructionBox}>
            <Info size={16} color="#38bdf8" style={{ flexShrink: 0 }} />
            <span style={{ fontSize: "0.78rem", color: "#e2e8f0" }}>
              Keep UTS QR commuter tickets or IRCTC PNR ready on your screen for ticket collector validation after the scanner.
            </span>
          </div>
        </div>
      ),
    },
    {
      id: 2,
      title: "Bridge: Ascent to Platform",
      badge: activeFob.fob_name?.split("(")?.[0]?.trim() || "Concourse Deck",
      distance: "Walk 50m Ahead",
      actionText: "AR Point to Concourse",
      render: () => (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <p style={t.descMuted}>Cross to descend onto Platform {assignedPlatform}.</p>
          <div style={t.fobSelectCard}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <strong style={{ color: "#fff", fontSize: "0.9rem" }}>{activeFob.fob_name}</strong>
                <div style={{ fontSize: "0.72rem", color: "#10b981", marginTop: 2 }}>
                  {activeFob.has_ramps ? "✓ Step-Free Ramp " : ""}
                  {activeFob.has_lifts ? "• Elevators Active " : ""}
                  {activeFob.has_escalators ? "• Escalators Active" : ""}
                </div>
              </div>
              <span style={t.tagBlue}>Recommended</span>
            </div>
          </div>

          <div style={t.instructionBox}>
            <Footprints size={16} color="#38bdf8" style={{ flexShrink: 0 }} />
            <span style={{ fontSize: "0.78rem", color: "#e2e8f0" }}>
              Take {activeFob.fob_name} ➔ Proceed along bridge/deck ➔ Follow wayfinding signs down to <strong>Platform {assignedPlatform}</strong>.
            </span>
          </div>
        </div>
      ),
    },
    {
      id: 3,
      title: "Berth: Walk to Coach Door",
      badge: `Platform ${assignedPlatform} Track`,
      distance: `~${targetCoachDistance}m along Platform`,
      actionText: `AR Point to Coach ${targetCoach}`,
      render: () => (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <p style={t.descMuted}>Select your coach on the 600m train rake:</p>
            <span style={{ fontSize: "0.72rem", color: "#38bdf8", fontWeight: 700 }}>
              Coach {targetCoach}: {targetCoachDistance}m from Engine
            </span>
          </div>

          {/* Clean Horizontal Coach Selector */}
          <div className="no-scrollbar" style={t.horizontalCoachStrip}>
            {coachAnalysis?.coaches?.map((c) => {
              const isSel = c.coach_code === targetCoach;
              return (
                <button
                  key={c.index}
                  onClick={() => {
                    setTargetCoach(c.coach_code);
                    fetchCoachPosition(selectedTrain, c.coach_code);
                  }}
                  style={{
                    ...t.coachPill,
                    ...(isSel ? t.coachPillActive : {}),
                  }}
                >
                  <strong style={{ fontSize: "0.8rem" }}>{c.coach_code}</strong>
                  <span style={{ fontSize: "0.55rem", opacity: 0.8 }}>{c.distance_from_engine_meters}m</span>
                </button>
              );
            })}
          </div>

          <div style={t.instructionBox}>
            <Train size={16} color="#06b6d4" style={{ flexShrink: 0 }} />
            <span style={{ fontSize: "0.78rem", color: "#e2e8f0" }}>
              Coach <strong>{targetCoach}</strong> will halt near <strong>Pillar 14 ({coachAnalysis?.target_coach_info?.platform_section || 'Middle'} of platform)</strong>. Wait here for boarding!
            </span>
          </div>
        </div>
      ),
    },
  ];

  return (
    <div style={t.appFrame}>
      {/* Sleek, Compact Top Header */}
      <header style={t.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <div style={t.logoIcon}>
            <Train size={14} color="#fff" />
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span style={t.logoTitle}>RailMitra</span>
            <span style={t.logoSub}>AR</span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {/* Pillar 5 Emergency SOS */}
          <button
            onClick={() => setEmergencyModalOpen(true)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              backgroundColor: "rgba(244, 63, 94, 0.15)",
              border: "1px solid rgba(244, 63, 94, 0.4)",
              color: "#fb7185",
              fontSize: "0.72rem",
              fontWeight: 800,
              padding: "5px 9px",
              borderRadius: "999px",
              cursor: "pointer",
            }}
            title="Emergency & Safety (Pillar 5)"
          >
            <ShieldAlert size={12} color="#fb7185" />
            <span>SOS</span>
          </button>

          {/* 2D Concourse Blueprint */}
          <button
            onClick={() => setActiveTab("blueprint")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              backgroundColor: activeTab === "blueprint" ? "rgba(16, 185, 129, 0.28)" : "rgba(16, 185, 129, 0.12)",
              border: "1px solid",
              borderColor: activeTab === "blueprint" ? "#10b981" : "rgba(16, 185, 129, 0.35)",
              color: "#10b981",
              fontSize: "0.72rem",
              fontWeight: 800,
              padding: "5px 9px",
              borderRadius: "999px",
              cursor: "pointer",
            }}
            title="2D Station Blueprint & Step-Free Route"
          >
            <Map size={12} color="#10b981" />
            <span>Blueprint</span>
          </button>

          <button onClick={() => { setSearchTarget("global"); setSearchOpen(true); }} style={t.stationPill}>
            <MapPin size={12} color="#38bdf8" />
            <span>{stationCode}</span>
          </button>
        </div>
      </header>

      {/* Main Container */}

      {/* Main Container */}

      <main style={{ ...t.main, ...(activeTab === "blueprint" ? { padding: 0, gap: 0, overflow: "hidden" } : {}) }}>
        {/* =========================================================================
            PILLAR 3: TURN-BY-TURN "CURBSIDE TO COACH BERTH" NAVIGATOR
           ========================================================================= */}
        {activeTab === "wayfinder" && !activeJourney && (
          <div style={t.emptyWayfinderCard}>
            <div style={t.emptyIconCircle}>
              <Compass size={36} color="#38bdf8" />
            </div>
            <h3 style={{ fontSize: "1.15rem", fontWeight: 800, color: "#fff", margin: "14px 0 6px 0" }}>
              No Active Journey Selected
            </h3>
            <p style={{ fontSize: "0.82rem", color: "#94a3b8", lineHeight: 1.5, margin: "0 0 18px 0", maxWidth: "300px", textAlign: "center" }}>
              Concourse wayfinding is calibrated per train. Please search your route in the <strong>Journey Planner</strong> and tap <strong>Navigate</strong> to unlock curbside gate guidance, FOB bridge, and coach door directions.
            </p>
            <button
              onClick={() => setActiveTab("planner")}
              style={{ ...t.btnARPrimary, width: "100%", maxWidth: "260px", padding: "12px 18px", justifyContent: "center" }}
            >
              <Calendar size={16} />
              <span>Go to Journey Planner</span>
            </button>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 16, color: "#64748b", fontSize: "0.72rem" }}>
              <Info size={13} />
              <span>Route ➔ Choose Train ➔ Tap Navigate</span>
            </div>
          </div>
        )}

        {activeTab === "wayfinder" && activeJourney && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {/* Active Train Context Banner */}
            <div style={t.activeTripBanner}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={t.kicker}>NAVIGATING CONCOURSE</span>
                    <span style={{ fontSize: "0.68rem", color: "#38bdf8", backgroundColor: "rgba(56, 189, 248, 0.15)", padding: "1px 6px", borderRadius: 4, fontWeight: 700 }}>
                      {activeJourney.from_code} ➔ {activeJourney.to_code}
                    </span>
                  </div>
                  <div style={{ fontSize: "1.05rem", fontWeight: 800, color: "#fff", marginTop: 4 }}>
                    {assignedTrainName}
                  </div>
                  <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
                    Platform <strong style={{ color: "#f59e0b" }}>{assignedPlatform}</strong> • Departure: <strong style={{ color: "#e2e8f0" }}>{activeJourney.departure_time || "Scheduled"}</strong>
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
                  <div style={t.coachTagBadge}>
                    Coach {targetCoach}
                  </div>
                  <button
                    onClick={() => setActiveTab("planner")}
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "#38bdf8",
                      fontSize: "0.7rem",
                      fontWeight: 700,
                      cursor: "pointer",
                      padding: 0,
                    }}
                  >
                    Change Train ➔
                  </button>
                </div>
              </div>
            </div>

            {/* Stepper Progress Bar (Visual Progress from Curbside to Berth) */}
            <div style={t.stepperRow}>
              {STEPS.map((s, idx) => {
                const isPassed = idx < currentStepIndex;
                const isCurrent = idx === currentStepIndex;
                return (
                  <button
                    key={s.id}
                    onClick={() => setCurrentStepIndex(idx)}
                    style={{
                      ...t.stepNode,
                      ...(isCurrent ? t.stepNodeCurrent : isPassed ? t.stepNodePassed : {}),
                    }}
                  >
                    <span style={{ fontSize: "0.72rem", fontWeight: 800 }}>
                      {idx + 1}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Active Step Card */}
            <div style={t.stepCardActive}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <span style={t.kicker}>STEP {currentStepIndex + 1} OF 4 • {STEPS[currentStepIndex].badge}</span>
                  <h3 style={t.stepTitleBig}>{STEPS[currentStepIndex].title}</h3>
                </div>
                <span style={t.distTag}>{STEPS[currentStepIndex].distance}</span>
              </div>

              {/* Step Content */}
              <div style={{ margin: "14px 0" }}>
                {STEPS[currentStepIndex].render()}
              </div>

              {/* Pillar 5 Blueprint Route Button */}
              <button
                onClick={() => setActiveTab("blueprint")}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "6px",
                  backgroundColor: "rgba(16, 185, 129, 0.12)",
                  border: "1px solid rgba(16, 185, 129, 0.35)",
                  color: "#10b981",
                  borderRadius: "10px",
                  padding: "9px 12px",
                  fontSize: "0.76rem",
                  fontWeight: 800,
                  cursor: "pointer",
                  width: "100%",
                  marginBottom: 8,
                }}
              >
                <Map size={14} color="#10b981" />
                <span>2D Station Blueprint & Step-Free Route</span>
              </button>

              {/* Action Buttons: Launch Camera AR & Next Step */}
              <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <button
                  onClick={() => {
                    const title = currentStepIndex === 0 ? activeGate.gate_name : STEPS[currentStepIndex].title;
                    const sub = currentStepIndex === 0 ? (activeGate.landmarks || "Station Curbside") : STEPS[currentStepIndex].distance;
                    checkDistanceAndLaunchAR(title, sub, 35);
                  }}
                  style={{ ...t.btnARPrimary, flex: 1 }}
                >
                  <Compass size={16} />
                  <span>{STEPS[currentStepIndex].actionText}</span>
                </button>

                {currentStepIndex < STEPS.length - 1 ? (
                  <button
                    onClick={() => setCurrentStepIndex(currentStepIndex + 1)}
                    style={t.btnNextStep}
                  >
                    <span>Next</span>
                    <ChevronRight size={16} />
                  </button>
                ) : (
                  <button
                    onClick={() => setCurrentStepIndex(0)}
                    style={{ ...t.btnNextStep, backgroundColor: "rgba(16, 185, 129, 0.2)", color: "#10b981", borderColor: "rgba(16, 185, 129, 0.4)" }}
                  >
                    <CheckCircle2 size={16} />
                    <span>Arrived</span>
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* =========================================================================
            PILLAR 5: 2D INDOOR STATION BLUEPRINT & ACCESSIBILITY ROUTING TAB
           ========================================================================= */}
        {activeTab === "blueprint" && (
          <StationBlueprintView
            stationCode={stationCode}
            stationName={stationName}
            targetPlatform={["7", "8", "9", "10", "11", "12"].includes(String(assignedPlatform)) ? String(assignedPlatform) : "10"}
            onSwitchToChennaiCentral={() => {
              setStationCode("MAS");
              setStationName("Chennai Central");
              loadStation("MAS");
            }}
            onLaunchAR={(title, sub, bearing) => {
              setActiveTab("wayfinder");
              checkDistanceAndLaunchAR(title, sub, bearing);
            }}
          />
        )}

        {/* =========================================================================
            PILLAR 2: LIVE DEPARTURE BOARD
           ========================================================================= */}
        {activeTab === "board" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={t.simpleCard}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h3 style={{ fontSize: "1.1rem", fontWeight: 800, color: "#fff" }}>{stationName} Live Board</h3>
                  <span style={{ fontSize: "0.72rem", color: "#10b981" }}>CRIS NTES Live Yard Feed</span>
                </div>
                <span style={t.pfBig}>{stationCode}</span>
              </div>
            </div>

            {stationTrains.map((train) => {
              const hasPf = train.platform && train.platform !== "0";
              const isSelected = selectedTrain?.train_number === train.train_number;
              return (
                <div
                  key={train.train_number}
                  onClick={() => {
                    setPlanFrom(train.source_code || stationCode);
                    setPlanFromName(stationName);
                    setPlanTo(train.destination_code || "CNB");
                    setPlanToName(train.destination_name || "Destination");
                    fetchJourneyPlan(train.source_code || stationCode, train.destination_code || "CNB");
                    setActiveTab("planner");
                  }}
                  style={{
                    ...t.trainCardItem,
                    ...(isSelected ? t.trainCardSelected : {}),
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <div>
                      <strong style={{ color: "#60a5fa", fontSize: "0.95rem", fontFamily: "monospace" }}>
                        {train.train_number}
                      </strong>{" "}
                      <span style={{ color: "#fff", fontWeight: 700, fontSize: "0.9rem" }}>{train.train_name}</span>
                      <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginTop: 2 }}>
                        {train.source_code} ➔ {train.destination_name}
                      </div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <span style={{ fontSize: "0.6rem", color: "#64748b", fontWeight: 800 }}>PLATFORM</span>
                      <div style={{ ...t.pfBoxMini, ...(hasPf ? t.pfBoxMiniActive : {}) }}>
                        {hasPf ? train.platform : "--"}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8, fontSize: "0.78rem" }}>
                    <span>ETA: <strong style={{ color: "#38bdf8" }}>{train.expected_arrival || train.scheduled_arrival}</strong></span>
                    <span style={{ color: train.delay_arrival && train.delay_arrival !== "RT" ? "#f43f5e" : "#10b981" }}>
                      {train.delay_arrival && train.delay_arrival !== "RT" ? `Late by ${train.delay_arrival}` : "On Time"}
                    </span>
                    <span style={{ color: "#38bdf8", fontWeight: 700, fontSize: "0.72rem" }}>
                      Plan in Planner ➔
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* =========================================================================
            PILLAR 1: JOURNEY PLANNER & ML DELAY FORECAST
           ========================================================================= */}
        {activeTab === "planner" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {/* Top Sub-Mode Switcher: Goal Planner | Ticketing AI | Direct Trains */}
            <div
              style={{
                display: "flex",
                background: "rgba(0, 0, 0, 0.45)",
                padding: 4,
                borderRadius: 14,
                border: "1px solid rgba(255, 255, 255, 0.08)",
                gap: 4,
              }}
            >
              <button
                onClick={(e) => {
                  e.currentTarget.blur();
                  setPlannerSubMode("goal");
                }}
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 5,
                  padding: "8px 6px",
                  borderRadius: 10,
                  fontSize: "0.78rem",
                  fontWeight: 800,
                  background: plannerSubMode === "goal" ? "linear-gradient(135deg, #f26522, #dc2626)" : "transparent",
                  color: plannerSubMode === "goal" ? "#fff" : "#94a3b8",
                  border: "none",
                  cursor: "pointer",
                  boxShadow: plannerSubMode === "goal" ? "0 2px 8px rgba(242, 101, 34, 0.35)" : "none",
                  transition: "all 0.15s ease",
                }}
              >
                <Target size={13} />
                <span>Goal Planner</span>
              </button>

              <button
                onClick={(e) => {
                  e.currentTarget.blur();
                  setPlannerSubMode("guidance");
                }}
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 5,
                  padding: "8px 6px",
                  borderRadius: 10,
                  fontSize: "0.78rem",
                  fontWeight: 800,
                  background: plannerSubMode === "guidance" ? "linear-gradient(135deg, #f26522, #dc2626)" : "transparent",
                  color: plannerSubMode === "guidance" ? "#fff" : "#94a3b8",
                  border: "none",
                  cursor: "pointer",
                  boxShadow: plannerSubMode === "guidance" ? "0 2px 8px rgba(242, 101, 34, 0.35)" : "none",
                  transition: "all 0.15s ease",
                }}
              >
                <MessageSquare size={13} />
                <span>Ticketing AI</span>
              </button>

              <button
                onClick={(e) => {
                  e.currentTarget.blur();
                  setPlannerSubMode("direct");
                }}
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 5,
                  padding: "8px 6px",
                  borderRadius: 10,
                  fontSize: "0.78rem",
                  fontWeight: 800,
                  background: plannerSubMode === "direct" ? "linear-gradient(135deg, #2563eb, #0284c7)" : "transparent",
                  color: plannerSubMode === "direct" ? "#fff" : "#94a3b8",
                  border: "none",
                  cursor: "pointer",
                  boxShadow: plannerSubMode === "direct" ? "0 2px 8px rgba(37, 99, 235, 0.35)" : "none",
                  transition: "all 0.15s ease",
                }}
              >
                <Train size={13} />
                <span>Direct Trains</span>
              </button>
            </div>

            {/* SUB-MODE 1: GOAL-BASED TRAIN JOURNEY PLANNER */}
            {plannerSubMode === "goal" && (
              <TicketPlanningModule
                initialSubTab="planner"
                onNavigateToBlueprint={(code, pf) => {
                  const targetCode = code || "MAS";
                  setStationCode(targetCode);
                  loadStation(targetCode);
                  setActiveTab("blueprint");
                }}
              />
            )}

            {/* SUB-MODE 2: INDIAN RAILWAYS TICKETING GUIDANCE AI */}
            {plannerSubMode === "guidance" && (
              <TicketPlanningModule
                initialSubTab="guidance"
                onNavigateToBlueprint={(code, pf) => {
                  const targetCode = code || "MAS";
                  setStationCode(targetCode);
                  loadStation(targetCode);
                  setActiveTab("blueprint");
                }}
              />
            )}

            {/* SUB-MODE 3: STATION-TO-STATION QUERY & ML DELAY FORECAST */}
            {plannerSubMode === "direct" && (
              <>
                <div style={t.simpleCard}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <span style={t.kicker}>JOURNEY PLANNER</span>
                <span style={{ fontSize: "0.72rem", color: "#38bdf8", fontWeight: 700 }}>{planTrains.length} Direct Trains</span>
              </div>

              {/* GPS Auto-Detect Nearest Station */}
              <button
                onClick={autoDetectLocation}
                disabled={locating}
                style={t.gpsDetectBtn}
              >
                <MapPin size={15} color="#06b6d4" />
                <span>{locating ? "Acquiring GPS Satellite & Nearest Station..." : "Auto-Detect My Station (GPS)"}</span>
              </button>

              {detectedStationMsg && (
                <div style={t.detectedAlert}>
                  <CheckCircle2 size={14} color="#10b981" style={{ flexShrink: 0 }} />
                  <span>{detectedStationMsg}</span>
                </div>
              )}

              {/* Interactive Station Selectors */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
                {/* FROM Box */}
                <div
                  onClick={() => {
                    setSearchTarget("planFrom");
                    setSearchQuery("");
                    setSearchOpen(true);
                  }}
                  style={t.stationSelectBox}
                >
                  <span style={t.kicker}>FROM (ORIGIN)</span>
                  <div style={{ fontSize: "1.05rem", fontWeight: 900, color: "#38bdf8", marginTop: 2 }}>
                    {planFrom}
                  </div>
                  <div style={{ fontSize: "0.74rem", color: "#cbd5e1", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {planFromName}
                  </div>
                  <span style={t.tapToChangeTag}>Tap to change</span>
                </div>

                {/* Swap Button */}
                <button
                  onClick={() => {
                    const f = planFrom; const fn = planFromName;
                    setPlanFrom(planTo); setPlanFromName(planToName);
                    setPlanTo(f); setPlanToName(fn);
                    setStationCode(planTo);
                    setStationName(planToName);
                    loadStation(planTo);
                    fetchJourneyPlan(planTo, f);
                  }}
                  style={t.swapBtn}
                >
                  <ArrowLeftRight size={14} color="#38bdf8" />
                </button>

                {/* TO Box */}
                <div
                  onClick={() => {
                    setSearchTarget("planTo");
                    setSearchQuery("");
                    setSearchOpen(true);
                  }}
                  style={t.stationSelectBox}
                >
                  <span style={t.kicker}>TO (DESTINATION)</span>
                  <div style={{ fontSize: "1.05rem", fontWeight: 900, color: "#38bdf8", marginTop: 2 }}>
                    {planTo}
                  </div>
                  <div style={{ fontSize: "0.74rem", color: "#cbd5e1", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {planToName}
                  </div>
                  <span style={t.tapToChangeTag}>Tap to change</span>
                </div>
              </div>

              {/* Quick Route Suggestions */}
              <div style={{ marginTop: 12 }}>
                <span style={{ fontSize: "0.62rem", color: "#64748b", fontWeight: 800, textTransform: "uppercase" }}>Popular Routes</span>
                <div style={{ display: "flex", gap: 6, overflowX: "auto", marginTop: 4, paddingBottom: 2 }}>
                  {[
                    { from: "VLCY", fn: "Velachery", to: "MAS", tn: "Chennai Central" },
                    { from: "NDLS", fn: "New Delhi", to: "CNB", tn: "Kanpur Central" },
                    { from: "CSMT", fn: "Mumbai CSMT", to: "PUNE", tn: "Pune Jn" },
                    { from: "HWH", fn: "Howrah Jn", to: "BBS", tn: "Bhubaneswar" },
                    { from: "SBC", fn: "KSR Bengaluru", to: "MAS", tn: "Chennai Central" },
                    { from: "NDLS", fn: "New Delhi", to: "BSB", tn: "Varanasi Jn" }
                  ].map((r, i) => (
                    <button
                      key={i}
                      onClick={() => {
                        setPlanFrom(r.from);
                        setPlanFromName(r.fn);
                        setPlanTo(r.to);
                        setPlanToName(r.tn);
                        setStationCode(r.from);
                        setStationName(r.fn);
                        loadStation(r.from);
                        fetchJourneyPlan(r.from, r.to);
                      }}
                      style={t.quickRouteChip}
                    >
                      {r.from} ➔ {r.to}
                    </button>
                  ))}
                </div>
              </div>

              <button
                onClick={() => fetchJourneyPlan(planFrom, planTo)}
                disabled={planLoading}
                style={{ ...t.btnARPrimary, width: "100%", marginTop: 12 }}
              >
                <Search size={14} />
                <span>{planLoading ? "Searching CRIS Schedules..." : "Search Direct Trains"}</span>
              </button>
            </div>

            {planTrains.map((tr) => (
              <div key={tr.train_number} style={t.trainCardItem}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <div>
                    <strong style={{ color: "#60a5fa", fontSize: "0.95rem", fontFamily: "monospace" }}>{tr.train_number}</strong>{" "}
                    <span style={{ color: "#fff", fontWeight: 700 }}>{tr.train_name}</span>
                    <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginTop: 2 }}>
                      {tr.departure_time} ➔ {tr.arrival_time} ({tr.duration})
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                  <button
                    onClick={() => fetchDelayForecast(tr)}
                    disabled={forecastLoadingTrain === tr.train_number}
                    style={{
                      ...t.btnSecondary,
                      flex: 1,
                      ...(forecastLoadingTrain === tr.train_number ? { borderColor: "rgba(56, 189, 248, 0.4)", backgroundColor: "rgba(56, 189, 248, 0.12)", color: "#38bdf8" } : {})
                    }}
                  >
                    <Sparkles size={13} color="#38bdf8" />
                    <span>{forecastLoadingTrain === tr.train_number ? "Calculating ML..." : "AI Forecast"}</span>
                  </button>
                  <button
                    onClick={() => handleNavigateFromPlanner(tr)}
                    style={{ ...t.btnARPrimary, flex: 1, padding: "8px 10px" }}
                  >
                    <Compass size={13} />
                    <span>Navigate</span>
                  </button>
                </div>
              </div>
            ))}
              </>
            )}
          </div>
        )}
      </main>

      {/* Bottom Sticky Navigation */}
      <nav style={t.bottomNav}>
        <button
          onClick={(e) => {
            e.currentTarget.blur();
            setActiveTab("planner");
          }}
          style={{ ...t.navBtn, ...(activeTab === "planner" ? t.navBtnActive : {}) }}
        >
          <Calendar size={18} />
          <span>Planner</span>
        </button>
        <button
          onClick={(e) => {
            e.currentTarget.blur();
            setActiveTab("wayfinder");
          }}
          style={{ ...t.navBtn, ...(activeTab === "wayfinder" ? t.navBtnActive : {}), position: "relative" }}
        >
          <Compass size={18} />
          <span>Wayfinder</span>
          {activeJourney && (
            <span
              style={{
                position: "absolute",
                top: 6,
                right: "22%",
                width: 7,
                height: 7,
                borderRadius: "50%",
                backgroundColor: "#10b981",
                boxShadow: "0 0 6px #10b981",
              }}
            />
          )}
        </button>
        <button
          onClick={(e) => {
            e.currentTarget.blur();
            setActiveTab("blueprint");
          }}
          style={{ ...t.navBtn, ...(activeTab === "blueprint" ? t.navBtnActive : {}) }}
        >
          <Map size={18} />
          <span>2D Map</span>
        </button>
        <button
          onClick={(e) => {
            e.currentTarget.blur();
            setActiveTab("board");
          }}
          style={{ ...t.navBtn, ...(activeTab === "board" ? t.navBtnActive : {}) }}
        >
          <Layers size={18} />
          <span>Live Board</span>
        </button>
      </nav>

      {/* =========================================================================
          FULLSCREEN AR CAMERA HUD OVERLAY
         ========================================================================= */}
      {arOpen && (
        <div style={t.arFullscreen}>
          <video ref={videoRef} autoPlay playsInline muted style={t.arVideo} />

          {/* AR Header */}
          <div style={t.arHeader}>
            <div style={t.arCompassBadge}>
              <Navigation
                size={16}
                style={{
                  transform: `rotate(${deviceHeading}deg)`,
                  transition: "transform 0.1s linear",
                  color: "#06b6d4",
                }}
              />
              <span>BEARING: {deviceHeading}° N</span>
            </div>
            <button onClick={closeAR} style={t.arCloseBtn}>
              <X size={20} color="#fff" />
            </button>
          </div>

          {/* Status Badge: Live Concourse vs Demo Simulation */}
          <div style={isDemoSimulation ? t.arSimBadge : t.arLiveBadge}>
            <Radio size={12} />
            <span>
              {isDemoSimulation
                ? `SIMULATION PREVIEW (${userDistanceToStation ? userDistanceToStation.toFixed(1) + ' km away' : 'DEMO MODE'})`
                : "LIVE CONCOURSE AR • INSIDE PERIMETER"}
            </span>
          </div>

          {/* Center Floating Target Reticle */}
          <div style={t.arCenterReticle}>
            <div className="pulse-target" style={t.arFloatingAnchor}>
              <div style={{ fontSize: "1.6rem", fontWeight: 900 }}>▲</div>
              <div style={{ fontSize: "1.1rem", fontWeight: 900, letterSpacing: "0.04em" }}>
                {arTarget.title}
              </div>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, marginTop: 2 }}>
                {arTarget.sub}
              </div>
            </div>
          </div>

          {/* Bottom Card in AR */}
          <div style={t.arBottomCard}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <strong style={{ color: "#fff", fontSize: "0.95rem" }}>{arTarget.title}</strong>
                <div style={{ fontSize: "0.72rem", color: "#94a3b8" }}>{arTarget.sub}</div>
              </div>
              <button onClick={closeAR} style={t.btnARPrimary}>
                Done
              </button>
            </div>
          </div>

          {camPermError && (
            <div style={t.arErrorAlert}>
              <Info size={14} color="#f59e0b" style={{ flexShrink: 0 }} />
              <span>{camPermError}</span>
            </div>
          )}
        </div>
      )}

      {/* =========================================================================
          MODAL: OUTSIDE STATION PERIMETER / PRE-ARRIVAL TRANSIT RADAR
         ========================================================================= */}
      {tooFarModal && (
        <div style={t.modalBackdrop}>
          <div style={{ ...t.sheetModal, maxHeight: "88vh" }}>
            {/* Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
              <div>
                <span style={{ ...t.codeTag, backgroundColor: "rgba(245, 158, 11, 0.18)", color: "#f59e0b" }}>
                  OUTSIDE CONCOURSE PERIMETER
                </span>
                <h4 style={{ color: "#fff", fontSize: "1.05rem", fontWeight: 800, marginTop: 4 }}>
                  {tooFarModal.distanceKm} km from {tooFarModal.stationName}
                </h4>
              </div>
              <button onClick={() => setTooFarModal(null)} style={t.iconBtn}>
                <X size={18} />
              </button>
            </div>

            {/* Explanation Card */}
            <div style={{ ...t.simpleCard, backgroundColor: "rgba(245, 158, 11, 0.06)", borderColor: "rgba(245, 158, 11, 0.25)", marginBottom: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <Info size={16} color="#f59e0b" />
                <span style={{ fontSize: "0.76rem", fontWeight: 800, color: "#fbbf24" }}>
                  Indoor Camera AR Inactive
                </span>
              </div>
              <p style={{ fontSize: "0.74rem", color: "#cbd5e1", lineHeight: 1.4 }}>
                Concourse turn-by-turn camera wayfinding operates inside the station perimeter (&lt; 1.5 km). Since you are currently <strong>{tooFarModal.distanceKm} km</strong> away, indoor station markers cannot guide you here.
              </p>
            </div>

            {/* Recommended Transit Actions */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
              {/* Google Maps Directions */}
              <a
                href={`https://www.google.com/maps/dir/?api=1&destination=${tooFarModal.coords.lat},${tooFarModal.coords.lon}`}
                target="_blank"
                rel="noreferrer"
                style={{ ...t.btnARPrimary, textDecoration: "none", width: "100%", justifyContent: "center", backgroundColor: "rgba(37, 99, 235, 0.2)", borderColor: "rgba(37, 99, 235, 0.5)", color: "#60a5fa" }}
              >
                <Navigation size={15} />
                <span>Navigate to Station Curbside in Google Maps</span>
              </a>

              {/* Concourse Entry Guidance */}
              <div style={{ padding: "10px", backgroundColor: "rgba(255, 255, 255, 0.03)", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
                <span style={t.kicker}>RECOMMENDED DROP-OFF</span>
                <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "#fff", marginTop: 2 }}>
                  {activeGate?.gate_name}
                </div>
                <div style={{ fontSize: "0.7rem", color: "#94a3b8", marginTop: 2 }}>
                  {activeGate?.landmarks} • Shortest path to Platform {assignedPlatform}
                </div>
              </div>
            </div>

            {/* Test Simulation Mode Option */}
            <div style={{ borderTop: "1px solid rgba(255, 255, 255, 0.08)", paddingTop: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontSize: "0.68rem", color: "#64748b", fontWeight: 800, textTransform: "uppercase" }}>Demo & Testing</span>
              </div>
              <button
                onClick={() => {
                  setIsDemoSimulation(true);
                  const pt = tooFarModal.pendingTarget;
                  setTooFarModal(null);
                  launchAR(pt.title, pt.sub, pt.bearing);
                }}
                style={{ ...t.btnSecondary, width: "100%", justifyContent: "center" }}
              >
                <Eye size={14} color="#38bdf8" />
                <span>Preview Concourse AR (Simulation Mode)</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* =========================================================================
          MODAL: AI DELAY PREDICTION & ML INTUITION DASHBOARD
         ========================================================================= */}
      {forecastModal && (
        <div style={t.modalBackdrop}>
          <div style={{ ...t.sheetModal, maxHeight: "88vh", overflowY: "auto" }}>
            {/* Modal Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ ...t.codeTag, backgroundColor: "rgba(56, 189, 248, 0.15)", color: "#38bdf8" }}>
                    {forecastModal.train_number}
                  </span>
                  <span style={{ fontSize: "0.68rem", color: "#06b6d4", fontWeight: 800, textTransform: "uppercase" }}>
                    {forecastModal.train_type || "SUPERFAST"}
                  </span>
                </div>
                <h4 style={{ color: "#fff", fontSize: "1.05rem", fontWeight: 800, marginTop: 4 }}>
                  {forecastModal.train_name}
                </h4>
                <div style={{ fontSize: "0.72rem", color: "#94a3b8" }}>
                  Destination Junction: <strong style={{ color: "#fff" }}>{forecastModal.station_code}</strong>
                </div>
              </div>
              <button onClick={() => setForecastModal(null)} style={t.iconBtn}>
                <X size={18} />
              </button>
            </div>

            {/* Top ML Score Cards */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
              <div style={t.metricBox}>
                <span style={t.kicker}>PREDICTED DELAY</span>
                <div style={{
                  fontSize: "1.35rem",
                  fontWeight: 900,
                  color: forecastModal.predicted_destination_delay_minutes > 20 ? "#f43f5e" : forecastModal.predicted_destination_delay_minutes > 10 ? "#f59e0b" : "#10b981",
                  marginTop: 2
                }}>
                  +{forecastModal.predicted_destination_delay_minutes} min
                </div>
                <span style={{ fontSize: "0.65rem", color: "#94a3b8" }}>at {forecastModal.station_code} buffer</span>
              </div>
              <div style={t.metricBox}>
                <span style={t.kicker}>ON-TIME CONFIDENCE</span>
                <div style={{ fontSize: "1.35rem", fontWeight: 900, color: "#38bdf8", marginTop: 2 }}>
                  {forecastModal.on_time_probability}%
                </div>
                {/* Visual Progress Bar */}
                <div style={{ width: "100%", height: "4px", backgroundColor: "rgba(255, 255, 255, 0.1)", borderRadius: "2px", marginTop: 6, overflow: "hidden" }}>
                  <div style={{ width: `${forecastModal.on_time_probability}%`, height: "100%", backgroundColor: "#38bdf8", borderRadius: "2px" }} />
                </div>
              </div>
            </div>

            {/* How It Was Calculated: Transparent Step-by-Step Pipeline */}
            <div style={{ ...t.simpleCard, backgroundColor: "rgba(6, 182, 212, 0.05)", borderColor: "rgba(6, 182, 212, 0.2)", marginBottom: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                <Sparkles size={14} color="#06b6d4" />
                <span style={{ fontSize: "0.74rem", fontWeight: 800, color: "#38bdf8", textTransform: "uppercase" }}>
                  Calculation Intuition & Model Breakdown
                </span>
              </div>

              {/* 4 Steps */}
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {(forecastModal.calculation_steps || [
                  `1. Queried 63,428 CRIS records: ${forecastModal.station_code} baseline is ${forecastModal.historical_mean_delay_minutes}m`,
                  `2. Evaluated precedence factor: ${forecastModal.train_type || 'EXPRESS'} track weight is ${forecastModal.precedence_weight || 0.7}x`,
                  `3. Blended current live telemetry delay (${forecastModal.live_input_delay_minutes || 0}m) with corridor baseline`,
                  `4. Result: Predicted delay of +${forecastModal.predicted_destination_delay_minutes}m (${forecastModal.on_time_probability}% probability)`
                ]).map((step, idx) => (
                  <div key={idx} style={{ display: "flex", alignItems: "flex-start", gap: 6, fontSize: "0.72rem", color: "#cbd5e1", lineHeight: 1.35 }}>
                    <CheckCircle2 size={12} color="#10b981" style={{ flexShrink: 0, marginTop: 2 }} />
                    <span>{step}</span>
                  </div>
                ))}
              </div>

              {/* Mathematical Formula Pill */}
              {forecastModal.formula_breakdown && (
                <div style={{ marginTop: 10, padding: "8px 10px", backgroundColor: "rgba(0, 0, 0, 0.4)", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
                  <span style={{ fontSize: "0.62rem", color: "#94a3b8", fontWeight: 800, textTransform: "uppercase" }}>Hybrid Regression Formula</span>
                  <div style={{ fontFamily: "monospace", fontSize: "0.72rem", color: "#67e8f9", marginTop: 2 }}>
                    Delay = {forecastModal.formula_breakdown}
                  </div>
                </div>
              )}
            </div>

            {/* Model Baseline & Metadata */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
              <div style={{ padding: "8px 10px", backgroundColor: "rgba(255, 255, 255, 0.03)", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                <span style={t.kicker}>HISTORICAL BENCHMARK</span>
                <div style={{ fontSize: "0.85rem", fontWeight: 800, color: "#fff", marginTop: 2 }}>
                  {forecastModal.historical_mean_delay_minutes} min avg
                </div>
                <span style={{ fontSize: "0.62rem", color: "#64748b" }}>63,428 CRIS runs dataset</span>
              </div>

              <div style={{ padding: "8px 10px", backgroundColor: "rgba(255, 255, 255, 0.03)", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                <span style={t.kicker}>RECOVERY CAPACITY</span>
                <div style={{ fontSize: "0.85rem", fontWeight: 800, color: "#10b981", marginTop: 2 }}>
                  {forecastModal.recovery_capacity || "Moderate"} Priority
                </div>
                <span style={{ fontSize: "0.62rem", color: "#64748b" }}>Green signal loop priority</span>
              </div>
            </div>

            {/* Corridor Insights */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
              {(forecastModal.insights || []).map((ins, i) => (
                <div key={i} style={{ fontSize: "0.72rem", color: "#94a3b8" }}>
                  💡 {ins}
                </div>
              ))}
            </div>

            <button onClick={() => setForecastModal(null)} style={{ ...t.btnARPrimary, width: "100%" }}>
              Done
            </button>
          </div>
        </div>
      )}

      {/* =========================================================================
          MODAL: STATION SEARCH
         ========================================================================= */}
      {searchOpen && (
        <div style={t.modalBackdrop}>
          <div style={t.sheetModal}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <div>
                <strong style={{ color: "#fff", fontSize: "0.95rem" }}>
                  {searchTarget === "planFrom"
                    ? "Select Origin Station (FROM)"
                    : searchTarget === "planTo"
                    ? "Select Destination Station (TO)"
                    : "Select Station"}
                </strong>
                <div style={{ fontSize: "0.7rem", color: "#64748b" }}>
                  {searchTarget === "planFrom"
                    ? "Also synchronizes concourse navigation & live board"
                    : "Search 8,990 Indian Railways stations"}
                </div>
              </div>
              <button onClick={() => setSearchOpen(false)} style={t.iconBtn}>
                <X size={18} />
              </button>
            </div>

            <input
              autoFocus
              type="text"
              placeholder="Type station name or code (NDLS, Kanpur, CSMT)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={t.searchInput}
            />

            {/* Quick Popular Stations */}
            {searchQuery.trim().length < 2 && (
              <div style={{ marginBottom: 12 }}>
                <span style={{ fontSize: "0.62rem", color: "#64748b", fontWeight: 800, textTransform: "uppercase" }}>Popular Hubs</span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                  {PRESET_STATIONS.map((ps) => (
                    <button
                      key={ps.code}
                      onClick={() => handleStationSelect(ps)}
                      style={t.quickRouteChip}
                    >
                      <strong style={{ color: "#38bdf8" }}>{ps.code}</strong> • {ps.name}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div style={{ maxHeight: "280px", overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
              {searchResults.map((s) => (
                <div
                  key={s.code}
                  onClick={() => handleStationSelect(s)}
                  style={t.searchItem}
                >
                  <div>
                    <strong style={{ color: "#fff", fontSize: "0.88rem" }}>{s.name}</strong>
                    <div style={{ fontSize: "0.7rem", color: "#64748b" }}>{s.state || s.zone}</div>
                  </div>
                  <span style={t.codeTag}>{s.code}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* =========================================================================
          PILLAR 5: EMERGENCY, POLICE & MEDICAL ASSISTANCE MODAL
         ========================================================================= */}
      <EmergencyHelpModal
        isOpen={emergencyModalOpen}
        onClose={() => setEmergencyModalOpen(false)}
        stationCode={stationCode}
      />
    </div>
  );
}

// Minimal, Uncluttered Design Tokens & Styles
const t = {
  appFrame: {
    maxWidth: "480px",
    margin: "0 auto",
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    backgroundColor: "#07090e",
    color: "#f8fafc",
    position: "relative",
    paddingBottom: "76px",
  },
  header: {
    position: "sticky",
    top: 0,
    zIndex: 50,
    padding: "6px 12px",
    minHeight: "44px",
    backgroundColor: "rgba(7, 9, 14, 0.95)",
    backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)",
    borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  logoIcon: {
    width: "24px",
    height: "24px",
    borderRadius: "6px",
    background: "linear-gradient(135deg, #2563eb, #06b6d4)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  logoTitle: {
    fontSize: "0.86rem",
    fontWeight: "800",
    color: "#fff",
    letterSpacing: "-0.01em",
  },
  logoSub: {
    fontSize: "0.6rem",
    color: "#06b6d4",
    fontWeight: "800",
    textTransform: "uppercase",
    letterSpacing: "0.06em",
  },
  stationPill: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    backgroundColor: "rgba(56, 189, 248, 0.12)",
    border: "1px solid rgba(56, 189, 248, 0.3)",
    color: "#38bdf8",
    fontSize: "0.75rem",
    fontWeight: "800",
    padding: "5px 10px",
    borderRadius: "999px",
    cursor: "pointer",
  },
  gpsDetectBtn: {
    width: "100%",
    backgroundColor: "rgba(6, 182, 212, 0.1)",
    borderWidth: "1px",
    borderStyle: "dashed",
    borderColor: "rgba(6, 182, 212, 0.4)",
    borderRadius: "12px",
    padding: "10px 14px",
    color: "#38bdf8",
    fontSize: "0.78rem",
    fontWeight: "800",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    cursor: "pointer",
    touchAction: "manipulation",
  },
  detectedAlert: {
    marginTop: "8px",
    backgroundColor: "rgba(16, 185, 129, 0.12)",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "rgba(16, 185, 129, 0.3)",
    borderRadius: "10px",
    padding: "8px 12px",
    color: "#6ee7b7",
    fontSize: "0.72rem",
    fontWeight: "700",
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  stationSelectBox: {
    flex: 1,
    backgroundColor: "rgba(255, 255, 255, 0.04)",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "rgba(255, 255, 255, 0.12)",
    borderRadius: "14px",
    padding: "10px 12px",
    cursor: "pointer",
    touchAction: "manipulation",
  },
  tapToChangeTag: {
    display: "inline-block",
    marginTop: "6px",
    fontSize: "0.62rem",
    fontWeight: "700",
    color: "#64748b",
    backgroundColor: "rgba(255, 255, 255, 0.05)",
    padding: "2px 6px",
    borderRadius: "4px",
  },
  quickRouteChip: {
    backgroundColor: "rgba(255, 255, 255, 0.05)",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "rgba(255, 255, 255, 0.1)",
    borderRadius: "999px",
    padding: "4px 10px",
    color: "#94a3b8",
    fontSize: "0.68rem",
    fontWeight: "700",
    whiteSpace: "nowrap",
    cursor: "pointer",
    touchAction: "manipulation",
  },
  main: {
    padding: "14px 16px",
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    flex: 1,
  },
  emptyWayfinderCard: {
    backgroundColor: "rgba(18, 24, 38, 0.85)",
    borderWidth: "1px",
    borderStyle: "dashed",
    borderColor: "rgba(56, 189, 248, 0.25)",
    borderRadius: "18px",
    padding: "36px 20px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    textAlign: "center",
    marginTop: "16px",
  },
  emptyIconCircle: {
    width: "64px",
    height: "64px",
    borderRadius: "50%",
    backgroundColor: "rgba(56, 189, 248, 0.1)",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "rgba(56, 189, 248, 0.25)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  activeTripBanner: {
    background: "linear-gradient(135deg, rgba(30, 41, 59, 0.8), rgba(15, 23, 42, 0.9))",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "16px",
    padding: "14px",
  },
  kicker: {
    fontSize: "0.62rem",
    fontWeight: "800",
    color: "#64748b",
    letterSpacing: "0.06em",
    textTransform: "uppercase",
  },
  coachTagBadge: {
    fontFamily: "monospace",
    backgroundColor: "#06b6d4",
    color: "#000",
    fontWeight: "900",
    fontSize: "0.85rem",
    padding: "4px 10px",
    borderRadius: "8px",
  },
  stepperRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "0 6px",
    gap: "8px",
  },
  stepNode: {
    flex: 1,
    height: "32px",
    borderRadius: "8px",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    backgroundColor: "rgba(255, 255, 255, 0.04)",
    color: "#64748b",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    transition: "all 0.2s",
  },
  stepNodeCurrent: {
    backgroundColor: "#2563eb",
    borderColor: "#3b82f6",
    color: "#fff",
    boxShadow: "0 0 12px rgba(37, 99, 235, 0.4)",
  },
  stepNodePassed: {
    backgroundColor: "rgba(16, 185, 129, 0.15)",
    borderColor: "rgba(16, 185, 129, 0.3)",
    color: "#10b981",
  },
  stepCardActive: {
    backgroundColor: "rgba(18, 24, 38, 0.85)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "18px",
    padding: "16px",
    boxShadow: "0 10px 30px rgba(0, 0, 0, 0.4)",
  },
  stepTitleBig: {
    fontSize: "1.15rem",
    fontWeight: "800",
    color: "#fff",
    marginTop: "2px",
  },
  distTag: {
    fontSize: "0.7rem",
    fontWeight: "700",
    color: "#38bdf8",
    backgroundColor: "rgba(56, 189, 248, 0.12)",
    padding: "4px 8px",
    borderRadius: "6px",
  },
  descMuted: {
    fontSize: "0.78rem",
    color: "#94a3b8",
  },
  entryChoiceCard: {
    backgroundColor: "rgba(0, 0, 0, 0.3)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "12px",
    padding: "12px",
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    cursor: "pointer",
    textAlign: "left",
  },
  entryChoiceActive: {
    borderColor: "#38bdf8",
    backgroundColor: "rgba(56, 189, 248, 0.08)",
  },
  recommendedPill: {
    fontSize: "0.62rem",
    fontWeight: "800",
    backgroundColor: "rgba(16, 185, 129, 0.15)",
    color: "#10b981",
    padding: "2px 6px",
    borderRadius: "4px",
    marginTop: "6px",
  },
  instructionBox: {
    display: "flex",
    alignItems: "flex-start",
    gap: "10px",
    backgroundColor: "rgba(56, 189, 248, 0.08)",
    border: "1px solid rgba(56, 189, 248, 0.2)",
    borderRadius: "12px",
    padding: "10px 12px",
  },
  checkpointCard: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "rgba(0, 0, 0, 0.3)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "12px",
    padding: "12px",
  },
  iconBoxTeal: {
    width: "36px",
    height: "36px",
    borderRadius: "10px",
    backgroundColor: "rgba(16, 185, 129, 0.15)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  tagGreen: {
    fontSize: "0.68rem",
    fontWeight: "800",
    color: "#10b981",
    backgroundColor: "rgba(16, 185, 129, 0.12)",
    padding: "3px 8px",
    borderRadius: "999px",
  },
  tagBlue: {
    fontSize: "0.68rem",
    fontWeight: "800",
    color: "#38bdf8",
    backgroundColor: "rgba(56, 189, 248, 0.12)",
    padding: "3px 8px",
    borderRadius: "999px",
  },
  fobSelectCard: {
    backgroundColor: "rgba(0, 0, 0, 0.3)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "12px",
    padding: "12px",
  },
  horizontalCoachStrip: {
    display: "flex",
    gap: "6px",
    overflowX: "auto",
    padding: "4px 0",
  },
  coachPill: {
    minWidth: "48px",
    height: "48px",
    borderRadius: "10px",
    backgroundColor: "rgba(255, 255, 255, 0.05)",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    color: "#fff",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
  },
  coachPillActive: {
    backgroundColor: "#06b6d4",
    borderColor: "#06b6d4",
    color: "#000",
    boxShadow: "0 0 12px rgba(6, 182, 212, 0.5)",
  },
  btnARPrimary: {
    backgroundColor: "rgba(6, 182, 212, 0.18)",
    border: "1px solid rgba(6, 182, 212, 0.4)",
    color: "#38bdf8",
    fontSize: "0.78rem",
    fontWeight: "800",
    padding: "10px 14px",
    borderRadius: "12px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    cursor: "pointer",
  },
  btnNextStep: {
    backgroundColor: "rgba(255, 255, 255, 0.06)",
    border: "1px solid rgba(255, 255, 255, 0.12)",
    color: "#fff",
    fontSize: "0.78rem",
    fontWeight: "800",
    padding: "10px 16px",
    borderRadius: "12px",
    display: "flex",
    alignItems: "center",
    gap: "4px",
    cursor: "pointer",
  },
  btnSecondary: {
    backgroundColor: "rgba(255, 255, 255, 0.05)",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    color: "#94a3b8",
    fontSize: "0.75rem",
    fontWeight: "700",
    padding: "8px 12px",
    borderRadius: "10px",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
  },
  // Bottom Nav
  bottomNav: {
    position: "fixed",
    bottom: 0,
    left: "50%",
    transform: "translateX(-50%)",
    width: "100%",
    maxWidth: "480px",
    backgroundColor: "rgba(7, 9, 14, 0.98)",
    backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)",
    borderTop: "1px solid rgba(255, 255, 255, 0.08)",
    paddingTop: "10px",
    paddingBottom: "max(14px, env(safe-area-inset-bottom, 14px))",
    paddingLeft: "16px",
    paddingRight: "16px",
    display: "flex",
    justifyContent: "space-around",
    alignItems: "center",
    zIndex: 999,
    touchAction: "manipulation",
  },
  navBtn: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: "4px",
    backgroundColor: "transparent",
    borderWidth: "0px",
    borderStyle: "none",
    outline: "none",
    color: "#64748b",
    fontSize: "0.72rem",
    fontWeight: "700",
    cursor: "pointer",
    padding: "6px 14px",
    borderRadius: "10px",
    WebkitTapHighlightColor: "transparent",
    touchAction: "manipulation",
    userSelect: "none",
  },
  navBtnActive: {
    color: "#38bdf8",
    backgroundColor: "rgba(56, 189, 248, 0.12)",
  },
  // AR Fullscreen
  arFullscreen: {
    position: "fixed",
    inset: 0,
    backgroundColor: "#050811",
    zIndex: 1000,
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
  },
  arVideo: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    objectFit: "cover",
  },
  arHeader: {
    position: "relative",
    zIndex: 10,
    padding: "16px",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  arCompassBadge: {
    backgroundColor: "rgba(0, 0, 0, 0.7)",
    backdropFilter: "blur(12px)",
    border: "1px solid rgba(6, 182, 212, 0.4)",
    padding: "6px 14px",
    borderRadius: "999px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    fontSize: "0.75rem",
    fontWeight: "800",
    color: "#38bdf8",
  },
  arCloseBtn: {
    backgroundColor: "rgba(0, 0, 0, 0.7)",
    border: "none",
    width: "36px",
    height: "36px",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
  },
  arSimBadge: {
    position: "absolute",
    top: "70px",
    left: "16px",
    right: "16px",
    backgroundColor: "rgba(245, 158, 11, 0.2)",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "rgba(245, 158, 11, 0.5)",
    padding: "6px 12px",
    borderRadius: "10px",
    fontSize: "0.72rem",
    fontWeight: "800",
    color: "#fbbf24",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    zIndex: 15,
  },
  arLiveBadge: {
    position: "absolute",
    top: "70px",
    left: "16px",
    right: "16px",
    backgroundColor: "rgba(16, 185, 129, 0.2)",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "rgba(16, 185, 129, 0.5)",
    padding: "6px 12px",
    borderRadius: "10px",
    fontSize: "0.72rem",
    fontWeight: "800",
    color: "#6ee7b7",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    zIndex: 15,
  },
  arCenterReticle: {
    position: "relative",
    zIndex: 10,
    alignSelf: "center",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
  },
  arFloatingAnchor: {
    backgroundColor: "rgba(6, 182, 212, 0.9)",
    color: "#000",
    padding: "14px 22px",
    borderRadius: "16px",
    textAlign: "center",
  },
  arBottomCard: {
    position: "relative",
    zIndex: 10,
    margin: "16px",
    padding: "14px 16px",
    backgroundColor: "rgba(10, 14, 23, 0.94)",
    backdropFilter: "blur(20px)",
    borderRadius: "16px",
    border: "1px solid rgba(255, 255, 255, 0.08)",
  },
  arErrorAlert: {
    position: "absolute",
    top: "70px",
    left: "16px",
    right: "16px",
    backgroundColor: "rgba(245, 158, 11, 0.15)",
    border: "1px solid rgba(245, 158, 11, 0.3)",
    padding: "8px 12px",
    borderRadius: "10px",
    fontSize: "0.72rem",
    color: "#fbbf24",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    zIndex: 15,
  },
  // Sub-items
  simpleCard: {
    backgroundColor: "rgba(18, 24, 38, 0.8)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "16px",
    padding: "14px",
  },
  trainCardItem: {
    backgroundColor: "rgba(18, 24, 38, 0.7)",
    border: "1px solid rgba(255, 255, 255, 0.06)",
    borderRadius: "16px",
    padding: "14px",
    cursor: "pointer",
  },
  trainCardSelected: {
    borderColor: "#38bdf8",
    backgroundColor: "rgba(56, 189, 248, 0.06)",
  },
  pfBig: {
    fontFamily: "monospace",
    fontSize: "1.05rem",
    fontWeight: "900",
    color: "#38bdf8",
  },
  pfBoxMini: {
    fontFamily: "monospace",
    fontSize: "1.05rem",
    fontWeight: "900",
    padding: "2px 8px",
    borderRadius: "6px",
    backgroundColor: "rgba(255, 255, 255, 0.06)",
    color: "#64748b",
  },
  pfBoxMiniActive: {
    backgroundColor: "#f59e0b",
    color: "#000",
  },
  swapBtn: {
    width: "32px",
    height: "32px",
    borderRadius: "50%",
    backgroundColor: "rgba(56, 189, 248, 0.12)",
    border: "1px solid rgba(56, 189, 248, 0.25)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
  },
  modalBackdrop: {
    position: "fixed",
    inset: 0,
    backgroundColor: "rgba(0, 0, 0, 0.8)",
    backdropFilter: "blur(12px)",
    zIndex: 200,
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "center",
  },
  sheetModal: {
    backgroundColor: "#111827",
    borderTopLeftRadius: "20px",
    borderTopRightRadius: "20px",
    borderTop: "1px solid rgba(255, 255, 255, 0.1)",
    padding: "18px",
    width: "100%",
    maxWidth: "480px",
    maxHeight: "80vh",
    display: "flex",
    flexDirection: "column",
  },
  iconBtn: {
    background: "none",
    border: "none",
    color: "#94a3b8",
    cursor: "pointer",
  },
  metricBox: {
    backgroundColor: "rgba(0, 0, 0, 0.3)",
    padding: "12px",
    borderRadius: "12px",
    textAlign: "center",
    border: "1px solid rgba(255, 255, 255, 0.06)",
  },
  searchInput: {
    width: "100%",
    backgroundColor: "rgba(255, 255, 255, 0.05)",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: "12px",
    padding: "10px 14px",
    color: "#fff",
    fontSize: "0.9rem",
    outline: "none",
    marginBottom: "10px",
  },
  searchItem: {
    padding: "10px",
    borderBottom: "1px solid rgba(255, 255, 255, 0.04)",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    cursor: "pointer",
  },
  codeTag: {
    fontFamily: "monospace",
    backgroundColor: "rgba(59, 130, 246, 0.2)",
    color: "#60a5fa",
    padding: "2px 6px",
    borderRadius: "6px",
    fontSize: "0.75rem",
    fontWeight: "700",
  },
};
