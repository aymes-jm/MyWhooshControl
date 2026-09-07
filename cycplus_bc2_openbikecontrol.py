#!/usr/bin/env python3
"""Bridge the CYCPLUS BC2 BLE buttons to an OpenBikeControl device."""

from __future__ import annotations

import argparse
import asyncio
import socket
import threading
import uuid
from contextlib import closing
from typing import Optional

from bleak import BleakClient, BleakScanner
from zeroconf import ServiceInfo, Zeroconf


SERVICE_TYPE = "_openbikecontrol._tcp.local."
SERVICE_UUID = "d273f680-d548-419d-b9d1-fa0472345229"
SHIFT_UP = bytes((0x01, 0x01, 0x01))
SHIFT_DOWN = bytes((0x01, 0x02, 0x01))
DEFAULT_DEVICE_NAME = "CYCPLUS BC2"
DEFAULT_UP_CODE = 0x01
DEFAULT_DOWN_CODE = 0x01
NORDIC_UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


def local_address() -> str:
    """Find the LAN address that other applications can use."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class OpenBikeControlDevice:
    """Serve one OpenBikeControl TCP client and send button state frames."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.ready = threading.Event()
        self._client: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def serve(self, stop: threading.Event) -> None:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(1)
            server.settimeout(0.5)
            self.port = server.getsockname()[1]
            self.ready.set()
            print(f"OpenBikeControl device listening on {self.host}:{self.port}")
            while not stop.is_set():
                try:
                    client, address = server.accept()
                except socket.timeout:
                    continue
                print(f"Application connected from {address[0]}:{address[1]}")
                with self._lock:
                    old_client = self._client
                    self._client = client
                if old_client is not None:
                    old_client.close()
                try:
                    while not stop.is_set() and client.recv(1):
                        pass
                except OSError:
                    pass
                finally:
                    with self._lock:
                        if self._client is client:
                            self._client = None
                    client.close()
                    print("Application disconnected.")

    def send_button(self, button_id: int, state: int = 1) -> bool:
        payload = bytes((0x01, button_id, state))
        with self._lock:
            if self._client is None:
                return False
            try:
                self._client.sendall(payload)
            except OSError:
                self._client = None
                return False
        return True

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None


def parse_code(value: str) -> int:
    """Parse a hexadecimal or decimal HID usage code."""
    code = int(value, 0)
    if not 0 <= code <= 0xFF:
        raise argparse.ArgumentTypeError("le code doit être compris entre 0 et 255")
    return code


def button_states(data: bytes, up_code: int, down_code: int) -> tuple[bool, bool]:
    """Return button states from the BC2 UART button fields."""
    if len(data) <= 7:
        return False, False
    return data[6] == up_code, data[7] == down_code


def select_notify_characteristic(
    characteristics: list[str], requested: Optional[str] = None
) -> str:
    """Prefer the Nordic UART TX characteristic when no UUID is specified."""
    if requested:
        selected = requested.lower()
        if selected not in {item.lower() for item in characteristics}:
            raise RuntimeError(
                f"La caractéristique {requested} n'accepte pas les notifications."
            )
        return selected
    for item in characteristics:
        if item.lower() == NORDIC_UART_TX:
            return item
    if not characteristics:
        raise RuntimeError("Aucune caractéristique BLE notificatrice trouvée.")
    return characteristics[0]


def notify_handler(
    device: OpenBikeControlDevice,
    up_code: int,
    down_code: int,
    previous: list[tuple[bool, bool]],
    debug_reports: bool = False,
):
    """Create a BLE notification callback that emits press and release edges."""

    def handle(sender: object, data: bytearray) -> None:
        if debug_reports:
            print(f"Rapport BLE [{sender}]: {bytes(data).hex(' ')}")
        current = button_states(bytes(data), up_code, down_code)
        old = previous[0]
        for index, (was_pressed, is_pressed) in enumerate(zip(old, current), start=1):
            if not is_pressed and not was_pressed:
                continue
            states = (0, 1) if is_pressed else (0,)
            for state in states:
                if device.send_button(index, state):
                    action = "appui" if state else "relâchement"
                    print(f"Bouton OBC {index}: {action} ({bytes(data).hex(' ')})")
                else:
                    print("Aucune application OpenBikeControl connectée.")
        previous[0] = current

    return handle


async def find_device(name: str):
    """Find a BLE device whose name contains the requested text."""
    device = await BleakScanner.find_device_by_filter(
        lambda candidate, _: name.lower() in (candidate.name or "").lower()
    )
    if device is None:
        raise RuntimeError(f"Périphérique BLE introuvable: {name}")
    return device


async def run_ble(
    device: OpenBikeControlDevice,
    name: str,
    characteristic: Optional[str],
    up_code: int,
    down_code: int,
    debug_reports: bool,
    stop: threading.Event,
) -> None:
    ble_device = await find_device(name)
    print(f"Connexion BLE à {ble_device.name or name} ({ble_device.address})...")
    async with BleakClient(ble_device) as client:
        notify_characteristics = [
            item.uuid
            for service in client.services
            for item in service.characteristics
            if "notify" in item.properties
        ]
        selected = select_notify_characteristic(notify_characteristics, characteristic)
        previous: list[tuple[bool, bool]] = [(False, False)]
        subscribed: list[str] = []
        if debug_reports and not characteristic:
            print("Caractéristiques BLE notificatrices:")
            for notify_characteristic in notify_characteristics:
                print(f"- {notify_characteristic}")
                await client.start_notify(
                    notify_characteristic,
                    notify_handler(
                        device, up_code, down_code, previous, debug_reports
                    ),
                )
                subscribed.append(notify_characteristic)
        else:
            print(f"Notifications BLE sur {selected}")
            await client.start_notify(
                selected, notify_handler(device, up_code, down_code, previous, debug_reports)
            )
            subscribed.append(selected)
        try:
            while not stop.wait(0.5):
                await asyncio.sleep(0)
        finally:
            for notify_characteristic in subscribed:
                await client.stop_notify(notify_characteristic)


def run(args: argparse.Namespace) -> None:
    stop = threading.Event()
    device = OpenBikeControlDevice(args.host, args.port)
    server_thread = threading.Thread(target=device.serve, args=(stop,), daemon=True)
    server_thread.start()
    if not device.ready.wait(5):
        raise RuntimeError("Le serveur OpenBikeControl n'a pas pu démarrer.")

    advertised_host = args.advertise_host or local_address()
    service_name = f"{args.name}.{SERVICE_TYPE}"
    service = ServiceInfo(
        SERVICE_TYPE,
        service_name,
        addresses=[socket.inet_aton(advertised_host)],
        port=device.port,
        properties={
            b"version": b"1",
            b"id": uuid.uuid4().hex[:12].encode(),
            b"name": args.name.encode(),
            b"service-uuids": SERVICE_UUID.encode(),
            b"manufacturer": b"CYCPLUS",
            b"model": b"BC2 BLE buttons",
        },
    )
    zeroconf = Zeroconf()
    zeroconf.register_service(service)
    print(f"Advertised as {service_name} at {advertised_host}:{device.port}")
    print(f"Codes HID: + = 0x{args.up_code:02x}, - = 0x{args.down_code:02x}")
    try:
        asyncio.run(
            run_ble(
                device,
                args.device,
                args.characteristic,
                args.up_code,
                args.down_code,
                args.debug_reports,
                stop,
            )
        )
    except KeyboardInterrupt:
        stop.set()
    finally:
        stop.set()
        device.close()
        zeroconf.unregister_service(service)
        zeroconf.close()
        server_thread.join(timeout=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Relie les boutons BLE du CYCPLUS BC2 à OpenBikeControl."
    )
    parser.add_argument("--device", default=DEFAULT_DEVICE_NAME, help="Nom BLE à rechercher.")
    parser.add_argument(
        "--characteristic",
        help="UUID de la caractéristique notificatrice (par défaut: première trouvée).",
    )
    parser.add_argument("--up-code", type=parse_code, default=DEFAULT_UP_CODE)
    parser.add_argument("--down-code", type=parse_code, default=DEFAULT_DOWN_CODE)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--advertise-host", help="Adresse annoncée par mDNS.")
    parser.add_argument("--port", type=int, default=0, help="0 choisit un port libre.")
    parser.add_argument("--name", default="CYCPLUS BC2 OpenBikeControl")
    parser.add_argument(
        "--debug-reports",
        action="store_true",
        help="affiche chaque rapport BLE reçu pour identifier les codes des boutons",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())