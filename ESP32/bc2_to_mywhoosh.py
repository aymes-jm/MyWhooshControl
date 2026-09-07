"""MicroPython bridge from CYCPLUS BC2 BLE buttons to OpenBikeControl.

The ESP32 acts as a BLE central for the BC2 and as a TCP server for the
OpenBikeControl application. Configure the Wi-Fi and BC2 name below before
flashing the script.
"""

import bluetooth
from machine import Pin
import mdns
import network
import socket
import time
from micropython import const


WIFI_SSID = "KANGOUROUS"
WIFI_PASSWORD = "SontFous"
BC2_NAME = "CYCPLUS BC2"
OBC_PORT = 8765
UP_CODE = 0x01
DOWN_CODE = 0x01
MIN_FRAME_INTERVAL_MS = 50
LED_PIN = 21
LED_ON = 1
LED_OFF = 0
LED_SINGLE_PERIOD_MS = 2000
LED_DOUBLE_FLASH_MS = 250

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


class StatusLed:
    """Display BC2 and OpenBikeControl connection status on the LED."""

    def __init__(self):
        self.pin = Pin(LED_PIN, Pin.OUT, value=LED_OFF)
        self.pattern = None
        self.pattern_started_ms = time.ticks_ms()
        self.last_state = None

    def _set(self, is_on):
        state = LED_ON if is_on else LED_OFF
        if state != self.last_state:
            self.pin.value(state)
            self.last_state = state

    def update(self, bc2_connected, app_connected):
        if bc2_connected and app_connected:
            pattern = "connected"
        elif bc2_connected or app_connected:
            pattern = "one_connected"
        else:
            pattern = "none_connected"

        now = time.ticks_ms()
        if pattern != self.pattern:
            self.pattern = pattern
            self.pattern_started_ms = now

        elapsed = time.ticks_diff(now, self.pattern_started_ms)
        if pattern == "connected":
            self._set(True)
        elif pattern == "one_connected":
            phase = elapsed % LED_SINGLE_PERIOD_MS
            first_flash = phase < LED_DOUBLE_FLASH_MS
            second_flash = (
                2 * LED_DOUBLE_FLASH_MS
                <= phase
                < 3 * LED_DOUBLE_FLASH_MS
            )
            self._set(first_flash or second_flash)
        else:
            self._set(elapsed % LED_SINGLE_PERIOD_MS < 1000)


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
        self._check_client()
        try:
            client, address = self.server.accept()
        except OSError:
            return
        client.settimeout(0.0)
        if self.client is not None:
            print("OpenBikeControl déconnecté")
            try:
                self.client.close()
            except OSError:
                pass
        self.client = client
        print("OpenBikeControl connecté:", address)

    def _check_client(self):
        if self.client is None:
            return
        try:
            data = self.client.recv(1)
        except OSError:
            return
        if not data:
            self.close_client()
            print("OpenBikeControl déconnecté")

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
            conn_handle, _, _ = data
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

    def connect(self, status_led=None):
        self.address = None
        self._scan_done = False
        print("Recherche BLE:", BC2_NAME)
        self.ble.gap_scan(5000, 30000, 30000)
        deadline = time.ticks_add(time.ticks_ms(), 7000)
        while self.address is None and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if status_led is not None:
                status_led.update(False, False)
            time.sleep_ms(50)
        self.ble.gap_scan(None)
        if self.address is None:
            raise RuntimeError("CYCPLUS BC2 introuvable")
        print("Connexion au CYCPLUS BC2")
        self.ble.gap_connect(self.address_type, self.address)
        deadline = time.ticks_add(time.ticks_ms(), 10000)
        while self.conn_handle is None and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if status_led is not None:
                status_led.update(False, False)
            time.sleep_ms(50)
        if self.conn_handle is None:
            raise RuntimeError("Connexion BLE impossible")
        deadline = time.ticks_add(time.ticks_ms(), 5000)
        while not self._characteristic_done and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if status_led is not None:
                status_led.update(True, False)
            time.sleep_ms(50)
        if self.tx_handle is None:
            raise RuntimeError("Caractéristique UART TX introuvable")
        self.ble.gattc_write(
            self.conn_handle,
            self.tx_handle + 1,
            b"\x01\x00",
            1,
        )
        print("BC2 connecté, notifications activées")

    def close(self):
        if self.conn_handle is not None:
            self.ble.gap_disconnect(self.conn_handle)
        self.ble.active(False)


def connect_wifi(status_led=None):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    while not wlan.isconnected():
        if status_led is not None:
            status_led.update(False, False)
        time.sleep_ms(250)
    print("Wi-Fi:", wlan.ifconfig()[0])
    return wlan


def main():
    status_led = StatusLed()
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
        address="0.0.0.0",
    )
    wlan = connect_wifi(status_led)
    mdns_service.address = wlan.ifconfig()[0]
    mdns_service.join_multicast()
    mdns_service.announce()
    obc = OpenBikeControlServer(OBC_PORT)
    previous = (False, False)
    previous_bc2_connected = False
    previous_app_connected = False

    def handle_report(data):
        nonlocal previous
        current = _button_states(data)
        for button_id, (was_pressed, is_pressed) in enumerate(
            zip(previous, current), start=1
        ):
            if was_pressed != is_pressed:
                button_name = "+" if button_id == 1 else "-"
                action = "appuyé" if is_pressed else "relâché"
                print("Bouton", button_name, action)
                if obc.send_button(button_id, int(is_pressed)):
                    print("Bouton", button_name, "envoyé", int(is_pressed))
        previous = current

    bc2 = BC2Central(handle_report)
    try:
        bc2.connect(status_led)
        previous_bc2_connected = bc2.conn_handle is not None
        while True:
            obc.poll()
            mdns_service.poll()
            bc2_connected = bc2.conn_handle is not None
            app_connected = obc.client is not None
            if bc2_connected != previous_bc2_connected:
                print("BC2 connecté" if bc2_connected else "BC2 déconnecté")
                previous_bc2_connected = bc2_connected
            if app_connected != previous_app_connected:
                print(
                    "Application OpenBikeControl connectée"
                    if app_connected
                    else "Application OpenBikeControl déconnectée"
                )
                previous_app_connected = app_connected
            status_led.update(bc2_connected, app_connected)
            time.sleep_ms(10)
    finally:
        bc2.close()
        mdns_service.close()
        obc.close()


main()