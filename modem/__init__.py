"""Kestrel modem prototype (Python reference)."""

from .address import bits_to_call, call_to_bits, is_group, link_id  # callsign coding and the link number
from .control import ACK_HAVE_IT, ACK_LINK, ACK_OK, ACK_RESEND, ChannelReport  # acknowledgment verdicts and the channel report

from .frame import RxResult, body_layout, build_ack, build_answer, build_beacon, build_control, build_frame, build_ident, control_layout, control_seconds, frame_seconds, receive  # transmitter, receiver and frame facts
from .levels import FADE_INDEX_LIMIT, LEVELS, MIN_SNR_DB, MIN_SNR_FADING_DB  # the speed levels and their limits
from .plan import build_plan, is_fading, join_parts, pick_level, plan_message  # level choice, airtime limits and splitting
