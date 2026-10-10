"""Regex patterns and vocabularies for the deterministic (rule-based) extractor.
Covers common English, Tamil-script and Tanglish phrasings used in the demo."""

import re

from app.domain.enums import PassengerNeed

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "a couple": 2, "ஒன்று": 1, "இரண்டு": 2, "மூன்று": 3, "நான்கு": 4,
    "ஐந்து": 5, "ஆறு": 6,
}
_NUM = r"(\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"

RE_CANCEL = re.compile(r"\b(cancel|stop planning|quit|abort)\b|ரத்து")
RE_RESTART = re.compile(r"\b(start over|restart|reset|new journey|plan another)\b|மீண்டும் தொடங்")
RE_CONFIRM = re.compile(
    r"^\s*(yes[,!. ]*)?(i\s+)?(confirm|book it|go ahead|finali[sz]e|proceed with)\b|^\s*(yes|ok|okay)\s*[.!]?\s*$|உறுதி"
)
RE_SELECT = re.compile(
    r"\b(?:option|choice|select|choose|pick|take|go with|i(?:'ll| will) take)\b\s*(?:the\s+|number\s+|no\.?\s*)?"
    r"(\d|first|second|third|cheapest|fastest|best|quickest|lowest)"
)
RE_SHOW = re.compile(
    r"\b(show|find|search|recommend|suggest|list)\b.*\b(options?|trains?|journeys?|routes?)\b|"
    r"\bshow (me )?options\b|காட்டு|தேடு"
)
RE_GREETING = re.compile(r"^\s*(hi|hello|hey|vanakkam|வணக்கம்)\b")
RE_HELP = re.compile(r"^\s*(help|what can you do)\b|உதவி செய்")
RE_CORRECTION = re.compile(r"\b(change|actually|instead|correction|update|make it|not .* but)\b|மாற்று")
RE_RELAX = re.compile(
    r"\b(relax|remove|drop|forget|ignore|no|don't need|do not need|without)\b(?:\s+\w+){0,3}?\s+"
    r"(deadline|arrival time|budget(?: limit)?|price limit|class|direct|transfer|time limit|window|departure time)"
)

RE_DATE = re.compile(
    r"(day after tomorrow|நாளை\s*மறுநாள்|tomorrow|tmrw|today|tonight|நாளை|இன்று|naalai|nalaiku|inniki|"
    r"(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"(?:திங்கள்|செவ்வாய்|புதன்|வியாழன்|வெள்ளி|சனி|ஞாயிறு)|"
    r"\d{4}-\d{1,2}-\d{1,2}|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:\s+\d{4})?|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)"
)
_TIME = r"(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?(?:\s+in the (?:morning|evening|night))?)"
RE_DEADLINE = re.compile(
    r"\b(?:before|by|no later than|latest by|not later than|reach(?:ing)? (?:by|before)|arrive (?:by|before)|"
    r"be there by)\s+" + _TIME
)
RE_DEADLINE_TA = re.compile(
    r"(காலை|மாலை|இரவு|kaalai|kalai|maalai|malai|iravu)?\s*(\d{1,2})\s*"
    r"(?:மணி(?:க்குள்|க்கு முன்)|mani\s*(?:kku|ku)?\s*(?:munnadi|munnaadi|kulla|kulle|ulla))"
)
RE_SOFT = re.compile(r"\b(ideally|preferably|if possible|around|roughly|approximately|flexible)\b")
RE_ARRIVAL_ANCHOR = re.compile(r"\b(reach|arrive|arriving|be in|get to|be there)\b|சேர")
RE_DEPART_AFTER = re.compile(r"\b(?:leave|leaving|depart|departing|start|starting|departure)\s+(?:after|from)\s+" + _TIME)
RE_DEPART_BEFORE = re.compile(r"\b(?:leave|leaving|depart|departing|start|starting|departure)\s+(?:before|by)\s+" + _TIME)
RE_PERIOD = re.compile(
    r"\b(?:depart\w*|leav\w*|start\w*|travel\w*|go)\s+(?:in the\s+|at\s+)?(morning|afternoon|evening|night)\b|"
    r"\b(morning|afternoon|evening|night|overnight)\s+(?:train|departure|journey)\b"
)

RE_COUNT = re.compile(_NUM + r"\s+(?:passengers?|people|persons?|adults?|travell?ers?|of us|tickets?|members?|pax)\b")
RE_FAMILY = re.compile(r"\b(?:family of|we are|there are|party of)\s+" + _NUM + r"\b")
RE_ALONE = re.compile(r"\b(alone|solo|just me|only me|by myself|single passenger|one person)\b|தனியாக")
RE_KIDS_COUNT = re.compile(_NUM + r"\s+(?:kids|children|sons|daughters|babies)\b")
RELATIONS = (
    "mother-in-law", "father-in-law", "grandmother", "grandfather", "grandma", "grandpa", "mother", "father",
    "mom", "mum", "dad", "wife", "husband", "son", "daughter", "brother", "sister", "friend", "colleague",
    "amma", "appa", "அம்மா", "அப்பா", "மனைவி", "கணவர்", "மகன்", "மகள்", "பாட்டி", "தாத்தா",
)
PAIR_RELATIONS = {"parents": 2, "grandparents": 2, "பெற்றோர்": 2}

NEED_PATTERNS: dict[PassengerNeed, re.Pattern[str]] = {
    PassengerNeed.WHEELCHAIR: re.compile(r"wheel\s*chair|சக்கர நாற்காலி"),
    PassengerNeed.ASSISTANCE_REQUESTED: re.compile(
        r"\bassist(ance)?\b|\bhelp (?:with|boarding|getting)|\bsupport\b|\bneeds? help\b|உதவி தேவை|உதவி வேண்டும்"),
    PassengerNeed.REDUCED_WALKING: re.compile(r"(less|reduced|minimal|limited) walking|can(?:no|')t walk|difficulty walking"),
    PassengerNeed.TRAVELLING_WITH_CHILDREN: re.compile(r"\b(kids?|child(?:ren)?|baby|babies|infant|toddler)\b|குழந்தை"),
    PassengerNeed.TRAVELLING_WITH_ELDERLY: re.compile(r"\b(elderly|senior|old age|aged|grand(?:mother|father|ma|pa|parents))\b|பாட்டி|தாத்தா|வயதான"),
    PassengerNeed.DAYTIME_DEPARTURE: re.compile(r"\bday\s*time\b|\bday train\b|during the day|avoid (?:night|overnight)|பகல்"),
    PassengerNeed.LONGER_TRANSFER_BUFFER: re.compile(r"(longer|more|extra|enough) (?:time (?:to|for) chang\w*|connection|transfer|buffer)"),
}
RE_ASSIST_MANDATORY = re.compile(
    r"(assistance|wheelchair|help)\s+(?:is\s+)?(mandatory|essential|compulsory|a must|required)|"
    r"must (?:have|get) (?:assistance|a wheelchair|help)|only (?:stations|journeys|trains) with (?:assistance|wheelchair)"
)

RE_COST = re.compile(r"\b(cheap|cheapest|cheaper|lowest (?:fare|price|cost)|least expensive|economical|low cost|save money)\b|மலிவ|குறைந்த கட்டண|kammi")
RE_TIME = re.compile(r"\b(fastest|quickest|shortest|quick|fast|least time)\b|வேகமான|சீக்கிர")
RE_BUDGET = re.compile(
    r"(under|below|within|less than|max(?:imum)?|budget(?: of| is)?|not more than|up ?to|at most|cannot exceed|can't exceed)"
    r"\s*(?:of\s*)?(?:rs\.?|₹|inr)?\s*(\d[\d,]*)\s*(?:rs|rupees|₹|inr)?"
)
RE_BUDGET_STRICT = re.compile(r"\b(max(?:imum)?|not more than|at most|cannot exceed|can't exceed|strict(?:ly)?|hard limit)\b")
RE_STRICT_WORD = re.compile(r"\b(only|must|strictly|mandatory|have to)\b")

RE_DIRECT = re.compile(r"\b(direct|no change|without chang\w*|avoid (?:transfers?|changes?|connections?)|no (?:transfers?|connections?)|single train)\b")
RE_DIRECT_SOFT = re.compile(r"\b(prefer(?:ably)?|if possible|ideally)\b")
RE_ALLOW_TRANSFER = re.compile(r"(transfers?|changes?|connections?) (?:are|is) (?:ok|okay|fine)|don't mind chang")

UNSUPPORTED = {
    "window seat": "seat selection", "lower berth": "berth selection", "upper berth": "berth selection",
    "meal": "meal booking", "tatkal": "Tatkal booking", "pnr": "PNR tracking", "refund": "refunds",
    "wifi": "on-board Wi-Fi information",
}

STOP_WORDS = {
    "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "tomorrow", "today",
    "the", "my", "a", "an", "be", "reach", "change", "travel", "go", "ac", "sleeper", "chair",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "before", "after", "morning", "evening", "night", "three", "two", "four",
}
