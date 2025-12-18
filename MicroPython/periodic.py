## @file periodic.py
#  A task scheduling mechanism that doesn't have the timing creep problem which
#  affects tasks that use *.sleep_ms() without accounting for the time taken to
#  perform the work done in the task.
#
#  @author Spluttflob
#  @author ChatGPT 5
#  @date   2025-Dec-16 Original file

import uasyncio as asyncio
import utime


## vTaskDelayUntil-style periodic scheduler for a single asyncio task.
#  
#  Usage:
#      p = Periodic(period_ms=5000)   # 5 seconds
#      while True:
#          # ... do work ...
#          await p.wait_next()
class PeriodicDelay:


    def __init__(self, period_ms, start_immediately=True):
        self.period = int(period_ms)
        now = utime.ticks_ms()
        if start_immediately:
            # first deadline is now (i.e. run immediately, then next +period)
            self.next_deadline = now
        else:
            # first deadline is now + period
            self.next_deadline = utime.ticks_add(now, self.period)


    ## Wait until the next deadline, then schedule the following one.
    async def wait_next(self):
        now = utime.ticks_ms()
        # How long until the current deadline?
        delay = utime.ticks_diff(self.next_deadline, now)
        if delay > 0:
            # Sleep only the remaining time to hit the deadline
            await asyncio.sleep_ms(delay)

        # Compute the *next* absolute deadline, without drift
        # (handles overruns by skipping slots if necessary)
        now = utime.ticks_ms()
        while utime.ticks_diff(self.next_deadline, now) <= 0:
            self.next_deadline = utime.ticks_add(self.next_deadline,
                                                 self.period)


#-------------------------------------------------------------------------------
if __name__ == "__main__":

    start_time = utime.ticks_ms()

    async def task_A():
        perd = PeriodicDelay(period_ms=1000)  # 1 Hz
        while True:
            print(f"A {utime.ticks_ms() - start_time}")
            await perd.wait_next()

    async def task_B():
        perd = PeriodicDelay(period_ms=2500)  # 0.4 Hz
        while True:
            print(f"B {utime.ticks_ms() - start_time}")
            # Pretend this task does variable work:
            # (e.g., sometimes 10 ms, sometimes 80 ms)
            # That variation will NOT cause long-term drift.
            await asyncio.sleep_ms(50)
            await perd.wait_next()

    async def main():
        asyncio.create_task(task_A())
        asyncio.create_task(task_B())
        # Keep loop alive
        while True:
            await asyncio.sleep(60)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Ctrl-C.")
    asyncio.new_event_loop()

