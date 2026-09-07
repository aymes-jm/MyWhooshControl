"""Small mDNS/DNS-SD advertiser for MicroPython ESP32."""

import socket
import struct
import time


MDNS_ADDRESS = "224.0.0.251"
MDNS_PORT = 5353
MDNS_TTL = 120


def _name(value):
    value = value.rstrip(".")
    encoded = bytearray()
    for label in value.split("."):
        raw = label.encode()
        encoded.append(len(raw))
        encoded.extend(raw)
    encoded.append(0)
    return bytes(encoded)


def _record(owner, record_type, payload, ttl=MDNS_TTL, flush=True):
    record_class = 0x0001 | (0x8000 if flush else 0)
    return (
        _name(owner)
        + struct.pack(">HHIH", record_type, record_class, ttl, len(payload))
        + payload
    )


def _txt(properties):
    value = bytearray()
    for item in properties:
        raw = item.encode()
        if len(raw) > 255:
            raise ValueError("Propriété TXT trop longue")
        value.append(len(raw))
        value.extend(raw)
    return bytes(value)


class Service:
    """Advertise one TCP DNS-SD service on the local network."""

    def __init__(
        self, instance, service_type, port, properties=(), hostname=None, address=None
    ):
        self.instance = instance.rstrip(".")
        self.service_type = service_type.rstrip(".")
        self.port = port
        self.properties = tuple(properties)
        self.hostname = (hostname or "esp32").rstrip(".")
        self.address = address
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        self._socket.bind(("0.0.0.0", MDNS_PORT))
        membership = socket.inet_aton(MDNS_ADDRESS) + socket.inet_aton("0.0.0.0")
        self._socket.setsockopt(
            socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership
        )
        self._socket.settimeout(0.0)
        self._last_announcement = 0
        self.announce()

    def _records(self):
        instance = self.instance + "." + self.service_type + ".local"
        service_type = self.service_type + ".local"
        host = self.hostname + ".local"
        address = self.address or self._local_address()
        ptr = _record(service_type, 12, _name(instance))
        srv = _record(
            instance,
            33,
            struct.pack(">HHH", 0, 0, self.port) + _name(host),
        )
        txt = _record(instance, 16, _txt(self.properties))
        arecord = _record(host, 1, socket.inet_aton(address))
        return ptr + srv + txt + arecord

    def _packet(self, goodbye=False):
        instance = self.instance + "." + self.service_type + ".local"
        service_type = self.service_type + ".local"
        host = self.hostname + ".local"
        address = self.address or self._local_address()
        ttl = 0 if goodbye else MDNS_TTL
        ptr = _record(service_type, 12, _name(instance), ttl, False)
        srv = _record(
            instance,
            33,
            struct.pack(">HHH", 0, 0, self.port) + _name(host),
            ttl,
        )
        txt = _record(instance, 16, _txt(self.properties), ttl)
        arecord = _record(host, 1, socket.inet_aton(address), ttl)
        return struct.pack(">HHHHHH", 0, 0x8400, 0, 4, 0, 0) + ptr + srv + txt + arecord

    def announce(self):
        packet = self._packet()
        self._socket.sendto(packet, (MDNS_ADDRESS, MDNS_PORT))
        self._last_announcement = time.ticks_ms()

    def poll(self):
        """Answer mDNS queries and periodically refresh the announcement."""
        if time.ticks_diff(time.ticks_ms(), self._last_announcement) > 60000:
            self.announce()
        while True:
            try:
                packet, address = self._socket.recvfrom(512)
            except OSError:
                return
            if len(packet) < 4 or packet[2] & 0x80:
                continue
            if address[0] != self.address:
                self._socket.sendto(self._packet(), (MDNS_ADDRESS, MDNS_PORT))

    def _local_address(self):
        return "0.0.0.0"

    def close(self):
        try:
            self._socket.sendto(self._packet(goodbye=True), (MDNS_ADDRESS, MDNS_PORT))
        except OSError:
            pass
        self._socket.close()