import logging
import sys
import signal

from modemcontroller import DSLModem

SERIAL_INTERFACE = "/dev/serial0"
RUNDIR = "/run/dsl-modem/"

logging.basicConfig(
    encoding="utf-8",
    format='%(levelname)s: %(message)s',
    level=logging.INFO,
)

def killhandler(_signal = None, _frame = None):
    ser.close()
    sys.exit(0)


signal.signal(signal.SIGTERM, killhandler)

if __name__ == "__main__":
    ser = DSLModem(SERIAL_INTERFACE, rundir=RUNDIR)
    try:
        ser.loopForever()
    except KeyboardInterrupt:
        pass
    killhandler()

