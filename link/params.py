"""Starting values for the link rules.

These are first settings chosen for the simulator. They are meant to be
tuned once Kestrel is tested on the air.
"""

TURNAROUND_S = 1.0  # pause between hearing a frame and transmitting the reply, in seconds
REPLY_MARGIN_S = 3.0  # extra time a station waits for a reply beyond the reply's own length
BEACON_TRIES = 5  # beacons sent without an answer before the station gives up
REPLY_SLOT_S = 49.6  # length of one reply slot after an L0 beacon: an answer at L0 (47.2 s since 0.43, when the second pattern added 4.8 s) plus a short gap
REPLY_SLOT_GAP_S = 2.4  # the gap: a reply slot is an answer at the beacon's level plus this (49.6 s at L0, 13.0 s at L2 since 0.43)
CALLUP_LEVEL = 2  # a call-up (beacon or directed call) is tried first at this level; if it brings no reply, it is sent again at L0
EXPECT_S = 300.0  # a station that just beaconed, or just called a station, accepts a directed call (from anyone after a beacon, from that station after a call) for this long, even when it does not answer calls by itself
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
OFFER_UNAVAILABLE = 4  # part-number value: "this station's operator is not available" (the one reply sent to a directed call while the operator has set the station to unavailable)
OFFER_MOVE = 3  # part-number value: "move to the working frequency given in the message-number field" (a proposal, or the same value sent back as agreement)
MOVE_STEP_HZ = 100  # a working frequency is given as an offset from the calling frequency, in steps of this many hertz (a signed 16-bit count)
MOVE_SETTLE_S = 3.0  # after a move is agreed, the proposing station waits this long for both radios to retune before it probes
MOVE_TRIES = 2  # times a move is proposed without a reply before the proposer goes to the working frequency anyway to look for its partner
MOVE_WAIT_S = 150.0  # a station that has moved and hears nothing from its partner on the working frequency for this long gives up the lock
ASKED_KEEP_S = 7200.0  # the level a station last asked this one to send at is remembered this long (two hours), and the next directed call to it starts no faster (since 0.43)
CALL_TRIES = 5  # times a directed call is sent without a reply before the calling station gives up
LONG_AFTER_CALLS = 2  # when the called station has lately been heard only in long frames, short calls given up after this many (L2, then L0), so a long call can follow sooner (since 0.41)
BROADCAST_LEVEL = 0  # the speed level a broadcast to everyone is sent at unless the operator chooses another (the slowest reaches the furthest)
BROADCAST_LIFE_HOURS = 2  # lifetime written into a broadcast frame (it is not forwarded, so the shortest value is used)
WORKING_IDLE_S = 180.0  # on a working frequency, a contact with no message traffic for this long is closed and both stations return to the calling frequency
WORKING_WARN_S = 60.0  # the operator of the station that proposed the move is warned this long before that happens
HOLD_TELL_S = 60.0  # while a transmission is held back because the frequency is in use, the operator is told this often

OFFER_NO_MAIL = 5  # part-number value in a status-3 acknowledgment: "this station does not carry mail for others" (the reply to a held or handed-on message it will not keep; the message number field names the message) (since 0.30)
MAIL_LIFE_HOURS = 62  # how long a message to a named station is kept and carried before it expires undelivered (the longest the lifetime field allows)
HOP_LIMIT = 4  # the most times a message may be passed on by stations other than its origin (the hops field counts them)
RECEIPT_LIST_H = 12  # a delivery receipt is listed in this station's mail notices for this many hours
HANDED_MOST = 3  # an origin hands each of its messages to at most this many carrying stations
PASSED_MOST = 2  # a carrying station passes each message it holds on to at most this many other carrying stations
REACH_S = 7200.0  # a station that listed another as heard in its mail notice is taken to reach it for this many seconds
BAG_MOST = 50  # the most messages for other stations this station will hold at once
BAG_PER_ORIGIN = 10  # the most of those from any one origin
NOTICE_L0_EVERY_S = 1800.0  # a mail notice goes with every beacon at the call-up level, but with an L0 beacon at most this often (it lasts 51 s at L0)
MAIL_TIDY_S = 60.0  # how often the station looks for expired mail
