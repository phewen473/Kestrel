"""Kestrel link layer (Python reference): the rules that set up, run and close a contact between two stations."""

from .adapt import common_levels, supported_level, wanted_level  # speed adaptation rules
from .simulate import Path, describe, run_link  # the two-station simulation
from .station import Station, Transmission  # one station's link rules
