"""Coach position from a coach composition the passenger supplies (e.g. ENG-A1-B1-B2-SL).

RailSaathi has no live rake data: `GET /api/trains/rake-position` only works out where a coach sits within a
composition that the caller provides, with nominal coach lengths."""


def parse_rake_composition(coach_str: str, target_coach: str = None):
    """
    Parses a passenger-supplied coach composition string (e.g. ENG-LPR-A3-A2-A1-H1-PC-B11-...-B1-LPR).
    Estimates each coach's distance from the engine with nominal lengths (coach 24.0 m, engine 22.0 m; real LHB/ICF
    rakes differ) and its rough section (front/middle/rear third) of the train. Not live data, not exact positions.
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
        # Fixed codes first: SLR/LPR/EOG (luggage/guard vans) would otherwise match the S (Sleeper) prefix.
        coach_type = "Locomotive" if code in ["ENG", "LOCO"] else \
                     "Luggage / Guard" if code in ["LPR", "SLR", "EOG"] else \
                     "Pantry Car" if code == "PC" else \
                     "General / Unreserved" if code in ["GS", "GEN"] else \
                     "First AC (1A)" if code.startswith("H") else \
                     "AC 2-Tier (2A)" if code.startswith("A") else \
                     "AC 3-Tier (3A)" if code.startswith("B") else \
                     "AC 3-Economy (3E)" if code.startswith("M") else \
                     "Sleeper (SL)" if code.startswith("S") else "Passenger Coach"

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
