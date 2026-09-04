#!/usr/bin/env python3
"""Expose the + and - keys as an OpenBikeControl network device."""

from __future__ import annotations

import argparse
import socket
import threading
import uuid
from contextlib import closing
from typing import Optional

from zeroconf import ServiceInfo, Zeroconf


SERVICE_TYPE = "_openbikecontrol._tcp.local."
SERVICE_UUID = "d273f680-d548-419d-b9d1-fa0472345229"
SHIFT_UP = bytes((0x01, 0x01, 0x01))
SHIFT_DOWN = bytes((0x01, 0x02, 0x01))


def local_address() -> str:
    """Find the LAN address that other applications can use."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class OpenBikeControlDevice:
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
                    self._client = client
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

    def send_shift(self, direction: int) -> bool:
        payload = SHIFT_UP if direction > 0 else SHIFT_DOWN
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


def run(args: argparse.Namespace) -> None:
    from pynput import keyboard

    stop = threading.Event()
    device = OpenBikeControlDevice(args.host, args.port)
    thread = threading.Thread(target=device.serve, args=(stop,), daemon=True)
    thread.start()
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
            b"manufacturer": b"BikeControl",
            b"model": b"Virtual Keyboard",
        },
    )
    zeroconf = Zeroconf()
    zeroconf.register_service(service)
    print(f"Advertised as {service_name} at {advertised_host}:{device.port}")
    print("Appuyez sur + ou - ; Echap pour quitter.")

    def on_press(key: object) -> Optional[bool]:
        if key == keyboard.Key.esc:
            stop.set()
            return False
        direction = {"+": 1, "-": -1}.get(getattr(key, "char", None))
        if direction is not None:
            if device.send_shift(direction):
                print("Commande OBC envoyée: " + ("Shift Up" if direction > 0 else "Shift Down"))
            else:
                print("Aucune application OpenBikeControl connectée.")
        return None

    try:
        with keyboard.Listener(on_press=on_press) as listener:
            while not stop.wait(0.5):
                pass
            listener.stop()
    except KeyboardInterrupt:
        stop.set()
    finally:
        device.close()
        zeroconf.unregister_service(service)
        zeroconf.close()
        thread.join(timeout=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Émule un périphérique OpenBikeControl.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--advertise-host", help="Adresse annoncée par mDNS.")
    parser.add_argument("--port", type=int, default=0, help="0 choisit un port libre.")
    parser.add_argument("--name", default="BikeControl Virtual Shifting")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
