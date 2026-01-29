## @file task_gps.py
#
#  This task sets up and watches a GPS module that keeps track of position and
#  time for a Bogan Radar. It uses a Real-Time Clock (RTC) to hold the time
#  in between GPS fixes.
#
#  The current design uses a PCF8523 RTC on an Adafruit(tm) Adalogger board
#  which can keep time while the ESP32 is powered down. One could also use the
#  RTC inside the ESP32; it would be necessary to wait for the GPS to get a fix
#  before knowing where and when it is if the ESP32's RTC is used, and if the
#  signal isn't too good or the GPS has been off for a while, this can take 
#  many minutes.
#
#  @author Spluttflob
#  @date   2025-Nov-14 Modified heavily from Boatsie GPS
#  @date   2026-Jan-11 Moved stuff from GPS callback to task function
#  @copyright (c) 2025 by Spluttflob, released under the GPL V3

import as_GPS
import machine
import uasyncio as asyncio
import pcf8523


## The local offset from GMT in hours; PDT is -7 and PST is -8
LOCAL_OFFSET = -8

## The pin number of the ESP32 pin connected to the GPS RXD pin
GPS_RXD_PIN_NUM = const(14)

## The pin number of the ESP32 pin connected to the GPS TXD pin
GPS_TXD_PIN_NUM = const(32)

## The pin number of the GPS power pin
GPS_POWER_PIN_NUM = const(15)

## A pin object for the GPS power pin
gps_power_pin = machine.Pin(GPS_POWER_PIN_NUM, machine.Pin.OUT, value=0)

# ## The number of GPS fixes before the real-time clock is updated with GPS time.
# #  A typical GPS might be set up to deliver a fix every 5 seconds; do the math.
# GPS_FIXES_PER_RTC_UPDATE = 720

## An event which triggers the update of the RTCs when the GPS has a good fix.
gps_fix_ready = asyncio.Event()
gps_fix_ready.clear()

## Global reference to the ESP32 RTC, which other tasks will need to use
esp_rtc = machine.RTC()

## A variable which will be set True when a valid date and time from either the
#  PCF8523 RTC or the GPS has been put into the ESP32 RTC
valid_datetime = False

## Callback which runs for each valid GPS fix.
#  @param agps The GPS driver which calls this callback
#  @param *_ A list of other parameters, all of which are ignored
def gps_callback(agps, *_):
    global valid_datetime, gps_fix_ready

    # Update the RTCs with (Y, M, D, h, m, s) once there's a good fix
    # The year must be greater than 2024, else something is amiss
    day, mon, year = agps.date
    if year > 24:
        valid_datetime = True
        gps_fix_ready.set()


## Turn on the GPS module by setting the power control pin high. This
#  assumes that there's an N-channel MOSFET connecting the ground of the
#  GPS module to system ground. If no power pin has been specified, this
#  method does nothing.
def gps_on():
    if gps_power_pin is not None:
        gps_power_pin.value(1)


## Turn off the GPS module by setting the power control pin high. This
#  assumes that there's an N-channel MOSFET connecting the ground of the
#  GPS module to system ground.  If no power pin has been specified, this
#  method does nothing.
def gps_off():
    if gps_power_pin is not None:
        gps_power_pin.value(0)


## The GPS task function which creates the GPS object and processes data
#  strings from it to make information available to other tasks. The task
#  code doesn't do much because the action happens in callbacks in AS_GPS
#  @param i2c The I2C bus which is used to talk to the PCF8523 real-time clock
#  @param data_batch A data batch collector to which GPS data is put for saving
#         to the SD card and sending through MQTT if available
#  @param period_ms How often the GPS is turned on to find time and place
#  @param test_print Whether to print diagnostic data to the serial port
async def gps_task(i2c, data_batch, period_ms=600_000, test_print=False):

    global gps_fix_ready, valid_datetime

    ## The UART (serial port) connected to the GPS module. We use non-standard
    #  pins on the 1.3 board; it's just what has worked out. Because of the
    #  annoying RS-232 naming pin convention, the ESP32's TXD (tx) pin connects
    #  to the GPS's RXD pin and vice versa. For some reason, we need to ensure
    #  that the pin connected to GPS TXD is a regular input, or something
    #  (maybe a pullup?) prevents good GPS signals on the RS-232 line.
    pin_rx = machine.Pin(GPS_TXD_PIN_NUM, machine.Pin.IN)
    uart = machine.UART(2, 9600, bits=8, parity=None, stop=1, flow=0,
                        tx=GPS_RXD_PIN_NUM, rx=GPS_TXD_PIN_NUM)
    pin_rx.init(machine.Pin.IN)

    ## The stream reader which gets data from the UART connected to the GPS
    the_reader = asyncio.StreamReader(uart)

    ## The one and only GPS module that a cheap ocean wave radar needs
    the_gps = as_GPS.AS_GPS(the_reader, local_offset=LOCAL_OFFSET,
                            fix_cb=gps_callback)

    # Create an RTC driver if a PCF8523 seems to be on the I2C bus and copy the
    # time from the PCF8523 to the ESP32 RTC, because the PCF8523 has a battery
    if 0x68 in i2c.scan():
        pcf_rtc = pcf8523.PCF8523(i2c)
        year, mon, day, hrs, mns, scs = pcf_rtc.datetime
        esp_rtc.datetime([year, mon, day, 0, hrs, mns, scs, 0])
        valid_datetime = True
        print(f"Set ESP32 RTC to {esp_rtc.datetime()} from PCF8523")
    else:
        pcf_rtc = None

    while True:
        # Turn on the GPS, then wait until it has a good fix
        gps_on()

        await gps_fix_ready.wait()

        day, mon, year = the_gps.date
        hrs, mns, scs = the_gps.local_time
        year += 2000

        # Update the fancy PCF8523 RTC and the ESP32's built-in RTC
        print(f"Updating RTCs at {year}-{mon}-{day} {hrs}:{mns:02d}:{scs:02d}")
        esp_rtc.datetime([year, mon, day, 0, hrs, mns, scs, 0])
        if pcf_rtc is not None:
            pcf_rtc.datetime = [year, mon, day, hrs, mns, scs]
        valid_datetime = True

        # Put the GPS position into the data batch for sending and/or saving
        lat = the_gps.latitude()
        lon = the_gps.longitude()
        alt = the_gps.altitude
#         node = task_mqtt.ip_node
        fix_it = f"G{lat[1]},{lat[0]},{lon[1]},{lon[0]},{alt}\r\n"
        await data_batch.put(fix_it.encode())
        del fix_it

        # Turn off the GPS; we'll turn it on to get the next fix
        gps_fix_ready.clear()
        gps_off()
        the_reader.close()

        if test_print:
            hrs, mns, scs = the_gps.local_time
            print(f"GPS {hrs}:{mns:02d}:{scs:02d}, ", end='')
            print(f"TsF: {the_gps.time_since_fix():6d}, ", end='')
            print(f"V:{the_gps._valid:08b}, ", end='')
            print(f"{the_gps.latitude()} {the_gps.longitude()}")

        await asyncio.sleep_ms(period_ms)


# ================================ TEST CODE ===================================
if __name__ == "__main__":

    # Used so the GPS can update the PCF8523 real-time clock if it's there
    i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(23))
    print(f"I2C devices: " + ",".join(f"0x{item:x}" for item in i2c.scan()))

    # A task which echoes what the GPS sends, just for debugging
    def echo_task():
        print("GPS echo test task")
        gps_on()
        while True:
            if uart.any():
                try:
                    print(uart.read().decode(), end='')
                except UnicodeError:
                    print("*", end='')


    # Choose one of the two task functions, echo to see if the GPS module is
    # sending any data or the real GPS task which can print information from
    # the parser which makes sense of what the GPS module is reporting.
    async def main():
#         asyncio.create_task(echo_task())
        asyncio.create_task(gps_task(i2c, period_ms=10_000, test_print=True))

        await asyncio.sleep_ms(86_400_000)


    print("Beginning GPS parser test.")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Ctrl-C. ", end='')

    asyncio.new_event_loop()
    print("Test finished.")

