"""Assistant message templates (English and Tamil). The assistant's wording is
template-driven, not LLM-generated, so it stays consistent and truthful."""

from app.domain.enums import Language

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "ask_destination": "Where would you like to travel to?",
        "ask_origin": "Where will you be travelling from?",
        "ask_journey_date": "Which date do you want to travel?",
        "ask_passenger_count": "How many passengers are travelling, including you?",
        "ask_preferences": "Do you need to arrive by a particular time, or would you prefer the cheapest "
                           "or fastest journey? (Say \"no preference\" to see all options.)",
        "ambiguous_station": "I found more than one match for \"{query}\". Which one do you mean: {options}?",
        "station_not_found": "I couldn't find \"{query}\" in the demo station list. Available places: {options}.",
        "field_issue": "{message}",
        "recs_ready": "I found {eligible} eligible option(s) out of {considered} in the demo data. "
                      "Here are my recommendations — choose one to review it.",
        "no_options": "No option in the current demo dataset meets all of your mandatory requirements.",
        "no_options_live": "No train in the live RailRadar results meets all of your mandatory requirements.",
        "recs_ready_live": "I found {eligible} eligible option(s) out of {considered} in live RailRadar data. "
                           "Here are my recommendations — choose one to review it. Timings can change; "
                           "fares may be missing.",
        "data_unavailable": "Live train data is unavailable right now ({reason}). Your details are saved — "
                            "say \"show options\" to try again.",
        "relax_offer": "You could relax a constraint: {options}.",
        "selected": "You selected {summary}. Review the summary and say \"confirm\" to approve this plan "
                    "for handoff. No ticket will be booked.",
        "confirmed": "Your journey plan is confirmed for handoff (ref {ref}). No ticket has been booked "
                     "and no seat is reserved.",
        "cancelled": "Planning cancelled. Say \"start over\" whenever you want to plan again.",
        "restarted": "Let's start a new plan. Where would you like to travel to?",
        "help": "Tell me where and when you want to travel, who is travelling, and what matters most "
                "(cheapest, fastest, arrival time, class, assistance). I'll ask only for what's missing.",
        "nothing_changed": "I didn't catch a change. Pick an option (e.g. \"option 1\") or tell me what to change.",
        "need_selection": "Please choose one of the recommended options before confirming.",
        "need_recommendations": "I still need a few details before I can search for options.",
        "updated": "Updated: {fields}.",
        "recalculated": "Your earlier recommendations no longer match and have been recalculated.",
        "unsupported": "This planner can't handle: {items}. I'll continue with the rest of your request.",
        "assistance_note": "Assistance is requested but not verified at every station for some options. "
                           "Say \"assistance is mandatory\" to see only options with listed assistance.",
        "assistance_mandatory_note": "You said assistance is mandatory. Options marked \"not verified\" do not have "
                                     "listed assistance at every station, so they are not fully compliant.",
        "session_cancelled": "This planning session was cancelled. Say \"start over\" to plan a new journey.",
        "llm_fallback": "",
    },
    "ta": {
        "ask_destination": "நீங்கள் எங்கு செல்ல விரும்புகிறீர்கள்?",
        "ask_origin": "நீங்கள் எங்கிருந்து பயணம் செய்கிறீர்கள்?",
        "ask_journey_date": "எந்த தேதியில் பயணம் செய்ய விரும்புகிறீர்கள்?",
        "ask_passenger_count": "உங்களையும் சேர்த்து எத்தனை பயணிகள்?",
        "ask_preferences": "குறிப்பிட்ட நேரத்திற்குள் சேர வேண்டுமா, அல்லது மலிவான / விரைவான பயணம் வேண்டுமா? "
                           "(எல்லா விருப்பங்களையும் பார்க்க \"no preference\" என்று சொல்லுங்கள்.)",
        "ambiguous_station": "\"{query}\" க்கு பல பொருத்தங்கள் உள்ளன. எதைக் குறிப்பிடுகிறீர்கள்: {options}?",
        "station_not_found": "\"{query}\" டெமோ நிலையப் பட்டியலில் இல்லை. கிடைப்பவை: {options}.",
        "field_issue": "{message}",
        "recs_ready": "டெமோ தரவில் {considered} விருப்பங்களில் {eligible} தகுதியானவை. "
                      "என் பரிந்துரைகள் இதோ — ஒன்றைத் தேர்ந்தெடுங்கள்.",
        "no_options": "உங்கள் கட்டாயத் தேவைகள் அனைத்தையும் பூர்த்தி செய்யும் விருப்பம் தற்போதைய டெமோ தரவில் இல்லை.",
        "no_options_live": "உங்கள் கட்டாயத் தேவைகளைப் பூர்த்தி செய்யும் ரயில் RailRadar நேரடி தரவில் இல்லை.",
        "recs_ready_live": "RailRadar நேரடி தரவில் {considered} இல் {eligible} தகுதியானவை. என் பரிந்துரைகள் இதோ. "
                           "நேரங்கள் மாறலாம்; கட்டணம் இல்லாமல் இருக்கலாம்.",
        "data_unavailable": "நேரடி ரயில் தரவு தற்போது கிடைக்கவில்லை ({reason}). உங்கள் விவரங்கள் சேமிக்கப்பட்டுள்ளன — "
                            "மீண்டும் முயற்சிக்க \"show options\" என்று சொல்லுங்கள்.",
        "relax_offer": "ஒரு நிபந்தனையைத் தளர்த்தலாம்: {options}.",
        "selected": "நீங்கள் தேர்ந்தெடுத்தது: {summary}. சுருக்கத்தைப் பார்த்து \"confirm\" / \"உறுதி\" என்று சொல்லுங்கள். "
                    "டிக்கெட் எதுவும் முன்பதிவு செய்யப்படாது.",
        "confirmed": "உங்கள் பயணத் திட்டம் உறுதி செய்யப்பட்டது (ref {ref}). டிக்கெட் முன்பதிவு செய்யப்படவில்லை.",
        "cancelled": "திட்டமிடல் ரத்து செய்யப்பட்டது. மீண்டும் தொடங்க \"start over\" என்று சொல்லுங்கள்.",
        "restarted": "புதிய திட்டத்தைத் தொடங்குவோம். எங்கு செல்ல விரும்புகிறீர்கள்?",
        "help": "எங்கு, எப்போது, யாருடன் பயணம் செய்கிறீர்கள், எது முக்கியம் (மலிவு, வேகம், நேரம், வகுப்பு, உதவி) என்று "
                "சொல்லுங்கள். தேவையானதை மட்டும் கேட்பேன்.",
        "nothing_changed": "மாற்றம் எதுவும் புரியவில்லை. ஒரு விருப்பத்தைத் தேர்ந்தெடுங்கள் (எ.கா. \"option 1\").",
        "need_selection": "உறுதி செய்வதற்கு முன் ஒரு விருப்பத்தைத் தேர்ந்தெடுங்கள்.",
        "need_recommendations": "விருப்பங்களைத் தேட இன்னும் சில விவரங்கள் தேவை.",
        "updated": "புதுப்பிக்கப்பட்டது: {fields}.",
        "recalculated": "முந்தைய பரிந்துரைகள் பொருந்தவில்லை; மீண்டும் கணக்கிடப்பட்டன.",
        "unsupported": "இவற்றை இந்த திட்டமிடுபவர் கையாள முடியாது: {items}.",
        "assistance_note": "சில விருப்பங்களில் எல்லா நிலையங்களிலும் உதவி சரிபார்க்கப்படவில்லை. "
                           "சரிபார்க்கப்பட்டவை மட்டும் வேண்டுமெனில் \"assistance is mandatory\" என்று சொல்லுங்கள்.",
        "assistance_mandatory_note": "உதவி கட்டாயம் என்று சொன்னீர்கள். \"சரிபார்க்கப்படவில்லை\" எனக் குறிக்கப்பட்ட "
                                     "விருப்பங்களில் எல்லா நிலையங்களிலும் உதவி பட்டியலிடப்படவில்லை.",
        "session_cancelled": "இந்த அமர்வு ரத்து செய்யப்பட்டது. புதிதாகத் தொடங்க \"start over\" என்று சொல்லுங்கள்.",
        "llm_fallback": "",
    },
}

FIELD_LABELS = {
    "en": {
        "origin": "origin", "destination": "destination", "journey_date": "date",
        "passenger_count": "passengers", "arrival_deadline": "arrival deadline",
        "departure_window": "departure window", "budget_limit": "budget", "budget_priority": "priority",
        "class_preference": "class", "passenger_needs": "passenger needs",
        "transfer_preference": "transfers", "assistance_mandatory": "assistance requirement",
        "date_anchor": "date meaning", "deadline_strict": "deadline type", "budget_strict": "budget type",
        "class_strict": "class requirement", "transfer_strict": "transfer requirement",
    },
    "ta": {
        "origin": "புறப்படும் இடம்", "destination": "சேருமிடம்", "journey_date": "தேதி",
        "passenger_count": "பயணிகள்", "arrival_deadline": "சேரும் நேரம்", "departure_window": "புறப்படும் நேரம்",
        "budget_limit": "பட்ஜெட்", "budget_priority": "முன்னுரிமை", "class_preference": "வகுப்பு",
        "passenger_needs": "பயணி தேவைகள்", "transfer_preference": "மாற்றங்கள்",
        "assistance_mandatory": "உதவி தேவை", "date_anchor": "தேதி பொருள்", "deadline_strict": "காலக்கெடு வகை",
        "budget_strict": "பட்ஜெட் வகை", "class_strict": "வகுப்பு தேவை", "transfer_strict": "மாற்ற தேவை",
    },
}


def msg(lang: Language, key: str, **kw: object) -> str:
    return MESSAGES[lang.value][key].format(**kw)


def field_label(lang: Language, field: str) -> str:
    return FIELD_LABELS[lang.value].get(field, field)
