import logging
import re
import threading
import time
import serial
import mqtt
from random import random
from gpiozero import OutputDevice, Button, LED
from sensors import SENSORS, LINK_STATES
from rgb1602 import LCD

COMMAND_DSL_DATA = b"\nlibmapi_dsl_cli\n"
COMMAND_ETH_DATA = b"ethtool eth0_1 | grep Link\n"
COMMAND_UPTIME = b"awk '{print \"\\nModem Uptime: \" $1}' /proc/uptime\n"
COMMAND_GET_SW_VERSION = b"cat /etc/sw_version\n"
COMMAND_SET_ROUTE = b"\nip route add 0.0.0.0/0 via 169.254.0.1\n"

ETH_IF = "enxb827ebc05d0a"

re_sw_version = re.compile(r"^\d{6}\.\d{1,2}\.\d{1,2}\.\d{3}\.\d{1,2}$")
re_int = re.compile(r"\D*(\d*)")
re_float = re.compile(r"\D*(\d+\.?\d*)")
re_hex = re.compile(r".*?(0x[\da-fA-F]*)")

def getValueFromString(line: str, returntype: type):
    """
    Uses different regexes to extract data from the modem output
    :param line:
    :param returntype:
    :return:
    """
    if returntype is int:
        match = re_int.match(line)
        return int(match[1])
    elif returntype is hex:
        match = re_hex.match(line)
        return int(match[1], 16)
    elif returntype is float:
        match = re_float.match(line)
        return float(match[1])
    elif returntype is str:
        _, value = line.split(":", maxsplit=1)
        return value.strip()
    else:
        raise TypeError("No Type defined")

class DSLModem:
    def __init__(self, serialport: str, baudrate: int = 115200, timeout: float = 1, rundir: str = None):
        self.LEDThread = None
        self.ethpacketcounter: int = 0
        self.serial = serial.Serial(serialport, baudrate, timeout=timeout)
        self.rundir = rundir
        self.modemData = {}
        self.trainingmode: int = 0
        self.laststatus: int = 0
        self.statusText: str = ""
        self.modemAvailable: bool = False
        self.lastAvailabilityCheck: float = 0
        self.showtime: bool = False
        self.mqtt = mqtt.Client(SENSORS.items())
        self.nextDataRequest: float = 0
        self.DataRequestTimer: float = 10
        self.lastReceived: float = time.time()
        self.lastReceivedTimeout: float = self.DataRequestTimer + timeout * 2
        self.collectedData = []
        self.collectingData: bool = False

        # initialize Modembutton
        self.modemButtonPressed: bool = False
        self.modemReboot: bool = False
        self.switch = ModemButton(27, 21, self)

        # initialize Displaybutton
        self.displaybutton = DisplayButton(22, self)

        # initialize display
        self.page = 0
        self.display = LCD()
        self.updateDisplay()
        self.display.backlight.brightness(50)
        self.displayTimer = None
        self.pageResetTimer = 10

        # initialize LEDs
        self.LED = ETHLEDs()

    def loopForever(self) -> None:
        self.LEDThread = LEDThread(self.LED)
        self.LEDThread.start()
        while True:
            self.loop()

    def loop(self) -> None:
        if not self.modemAvailable:
            if self.lastAvailabilityCheck + 5 < time.time():
                logging.debug("Send Availability Check...")
                self.lastAvailabilityCheck = time.time()
                self.serial.write(b"\n")  # Send newline to activate prompt

        line = ""
        try:
            line = self.serial.readline().strip().decode()
        except UnicodeDecodeError:
            pass
        except Exception as e:
            logging.error(e)

        if line.startswith("root@SpeedportW925V"):
            self.modemReboot = False
            self.lastReceived = time.time()
            if not self.modemAvailable:
                logging.info("Serial connection to modem established")
                self.modemAvailable = True
                self.serial.write(COMMAND_SET_ROUTE)
                self.mqtt.connect()
            if line.startswith("root@SpeedportW925V:/# libmapi_dsl_cli"):
                logging.debug("Collecting DSL data")
                self.collectingData = True
                self.collectedData = [time.strftime("%Y-%m-%d %H:%M:%S\n\n")]
                line = ""
            else:
                if self.collectingData:
                    logging.debug("Done collecting DSL data")
                    self.collectingData = False
                    self.writeCollectedData()
                    if self.mqtt.swversion == "":
                        logging.info("Requesting Software Version from modem")
                        self.serial.write(COMMAND_GET_SW_VERSION)
                line = line[len("root@SpeedportW925V:/#"):-1].strip()

        if line.startswith(">"):
            # we're stuck in a prompt we dont want to be in. Try to recover...
            logging.error("Got '>' prompt, trying to recover automatically")
            self.serial.write(b"\x03")  # CTRL+C
            self.serial.write(b"\x04")  # CTRL+D
            time.sleep(0.1)
            self.serial.write(b"\n")  # newline to activate shell again in case we closed it with CTRL-D

        if line != "":
            self.parseLine(line)
            self.trainingmode = self.modemData.get("dsl_link_state")
            if self.trainingmode is None or not self.modemAvailable:
                self.trainingmode = 0

        if self.modemAvailable or self.modemReboot:
            if self.nextDataRequest <= time.time():
                self.requestModemData()

            # timeout - Modem is offline
            if self.lastReceived + self.lastReceivedTimeout < time.time():
                logging.error("Lost serial connection to modem!")
                self.modemAvailable = False
                self.modemReboot = False
                self.mqtt.disconnect()
                self.trainingmode = 0
                self.modemData = {}
                self.updateDisplay()

        self.updateLEDs()

    def parseLine(self, line: str) -> None:
        # logging.debug(line)
        if self.collectingData:
            self.collectedData.append(line + "\n")

        try:
            for linestart, sensor in SENSORS.items():
                if line.startswith(linestart):
                    if not sensor.get("name"):
                        sensor["name"] = linestart
                    uid = sensor.get("name").replace(" ", "_").lower()
                    self.modemData[uid] = getValueFromString(line, sensor.get("type"))
                    if sensor.get("convert"):
                        sensorvalue = sensor.get("convert").get(self.modemData.get(uid))
                        if sensorvalue is None:
                            sensorvalue = "unknown"
                        self.mqtt.publish(uid + "/raw", str(self.modemData.get(uid)))
                    else:
                        sensorvalue = str(self.modemData.get(uid))
                    self.mqtt.publish(uid, sensorvalue, retain=True)
                    logging.debug(f'{sensor.get("name")}: {sensorvalue}')
                    return

            if line.startswith("xDSL training status changed"):
                self.nextDataRequest = time.time()

            elif line.startswith("xDSL Enter SHOWTIME"):
                logging.info("Showtime!")
                self.showtime = True
                self.nextDataRequest = time.time() + 2

            elif line.startswith("xDSL Leave SHOWTIME"):
                logging.info("No Showtime.")
                self.showtime = False
                self.nextDataRequest = time.time() + 2

            elif line.find("libphy: 0:02") > 0:
                self.nextDataRequest = time.time()

            elif re_sw_version.match(line):
                logging.info("Got Software Version: " + line)
                self.mqtt.swversion = line
                self.mqtt.hass_discovery()
                self.nextDataRequest = time.time() + 2

        except TypeError as e:
            logging.error(e)

    def close(self) -> None:
        logging.info("CLosing connections...")
        if self.displayTimer:
            self.displayTimer.cancel()
        self.LEDThread.stop()
        self.LEDThread.join()
        self.display.clear()
        self.display.backlight.RGB(0, 0, 0)
        self.mqtt.disconnect()
        self.serial.close()
        self.LED.close()
        logging.info("Connections closed.")

    def requestModemData(self) -> None:
        logging.debug("Requesting Modem Data...")
        if not self.mqtt.is_connected():
            self.mqtt.connect()

        self.nextDataRequest = time.time() + self.DataRequestTimer
        self.serial.write(COMMAND_UPTIME)
        self.serial.write(COMMAND_ETH_DATA)
        self.serial.write(COMMAND_DSL_DATA)

    def writeCollectedData(self) -> None:
        with open(self.rundir + "collectedData.txt", "w") as f:
            f.writelines(self.collectedData)
        self.updateDisplay()

    def updateDisplay(self) -> None:
        if self.modemButtonPressed:
            self.display.backlight.RGB(255, 0, 255)
        elif self.modemReboot:
            self.display.backlight.RGB(255, 0, 0)
        elif self.trainingmode in (0x0800, 0x0801):
            self.display.backlight.RGB(0, 255, 0)
        elif self.trainingmode >= 0x0300:
            self.display.backlight.RGB(255, 255, 0)
        else:
            self.display.backlight.RGB(255, 0, 0)

        self.display.clear()
        if self.modemReboot:
            self.display.printlines("Rebooting", "Modem!", align="center")
        elif self.modemButtonPressed:
            self.display.printlines("Hold Button:", "Modem Reset!", align="center")
        elif self.modemAvailable:
            if self.trainingmode in (0x800, 0x801):
                if self.page == 0:
                    self.display.print(f"US:{self.modemData.get('us_current_data_rate'):>8} kb/s", 0, 0)
                    self.display.print(f"DS:{self.modemData.get('ds_current_data_rate'):>8} kb/s", 1, 0)
                elif self.page == 1:
                    self.display.print(f"UA:{self.modemData.get('upstream_attainable_data_rate'):>8} kb/s", 0, 0)
                    self.display.print(f"DA:{self.modemData.get('downstream_attainable_data_rate'):>8} kb/s", 1, 0)
                elif self.page == 2:
                    self.display.print("Error-Counter:", 0, 0)
                    self.display.print(f"{self._count_errors()}", 1, 0)
                else:
                    self.page = 0
                    self.updateDisplay()
            else:
                self.display.print("DSL:", 0, 0)
                try:
                    self.display.print(LINK_STATES.get(self.trainingmode).title(), 1, 0)
                except:
                    self.display.print("Unknown", 1, 0)
        else:
            self.display.printlines("Modem", "unavailable", align="center")

    def next_page(self, reset = False) -> None:
        if self.displayTimer:
            self.displayTimer.cancel()
        if reset:
            self.page = 0
        else:
            self.page += 1
            self.displayTimer = threading.Timer(self.pageResetTimer, self.next_page, kwargs={"reset": True})
            self.displayTimer.start()
        self.updateDisplay()

    def updateLEDs(self) -> None:
        # update DSL connection LEDs
        if self.trainingmode in (0x800, 0x801):  # showtime
            self.LED.off(3, 1)
            self.LED.on(3, 2)
        elif self.trainingmode >= 0x300:  # training
            self.LED.on(3, 1)
            self.LED.off(3, 2)
        else:  # no connection
            self.LED.off(3, 1)
            self.LED.off(3, 2)

        # update PPPoE connection LEDs
        if self.modemData.get("eth_connected") == "yes":
            self.LED.on(2, 2)
        else:
            self.LED.off(2, 2)

    def _count_errors(self) -> int:
        errors = 0
        for key, data in self.modemData.items():
            if key.startswith(("near-end", "far-end")):
                errors += data
        return errors

class ModemButton:
    def __init__(self, inputpin, outputpin, modem: 'DSLModem'):
        self.output = OutputDevice(pin=outputpin, initial_value=True, active_high=True)
        self.button = Button(pin=inputpin, pull_up=True, bounce_time=None, hold_time=3)
        self.modem = modem
        self.button.when_held = self._restart
        self.button.when_activated = self._pressed
        self.button.when_deactivated = self._unpressed

    def on(self) -> None:
        self.output.on()

    def off(self) -> None:
        self.output.off()

    def _pressed(self) -> None:
        logging.info("Modem Button Pressed")
        self.modem.modemButtonPressed = True
        self.modem.updateDisplay()

    def _unpressed(self) -> None:
        logging.info("Modem Button Released")
        self.modem.modemButtonPressed = False
        self.modem.updateDisplay()

    def _restart(self) -> None:
        logging.info("Modem Button Held")
        self.modem.nextDataRequest = time.time() + 30
        self.modem.modemButtonPressed = False
        self.modem.modemReboot = True
        self.modem.updateDisplay()
        self.off()
        time.sleep(5)
        self.on()

class DisplayButton:
    def __init__(self, inputpin: int, modem: 'DSLModem'):
        self.button = Button(pin=inputpin, pull_up=True, bounce_time=0.1, hold_time=3)
        self.modem = modem
        self.pressed = False
        self.button.when_activated = self._pressed
        self.button.when_deactivated = self._unpressed

    def _pressed(self) -> None:
        logging.info("Display Button Pressed")
        self.pressed = True
        self.modem.next_page()

    def _unpressed(self) -> None:
        logging.info("Display Button Released")
        self.pressed = False

class LEDThread(threading.Thread):
    def __init__(self, led: 'ETHLEDs'):
        threading.Thread.__init__(self)
        self.name = "LEDThread"
        self.LED = led
        self.ethpacketcounter = 0
        self.running = True

    def run(self) -> None:
        logging.debug("Starting LED Thread")
        while self.running:
            # update ETH connection LEDs
            # check if eth0 is connected
            with open("/sys/class/net/"+ETH_IF+"/carrier") as f:
                carrier = f.readline().strip()
            if carrier:
                self.LED.on(1, 2)
            else:
                self.LED.off(1, 2)

            # read eth0 packet count for actvity led
            with open("/sys/class/net/"+ETH_IF+"/statistics/tx_packets") as f:
                packets = int(f.readline().strip())
            with open("/sys/class/net/"+ETH_IF+"/statistics/rx_packets") as f:
                packets += int(f.readline().strip())
            if packets != self.ethpacketcounter and not self.LED.value(1, 1):
                self.ethpacketcounter = packets
                self.LED.on(1, 1)
            else:
                self.LED.off(1, 1)
            time.sleep(0.1)

            # randomly flicker the LED for PPPoE if connected since we cant measure it
            if self.LED.value(2, 2):
                self.LED.value(2, 1, (random() < 0.5))
            else:
                self.LED.off(2, 1)

    def stop(self) -> None:
        logging.debug("Stopping LED Thread")
        self.running = False

class ETHLEDs:
    def __init__(self):
        """
        Controls the ETH LEDs on the board
        """
        self.eth1_1 = LED(18)
        self.eth1_2 = LED(17)
        self.eth2_1 = LED(8)
        self.eth2_2 = LED(25)
        self.eth3_1 = LED(7)
        self.eth3_2 = LED(11)
        self.LEDs = {1: {1: self.eth1_1, 2: self.eth1_2},
                     2: {1: self.eth2_1, 2: self.eth2_2},
                     3: {1: self.eth3_1, 2: self.eth3_2}}

    def close(self):
        for port in self.LEDs.values():
            for led in port.values():
                led.off()

    def on(self, port: int, led: int) -> None:
        """
        Turn LED on
        :param port:
        :param led:
        :return:
        """
        self.LEDs.get(port).get(led).on()

    def off(self, port: int, led: int) -> None:
        """
        Turn LED off
        :param port:
        :param led:
        :return:
        """
        self.LEDs.get(port).get(led).off()

    def value(self, port: int, led: int, value: int = None) -> int:
        """
        Set LED to value, returns state of the LED
        :param port:
        :param led:
        :param value:
        :return:
        """
        if value is not None:
            self.LEDs.get(port).get(led).value = value
        return self.LEDs.get(port).get(led).value