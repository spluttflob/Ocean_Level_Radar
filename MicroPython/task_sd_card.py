## @file task_sd_card.py
#  This file contains a uasyncio task which reads and writes data to and from
#  a SD card.
#
#  This version is for the Bogan Radar Project. It is intended to save readings
#  of ocean height, dates and times, and auxiliary information to files on the
#  SD card.
#
#  @author Spluttflob
#  @date   2025-11-10  Modified from a nautical data program by Spluttflob
#  @date   2026-01-11  Removed class, just made a module; use with file opens
#  @copyright (c) 2025-2026 by Spluttflob, released under the GPL V3

from utime import localtime
import uasyncio as asyncio
from machine import SDCard, Pin
from os import mount, umount, listdir, stat, sync
from gc import mem_free
import databatch
import task_watchdog


## The name of the file that holds the radar device configuration.
#  The SD card directory will be prepended onto this name.
CONFIG_FILE_NAME = "/radar.cfg"

## The directory at which the SD card is mounted.
SD_DIR = "/sd"

## The configuration configuration of the radar. The default configuration will
#  be used if it's not possible to read a configurartion file from the SD card.
the_configuration = \
    {"Site Name":          "test0",
     "Beginning Distance":  1.0,
     "Ending Distance":     8.0,
     "Sensitivity":         500,
     "Time Per Point":      5.0,
     "Awake Time":          0.0,
     "Cycle Time":          0.0}

## The name of the data file in which data is currently being stored.
#  This name might be changed to reflect a time and date when it is opened.
data_file_name = None


## Initialize the SD card object, but don't attempt to start the card yet.
#  The default slot and pin numbers are for an ESP32 Feather (from Adafruit
#  or EZSBC) and an Adafruit datalogger FeatherWing.
#  @param config_file_name The full pathname of the mark data file, starting
#         with the directory where the SD card was mounted, such as "/sd/"
#  @param sd_slot The SD card slot number, default 3 for ESP32 Featherwing
#  @param sck_pin The SPI SCK pin number, default 5
#  @param mosi_pin The SPI MOSI pin number, default 18
#  @param miso_pin The SPI MISO pin number, default 19
#  @param cs_pin The SPI CS pin number, default 33
def init(sd_slot=3, sck_pin=5, mosi_pin=18, miso_pin=19, cs_pin=33):

    ## A reference to the one and only SD card object
    the_sd_card = SDCard(slot=sd_slot, sck=Pin(sck_pin), mosi=Pin(mosi_pin),
                         miso=Pin(miso_pin), cs=Pin(cs_pin))
    return the_sd_card


## Read a file containing the configuration of the radar system.
#  This function should only be called when the program starts or an SD
#  card is inserted into the socket; the operation is all done at once so
#  that another task can't read a partially edited configuration.
#
#  Format: The configuration file looks like a dictionary with comments:
#          Beginning Distance:  1.0        #  Beginning distance (m)
#          Time Per Point:      5.0        #  Seconds between data points
#          ...etc...
def read_config_file():

    global the_configuration

    try:
        with open(CONFIG_FILE_NAME, mode='r') as cfile:
            lines = cfile.readlines()
    except OSError:
        print(f"Unable to open '{CONFIG_FILE_NAME}'")
    else:
        for line in lines:
            if line:
                try:
                    no_comment = line.split('#')
                    colony = no_comment[0].split(':')
                    key = colony[0].strip()
                    val_str = colony[1].strip()
                    try:
                        value = float(val_str)
                    except ValueError:
                        value = val_str
                except (IndexError, ValueError):
                    pass
                else:    
                    the_configuration[key] = value


## Put the configuration into a string in a somewhat readable way.
def config_str():
    conf_str = "Item                     Value\r\n"
    conf_str += "----                     -----\r\n"
    for key, value in the_configuration.items():
        conf_str += f"{key:24s} {value}\r\n"
    return conf_str


## Write the configuration into a data file in an easy-ish-to-read format.
#  The data file must be open to allow writing.
def write_config(data_file):
    if data_file:
        try:
            for key, value in the_configuration.items():
                data_file.write(f"{key:24s} {value}\r\n")
        except OSError as ohpoop:
            print(f"Error writing configuration: {ohpoop}")


## Create a file name from the date and time read from the ESP32's RTC. If a
#  reasonable date hasn't been put into the RTC yet, wait a second and try
#  again.
async def file_name_from_date():
    global data_file_name

    while True:
        year, mon, day, hrs, mns, scs, wd, us = localtime()
        if year > 2024:
            data_file_name = SD_DIR + \
                f"/R_{mon:02d}-{day:02d}_{hrs:02d}{mns:02d}{scs:02d}.sacsv"
            break
        else:
            print(f"Bad local time: {localtime()}")
            await asyncio.sleep_ms(1_000)


## Run a task which reads a configuration from an SD card and saves
#  data to a file on the SD card. The file is opened and closed for each
#  batch of data to reduce the chance of data corruption when power is lost
#  with the file open.
#
#  For ESP32 Feather and Adalogger wing, SCK=5, MOSI=18, MISO=19, CS=33
#
#  States:
#    * 0 - No SD card has been detected, check every 10s for one
#    * 1 - SD card detected; open it and read configuration file
#    * 2 - SD card present and open; save data when available
#
#  @param consumer A DataBatch connection that supplies batches of strings of
#         data to be written to this SD card
async def task_SD_Card(consumer):

    state = 0

    the_sd_card = init()

    while True:
        # The starting state. Check if an SD card is present by trying to
        # mount it; if we can't, wait for a card to be plugged in.
        if state == 0:
            try:
                mount(the_sd_card, SD_DIR)
            except OSError as oops:       # Probably means no card, so wait
                print(f"No SD card, error '{oops}'")
                await asyncio.sleep_ms(5_000)
            else:
                print(f"Files in {SD_DIR}: {listdir(SD_DIR)}")
                state = 1                 # We've found a card
                await asyncio.sleep_ms(10)
            finally:
                task_watchdog.sd_card_event.set()

        # Now that a card has been mounted, read the configuration file and
        # write configuration information to the data file
        elif state == 1:
            try:
                read_config_file()
                print(config_str(), end='')
                await file_name_from_date()
                with open(data_file_name, 'a') as da_file:
                    da_file.write(config_str())
            except OSError:
                state = 0
                await asyncio.sleep_ms(1000)
            else:
                state = 2
                await asyncio.sleep_ms(500)

        # Try to get and write a batch of data. First wait for the batch to
        # be ready. Then try to open the file, write data, and close the
        # file. If saving data didn't work, give up on writing this batch
        # (to prevent getting stuck) and go to state 0 to try to remount the
        # SD card so the next data batch can be saved. 
        elif state == 2:
            to_write = await consumer.get()

            task_watchdog.sd_card_event.set()    # So watchdog won't reset ESP32

            try:
                with open(data_file_name, 'a') as da_file:
                    da_file.write(to_write)
            except OSError as foops:
                print(f"Problem saving to data file: {foops}")
                try:
                    umount(SD_DIR)
                except OSError:             # SD card not present or working
                    pass
                finally:
                    state = 0               # Where we try to re-mount
            finally:
                del to_write    # So memory can be reused while we wait for data

            await asyncio.sleep_ms(50)


# --------------------------------- Test Code ----------------------------------
#
# NOT WORKING RIGHT NOW: Needs to be updated to use the most recent databatch

if __name__ == "__main__":

    ## Create some data (just counting numbers and text) and put it in the queue
    async def test_data_task(a_batch):
        count = 0
        while True:
            send_str = f"#{count}: {gc.mem_free()} bytes. "
            count += 1
            await a_batch.put(send_str.encode())      # Save bytes, not Unicode
            await asyncio.sleep_ms(1000)


    ## Another task which prints periodically to verify that the SD card task
    #  hasn't blocked all tasks from running.  Hopefully.
    async def other_task(a_consumer):
        while True:
            text = await a_consumer.get()
            print(f"{text} RAM: {gc.mem_free()}.  ")


    ## Get the task functions running, then twiddle thumbs until Control-C'ed.
    async def main():

        # Create a DataBatch object and two consumers that get the data. The
        # DataBatch should discard data if the queue becomes full because of
        # one stuck consumer; the other consumer will still get all the data
        batch = databatch.DataBatch(5, maxsize=10, drop_old=True)
        consumer_A = batch.register()
        consumer_B = batch.register()

        # Create a list of tasks which asyncio will run concurrently
        tasks = []
        tasks.append(asyncio.create_task(test_data_task(batch)))
        tasks.append(asyncio.create_task(task_SD_Card(consumer_A)))
        tasks.append(asyncio.create_task(other_task(consumer_B)))

        # Using asyncio.gather() allows us to catch and deal with exceptions in
        # each task; otherwise one task may quit while others just keep going
        try:
            await asyncio.gather(*tasks)
        except MemoryError as oops:
            print(f"FAIL: {oops}")
            machine.reset()


    print("Testing SD card for Bogan Radar")
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Control-C ", end='')

    finally:
        asyncio.new_event_loop()             # Clear retained state
        print("Exiting")



#     import utime
# 
#     the_queue = queue.Queue(maxsize=3)
# 
#     print(f"Task SD Card Test, asyncio {'.'.join(map(str, asyncio.__version__))}")
# 
#     # Simulate a task sending data to be recorded; just use time from the RTC.
#     # We're going to beat the heck out of the SD card to see if we can reproduce
#     # errors that have been causing the wave radar to stop working
#     async def sim_data_task(a_queue):
#         count = 0
#         while True:
#             now = utime.localtime()
#             now_str = f"{now[3]:02d}:{now[4]:02d}:{now[5]:02d},{mem_free()}\r\n"
#             count += 1
#             if count % 25 == 0:
#                 print(now_str, end='')
#             a_queue.put(now_str)
#             await asyncio.sleep_ms(200)
# 
# 
#     # Run the task function as a test.
#     async def main():
#         asyncio.create_task(task_SD_Card(the_queue))
#         asyncio.create_task(sim_data_task(the_queue))
# 
#         while True:
#             await asyncio.sleep_ms(1_000)
# 
#     try:
#         asyncio.run(main())
# 
#     except KeyboardInterrupt:
#         print("Ctrl-C. ", end='')
# 
#     asyncio.new_event_loop()
#     print("\r\nTest finished.")

