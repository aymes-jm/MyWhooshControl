#!/usr/bin/env python3
"""Emulate the MyWhoosh Link application for local protocol testing.

The emulator connects as a MyWhoosh Link client and displays the JSON
commands sent by mywhoosh_virtual_shifting.py.
"""

from __future__ import annotations

import argparse
import json
import socket
from typing import Any


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 21587


def handle_message(line: bytes) -> dict[str, Any]:
    """Decode and validate one newline-delimited MyWhoosh message."""
    message = json.loads(line.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("message JSON must be an object")
    if message.get("MessageType") != "Controls":
        raise ValueError("unexpected MessageType")
    controls = message.get("InGameControls")
    if not isinstance(controls, dict) or "GearShifting" not in controls:
        raise ValueError("missing InGameControls.GearShifting")
    if controls["GearShifting"] not in ("1", "-1"):
        raise ValueError("GearShifting must be '1' or '-1'")
    return message


def run(host: str, port: int) -> None:
    """Connect to the controller and print received gear commands."""
    print(f"Connexion à {host}:{port}...")
    with socket.create_connection((host, port), timeout=10) as client:
        client.settimeout(None)
        print("Connecté. Appuyez sur + ou - dans l'autre terminal.")
        buffer = b""
        while True:
            data = client.recv(4096)
            if not data:
                print("Le contrôleur a fermé la connexion.")
                return
            buffer += data
            while b"\n" in buffer:
                raw_line, buffer = buffer.split(b"\n", 1)
                if not raw_line.strip():
                    continue
                try:
                    message = handle_message(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                    print(f"Commande invalide reçue: {error}")
                    continue
                direction = message["InGameControls"]["GearShifting"]
                label = "montée (+)" if direction == "1" else "descente (-)"
                print(f"Commande reçue: {label} | {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Émule MyWhoosh Link et affiche les commandes reçues."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        run(**vars(parse_args()))
    except KeyboardInterrupt:
        print("\nArrêt de l'émulateur.")
    except ConnectionRefusedError:
        raise SystemExit(
            "Connexion refusée. Lancez d'abord mywhoosh_virtual_shifting.py."
        )
