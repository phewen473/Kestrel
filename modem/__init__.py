"""Kestrel modem prototype (Python reference)."""

from .frame import RxResult, body_layout, build_frame, frame_seconds, receive  # transmitter, receiver and frame facts
from .levels import FADE_INDEX_LIMIT, LEVELS, MIN_SNR_DB, MIN_SNR_FADING_DB  # the speed levels and their limits
from .plan import build_plan, is_fading, join_parts, pick_level, plan_message  # level choice, airtime limits and splitting
