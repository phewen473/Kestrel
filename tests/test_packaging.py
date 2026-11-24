"""The Windows build must pack every module the panel imports from beside itself in tools (since 0.37).

A 0.37 build left out tools/theme_editor.py and tools/frame_strip.py: the
packed program stopped at start with "No module named 'theme_editor'".
"""

import os  # paths
import re  # reading the import lines

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository


def test_panel_modules_beside_it_are_packed():  # every bare import of a module in tools is found by the build
    tools = os.path.join(ROOT, "tools")  # the panel's folder
    with open(os.path.join(tools, "kestrel_panel.py"), encoding="utf-8") as handle:  # the panel
        text = handle.read()  # its source
    names = set(re.findall(r"^(?:from|import) (\w+)", text, flags=re.M))  # every top-level module it imports at the start of a line
    beside = sorted(name for name in names if os.path.isfile(os.path.join(tools, name + ".py")))  # those that are files beside it
    assert beside, "expected the panel to import modules from beside itself"  # theme_editor and frame_strip at least
    with open(os.path.join(ROOT, "packaging", "windows", "kestrel.spec"), encoding="utf-8") as handle:  # the build recipe
        spec = handle.read()  # its text
    assert 'os.path.join(ROOT, "tools")' in spec.split("pathex=")[1].split("\n")[0], "the build must search tools for the panel's own modules"  # tools on the search path
    for name in beside:  # each module beside the panel
        assert f'"{name}"' in spec, f"{name} should be named in the build's hidden imports"  # named, so it is packed even if the search misses it
