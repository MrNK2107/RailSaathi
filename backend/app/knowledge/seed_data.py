"""
RailSathi AI — Curated Ticketing Knowledge Seed Data

Guidance, not official policy. Every record is attributed to a public page on an official Indian Railways
domain (irctc.co.in / indianrail.gov.in) and carries `as_of`, the date the record was written (2026-10-14).
Rules change: answers built on these records must tell passengers to verify the linked official page before acting.

Deliberately NOT included: fares, Tatkal surcharges, and exact cancellation amounts or time slabs. These are revised
from time to time and stating them from memory would risk giving passengers wrong numbers; records point to the
official refund rules instead.
"""

AS_OF = "2026-10-14"

_IR_STATIC = "https://www.indianrail.gov.in/enquiry/StaticPages/StaticEnquiry.jsp?StaticPage="

_SOURCE_DEFAULTS = {
    "source_type": "official_web_page",
    "retrieved_at": AS_OF,
    "last_verified_at": AS_OF,
    "as_of": AS_OF,
    "publication_date": None,
    "effective_from": None,
    "effective_until": None,
    "verification_status": "curated_guidance",
    "retrieval_status": "success",
}

SOURCES = [
    {
        **_SOURCE_DEFAULTS,
        "source_id": "src-irctc-train-search",
        "title": "IRCTC Next Generation e-Ticketing: train search and booking",
        "publisher": "IRCTC",
        "source_url": "https://www.irctc.co.in/nget/train-search",
        "notes": "Official IRCTC booking site. Travel classes, quotas and the booking flow are shown in the search "
                 "and booking screens. Guidance compiled by RailSaathi; verify on the site.",
    },
    {
        **_SOURCE_DEFAULTS,
        "source_id": "src-ir-pnr-enquiry",
        "title": "Indian Railways Passenger Reservation Enquiry: PNR status",
        "publisher": "Indian Railways (CRIS)",
        "source_url": "https://www.indianrail.gov.in/enquiry/PNR/PnrEnquiry.html?locale=en",
        "notes": "Official PNR enquiry, which shows booking and current status (CNF / RAC / WL).",
    },
    {
        **_SOURCE_DEFAULTS,
        "source_id": "src-ir-quota-codes",
        "title": "Indian Railways Passenger Reservation Enquiry: quota codes",
        "publisher": "Indian Railways (CRIS)",
        "source_url": _IR_STATIC + "quota_Code.html&locale=en",
        "notes": "Official list of reservation quota codes, linked from the enquiry portal's View Codes menu.",
    },
    {
        **_SOURCE_DEFAULTS,
        "source_id": "src-ir-tatkal-scheme",
        "title": "Indian Railways Passenger Reservation Enquiry: Tatkal scheme",
        "publisher": "Indian Railways (CRIS)",
        "source_url": _IR_STATIC + "tatkal_Scheme.html&locale=en",
        "notes": "Official Tatkal scheme page, linked from the enquiry portal's View Codes menu.",
    },
    {
        **_SOURCE_DEFAULTS,
        "source_id": "src-ir-refund-rules",
        "title": "Indian Railways Passenger Reservation Enquiry: refund rules",
        "publisher": "Indian Railways (CRIS)",
        "source_url": _IR_STATIC + "refund_Rules.html&locale=en",
        "notes": "Official cancellation and refund rules, linked from the enquiry portal's Rules menu. Charges and "
                 "time windows are revised from time to time; this page is the authority.",
    },
]


def _rule(guidance_id: str, topic: str, question: str, answer: str, source_id: str, excerpt: str,
          conditions: list[str] | None = None, exceptions: list[str] | None = None) -> dict:
    return {
        "guidance_id": guidance_id,
        "topic": topic,
        "question": question,
        "answer_text": answer,
        "conditions": conditions or [],
        "exceptions": exceptions or [],
        "source_id": source_id,
        "source_excerpt": excerpt,
        "last_verified_at": AS_OF,
        "as_of": AS_OF,
        "status": "active",
    }


_CLASSES = "src-irctc-train-search"
_STATUS = "src-ir-pnr-enquiry"
_REFUND = "src-ir-refund-rules"

GUIDANCE_RECORDS = [
    # === TICKET CLASSES ===
    _rule("tc-codes", "ticket_class", "What do the class codes 1A, 2A, 3A, 3E, SL, CC, EC and 2S mean?",
          "Indian Railways travel classes are shown by short codes when you search for trains: "
          "1A = AC First Class, 2A = AC 2 Tier, 3A = AC 3 Tier, 3E = AC 3 Tier Economy, SL = Sleeper Class, "
          "CC = AC Chair Car, EC = Executive Chair Car, 2S = Second Sitting. Not every train has every class; "
          "the classes a train offers are listed when you search for it on IRCTC.",
          _CLASSES, "Class codes: 1A, 2A, 3A, 3E, SL, CC, EC, 2S.",
          ["The classes available differ from train to train"]),
    _rule("tc-sl", "ticket_class", "What is Sleeper (SL) class?",
          "Sleeper Class (SL) is the non-air-conditioned reserved class with three-tier sleeping berths (lower, "
          "middle and upper, plus side berths). It is the most economical reserved sleeping class on long-distance "
          "Mail and Express trains. Bedding is not supplied in Sleeper Class.",
          _CLASSES, "SL: Sleeper Class, non-AC three-tier berths.",
          ["No air conditioning", "Bedding is not supplied", "Reservation is required"],
          ["Fully air-conditioned trains do not have Sleeper Class"]),
    _rule("tc-3a", "ticket_class", "What is AC 3 Tier (3A) class?",
          "AC 3 Tier (3A) is an air-conditioned class with three-tier sleeping berths (lower, middle and upper, "
          "plus side berths). Bedding is normally supplied. It costs more than Sleeper and less than AC 2 Tier.",
          _CLASSES, "3A: AC 3 Tier, air-conditioned three-tier berths.",
          ["Air-conditioned three-tier berths", "Reservation is required"]),
    _rule("tc-3e", "ticket_class", "What is AC 3 Tier Economy (3E) class?",
          "AC 3 Tier Economy (3E) is an air-conditioned three-tier sleeping class whose coaches carry more berths "
          "than a standard 3A coach, and it is priced below 3A. It is offered only on some trains, and amenities can "
          "differ from 3A; check the train's details on IRCTC.",
          _CLASSES, "3E: AC 3 Tier Economy, offered on selected trains.",
          ["Available on selected trains only"], ["Amenities may differ from 3A; verify for your train"]),
    _rule("tc-2a", "ticket_class", "What is AC 2 Tier (2A) class?",
          "AC 2 Tier (2A) is an air-conditioned class with two-tier sleeping berths (lower and upper, plus side "
          "berths), giving more headroom and privacy than 3A. Bedding is normally supplied.",
          _CLASSES, "2A: AC 2 Tier, air-conditioned two-tier berths.",
          ["Air-conditioned two-tier berths", "Reservation is required"]),
    _rule("tc-1a", "ticket_class", "What is AC First Class (1A)?",
          "AC First Class (1A) is the highest regular class: air-conditioned lockable cabins (two-berth coupes and "
          "four-berth cabins) with bedding supplied. It is offered only on some trains.",
          _CLASSES, "1A: AC First Class, lockable cabins and coupes.",
          ["Offered only on some trains", "Reservation is required"]),
    _rule("tc-cc", "ticket_class", "What is AC Chair Car (CC)?",
          "AC Chair Car (CC) is an air-conditioned reserved seating class (no berths), used on day trains such as "
          "Shatabdi, Jan Shatabdi, Vande Bharat and some Intercity services.",
          _CLASSES, "CC: AC Chair Car, air-conditioned reserved seats.",
          ["Seats only, no berths", "Reservation is required"]),
    _rule("tc-ec", "ticket_class", "What is Executive Chair Car (EC)?",
          "Executive Chair Car (EC) is the premium air-conditioned seating class on day trains such as Shatabdi "
          "and Vande Bharat, with wider seats than AC Chair Car.",
          _CLASSES, "EC: Executive Chair Car, premium AC seating.",
          ["Seats only, no berths", "Offered only on some day trains"]),
    _rule("tc-2s", "ticket_class", "What is Second Sitting (2S)?",
          "Second Sitting (2S) is the non-air-conditioned reserved seating class: a reserved seat, no berth. "
          "It is the most economical reserved class.",
          _CLASSES, "2S: Second Sitting, non-AC reserved seats.",
          ["No air conditioning", "Seats only, no berths"]),
    # === RESERVATION STATUS ===
    _rule("rs-cnf", "reservation_status", "What does CNF (confirmed) status mean?",
          "CNF means the ticket has a confirmed berth or seat. Once the reservation chart is prepared, the coach "
          "and berth or seat number are shown against the PNR.",
          _STATUS, "CNF: confirmed berth or seat.",
          ["You can board and use the allotted berth or seat"]),
    _rule("rs-rac", "reservation_status", "What does RAC (Reservation Against Cancellation) mean?",
          "RAC means you may board and travel, but you are given a shared berth (typically one side-lower berth "
          "shared by two RAC passengers) rather than a full berth. If confirmed passengers cancel, an RAC ticket can "
          "move up to CNF before the chart is prepared.",
          _STATUS, "RAC: may board with shared accommodation; can be upgraded to confirmed.",
          ["RAC passengers may board and travel", "The status can change until the chart is prepared"]),
    _rule("rs-wl", "reservation_status", "What does WL (waitlisted) status mean?",
          "WL means you do not have a berth or seat yet; you are in a queue that moves up as others cancel. A "
          "waitlisted e-ticket (booked on IRCTC) that is still fully waitlisted when the chart is prepared is "
          "cancelled automatically and the refund goes to the original payment account. Passengers whose e-ticket "
          "is still fully waitlisted after charting are not allowed to travel on it.",
          _STATUS, "WL: waitlisted; fully waitlisted e-tickets are dropped at charting and refunded.",
          ["Check the latest status with your PNR before going to the station",
           "Fully waitlisted e-tickets are cancelled automatically at chart preparation"],
          ["Counter (paper) tickets are handled differently from e-tickets",
           "The refund for an automatically cancelled e-ticket can be subject to a small clerkage charge; "
           "see the official refund rules"]),
    _rule("rs-wl-types", "reservation_status", "What are GNWL, RLWL and PQWL waitlists?",
          "Trains keep separate waitlists depending on where you board and get off. GNWL (general waitlist) is for "
          "journeys from or near the train's origin and usually clears most often. RLWL (remote location waitlist) "
          "is for journeys from certain intermediate stations, and PQWL (pooled quota waitlist) is for shorter "
          "journeys between intermediate stations; these have smaller quotas and usually clear less often. "
          "Quota codes are listed on the official enquiry portal.",
          "src-ir-quota-codes", "Waitlist types follow the quota the ticket is booked under: GNWL, RLWL, PQWL.",
          ["Which waitlist you join depends on your boarding and destination stations"],
          ["Other quotas (for example Tatkal, ladies, senior citizen) have their own rules"]),
    _rule("rs-chart", "reservation_status", "When does my waitlisted or RAC status become final?",
          "Status keeps changing until the reservation chart is prepared before the train departs. After charting, "
          "the PNR shows the final status and, for confirmed passengers, the coach and berth. Check your PNR on the "
          "official enquiry site close to departure.",
          _STATUS, "Status is final once the reservation chart is prepared.",
          ["Check the PNR status close to departure"]),
    # === BOOKING PROCESS ===
    _rule("bp-irctc-online", "booking_process", "How do I book a train ticket online on IRCTC?",
          "1. Open the official IRCTC site (https://www.irctc.co.in) or the IRCTC Rail Connect app and log in with "
          "your registered IRCTC account (register first if you do not have one).\n"
          "2. Enter the from and to stations, journey date, class and quota (for example General or Tatkal), then "
          "search.\n"
          "3. Check the availability shown for each train and class (AVAILABLE, RAC or WL) and pick one.\n"
          "4. Enter passenger details and review the summary.\n"
          "5. Pay with one of the offered payment options. The e-ticket and PNR are sent by SMS and e-mail.\n"
          "RailSaathi only gives guidance; it never books or pays for tickets.",
          _CLASSES, "IRCTC online booking: log in, search, choose train and class, add passengers, pay.",
          ["A registered IRCTC account is required",
           "Bookings open only within the advance reservation period"],
          ["Tatkal booking has its own opening times and rules"]),
    _rule("bp-advance-period", "booking_process", "How many days in advance can I book a train ticket?",
          "For most trains, general-quota reservations open 60 days in advance, not counting the date of journey "
          "(this window was reduced from 120 days with effect from 1 November 2024). Some trains, such as certain "
          "day trains, have shorter windows. The IRCTC search only offers dates that are open for booking.",
          _CLASSES, "Advance reservation period: 60 days excluding the date of journey (from 1 November 2024).",
          ["The window does not count the date of journey"],
          ["Some trains have a shorter advance reservation period", "Foreign tourist quota rules differ"]),
    _rule("bp-counter", "booking_process", "How do I book a ticket at a railway station counter?",
          "At a computerised reservation counter, fill in a reservation requisition form (train, date, stations, "
          "class and passenger details), hand it in at the counter and pay. You receive a printed ticket with the "
          "PNR. Counter tickets follow the same advance reservation period as online bookings.",
          _CLASSES, "Counter booking: requisition form, pay at the counter, printed ticket with PNR.",
          ["Counters have fixed opening hours"],
          ["Counter tickets are cancelled at a counter, and some refund rules differ from e-tickets"]),
    _rule("bp-tatkal-window", "booking_process", "When does Tatkal booking open?",
          "Tatkal booking opens one day before the date of journey (not counting the journey date, counted from the "
          "train's originating station): at 10:00 for AC classes and at 11:00 for non-AC classes. Tatkal tickets "
          "cost more than general-quota tickets and are limited in number, so they often sell out within minutes.",
          "src-ir-tatkal-scheme", "Tatkal: opens one day in advance, 10:00 for AC classes, 11:00 for non-AC.",
          ["One day in advance, excluding the date of journey", "AC classes 10:00, non-AC classes 11:00",
           "Tatkal charges are added to the fare"],
          ["Check the official Tatkal scheme page for current identity and passenger-limit rules"]),
    # === CANCELLATION & REFUND ===
    _rule("cr-general", "cancellation_refund", "How are cancellation charges and refunds worked out?",
          "For a confirmed ticket, the cancellation charge depends on the class and on how long before the train's "
          "scheduled departure you cancel: cancelling earlier costs less, and close to departure the refund can be "
          "small or nil. RAC and waitlisted tickets have a separate, lower charge if cancelled in time. These time "
          "windows and charges are revised from time to time, so RailSaathi does not quote amounts: check the "
          "current slabs on the official refund rules page before you cancel.",
          _REFUND, "Cancellation charges depend on class and time before departure; see the official slabs.",
          ["Charges vary by class and by time before scheduled departure",
           "E-tickets are cancelled online; counter tickets at a counter"],
          ["Tatkal tickets have their own rules", "A train cancelled by the railways gets a full refund"]),
    _rule("cr-eticket", "cancellation_refund", "How do I cancel an IRCTC e-ticket?",
          "Log in to the IRCTC site or app with the account that booked the ticket, open your booked tickets "
          "(My Transactions / Booked Ticket History), select the PNR and the passengers to cancel, and confirm. "
          "The refund, after any cancellation charge, goes back to the original payment method. If online "
          "cancellation is no longer allowed for your case, a TDR (Ticket Deposit Receipt) may be filed instead.",
          _REFUND, "E-ticket cancellation: IRCTC account, booked tickets, cancel; refund to the original payment.",
          ["Use the IRCTC account that booked the ticket", "Refunds go to the original payment method"],
          ["Some situations need a TDR instead of a normal cancellation"]),
    _rule("cr-tatkal", "cancellation_refund", "Can I get a refund if I cancel a confirmed Tatkal ticket?",
          "No refund is given when you cancel a confirmed Tatkal ticket yourself. Waitlisted Tatkal tickets can be "
          "cancelled with the applicable charge, and a refund may be claimed in specific cases such as the train "
          "being cancelled or running very late; see the official refund rules.",
          _REFUND, "Confirmed Tatkal tickets: no refund on cancellation by the passenger.",
          ["Confirmed Tatkal: no refund on passenger cancellation"],
          ["Train cancellation or very late running can allow a refund claim"]),
    _rule("cr-train-cancelled", "cancellation_refund", "What if the railways cancel my train?",
          "If the railways cancel the train, passengers are entitled to a full refund of the fare. For IRCTC "
          "e-tickets on a fully cancelled train the ticket is normally cancelled and refunded automatically to the "
          "original payment method; check your booked ticket history, and follow the official refund rules if it "
          "is not.",
          _REFUND, "Train cancelled by the railways: full refund.",
          ["Full refund when the railways cancel the train"]),
    _rule("cr-tdr", "cancellation_refund", "What is a TDR (Ticket Deposit Receipt)?",
          "A TDR is the request you file (online from your IRCTC booked tickets for e-tickets) to claim a refund in "
          "situations a normal cancellation does not cover, for example when you could not travel because the train "
          "ran very late. Whether a refund is due, and how much, is decided under the official refund rules.",
          _REFUND, "TDR: the claim filed for refunds outside normal cancellation.",
          ["TDRs have their own filing deadlines; see the official rules"]),
]
