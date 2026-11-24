"""Tests that a rigctld Kestrel starts cannot outlive Kestrel, and that a leftover one is ended safely (since 0.38R2)."""

import os  # paths and the data folder
import subprocess  # the stand-in processes
import sys  # the Python running the tests
import tempfile  # a scratch data folder
import textwrap  # the stand-in Kestrel's script
import time  # waiting
import unittest  # the test runner
from unittest import mock  # pointing the pid file at the scratch folder

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # the repository root

from live import rig  # what is tested  # noqa: E402


def running(pid):  # is a process still there?
    """Return True if process `pid` is running."""
    return rig._image_name(pid) != ""  # it has a name while it runs


@unittest.skipUnless(sys.platform == "win32", "the job object is Windows only")  # Windows
class JobObjectTest(unittest.TestCase):  # a crash of Kestrel takes its rigctld with it
    def test_child_ends_when_parent_is_killed(self):  # the crash case
        script = textwrap.dedent(f"""
            import subprocess, sys, time  # a stand-in Kestrel
            sys.path.insert(0, {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))!r})  # the repository
            from live import rig  # the code under test
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # a stand-in rigctld
            print(child.pid, rig._tie_to_kestrel(child), flush=True)  # its number, and whether it was tied
            time.sleep(60)  # wait to be killed
        """)  # the stand-in Kestrel
        parent = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)  # start it
        pid, tied = parent.stdout.readline().split()  # the child's number and whether it was tied
        self.assertEqual(tied, "True")  # tied to the job
        self.assertTrue(running(int(pid)))  # running now
        subprocess.run(["taskkill", "/PID", str(parent.pid), "/F"], capture_output=True)  # Kestrel "crashes" (killed outright, no clean-up)
        parent.wait(timeout=10)  # gone
        for _ in range(50):  # give Windows a moment
            if not running(int(pid)):  # the child went with it
                break  # done
            time.sleep(0.1)  # wait
        self.assertFalse(running(int(pid)))  # the stand-in rigctld did not outlive Kestrel


class LeftoverTest(unittest.TestCase):  # the note of last time's rigctld
    def test_other_program_left_alone(self):  # a process number reused by another program
        with tempfile.TemporaryDirectory() as folder:  # scratch data folder
            note = os.path.join(folder, "_rigctld.pid")  # the note
            other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])  # not a rigctld
            try:  # always tidy up
                with open(note, "w", encoding="utf-8") as handle:  # the note names it
                    handle.write(f"{other.pid}\n")  # its number
                with mock.patch.object(rig, "_pid_file", return_value=note):  # look at the scratch note
                    self.assertEqual(rig.end_leftover(), "")  # nothing ended
                self.assertIsNone(other.poll())  # still running
                self.assertFalse(os.path.exists(note))  # and the stale note is gone
            finally:  # tidy up
                other.kill()  # the stand-in goes

    def test_no_note(self):  # the usual case
        with tempfile.TemporaryDirectory() as folder:  # scratch data folder
            with mock.patch.object(rig, "_pid_file", return_value=os.path.join(folder, "_rigctld.pid")):  # no note there
                self.assertEqual(rig.end_leftover(), "")  # nothing to do

    def test_holders_on_another_port_left_alone(self):  # no rigctld for a made-up port
        self.assertEqual(rig.end_kestrel_holders("COM99"), "")  # nothing ended


if __name__ == "__main__":  # run directly
    unittest.main()  # the tests
