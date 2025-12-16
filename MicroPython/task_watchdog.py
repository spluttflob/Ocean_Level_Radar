## @file task_watchdog.py
#  This file contains a software/hardware watchdog timer for the Bogan Radar.
#  The ESP32's hardware watchdog is used in case the microcontroller hangs
#  completely, and some software watchdogs are used to ensure that critical
#  tasks are doing their job. The system will be restarted if any watchdog
#  detects that something is amiss.
#
#  @author Spluttflob
#  @date   2025-Dec-15  Original file split from main.py
#  @copyright (c) 2025 by Spluttflob, released under the GPL V3

from machine import Pin, WDT, reset
import uasyncio as asyncio
from utime import sleep_ms, ticks_ms, ticks_diff


## An indicator LED used by the watchdog task to show things are OK (or not)
#  On the EZSBC board, the LED turns on when the pin is set low.
status_LED = Pin(13, Pin.OUT, value=1)

## The pin value that lights the LED
LED_ON = 0

## The pin value that extinguishes the LED
LED_OFF = 1

## How often in milliseconds to check that other tasks are still running
TASK_CHECK_MS = 60_000

## Flag that indicates the radar task is still running. Every minute, this task
#  sets the flag to False; another task must set it True or system reboots.
radar_task_flag = True

## Flag that indicates the SD card task is running. Every minute, this task
#  sets the flag to False; another task must set it True or system reboots.
sd_card_task_flag = True

## Flag that indicates the MQTT task is running.  Every minute, this task
#  sets the flag to False; another task must set it True or system reboots.
mqtt_task_flag = True


## @brief   Task function which monitors how the rest of the system is doing.
#  @details A hardware watchdog timer is used so that if things really go down
#           the drain, the system will be restarted. The ESP32 watchdog timer
#           is really strict in that once it has been started, it cannot be
#           stopped or changed. There are software watchdogs in that other
#           tasks have to tell this task that they're alive periodically or the
#           system will be restarted by software in this task.
async def task_watchdog():

    global radar_task_flag, sd_card_task_flag, mqtt_task_flag

    # Wait a minute before activating the watchdog timer; this allows someone
    # to Ctrl-C the system after reboot and halt main.py if there is a bug that
    # would otherwise cause infinitely repeating watchdog timer reboots.
    await asyncio.sleep_ms(60_000)

    doggo = WDT(timeout=10_000)            # Timeout in 10 seconds if not fed
    last_check_time = ticks_ms()           # Last time we checked task flags

    while True:

        doggo.feed()                       # Ensure the watchdog (timer) is fed

        # Once every TASK_CHECK_MS, check for a message from each task which is
        # being watched by a software watchdog. If any of these tasks has
        # stopped, complain woefully and reboot the system
        if ticks_diff(ticks_ms(), last_check_time) >= TASK_CHECK_MS:
            last_check_time = ticks_ms()

            if not radar_task_flag or not sd_card_task_flag:
                if not radar_task_flag:
                    print("Oh noes! Radar task stopped; we'll reboot.")
                if not sd_card_task_flag:
                    print("Bummer! SD card task stopped; we'll reboot.")
                await asyncio.sleep_ms(1_000)
                reset()
            else:
                print("Watchdog check passed.")

            radar_task_flag = False
            sd_card_task_flag = False

        # Run often enough to definitely keep the doggo fed if there's no crash
        await asyncio.sleep_ms(1_000)

#         # Battery voltage is being wonky on test machine; not using it for now
#         batt_v_ctl_pin.value(1)            # Turn on voltage divider, wait for
#         await asyncio.sleep_ms(10)         # it to settle
#         vbatt = batt_v_sensor.read_uv() * 2.0
#         batt_v_ctl_pin.value(0)


## @brief   Task function which blinks an LED to indicate how system is doing.
async def task_LED():

        status_LED.value(LED_ON)           # For the EZSBC feather, 0 is LED on
        await asyncio.sleep_ms(40)
        status_LED.value(LED_OFF)

        if task_gps.valid_datetime:
            await asyncio.sleep_ms(4950)   # Blink every 5s if valid, 1s if not
        else:
            await asyncio.sleep_ms(950)


if __name__ == "__main__":

    ## @brief   The function which creates and runs each of the task functions.
    async def main():
        asyncio.create_task(task_watchdog())
        while True:
            await asyncio.sleep_ms(1_000)

    # Run the main program here. If we're doing a test, the program may be stopped
    # by pressing Ctrl-C. For normal measurements, just leave it running for days,
    # weeks, or months on end. An uncaught exception causes a file closing to save
    # data to the SD card, then a reboot to restart the whole program
    print("Bogan Radar watchdog timer test")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Ctrl-C. ", end='')
    except Exception as ohnoes:
        print("Uncaught exception {ohnoes}")
        sleep_ms(500)
    finally:
        asyncio.new_event_loop()
        print("Watchdog timer test finished.")

