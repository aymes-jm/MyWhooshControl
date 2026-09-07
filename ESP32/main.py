"""MicroPython bridge from CYCPLUS BC2 BLE buttons to OpenBikeControl.

The ESP32 acts as a BLE central for the BC2 and as a TCP server for the
OpenBikeControl application. Configure the Wi-Fi and BC2 name below before
flashing the script.
"""

import bluetooth
import mdns
import network
import socket
import time
from micropython import const


WIFI_SSID = ""
WIFI_PASSWORD = ""
BC2_NAME = "CYCPLUS BC2"
OBC_PORT = 8765
UP_CODE = 0x01
DOWN_CODE = 0x01
MIN_FRAME_INTERVAL_MS = 50

UART_SERVICE_UUID = bluetooth.UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
UART_RX_UUID = bluetooth.UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e")
UART_TX_UUID = bluetooth.UUID("6e400003-b5a3-f393-e0a9-e50e24dcca9e")

_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_GATTC_SERVICE_RESULT = const(9)
_IRQ_GATTC_SERVICE_DONE = const(10)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_CHARACTERISTIC_DONE = const(12)
_IRQ_GATTC_NOTIFY = const(18)


def _decode_name(adv_data):
    """Return the complete or shortened Bluetooth name from advertisement data."""
    index = 0
    while index + 1 < len(adv_data):
        length = adv_data[index]
        if length == 0:
            break
        kind = adv_data[index + 1]
        if kind in (0x08, 0x09):
            return bytes(adv_data[index + 2:index + 1 + length]).decode(
                "utf-8", "ignore"
            )
        index += length + 1
    return ""


def _button_states(data):
    """Decode the BC2 button fields at offsets 6 and 7."""
    if len(data) <= 7:
        return False, False
    return data[6] == UP_CODE, data[7] == DOWN_CODE


class OpenBikeControlServer:
    """Serve one TCP client and send OBC button-state frames."""

    def __init__(self, port):
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("0.0.0.0", port))
        self.server.listen(1)
        self.server.settimeout(0.1)
        self.client = None
        self.last_sent_ms = 0

    def poll(self):
        try:
            client, address = self.server.accept()
        except OSError:
            return
        client.settimeout(0.0)
        if self.client is not None:
            try:
                self.client.close()
            except OSError:
                pass
        self.client = client
        print("OpenBikeControl connecté:", address)

    def send_button(self, button_id, state):
        if self.client is None:
            return False
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self.last_sent_ms)
        if elapsed < MIN_FRAME_INTERVAL_MS:
            time.sleep_ms(MIN_FRAME_INTERVAL_MS - elapsed)
        try:
            self.client.send(bytes((0x01, button_id, state)))
        except OSError:
            self.close_client()
            return False
        self.last_sent_ms = time.ticks_ms()
        return True

    def close_client(self):
        if self.client is not None:
            try:
                self.client.close()
            except OSError:
                pass
            self.client = None

    def close(self):
        self.close_client()
        self.server.close()


class BC2Central:
    """Find, connect to, and subscribe to the BC2 Nordic UART TX field."""

    def __init__(self, on_report):
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        self.on_report = on_report
        self.address = None
        self.address_type = None
        self.conn_handle = None
        self.service_handle = None
        self.tx_handle = None
        self._scan_done = False
        self._service_done = False
        self._characteristic_done = False

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            address_type, address, _, _, adv_data = data
            name = _decode_name(adv_data)
            if BC2_NAME.lower() in name.lower():
                self.address_type = address_type
                self.address = bytes(address)
                self.ble.gap_scan(None)
        elif event == _IRQ_SCAN_DONE:
            self._scan_done = True
        elif event == _IRQ_PERIPHERAL_CONNECT:
            _, _, conn_handle = data
            self.conn_handle = conn_handle
            self._service_done = False
            self.ble.gattc_discover_services(conn_handle)
        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            self.conn_handle = None
            self.service_handle = None
            self.tx_handle = None
        elif event == _IRQ_GATTC_SERVICE_RESULT:
            conn_handle, start_handle, end_handle, uuid = data
            if conn_handle == self.conn_handle and uuid == UART_SERVICE_UUID:
                self.service_handle = (start_handle, end_handle)
        elif event == _IRQ_GATTC_SERVICE_DONE:
            if self.service_handle is not None:
                self._characteristic_done = False
                self.ble.gattc_discover_characteristics(
                    self.conn_handle,
                    self.service_handle[0],
                    self.service_handle[1],
                )
            else:
                self._service_done = True
        elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
            conn_handle, _, value_handle, properties, uuid = data
            if conn_handle == self.conn_handle and uuid == UART_TX_UUID:
                self.tx_handle = value_handle
        elif event == _IRQ_GATTC_CHARACTERISTIC_DONE:
            self._characteristic_done = True
        elif event == _IRQ_GATTC_NOTIFY:
            conn_handle, value_handle, data = data
            if conn_handle == self.conn_handle and value_handle == self.tx_handle:
                self.on_report(bytes(data))

    def connect(self):
        self.address = None
        self._scan_done = False
        print("Recherche BLE:", BC2_NAME)
        self.ble.gap_scan(5000, 30000, 30000)
        deadline = time.ticks_add(time.ticks_ms(), 7000)
        while self.address is None and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(50)
        self.ble.gap_scan(None)
        if self.address is None:
            raise RuntimeError("CYCPLUS BC2 introuvable")
        print("Connexion au CYCPLUS BC2")
        self.ble.gap_connect(self.address_type, self.address)
        deadline = time.ticks_add(time.ticks_ms(), 10000)
        while self.conn_handle is None and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(50)
        if self.conn_handle is None:
            raise RuntimeError("Connexion BLE impossible")
        deadline = time.ticks_add(time.ticks_ms(), 5000)
        while not self._characteristic_done and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(50)
        if self.tx_handle is None:
            raise RuntimeError("Caractéristique UART TX introuvable")
        self.ble.gattc_write(
            self.conn_handle,
            self.tx_handle + 1,
            b"\x01\x00",
            1,
        )
        print("Notifications BC2 activées")

    def close(self):
        if self.conn_handle is not None:
            self.ble.gap_disconnect(self.conn_handle)
        self.ble.active(False)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    while not wlan.isconnected():
        time.sleep_ms(250)
    print("Wi-Fi:", wlan.ifconfig()[0])
    return wlan


def main():
    wlan = connect_wifi()
    obc = OpenBikeControlServer(OBC_PORT)
    mdns_service = mdns.Service(
        "CYCPLUS BC2 OpenBikeControl",
        "_openbikecontrol._tcp",
        OBC_PORT,
        (
            "version=1",
            "name=CYCPLUS BC2 OpenBikeControl",
            "service-uuids=d273f680-d548-419d-b9d1-fa0472345229",
            "manufacturer=CYCPLUS",
            "model=BC2 BLE buttons",
        ),
        hostname=network.hostname() or "esp32",
        address=wlan.ifconfig()[0],
    )
    previous = (False, False)

    def handle_report(data):
        nonlocal previous
        current = _button_states(data)
        for button_id, (was_pressed, is_pressed) in enumerate(
            zip(previous, current), start=1
        ):
            if was_pressed != is_pressed:
                if obc.send_button(button_id, int(is_pressed)):
                    print("Bouton", button_id, "état", int(is_pressed))
        previous = current

    bc2 = BC2Central(handle_report)
    try:
        bc2.connect()
        while True:
            obc.poll()
            mdns_service.poll()
            time.sleep_ms(10)
    finally:
        bc2.close()
        mdns_service.close()
        obc.close()


main()