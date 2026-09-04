#!/usr/bin/env python3
"""Emulate MyWhoosh as an OpenBikeControl TCP application."""

from __future__ import annotations

import argparse
import socket
import threading
from contextlib import closing
from typing import Optional

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf


SERVICE_TYPE = "_openbikecontrol._tcp.local."
BUTTON_STATE = 0x01
SHIFT_NAMES = {0x01: "Shift Up (+)", 0x02: "Shift Down (-)"}


class DeviceListener(ServiceListener):
    def __init__(self, zeroconf: Zeroconf, wanted_name: Optional[str]) -> None:
        self.zeroconf = zeroconf
        self.wanted_name = wanted_name
        self.result: Optional[tuple[str, int, str]] = None
        self.found = threading.Event()

    def add_service(self, _: Zeroconf, __: str, name: str) -> None:
        self._check(name)

    def update_service(self, _: Zeroconf, __: str, name: str) -> None:
        self._check(name)

    def remove_service(self, _: Zeroconf, __: str, ___: str) -> None:
        return

    def _check(self, name: str) -> None:
        if self.result is not None:
            return
        if self.wanted_name and not name.startswith(self.wanted_name + "."):
            return
        info = self.zeroconf.get_service_info(SERVICE_TYPE, name)
        if info is None or not info.parsed_addresses():
            return
        self.result = (info.parsed_addresses()[0], info.port, name)
        self.found.set()


def discover_device(name: Optional[str], timeout: float) -> tuple[str, int, str]:
    """Discover an OpenBikeControl device through mDNS."""
    zeroconf = Zeroconf()
    listener = DeviceListener(zeroconf, name)
    browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)
    try:
        if not listener.found.wait(timeout):
            raise TimeoutError("Aucun périphérique OpenBikeControl trouvé.")
        assert listener.result is not None
        return listener.result
    finally:
        browser.cancel()
        zeroconf.close()


def decode_button_state(data: bytes) -> list[tuple[int, int]]:
    """Decode a complete OBC button-state frame."""
    if len(data) < 3 or data[0] != BUTTON_STATE or len(data[1:]) % 2:
        raise ValueError("trame Button State OpenBikeControl invalide")
    return list(zip(data[1::2], data[2::2]))


def send_app_info(client: socket.socket) -> None:
    """Announce the two virtual-shifting actions supported by this app."""
    app_id = b"mywhoosh-emulator"
    version = b"1.0.0"
    payload = bytes((0x04, 0x01, len(app_id))) + app_id
    payload += bytes((len(version),)) + version + bytes((2, 0x01, 0x02))
    client.sendall(payload)


def run(args: argparse.Namespace) -> None:
    if args.host:
        host, port, service_name = args.host, args.port, "direct"
    else:
        host, port, service_name = discover_device(args.name, args.timeout)
    print(f"Connexion à {service_name} ({host}:{port})...")
    with closing(socket.create_connection((host, port), timeout=args.timeout)) as client:
        client.settimeout(None)
        send_app_info(client)
        print("Connecté. Réception des commandes OpenBikeControl...")
        buffer = b""
        while True:
            data = client.recv(4096)
            if not data:
                print("Le périphérique a fermé la connexion.")
                return
            buffer += data
            while len(buffer) >= 3:
                if buffer[0] != BUTTON_STATE:
                    raise ValueError(f"Type de message inattendu: 0x{buffer[0]:02x}")
                frame, buffer = buffer[:3], buffer[3:]
                for button_id, state in decode_button_state(frame):
                    action = SHIFT_NAMES.get(button_id, f"Button 0x{button_id:02X}")
                    print(f"Commande reçue: {action}, état={state}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Émule MyWhoosh comme client OpenBikeControl."
    )
    parser.add_argument("--host", help="Adresse directe (désactive la découverte mDNS).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--name", help="Nom mDNS exact du périphérique à rechercher.")
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        run(parse_args())
    except (ConnectionRefusedError, TimeoutError, OSError, ValueError) as error:
        raise SystemExit(f"Erreur émulateur MyWhoosh: {error}") from error
