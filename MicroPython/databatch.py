## @file databatch.py
#  This file contains a class that stores a batch of data to be printed, saved
#  to an SD card, sent through the Interwebs, etc. in an asyncio environment.
#  The batch is really just a string made of smaller strings, but it uses
#  asyncio events to synchronize production of data in one task with sending
#  and/or storage of data in multiple other tasks. Saving data in one task and
#  using it in multiple tasks is what distinguishes this class from a queue.

import gc
from io import StringIO
import uasyncio as asyncio


## This class holds a batch of data which will be saved gradually as data is
#  measured, then saved in a file or sent at once through a network connection.
#  It uses asyncio to cause data consuming tasks to wait for a batch to be
#  ready.
class DataBatch:

    ## Initialize a batch, giving it references to .......... something?
    #  @param batch_size The number of entries saved before printing or sending
    #  @param n_consumers The number of tasks using the data
    def __init__(self, batch_size, n_consumers):

        self._data = StringIO()
        self._n_saved = 0              # The number of entries saved so far
        self._size = batch_size        # Number of entries before data is sent
        self._consumers = n_consumers  # How many consumer tasks use the data

        # This event tells consuming tasks that data is ready to be used
        self._data_ready = asyncio.Event()
        self._data_ready.clear()

        # This event authorizes data saving tasks that more data may be saved
        self._ok_to_save = asyncio.Event()
        self._ok_to_save.set()

        # Number of consumers for which we're still waiting
        self._waiting_for = 0


    ## Add a new bit of data (as a string) to this batch of data, then delete
    #  the data after a copy was tacked onto the batch of data. This method
    #  waits for data to be saved if necessary.
    #  TODO: Add double buffering so data may be taken as it's being saved
    #  @param new_data A string containing more data to be added to the batch
    async def put(self, new_data):
        await self._ok_to_save.wait()

        self._data.write(new_data)
        self._n_saved += 1

        # If the batch is ready to use, unblock the consuming task(s)
        if self._n_saved >= self._size:
            self._waiting_for = self._consumers
            self._ok_to_save.clear()
            self._data_ready.set()
            self._data_ready.clear()

        return self


    ## Clear the data, recovering its memory as soon as possible, and setting up
    #  a new StringIO object to hold future data. This method should be called
    #  by the last task which has used the data, if multiple tasks use the data.
    def clear(self):
        self._data.close()
        self._data = StringIO()
        self._n_saved = 0
#         self._data_ready.clear()
        self._ok_to_save.set()
        gc.collect()


    ## Return a batch of data when it is ready, blocking the calling task until
    #  the batch has been filled with data.
    #  Usage: batch_o_data = await the_batch.get()
    async def get(self):
        # Batch is not yet ready; suspend task until data batch is full
        await self._data_ready.wait()
        return self._data.getvalue()


    ## Each consumer task calls this when finished consuming. When all the
    #  consumers are done with the data, we can begin making a new batch.
    def done(self):
        self._waiting_for -= 1
        if self._waiting_for <= 0:
            self.clear()


    ## Return the data batch as a string to be stored, printed, sent over the
    #  web, or otherwise used. This method is only for debugging and is not to
    #  be used in a task.
    def __str__(self):
        return self._data.getvalue()


#-------------------------------------------------------------------------------

if __name__ == "__main__":

    begin_ram = None

    # Parameters: Number of data before sending batch, number of consumer tasks
    batch = DataBatch(5, 2)


    # Function that creates some fake data
    async def task_data(a_batch):
        count = 0
        
        while True:
            data = f"Data {count}, "
            count += 1
            await a_batch.put(data)
            del data
            await asyncio.sleep_ms(1_000)


    # One function that displays the data
    async def task_show_A(a_batch):
        while True:
            to_show = await a_batch.get()
            print(f"A: {to_show} ")
            a_batch.done()


    # Another function that displays the same data
    async def task_show_B(b_batch):
        global begin_ram
        while True:
            to_show = await b_batch.get()
            print(f"B: {to_show} ")
            print(f"RAM: {begin_ram - gc.mem_free()}")
            b_batch.done()


    # The function which creates and runs each of the task functions
    async def main():
        global begin_ram
        begin_ram = gc.mem_free()
        print(f"Begin: {begin_ram}")

        asyncio.create_task(task_data(batch))
        asyncio.create_task(task_show_A(batch))
        asyncio.create_task(task_show_B(batch))

        while True:
            await asyncio.sleep_ms(1_000)

    # Run the main function here. If we're doing a test, the program may be stopped
    # by pressing Ctrl-C. For normal measurements, just leave it running for days,
    # weeks, or months on end. An uncaught exception causes a file closing to save
    # data to the SD card if possible, then a reboot to restart the whole program
    print("Beginning data batch test.")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Ctrl-C. ", end='')
    except Exception as ohnoes:
        print(f"Uncaught exception {ohnoes}")
        utime.sleep_ms(500)
    finally:
        asyncio.new_event_loop()
        print("Data batch test finished.")

