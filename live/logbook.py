"""The station logbook: a CSV file per day, and an ADIF file of completed contacts.

Three levels of detail, chosen under Settings > Logging:

- basic:    messages sent and received, broadcasts, and the start and end
            of each contact, with who, when and on what frequency.
- advanced: adds every beacon and directed call sent, every station heard,
            and the signal readings (level, SNR, fading, frequency offset),
            the rig in use and the transmit power.
- verbose:  everything: every frame received (including those that failed
            their check) and every frame sent, the radio's meters while
            transmitting (power, ALC, SWR), the input level, and a record
            of the settings in use whenever a run starts.

The CSV files open in a spreadsheet; every file has the same columns,
and a column the chosen level does not fill is left empty. Times are UTC,
as in any amateur radio log. Completed contacts also go into an ADIF file
that logging programs can import.
"""

import csv  # the daily log files
import os  # file paths
import threading  # the working thread and the window both write
import time  # dates and times

LEVELS = ("basic", "advanced", "verbose")  # the levels of detail, least first
COLUMNS = ("utc_date", "utc_time", "station", "direction", "event", "from", "to", "text", "dial_khz",  # (continued: basic columns)
           "level", "snr_db", "fade", "offset_hz", "rig", "power_w",  # (continued: advanced columns)
           "alc", "swr", "tx_audio", "rx_input_dbfs", "detail")  # verbose columns
FIELD_LEVEL = {name: 0 for name in COLUMNS[:9]}  # the columns every level fills
FIELD_LEVEL.update({name: 1 for name in COLUMNS[9:15]})  # the columns from advanced up
FIELD_LEVEL.update({name: 2 for name in COLUMNS[15:]})  # the columns only verbose fills
EVENT_LEVEL = {"message": 0, "broadcast": 0, "contact start": 0, "contact end": 0, "telemetry": 0, "mail": 0,  # (continued: basic events)
               "beacon": 1, "call": 1, "heard": 1, "run": 1,  # (continued: advanced events)
               "frame": 2, "sent": 2, "meters": 2, "settings": 2}  # verbose events
BANDS = ((1.8, 2.0, "160m"), (3.5, 4.0, "80m"), (5.06, 5.45, "60m"), (7.0, 7.3, "40m"), (10.1, 10.15, "30m"), (14.0, 14.35, "20m"),  # (continued)
         (18.068, 18.168, "17m"), (21.0, 21.45, "15m"), (24.89, 24.99, "12m"), (28.0, 29.7, "10m"), (50.0, 54.0, "6m"), (144.0, 148.0, "2m"))  # amateur bands in MHz, with their ADIF names
AUDIO_CENTRE_HZ = 1500.0  # Kestrel's signal sits this far above the dial frequency (upper sideband)


def band_for(mhz):  # which band a frequency is in
    """Return the ADIF band name for `mhz`, or "" if it is outside the amateur bands listed."""
    for low, high, name in BANDS:  # each band
        if low <= mhz <= high:  # inside it
            return name  # its name
    return ""  # none


def adif_field(name, value):  # one ADIF field
    """Return `value` as an ADIF field <NAME:length>value, or "" when it is empty."""
    text = str(value) if value is not None else ""  # the value as text
    return f"<{name}:{len(text)}>{text} " if text else ""  # the field, with its length


class Logbook:  # the CSV and ADIF logs
    """Write log rows at the chosen level of detail, and completed contacts as ADIF records."""

    def __init__(self, folder, name="kestrel", level="basic"):  # set up the logbook
        self.folder = folder  # where the files go
        self.name = name  # the start of every file name (kestrel, or kestrel_<profile> for a second panel)
        self.level = level if level in LEVELS else "basic"  # the level of detail
        self.lock = threading.Lock()  # one writer at a time
        self.observers = []  # functions told of every event, whatever the level of detail: observer(event, when, fields) (the contact book, since 0.31R3)

    def csv_path(self, when=None):  # the day's CSV file
        """Return the path of the CSV file for the UTC day of `when` (now if None)."""
        return os.path.join(self.folder, f"{self.name}_{time.strftime('%Y-%m-%d', time.gmtime(when))}.csv")  # one file per UTC day

    def adif_path(self):  # the contacts file
        """Return the path of the ADIF file of completed contacts."""
        return os.path.join(self.folder, f"{self.name}_contacts.adi")  # one file for all contacts

    def wants(self, event):  # does the chosen level record this event?
        """Return True if events of this kind are written at the chosen level."""
        return EVENT_LEVEL.get(event, 2) <= LEVELS.index(self.level)  # unknown events only in verbose

    def write(self, event, when=None, **fields):  # add one row
        """Write one row for `event` if the chosen level records it; columns above the level are left empty. Return the row written, or None.

        Every observer is told of the event first, at any level of detail,
        with all the fields given (including any that are not columns, such
        as report_db: how the other station reported hearing this one).
        """
        when = time.time() if when is None else when  # the moment of the event
        for observer in self.observers:  # whoever wants to know (the contact book)
            try:  # an observer's fault must never stop the logbook
                observer(event, when, fields)  # tell it
            except Exception:  # anything at all
                pass  # the logbook goes on
        if not self.wants(event):  # not at this level
            return None  # nothing written
        depth = LEVELS.index(self.level)  # how many column groups to fill
        row = {name: "" for name in COLUMNS}  # an empty row
        row.update({"utc_date": time.strftime("%Y-%m-%d", time.gmtime(when)), "utc_time": time.strftime("%H:%M:%S", time.gmtime(when)), "event": event})  # when, and what
        for name, value in fields.items():  # each value given
            if name in FIELD_LEVEL and FIELD_LEVEL[name] <= depth:  # a known column that this level fills
                row[name] = "" if value is None else (f"{value:.1f}" if isinstance(value, float) else value)  # tenths are plenty for the numbers
        path = self.csv_path(when)  # the day's file
        with self.lock:  # one writer at a time
            try:  # the disk may refuse
                os.makedirs(self.folder, exist_ok=True)  # make sure the folder is there
                new = not os.path.exists(path)  # a new day's file needs its header
                with open(path, "a", newline="", encoding="utf-8") as handle:  # append
                    writer = csv.DictWriter(handle, fieldnames=COLUMNS)  # the CSV writer
                    if new:  # first row of the day
                        writer.writeheader()  # the column names
                    writer.writerow(row)  # the row
            except OSError:  # it could not be written (the file may be open in a spreadsheet that locks it)
                return None  # the window still shows what happened
        return row  # what was written

    def contact(self, record):  # add a completed contact to the ADIF file
        """Append one ADIF record. `record` has call, start, end (seconds since 1970), dial_khz and, if known, grid, my_call, my_grid, snr (heard, dB), power_w, rig, sent, received and best_level."""
        start, end = time.gmtime(record["start"]), time.gmtime(record["end"])  # the times, in UTC
        mhz = (record["dial_khz"] * 1000.0 + AUDIO_CENTRE_HZ) / 1e6  # the signal's own frequency
        text = "".join((  # the record's fields
            adif_field("CALL", record["call"]),  # the other station
            adif_field("QSO_DATE", time.strftime("%Y%m%d", start)), adif_field("TIME_ON", time.strftime("%H%M%S", start)),  # when it began
            adif_field("QSO_DATE_OFF", time.strftime("%Y%m%d", end)), adif_field("TIME_OFF", time.strftime("%H%M%S", end)),  # when it ended
            adif_field("BAND", band_for(mhz)), adif_field("FREQ", f"{mhz:.6f}"),  # where
            adif_field("MODE", "MFSK"),  # Kestrel is a multi-tone FSK mode; it has no ADIF mode name of its own
            adif_field("RST_RCVD", f"{record['snr']:+.0f}" if record.get("snr") is not None else ""),  # how the other station was heard, as an SNR in dB
            adif_field("GRIDSQUARE", record.get("grid", "")),  # where the other station is, if known
            adif_field("STATION_CALLSIGN", record.get("my_call", "")), adif_field("MY_GRIDSQUARE", record.get("my_grid", "")),  # this station
            adif_field("TX_PWR", f"{record['power_w']:.0f}" if record.get("power_w") is not None else ""),  # transmit power
            adif_field("MY_RIG", record.get("rig", "")),  # the radio
            adif_field("COMMENT", f"Kestrel (KES) signal v{record.get('signal', '')}; {record.get('sent', 0)} message(s) sent, {record.get('received', 0)} received; fastest level L{record.get('best_level', 0)}"),  # what passed
        )) + "<EOR>\n"  # end of the record
        path = self.adif_path()  # the contacts file
        with self.lock:  # one writer at a time
            try:  # the disk may refuse
                os.makedirs(self.folder, exist_ok=True)  # make sure the folder is there
                new = not os.path.exists(path)  # a new file needs its header
                with open(path, "a", encoding="utf-8") as handle:  # append
                    if new:  # first record
                        handle.write("Kestrel contact log\n" + adif_field("ADIF_VER", "3.1.4") + adif_field("PROGRAMID", "Kestrel") + "<EOH>\n")  # the header
                    handle.write(text)  # the record
            except OSError:  # it could not be written
                return None  # nothing more to do
        return text  # what was written
