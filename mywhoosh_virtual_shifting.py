#!/usr/bin/env python3
"""Control MyWhoosh virtual gears with the + and - keys.

This implements the MyWhoosh Link protocol used by OpenBikeControl:
MyWhoosh connects to this program as a TCP client on port 21587.
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
from contextlib import closing
from typing import Optional


DEFAULT_PORT = 21587


def gear_message(direction: int) -> bytes:
    """Return one MyWhoosh Link gear-shift message."""
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 or 1")
    message = {
        "MessageType": "Controls",
        "InGameControls": {"GearShifting": str(direction)},
    }
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


class MyWhooshLinkServer:
    """Small single-client TCP server compatible with MyWhoosh Link."""

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.bound_port: Optional[int] = None
        self._client: Optional[socket.socket] = None
        self._client_lock = threading.Lock()

    def serve_forever(self, stop_event: threading.Event) -> None:
        """Accept MyWhoosh connections until stop_event is set."""
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(1)
            server.settimeout(0.5)
            self.bound_port = server.getsockname()[1]
            print(f"MyWhoosh Link server listening on {self.host}:{self.bound_port}")
            print("Open MyWhoosh Link and connect it to this computer.")

            while not stop_event.is_set():
                try:
                    client, address = server.accept()
                except socket.timeout:
                    continue
                print(f"MyWhoosh connected from {address[0]}:{address[1]}")
                with self._client_lock:
                    old_client = self._client
                    self._client = client
                if old_client is not None:
                    old_client.close()
                client.settimeout(0.5)
                self._wait_for_disconnect(client, stop_event)
                with self._client_lock:
                    if self._client is client:
                        self._client = None
                client.close()
                print("MyWhoosh disconnected; waiting for reconnection.")

    @staticmethod
    def _wait_for_disconnect(
        client: socket.socket, stop_event: threading.Event
    ) -> None:
        """Keep the connection observable so a later Link reconnect works."""
        while not stop_event.is_set():
            try:
                data = client.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return

    def send_gear(self, direction: int) -> bool:
        """Send a gear shift; return False when MyWhoosh is not connected."""
        payload = gear_message(direction)
        with self._client_lock:
            client = self._client
            if client is None:
                return False
            try:
                client.sendall(payload)
            except OSError:
                self._client = None
                return False
        return True

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None:
                self._client.close()
                self._client = None


def run(args: argparse.Namespace) -> None:
    """Start the TCP server and global keyboard listener."""
    try:
        from pynput import keyboard
    except ImportError as error:
        raise SystemExit(
            "pynput est requis. Installez les dépendances avec: "
            "python -m pip install -r requirements.txt"
        ) from error

    stop_event = threading.Event()
    server = MyWhooshLinkServer(args.host, args.port)
    server_thread = threading.Thread(
        target=server.serve_forever, args=(stop_event,), daemon=True
    )
    server_thread.start()

    def on_press(key: object) -> Optional[bool]:
        if key == keyboard.Key.esc:
            stop_event.set()
            return False
        char = getattr(key, "char", None)
        direction = {"+": 1, "-": -1}.get(char)
        if direction is None:
            return None
        if server.send_gear(direction):
            print("Vitesse virtuelle: " + ("+" if direction > 0 else "-"))
        else:
            print("MyWhoosh n'est pas connecté.")
        return None

    print("Appuyez sur + ou - pour changer de vitesse, Échap pour quitter.")
    try:
        with keyboard.Listener(on_press=on_press) as listener:
            while not stop_event.wait(0.5):
                pass
            listener.stop()
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        server.close()
        server_thread.join(timeout=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pilote les vitesses virtuelles de MyWhoosh avec + et -."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Adresse d'écoute (défaut: toutes les interfaces).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port MyWhoosh Link (défaut: {DEFAULT_PORT}).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
