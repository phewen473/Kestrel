"""Starting values for the link rules.

These are first settings chosen for the simulator. They are meant to be
tuned once Kestrel is tested on the air.
"""

TURNAROUND_S = 1.0  # pause between hearing a frame and transmitting the reply, in seconds
REPLY_MARGIN_S = 3.0  # extra time a station waits for a reply beyond the reply's own length
BEACON_TRIES = 5  # beacons sent without an answer before the station gives up
REPLY_SLOT_S = 42.0  # length of one reply slot after an L0 beacon: an answer at L0 (39.6 s) plus a short gap
REPLY_SLOT_GAP_S = 2.4  # the gap: a reply slot is an answer at the beacon's level plus this (42 s at L0, 11.3 s at L2)
CALLUP_LEVEL = 2  # a call-up (beacon or directed call) is tried first at this level; if it brings no reply, it is sent again at L0
HEARD_FOR_CALL_S = 600.0  # a directed call carries the caller's reading of the called station if it heard that station within this many seconds
WIDE_SLOTS = 4  # reply slots after a beacon that asks for a wide window (a plain beacon has one)
STEP_UP_CLEAN = 2  # clean frames in a row before the receiver asks for a faster level
STEP_UP_LEVELS = 2  # the most levels the receiver moves up in one step
HISTORY = 4  # recent frames the receiver looks at when it chooses the level to ask for
SNR_LOOKBACK = 3  # of those, how many recent SNR readings the weakest is taken from
MISS_LIMIT = 3  # unanswered transmissions in a row before the station starts reacquiring
MAX_RESENDS = 4  # times one frame is sent again at the receiver's request before the station starts reacquiring
REACQUIRE_TRIES = 4  # unanswered probes before the lock is given up
FINAL_TRIES = 2  # times the closing identification is sent before the station leaves anyway
LOCK_TIMEOUT_S = 300.0  # a locked station that hears nothing from its partner for this long gives up the lock
KEEPALIVE_S = 120.0  # silence, in seconds, after which the station holding the turn offers it again to keep the lock alive
IDENT_EVERY_S = 540.0  # a station identifies after this many seconds without sending its callsign (nine minutes, inside the ten-minute rule)

OFFER_REPLY = 0  # part-number value in a status-3 acknowledgment: a plain reply, nothing more expected
OFFER_TURN = 1  # part-number value: "I have nothing to send; the turn is yours" (must be answered)
OFFER_PROBE = 2  # part-number value: "are you still there?" sent while reacquiring (must be answered with a status-3 acknowledgment)
OFFER_MOVE = 3  # part-number value: "move to the working frequency given in the message-number field" (a proposal, or the same value sent back as agreement)
MOVE_STEP_HZ = 100  # a working frequency is given as an offset from the calling frequency, in steps of this many hertz (a signed 16-bit count)
MOVE_SETTLE_S = 3.0  # after a move is agreed, the proposing station waits this long for both radios to retune before it probes
MOVE_TRIES = 2  # times a move is proposed without a reply before the proposer goes to the working frequency anyway to look for its partner
MOVE_WAIT_S = 150.0  # a station that has moved and hears nothing from its partner on the working frequency for this long gives up the lock
CALL_TRIES = 5  # times a directed call is sent without a reply before the calling station gives up
BROADCAST_LEVEL = 0  # the speed level a broadcast to everyone is sent at unless the operator chooses another (the slowest reaches the furthest)
BROADCAST_LIFE_HOURS = 2  # lifetime written into a broadcast frame (it is not forwarded, so the shortest value is used)
WORKING_IDLE_S = 180.0  # on a working frequency, a contact with no message traffic for this long is closed and both stations return to the calling frequency
WORKING_WARN_S = 60.0  # the operator of the station that proposed the move is warned this long before that happens
