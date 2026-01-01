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
import periodic
from micropython import const # Constants use a little less memory
import uasyncio as asyncio    # Cooperative multitasking, Python style
import as_GPS                 # Asyncio driver for GPS parsing
import pcf8523                # Real-time clock on the Adalogger
import task_sd_card           # For storing data on the Adalogger
import task_gps               # Reads NMEA strings from a generic GPS module
import as_xm125_distance      # The radar module
import task_mqtt              # If messages are sent through Web in real time
import task_watchdog          # Monitors system and reboots if malfunctioning
import task_web               # Makes data files available on web pages


## How many milliseconds (approximately) between data points.
#  This probably ought to be at least 1000 until software has been improved.
#
#  WARNING: This rate must be faster than the rate at which the watchdog task
#  in task_watchdog.py checks the radar task flag, or the watchdog will reboot
#  the system unnecessarily.
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

## The I2C bus object used to talk to the radar sensor and PCF8523 RTC
i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(23))
print(f"I2C devices:", ",".join(f"0x{item:x}" for item in i2c.scan()))


## @brief   The function which manages taking and saving of radar data.
#  @details This task creates the radar driver and uses it to get data; it uses
#           the SD card task to provide the radar configuration (range, etc.)
#           and save the data. If MQTT is enabled, data will be collected into
#           messages to be sent to an MQTT broker.
#  @param   data_per_mqtt_msg The number of readings per MQTT message sent, or
#           None if we're not using MQTT at all
async def task_radar(data_per_mqtt_msg):

    # Set up a periodic scheduler object which minimizes clock drift
    perd = periodic.PeriodicDelay(period_ms=MS_PER_DATA_POINT)

    # Create the radar object. GPIO 27 is the WAKE pin of the radar
    radar = as_xm125_distance.XM125Distance(i2c, RADAR_WAKE_PIN_NUM)
    print(f"XM125 distance detector version {radar.version_string()}")

    # Try until we get valid parameters from the configuration dictionary
    while True:
        try:
            begin_dist_m = task_sd_card.the_SD_card.config["Beginning Distance"]
            end_dist_m = task_sd_card.the_SD_card.config["Ending Distance"]
            sensitivity = int(task_sd_card.the_SD_card.config["Sensitivity"])
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
        now_str = f"D{now[0]:04d}-{now[1]:02d}-{now[2]:02d}T{now[3]:02d}:{now[4]:02d}:{now[5]:02d}"

        a_line = ";".join((now_str, prt_str)) + "\r\n"
        print(a_line, end='')

        # Save to SD card the time and measurement using put_nowait() in case
        # something has gone wrong with the SD card -- we don't want to block
        # taking data (and sending it via MQTT if enabled) if the SD card has
        # a problem
        if task_sd_card.sd_queue.full():
            print("Problem: SD Card queue full")
        else:
            await task_sd_card.sd_queue.put(a_line)

#         try:
#             await task_sd_card.sd_queue.put_nowait(a_line + "\r\n")
#         except queue.QueueFull as qoops:
#             print(f"Problem sending to SD card queue: {qoops}")

        # If using MQTT for real-time cloud storage, assemble a larger string
        # with a number of readings to be sent as one MQTT message
        if data_per_mqtt_msg is not None:
            mqtt_string += a_line
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
                day, mon, year = task_gps.the_gps.date
                year += 2000
                hrs, mns, scs = task_gps.the_gps.local_time
                lat = task_gps.the_gps.latitude()
                lon = task_gps.the_gps.longitude()
                alt = task_gps.the_gps.altitude
                fix_it = f"G{year}-{mon}-{day},{hrs:02d}:{mns:02d}:{scs:02d},{lat[1]},{lat[0]},{lon[1]},{lon[0]},{alt},{task_mqtt.ip_node}"
                await task_sd_card.sd_queue.put(fix_it + "\r\n")
                await task_mqtt.mqtt_queue.put(fix_it)

        # We're having memory allocation errors on classic ESP32 sometimes. Try
        # to keep memory well managed to prevent such errors
        gc.collect()

        task_watchdog.radar_task_flag = True

        # Wait the correct duration so this task runs at the next sampling time
        await perd.wait_next()


## @brief   The function which creates and runs each of the task functions.
#  @details After getting the cotasks running, we enter an infinite loop to run
#           until somebody shuts off the power or the device is eaten by a
#           pelican.
async def main():
    global i2c

    # MQTT and web tasks are only used if the device will be on a LAN reporting
    # data in real time; if on solar at a remote site, comment out these tasks
    # Create MQTT task first and wait for the network to get going
    asyncio.create_task(task_mqtt.mqtt_task())
    while not task_mqtt.net_station or not task_mqtt.net_station.isconnected():
        await asyncio.sleep_ms(10)
    #    
    asyncio.create_task(task_mqtt.check_WiFi_task())
#     asyncio.create_task(task_web.file_server_task())

    # Wait for the WiFi using tasks to get stable before running other tasks. 
    await asyncio.sleep_ms(2_000)

    asyncio.create_task(task_sd_card.the_SD_card.task_function())
    asyncio.create_task(task_gps.gps_task(i2c))
    asyncio.create_task(task_radar(POINTS_PER_MQTT_MESSAGE))
    asyncio.create_task(task_watchdog.task_watchdog())

    while True:
        await asyncio.sleep_ms(1_000)


# Run the main function here. If we're doing a test, the program may be stopped
# by pressing Ctrl-C. For normal measurements, just leave it running for days,
# weeks, or months on end. An uncaught exception causes a file closing to save
# data to the SD card if possible, then a reboot to restart the whole program
print("Beginning Bogan Radar water level measurements.")
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Ctrl-C. ", end='')
except Exception as ohnoes:
    print(f"Uncaught exception {ohnoes}")
    utime.sleep_ms(500)
finally:
    task_sd_card.the_SD_card.close_data_file()
    asyncio.new_event_loop()
    print("Water level measurement test finished.")
