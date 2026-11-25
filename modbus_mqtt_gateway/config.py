"""Read and validate gateway settings."""

from dataclasses import dataclass
from importlib.resources import files
import math
from pathlib import Path
import tomllib


WORD_COUNTS = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2}


@dataclass(frozen=True)
class Register:
    name: str
    function: str
    address: int
    kind: str
    scale: float
    unit: str
    word_order: str

    @property
    def count(self):
        return WORD_COUNTS[self.kind]

    def convert(self, words):
        if len(words) != self.count:
            raise ValueError(f"{self.name}: unexpected register count")
        if self.word_order == "little":
            words = list(reversed(words))
        raw = int.from_bytes(
            b"".join(word.to_bytes(2, "big") for word in words),
            byteorder="big",
            signed=self.kind.startswith("int"),
        )
        value = round(raw * self.scale, 9)
        if not math.isfinite(value):
            raise ValueError(f"{self.name}: scaled value is out of range")
        return value


@dataclass(frozen=True)
class Modbus:
    host: str
    port: int
    device_id: int
    timeout: float
    poll_interval: float
    name: str


@dataclass(frozen=True)
class Mqtt:
    host: str
    port: int
    topic_prefix: str


@dataclass(frozen=True)
class Config:
    modbus: Modbus
    mqtt: Mqtt
    registers: tuple[Register, ...]


def text_field(value, key):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{key} must be a non-empty string without surrounding whitespace")
    return value


def integer(value, key, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be an integer between {minimum} and {maximum}")
    return value


def number(value, key):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number")
    return float(value)


def positive(value, key):
    value = number(value, key)
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def parse_register(entry):
    kind = text_field(entry["type"], "registers.type")
    if kind not in WORD_COUNTS:
        raise ValueError(f"unsupported register type: {kind}")
    function = text_field(entry["function"], "registers.function")
    if function not in ("input", "holding"):
        raise ValueError("registers.function must be input or holding")
    order = text_field(entry.get("word_order", "big"), "registers.word_order")
    if order not in ("big", "little"):
        raise ValueError("registers.word_order must be big or little")
    return Register(
        text_field(entry["name"], "registers.name"),
        function,
        integer(entry["address"], "registers.address", 0, 65536 - WORD_COUNTS[kind]),
        kind,
        number(entry.get("scale", 1), "registers.scale"),
        text_field(entry["unit"], "registers.unit"),
        order,
    )


def load_config(path=None):
    source = Path(path) if path is not None else files(__package__).joinpath("demo.toml")
    with source.open("rb") as stream:
        raw = tomllib.load(stream)
    try:
        modbus = raw["modbus"]
        mqtt = raw["mqtt"]
        prefix = text_field(mqtt["topic_prefix"], "mqtt.topic_prefix")
        if any(char in prefix for char in ("#", "+", "\0")) or not all(prefix.split("/")):
            raise ValueError("mqtt.topic_prefix must contain non-empty literal topic levels")
        registers = tuple(parse_register(entry) for entry in raw["registers"])
        if not registers or len({item.name for item in registers}) != len(registers):
            raise ValueError("registers must be non-empty and have unique names")
        return Config(
            Modbus(
                text_field(modbus["host"], "modbus.host"),
                integer(modbus["port"], "modbus.port", 1, 65535),
                integer(modbus["device_id"], "modbus.device_id", 1, 247),
                positive(modbus.get("timeout", 0.75), "modbus.timeout"),
                positive(modbus.get("poll_interval", 1), "modbus.poll_interval"),
                text_field(modbus["name"], "modbus.name"),
            ),
            Mqtt(
                text_field(mqtt["host"], "mqtt.host"),
                integer(mqtt["port"], "mqtt.port", 1, 65535),
                prefix,
            ),
            registers,
        )
    except (KeyError, TypeError) as error:
        raise ValueError(f"invalid gateway configuration: {error}") from error
