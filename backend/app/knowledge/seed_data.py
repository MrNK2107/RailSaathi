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
    # The IRCTC search shows each class by name and code; these records only restate what the class name says
    # and send passengers to the train's details on IRCTC for amenities and layout.
    _rule("tc-codes", "ticket_class", "What do the class codes 1A, 2A, 3A, 3E, SL, CC, EC and 2S mean?",
          "When you search for trains on IRCTC, each class is shown with a short code: 1A = AC First Class, "
          "2A = AC 2 Tier, 3A = AC 3 Tier, 3E = AC 3 Economy, SL = Sleeper, CC = AC Chair Car, "
          "EC = Executive Chair Car, 2S = Second Sitting. Not every train has every class; the IRCTC search lists "
          "the classes each train offers.",
          _CLASSES, "IRCTC train search shows the classes each train offers, by name and code.",
          ["The classes available differ from train to train"]),
    _rule("tc-sl", "ticket_class", "What is Sleeper (SL) class?",
          "Sleeper (SL) is the non-air-conditioned reserved class with sleeping berths, and usually the cheapest "
          "reserved sleeping class. Check the train's class details on IRCTC for what is provided.",
          _CLASSES, "IRCTC lists Sleeper (SL) among the classes a train offers.",
          ["No air conditioning", "Reservation is required"]),
    _rule("tc-3a", "ticket_class", "What is AC 3 Tier (3A) class?",
          "AC 3 Tier (3A) is an air-conditioned class with sleeping berths in three tiers. Check the train's class "
          "details on IRCTC for what is provided.",
          _CLASSES, "IRCTC lists AC 3 Tier (3A) among the classes a train offers.",
          ["Air-conditioned, three-tier berths", "Reservation is required"]),
    _rule("tc-3e", "ticket_class", "What is AC 3 Economy (3E) class?",
          "AC 3 Economy (3E) is an air-conditioned three-tier sleeping class offered on some trains, priced below "
          "AC 3 Tier. Check the train's class details on IRCTC.",
          _CLASSES, "IRCTC lists AC 3 Economy (3E) on the trains that offer it.",
          ["Offered on selected trains only"]),
    _rule("tc-2a", "ticket_class", "What is AC 2 Tier (2A) class?",
          "AC 2 Tier (2A) is an air-conditioned class with sleeping berths in two tiers. Check the train's class "
          "details on IRCTC for what is provided.",
          _CLASSES, "IRCTC lists AC 2 Tier (2A) among the classes a train offers.",
          ["Air-conditioned, two-tier berths", "Reservation is required"]),
    _rule("tc-1a", "ticket_class", "What is AC First Class (1A)?",
          "AC First Class (1A) is the highest air-conditioned sleeping class, offered only on some trains. Check "
          "the train's class details on IRCTC.",
          _CLASSES, "IRCTC lists AC First Class (1A) on the trains that offer it.",
          ["Offered only on some trains", "Reservation is required"]),
    _rule("tc-cc", "ticket_class", "What is AC Chair Car (CC)?",
          "AC Chair Car (CC) is an air-conditioned reserved seating class (seats, not berths), usually on day "
          "trains. Check the train's class details on IRCTC.",
          _CLASSES, "IRCTC lists AC Chair Car (CC) on the trains that offer it.",
          ["Seats only, no berths", "Reservation is required"]),
    _rule("tc-ec", "ticket_class", "What is Executive Chair Car (EC)?",
          "Executive Chair Car (EC) is the higher air-conditioned seating class (seats, not berths) on some day "
          "trains. Check the train's class details on IRCTC.",
          _CLASSES, "IRCTC lists Executive Chair Car (EC) on the trains that offer it.",
          ["Seats only, no berths", "Offered only on some trains"]),
    _rule("tc-2s", "ticket_class", "What is Second Sitting (2S)?",
          "Second Sitting (2S) is the non-air-conditioned reserved seating class (a reserved seat, not a berth). "
          "Check the train's class details on IRCTC.",
          _CLASSES, "IRCTC lists Second Sitting (2S) on the trains that offer it.",
          ["No air conditioning", "Seats only, no berths"]),
    # === RESERVATION STATUS ===
    # Status definitions are RailSaathi guidance; the cited PNR enquiry is where the passenger checks the actual
    # status, and the refund rules page covers what happens to RAC/WL tickets.
    _rule("rs-cnf", "reservation_status", "What does CNF (confirmed) status mean?",
          "CNF means the ticket has a confirmed berth or seat. Check the current status, and after charting the "
          "coach and berth or seat, on the official PNR enquiry.",
          _STATUS, "The official PNR enquiry shows a ticket's current status (for example CNF, RAC or WL).",
          ["You can travel on the allotted berth or seat"]),
    _rule("rs-rac", "reservation_status", "What does RAC (Reservation Against Cancellation) mean?",
          "RAC means you may board and travel, but with shared accommodation rather than a full berth of your "
          "own. If confirmed passengers cancel, an RAC ticket can move up to CNF before the chart is prepared. "
          "Check your current status on the official PNR enquiry.",
          _STATUS, "The official PNR enquiry shows a ticket's current status (for example CNF, RAC or WL).",
          ["RAC passengers may board and travel", "The status can change until the chart is prepared"]),
    _rule("rs-wl", "reservation_status", "What does WL (waitlisted) status mean?",
          "WL means you do not have a berth or seat yet; you are in a queue that moves up as others cancel. A "
          "waitlisted e-ticket that is still fully waitlisted when the chart is prepared is cancelled "
          "automatically and refunded to the original payment account, and passengers on it are not allowed to "
          "travel. See the official refund rules for the details, and check your status on the PNR enquiry.",
          _REFUND, "The official refund rules cover waitlisted tickets that are not confirmed at charting.",
          ["Check the latest status with your PNR before going to the station"],
          ["Counter (paper) tickets are handled differently from e-tickets",
           "A clerkage charge may apply; see the official refund rules"]),
    _rule("rs-wl-types", "reservation_status", "What are GNWL, RLWL and PQWL waitlists?",
          "Trains keep separate waitlists depending on where you board and get off, each tied to a reservation "
          "quota: GNWL (general), RLWL (remote location) and PQWL (pooled quota). Which one you join depends on "
          "your boarding and destination stations, and the general waitlist usually clears most often. The "
          "official quota codes page lists the quotas.",
          "src-ir-quota-codes", "The official quota codes page lists the reservation quotas.",
          ["Which waitlist you join depends on your boarding and destination stations"]),
    _rule("rs-chart", "reservation_status", "When does my waitlisted or RAC status become final?",
          "Status can change until the reservation chart is prepared before the train departs. After charting, "
          "the PNR shows the final status. Check your PNR on the official enquiry close to departure.",
          _STATUS, "The official PNR enquiry shows a ticket's current status.",
          ["Check the PNR status close to departure"]),
    # === BOOKING PROCESS ===
    _rule("bp-irctc-online", "booking_process", "How do I book a train ticket online on IRCTC?",
          "1. Open the official IRCTC site (https://www.irctc.co.in) or the IRCTC Rail Connect app and log in with "
          "your registered IRCTC account (register first if you do not have one).\n"
          "2. Enter the from and to stations, journey date, class and quota (for example General or Tatkal), then "
          "search.\n"
          "3. Check the availability shown for each train and class and pick one.\n"
          "4. Enter passenger details and review the summary.\n"
          "5. Pay with one of the offered payment options; the booking confirmation shows your PNR.\n"
          "RailSaathi only gives guidance; it never books or pays for tickets.",
          _CLASSES, "IRCTC train search: log in, search, choose train and class, add passengers, pay.",
          ["A registered IRCTC account is required",
           "Bookings open only within the advance reservation period"],
          ["Tatkal booking has its own opening times and rules"]),
    _rule("bp-advance-period", "booking_process", "How many days in advance can I book a train ticket?",
          "Reservations open a fixed number of days before the date of journey (the advance reservation period), "
          "and some trains have shorter windows. RailSaathi does not quote the number because it is revised from "
          "time to time: the IRCTC train search only offers journey dates that are currently open for booking, so "
          "check the latest date it allows.",
          _CLASSES, "IRCTC train search offers only the journey dates open for booking.",
          ["Bookings open only within the advance reservation period"]),
    _rule("bp-counter", "booking_process", "How do I book a ticket at a railway station counter?",
          "At a computerised reservation counter, fill in a reservation requisition form (train, date, stations, "
          "class and passenger details), hand it in at the counter and pay. You receive a printed ticket with the "
          "PNR. The same advance reservation period applies as for online bookings.",
          _CLASSES, "Reservations, online or at a counter, open within the advance reservation period.",
          ["Counters have fixed opening hours"],
          ["Counter tickets are cancelled at a counter, and some refund rules differ from e-tickets"]),
    _rule("bp-tatkal-window", "booking_process", "When does Tatkal booking open?",
          "Tatkal booking opens one day before the date of journey (not counting the journey date, counted from the "
          "train's originating station): at 10:00 for AC classes and at 11:00 for non-AC classes. Tatkal tickets "
          "cost more than general-quota tickets and are limited in number. Check the official Tatkal scheme page "
          "for the current rules.",
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
