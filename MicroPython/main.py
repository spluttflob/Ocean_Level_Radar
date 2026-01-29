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
from machine import Pin, I2C  # Also ADC if measuring battery voltage
import periodic
from micropython import const # Constants use a little less memory
import uasyncio as asyncio    # Cooperative multitasking, Python style
import databatch              # Store batches of data to be saved and/or sent
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

## Save location from GPS once per this many data lines
GPS_LINE_PERIOD = const(60)

## @brief   The number of data points per MQTT messsage.
#  @details This is used so we're not continuously spamming the MQTT broker,
#  instead giving it a larger message less frequently.
POINTS_PER_DATA_BATCH = const(60)

## @brief   The maximum number of items in the DataBatch queue.
#  @details The queue will keep readings in case the SD card or MQTT system are
#  slowed for some reason, but too large a queue may run out of memory.
MAX_DATA_QUEUE_SIZE = 10

## How many data batches between MQTT "hello" messages that say what this data
#  is about. We may use public MQTT brokers, so anyone might read the data
BATCHES_PER_HELLO = 12

## A message sent infrequently to the MQTT broker explaining to the public what
#  this data is
HELLO_MESSAGE = b"# Public tide data (c) Spluttflob, CC-BY-NC-SA 3.0"

## The number of the pin used to wake up the radar and put it to sleep
RADAR_WAKE_PIN_NUM = const(27)

# ## The number of the pin used to activate the EZSBC battery voltage divider, or
# #  0 if using another board such as Adafruit's that doesn't have this feature.
# batt_v_ctl_pin = Pin(2, Pin.OUT, value=0)

# ## The number of the pin used to measure the battery voltage. It's set up with
# #  the maximum attenuation so we can read high enough voltages.
# batt_v_sensor = ADC(Pin(35), atten=ADC.ATTN_11DB)

## The I2C bus object used to talk to the radar sensor and PCF8523 RTC
i2c = I2C(0, scl=Pin(22), sda=Pin(23))
print(f"I2C devices:", ",".join(f"0x{item:x}" for item in i2c.scan()))


## @brief   The function which manages taking and saving of radar data.
#  @details This task creates the radar driver and uses it to get data; it uses
#           the SD card task to provide the radar configuration (range, etc.)
#           and save the data. If MQTT is enabled, data will be collected into
#           messages to be sent to an MQTT broker.
#  @param   data_batch A data collection object which saves sets of readings to
#           be written to the SD card or sent via MQTT
async def task_radar(data_batch):

    # Set up a periodic scheduler object which minimizes clock drift
    perd = periodic.PeriodicDelay(period_ms=MS_PER_DATA_POINT)

    # Create the radar object. GPIO 27 is the WAKE pin of the radar
    radar = as_xm125_distance.XM125Distance(i2c, RADAR_WAKE_PIN_NUM)
    print(f"XM125 distance detector version {radar.version_string()}")

    # Try until we get valid parameters from the configuration dictionary
    while True:
        try:
            begin_dist_m = task_sd_card.the_configuration["Beginning Distance"]
            end_dist_m = task_sd_card.the_configuration["Ending Distance"]
            sensitivity = int(task_sd_card.the_configuration["Sensitivity"])
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

    gps_count = GPS_LINE_PERIOD * 4 // 5
    hello_count = BATCHES_PER_HELLO

    while True:
        # Take measurement first; it might take some time
        prt_str = await radar.measure_to_sacsv()

        # Immediately after measurement, record time from real-time clock
        now = utime.localtime()
        now_str = f"D{now[0]:04d}-{now[1]:02d}-{now[2]:02d}T{now[3]:02d}:{now[4]:02d}:{now[5]:02d}"

        a_line = b";".join((now_str.encode(), prt_str))
        del now_str, prt_str
        print(a_line, "|", gc.mem_free())
        a_line += b"\r\n"

        # Send the line of data to the data batch, which will pass batches of
        # data to the tasks that store and/or send the data
        await data_batch.put(a_line)
        del a_line
        if hello_count > BATCHES_PER_HELLO:
            hello_count = 0
            await data_batch.put(HELLO_MESSAGE)

        # We're having memory allocation errors on classic ESP32 sometimes. Try
        # to keep memory well managed to prevent such errors
        gc.collect()

        # Keep the watchdog task happy so it doesn't reboot the processor
        task_watchdog.radar_event.set()

        # Wait the correct duration so this task runs at the next sampling time
        await perd.wait_next()


## @brief   The function which creates and runs each of the task functions.
#  @details After getting the cotasks running, we enter an infinite loop to run
#           until somebody shuts off the power or the device is eaten by a
#           pelican.
async def main():
    global i2c

    # Create a DataBatch object and two consumers that get the data. The
    # DataBatch should discard data if the queue becomes full because of
    # one stuck consumer; the other consumer will still get all the data
    batch = databatch.DataBatch(POINTS_PER_DATA_BATCH,
                                maxsize=MAX_DATA_QUEUE_SIZE, drop_old=True)
    consumer_A = batch.register()
    consumer_B = batch.register()

    tasks = []
    tasks.append(asyncio.create_task(task_sd_card.task_SD_Card(consumer_A)))
    tasks.append(asyncio.create_task(task_mqtt.mqtt_task(consumer_B)))
    tasks.append(asyncio.create_task(task_gps.gps_task(i2c, batch)))
    tasks.append(asyncio.create_task(task_radar(batch)))
    tasks.append(asyncio.create_task(task_watchdog.task_watchdog()))
    asyncio.create_task(task_web.file_server_task())

    gc.collect()
    print(f"After tasks RAM free: {gc.mem_free()}")

    # Using asyncio.gather() allows us to catch and deal with exceptions in
    # each task; otherwise one task may quit while others just keep going
    while True:
        await asyncio.sleep_ms(1000)

    try:
        await asyncio.gather(*tasks)
    except MemoryError as oops:
        print(f"FAIL: {oops}")
        machine.reset()


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
    print(f"Uncaught exception: {ohnoes}")
    utime.sleep_ms(500)
finally:
    asyncio.new_event_loop()
    print("Water level measurement test finished.")
