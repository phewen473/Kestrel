"""Kestrel HF channel simulator."""

from .channel import CONDITIONS, SKYWAVE, NoisePool, add_pool_noise, run_channel  # the main entry points, the sky-wave conditions of our own paths, and real band noise (since 0.43)
