"""
RailSathi AI — Curated Ticketing Knowledge Seed Data

Source-backed Indian Railways ticketing guidance.
Each guidance record references an authoritative source.

IMPORTANT: All source URLs and content are based on publicly available
Indian Railways and IRCTC information. Verification dates reflect the
date this data was curated, not necessarily the current policy date.
Users should always verify current rules at official sources.
"""

SOURCES = [
    {
        "source_id": "src-irctc-classes",
        "title": "IRCTC Train Classes and Accommodation Types",
        "publisher": "IRCTC / Indian Railways",
        "source_url": "https://www.irctc.co.in/nget/train-list",
        "source_type": "official_documentation",
        "retrieved_at": "2026-01-15",
        "last_verified_at": "2026-01-15",
        "publication_date": None,
        "effective_from": None,
        "effective_until": None,
        "verification_status": "manually_verified",
        "retrieval_status": "success",
        "notes": "Information about Indian Railways travel classes compiled from official IRCTC booking interface and Indian Railways documentation.",
    },
    {
        "source_id": "src-irctc-booking",
        "title": "IRCTC Online Ticket Booking Process",
        "publisher": "IRCTC",
        "source_url": "https://www.irctc.co.in/nget/train-search",
        "source_type": "official_documentation",
        "retrieved_at": "2026-01-15",
        "last_verified_at": "2026-01-15",
        "verification_status": "manually_verified",
        "retrieval_status": "success",
        "notes": "Official IRCTC online booking steps and requirements.",
    },
    {
        "source_id": "src-irctc-reservation",
        "title": "Indian Railways Reservation Status Terminology",
        "publisher": "Indian Railways",
        "source_url": "https://www.indianrail.gov.in/enquiry/StaticPages/StaticEnquiry.jsp?StaticPage=PNR_help.html",
        "source_type": "official_documentation",
        "retrieved_at": "2026-01-15",
        "last_verified_at": "2026-01-15",
        "verification_status": "manually_verified",
        "retrieval_status": "success",
        "notes": "PNR status terminology and reservation status explanations.",
    },
    {
        "source_id": "src-irctc-refund",
        "title": "Indian Railways Cancellation and Refund Rules",
        "publisher": "Indian Railways",
        "source_url": "https://www.irctc.co.in/nget/cancellation-refund-rules",
        "source_type": "official_documentation",
        "retrieved_at": "2026-01-15",
        "last_verified_at": "2026-01-15",
        "verification_status": "manually_verified",
        "retrieval_status": "success",
        "notes": "Cancellation charges and refund rules for tickets booked through IRCTC. Rules may be updated by Indian Railways; passengers should verify current rules before cancellation.",
    },
]

GUIDANCE_RECORDS = [
    # === TICKET CLASSES ===
    {
        "guidance_id": "tc-sl",
        "topic": "ticket_class",
        "question": "What is Sleeper (SL) class?",
        "answer_text": (
            "Sleeper Class (SL) is one of the most popular and economical classes in Indian Railways "
            "for long-distance travel. It provides sleeping berths arranged in a three-tier configuration. "
            "Each bay has 6 berths: 2 lower, 2 middle, and 2 upper berths, plus 2 side berths (upper and lower). "
            "SL class does not have air conditioning. Bedding is not provided; passengers typically carry their own. "
            "Sleeper class is available on most Mail, Express, and Superfast trains."
        ),
        "conditions": [
            "No air conditioning is provided",
            "Bedding and linen are not included",
            "Available on Mail, Express, and Superfast trains",
            "Reservation is mandatory",
        ],
        "exceptions": [
            "Not available on Rajdhani, Shatabdi, or fully AC trains",
        ],
        "source_id": "src-irctc-classes",
        "source_excerpt": "SL — Sleeper Class: Non-AC sleeping accommodation with three-tier berths.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "tc-3a",
        "topic": "ticket_class",
        "question": "What is Third AC (3A) class?",
        "answer_text": (
            "Third AC (3A) is an air-conditioned class with three-tier sleeping berths. "
            "The layout is similar to Sleeper class with 6 berths per bay plus 2 side berths, "
            "but all compartments are air-conditioned. Bedding (blanket, pillow, and bed sheet) is "
            "provided by Indian Railways. Curtains are available for privacy. "
            "3A is more affordable than 2A and 1A while offering AC comfort. "
            "It is available on most long-distance Mail, Express, Superfast, and Rajdhani trains."
        ),
        "conditions": [
            "Air-conditioned with three-tier berths",
            "Bedding and linen are provided",
            "Available on most long-distance trains",
            "Reservation is mandatory",
        ],
        "exceptions": [],
        "source_id": "src-irctc-classes",
        "source_excerpt": "3A — Third AC: Air-conditioned sleeper with three-tier berths and bedding provided.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "tc-2a",
        "topic": "ticket_class",
        "question": "What is Second AC (2A) class?",
        "answer_text": (
            "Second AC (2A) is an air-conditioned class with two-tier sleeping berths. "
            "Each bay has 4 berths: 2 lower and 2 upper, plus 2 side berths. "
            "It offers more space and privacy than 3A, with thick curtains separating each bay. "
            "Bedding (blanket, pillow, and bed sheet) is provided. "
            "2A is a premium class available on most long-distance trains including "
            "Rajdhani, Duronto, and Superfast trains."
        ),
        "conditions": [
            "Air-conditioned with two-tier berths",
            "Bedding and linen are provided",
            "More spacious than 3A",
            "Curtains provided for privacy",
            "Reservation is mandatory",
        ],
        "exceptions": [],
        "source_id": "src-irctc-classes",
        "source_excerpt": "2A — Second AC: Air-conditioned sleeper with two-tier berths, bedding, and curtains.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "tc-1a",
        "topic": "ticket_class",
        "question": "What is First AC (1A) class?",
        "answer_text": (
            "First AC (1A) is the most premium class in Indian Railways. "
            "It features private cabins (coupes) with lockable doors, accommodating 2 or 4 passengers. "
            "It is fully air-conditioned with bedding, linen, and individual reading lights. "
            "1A offers the highest level of privacy and comfort. "
            "It is available on select long-distance trains and Rajdhani Express services."
        ),
        "conditions": [
            "Air-conditioned with private lockable cabins",
            "Bedding, linen, and individual reading lights provided",
            "Most expensive reserved class",
            "Limited availability — not on all trains",
            "Reservation is mandatory",
        ],
        "exceptions": [],
        "source_id": "src-irctc-classes",
        "source_excerpt": "1A — First AC: Premium AC class with private lockable cabins.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "tc-cc",
        "topic": "ticket_class",
        "question": "What is AC Chair Car (CC) class?",
        "answer_text": (
            "AC Chair Car (CC) is an air-conditioned seating class available on shorter-distance "
            "trains such as Shatabdi Express, Jan Shatabdi, and some Intercity trains. "
            "It provides reserved, reclining, cushioned seats arranged in rows (typically 3+2 configuration). "
            "It does not have sleeping berths. Suitable for daytime journeys."
        ),
        "conditions": [
            "Air-conditioned seating only — no sleeping berths",
            "Available on Shatabdi, Jan Shatabdi, and select day trains",
            "Reservation is mandatory",
        ],
        "exceptions": [],
        "source_id": "src-irctc-classes",
        "source_excerpt": "CC — AC Chair Car: Air-conditioned reserved seating for day travel.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "tc-3e",
        "topic": "ticket_class",
        "question": "What is Third AC Economy (3E) class?",
        "answer_text": (
            "Third AC Economy (3E) is a relatively newer class introduced on select trains. "
            "It has a layout similar to 3A but with modifications to accommodate more passengers — "
            "typically with side berths arranged in a three-tier (instead of two-tier) configuration on "
            "one side. It is air-conditioned and bedding may be provided, though policies may vary. "
            "3E is priced lower than standard 3A."
        ),
        "conditions": [
            "Air-conditioned with modified three-tier layout",
            "Available on select trains only",
            "Priced lower than 3A",
            "Reservation is mandatory",
        ],
        "exceptions": [
            "Bedding policy may vary by train — verify at the time of booking",
        ],
        "source_id": "src-irctc-classes",
        "source_excerpt": "3E — Third AC Economy: AC class with higher capacity at reduced fare.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    # === RESERVATION STATUS ===
    {
        "guidance_id": "rs-cnf",
        "topic": "reservation_status",
        "question": "What does CNF (Confirmed) status mean?",
        "answer_text": (
            "CNF (Confirmed) means that the ticket has a confirmed seat or berth allocation. "
            "The passenger has a guaranteed place on the train and can travel on the ticket. "
            "A confirmed ticket will show the specific coach number and berth/seat number on the "
            "reservation chart. The passenger can board the assigned coach and occupy the allotted berth."
        ),
        "conditions": [
            "Passenger has a guaranteed berth or seat",
            "Coach and berth number are assigned",
            "Passenger can travel on the booked train",
        ],
        "exceptions": [],
        "source_id": "src-irctc-reservation",
        "source_excerpt": "CNF/Confirmed — Ticket with confirmed seat/berth allocation.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "rs-rac",
        "topic": "reservation_status",
        "question": "What does RAC (Reservation Against Cancellation) status mean?",
        "answer_text": (
            "RAC (Reservation Against Cancellation) means the passenger has a partial reservation. "
            "RAC passengers are allowed to board the train and are typically given a shared berth "
            "(usually a side-lower berth shared between two RAC passengers as sitting accommodation). "
            "If confirmed passengers cancel their tickets, RAC tickets may get upgraded to CNF status. "
            "RAC passengers can travel on the train — they are not denied boarding."
        ),
        "conditions": [
            "Passenger is allowed to board and travel",
            "Typically assigned shared sitting accommodation (side-lower berth)",
            "May be upgraded to confirmed if cancellations occur",
            "RAC status can change up to chart preparation time",
        ],
        "exceptions": [
            "The specific sharing arrangement may vary by train type",
        ],
        "source_id": "src-irctc-reservation",
        "source_excerpt": "RAC — Reservation Against Cancellation: Passenger can board with shared berth; may be upgraded to confirmed.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "rs-wl",
        "topic": "reservation_status",
        "question": "What does WL (Waitlisted) status mean?",
        "answer_text": (
            "WL (Waitlisted) means the passenger does not currently have a confirmed seat or berth. "
            "Waitlisted passengers are placed in a queue. If passengers ahead in the queue cancel "
            "their tickets, the waitlist moves up. If a WL ticket does not move to RAC or CNF status "
            "before the final chart preparation, the ticket is automatically cancelled and the fare is "
            "refunded (for e-tickets booked through IRCTC). Waitlisted passengers whose tickets remain "
            "WL after chart preparation are generally not permitted to board the train."
        ),
        "conditions": [
            "No confirmed seat or berth — passenger is in a queue",
            "May move to RAC or CNF if cancellations occur",
            "E-tickets booked via IRCTC are auto-cancelled if still WL after chart preparation",
            "Passengers with WL status after chart preparation should not board",
        ],
        "exceptions": [
            "Counter tickets (booked at railway station) have different WL handling rules",
            "Different waitlist types exist: GNWL, RLWL, PQWL, etc., with different queue priorities",
        ],
        "source_id": "src-irctc-reservation",
        "source_excerpt": "WL — Waitlisted: No confirmed berth; auto-cancelled for e-tickets if not confirmed by chart time.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "rs-wl-types",
        "topic": "reservation_status",
        "question": "What are the different types of waitlists (GNWL, RLWL, PQWL)?",
        "answer_text": (
            "Indian Railways maintains several waitlist queues:\n\n"
            "• GNWL (General Waitlist): The main waitlist for the entire journey from originating station. "
            "This typically has the best chance of confirmation.\n\n"
            "• RLWL (Remote Location Waitlist): For passengers boarding from an intermediate station. "
            "Moves independently and generally has lower confirmation chances than GNWL.\n\n"
            "• PQWL (Pooled Quota Waitlist): For journeys between intermediate stations. "
            "Has a separate, usually smaller, quota and lower confirmation chances.\n\n"
            "The type of waitlist depends on the boarding and destination stations relative to "
            "the train's originating and terminating stations."
        ),
        "conditions": [
            "GNWL generally has the best confirmation chances",
            "RLWL and PQWL have independent, typically smaller quotas",
            "Waitlist type is determined by your boarding and destination stations",
        ],
        "exceptions": [
            "Some trains have additional quota types (ladies, defence, tatkal, etc.)",
        ],
        "source_id": "src-irctc-reservation",
        "source_excerpt": "Waitlist types include GNWL, RLWL, PQWL based on boarding/destination stations.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    # === BOOKING PROCESS ===
    {
        "guidance_id": "bp-irctc-online",
        "topic": "booking_process",
        "question": "How do I book a train ticket online through IRCTC?",
        "answer_text": (
            "To book a train ticket online through IRCTC:\n\n"
            "1. Visit the official IRCTC website (https://www.irctc.co.in) or use the IRCTC Rail Connect mobile app.\n\n"
            "2. Log in with your registered IRCTC account. If you don't have one, register first by providing your "
            "name, email, phone number, and creating a username and password.\n\n"
            "3. On the booking page, enter: From station, To station, Date of journey, Class preference, "
            "and Quota (General, Tatkal, Ladies, etc.).\n\n"
            "4. Search for available trains. Review the train options, availability status, and fares.\n\n"
            "5. Select a train and class. Click 'Book Now'.\n\n"
            "6. Enter passenger details: Name, Age, Gender, Berth preference (optional), and ID card type "
            "for the journey.\n\n"
            "7. Review the booking summary and proceed to payment.\n\n"
            "8. Complete payment through the available payment options (UPI, net banking, credit/debit card, etc.).\n\n"
            "9. Upon successful payment, you will receive an e-ticket with PNR number via email and SMS.\n\n"
            "Note: This is guidance on the official process. RailSathi does not perform actual bookings."
        ),
        "conditions": [
            "A registered IRCTC account is required",
            "A valid email and phone number are required for registration",
            "Booking opens at specific times depending on quota (e.g., Tatkal at 10:00 AM for AC, 11:00 AM for non-AC)",
            "Payment must be completed within the allotted time",
            "Maximum 6 passengers per booking (subject to rules)",
        ],
        "exceptions": [
            "Tatkal booking has specific timing and additional charges",
            "Foreign tourists may have different registration requirements",
        ],
        "source_id": "src-irctc-booking",
        "source_excerpt": "IRCTC online booking: Register → Search trains → Enter passenger details → Pay → Receive e-ticket.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "bp-counter",
        "topic": "booking_process",
        "question": "How do I book a ticket at a railway station counter?",
        "answer_text": (
            "To book a ticket at a railway station reservation counter:\n\n"
            "1. Visit the nearest railway station with a computerized reservation counter.\n\n"
            "2. Obtain a reservation form from the counter or designated forms area.\n\n"
            "3. Fill in the reservation form with: Train number/name, Date of journey, From and To stations, "
            "Class, Passenger details (name, age, gender), and contact information.\n\n"
            "4. Submit the form at the counter.\n\n"
            "5. Pay the fare in cash or through accepted payment methods.\n\n"
            "6. Collect your printed ticket with PNR number.\n\n"
            "Counter booking is subject to the reservation counter's operating hours. "
            "Some stations have separate counters for current booking and advance reservation."
        ),
        "conditions": [
            "Reservation counters have specific operating hours",
            "A filled reservation form is required",
            "Advance reservation is available up to 120 days before the journey date (subject to rules)",
            "Payment can typically be made in cash",
        ],
        "exceptions": [
            "Counter-booked tickets have different cancellation rules than e-tickets",
            "Some stations may have limited counter availability",
        ],
        "source_id": "src-irctc-booking",
        "source_excerpt": "Counter booking: Fill reservation form → Submit at counter → Pay → Collect ticket.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    # === CANCELLATION & REFUND ===
    {
        "guidance_id": "cr-general",
        "topic": "cancellation_refund",
        "question": "What are the general cancellation and refund rules for Indian Railways tickets?",
        "answer_text": (
            "General cancellation and refund rules for Indian Railways:\n\n"
            "• Confirmed tickets (CNF): Cancellation charges are deducted from the fare based on "
            "how much time before departure the cancellation is made. The remaining amount is refunded.\n\n"
            "• RAC tickets: Can be cancelled with applicable cancellation charges similar to confirmed tickets.\n\n"
            "• Waitlisted (WL) e-tickets: If still waitlisted at chart preparation, the ticket is "
            "automatically cancelled and a full refund is processed. If you cancel a WL e-ticket before "
            "chart preparation, a nominal cancellation charge may apply.\n\n"
            "• Cancellation charges typically increase as the departure time approaches.\n\n"
            "• Tatkal tickets have different (typically higher) cancellation charges and restrictions.\n\n"
            "IMPORTANT: Cancellation charges and refund amounts are subject to change by Indian Railways. "
            "Always verify the current rules on the IRCTC website or at the railway station before cancelling."
        ),
        "conditions": [
            "Cancellation charges vary based on time before departure",
            "Charges vary by class and ticket type",
            "E-ticket cancellation can be done online through IRCTC",
            "Counter-ticket cancellation must be done at a railway station counter",
            "Refund processing time may vary",
        ],
        "exceptions": [
            "Tatkal tickets have special cancellation rules with higher charges or no refund in some cases",
            "Partially confirmed group tickets have specific rules",
            "Train cancellation by railways entitles a full refund",
        ],
        "source_id": "src-irctc-refund",
        "source_excerpt": "Cancellation charges vary by time before departure, class, and ticket type. WL e-tickets are auto-refunded.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "cr-eticket",
        "topic": "cancellation_refund",
        "question": "How do I cancel an e-ticket booked through IRCTC?",
        "answer_text": (
            "To cancel an e-ticket booked through IRCTC:\n\n"
            "1. Log in to the IRCTC website (https://www.irctc.co.in) or IRCTC Rail Connect app.\n\n"
            "2. Go to 'My Transactions' or 'Booked Ticket History'.\n\n"
            "3. Find the ticket you want to cancel using the PNR number or booking date.\n\n"
            "4. Click on 'Cancel Ticket'. You can cancel individual passengers or the entire ticket.\n\n"
            "5. Confirm the cancellation.\n\n"
            "6. The refund (after deducting applicable cancellation charges) is processed to the "
            "original payment method. Refund processing time varies.\n\n"
            "Note: Online cancellation through IRCTC is available up to a certain time before departure. "
            "After that window, you may need to file a TDR (Ticket Deposit Receipt) for a refund claim."
        ),
        "conditions": [
            "Must be logged into the IRCTC account that booked the ticket",
            "Online cancellation available up to a specified time before departure",
            "Refund is processed to the original payment method",
            "Cancellation charges are deducted from the refund",
        ],
        "exceptions": [
            "After chart preparation, only specific cancellation scenarios may be eligible",
            "TDR can be filed for special cases like train cancellation or late arrival",
        ],
        "source_id": "src-irctc-refund",
        "source_excerpt": "E-ticket cancellation: Log in to IRCTC → My Transactions → Cancel Ticket → Refund to original payment method.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
    {
        "guidance_id": "cr-tatkal",
        "topic": "cancellation_refund",
        "question": "What are the cancellation rules for Tatkal tickets?",
        "answer_text": (
            "Tatkal ticket cancellation rules are generally stricter than regular tickets:\n\n"
            "• Confirmed Tatkal tickets: Refund is generally NOT provided for cancellation of "
            "confirmed Tatkal tickets by the passenger. The ticket is treated as a no-refund cancellation.\n\n"
            "• Waitlisted Tatkal e-tickets: If the ticket remains waitlisted and is auto-cancelled at "
            "chart preparation, a full refund of the fare (including Tatkal charges) is provided.\n\n"
            "• If the train is cancelled or significantly delayed by Indian Railways, Tatkal passengers "
            "may be eligible for a refund through TDR.\n\n"
            "IMPORTANT: These rules are subject to change. Verify the current Tatkal cancellation policy "
            "on the IRCTC website before booking."
        ),
        "conditions": [
            "Confirmed Tatkal tickets generally have no refund on passenger-initiated cancellation",
            "Waitlisted Tatkal e-tickets auto-cancelled at chart time get a full refund",
            "Tatkal charges are in addition to the base fare",
        ],
        "exceptions": [
            "Railway-side cancellations or significant delays may allow TDR-based refund",
            "Rules may differ between AC and non-AC Tatkal",
        ],
        "source_id": "src-irctc-refund",
        "source_excerpt": "Tatkal confirmed tickets: generally no refund on passenger cancellation. WL Tatkal: full refund if auto-cancelled.",
        "last_verified_at": "2026-01-15",
        "status": "active",
    },
]
