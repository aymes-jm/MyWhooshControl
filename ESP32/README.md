# ESP32 MicroPython

`main.py` relie les boutons BLE du CYCPLUS BC2 à un client OpenBikeControl.
L'ESP32 se connecte au BC2 comme central BLE, ouvre un serveur TCP sur le port
`8765` et publie ce serveur avec le module mDNS local `mdns.py`.

Avant le transfert, renseigner `WIFI_SSID`, `WIFI_PASSWORD` et éventuellement
`BC2_NAME`, `UP_CODE` et `DOWN_CODE` dans `main.py`. Le protocole reprend le
code Python : les octets 6 et 7 des rapports UART indiquent respectivement
les boutons `+` et `-`, et une trame OBC vaut `01 <bouton> <état>`.

Le module répond aux requêtes DNS-SD sur `224.0.0.251:5353` et publie les
enregistrements `PTR`, `SRV`, `TXT` et `A` du service
`_openbikecontrol._tcp.local.`. Si le réseau bloque le multicast, utiliser
l'adresse IP affichée sur la console série comme solution de secours.