"""Antenna types (since 0.39R2): the fixed list offered in Settings > Station and in contact records.

The operator picks this station's antenna from the list below; it cannot be
added to or changed. A homemade antenna is "Homebuilt", and anything else
"Other". After a completed contact the station sends its antenna to the
other station (an "ANT" message), which fills in that station's record.
"""

TYPES = (  # the common HF antennas, roughly from simplest to largest; fixed (not editable by the operator)
    "Dipole", "Inverted V", "NVIS dipole (low)", "Fan dipole (multiband)", "Off-center-fed dipole (OCF)", "G5RV", "Doublet with ladder line",  # (continued: dipoles)
    "End-fed half-wave (EFHW)", "End-fed random wire", "Long wire", "Vertical (ground-mounted)", "Vertical with elevated radials",  # (continued: end-fed and verticals)
    "Mobile whip", "Screwdriver antenna", "Magnetic loop", "Horizontal loop (skyloop)", "Delta loop", "Hexbeam",  # (continued: mobile, loops and small beams)
    "Yagi", "Moxon", "Indoor / stealth antenna", "Homebuilt", "Other",  # (continued: beams, homemade and the rest)
)  # the list
NONE = ""  # no antenna chosen yet


def known(name):  # one of the list?
    """Return `name` if it is one of TYPES (capitals ignored, given back as the list writes it), else ""."""
    wanted = " ".join(str(name or "").split()).lower()  # tidied, in small letters
    return next((kind for kind in TYPES if kind.lower() == wanted), NONE)  # the list's own spelling, or nothing
