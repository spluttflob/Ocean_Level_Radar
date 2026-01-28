## PCF8523 Real Time Clock (RTC) module for MicroPython
#
#  Nov. 2025 Spluttflob made minor changes to MicroPython version, added tests
#  Jun. 2020 Meurisse D. for MCHobby (shop.mchobby.be) ported to MicroPython
#  Nov. 2016 Philip R. Moyer and Radomir Dopieralski for Adafruit Industries
#            - original version for CircuitPython
#
#  - Milliseconds are not supported by this RTC.
#  - Datasheet: http://cache.nxp.com/documents/data_sheet/PCF8523.pdf
#  - based on https://github.com/adafruit/Adafruit_CircuitPython_PCF8523.git
#
# The MIT License (MIT)
#
# Original Arduino program Copyright (c) 2016 Philip R. Moyer and Radomir
# Dopieralski for Adafruit Industries.
#
# Code from https://github.com/mchobby/esp8266-upy/tree/master/pcf8523
#
# BUG: Something in here thinks January 2026 is the 13th month of 2025...!
#
# __version__ = "0.0.1"

import utime as time

STANDARD_BATTERY_SWITCHOVER_AND_DETECTION = 0b000
BATTERY_SWITCHOVER_OFF = 0b111

RTC_REG = 0x03
ALARM_REG = 0x0A
CONTROL_1_REG = 0x00


## Convert binary coded decimal to binary.
def bcd2bin(value):
    return value - 6 * (value >> 4)


## Convert a binary value to binary coded decimal.
def _bin2bcd(value):
    return value + 6 * (value // 10)


## Interface to the PCF8523 Real Time Clock.
class PCF8523:

    ## Initialize the PCF8523 driver object.
    #  @param i2c An I2C bus object which has already been set up
    #  @param address The address of the PCF8523 on the I2C bus
    def __init__(self, i2c, address=0x68):
        self.i2c = i2c
        self.address = address
        self.buf1 = bytearray(1)
        self.buf7 = bytearray(7)

        # Try and verify this is the RTC we expect by checking the timer B
        # frequency control bits which are 1 on reset and shouldn't ever be
        # changed.
        self.retries = 2
        while self.retries > 0:
            self.buf1[0] = 0x12
            self.i2c.writeto(self.address, self.buf1)
            self.i2c.readfrom_into(self.address, self.buf1)
            if (self.buf1[0] & 0b00000111) != 0b00000111 and self.retries == 2:                
                self.soft_reset()
            elif (self.buf1[0] & 0b00000111) != 0b00000111 and self.retries == 1:
                raise ValueError("Unable to find PCF8523 at i2c address 0x68.")
            self.retries -= 1


    ## Send a reset command to the RTC chip.
    def soft_reset(self):
        self.buf1 = bytearray(1)
        self.buf1[0] = 0x58
        # writes 0x58 to address 0x00 to reset the chip
        self.i2c.writeto_mem(self.address, CONTROL_1_REG, self.buf1)


    ## Get the date and time from a given register location (0x03 for RTC,
    #  0x0A for alarm).
    def _read_datetime(self, time_reg):
        weekday_offset = 1
        weekday_start  = 0

        self.buf1[0] = time_reg
        self.i2c.writeto(self.address, self.buf1)
        self.i2c.readfrom_into(self.address, self.buf7)
        # CircuitPython struct_time (tm_year=1999, tm_mon=12, tm_mday=31,
        #   tm_hour=17, tm_min=4, tm_sec=58, tm_wday=4, tm_yday=365, tm_isdst=0)
        # MicroPython mktime (year, month, mday, hour, minute, second, weekday,
        #                     yearday)
        return time.mktime((
                bcd2bin(self.buf7[6]) + 2000,
                bcd2bin(self.buf7[5]),
                bcd2bin(self.buf7[4 - weekday_offset]),
                bcd2bin(self.buf7[2]),
                bcd2bin(self.buf7[1]),
                bcd2bin(self.buf7[0] & 0x7F),
                bcd2bin(self.buf7[3 + weekday_offset] - weekday_start),
                -1,
                -1))


    ## Get a string which holds the date and time from the RTC.
    #  @param time_reg The register to read, actual time or alarm time
    #  @param date Whether to put the date in the string before the time
    #  @param extras Whether to show the day of week and day of year also
    def get_datetime_str(self, time_reg, date=False, extras=False):
        self.buf1[0] = time_reg
        self.i2c.writeto(self.address, self.buf1)
        self.i2c.readfrom_into(self.address, self.buf7)

        str = ""
        if date:
            str += f"{2000 + bcd2bin(self.buf7[6])}-{bcd2bin(self.buf7[5])}-{bcd2bin(self.buf7[3])},"
        str += f"{bcd2bin(self.buf7[2]):02d}:{bcd2bin(self.buf7[1]):02d}:{bcd2bin(self.buf7[0]):02d}"
        if extras:
            str += f",dow:{bcd2bin(self.buf7[4])},"   # dow:{bcd2bin(self.buf7[7])}"
        return str


    ## Set the time from the tuple (year, month, mday, hour, minute, second,
    #  weekday, yearday) on the given register (0x03 for RTC, 0x0A for alarm)
    def _write_datetime(self, time_reg, value):
        weekday_offset = 1
        weekday_start  = 0

        self.buf7[0] = _bin2bcd(value[5]) & 0x7F    # tm_sec format conversions
        self.buf7[1] = _bin2bcd(value[4])           # tm_min
        self.buf7[2] = _bin2bcd(value[3])           # tm_hour
        self.buf7[3 + weekday_offset] = _bin2bcd(
            value[6] + weekday_start                # tm_wday
        )
        self.buf7[4 - weekday_offset] = _bin2bcd(value[2]) # tm_mday
        self.buf7[5] = _bin2bcd(value[1]) # tm_mon
        self.buf7[6] = _bin2bcd(value[0] - 2000) # tm_year

        self.i2c.writeto_mem(self.address, time_reg, self.buf7)


    ## Gets the current date and time. Just gets the important fields:
    #  Year, month, day-of-month, hours, minutes, seconds.
    @property
    def datetime(self):
#         return self._read_datetime(RTC_REG)  # Naah, this version is lame
        weekday_offset = 1
        weekday_start  = 0

        self.buf1[0] = RTC_REG
        self.i2c.writeto(self.address, self.buf1)
        self.i2c.readfrom_into(self.address, self.buf7)
        # MicroPython mktime (year, month, mday, hour, minute, second, weekday,
        #                     yearday)
        return (bcd2bin(self.buf7[6]) + 2000,
                bcd2bin(self.buf7[5]),
                bcd2bin(self.buf7[3]),
                bcd2bin(self.buf7[2]),
                bcd2bin(self.buf7[1]),
                bcd2bin(self.buf7[0] & 0x7F))


    ## Set the current time from the tuple (year, month, mday, hour, minute,
    #  second, weekday, yearday)
    #  @param dt The new datetime in a list, either (Y, M, D, h, m, s) or the
    #         above
    @datetime.setter
    def datetime(self, dt):
        # Automatically sets lost_power to false
        self.power_management = STANDARD_BATTERY_SWITCHOVER_AND_DETECTION

        if len(dt) == 6:
            # Compute the day of the year as suggested by GPT 5
            mdays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            if (dt[0] % 4 == 0 and dt[0] % 100 != 0) or (dt[0] % 400 == 0):
                mdays[1] = 29
            yearday = sum(mdays[:dt[1] - 1]) + dt[2]

            if dt[1] < 3:        # Now the day of the week by Zeller’s
                dt[1] += 12      # congruence algorithm (works for
                dt[0] -= 1       # Gregorian calendar) 
            K = dt[0] % 100      # as suggested by GPT 5
            J = dt[0] // 100
            h = (dt[2] + (13 * (dt[1] + 1)) // 5 + K + (K // 4) + (J // 4) + 5 * J) % 7
            weekday = (h + 5) % 7           # Zeller: 0=Sat, 1=Sun, ..., 6=Fri
            dt.extend([weekday, yearday])   # Python style: 0=Mon, ... 6=Sun

        elif len(value) != 8:
            raise ValueError("Invalid size array for date and time")

        print(f"Setting date/time to {dt}")    ######################################
        self._write_datetime(RTC_REG, dt)


    ## Power management state that dictates battery switchover, power sources
    #  and low battery detection. Defaults to BATTERY_SWITCHOVER_OFF (0b000).
    @property
    def power_management(self):
        # i2c_bits.RWBits(3, 0x02, 5)
        self.i2c.readfrom_mem_into(self.address, 0x02, self.buf1)
        return self.buf1[0] >> 5


    @power_management.setter
    def power_management(self, value):
        # reg 0x02 bits 5,6,7 (3 lasts bits)
        self.i2c.readfrom_mem_into(self.address, 0x02, self.buf1)
        self.buf1[0] = self.buf1[0] & 0b00011111
        self.buf1[0] = self.buf1[0] | (value << 5)
        self.i2c.writeto_mem(self.address, 0x02, self.buf1)


    @property
    def lost_power(self):
    ## True if the device has lost power since the time was set.
        self.i2c.readfrom_mem_into(self.address, 0x03, self.buf1)
        return (self.buf1[0] & 0b10000000) == 0b10000000


    @lost_power.setter
    def lost_power(self, value):
        self.i2c.readfrom_mem_into(self.address, 0x03, self.buf1)
        self.buf1 = (self.buf1[0] & 0b01111111) # Clear the bit
        if value:
            self.buf1 = self.buf1[0] | 0b10000000
        self.i2c.writeto_mem(self.address, 0x03, self.buf1)


    ## True if the battery is low and should be replaced.
    @property
    def battery_low(self):
        self.i2c.readfrom_mem_into(self.address, 0x02, self.buf1)
        return (self.buf1[0] & 0b00000100) == 0b00000100


    ## True if the interrupt pin will output when alarm is alarming.
    @property
    def alarm_interrupt(self):
        self.i2c.readfrom_mem_into(self.address, 0x00, self.buf1)
        return (self.buf1[0] & 0b00000010) == 0b00000010


    @alarm_interrupt.setter
    def alarm_interrupt(self, value):
        self.i2c.readfrom_mem_into(self.address, 0x00, self.buf1)
        self.buf1[0] = self.buf1[0] & 0b11111101 # clear the bit
        if value:
            self.buf1[0] = self.buf1[0] | 0b00000010 # set the bit
        self.i2c.writeto_mem(self.address, 0x00, self.buf1)


    ## True if alarm is alarming. Set to False to reset.
    @property
    def alarm_status(self):
        self.i2c.readfrom_mem_into(self.address, 0x01, self.buf1)
        return (self.buf1[0] & 0b00001000) == 0b00001000


    @alarm_status.setter
    def alarm_status(self, value):
        self.i2c.readfrom_mem_into(self.address, 0x01, self.buf1)
        self.buf1[0] = self.buf1[0] & 0b11110111 # clear the bit
        if value:
            self.buf1[0] = self.buf1[0] | 0b00001000 # set the bit
        self.i2c.writeto_mem(self.address, 0x01, self.buf1)


    ## Get or set the alarm minute.
    def alarm_min(self, min=None, enable=None):
        # read current definition
        self.i2c.readfrom_mem_into(self.address, ALARM_REG + 0x00, self.buf1)
        if min==None and enable==None:
            min = bcd2bin(self.buf1[0] & 0b01111111)
            enable = not((self.buf1[0] & 0b10000000) == 0b10000000) # Register @ 0 when enabled
            return min,enable
        else:
            if min!=None:
                self.buf1[0] = self.buf1[0] & 0b10000000 # keep enable info
                self.buf1[0] = self.buf1[0] | (_bin2bcd(min) & 0b01111111) # inject min
            if enable!=None:
                enable = not(enable) # alarm is enabled when 0 is placed into the register
                self.buf1[0] = self.buf1[0] & 0b01111111 # keep min info
                if enable:
                    self.buf1[0] = self.buf1[0] | 0b10000000 # Inject enable
            self.i2c.writeto_mem(self.address, ALARM_REG + 0x00, self.buf1)


    ## Get or set the alarm hour.
    def alarm_hour(self, hour=None, enable=None):
        # read current definition
        self.i2c.readfrom_mem_into(self.address, ALARM_REG + 0x01, self.buf1)
        if hour==None and enable==None:
            hour = bcd2bin(self.buf1[0] & 0b00111111)
            enable = not((self.buf1[0] & 0b10000000) == 0b10000000) # Register @ 0 when enabled
            return hour,enable
        else:
            if hour!=None:
                self.buf1[0] = self.buf1[0] & 0b10000000 # keep enable info
                self.buf1[0] = self.buf1[0] | (_bin2bcd(hour) & 0b00111111) # inject hour
            if enable!=None:
                enable = not(enable) # alarm is enabled when 0 is placed into the register
                self.buf1[0] = self.buf1[0] & 0b01111111 # keep min info
                if enable:
                    self.buf1[0] = self.buf1[0] | 0b10000000 # Inject enable
            self.i2c.writeto_mem(self.address, ALARM_REG + 0x01, self.buf1)


    ## Get or set the alarm day.
    def alarm_day(self, day=None, enable=None):
        # read current definition
        self.i2c.readfrom_mem_into(self.address, ALARM_REG + 0x02, self.buf1)
        if day==None and enable==None:
            day = bcd2bin(self.buf1[0] & 0b00111111)
            enable = not((self.buf1[0] & 0b10000000) == 0b10000000) # Register @ 0 when enabled
            return day,enable
        else:
            if day!=None:
                self.buf1[0] = self.buf1[0] & 0b10000000 # keep enable info
                self.buf1[0] = self.buf1[0] | (_bin2bcd(day) & 0b00111111) # inject day
            if enable!=None:
                enable = not(enable) # alarm is enabled when 0 is placed into the register
                self.buf1[0] = self.buf1[0] & 0b00111111 # keep day info
                if enable:
                    self.buf1[0] = self.buf1[0] | 0b10000000 # Inject enable
            self.i2c.writeto_mem(self.address, ALARM_REG + 0x02, self.buf1)


    ## Get or set the alarm weekday.
    def alarm_weekday(self, weekday=None, enable=None):
        # read current definition
        self.i2c.readfrom_mem_into(self.address, ALARM_REG + 0x03, self.buf1)
        weekday_start  = 0
        if weekday==None and enable==None:
            weekday = bcd2bin((self.buf1[0] & 0b00000111) - weekday_start)
            enable = not((self.buf1[0] & 0b10000000) == 0b10000000) # Register @ 0 when enabled
            return weekday,enable
        else:
            if weekday!=None:
                self.buf1[0] = self.buf1[0] & 0b10000000 # keep enable info
                self.buf1[0] = self.buf1[0] | (_bin2bcd(weekday) & 0b00000111) # inject weekday
            if enable!=None:
                enable = not(enable) # alarm is enabled when 0 is placed into the register
                self.buf1[0] = self.buf1[0] & 0b00000111 # keep weekday info
                if enable:
                    self.buf1[0] = self.buf1[0] | 0b10000000 # Inject enable
            self.i2c.writeto_mem(self.address, ALARM_REG + 0x03, self.buf1)


# -------------------------- Test code -------------------------
if __name__ == "__main__":

    import machine

    i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(23))
    print(f"I2C devices: {i2c.scan()}")

    # This is the PCF8523 that we're testing
    pcf_rtc = PCF8523(i2c)

    # The ESP32 has an RTC also
    esp_rtc = machine.RTC()
    print(f"Begin with ESP32 RTC at {esp_rtc.datetime()}")

    year, mon, day, hrs, mns, scs = pcf_rtc.datetime
    esp_rtc.datetime([year, mon, day, 0, hrs, mns, scs, 0])
    print(f"Set ESP32 RTC to {esp_rtc.datetime()} from PCF8523")

    while True:
        try:
            _time = pcf_rtc.datetime
            print(f"Time: {_time}", end="   ")
            print(pcf_rtc.get_datetime_str(RTC_REG, True, True))
        #     print(time.localtime(_time))
        except KeyboardInterrupt:
            break
        time.sleep_ms(10_000)

    print("Test done.")



