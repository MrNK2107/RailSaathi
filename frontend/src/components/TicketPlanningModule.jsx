import React, { useState, useEffect, useRef } from "react";
import {
  Train,
  Target,
  MessageSquare,
  Send,
  ShieldCheck,
  ExternalLink,
  Clock,
  MapPin,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  Sparkles,
  Map,
  Layers,
  ArrowRight,
  BookOpen,
} from "lucide-react";
import "./TicketPlanningModule.css";

const GOAL_TEMPLATES = [
  {
    title: "🏢 Tidel Park (Chennai)",
    prompt: "I have a meeting at Tidel Park in Chennai at 10:00 AM on 25 October. I'm travelling from Bengaluru. I want AC 3-tier if possible, prefer a reasonably affordable train, and want to reach the meeting location at least 45 minutes early. Find the best train.",
  },
  {
    title: "🎓 IIT Madras Exam",
    prompt: "Exam at IIT Madras Chennai at 09:00 AM on 25 October 2026. Travelling from Bengaluru. Need at least 1 hour buffer at the venue.",
  },
  {
    title: "💼 BKC Mumbai Meet",
    prompt: "I have a business meeting at Bandra Kurla Complex (BKC) Mumbai at 11:00 AM on 2026-10-25 from New Delhi. Prefer Rajdhani Express.",
  },
  {
    title: "💻 HITEC City Interview",
    prompt: "Job interview at HITEC City Hyderabad at 09:30 AM on 2026-10-25 from Bengaluru. Need 45 mins buffer.",
  },
];

const TICKETING_TOPICS = [
  {
    icon: "🚆",
    title: "Class Differences (2A vs 3A)",
    desc: "Berth layout, bedding, privacy curtains & comfort levels.",
    prompt: "What is the difference between Second AC (2A) and Third AC (3A) classes?",
  },
  {
    icon: "📋",
    title: "RAC & Waiting List Rules",
    desc: "RAC boarding rights, chart preparation & GNWL vs RLWL.",
    prompt: "How does RAC work and can I board the train with an RAC ticket?",
  },
  {
    icon: "⚡",
    title: "Tatkal Booking Workflows",
    desc: "Official opening hours (10 AM AC / 11 AM Non-AC) & ID rules.",
    prompt: "What are the exact booking timings, rules, and procedures for Tatkal tickets?",
  },
  {
    icon: "💸",
    title: "Cancellation & Refund Policies",
    desc: "Time-slab deductions (48h, 12h, 4h), clerkage charges & TDR filing.",
    prompt: "What are the cancellation charges for a confirmed ticket cancelled 24 hours before train departure?",
  },
];

export default function TicketPlanningModule({ onNavigateToBlueprint, onSelectTrainForTrip, initialSubTab = "planner" }) {
  const [subTab, setSubTab] = useState(initialSubTab); // 'planner' or 'guidance'

  // === Goal Planner State ===
  const [plannerPrompt, setPlannerPrompt] = useState(GOAL_TEMPLATES[0].prompt);
  const [showAdvancedForm, setShowAdvancedForm] = useState(false);
  const [origin, setOrigin] = useState("Bengaluru");
  const [venue, setVenue] = useState("Tidel Park");
  const [destCity, setDestCity] = useState("Chennai");
  const [meetingDate, setMeetingDate] = useState("2026-10-25");
  const [meetingTime, setMeetingTime] = useState("10:00");
  const [bufferMinutes, setBufferMinutes] = useState(45);
  const [preferredClass, setPreferredClass] = useState("3A");
  const [preferredTrain, setPreferredTrain] = useState("");
  const [budgetMax, setBudgetMax] = useState("");

  const [planningLoading, setPlanningLoading] = useState(false);
  const [journeyPlan, setJourneyPlan] = useState(null);
  const [plannerError, setPlannerError] = useState(null);

  // === Chat Guidance State ===
  const [messages, setMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [sourcesList, setSourcesList] = useState([]);
  const [sourcesModalOpen, setSourcesModalOpen] = useState(false);

  const chatEndRef = useRef(null);

  useEffect(() => {
    fetchSources();
  }, []);

  useEffect(() => {
    if (subTab === "guidance") {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, subTab]);

  const fetchSources = async () => {
    try {
      const res = await fetch("/api/sources");
      if (res.ok) {
        const data = await res.json();
        setSourcesList(data.sources || []);
      }
    } catch (e) {
      console.warn("Failed to load sources:", e);
    }
  };

  // === Journey Planning Actions ===
  const handlePlanJourney = async (e) => {
    if (e) e.preventDefault();
    setPlanningLoading(true);
    setPlannerError(null);

    const payload = showAdvancedForm
      ? {
          origin,
          destination_venue: venue,
          destination_city: destCity,
          meeting_date: meetingDate,
          meeting_time: meetingTime,
          required_arrival_buffer_minutes: Number(bufferMinutes),
          preferred_class: preferredClass || undefined,
          preferred_train_name_or_number: preferredTrain || undefined,
          budget_max: budgetMax ? Number(budgetMax) : undefined,
        }
      : {
          prompt: plannerPrompt,
        };

    try {
      const res = await fetch("/api/journey/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        setPlannerError(data.detail || data.error || "Failed to generate journey plan.");
      } else {
        setJourneyPlan(data);
      }
    } catch (err) {
      setPlannerError("Network error connecting to RailSathi planning backend.");
    } finally {
      setPlanningLoading(false);
    }
  };

  const handleRefine = async (refinements) => {
    if (!journeyPlan) return;
    setPlanningLoading(true);
    setPlannerError(null);

    const payload = {
      requirements: journeyPlan.trip_requirements,
      ...refinements,
    };

    try {
      const res = await fetch("/api/journey/refine", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok) {
        setJourneyPlan(data);
      } else {
        setPlannerError(data.detail || data.error || "Failed to refine plan.");
      }
    } catch (err) {
      setPlannerError("Network error refining journey plan.");
    } finally {
      setPlanningLoading(false);
    }
  };

  // === Chat Guidance Actions ===
  const handleSendChat = async (textToSend) => {
    const query = textToSend || chatInput;
    if (!query.trim() || chatLoading) return;

    const userMsg = {
      role: "user",
      content: query,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };
    setMessages((prev) => [...prev, userMsg]);
    setChatInput("");
    setChatLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: query,
          conversation_id: conversationId,
        }),
      });

      const data = await res.json();
      if (res.ok) {
        if (data.conversation_id) setConversationId(data.conversation_id);
        const assistantMsg = {
          role: "assistant",
          content: data.answer,
          sources: data.sources || [],
          status: data.status,
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `⚠️ ${data.detail || data.error || "Failed to get response"}`,
            status: "error",
            timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          },
        ]);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "⚠️ Network error: Could not reach backend server.",
          status: "error",
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  return (
    <div className="tpm-container">
      {/* Sub-Navigation Switcher */}
      <div className="tpm-subnav-bar">
        <button
          className={`tpm-subnav-btn ${subTab === "planner" ? "active" : ""}`}
          onClick={() => setSubTab("planner")}
        >
          <Target size={14} />
          <span>Goal Planner</span>
        </button>
        <button
          className={`tpm-subnav-btn ${subTab === "guidance" ? "active" : ""}`}
          onClick={() => setSubTab("guidance")}
        >
          <MessageSquare size={14} />
          <span>Ticketing Rules AI</span>
        </button>
        <button
          className="tpm-subnav-btn"
          style={{ flex: 0.6, fontSize: "0.72rem", opacity: 0.8 }}
          onClick={() => setSourcesModalOpen(true)}
          title="Verified Indian Railways Sources"
        >
          <BookOpen size={12} />
          <span>Sources</span>
        </button>
      </div>

      {/* =====================================================================
          TAB 1: GOAL-BASED JOURNEY PLANNER
         ===================================================================== */}
      {subTab === "planner" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Hero Form Card */}
          <div className="tpm-card">
            <div className="tpm-hero-header">
              <div className="tpm-hero-title">
                <Sparkles size={16} color="#f26522" />
                <span>Plan Train by Real-World Goal</span>
              </div>
              <p className="tpm-hero-desc">
                Tell us where and when you need to be. RailSathi calculates cab transit, station arrival deadlines, and evaluates feasible trains.
              </p>
            </div>

            {/* Quick Templates */}
            <div className="tpm-template-chips">
              <span className="tpm-chip-lbl">Quick Scenarios:</span>
              {GOAL_TEMPLATES.map((tpl, i) => (
                <button
                  key={i}
                  className="tpm-chip"
                  onClick={() => {
                    setPlannerPrompt(tpl.prompt);
                    setShowAdvancedForm(false);
                  }}
                >
                  {tpl.title}
                </button>
              ))}
            </div>

            <form onSubmit={handlePlanJourney}>
              {!showAdvancedForm ? (
                <div>
                  <textarea
                    className="tpm-textarea"
                    rows="3"
                    value={plannerPrompt}
                    onChange={(e) => setPlannerPrompt(e.target.value)}
                    placeholder="e.g. Meeting at Tidel Park Chennai at 10 AM on 25 Oct from Bengaluru. Need 45m buffer..."
                  />
                  <div className="tpm-form-bottom">
                    <button
                      type="button"
                      className="tpm-btn-toggle"
                      onClick={() => setShowAdvancedForm(true)}
                    >
                      ⚙️ Structured Fields
                    </button>
                    <button
                      type="submit"
                      className="tpm-btn-primary"
                      disabled={planningLoading}
                    >
                      {planningLoading ? "Evaluating..." : "🚀 Find Best Train"}
                    </button>
                  </div>
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <div className="tpm-grid-form">
                    <div className="tpm-field">
                      <label>Origin City</label>
                      <input
                        className="tpm-input"
                        type="text"
                        value={origin}
                        onChange={(e) => setOrigin(e.target.value)}
                        required
                      />
                    </div>
                    <div className="tpm-field">
                      <label>Destination Venue / Landmark</label>
                      <input
                        className="tpm-input"
                        type="text"
                        value={venue}
                        onChange={(e) => setVenue(e.target.value)}
                        placeholder="e.g. Tidel Park"
                        required
                      />
                    </div>
                    <div className="tpm-field">
                      <label>Destination City</label>
                      <input
                        className="tpm-input"
                        type="text"
                        value={destCity}
                        onChange={(e) => setDestCity(e.target.value)}
                        placeholder="e.g. Chennai"
                      />
                    </div>
                    <div className="tpm-field">
                      <label>Date</label>
                      <input
                        className="tpm-input"
                        type="date"
                        value={meetingDate}
                        onChange={(e) => setMeetingDate(e.target.value)}
                        required
                      />
                    </div>
                    <div className="tpm-field">
                      <label>Meeting Time</label>
                      <input
                        className="tpm-input"
                        type="time"
                        value={meetingTime}
                        onChange={(e) => setMeetingTime(e.target.value)}
                        required
                      />
                    </div>
                    <div className="tpm-field">
                      <label>Buffer at Venue (Mins)</label>
                      <input
                        className="tpm-input"
                        type="number"
                        min="0"
                        max="300"
                        value={bufferMinutes}
                        onChange={(e) => setBufferMinutes(e.target.value)}
                        required
                      />
                    </div>
                    <div className="tpm-field">
                      <label>Preferred Class</label>
                      <select
                        className="tpm-select"
                        value={preferredClass}
                        onChange={(e) => setPreferredClass(e.target.value)}
                      >
                        <option value="">Any Class</option>
                        <option value="3A">AC 3-Tier (3A)</option>
                        <option value="2A">AC 2-Tier (2A)</option>
                        <option value="CC">AC Chair Car (CC)</option>
                        <option value="SL">Sleeper (SL)</option>
                        <option value="1A">First AC (1A)</option>
                      </select>
                    </div>
                    <div className="tpm-field">
                      <label>Max Budget (₹)</label>
                      <input
                        className="tpm-input"
                        type="number"
                        value={budgetMax}
                        onChange={(e) => setBudgetMax(e.target.value)}
                        placeholder="e.g. 1500"
                      />
                    </div>
                  </div>

                  <div className="tpm-form-bottom">
                    <button
                      type="button"
                      className="tpm-btn-toggle"
                      onClick={() => setShowAdvancedForm(false)}
                    >
                      💬 Natural Language
                    </button>
                    <button
                      type="submit"
                      className="tpm-btn-primary"
                      disabled={planningLoading}
                    >
                      {planningLoading ? "Evaluating..." : "🚀 Evaluate Trains"}
                    </button>
                  </div>
                </div>
              )}
            </form>
          </div>

          {/* Error Message */}
          {plannerError && (
            <div className="tpm-error-banner">
              <AlertTriangle size={18} color="#ef4444" style={{ flexShrink: 0 }} />
              <span>{plannerError}</span>
            </div>
          )}

          {/* Results Display */}
          {journeyPlan && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {/* Goal Ribbon */}
              <div className="tpm-goal-ribbon">
                <div className="tpm-ribbon-top">
                  <span className="tpm-badge-goal">TARGET GOAL</span>
                  <span style={{ fontSize: "0.75rem", color: "#38bdf8", fontWeight: 700 }}>
                    {journeyPlan.trip_requirements.meeting_time} ({journeyPlan.trip_requirements.meeting_date})
                  </span>
                </div>
                <div className="tpm-ribbon-title">
                  Reach {journeyPlan.trip_requirements.destination_venue} in {journeyPlan.trip_requirements.destination_city || "Chennai"}
                </div>
                <div className="tpm-ribbon-sub">
                  <span>From: <strong>{journeyPlan.trip_requirements.origin}</strong></span>
                  <span>Buffer: <strong>{journeyPlan.trip_requirements.required_arrival_buffer_minutes}m</strong></span>
                  {journeyPlan.trip_requirements.preferred_class && (
                    <span>Class: <strong>{journeyPlan.trip_requirements.preferred_class}</strong></span>
                  )}
                </div>
              </div>

              {/* Resolved Station Hubs */}
              <div className="tpm-stations-bar">
                <span>🚉 Stations near venue:</span>
                {journeyPlan.candidate_destination_stations?.slice(0, 3).map((st) => (
                  <span key={st.station_code} className="tpm-station-chip">
                    {st.station_code} (~{st.distance_to_venue_km}km)
                  </span>
                ))}
              </div>

              {/* TOP RECOMMENDED TRAIN HERO */}
              {journeyPlan.best_match ? (
                <div className="tpm-best-card">
                  <div className="tpm-best-badges">
                    <span className="tpm-badge-top">🏆 TOP FEASIBLE TRAIN</span>
                    <span className="tpm-badge-buffer">
                      ✅ +{journeyPlan.best_match.actual_arrival_buffer_minutes}m Buffer at Venue
                    </span>
                  </div>

                  <div className="tpm-train-title">
                    <span>{journeyPlan.best_match.train_service.train_name}</span>
                    <span className="tpm-train-num">#{journeyPlan.best_match.train_service.train_number}</span>
                  </div>

                  {/* Timeline Visualizer */}
                  <div className="tpm-timeline">
                    <div className="tpm-tl-node">
                      <span className="tpm-tl-time">{journeyPlan.best_match.train_service.departure_time}</span>
                      <span className="tpm-tl-station">{journeyPlan.best_match.train_service.origin_station_name}</span>
                      <span className="tpm-tl-code">({journeyPlan.best_match.train_service.origin_station_code})</span>
                    </div>

                    <div className="tpm-tl-seg">
                      <span className="tpm-tl-seg-dur">
                        {Math.floor(journeyPlan.best_match.train_service.duration_minutes / 60)}h{" "}
                        {journeyPlan.best_match.train_service.duration_minutes % 60}m ride
                      </span>
                      <div className="tpm-tl-line"></div>
                    </div>

                    <div className="tpm-tl-node">
                      <span className="tpm-tl-time">{journeyPlan.best_match.train_service.arrival_time}</span>
                      <span className="tpm-tl-station">{journeyPlan.best_match.train_service.destination_station_name}</span>
                      <span className="tpm-tl-code">({journeyPlan.best_match.train_service.destination_station_code})</span>
                    </div>

                    <div className="tpm-tl-seg">
                      <span className="tpm-tl-seg-dur">
                        ~{journeyPlan.best_match.last_mile_duration_minutes}m cab
                      </span>
                      <div className="tpm-tl-line transfer"></div>
                    </div>

                    <div className="tpm-tl-node">
                      <span className="tpm-tl-time" style={{ color: "#34d399" }}>
                        {journeyPlan.best_match.actual_arrival_buffer_minutes}m early
                      </span>
                      <span className="tpm-tl-station" style={{ color: "#38bdf8" }}>Venue</span>
                      <span className="tpm-tl-code">{journeyPlan.trip_requirements.meeting_time}</span>
                    </div>
                  </div>

                  {/* Details row */}
                  <div className="tpm-details-row">
                    <div className="tpm-detail-box">
                      <span className="tpm-detail-kicker">Recommended Class & Fare</span>
                      <span className="tpm-detail-val">
                        {journeyPlan.best_match.recommended_class || "3A"} — ₹{journeyPlan.best_match.recommended_fare || 830}
                      </span>
                    </div>
                    <div className="tpm-detail-box">
                      <span className="tpm-detail-kicker">Last-Mile Transit</span>
                      <span className="tpm-detail-val">
                        ~{journeyPlan.best_match.last_mile_distance_km} km ({journeyPlan.best_match.last_mile_duration_minutes}m cab)
                      </span>
                    </div>
                  </div>

                  {/* Action buttons: IRCTC + Station Blueprint */}
                  <div className="tpm-actions-bar">
                    {journeyPlan.best_match.booking_handoff && (
                      <a
                        href={journeyPlan.best_match.booking_handoff.booking_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="tpm-btn-irctc"
                      >
                        <Train size={14} />
                        <span>Book on IRCTC</span>
                        <ExternalLink size={12} />
                      </a>
                    )}

                    {onNavigateToBlueprint && (
                      <button
                        type="button"
                        className="tpm-btn-concourse"
                        onClick={() => {
                          const destStation = journeyPlan.best_match.train_service.destination_station_code;
                          onNavigateToBlueprint(destStation || "MAS", "10");
                        }}
                      >
                        <Map size={14} />
                        <span>Concourse Blueprint</span>
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="tpm-card" style={{ border: "1px solid rgba(239, 68, 68, 0.3)" }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                    <AlertTriangle size={20} color="#f87171" />
                    <div>
                      <h4 style={{ color: "#f87171", fontSize: "0.9rem", margin: "0 0 4px 0" }}>
                        No Direct Trains Meet Exact Deadline
                      </h4>
                      <p style={{ color: "#94a3b8", fontSize: "0.78rem", margin: 0 }}>
                        {journeyPlan.tradeoff_explanation || journeyPlan.summary}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Feasible Alternatives */}
              {journeyPlan.feasible_alternatives?.length > 0 && (
                <div className="tpm-alts-container">
                  <div className="tpm-section-title">
                    <Train size={14} color="#38bdf8" />
                    <span>Feasible Alternative Trains ({journeyPlan.feasible_alternatives.length})</span>
                  </div>
                  {journeyPlan.feasible_alternatives.map((alt) => (
                    <div key={alt.candidate_id} className="tpm-alt-card">
                      <div className="tpm-alt-header">
                        <span className="tpm-alt-name">
                          {alt.train_service.train_name} #{alt.train_service.train_number}
                        </span>
                        <span className="tpm-alt-buffer">
                          +{alt.actual_arrival_buffer_minutes}m buffer
                        </span>
                      </div>
                      <div className="tpm-alt-timing">
                        Departs {alt.train_service.departure_time} ({alt.train_service.origin_station_code}) → Arrives {alt.train_service.arrival_time} ({alt.train_service.destination_station_code})
                      </div>
                      <div className="tpm-alt-footer">
                        <span style={{ fontSize: "0.75rem", color: "#cbd5e1", fontWeight: 700 }}>
                          {alt.recommended_class} (₹{alt.recommended_fare})
                        </span>
                        <div style={{ display: "flex", gap: 6 }}>
                          {onNavigateToBlueprint && (
                            <button
                              type="button"
                              onClick={() => onNavigateToBlueprint(alt.train_service.destination_station_code, "10")}
                              style={{
                                background: "none",
                                border: "none",
                                color: "#38bdf8",
                                fontSize: "0.72rem",
                                fontWeight: 700,
                                cursor: "pointer",
                                display: "flex",
                                alignItems: "center",
                                gap: 3,
                              }}
                            >
                              <Map size={11} />
                              Map
                            </button>
                          )}
                          {alt.booking_handoff && (
                            <a
                              href={alt.booking_handoff.booking_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{
                                color: "#10b981",
                                fontSize: "0.72rem",
                                fontWeight: 700,
                                textDecoration: "none",
                                display: "flex",
                                alignItems: "center",
                                gap: 3,
                              }}
                            >
                              IRCTC <ExternalLink size={11} />
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Infeasible / Deadline Missed Section */}
              {journeyPlan.infeasible_options?.length > 0 && (
                <div className="tpm-alts-container">
                  <div className="tpm-section-title" style={{ color: "#f87171" }}>
                    <AlertTriangle size={14} color="#f87171" />
                    <span>Evaluated Trains That Miss Deadline ({journeyPlan.infeasible_options.length})</span>
                  </div>
                  {journeyPlan.infeasible_options.slice(0, 3).map((inf) => (
                    <div key={inf.candidate_id} className="tpm-inf-card">
                      <div className="tpm-inf-header">
                        <strong style={{ color: "#fff" }}>
                          {inf.train_service.train_name} (#{inf.train_service.train_number})
                        </strong>
                        <span style={{ color: "#ef4444", fontWeight: 700 }}>Arrives {inf.train_service.arrival_time}</span>
                      </div>
                      <div className="tpm-inf-reasons">
                        {inf.hard_constraint_violations?.map((v, vi) => (
                          <span key={vi} className="tpm-inf-tag">
                            ⚠️ {v}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Quick Refine Toolbar */}
              <div className="tpm-refine-toolbar">
                <span style={{ fontSize: "0.72rem", fontWeight: 700, color: "#94a3b8" }}>⚡ Quick Refine:</span>
                <button
                  className="tpm-refine-btn"
                  onClick={() => handleRefine({ required_arrival_buffer_minutes: 30 })}
                >
                  30m Buffer
                </button>
                <button
                  className="tpm-refine-btn"
                  onClick={() => handleRefine({ preferred_class: "CC" })}
                >
                  AC Chair Car (CC)
                </button>
                <button
                  className="tpm-refine-btn"
                  onClick={() => handleRefine({ meeting_time: "11:00" })}
                >
                  11:00 AM
                </button>
                <button
                  className="tpm-refine-btn"
                  onClick={() => handleRefine({ meeting_time: "14:00" })}
                >
                  02:00 PM
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* =====================================================================
          TAB 2: INDIAN RAILWAYS TICKETING GUIDANCE AI
         ===================================================================== */}
      {subTab === "guidance" && (
        <div className="tpm-card tpm-chat-container">
          {messages.length === 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 12, margin: "auto 0" }}>
              <div style={{ textAlign: "center" }}>
                <h3 style={{ fontSize: "1.05rem", fontWeight: 800, color: "#fff", margin: "0 0 4px 0" }}>
                  💬 Indian Railways Ticketing Guidance
                </h3>
                <p style={{ fontSize: "0.76rem", color: "#94a3b8", margin: 0 }}>
                  Ask verified rules about RAC/WL, Tatkal booking timings, coach classes, or refunds.
                </p>
              </div>

              <div className="tpm-topics-grid">
                {TICKETING_TOPICS.map((topic, i) => (
                  <div
                    key={i}
                    className="tpm-topic-card"
                    onClick={() => handleSendChat(topic.prompt)}
                  >
                    <div className="tpm-topic-icon">{topic.icon}</div>
                    <div className="tpm-topic-title">{topic.title}</div>
                    <div className="tpm-topic-desc">{topic.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="tpm-chat-messages">
              {messages.map((m, idx) => (
                <div key={idx} className={`tpm-msg-bubble ${m.role}`}>
                  <div className="tpm-msg-header">
                    <span>{m.role === "user" ? "👤 Passenger" : "🚆 RailSathi AI"}</span>
                    <span>{m.timestamp}</span>
                  </div>
                  <div>
                    {m.content.split("\n").map((line, li) => (
                      <p key={li} style={{ margin: "0 0 4px 0" }}>{line}</p>
                    ))}
                  </div>
                  {m.sources?.length > 0 && (
                    <div className="tpm-msg-sources">
                      <span style={{ fontSize: "0.62rem", color: "#64748b", fontWeight: 700 }}>SOURCES:</span>
                      {m.sources.map((s, si) => (
                        <a
                          key={si}
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="tpm-source-tag"
                        >
                          {s.title} <ExternalLink size={9} />
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {chatLoading && (
                <div className="tpm-msg-bubble assistant" style={{ fontStyle: "italic", opacity: 0.8 }}>
                  Consulting verified Indian Railways knowledge base...
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
          )}

          {/* Chat Input Bar */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendChat();
            }}
            className="tpm-chat-bar"
          >
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder="Ask about Tatkal, RAC/WL rules, refund slabs..."
              className="tpm-chat-input"
            />
            <button type="submit" className="tpm-chat-send" disabled={chatLoading}>
              <Send size={15} />
            </button>
          </form>
        </div>
      )}

      {/* =====================================================================
          VERIFIED SOURCES MODAL
         ===================================================================== */}
      {sourcesModalOpen && (
        <div className="tpm-modal-backdrop" onClick={() => setSourcesModalOpen(false)}>
          <div className="tpm-modal-content" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <ShieldCheck size={18} color="#10b981" />
                <h3 style={{ fontSize: "0.95rem", fontWeight: 800, color: "#fff", margin: 0 }}>
                  Verified Railway Knowledge Sources
                </h3>
              </div>
              <button
                onClick={() => setSourcesModalOpen(false)}
                style={{ background: "none", border: "none", color: "#94a3b8", fontSize: "1.1rem", cursor: "pointer" }}
              >
                ✕
              </button>
            </div>

            <p style={{ fontSize: "0.75rem", color: "#94a3b8", margin: 0 }}>
              RailSathi AI is strictly grounded in official Indian Railways regulations, IRCTC booking circulars, and verified timetable schedules.
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
              {sourcesList.length > 0 ? (
                sourcesList.map((s) => (
                  <div
                    key={s.source_id}
                    style={{
                      background: "rgba(255, 255, 255, 0.04)",
                      border: "1px solid rgba(255, 255, 255, 0.08)",
                      borderRadius: 10,
                      padding: "8px 10px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
                      <strong style={{ fontSize: "0.82rem", color: "#f1f5f9" }}>{s.title}</strong>
                      <span style={{ fontSize: "0.65rem", color: "#10b981", fontWeight: 700 }}>
                        Verified: {s.last_verified_at}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.7rem", color: "#94a3b8", marginBottom: 4 }}>{s.publisher}</div>
                    <a
                      href={s.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        fontSize: "0.7rem",
                        color: "#38bdf8",
                        textDecoration: "none",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 3,
                      }}
                    >
                      {s.source_url} <ExternalLink size={10} />
                    </a>
                  </div>
                ))
              ) : (
                <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
                  Authoritative Sources: IRCTC Official Portal, Ministry of Railways Tariff Circulars, NTES Timetable DB.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
