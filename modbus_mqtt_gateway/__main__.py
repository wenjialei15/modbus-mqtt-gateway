"""Command-line entry points for the gateway and the software lab."""

import argparse
import asyncio
from contextlib import contextmanager
import logging
import sys
import threading

from paho.mqtt import client as mqtt

from .config import load_config, positive
from .gateway import run_gateway
from .simulation import Meter, local_broker


LOG = logging.getLogger("modbus_mqtt_gateway")


@contextmanager
def subscriber(config):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.reconnect_delay_set(1, 5)

    def on_connect(client, userdata, flags, reason, properties):
        if reason.is_failure:
            LOG.warning("Subscriber connection rejected: %s", reason)
        else:
            client.subscribe(f"{config.topic_prefix}/#", qos=1)

    def on_message(client, userdata, message):
        print(f"{message.topic} {message.payload.decode('utf-8', errors='replace')}", flush=True)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(config.host, config.port)
    client.loop_start()
    try:
        yield
    finally:
        client.disconnect()
        client.loop_stop()


async def run_demo(config, *, outage, duration):
    meter = Meter(config.modbus)
    async with local_broker(config.mqtt):
        await meter.start()
        stop = threading.Event()
        with subscriber(config.mqtt):
            simulator = asyncio.create_task(meter.run(outage))
            gateway = asyncio.create_task(asyncio.to_thread(run_gateway, config, stop))
            try:
                finished, _ = await asyncio.wait(
                    (simulator, gateway), timeout=duration, return_when=asyncio.FIRST_COMPLETED,
                )
                for task in finished:
                    task.result()
            finally:
                stop.set()
                simulator.cancel()
                await asyncio.gather(simulator, gateway, return_exceptions=True)
                await meter.close()


async def run_simulator(config):
    meter = Meter(config.modbus)
    await meter.start()
    try:
        await meter.run()
    finally:
        await meter.close()


async def run_broker(config):
    async with local_broker(config.mqtt):
        await asyncio.Event().wait()


def duration_arg(value):
    try:
        return positive(float(value), "duration")
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description="Software-only Modbus TCP to MQTT power-meter lab.")
    parser.add_argument("--config", metavar="FILE", help="TOML settings (default: embedded demo.toml)")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run the simulator, broker, gateway and subscriber together")
    demo.add_argument("--outage", action="store_true", help="stop the Modbus listener from second 6 to 11")
    demo.add_argument("--duration", type=duration_arg, help="exit after this many seconds")
    commands.add_parser("simulator", help="run only the Modbus TCP power meter")
    commands.add_parser("broker", help="run only the local aMQTT broker")
    commands.add_parser("gateway", help="poll Modbus TCP and publish to MQTT")
    commands.add_parser("subscribe", help="print MQTT messages for the configured topic prefix")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("amqtt").setLevel(logging.ERROR)
    logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
    logging.getLogger("transitions").setLevel(logging.WARNING)
    try:
        config = load_config(args.config)
        if args.command == "demo":
            asyncio.run(run_demo(config, outage=args.outage, duration=args.duration))
        elif args.command == "simulator":
            asyncio.run(run_simulator(config))
        elif args.command == "broker":
            asyncio.run(run_broker(config))
        elif args.command == "gateway":
            run_gateway(config, threading.Event())
        else:
            with subscriber(config.mqtt):
                threading.Event().wait()
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        LOG.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
