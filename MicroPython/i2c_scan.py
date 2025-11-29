# Just scan the I2C bus to make sure somebody is there
import machine
import utime

wakeup_pin = machine.Pin(27, machine.Pin.OUT)
wakeup_pin.value(1)
utime.sleep_ms(100)
i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(23))
print(f"I2C devices: " + ",".join(f"0x{item:x}" for item in i2c.scan()))
