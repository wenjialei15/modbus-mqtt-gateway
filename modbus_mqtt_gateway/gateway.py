"""Poll one Modbus TCP device and deliver MQTT updates."""

from datetime import datetime, timezone
import json
import logging
import threading

from paho.mqtt import client as mqtt
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException


LOG = logging.getLogger(__name__)


def encode(message):
    return json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Publisher:
    def __init__(self, config):
        self.config = config
        self.topic = config.mqtt.topic_prefix
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.reconnect_delay_set(1, 5)
        self.client.max_queued_messages_set(8)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.generation = 0
        self.ready = threading.Event()
        self.client.will_set(
            f"{self.topic}/status", self.status_payload("unknown", "gateway_disconnected"),
            qos=1, retain=True,
        )

    def status_payload(self, state, reason, timestamp=None):
        return encode({
            "device": self.config.modbus.name,
            "state": state,
            "reason": reason,
            "observed_at": timestamp,
        })

    def on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure:
            LOG.warning("MQTT broker rejected the connection: %s", reason)
            return
        self.generation += 1
        self.ready.set()
        LOG.info("MQTT connected (%s:%s)", self.config.mqtt.host, self.config.mqtt.port)

    def on_disconnect(self, client, userdata, flags, reason, properties):
        self.ready.clear()
        if reason.is_failure:
            LOG.warning("MQTT disconnected: %s", reason)

    def __enter__(self):
        self.client.connect_async(self.config.mqtt.host, self.config.mqtt.port)
        self.client.loop_start()
        return self

    def __exit__(self, *exc):
        self.publish("status", self.status_payload("unknown", "gateway_stopped", utc_now()), retain=True)
        self.client.disconnect()
        self.client.loop_stop()

    def publish(self, suffix, payload, *, retain=False):
        if not self.ready.is_set():
            return False
        try:
            delivery = self.client.publish(f"{self.topic}/{suffix}", payload, qos=1, retain=retain)
            if delivery.rc == mqtt.MQTT_ERR_SUCCESS:
                delivery.wait_for_publish(timeout=0.75)
                if delivery.is_published():
                    return True
            LOG.warning("MQTT delivery unconfirmed for %s", suffix)
        except (RuntimeError, ValueError) as error:
            LOG.warning("MQTT delivery interrupted for %s: %s", suffix, error)
        return False


def read_metrics(client, config):
    if not client.connect():
        raise ConnectionError("could not connect to the Modbus endpoint")
    metrics = {}
    for register in config.registers:
        read = client.read_input_registers if register.function == "input" else client.read_holding_registers
        response = read(register.address, count=register.count, device_id=config.modbus.device_id)
        if response.isError():
            raise ModbusException(f"{register.name}: {response}")
        metrics[register.name] = {"value": register.convert(response.registers), "unit": register.unit}
    return metrics


def run_gateway(config, stop):
    target = config.modbus
    client = ModbusTcpClient(target.host, port=target.port, timeout=target.timeout, retries=0)
    previous_state = None
    last_published_status = None
    try:
        with Publisher(config) as publisher:
            while not stop.is_set():
                metrics = None
                try:
                    metrics = read_metrics(client, config)
                    state, reason = "online", None
                except (OSError, ModbusException, ValueError) as error:
                    client.close()
                    state, reason = "offline", "modbus_read_failed"
                    if state != previous_state:
                        LOG.warning("Modbus device offline (%s): %s", target.name, error)
                if state == "online" and state != previous_state:
                    LOG.info("Modbus device online (%s)", target.name)
                previous_state = state
                timestamp = utc_now()
                status_key = (state, publisher.generation)
                if status_key != last_published_status and publisher.publish(
                    "status", publisher.status_payload(state, reason, timestamp), retain=True,
                ):
                    last_published_status = status_key
                if metrics is not None:
                    publisher.publish("telemetry", encode({
                        "device": target.name, "observed_at": timestamp, "metrics": metrics,
                    }))
                stop.wait(target.poll_interval)
    finally:
        client.close()
