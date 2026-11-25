import json
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from modbus_mqtt_gateway.config import Register, load_config


CONFIG = Path(__file__).resolve().parents[1] / "modbus_mqtt_gateway" / "demo.toml"


class GatewayTest(unittest.TestCase):
    def test_register_conversion(self):
        self.assertEqual(Register("power", "input", 2, "int16", 1, "W", "big").convert([0xFF9C]), -100)
        energy = Register("energy", "input", 3, "uint32", 0.001, "kWh", "little")
        self.assertEqual(energy.convert([0xEB68, 1]), 125.8)
        with self.assertRaisesRegex(ValueError, "unexpected register count"):
            energy.convert([1])

    def test_config_rejects_wildcard_and_register_overflow(self):
        content = CONFIG.read_text(encoding="utf-8")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.toml"
            path.write_text(content.replace("lab/meter-01", "lab/#"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "literal topic"):
                load_config(path)
            path.write_text(content.replace("address = 3", "address = 65535"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "registers.address"):
                load_config(path)

    def test_real_protocols_detect_outage_and_recover(self):
        with socket.socket() as modbus, socket.socket() as mqtt:
            modbus.bind(("127.0.0.1", 0))
            mqtt.bind(("127.0.0.1", 0))
            modbus_port = modbus.getsockname()[1]
            mqtt_port = mqtt.getsockname()[1]
        content = CONFIG.read_text(encoding="utf-8")
        content = content.replace("15020", str(modbus_port)).replace("18883", str(mqtt_port))
        content = content.replace("poll_interval = 1.0", "poll_interval = 0.4")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "test.toml"
            path.write_text(content, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "modbus_mqtt_gateway", "--config", str(path),
                 "demo", "--outage", "--duration", "14"],
                text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=27,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        messages = [
            (topic.rsplit("/", 1)[-1], json.loads(payload))
            for topic, payload in (line.split(" ", 1) for line in result.stdout.splitlines())
        ]
        status_positions = [
            (index, payload["state"]) for index, (topic, payload) in enumerate(messages) if topic == "status"
        ]
        self.assertEqual([state for _, state in status_positions], ["online", "offline", "online", "unknown"])
        first, lost, recovered, stopped = [index for index, _ in status_positions]
        self.assertTrue(all(topic == "telemetry" for topic, _ in messages[first + 1:lost]))
        self.assertGreater(lost, first + 1)
        self.assertEqual(recovered, lost + 1)
        self.assertGreater(stopped, recovered + 1)
        metrics = messages[recovered + 1][1]["metrics"]
        self.assertEqual(set(metrics), {"voltage", "current", "power", "energy"})
        self.assertEqual(metrics["voltage"]["unit"], "V")
        self.assertTrue(227.5 <= metrics["voltage"]["value"] <= 232.5)
        self.assertGreaterEqual(metrics["energy"]["value"], 125.8)


if __name__ == "__main__":
    unittest.main()
