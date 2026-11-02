"""Run with: python3 -m unittest tests.test_find_monitor"""

import os
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "deploy", "find-monitor")


def record(serial, protocol="IPv4", address="192.168.50.94"):
    host = "airgradient_{}".format(serial)
    return (
        '=;wlan0;{};{};_airgradient._tcp;local;{}.local;{};80;'
        '"model=I-9PSL" "serialno={}" "fw_ver=3.7.0" "vendor=AirGradient"'
    ).format(protocol, host, host, address, serial)


class FindMonitorTests(unittest.TestCase):
    def run_script(self, answers, stdin=""):
        """`answers` are avahi-browse outputs, one per call; the last one repeats."""
        with tempfile.TemporaryDirectory() as stubs:
            for index, answer in enumerate(answers):
                with open(os.path.join(stubs, "answer{}".format(index)), "w") as handle:
                    handle.write(answer)
            self.write_stub(
                stubs,
                "avahi-browse",
                'n=$(cat "$0.calls" 2>/dev/null || echo 0)\n'
                'echo $((n + 1)) > "$0.calls"\n'
                '[ "$n" -lt {last} ] || n={last}\n'
                'cat "$(dirname "$0")/answer$n"\n'.format(last=len(answers) - 1),
            )
            self.write_stub(stubs, "sleep", "exit 0\n")
            env = dict(os.environ, PATH=stubs + os.pathsep + os.environ["PATH"])
            done = subprocess.run(
                ["bash", SCRIPT],
                input=stdin,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
            return done

    def write_stub(self, folder, name, body):
        path = os.path.join(folder, name)
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\n" + body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def test_one_monitor_is_used(self):
        done = self.run_script(["+;wlan0;IPv4;x;_airgradient._tcp;local\n" + record("aa") + "\n"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "airgradient_aa.local\n")

    def test_the_same_monitor_on_two_protocols_is_one_monitor(self):
        answer = record("aa") + "\n" + record("aa", "IPv6", "fe80::1") + "\n"
        done = self.run_script([answer])
        self.assertEqual(done.stdout, "airgradient_aa.local\n")

    def test_a_slow_answer_is_waited_for(self):
        done = self.run_script(["", "", record("aa") + "\n"])
        self.assertEqual(done.stdout, "airgradient_aa.local\n")

    def test_none_found_fails_and_says_how_to_recover(self):
        done = self.run_script([""])
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertIn("pass the monitor's address", done.stderr)

    def test_several_ask_which(self):
        done = self.run_script([record("aa") + "\n" + record("bb") + "\n"], stdin="2\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "airgradient_bb.local\n")
        self.assertIn("airgradient_aa.local", done.stderr)

    def test_a_bad_choice_asks_again(self):
        done = self.run_script([record("aa") + "\n" + record("bb") + "\n"], stdin="9\n1\n")
        self.assertEqual(done.stdout, "airgradient_aa.local\n")

    def test_several_with_nobody_to_ask_fails(self):
        done = self.run_script([record("aa") + "\n" + record("bb") + "\n"])
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout.strip(), "")  # select prints a newline at end of input.


if __name__ == "__main__":
    unittest.main()
