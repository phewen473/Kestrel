"""Kestrel modem prototype (Python reference)."""

from .frame import RxResult, body_layout, build_frame, frame_seconds, receive  # transmitter, receiver and frame facts
from .levels import LEVELS, MIN_SNR_DB  # the speed levels
from .plan import build_plan, join_parts, pick_level, plan_message  # level choice, airtime limits and splitting
