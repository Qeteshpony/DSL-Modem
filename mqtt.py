import logging
import time

import paho.mqtt.client as mqtt
import json

SERVER = "10.101.100.21"
PORT = 1883
USER = ""
PASSWORD = ""
MQTT_DISCOVERY_BASETOPIC = "homeassistant/"
IDENTIFIER = "dslmodem_private"


class Client:
    def __init__(self, sensors: dict, send_again_timeout: float = 300):
        self.sensors = sensors
        self.sendAgain = send_again_timeout
        self.mqtt = mqtt.Client()
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_disconnect = self.on_disconnect
        self.connected = False
        self.basetopic = IDENTIFIER + "/"
        self.swversion = ""
        self.history = {}

    def connect(self):
        try:
            self.mqtt.connect(SERVER, PORT)
        except TimeoutError:
            pass
        else:
            self.mqtt.will_set(self.basetopic + "LWT", "offline", retain=True)
            self.mqtt.loop_start()

    def disconnect(self):
        self.publish("LWT", "offline", retain=True)
        self.mqtt.loop_stop()
        self.mqtt.disconnect()

    def on_connect(self, *_args, **_kwargs):
        self.connected = True
        logging.info("Connected to MQTT-Server")
        self.publish("LWT", "online", retain=True)
        # self.hass_discovery()

    def on_disconnect(self, *_args, **_kwargs):
        self.connected = False
        logging.info("MQTT disconnected")

    def is_connected(self) -> bool:
        return self.mqtt.is_connected()

    def publish(self, topic: str, message: str, retain: bool = False, fulltopic: bool = False):
        if self.connected:
            if not fulltopic:
                topic = self.basetopic + topic
            if not topic in self.history.keys():
                self.history[topic] = {"message": "", "timestamp": 0}
            if message != self.history.get(topic).get("message") or self.history.get(topic).get("timestamp") + self.sendAgain < time.time():
                self.mqtt.publish(topic, message, retain=retain)
                self.history[topic] = {"message": message, "timestamp": time.time()}


    def hass_discovery(self):
        logging.info("Sending HASS Discovery Messages...")
        for linestart, sensor in self.sensors:
            if not sensor.get("internal"):
                if not sensor.get("name"):
                    sensor["name"] = linestart
                if type(sensor.get("convert")) is dict:
                    sensor["options"] = list(sensor["convert"].values())
                    sensor["device_class"] = "enum"
                self.hass_discovery_message(**sensor)

    def hass_discovery_message(self, name: str, icon: str = None, **kwargs) -> None:
        kwargs.pop("type", None)
        kwargs.pop("convert", None)
        logging.debug("Sending HASS Discovery Message for " + name)

        uid = name.replace(" ", "_").lower()

        device = {
                "name": "DSL-Modem Privat",
                "identifiers": [IDENTIFIER],
                "manufacturer": "Deutsche Telekom",
                "model": "Speedport W925V",
                "sw_version": self.swversion,
        }

        payload = {
            "name": name,
            "unique_id": IDENTIFIER.lower() + "_" + uid,
            "device": device,
            "availability_topic": self.basetopic + "LWT",
            "state_topic": self.basetopic + uid,
            "icon": "mdi:"+icon,
        }

        for arg, value in kwargs.items():
            if value:
                payload[arg] = value

        self.publish(MQTT_DISCOVERY_BASETOPIC + "sensor/" + IDENTIFIER + "/" + uid + "/config",
                     json.dumps(payload), retain=True, fulltopic=True)


