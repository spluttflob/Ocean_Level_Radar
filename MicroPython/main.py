## @file main.py
#  This is the main file of the ESP32 firmware for the Bogan Radar Project.
#  The ESP32 manages the collection of data from the XM125 radar, the
#  synchronization of the GPS and real-time clocks, and the saving of data to
#  an SD card.
#
#  The XM125 should be programmed with Acconeer's i2c_distance_detector
#  application, binary files for which are available in the XM125/A121
#  development support package from Acconeer. The version used for testing this
#  software is from acconeer_xm125_a121-v1_12_0.zip, and newer versions should
#  work. Look in the xm125/out/ folder for i2c_distance_detector.elf. The
#  STM32CubeProgrammer is recommended for programming the STM32 microcontroller
#  built into the XM125; using leftover ST-Link2 programmers from fried (or
#  working) Nucleo boards is economically efficient.
#
#  Repository:  https://github.com/spluttflob/Ocean_Level_Radar
#
#  @author Spluttflob
#  @date   2025-Nov-18  Original file
#  @copyright (c) 2025 by Spluttflob, released under the GPL V3

import gc
import utime
import machine
from os import sync           # To save files before rebooting
import uasyncio as asyncio    # Cooperative multitasking, Python style
import as_GPS                 # Asyncio driver for GPS parsing
import pcf8523                # Real-time clock on the Adalogger
import task_sd_card           # For storing data on the Adalogger
import task_gps               # Reads NMEA strings from a generic GPS module
import as_xm125_distance      # The radar module
import task_mqtt              # If messages are sent through Web in real time
from micropython import const # Constants use a little less memory


## How many milliseconds (approximately) between data points.
#  This probably ought to be at least 1000 until software has been improved.
MS_PER_DATA_POINT = 5000

## Save location, date, and time directly from GPS once per this many data lines
GPS_FIX_PER_SAVE = const(60)

## @brief   The number of data points per MQTT messsage.
#  @details This is used so we're not continuously spamming the MQTT broker,
#  instead giving it a larger message less frequently.
POINTS_PER_MQTT_MESSAGE = const(60)

## How many MQTT messages between MQTT "hello" messages that say what this data
#  is about. We may use public MQTT brokers, so anyone might read the data
MQTT_MSGS_PER_HELLO = 12

## A message sent infrequently to the MQTT broker explaining to the public what
#  this data is
MQTT_HELLO_MESSAGE = "# Public tide data (c) Spluttflob, CC-BY-NC-SA 3.0"

## The number of the pin used to wake up the radar and put it to sleep
RADAR_WAKE_PIN_NUM = const(27)

## The number of the pin used to activate the EZSBC battery voltage divider, or
#  0 if using another board such as Adafruit's that doesn't have this feature.
batt_v_ctl_pin = machine.Pin(2, machine.Pin.OUT, value=0)

## The number of the pin used to measure the battery voltage. It's set up with
#  the maximum attenuation so we can read high enough voltages.
batt_v_sensor = machine.ADC(machine.Pin(35), atten=machine.ADC.ATTN_11DB)

## An indicator LED used by the watchdog task to show things are OK (or not)
#  On the EZSBC board, the LED turns on when the pin is set low.
status_LED = machine.Pin(13, machine.Pin.OUT, value=1)

## The one SD card driver object for reading the configuration file and saving
#  data.
the_SD_card = task_sd_card.Radar_SD_Card(task_sd_card.SD_DIR + "/radar.cfg")

## A serial interface with which to receive data from the GPS module. The pin
#  numbers are for the Wave Radar board version 1.3.
uart = machine.UART(2, 9600, bits=8, parity=None, stop=1, flow=0, tx=14, rx=32)

## The one and only GPS module that a cheap ocean wave radar needs.
the_gps = as_GPS.AS_GPS(asyncio.StreamReader(uart),
                        local_offset=task_gps.LOCAL_OFFSET,
                        fix_cb=task_gps.gps_callback)

## The I2C bus object used to talk to the radar sensor and PCF8523 RTC
i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(23))
print(f"I2C devices:", ",".join(f"0x{item:x}" for item in i2c.scan()))


## @brief   Task function which monitors how the rest of the system is doing.
#  @details A watchdog timer is used so that if things really go to pieces, the
#           system will be restarted. The ESP32 watchdog timer is really strict
#           in that once it has been started, it cannot be stopped or changed.
async def task_watchdog():

    # Wait a minute before activating the watchdog timer; this allows someone
    # to Ctrl-C the system after reboot and halt main.py if there is a bug that
    # would otherwise cause infinitely repeating watchdog timer reboots.
    await asyncio.sleep_ms(60_000)

    doggo = machine.WDT(timeout=10_000)    # Timeout every 10 seconds

    while True:
#         # Battery voltage is being wonky on test machine; not using it for now
#         batt_v_ctl_pin.value(1)            # Turn on voltage divider, wait for
#         await asyncio.sleep_ms(10)         # it to settle
#         vbatt = batt_v_sensor.read_uv() * 2.0
#         batt_v_ctl_pin.value(0)

        status_LED.value(0)                # For the EZSBC feather, 0 is LED on
        await asyncio.sleep_ms(40)
        status_LED.value(1)

        if task_gps.valid_datetime:
            await asyncio.sleep_ms(4950)   # Blink every 5s if valid, 1s if not
        else:
            await asyncio.sleep_ms(950)
        doggo.feed()                       # Ensure the watchdog (timer) is fed


## @brief   The function which manages taking and saving of radar data.
#  @details This task creates the radar driver and uses it to get data; it uses
#           the SD card task to provide the radar configuration (range, etc.)
#           and save the data. If MQTT is enabled, data will be collected into
#           messages to be sent to an MQTT broker.
#  @param   data_per_mqtt_msg The number of readings per MQTT message sent, or
#           None if we're not using MQTT at all
async def task_radar(data_per_mqtt_msg):

    # Create the radar object. GPIO 27 is the WAKE pin of the radar
    radar = as_xm125_distance.XM125Distance(i2c, RADAR_WAKE_PIN_NUM)
    print(f"XM125 distance detector version {radar.version_string()}")

    # Try until we get valid parameters from the configuration dictionary
    while True:
        try:
            begin_dist_m = the_SD_card.config["Beginning Distance"]
            end_dist_m = the_SD_card.config["Ending Distance"]
            sensitivity = int(the_SD_card.config["Sensitivity"])
        except KeyError:
            print("Waiting for radar configuration")
            await asyncio.sleep_ms(5_000)
        else:
            begin_mm = int(begin_dist_m * 1000)
            end_mm = int(end_dist_m * 1000)
            break

    # Reset the radar, then set its range and sensitivity, then calibrate it
    await radar.reset()
    radar.set_range_mm(begin_mm, end_mm)
    radar.set_sensitivity(sensitivity)
    await radar.apply_config_and_calibrate()
    print(f"Radar range: {radar.get_range_mm()}", end='  ')
    print(f"Protocol status {radar.protocol_status():08x}", end='  ')
    print(f"Detector status {radar.detector_status():08x}")

    last_fix_count = GPS_FIX_PER_SAVE
    mqtt_string = ""
    mqtt_count = 0
    mqtt_hello_count = MQTT_MSGS_PER_HELLO

    while True:
        # Take measurement first; it might take some time
        prt_str = await radar.measure_to_sacsv()

        # Immediately after measurement, record time from real-time clock
        now = utime.localtime()
        now_str = f"D{now[3]:02d}:{now[4]:02d}:{now[5]:02d}"

        # Print and/or save to SD card the time and measurement
        await task_sd_card.sd_queue.put(";".join((now_str, prt_str)) + "\r\n")
        print(";".join((now_str, prt_str)))

        # If using MQTT for real-time cloud storage, assemble a larger string
        # with a number of readings to be sent as one MQTT message
        if data_per_mqtt_msg is not None:
            mqtt_string += ";".join((now_str, prt_str))
            mqtt_string += "\r\n"
            mqtt_count += 1
            if mqtt_count >= data_per_mqtt_msg:
                mqtt_count = 0
                await task_mqtt.mqtt_queue.put(mqtt_string)
                mqtt_string = ""
                # Occasionally send a hello message to public MQTT broker
                mqtt_hello_count += 1
                if mqtt_hello_count > MQTT_MSGS_PER_HELLO:
                    mqtt_hello_count = 0
                    await task_mqtt.mqtt_queue.put(MQTT_HELLO_MESSAGE)

        # If it's time to save a line of GPS data, do so and reset counter
        if task_gps.valid_datetime:
            last_fix_count += 1
            if last_fix_count > GPS_FIX_PER_SAVE:
                last_fix_count = 0
                day, mon, year = the_gps.date
                year += 2000
                hrs, mns, scs = the_gps.local_time
                lat = the_gps.latitude()
                lon = the_gps.longitude()
                alt = the_gps.altitude
                fix_it = f"G{year}-{mon}-{day},{hrs:02d}:{mns:02d}:{scs:02d},{lat[1]},{lat[0]},{lon[1]},{lon[0]},{alt}"
                await task_sd_card.sd_queue.put(fix_it + "\r\n")
                await task_mqtt.mqtt_queue.put(fix_it)

        await asyncio.sleep_ms(MS_PER_DATA_POINT)


## @brief   The function which creates and runs each of the task functions.
#  @details After getting the cotasks running, we enter an infinite loop to run
#           until somebody shuts off the power or the device is eaten by a
#           pelican.
async def main():
    global i2c

    asyncio.create_task(the_SD_card.task_function())
    asyncio.create_task(task_gps.gps_task(i2c))
    asyncio.create_task(task_radar(POINTS_PER_MQTT_MESSAGE))
    asyncio.create_task(task_mqtt.mqtt_task())
    asyncio.create_task(task_mqtt.check_WiFi_task())
    asyncio.create_task(task_watchdog())

    while True:
        await asyncio.sleep_ms(1_000)


# Run the main program here. If we're doing a test, the program may be stopped
# by pressing Ctrl-C. For normal measurements, just leave it running for days,
# weeks, or months on end. An uncaught exception causes a file closing to save
# data to the SD card, then a reboot to restart the whole program
print("Beginning Bogan Radar water level measurements.")
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Ctrl-C. ", end='')
except Exception as ohnoes:
    print("Uncaught exception {ohnoes}, rebooting!")
    the_SD_card.close_data_file()
    utime.sleep_ms(500)
finally:
    the_SD_card.close_data_file()
    asyncio.new_event_loop()
    print("Water level measurement test finished.")
    machine.reset()
