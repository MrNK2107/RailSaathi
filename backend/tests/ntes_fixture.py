"""NTES responses for tests, trimmed from shapes observed live on 2026-10-17 (scripts/ntes_smoke.py), plus a fake
synchronous client with the same method names as `ntes.NTESClient`. No network."""

import copy


class NTESError(Exception):
    """Same class name as ntes.exceptions.NTESError (the gateway maps errors by name and message)."""


class NTESCryptoError(Exception):
    pass


def between(no, name, frm, to, dep, travel, days="Daily", classes="1A,2A,3A,SL,GEN,PWD", arr="00:00"):
    return {"TrainNumber": no, "TrainName": name, "FromStation": frm, "FromStationName": f"{frm} NTES NAME",
            "toStation": to, "ToStationName": f"{to} NTES NAME", "DepTimeFrom": dep, "ArrTimeTo": arr,
            "TravelTime": travel, "DayOfRun": days, "ClassOfTravel": classes, "TrainType": "SUF",
            "Source": frm, "Destination": to}


# Sunday 11 Oct 2026 is the search date in the tests.
MAS_SBC = {
    "StationFromCode": "MAS", "StationToCode": "SBC", "TotalTrains": 6, "AlertMsg": "", "TrainType": "XXX",
    "Trains": [
        between("20607", "MYS VANDE BHARAT", "MAS", "SBC", "05:50", "04:10", "Mon,tue,thu,fri,sat,sun", "CC"),
        between("12007", "MAS MYS SHATABDI", "MAS", "SBC", "06:00", "04:30", "Mon,tue,wed,fri,sat,sun", "EC,CC"),
        between("12657", "MAS SBC SF MAIL", "MAS", "SBC", "22:50", "05:45", "Daily", "1A,2A,3A,SL,GEN,PWD", "04:35"),
        between("22601", "MAS SNSI SF EXP", "MAS", "YNK", "10:25", "06:06", "Wed"),  # YNK: not a Bengaluru station
        between("15228", "MFP SMVB EXP", "PER", "SMVB", "03:05", "06:40", "Sun"),  # PER: not a Chennai station
        between("12292", "MAS YPR SF EXP", "MAS", "YPR", "23:30", "06:30", "Sat"),  # does not run on Sundays
    ],
}

SCHEDULE_12658 = {
    "TrainNumber": "12658", "TrainName": "SBC MAS SF MAIL", "Source": "SBC", "Destination": "MAS",
    "TravelTime": "05:25", "DaysOfRun": "Daily", "AlertMsg": "",
    "stations": [
        {"StationName": "KSR BENGALURU", "STA": "", "STD": "22:40", "StationCode": "SBC", "Day": 1, "Sr": 1},
        {"StationName": "BANGALORE CANT", "STA": "22:50", "STD": "22:51", "StationCode": "BNC", "Day": 1, "Sr": 2},
        {"StationName": "KATPADI JN", "STA": "01:58", "STD": "02:00", "StationCode": "KPD", "Day": 2, "Sr": 5},
        {"StationName": "PERAMBUR", "STA": "03:28", "STD": "03:30", "StationCode": "PER", "Day": 2, "Sr": 7},
        {"StationName": "PURATCHI THALAIVAR DR. MGR CTL", "STA": "04:05", "STD": "", "StationCode": "MAS",
         "Day": 2, "Sr": 8},
    ],
}


def board_row(no, name, std, dest, dest_name, delay="RT", cancel=0, sta="SRC"):
    return {"TrainNumber": no, "TrainName": name, "STA": sta, "STD": std, "ETD": std.split(" ")[0],
            "DelayDep": delay, "DelayArr": "RT", "Cancel": cancel, "DepCancelFlag": 0, "Destination": dest,
            "DestinationName": dest_name, "Source": "MAS", "Platform": "5", "StartDate": "17-Oct-2026"}


# MAS board fetched at 02:50 IST on Saturday 17 Oct 2026.
MAS_BOARD = {
    "Station": "MAS", "StationName": "PURATCHI THALAIVAR DR. MGR CTL CHENNAI", "NextHr": "4", "AlertMsg": "",
    "TrainsAtStation": [
        # Scheduled 23:10 yesterday, 3 h 47 min late: still to leave at 02:57, so it is on the board.
        board_row("12511", "RAPTISAGAR EXP", "23:10 16-Oct", "TVCN", "THIRUVANANTHAPURAM NORTH", "03:47",
                  sta="22:40 16-Oct"),
        board_row("22652", "PGT MAS EXPRESS", "DSTN", "MAS", "PURATCHI THALAIVAR DR. MGR CTL CHENNAI",
                  sta="03:45 17-Oct"),  # ends here: not a departure
        board_row("20607", "MYS VANDE BHARAT", "05:50 17-Oct", "MYS", "MYSURU JN"),
        board_row("12007", "MAS MYS SHATABDI", "06:00 17-Oct", "MYS", "MYSURU JN", cancel=1),
        board_row("12675", "KOVAI EXPRESS", "06:10 17-Oct", "CBE", "COIMBATORE JN", "00:15"),
        board_row("12639", "BRINDAVAN SF EXP", "07:40 17-Oct", "SBC", "KSR BENGALURU"),  # after a 4 h window
    ],
}

LIVE_12658 = {
    "TN": "12658", "TNM": "SBC MAS SF MAIL", "SRC": "SBC", "DSTN": "MAS", "STD": "16-Oct-2026", "AlertMsg": "",
    "CPOS": "Departed from MAHENDRAVADI(MDVE) at 02:37 17-Oct", "LDEL": "3", "TRUNST": 1,
    "LUPDFULL": "Departed from Mahendravadi at 17-Oct-2026 02:37. Next stoppage station is Arakkonam Jn.",
    "STNS": [{"SC": "SBC", "STD": "22:40 16-Oct", "ETD": "22:47 16-Oct", "DDEP": "00:07"}],
}

LIVE_LATE = {**LIVE_12658, "TN": "12657", "LDEL": "25"}


class FakeNTES:
    """Stands in for ntes.NTESClient. `responses` maps a call name to a value, a callable(*args) or an exception
    (raised). Every call is recorded in `calls`. pnr_status must never be called."""

    def __init__(self, responses: dict | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple] = []

    def _answer(self, name, *args):
        self.calls.append((name, *args))
        value = self.responses.get(name)
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            value = value(*args)
            if isinstance(value, BaseException):
                raise value
        if value is None:
            raise NTESError("request failed: No Data Found !!!")
        return copy.deepcopy(value)

    def trains_between(self, from_station, to_station, train_type="XXX"):
        return self._answer("trains_between", from_station, to_station, train_type)

    def schedule(self, train_no, start_date=""):
        return self._answer("schedule", train_no)

    def station_live(self, station_code, hours=2):
        return self._answer("station_live", station_code, hours)

    def live_status(self, train_no, start_date):
        return self._answer("live_status", train_no, start_date)

    def pnr_status(self, pnr):  # pragma: no cover - the test fails if this is ever reached
        raise AssertionError("pnr_status must never be called")
