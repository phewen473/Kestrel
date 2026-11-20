"""Scan a finished program folder for words that must not be in a public installer.

The installer must carry nothing that points to the computer, network or
station it was built on. This script reads every file in the folder (as
bytes, so compiled files and DLLs are checked too) and looks for each word
in plain text and in Windows' 16-bit text, ignoring case.

The words come from:
  - the build computer itself: its name, the user's name and profile folder;
  - an optional private list, one word per line, kept outside the
    repository (the build script passes packaging/cache/private_words.txt,
    which Git ignores, so the private words are never published);
  - --allow WORD=FILE: a word allowed in files whose name contains FILE
    (the originator credit in the About box and NOTICE, for example).

    python privacy_scan.py FOLDER [--words FILE] [--allow WORD=PART ...]

Exit code 0 when nothing was found, 1 when something was.
"""

import argparse  # reads the command-line options
import os  # file paths and the environment
import sys  # the exit code


def words_to_find(word_file):  # the words to look for
    """Return the list of words: the build computer's own names plus the private list."""
    words = set()  # no repeats
    for name in ("COMPUTERNAME", "USERNAME", "USERDOMAIN"):  # the computer and the user
        value = os.environ.get(name, "").strip()  # its value here
        if len(value) >= 3 and value.upper() not in ("WORKGROUP",):  # long enough to mean something, and not Windows' default group
            words.add(value)  # look for it
    profile = os.environ.get("USERPROFILE", "").strip()  # the user's profile folder
    if profile:  # known
        words.add(profile)  # look for the whole path
    if word_file and os.path.isfile(word_file):  # a private list was given
        with open(word_file, "r", encoding="utf-8") as handle:  # read it
            for line in handle:  # each line
                word = line.strip()  # the word
                if word and not word.startswith("#"):  # not blank, not a comment
                    words.add(word)  # look for it
    return sorted(words, key=str.lower)  # the list


def scan(folder, words, allowed):  # look through every file
    """Return a list of (file, word) found; `allowed` maps a lower-case word to file-name parts where it may appear."""
    patterns = []  # (word, its lower-case bytes in plain text, in 16-bit text)
    for word in words:  # each word
        low = word.lower()  # compared without case
        patterns.append((word, low.encode("utf-8"), low.encode("utf-16-le")))  # both encodings
    found = []  # what turned up
    for top, _, files in os.walk(folder):  # every folder
        for name in files:  # every file
            path = os.path.join(top, name)  # its full path
            try:  # it may be unreadable
                with open(path, "rb") as handle:  # read it as bytes
                    data = handle.read().lower()  # compared without case (only ASCII letters change)
            except OSError:  # unreadable
                continue  # skip it
            for word, plain, wide in patterns:  # each word
                if plain in data or wide in data:  # present
                    places = allowed.get(word.lower(), [])  # where it is allowed
                    if not any(part.lower() in name.lower() for part in places):  # not one of those
                        found.append((os.path.relpath(path, folder), word))  # report it
    return found  # the findings


def unpack_archives(folder, into):  # PyInstaller packs the Python code compressed inside Kestrel.exe: unpack it so it can be scanned too
    """Write every module packed inside the program's .exe files to `into`, as bytes; return how many were written (0 if PyInstaller is not available)."""
    try:  # the readers come with PyInstaller (installed in the build environment)
        from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader  # PyInstaller's own archive readers
    except ImportError:  # not available
        return 0  # nothing unpacked
    count = 0  # modules written
    for top, _, files in os.walk(folder):  # every folder
        for name in files:  # every file
            if not name.lower().endswith(".exe"):  # only programs carry packed archives
                continue  # skip it
            try:  # not every .exe is a PyInstaller program
                outer = CArchiveReader(os.path.join(top, name))  # the archive appended to the program
            except Exception:  # not one
                continue  # skip it
            for entry in list(outer.toc):  # each item in it
                try:  # an item may refuse
                    data = outer.extract(entry)  # its bytes
                except Exception:  # it did
                    continue  # skip it
                if isinstance(data, tuple):  # some versions return (flags, bytes)
                    data = data[-1]  # the bytes
                if not isinstance(data, (bytes, bytearray)):  # not bytes
                    continue  # skip it
                target = os.path.join(into, f"{count:05d}_" + "".join(c if c.isalnum() or c in "._-" else "_" for c in str(entry))[-80:])  # a safe file name
                with open(target, "wb") as handle:  # write it
                    handle.write(data)  # as is
                count += 1  # one more
                if str(entry).lower().endswith(".pyz") or entry == "PYZ.pyz" or data[:4] == b"PYZ\0":  # the compressed Python modules
                    try:  # open it
                        inner = ZlibArchiveReader(target)  # the module archive
                        for module in list(inner.toc):  # each module
                            try:  # a module may refuse
                                code = inner.extract(module, raw=True) if "raw" in ZlibArchiveReader.extract.__code__.co_varnames else inner.extract(module)  # its bytes (or code object)
                            except Exception:  # it did
                                continue  # skip it
                            if not isinstance(code, (bytes, bytearray)):  # a code object
                                import marshal  # turn it back into bytes
                                code = marshal.dumps(code)  # its marshalled form, which holds its text unchanged
                            with open(os.path.join(into, f"{count:05d}_mod_" + "".join(c if c.isalnum() else "_" for c in str(module))[-60:]), "wb") as handle:  # write it
                                handle.write(code)  # as bytes
                            count += 1  # one more
                    except Exception:  # not readable as a module archive
                        pass  # the raw bytes were still written
    return count  # how many


def main():  # the script itself
    parser = argparse.ArgumentParser(description=__doc__)  # the command-line reader
    parser.add_argument("folder", help="the finished program folder")  # what to scan
    parser.add_argument("--words", default="", help="a private word list, one per line")  # extra words
    parser.add_argument("--allow", action="append", default=[], help="WORD=PART: WORD may appear in files whose name contains PART")  # exceptions
    args = parser.parse_args()  # read them
    allowed = {}  # word -> file-name parts
    for item in args.allow:  # each exception
        word, _, part = item.partition("=")  # split it
        allowed.setdefault(word.lower(), []).append(part)  # keep it
    words = words_to_find(args.words)  # the words to look for
    words += [word for word in allowed if word not in [w.lower() for w in words]]  # allowed words are still looked for everywhere else
    found = scan(args.folder, words, allowed)  # look through the files as they are
    import tempfile  # a scratch folder for the unpacked modules
    with tempfile.TemporaryDirectory() as scratch:  # removed afterwards
        unpacked = unpack_archives(args.folder, scratch)  # unpack the Python code packed inside the program
        print(f"privacy scan: {unpacked} packed items unpacked and checked as well")  # what was done
        found += [(f"(packed in the program) {path.split('_', 1)[-1]}", word) for path, word in scan(scratch, words, {w: p + ["about", "kestrel_panel", "notice"] for w, p in allowed.items()})]  # look through them too (the credit may also sit in the panel's own module)
    print(f"privacy scan: {len(words)} words checked in every file under the program folder")  # what was done (the words themselves are not printed)
    for path, word in found:  # each finding
        print(f"  FOUND in {path}: a private word ({len(word)} characters, starting {word[:2]!r})")  # where (the word is only hinted at, so the log does not spread it)
    print("privacy scan: clean" if not found else f"privacy scan: {len(found)} finding(s)")  # the verdict
    sys.exit(1 if found else 0)  # the exit code


if __name__ == "__main__":  # only when run as a script
    main()  # go
