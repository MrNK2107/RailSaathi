import React, { useState, useEffect } from "react";
import {
  PhoneCall,
  ShieldAlert,
  HeartPulse,
  X,
  MapPin,
  Accessibility,
  CheckCircle2,
} from "lucide-react";

export default function EmergencyHelpModal({ isOpen, onClose, stationCode = "MAS" }) {
  const [, setStationInfo] = useState(null);
  const [, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      fetchStationInfo();
    }
  }, [isOpen, stationCode]);

  const fetchStationInfo = async () => {
    setLoading(true);
    try {
      const slug = stationCode === "MAS" ? "chennai_central" : "chennai_central";
      const res = await fetch(`/api/stations/${slug}/info`);
      if (res.ok) {
        const data = await res.json();
        setStationInfo(data);
      }
    } catch (e) {
      console.error("Failed to load emergency info:", e);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div style={styles.backdrop}>
      <div style={styles.sheet}>
        {/* Header */}
        <div style={styles.header}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={styles.sosIcon}>
              <ShieldAlert size={20} color="#fff" />
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={styles.kicker}>PILLAR 5 SAFETY & INCLUSION</span>
                <span style={styles.badgeSOS}>24×7 EMERGENCY</span>
              </div>
              <h3 style={styles.title}>Emergency & Medical Assistance</h3>
            </div>
          </div>
          <button onClick={onClose} style={styles.closeBtn}>
            <X size={20} color="#94a3b8" />
          </button>
        </div>

        {/* Content Body */}
        <div style={styles.body}>
          {/* Top Priority SOS Alert Card */}
          <div style={styles.sosCard}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
              <HeartPulse size={22} color="#f43f5e" style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <strong style={{ color: "#fff", fontSize: "0.95rem" }}>
                  Rajiv Gandhi Govt General Hospital (RGGGH Trauma Care)
                </strong>
                <p style={{ color: "#cbd5e1", fontSize: "0.75rem", margin: "4px 0 8px 0", lineHeight: 1.4 }}>
                  Level-1 Trauma & Emergency Care connected directly via pedestrian subway across EVR Periyar Salai (equipped with Southern Railway escalators).
                </p>
                <div style={{ display: "flex", gap: 8 }}>
                  <a href="tel:04425305000" style={styles.callBtnPrimary}>
                    <PhoneCall size={14} />
                    <span>Call 044-25305000</span>
                  </a>
                  <a
                    href="https://maps.google.com/?q=Rajiv+Gandhi+Government+General+Hospital+Chennai"
                    target="_blank"
                    rel="noreferrer"
                    style={styles.btnSecondary}
                  >
                    <MapPin size={14} />
                    <span>Subway Route</span>
                  </a>
                </div>
              </div>
            </div>
          </div>

          {/* Quick Helplines Grid */}
          <span style={styles.sectionTitle}>CRITICAL RAILWAY & CIVIC HELPLINES</span>
          <div style={styles.grid}>
            {/* 139 Rail Madad */}
            <div style={styles.contactItem}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <span style={styles.phoneLabel}>SECURITY & RAIL MADAD</span>
                  <div style={styles.phoneNum}>139</div>
                  <span style={styles.phoneDesc}>Unified RPF, security & medical assistance on trains</span>
                </div>
                <a href="tel:139" style={styles.miniCallBtn}>
                  <PhoneCall size={14} />
                </a>
              </div>
            </div>

            {/* Central Station Police Booth */}
            <div style={styles.contactItem}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <span style={styles.phoneLabel}>CENTRAL STATION POLICE BOOTH</span>
                  <div style={styles.phoneNum}>044-25353545</div>
                  <span style={styles.phoneDesc}>On-site booth at Central Station Bus Stop drop-off</span>
                </div>
                <a href="tel:04425353545" style={styles.miniCallBtn}>
                  <PhoneCall size={14} />
                </a>
              </div>
            </div>

            {/* Divyangjan Wheelchair Assistance */}
            <div style={styles.contactItem}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <span style={styles.phoneLabel}>DIVYANGJAN & SENIOR ASSISTANCE</span>
                  <div style={styles.phoneNum}>044-25357780</div>
                  <span style={styles.phoneDesc}>Book Battery Car & Wheelchair Sahayak at Wall Tax Rd</span>
                </div>
                <a href="tel:04425357780" style={styles.miniCallBtn}>
                  <PhoneCall size={14} />
                </a>
              </div>
            </div>

            {/* National ERSS 112 */}
            <div style={styles.contactItem}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <span style={styles.phoneLabel}>NATIONAL EMERGENCY (ERSS)</span>
                  <div style={styles.phoneNum}>112 / 108</div>
                  <span style={styles.phoneDesc}>Pan-India Police, Fire & Tamil Nadu Ambulance</span>
                </div>
                <a href="tel:112" style={styles.miniCallBtn}>
                  <PhoneCall size={14} />
                </a>
              </div>
            </div>
          </div>

          {/* Keyplan Physical Station Amenities */}
          <span style={styles.sectionTitle}>ACCESSIBLE ON-SITE AMENITIES (KEYPLAN)</span>
          <div style={styles.amenityList}>
            <div style={styles.amenityCard}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Accessibility size={16} color="#38bdf8" />
                <strong style={{ color: "#fff", fontSize: "0.82rem" }}>Divyangjan Wheelchair Ramp</strong>
              </div>
              <p style={{ color: "#94a3b8", fontSize: "0.72rem", margin: "4px 0 0 0" }}>
                At-grade step-free accessible ramp situated at the Wall Tax Road passenger drop-off zone.
              </p>
            </div>

            <div style={styles.amenityCard}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <CheckCircle2 size={16} color="#10b981" />
                <strong style={{ color: "#fff", fontSize: "0.82rem" }}>Prepaid Taxi & Auto Stand</strong>
              </div>
              <p style={{ color: "#94a3b8", fontSize: "0.72rem", margin: "4px 0 0 0" }}>
                Government-regulated fare booth at the south-east circulating drop zone.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

const styles = {
  backdrop: {
    position: "fixed",
    inset: 0,
    backgroundColor: "rgba(0, 0, 0, 0.78)",
    backdropFilter: "blur(8px)",
    zIndex: 1000,
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "center",
  },
  sheet: {
    width: "100%",
    maxWidth: "480px",
    backgroundColor: "#0d131f",
    borderRadius: "20px",
    border: "1px solid rgba(255, 255, 255, 0.12)",
    maxHeight: "80vh",
    marginBottom: "74px",
    marginRight: "10px",
    marginLeft: "10px",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  header: {
    padding: "16px 18px",
    borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  sosIcon: {
    width: "36px",
    height: "36px",
    borderRadius: "10px",
    backgroundColor: "rgba(244, 63, 94, 0.2)",
    border: "1px solid rgba(244, 63, 94, 0.4)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  kicker: {
    fontSize: "0.62rem",
    fontWeight: 800,
    color: "#64748b",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  badgeSOS: {
    fontSize: "0.6rem",
    fontWeight: 800,
    backgroundColor: "rgba(244, 63, 94, 0.2)",
    color: "#fb7185",
    padding: "1px 6px",
    borderRadius: "4px",
    border: "1px solid rgba(244, 63, 94, 0.4)",
  },
  title: {
    fontSize: "1.05rem",
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
  body: {
    padding: "16px 18px",
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: "14px",
  },
  sosCard: {
    backgroundColor: "rgba(244, 63, 94, 0.08)",
    border: "1px solid rgba(244, 63, 94, 0.3)",
    borderRadius: "14px",
    padding: "14px",
  },
  callBtnPrimary: {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    backgroundColor: "#f43f5e",
    color: "#fff",
    fontSize: "0.78rem",
    fontWeight: 800,
    padding: "8px 12px",
    borderRadius: "8px",
    textDecoration: "none",
  },
  btnSecondary: {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    backgroundColor: "rgba(255, 255, 255, 0.08)",
    color: "#e2e8f0",
    fontSize: "0.78rem",
    fontWeight: 700,
    padding: "8px 12px",
    borderRadius: "8px",
    textDecoration: "none",
    border: "1px solid rgba(255, 255, 255, 0.1)",
  },
  sectionTitle: {
    fontSize: "0.68rem",
    fontWeight: 800,
    color: "#94a3b8",
    textTransform: "uppercase",
    letterSpacing: "0.06em",
  },
  grid: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  contactItem: {
    backgroundColor: "rgba(255, 255, 255, 0.03)",
    border: "1px solid rgba(255, 255, 255, 0.06)",
    borderRadius: "12px",
    padding: "12px 14px",
  },
  phoneLabel: {
    fontSize: "0.62rem",
    color: "#64748b",
    fontWeight: 800,
    display: "block",
  },
  phoneNum: {
    fontSize: "1rem",
    fontWeight: 900,
    color: "#38bdf8",
    fontFamily: "monospace",
    margin: "2px 0",
  },
  phoneDesc: {
    fontSize: "0.72rem",
    color: "#94a3b8",
  },
  miniCallBtn: {
    width: "36px",
    height: "36px",
    borderRadius: "10px",
    backgroundColor: "rgba(56, 189, 248, 0.15)",
    border: "1px solid rgba(56, 189, 248, 0.4)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#38bdf8",
    textDecoration: "none",
  },
  amenityList: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  amenityCard: {
    backgroundColor: "rgba(255, 255, 255, 0.02)",
    border: "1px solid rgba(255, 255, 255, 0.05)",
    borderRadius: "10px",
    padding: "10px 12px",
  },
};
