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
#  @copyright (c) 2025 by Spluttflob, released under the GPL V3

from utime import localtime
import uasyncio as asyncio
from machine import SDCard, Pin
from os import mount, umount, listdir, stat, sync
from queue import Queue
import databatch
import task_gps
import task_watchdog


## The default configuration of the radar, to be used if it's not possible to
#  read a configurartion file from the SD card.
DEFAULT_CONFIG = \
    {"Site Name":          "Testing",
     "Beginning Distance":  1.0,
     "Ending Distance":     10.0,
     "Sensitivity":         500,
     "Time Per Point":      5.0,
     "Awake Time":          0.0,
     "Cycle Time":          0.0}

## This queue holds strings of text to be written to the SD card. The 'maxsize'
#  parameter is the maximum number of items that may be stored in the queue;
#  a full queue can block writing, which is quite bad and should be prevented.
sd_queue = Queue(maxsize=100)

## How many lines are written to the SD card before we reopen the data file to
#  ensure that data is actually written to the card, not just held in a memory
#  buffer to be written when the file is closed
SD_LINES_PER_SYNC = 720

## The directory at which the SD card is mounted.
SD_DIR = "/sd"


## Class which encapsulates the data and methods needed to manage an SD card
#  in a boat navigation system.
class Radar_SD_Card:

    ## The most recently used name of a data file. We can begin automatically
    #  making file names with this one so we don't repeatedly try file names
    #  that have been used while this program was running.
    recent_data_file_name = ""


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
    def __init__(self, config_file_name, sd_slot=3, sck_pin=5, mosi_pin=18,
                 miso_pin=19, cs_pin=33):

        ## A reference to the one and only SD card object
        self.sdcard = SDCard(slot=sd_slot, sck=Pin(sck_pin), mosi=Pin(mosi_pin),
                             miso=Pin(miso_pin), cs=Pin(cs_pin))

        ## The name of the file which holds configuration information. It
        #  should generally be a full pathname such as @c /sd/config.txt
        self.config_file_name = config_file_name 

        ## The name of the data file in which data is currently being stored
        self.data_file_name = None

        ## A list containing mark data; it will contain contents read from a
        #  file on the SD card.
        self.config = {}

        ## Finite state machine state used in the task function. Also used to
        #  tell if the SD card can be written.
        self.state = 0

        ## The data file to which to save location, speed, etc.
        self.data_file = None


    ## Read a file containing the configuration of the radar system.
    #  This function should only be called when the program starts or an SD
    #  card is inserted into the socket; the operation is all done at once so
    #  that another task can't read a partially edited configuration.
    #
    #  Format: The configuration file looks like a dictionary with comments:
    #          Beginning Distance:  1.0        #  Beginning distance (m)
    #          Time Per Point:      5.0        #  Seconds between data points
    #          ...etc...
    def read_config_file(self):

        try:
            with open(self.config_file_name, mode='r') as cfile:
                lines = cfile.readlines()
        except OSError:
            self.config = DEFAULT_CONFIG.copy()
            print(f"Unable to open '{self.config_file_name}'")
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
                        self.config[key] = value


    ## Show the configuration in a somewhat readable way.
    def show_config(self):
        print("\r\nItem                     Value")
        print("----                     -----")
        for key, value in self.config.items():
            print(f"{key:24s} {value}")


    ## Write the configuration into a data file in an easy-ish-to-read format.
    #  A data file must be open as self.data_file.
    def write_config(self):
        if self.data_file:
            for key, value in self.config.items():
                self.data_file.write(f"{key:24s} {value}\r\n")


    ## Open a data file whose name is based on the current date and time.
    #  This is a critical operation, so keep trying until the file can be
    #  opened, giving other tasks a chance to run in the meantime.
    async def open_data_file(self):
        while True:
            year, mon, day, wd, hrs, mns, scs, us = task_gps.esp_rtc.datetime()
            self.data_file_name = SD_DIR + \
                f"/R_{mon:02d}-{day:02d}_{hrs:02d}{mns:02d}{scs:02d}.sacsv"
            try:
                self.data_file = open(self.data_file_name, 'a')
            except OSError as oops:
                print(f"Error {oops} opening {self.data_file_name}")
                self.data_file = None
                await asyncio.sleep_ms(100)
            else:
                self.write_config()
                break


    ## Close the data file.
    #  Not sure if we have to unmount the card to safely flush data to it?
    def close_data_file(self):
        if self.data_file:
            self.data_file.close()


    ## Close and reopen the data file to force data to be written to the card.
    #  If something goes wrong, retry indefinitely while giving other tasks a
    #  chance to run.
    async def reopen_data_file(self):
        while True:
            try:
                self.data_file.close()
            except OSError:
                await asyncio.sleep_ms(100)
            else:
                break
        while True:
            try:
                self.data_file = open(self.data_file_name, 'a')
            except OSError:
                await asyncio.sleep_ms(100)
            else:
                break
        print(f"File {self.data_file_name} reopened")


    ## Run a task which reads a configuration from an SD card and saves
    #  data to a file on the SD card.
    #
    #  For ESP32 Feather and logger wing, SCK=5, MOSI=18, MISO=19, CS=33
    #
    #  States:
    #    * 0 - No SD card has been detected, check every 10s for one
    #    * 1 - SD card detected; open it and read configuration file
    #    * 2 - Wait for date and time to be available, then open data file
    #    * 3 - SD card present and open; save data when available
    #
    #  @param data_batch A data batch holder that keeps sets of data to save
    #  @param skip_datetime_check For testing, don't wait for valid date/time
    async def task_function(self, data_batch, skip_datetime_check=False):

        while True:
            # No matter the state, we must feed the watchdog task or be rebooted
#             task_watchdog.sd_card_task_flag = True

            if self.state == 0:               # Check if a card is present
                try:
                    mount(self.sdcard, SD_DIR)
                except OSError as oops:       # Probably means no card, so wait
                    print(f"No SD card, error '{oops}'")
                    await asyncio.sleep_ms(10_000)
                else:
                    print(f"Files in {SD_DIR}: {listdir(SD_DIR)}")
                    self.state = 1            # We've found a card
                    await asyncio.sleep_ms(10)

            elif self.state == 1:             # Card mounted; read config. file
                try:
                    self.read_config_file()
                    self.show_config()
                except OSError:
                    self.state = 0
                    await asyncio.sleep_ms(1000)
                else:
                    self.state = 2
                    await asyncio.sleep_ms(500)

            elif self.state == 2:             # Write batches of data when ready
                try:
                    to_write = await data_batch.get()
                    await self.open_data_file()
                    self.data_file.write(to_write)
                    self.close_data_file()
                    data_batch.done()
                except OSError as foops:
                    print(f"Problem saving to data file: {foops}")
                    try:
                        umount(SD_DIR)
                    except OSError:
                        pass
                    finally:
                        self.state = 0          # Where we try to re-mount
                await asyncio.sleep_ms(10)


## The one SD card driver object which will be accessed from other tasks in
#  order to get a configuration and save data.
the_SD_card = Radar_SD_Card(SD_DIR + "/radar.cfg")


# --------------------------------- Test Code ----------------------------------
if __name__ == "__main__":

    import utime

    print(f"Task SD Card Test, asyncio {'.'.join(map(str, asyncio.__version__))}")

    # Simulate a task sending data to be recorded; just use time from the RTC.
    # We're going to beat the heck out of the SD card to see if we can reproduce
    # errors that have been causing the wave radar to stop working
    async def sim_data_task():
        count = 0
        while True:
            now = utime.localtime()
            now_str = f"{now[3]:02d}:{now[4]:02d}:{now[5]:02d}\r\n"
            await sd_queue.put(now_str)
            count += 1
            if count % 10 == 0:
                print(now_str, end='')
            await asyncio.sleep_ms(100)


    # Run the task function as a test.
    async def main():
        asyncio.create_task(the_SD_card.task_function(skip_datetime_check=True))
        asyncio.create_task(sim_data_task())

        while True:
            await asyncio.sleep_ms(1_000)

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Ctrl-C. ", end='')

    the_SD_card.close_data_file()

    asyncio.new_event_loop()
    print("\r\nTest finished.")

