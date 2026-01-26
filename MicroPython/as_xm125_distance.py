## @file as_xm125_distance.py
#
#  A MicroPython driver for an Acconeer XM125 radar. This version runs in the
#  uasyncio environment, permitting cooperative multitasking with the GPS, SD
#  card, wireless interface, and whatever other tasks we need running to get
#  good data conveniently from Poseidon's domain.
#
#  @author Spluttflob
#  @date   2025-11-06 Original file, inspired by a ChatGPT session that didn't
#          give usable results and the Acconeer example files which are in C
#  @copyright (c) 2025 by Spluttflob, released under the GPL 3

import asyncio
import struct
from micropython import const
from queue import Queue                   # The uasyncio V3 version
from machine import Pin
from utime import sleep_ms


# Addresses of 'registers' in the I2C device from distance_reg_protocol.h
VERSION_ADDRESS = const(0)
PROTOCOL_STATUS_ADDRESS = const(1)
MEASURE_COUNTER_ADDRESS = const(2)
DETECTOR_STATUS_ADDRESS = const(3)
DISTANCE_RESULT_ADDRESS = const(16)
PEAK0_DISTANCE_ADDRESS = const(17)   # Use offsets to find the other ones
PEAK0_STRENGTH_ADDRESS = const(27)
START_ADDRESS = const(64)
END_ADDRESS = const(65)
MAX_STEP_LENGTH_ADDRESS = const(66)
CLOSE_RANGE_LEAKAGE_CANCELLATION_ADDRESS = const(67)
SIGNAL_QUALITY_ADDRESS = const(68)
MAX_PROFILE_ADDRESS = const(69)
THRESHOLD_METHOD_ADDRESS = const(70)
PEAK_SORTING_ADDRESS = const(71)
NUM_FRAMES_RECORDED_THRESHOLD_ADDRESS = const(72)
FIXED_AMPLITUDE_THRESHOLD_VALUE_ADDRESS = const(73)
THRESHOLD_SENSITIVITY_ADDRESS = const(74)
REFLECTOR_SHAPE_ADDRESS = const(75)
FIXED_STRENGTH_THRESHOLD_VALUE_ADDRESS = const(76)
MEASURE_ON_WAKEUP_ADDRESS = const(128)
COMMAND_ADDRESS = const(256)
APPLICATION_ID_ADDRESS = const(65535)

# Commands to be sent to the command register
CMD_RESET_MODULE = const(1381192737)
CMD_APPLY_CONFIG_AND_CALIBRATE = const(1)
CMD_MEASURE_DISTANCE = const(2)
CMD_APPLY_CONFIGURATION = const(3)
CMD_CALIBRATE = const(4)
CMD_RECALIBRATE = const(5)
CMD_ENABLE_UART_LOGS = const(32)
CMD_DISABLE_UART_LOGS = const(33)
CMD_LOG_CONFIGURATION = const(34)

## The number of milliseconds to wait before checking if the detector is busy
BUSY_WAIT_SLEEP_MS = const(10)

## The number of retries to wait for the detector to be not busy. Multiply by
#  BUSY_WAIT_SLEEP_MS to get the number of milliseconds we're willing to wait.
BUSY_WAIT_RETRIES = const(1000)

## The default address for the XM125 (address pin not connected)
XM125_I2C_ADDR = const(0x52)


## This class allows comparatively easy interaction with an Acconeer XM125 radar
#  module in a uasyncio environment. 
class XM125Distance:

    ## @brief   Initialize the XM125.
    #  @details Set up the XM125 to take measurements and awaken it.
    #  @param   i2c An I2C bus which has already been configured.
    #  @param   wakeup_pin_num The number of the pin used to awaken the XM125
    def __init__(self, i2c, wakeup_pin_num, addr:int=XM125_I2C_ADDR) -> None:
        self.i2c = i2c
        self.addr = addr

        # Configure wakeup pin as an output and turn the device on
        self.wakeup_pin = Pin(wakeup_pin_num, Pin.OUT)
        self.wake_up()
        sleep_ms(100)

        i2c_scan = self.i2c.scan()
        if not addr in i2c_scan:
            raise ValueError(f"XM125 not found at I2C address 0x{addr:X}")

        # We may have to reset the detector after startup?
        self.reset()
        sleep_ms(100);          # Can't use asyncio as this isn't an async def.
#         print("XM125 startup OK.")  ####################################################


    ## @brief Awaken the XM125 so it can take measurements.
    def wake_up(self):
        self.wakeup_pin.value(1)


    ## @brief Put the XM125 to sleep so it uses less power.
    def sleep(self):
        self.wakeup_pin.value(0)


    ## @brief Convert a 16-bit integer into a couple of bytes.
    def _u16_to_bytes_be(self, val: int) -> bytes:
        return struct.pack(">H", val & 0xFFFF)


    ## @brief Convert a 32-bit integer to a bunch of bytes.
    def _u32_to_bytes_be(self, val: int) -> bytes:
        return struct.pack(">I", val & 0xFFFFFFFF)


    ## @brief Convert a set of bytes into a 32-bit integer.
    def _bytes_to_u32_be(self, buf: bytes) -> int:
        return struct.unpack(">I", buf)[0]


    ## @brief   Convert a 32-bit register value to a 2's complement integer.
    #  @param   num The number to be converted
    #  @returns The converted number as a signed Python integer 
    def from_u32(self, num: int) -> int:
        if num > 2147483647:
            num -= 4294967296
        return num


    ## @brief Read register value over I2C
    # @param reg_addr The register address to read
    # @returns The data which has been read from the register
    def read_register(self, reg_addr: int) -> int:
        self.i2c.writeto(self.addr, self._u16_to_bytes_be(reg_addr), False)
        buf = self.i2c.readfrom(self.addr, 4)
        return self._bytes_to_u32_be(buf)


    ## @brief   Write an integer to a register in the XM125.
    #  @details The address and data are put together into 6 bytes that are
    #           then written to the I2C bus.
    def write_register(self, reg_addr: int, data: int) -> None:
        payload = self._u16_to_bytes_be(reg_addr) + self._u32_to_bytes_be(data)
        self.i2c.writeto(self.addr, payload)


    ## @brief   Send a command to the device.
    #  @details All 32 bits of the command integer are sent. Most commands are
    #           smaller integers but reset seems to be larger.
    def command(self, cmd: int) -> None:
        self.write_register(COMMAND_ADDRESS, cmd)


    ## @brief Read the XM125's version register and return its version string.
    def version_string(self) -> str:
        ver = self.read_register(VERSION_ADDRESS)
        return f"{(ver >> 16) & 0xFFFF}.{(ver >> 8) & 0xFF}.{ver & 0xFF}"


    ## @brief Get the contents of the protocol status register.
    #
    def protocol_status(self):
        return self.read_register(PROTOCOL_STATUS_ADDRESS)


    ## @brief   Get the contents of the detector status register.
    #  @details This register contains bits showing whether sensor operations
    #           are working and if the detector is busy.
    def detector_status(self) -> int:
        return self.read_register(DETECTOR_STATUS_ADDRESS)


    ## @brief   Check if the detector is busy.
    #  @returns True if the detector is busy and False if it isn't busy.
    def det_busy(self) -> bool:
        return bool(self.read_register(DETECTOR_STATUS_ADDRESS) & 0x80000000)


    ## @brief   Check if any detector error bits are set.
    #  @returns True if an error bit is set and False if not.
    def det_error(self) -> bool:
        return bool(self.read_register(DETECTOR_STATUS_ADDRESS) & 0xFFFF0000)


    ## @brief   Reset the detector, then wait until it's no longer busy.
    async def reset(self) -> None:
        self.command(CMD_RESET_MODULE)
        await self.busy_wait()


    ## @brief   Wait until the detector is not busy.
    async def busy_wait(self) -> None:
        tries = 0
        while True:
            await asyncio.sleep_ms(BUSY_WAIT_SLEEP_MS)
            try:
                if not self.det_busy():   # Also may be waiting for I2C to work
                    break
            except OSError:
                pass
            tries += 1
            if tries > BUSY_WAIT_RETRIES:
                raise RuntimeError("Timeout waiting for XM125")


    ## @brief Set measurement range in millimeters.
    def set_range_mm(self, start_mm: int = 250, end_mm: int = 3000) -> None:
        self.write_register(START_ADDRESS, start_mm)
        self.write_register(END_ADDRESS, end_mm)


    ## @brief Get the starting and ending measurement range in millimeters.
    def get_range_mm(self) -> tuple(int, int):
        start = self.read_register(START_ADDRESS)
        end = self.read_register(END_ADDRESS)
        return start, end


    ## @brief   Set the sensitivity of the distance detector.
    def set_sensitivity(self, level: int = 500) -> None:
        self.write_register(THRESHOLD_SENSITIVITY_ADDRESS, level)



    ## @brief   Tell the detector to apply its configuration, then wait until
    #           has finished doing so.
    async def apply_configuration(self) -> None:
        print("Apply config...", end='')                  #############################
        self.command(CMD_APPLY_CONFIGURATION)
        await self.busy_wait()
        print("done.")                                    #############################


    ## @brief   Tell the detector to go calibrate itself, then wait for it.
    async def calibrate(self) -> None:
        print("Calibrating...", end='')                   #############################
        self.command(CMD_CALIBRATE)
        await self.busy_wait()
        print("done.")                                    #############################


    ## @brief   Tell the detector to apply its configuration and calibrate
    #           itself, then wait until it's not busy doing so.
    async def apply_config_and_calibrate(self) -> None:
        self.command(CMD_APPLY_CONFIG_AND_CALIBRATE)
        await self.busy_wait()


    ## @brief   Measure one distance and return information about the result.
    #  @details The data from the measurement is available through calls to
    #           get_distances() and get_strengths().
    #  @returns A tuple of the number of distances to objects found,
    #           whether something may have been seen closer than the near limit,
    #           whether calibration is now needed, and
    #           whether an error condition exists after the measurement
    # 
    #  Bitfield                Pos   Width  Mask
    #  NUM DISTANCES           0     4      0x0000000F
    #  NEAR START EDGE         8     1      0x00000100
    #  CALIBRATION NEEDED      9     1      0x00000200
    #  MEASURE_DISTANCE_ERROR  10    1      0x00000400
    #  TEMPERATURE             16    16     0xFFFF0000  (not very accurate)
    async def measure_distance(self) -> tuple(int, bool, bool, bool):
        self.command(CMD_MEASURE_DISTANCE)
        await self.busy_wait()
        if self.det_error():
            print(f"Detector error, status {self.detector_status():08x}")  ###########
        det_res = self.read_register(DISTANCE_RESULT_ADDRESS)
#         print(f"Detector result: {det_res:08x}", end=' ')
        num_distances = det_res & 0x0F
        near_start_edge = bool(det_res & 0x0100)
        calib_needed = bool(det_res & 0x0200)
        error = bool(det_res & 0x0400)

        # If calibration is needed, do it now
        if calib_needed:
            print("Recalibrating radar...", end='')        #################################
            self.command(CMD_CALIBRATE)
            await self.busy_wait()
            print("done.")                                 #################################

        return (num_distances, near_start_edge, calib_needed, error)        


    ## @brief   Get the most recently measured distances in a list.
    #  @returns A list containing the distances to detected objects
    def get_distances(self, num_distances: int) -> list:
        dists = []
        for index in range(num_distances):
            a_dist = self.read_register(PEAK0_DISTANCE_ADDRESS + index)
            dists.append(a_dist)
        return dists


    ## @brief   Get the signal strengths for measured distances.
    #  @returns A list containing the strengths of signals from the detected
    #           objects.
    def get_strengths(self, num_distances: int) -> list:
        strengths = []
        for index in range(num_distances):
            a_strn = self.read_register(PEAK0_STRENGTH_ADDRESS + index)
            strengths.append(a_strn)
        return strengths
    

    ## @brief   Make a measurement and put the results into a string that can
    #           be displayed, saved in a file, etc.
    #  @details The string is in Semicolon-And-Comma-Separated-Value format
    #           (yes, I just made that up). Distance and strength measurements
    #           are separated by commas, and distance,strength pairs are
    #           separated by semicolons.
    async def measure_to_sacsv(self) -> bytes:
        n_dist, nearer, calib, error = await self.measure_distance()
        if n_dist == 0:
            return b"NR"
        else:
            ret_str = ";".join([f"{dist / 1000.0},{self.from_u32(sgth) / 1000.0:.1f}"
                                for dist, sgth
                                in zip(self.get_distances(n_dist),
                                       self.get_strengths(n_dist))])
        return ret_str.encode()


if __name__ == "__main__":

    import machine
    import utime

    print("Testing the XM125 radar module")

    # Create an I2C bus object to talk to the sensor
    i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(23))


    # A task which echoes what the GPS sends, just for debugging
    def task_radar():
        radar = XM125Distance(i2c, 27)
        print(f"I2C devices: " + ",".join(f"0x{item:x}" for item in i2c.scan()))
        print(f"XM125 distance detector version {radar.version_string()}")

        print("Reset...", end='')
        await radar.reset()
        print("done.")
        radar.set_range_mm(300, 3000)
        radar.set_sensitivity(600)
        await radar.apply_config_and_calibrate()
        print(f"Radar range: {radar.get_range_mm()}")
        print(f"Protocol status {radar.protocol_status():08x}")
        print(f"Detector status {radar.detector_status():08x}")

        while True:
            prt_str = await radar.measure_to_sacsv()
            print(prt_str)

            await asyncio.sleep_ms(5000)


    # Get the task function running, then twiddle thumbs ad infinitum.
    async def main():

        asyncio.create_task(task_radar())

        while True:
            await asyncio.sleep_ms(3600)


    print("Beginning XM125 RADAR test.")
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Ctrl-C. ", end='')

    asyncio.new_event_loop()


    print("Test done.")


