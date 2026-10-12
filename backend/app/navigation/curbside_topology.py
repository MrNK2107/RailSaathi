"""
Station Topologies & Gate/FOB Navigation Dataset
Provides curbside entries, security checkpoints, Foot-Over-Bridges (FOBs),
accessibility paths, and platform connections for major Indian Railway hubs.
"""

STATION_TOPOLOGIES = {
    "NDLS": {
        "station_name": "New Delhi Railway Station",
        "station_code": "NDLS",
        "total_platforms": 16,
        "entries": [
            {
                "gate_id": "GATE_AJMERI",
                "gate_name": "Gate 2 - Ajmeri Gate (East Entry)",
                "recommended_for_platforms": ["9", "10", "11", "12", "13", "14", "15", "16"],
                "landmarks": "Near Airport Express & Yellow Line Metro, Bhavbhuti Marg",
                "amenities": ["Baggage Scanner", "ATVM Kiosks", "Escalator to FOB 2", "Wheelchair Ramp"],
                "step_free": True
            },
            {
                "gate_id": "GATE_PAHARGANJ",
                "gate_name": "Gate 1 - Paharganj (West Entry)",
                "recommended_for_platforms": ["1", "2", "3", "4", "5", "6", "7", "8"],
                "landmarks": "Opposite Main Bazaar, State Entry Road",
                "amenities": ["Main Concourse", "Baggage Scanner", "PRS Booking Office", "FOB 1 Access"],
                "step_free": True
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "FOB 1 (North Bridge)",
                "connects_platforms": "Platforms 1 to 16",
                "has_ramps": False,
                "has_lifts": True,
                "has_escalators": True,
                "traffic_density": "High (Central commuter flow)"
            },
            {
                "fob_name": "FOB 2 (South Bridge - Step-Free)",
                "connects_platforms": "Platforms 1 to 16",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": True,
                "traffic_density": "Moderate (Recommended for Luggage & Divyangjan)"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "Curbside Gate Check", "desc": "Approach via optimal gate to save 10-15 mins walking."},
            {"step": 2, "title": "Baggage X-Ray Scanner", "desc": "Security screening mandatory at main porch entry."},
            {"step": 3, "title": "FOB Concourse Ascent", "desc": "Take FOB 2 if you have heavy luggage or require elevator."},
            {"step": 4, "title": "Platform Ramp Descent", "desc": "Descend stairs/ramp directly to your assigned platform."}
        ]
    },
    "CSMT": {
        "station_name": "Mumbai Chhatrapati Shivaji Maharaj Terminus",
        "station_code": "CSMT",
        "total_platforms": 18,
        "entries": [
            {
                "gate_id": "GATE_MAINLINE",
                "gate_name": "Main Line Heritage Porch (Platforms 8-18)",
                "recommended_for_platforms": ["8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18"],
                "landmarks": "DN Road, Outstation Terminus Entrance",
                "amenities": ["Baggage Scanner", "VIP Lounge", "Battery Carts", "Ramps"],
                "step_free": True
            },
            {
                "gate_id": "GATE_SUBURBAN",
                "gate_name": "Suburban Concourse (Platforms 1-7)",
                "recommended_for_platforms": ["1", "2", "3", "4", "5", "6", "7"],
                "landmarks": "Subway link from Fort & St. Xavier's",
                "amenities": ["ATVM Machines", "Fast-track ticket counters", "Suburban FOB"],
                "step_free": False
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "Main Concourse Deck (At-Grade)",
                "connects_platforms": "Platforms 8 to 18 (Terminal Buffer stops)",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": False,
                "traffic_density": "Step-free buffer access at train rear"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "Main Line Concourse", "desc": "Terminal layout allows direct buffer entrance without climbing."},
            {"step": 2, "title": "Security Screening", "desc": "Proceed through central scanner gates."},
            {"step": 3, "title": "Platform Direct Walk", "desc": "Walk straight along buffer end to your assigned track."}
        ]
    },
    "HWH": {
        "station_name": "Howrah Junction",
        "station_code": "HWH",
        "total_platforms": 23,
        "entries": [
            {
                "gate_id": "HWH_NEW_COMPLEX",
                "gate_name": "New Complex Entrance (Platforms 17-23)",
                "recommended_for_platforms": ["17", "18", "19", "20", "21", "22", "23"],
                "landmarks": "South Approach, Cab Road Entry",
                "amenities": ["Direct Cab Drop, Escalators, Premium Lounges"],
                "step_free": True
            },
            {
                "gate_id": "HWH_OLD_COMPLEX",
                "gate_name": "Old Complex Historic Wing (Platforms 1-16)",
                "recommended_for_platforms": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16"],
                "landmarks": "Howrah Bridge Road, Ferry Ghat Link",
                "amenities": ["Historic Big Clock, Subways, UTS Counters"],
                "step_free": True
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "Subway & Inter-Complex Connector",
                "connects_platforms": "Connects Old Complex to New Complex",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": True,
                "traffic_density": "Heavy passenger interchange"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "Complex Selection", "desc": "Ensure you are at Old Complex (PF 1-16) or New Complex (PF 17-23)."},
            {"step": 2, "title": "Security X-Ray", "desc": "Screen baggage before concourse access."},
            {"step": 3, "title": "Track Approach", "desc": "Head directly down the buffer platform."}
        ]
    },
    "VLCY": {
        "station_name": "Velachery MRTS Terminal",
        "station_code": "VLCY",
        "total_platforms": 3,
        "default_platform": "1",
        "entries": [
            {
                "gate_id": "VLCY_NORTH",
                "gate_name": "Gate 1 - North Entrance (Lake Road)",
                "recommended_for_platforms": ["1", "2"],
                "landmarks": "Velachery Lake Road, Auto Stand & Northern Main Porch",
                "amenities": ["Baggage Scanner", "UTS Ticket Counters", "Escalator to Mezzanine Deck"],
                "step_free": True
            },
            {
                "gate_id": "VLCY_SOUTH",
                "gate_name": "Gate 2 - South Entrance (Bypass Road & Bus Terminus)",
                "recommended_for_platforms": ["2", "3"],
                "landmarks": "Velachery Bypass Road & MTC Bus Terminus Link",
                "amenities": ["ATVM Kiosks", "Wide Step-Free Ramp", "Direct Elevated Deck Elevator"],
                "step_free": True
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "Mezzanine Concourse Deck (Step-Free)",
                "connects_platforms": "Platforms 1 to 3",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": True,
                "traffic_density": "Elevated MRTS Concourse Deck"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "Lake Road / Bypass Porch", "desc": "Enter via North Lake Road or South Bus Terminus link."},
            {"step": 2, "title": "Concourse X-Ray Screening", "desc": "Security screening at station entrance hall."},
            {"step": 3, "title": "Mezzanine Deck Ascent", "desc": "Take escalator or lift up to elevated platform level."},
            {"step": 4, "title": "Platform 1-3 Boarding", "desc": "Step directly onto your MRTS suburban train."}
        ]
    },
    "MAS": {
        "station_name": "Puratchi Thalaivar Dr. M.G. Ramachandran Central (MAS)",
        "station_code": "MAS",
        "total_platforms": 12,
        "default_platform": "1",
        "entries": [
            {
                "gate_id": "MAS_GATE_1",
                "gate_name": "Gate 1 - EVR Periyar Salai (Main Heritage Porch)",
                "recommended_for_platforms": ["1", "2", "3", "4", "5", "6"],
                "landmarks": "Main Red Heritage Building, Southern Railway HQ & Metro Subways",
                "amenities": ["Baggage Scanners", "Executive Lounge", "Battery Buggy Stand", "PRS Counters"],
                "step_free": True
            },
            {
                "gate_id": "MAS_GATE_6",
                "gate_name": "Gate 6 - Wall Tax Road Entry",
                "recommended_for_platforms": ["7", "8", "9", "10", "11", "12"],
                "landmarks": "Wall Tax Road Drop-off, Direct Cab Parking Area",
                "amenities": ["ATVMs", "Security Scanner", "Direct High Platform Access"],
                "step_free": True
            },
            {
                "gate_id": "MAS_MMC",
                "gate_name": "MMC Suburban Terminal (Gate 3)",
                "recommended_for_platforms": ["MMC 1", "MMC 2", "MMC 3", "MMC 4", "MMC 5"],
                "landmarks": "Moore Market Complex Suburban Terminal next to Central",
                "amenities": ["UTS Fast-Track Counters", "Footbridge to Central Main Line"],
                "step_free": True
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "Terminal Buffer Headwall Concourse (At-Grade)",
                "connects_platforms": "Platforms 1 to 12 (Zero climbing)",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": True,
                "traffic_density": "Terminal Buffer Headwall - Step-Free"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "EVR Periyar Salai Entry", "desc": "Approach via Gate 1 for PF 1-6 or Gate 6 for PF 7-12."},
            {"step": 2, "title": "Main Porch Baggage Scanner", "desc": "Mandatory security check in circulating hall."},
            {"step": 3, "title": "Buffer Headwall Walkway", "desc": "Terminal layout allows direct buffer entrance without climbing stairs."},
            {"step": 4, "title": "Coach Door Boarding", "desc": "Walk straight along buffer end to your coach position."}
        ]
    },
    "MSB": {
        "station_name": "Chennai Beach Junction",
        "station_code": "MSB",
        "total_platforms": 8,
        "default_platform": "1",
        "entries": [
            {
                "gate_id": "MSB_GATE_1",
                "gate_name": "Gate 1 - Rajaji Salai Main Entrance",
                "recommended_for_platforms": ["1", "2", "3", "4"],
                "landmarks": "Opposite Chennai Port Trust & Madras High Court Metro",
                "amenities": ["UTS Counters", "Baggage Scanner", "Direct Ramp"],
                "step_free": True
            },
            {
                "gate_id": "MSB_GATE_2",
                "gate_name": "Gate 2 - North Beach Road Entry",
                "recommended_for_platforms": ["5", "6", "7", "8"],
                "landmarks": "North Beach Road Harbor Link",
                "amenities": ["Commuter Gates", "Subway to MRTS Elevated Lines"],
                "step_free": True
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "Central Beach FOB (Step-Free)",
                "connects_platforms": "Platforms 1 to 8",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": False,
                "traffic_density": "Suburban & MRTS Transfer Flow"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "Rajaji Salai Entry", "desc": "Enter from port side main road."},
            {"step": 2, "title": "Turnstile & Security", "desc": "Ticket scan and baggage screening."},
            {"step": 3, "title": "Beach FOB Ramp", "desc": "Take ramp up to cross onto MRTS tracks."},
            {"step": 4, "title": "Platform Boarding", "desc": "Descend directly to your suburban train."}
        ]
    },
    "MS": {
        "station_name": "Chennai Egmore",
        "station_code": "MS",
        "total_platforms": 11,
        "default_platform": "1",
        "entries": [
            {
                "gate_id": "MS_EAST",
                "gate_name": "Gandhi Irwin Road Entrance (East / Metro)",
                "recommended_for_platforms": ["1", "2", "3", "4", "5"],
                "landmarks": "Main Indo-Saracenic Heritage Building & Egmore Metro",
                "amenities": ["Main Ticket Hall", "Baggage Scanners", "Executive Lounge"],
                "step_free": True
            },
            {
                "gate_id": "MS_WEST",
                "gate_name": "EVK Sampath Road Entrance (West Concourse)",
                "recommended_for_platforms": ["6", "7", "8", "9", "10", "11"],
                "landmarks": "Poonamallee High Road Link & Premium Cab Drop",
                "amenities": ["ATVMs", "Security Scanner", "Direct Escalators"],
                "step_free": True
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "South Foot-Over-Bridge (Step-Free)",
                "connects_platforms": "Platforms 1 to 11",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": True,
                "traffic_density": "High capacity express bridge"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "Gandhi Irwin / Sampath Entry", "desc": "Pick East or West entrance."},
            {"step": 2, "title": "Main Porch Baggage Scanner", "desc": "Clear X-ray scanner in main hall."},
            {"step": 3, "title": "South FOB Ascent", "desc": "Take ramp or elevator to FOB."},
            {"step": 4, "title": "Platform Descent", "desc": "Descend to your train track."}
        ]
    },
    "SBC": {
        "station_name": "KSR Bengaluru City Junction",
        "station_code": "SBC",
        "total_platforms": 10,
        "default_platform": "1",
        "entries": [
            {
                "gate_id": "SBC_MAIN",
                "gate_name": "Gate 1 - City Main Concourse (Majestic)",
                "recommended_for_platforms": ["1", "2", "3", "4", "5"],
                "landmarks": "Sangolli Rayanna Circle, BMTC Bus Stand & Namma Metro Subway",
                "amenities": ["Main Booking Office", "Baggage Scanner", "Wheelchair Carts"],
                "step_free": True
            },
            {
                "gate_id": "SBC_REAR",
                "gate_name": "Gate 2 - Okalipuram / MG Colony Entry",
                "recommended_for_platforms": ["6", "7", "8", "9", "10"],
                "landmarks": "Okalipuram Rear Approach, Cab Drop Area",
                "amenities": ["ATVM Kiosks", "Security Gate", "Escalator to FOB"],
                "step_free": True
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "Central Elevated FOB (Step-Free)",
                "connects_platforms": "Platforms 1 to 10",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": True,
                "traffic_density": "High passenger flow"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "Majestic / Okalipuram Entrance", "desc": "Choose front or rear gate."},
            {"step": 2, "title": "Security Screening", "desc": "Baggage screening at entrance hall."},
            {"step": 3, "title": "Central FOB Ascent", "desc": "Escalator or lift to Central FOB."},
            {"step": 4, "title": "Platform Descent", "desc": "Ramp down to your platform."}
        ]
    },
    "CNB": {
        "station_name": "Kanpur Central",
        "station_code": "CNB",
        "total_platforms": 10,
        "default_platform": "1",
        "entries": [
            {
                "gate_id": "CNB_CITY",
                "gate_name": "Gate 1 - City Side Entrance (Cantonment)",
                "recommended_for_platforms": ["1", "2", "3", "4", "5"],
                "landmarks": "Main Station Road, Cantt Approach",
                "amenities": ["Main Porch", "Baggage Scanner", "Executive Lounge"],
                "step_free": True
            },
            {
                "gate_id": "CNB_GT_ROAD",
                "gate_name": "Gate 2 - GT Road / Babupurwa Side",
                "recommended_for_platforms": ["6", "7", "8", "9", "10"],
                "landmarks": "GT Road Flyover Link, Cab Stand",
                "amenities": ["ATVMs", "Security Scanner", "Direct Ramp to FOB"],
                "step_free": True
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "Main Delhi-End FOB (Step-Free)",
                "connects_platforms": "Platforms 1 to 10",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": True,
                "traffic_density": "Step-free ramp bridge"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "City / GT Road Entry", "desc": "Enter via City Side or GT Road."},
            {"step": 2, "title": "Security X-Ray", "desc": "Scan bags at main entrance."},
            {"step": 3, "title": "Main FOB Ramp", "desc": "Walk up ramp to FOB."},
            {"step": 4, "title": "Platform Descent", "desc": "Walk down to platform."}
        ]
    }
}


def get_station_topology(station_code: str):
    """Fetches station entrance and navigation layout."""
    code = station_code.upper().strip()
    if code in STATION_TOPOLOGIES:
        return STATION_TOPOLOGIES[code]

    # Generic intelligent fallback template for stations without custom blueprint
    return {
        "station_name": f"{code} Railway Station",
        "station_code": code,
        "total_platforms": 4,
        "default_platform": "1",
        "entries": [
            {
                "gate_id": f"{code}_GATE_1",
                "gate_name": "Gate 1 - Main Entrance (City Side)",
                "recommended_for_platforms": ["1", "2"],
                "landmarks": f"{code} Station Road & Primary Circulating Porch",
                "amenities": ["Ticket Counter", "Security Scanner", "Waiting Hall"],
                "step_free": True
            },
            {
                "gate_id": f"{code}_GATE_2",
                "gate_name": "Gate 2 - Circulating Area (Rear Entrance)",
                "recommended_for_platforms": ["3", "4", "5", "6"],
                "landmarks": f"{code} Second Entry / Station Parking Stand",
                "amenities": ["ATVM Kiosks", "Security Gate", "FOB Access"],
                "step_free": True
            }
        ],
        "foot_over_bridges": [
            {
                "fob_name": "Central Foot-Over-Bridge (Step-Free)",
                "connects_platforms": "All Platforms",
                "has_ramps": True,
                "has_lifts": True,
                "has_escalators": False,
                "traffic_density": "Standard flow"
            }
        ],
        "procedure_checkpoints": [
            {"step": 1, "title": "Main Porch Entry", "desc": f"Enter through {code} primary gate."},
            {"step": 2, "title": "Security & Tickets", "desc": "Clear scanner checkpoint and check platform indicator display."},
            {"step": 3, "title": "FOB Crossing", "desc": "Take Central FOB to reach destination platform."},
            {"step": 4, "title": "Platform Boarding", "desc": "Descend directly to your coach berth position."}
        ]
    }


def parse_rake_composition(coach_str: str, target_coach: str = None):
    """
    Parses live coach composition string (e.g. ENG-LPR-A3-A2-A1-H1-PC-B11-...-B1-LPR)
    Computes exact meter offsets and relative positions along a 600m platform.
    Standard LHB/ICF coach length = 24.0 meters. Engine = 22.0 meters.
    """
    if not coach_str:
        return {"total_coaches": 0, "coaches": [], "target_coach_info": None}

    # Split coaches
    raw_tokens = [c.strip().upper() for c in coach_str.replace(",", "-").split("-") if c.strip()]

    coaches = []
    current_distance = 0.0
    target_info = None

    for idx, code in enumerate(raw_tokens):
        length = 22.0 if code == "ENG" or "LOCO" in code else 24.0

        # Position relative to 600m platform
        relative_section = "Front" if idx < len(raw_tokens) / 3 else "Middle" if idx < (2 * len(raw_tokens)) / 3 else "Rear"

        # Class identification
        coach_type = "Locomotive" if code in ["ENG", "LOCO"] else \
                     "First AC (1A)" if code.startswith("H") else \
                     "AC 2-Tier (2A)" if code.startswith("A") else \
                     "AC 3-Tier (3A)" if code.startswith("B") else \
                     "AC 3-Economy (3E)" if code.startswith("M") else \
                     "Sleeper (SL)" if code.startswith("S") else \
                     "Pantry Car" if code == "PC" else \
                     "General / Unreserved" if code in ["GS", "GEN"] else \
                     "Luggage / Guard" if code in ["LPR", "SLR", "EOG"] else "Passenger Coach"

        coach_data = {
            "index": idx + 1,
            "coach_code": code,
            "coach_type": coach_type,
            "distance_from_engine_meters": round(current_distance),
            "platform_section": relative_section
        }
        coaches.append(coach_data)

        if target_coach and target_coach.upper().strip() == code:
            target_info = coach_data

        current_distance += length

    return {
        "total_coaches": len(coaches),
        "total_rake_length_meters": round(current_distance),
        "coaches": coaches,
        "target_coach_info": target_info
    }
