"""
Original from https://github.com/DFRobot/DFRobot_RGB1602_RaspberryPi/blob/master/python/rgb1602.py
Massively modified by Qetesh to make it work for this project
"""

import logging
import time
import smbus

LCD_ADDRESS = 0x3e
RGB_ADDRESS = 0x60

# Backlight control 
REG_RED = 0x04
REG_GREEN = 0x03
REG_BLUE = 0x02
REG_MODE1 = 0x00
REG_MODE2 = 0x01
REG_OUTPUT = 0x08

# LCD control
LCD_COMMAND = 0x80
LCD_DATA = 0x40
LCD_CLEARDISPLAY = 0x01
LCD_RETURNHOME = 0x02
LCD_ENTRYMODESET = 0x04
LCD_DISPLAYCONTROL = 0x08
LCD_CURSORSHIFT = 0x10
LCD_FUNCTIONSET = 0x20
LCD_SETCGRAMADDR = 0x40
LCD_SETDDRAMADDR = 0x80

# flags for display entry mode
LCD_ENTRYRIGHT = 0x00
LCD_ENTRYLEFT = 0x02
LCD_ENTRYSHIFTINCREMENT = 0x01
LCD_ENTRYSHIFTDECREMENT = 0x00

# flags for display on/off control
LCD_DISPLAYON = 0x04
LCD_DISPLAYOFF = 0x00
LCD_CURSORON = 0x02
LCD_CURSOROFF = 0x00
LCD_BLINKON = 0x01
LCD_BLINKOFF = 0x00

# flags for display/cursor shift
LCD_DISPLAYMOVE = 0x08
LCD_CURSORMOVE = 0x00
LCD_MOVERIGHT = 0x04
LCD_MOVELEFT = 0x00

# flags for function set
LCD_8BITMODE = 0x10
LCD_4BITMODE = 0x00
LCD_2LINE = 0x08
LCD_1LINE = 0x00
LCD_5x10DOTS = 0x04
LCD_5x8DOTS = 0x00

lcd_charmap = {
    ord(u'ä'): chr(0xe1),
    ord(u'Ä'): chr(0xe1),
    ord(u'ö'): chr(0xef),
    ord(u'Ö'): chr(0xef),
    ord(u'ü'): chr(0xf5),
    ord(u'Ü'): chr(0xf5),
    ord(u'°'): chr(0xdf),
    ord(u'α'): chr(0xe0),
    ord(u'β'): chr(0xe2),
    ord(u'ε'): chr(0xe3),
    ord(u'σ'): chr(0xe5),
    ord(u'ρ'): chr(0xe6),
    ord(u'π'): chr(0xf7),
    ord(u'√'): chr(0xe8),
    ord(u'μ'): chr(0xe4),
    ord(u'¢'): chr(0xec),
    ord(u'£'): chr(0xed),
    ord(u'ñ'): chr(0xee),
    ord(u'ϴ'): chr(0xf2),
    ord(u'∞'): chr(0xf3),
    ord(u'Σ'): chr(0xf6),
    ord(u'Ω'): chr(0xf4),
    ord(u'÷'): chr(0xfd),
}


class LCD:
    def __init__(self, cols: int = 16, lines: int = 2, i2cbus: int = 1) -> None:
        self._showmode = None
        self._currline = None
        self._numlines = None
        self._showcontrol = None
        self._numlines = lines
        self._numcols = cols
        self._currline = 0
        
        self._bus = smbus.SMBus(i2cbus)
        self._showfunction = LCD_4BITMODE | LCD_1LINE | LCD_5x8DOTS

        if lines > 1:
            self._showfunction |= LCD_2LINE

        # Send function set command sequence
        self.LCDCommand(LCD_FUNCTIONSET | self._showfunction)
        # delayMicroseconds(4500);  # wait more than 4.1ms
        time.sleep(0.005)
        # second try
        self.LCDCommand(LCD_FUNCTIONSET | self._showfunction)
        # delayMicroseconds(150);
        time.sleep(0.005)
        # third go
        self.LCDCommand(LCD_FUNCTIONSET | self._showfunction)
        # finally, set # lines, font size, etc.
        self.LCDCommand(LCD_FUNCTIONSET | self._showfunction)
        # turn the display on with no cursor or blinking default
        self._showcontrol = LCD_DISPLAYON | LCD_CURSOROFF | LCD_BLINKOFF
        self.display()
        # clear it off
        self.clear()
        # Initialize to default text direction (for romance languages)
        self._showmode = LCD_ENTRYLEFT | LCD_ENTRYSHIFTDECREMENT
        # set the entry mode
        self.LCDCommand(LCD_ENTRYMODESET | self._showmode)

        # init backlight
        self.backlight = Backlight(self._bus)

    def LCDCommand(self, cmd: int) -> None:
        self._bus.write_i2c_block_data(LCD_ADDRESS, LCD_COMMAND, [cmd])

    def LCDwrite(self, data: int) -> None:
        self._bus.write_i2c_block_data(LCD_ADDRESS, LCD_DATA, [data])

    def setCursor(self, row: int, col: int) -> None:
        if row == 0:
            col |= 0x80
        else:
            col |= 0xc0
        self.LCDCommand(col)

    def clear(self) -> None:
        self.LCDCommand(LCD_CLEARDISPLAY)
        time.sleep(0.002)

    def scrollDisplayLeft(self, cols: int = 1) -> None:
        for _ in range(cols):
            self.LCDCommand(LCD_CURSORSHIFT | LCD_DISPLAYMOVE | LCD_MOVELEFT)

    def scrollDisplayRight(self, cols: int = 1) -> None:
        for _ in range(cols):
            self.LCDCommand(LCD_CURSORSHIFT | LCD_DISPLAYMOVE | LCD_MOVERIGHT)

    def print(self, text: str, row: int = None, col: int = None, align: str = "left") -> None:
        if align == "center":
            col = (self._numcols - len(text)) // 2
        if align == "right":
            col = self._numcols - len(text)
        if row or col:
            if row is None: row = 0
            if col is None: col = 0
            self.setCursor(row=row, col=col)
        text = text.translate(lcd_charmap)
        for char in text:
            self.LCDwrite(ord(char))

    def printlines(self, line1, line2, align="left"):
        self.print(line1, 0, 0, align=align)
        self.print(line2, 1, 0, align=align)

    def home(self) -> None:
        self.LCDCommand(LCD_RETURNHOME)  # set cursor position to zero
        time.sleep(1)  # this command takes a long time!

    def noDisplay(self) -> None:
        self._showcontrol &= ~LCD_DISPLAYON
        self.LCDCommand(LCD_DISPLAYCONTROL | self._showcontrol)

    def display(self) -> None:
        self._showcontrol |= LCD_DISPLAYON
        self.LCDCommand(LCD_DISPLAYCONTROL | self._showcontrol)

    def stopBlink(self) -> None:
        self._showcontrol &= ~LCD_BLINKON
        self.LCDCommand(LCD_DISPLAYCONTROL | self._showcontrol)

    def blink(self) -> None:
        self._showcontrol |= LCD_BLINKON
        self.LCDCommand(LCD_DISPLAYCONTROL | self._showcontrol)

    def noCursor(self) -> None:
        self._showcontrol &= ~LCD_CURSORON
        self.LCDCommand(LCD_DISPLAYCONTROL | self._showcontrol)

    def cursor(self) -> None:
        self._showcontrol |= LCD_CURSORON
        self.LCDCommand(LCD_DISPLAYCONTROL | self._showcontrol)

    def leftToRight(self) -> None:
        self._showmode |= LCD_ENTRYLEFT
        self.LCDCommand(LCD_ENTRYMODESET | self._showmode)

    def rightToLeft(self) -> None:
        self._showmode &= ~LCD_ENTRYLEFT
        self.LCDCommand(LCD_ENTRYMODESET | self._showmode)

    def noAutoscroll(self) -> None:
        self._showmode &= ~LCD_ENTRYSHIFTINCREMENT
        self.LCDCommand(LCD_ENTRYMODESET | self._showmode)

    def autoscroll(self) -> None:
        self._showmode |= LCD_ENTRYSHIFTINCREMENT
        self.LCDCommand(LCD_ENTRYMODESET | self._showmode)

    def customSymbol(self, location: int, charmap: list) -> None:
        location &= 0x7  # we only have 8 locations 0-7
        self.LCDCommand(LCD_SETCGRAMADDR | (location << 3))

        for i in range(0, 8):
            self._bus.write_i2c_block_data(LCD_ADDRESS, 0x40, [charmap[i]])

    def blink_on(self) -> None:
        self.blink()

    def blink_off(self) -> None:
        self.stopBlink()

    def cursor_on(self) -> None:
        self.cursor()

    def cursor_off(self) -> None:
        self.noCursor()


class Backlight:
    def __init__(self, bus):
        self._bus = bus
        self.brightnesslevel = 255
        self.rgbvalues = [0,0,0]
        # backlight init
        self.set(REG_MODE1, 0)
        # set LEDs controllable by both PWM and GRPPWM registers
        self.set(REG_OUTPUT, 0xFF)
        # set MODE2 values
        # 0010 0000 -> 0x20  (DMBLNK to 1, ie blinky mode)
        self.set(REG_MODE2, 0x20)
        self.RGB(255, 255, 255)

    def set(self, reg: int, data: int) -> None:
        self._bus.write_i2c_block_data(RGB_ADDRESS, reg, [data])

    def RGB(self, red: int = None, green: int = None, blue: int = None, brightness: int = None) -> None:
        if red is None:
            red = self.rgbvalues[0]
        if green is None:
            green = self.rgbvalues[1]
        if blue is None:
            blue = self.rgbvalues[2]
        if brightness is not None:
            self.brightnesslevel = brightness

        logging.debug(f"Set Backlight to ({red}, {green}, {blue}, {self.brightnesslevel})")

        self.rgbvalues = [red, green, blue]

        red = int(red * self.brightnesslevel / 255)
        green = int(green * self.brightnesslevel / 255)
        blue = int(blue * self.brightnesslevel / 255)

        self.set(REG_RED, red)
        self.set(REG_GREEN, green)
        self.set(REG_BLUE, blue)

    def brightness(self, brightness: int) -> None:
        self.brightnesslevel = brightness
        self.RGB()

    def blink(self, period: float = 1.0, dutycycle: float = 0.5, blink: bool = True) -> None:
        if not blink:
            period = 0.0
            dutycycle = 1.0

        # blink period in seconds = (<reg 7> + 1) / 24
        # on/off ratio = <reg 6> / 255
        period = int(period * 24)
        if period > 0xFF:
            period = 0
        if not 0.0 <= dutycycle <= 1.0:
            raise ValueError("Duty Cycle must be between 0.0 and 1.0")
        dutycycle = int(dutycycle * 255)
        self.set(0x07, period)  # blink every second
        self.set(0x06, dutycycle)  # half on, half off

    def noBlink(self) -> None:
        self.set(0x07, 0x00)
        self.set(0x06, 0xff)
