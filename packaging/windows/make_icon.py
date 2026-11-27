"""Build kestrel.ico (the program, installer and window icon) from kestrel_icon.svg.

Run by hand only when the artwork changes; the build uses the committed kestrel.ico.
Needs two Python packages not used by Kestrel itself: pip install cairosvg pillow
(cairosvg also needs the Cairo library, which Linux and MSYS2 provide).

    python packaging/windows/make_icon.py
"""

import io  # in-memory files for the rendered pictures
import os  # file paths
import sys  # exit code

import cairosvg  # draws the SVG artwork as a picture  # noqa: E402
from PIL import Image  # assembles the pictures into one .ico file  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))  # this folder, packaging/windows
SOURCE = os.path.join(HERE, "kestrel_icon.svg")  # the artwork
TARGET = os.path.join(HERE, "kestrel.ico")  # the icon file the spec, the NSIS script and the panel use
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]  # every size Windows asks for (title bar, taskbar, Explorer views, Start menu, high-DPI screens)


def render(size):  # draw the artwork at one size
    """Return the artwork drawn at size x size pixels as a picture with transparency."""
    png = cairosvg.svg2png(url=SOURCE, output_width=size, output_height=size)  # Cairo draws it straight at the target size (sharper than shrinking a big picture)
    return Image.open(io.BytesIO(png)).convert("RGBA")  # read it back as a picture with an alpha channel


def main():  # build the icon
    """Draw every size and write them all into kestrel.ico."""
    pictures = [render(size) for size in SIZES]  # one picture per size, smallest first
    largest = pictures[-1]  # the 256 picture leads; Pillow writes the others beside it
    largest.save(TARGET, format="ICO", sizes=[(s, s) for s in SIZES], append_images=pictures[:-1])  # one .ico holding every size, each drawn at its own size
    print(f"wrote {TARGET}: sizes {', '.join(str(s) for s in SIZES)}")  # say what was made
    return 0  # success


if __name__ == "__main__":  # run as a program
    sys.exit(main())  # build and report
