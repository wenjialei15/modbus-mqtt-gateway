"""Software power meter and local MQTT broker for the lab."""

import asyncio
from contextlib import asynccontextmanager
import logging
import math
import time

from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import ModbusTcpServer


LOG = logging.getLogger(__name__)


def loopback(host):
    if host != "127.0.0.1":
        raise ValueError("demo services must bind to 127.0.0.1")


def meter_words(elapsed):
    voltage = round(2300 + 24 * math.sin(elapsed / 4))
    current = round(440 + 125 * math.sin(elapsed / 6))
    power = round(voltage * current * 0.001 * 0.94)
    energy = 125_800 + int(max(elapsed, 0) / 3.6)
    return [voltage, current, power, (energy >> 16) & 0xFFFF, energy & 0xFFFF]


class Meter:
    def __init__(self, config):
        loopback(config.host)
        self.config = config
        self.started = time.monotonic()
        self.device = ModbusDeviceContext(ir=ModbusSequentialDataBlock(1, meter_words(0)))
        self.server = None

    async def start(self):
        self.device.setValues(4, 0, meter_words(time.monotonic() - self.started))
        context = ModbusServerContext(devices={self.config.device_id: self.device}, single=False)
        server = ModbusTcpServer(context, address=(self.config.host, self.config.port))
        await server.serve_forever(background=True)
        self.server = server
        LOG.info("Simulator listening on %s:%s", self.config.host, self.config.port)

    async def close(self):
        if self.server is not None:
            await self.server.shutdown()
            self.server = None

    async def run(self, outage=False):
        started = time.monotonic()
        while True:
            elapsed = time.monotonic() - started
            if outage and 6 <= elapsed < 11:
                if self.server is not None:
                    LOG.info("Demo fault: stopping the Modbus TCP listener for 5 seconds")
                    await self.close()
            else:
                if self.server is None:
                    await self.start()
                self.device.setValues(4, 0, meter_words(time.monotonic() - self.started))
            await asyncio.sleep(0.25)


@asynccontextmanager
async def local_broker(config):
    loopback(config.host)
    try:
        from amqtt.broker import Broker
    except ImportError as error:
        raise ValueError('install the demo dependencies with python -m pip install ".[demo]"') from error
    broker = Broker({
        "listeners": {"default": {"type": "tcp", "bind": f"{config.host}:{config.port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    })
    await broker.start()
    LOG.info("MQTT broker listening on %s:%s", config.host, config.port)
    try:
        yield
    finally:
        await broker.shutdown()
