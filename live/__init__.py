"""Kestrel on real audio: a continuous receiver, sound-card input and output, transmitter keying, and a live station."""

from .listener import Heard, Listener, frame_samples  # the continuous receiver
from .runner import KIND, call_request, describe, plain_line, run_station, status_for  # one Station on real audio, in real time; a directed call to make when free; and its state from a log line
