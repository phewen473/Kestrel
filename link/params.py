"""Starting values for the link rules.

These are first settings chosen for the simulator. They are meant to be
tuned once Kestrel is tested on the air.
"""

TURNAROUND_S = 1.0  # pause between hearing a frame and transmitting the reply, in seconds
REPLY_MARGIN_S = 3.0  # extra time a station waits for a reply beyond the reply's own length
BEACON_TRIES = 5  # beacons sent without an answer before the station gives up
STEP_UP_CLEAN = 2  # clean frames in a row before the receiver asks for a faster level
STEP_UP_LEVELS = 2  # the most levels the receiver moves up in one step
HISTORY = 4  # recent frames the receiver looks at when it chooses the level to ask for
SNR_LOOKBACK = 3  # of those, how many recent SNR readings the weakest is taken from
MISS_LIMIT = 3  # unanswered transmissions in a row before the station starts reacquiring
MAX_RESENDS = 4  # times one frame is sent again at the receiver's request before the station starts reacquiring
REACQUIRE_TRIES = 4  # unanswered probes before the lock is given up
FINAL_TRIES = 2  # times the closing identification is sent before the station leaves anyway
KEEPALIVE_S = 120.0  # silence, in seconds, after which the station holding the turn offers it again to keep the lock alive
IDENT_EVERY_S = 540.0  # a station identifies after this many seconds without sending its callsign (nine minutes, inside the ten-minute rule)

OFFER_REPLY = 0  # part-number value in a status-3 acknowledgment: a plain reply, nothing more expected
OFFER_TURN = 1  # part-number value: "I have nothing to send; the turn is yours" (must be answered)
OFFER_PROBE = 2  # part-number value: "are you still there?" sent while reacquiring (must be answered with a status-3 acknowledgment)
