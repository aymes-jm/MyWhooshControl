# Contrôle des vitesses MyWhoosh

Ce script reprend la méthode **MyWhoosh Link** utilisée dans
[OpenBikeControl](https://github.com/OpenBikeControl/bikecontrol) :
MyWhoosh se connecte à un serveur TCP local sur le port fixe `21587`, puis le
script lui envoie les commandes de changement de vitesse.

## Installation

```bash
python3 -m pip install -r requirements.txt
```

## Utilisation

1. Lancez le script sur le même ordinateur que MyWhoosh :

   ```bash
   python3 mywhoosh_virtual_shifting.py
   ```

2. Dans MyWhoosh, activez/configurez **MyWhoosh Link** pour cet ordinateur.
3. Appuyez sur `+` pour monter d'une vitesse et `-` pour descendre.
4. Appuyez sur `Échap` ou `Ctrl+C` pour arrêter.

Le port `21587` est imposé par le protocole MyWhoosh Link. Si le pare-feu
bloque la connexion, autorisez Python sur ce port.

## Tester sans MyWhoosh

Dans un premier terminal, lancez le contrôleur :

```bash
python3 mywhoosh_virtual_shifting.py
```

Dans un second terminal, lancez l'émulateur :

```bash
python3 mywhoosh_link_emulator.py
```

Appuyez ensuite sur `+` ou `-` dans le premier terminal. L'émulateur affiche
chaque commande JSON reçue comme le ferait MyWhoosh.

## Utiliser OpenBikeControl directement

Le script [openbikecontrol_virtual_device.py](./openbikecontrol_virtual_device.py)
émule un périphérique OpenBikeControl via mDNS/TCP (format binaire officiel).
MyWhoosh doit être configuré pour rechercher les périphériques OpenBikeControl.

```bash
python3 openbikecontrol_virtual_device.py
```

MyWhoosh découvre alors `BikeControl Virtual Shifting`. Les touches `+` et `-`
émettent respectivement les boutons OBC `0x01` (Shift Up) et `0x02`
(Shift Down).

Pour tester le périphérique simulé comme si MyWhoosh était connecté, lancez
dans un autre terminal :

```bash
python3 mywhoosh_openbikecontrol_emulator.py --host 127.0.0.1 --port 8765
```

Utilisez le même port que celui indiqué par le périphérique virtuel (il est
conseillé de lancer celui-ci avec `--port 8765`). Sans `--host`, l'émulateur
cherche automatiquement le périphérique via mDNS :

```bash
python3 mywhoosh_openbikecontrol_emulator.py
```

## Utiliser un CYCPLUS BC2

Le script `cycplus_bc2_openbikecontrol.py` découvre le CYCPLUS BC2 en BLE,
écoute sa caractéristique notificatrice et publie les boutons comme un
périphérique OpenBikeControl. Il recherche par défaut le code HID `0x2e` pour
`+` et `0x2d` pour `-`.

```bash
python3 cycplus_bc2_openbikecontrol.py
```

Le nom BLE et la caractéristique peuvent être précisés si nécessaire :

```bash
python3 cycplus_bc2_openbikecontrol.py \
   --device "CYCPLUS BC2" \
   --characteristic 00002a4d-0000-1000-8000-00805f9b34fb
```

Si les rapports du périphérique utilisent d'autres codes, utilisez `--up-code`
et `--down-code` en décimal ou hexadécimal. Le Bluetooth doit être activé et
le périphérique ne doit pas être déjà connecté à une autre application.
