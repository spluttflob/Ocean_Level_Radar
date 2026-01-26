## @file databatch.py
#  This file contains a class that stores a batch of data to be printed, saved
#  to an SD card, sent through the Interwebs, etc. in an asyncio environment.
#  The batch is really just a string made of smaller strings, but it uses
#  asyncio events to synchronize production of data in one task with sending
#  and/or storage of data in multiple other tasks. Saving data in one task and
#  using it in multiple tasks, as well as accumulating long strings efficiently,
#  are what distinguish this class from a regular queue.
#
#  @author Spluttflob with help from ChatGPT 5.2
#  @date   2026-Jan-25
#  @copyright (c) 2026 by Spluttflob, released under the GPL V3

import gc
from io import BytesIO
import uasyncio as asyncio
from broadqueue import BroadcastQueue, _BQConsumer


## This class holds a batch of data which will be saved gradually as data is
#  measured, then saved in a file or sent at once through a network connection.
#  It uses asyncio to cause data consuming tasks to wait for a batch to be
#  ready.
class DataBatch(BroadcastQueue):

    ## Initialize a batch, creating a BytesIO object to store the data.
    #  @param batch_size The number of entries saved before printing or sending
    #  @param maxsize The maximum number of items allowed in the queue
    #  @param drop_old True if recently joined consumer ignores oldest items
    def __init__(self, batch_size, maxsize=10, drop_old=False):
        super().__init__(maxlen=maxsize, drop_oldest=drop_old)

        self._data = bytearray()       # The bytestring currently being written
        self._n_saved = 0              # The number of entries saved so far
        self._size = batch_size        # Number of entries before data is sent


    ## Add a new bit of data (as bytes) to this batch of data, then delete
    #  the data after a copy was tacked onto the batch of data. This method
    #  waits for data to be saved if necessary.
    #  TODO: Add double buffering so data may be taken as it's being saved
    #  @param new_data A bytearray containing more data to be added to the batch
    async def put(self, new_data):
        self._n_saved += 1
        self._data.extend(new_data)
        del new_data

        # If the batch is ready to be read, put the StreamIO object in the queue
        if self._n_saved >= self._size:
            self._n_saved = 0
            await super().put(self._data)
            self._data = bytearray()       # Make a new byte array for new data

        return self


#-------------------------------------------------------------------------------

if __name__ == "__main__":

    import utime

    begin_ram = None

    # Function that creates some fake data
    async def task_data(a_batch):
        count = 0
        while True:
            data = f"Data {count}, ".encode()
            count += 1
            await a_batch.put(data)
            del data
            await asyncio.sleep_ms(1_000)


    # One function that displays the data
    async def task_show_A(a_cons):
        while True:
            to_show = await a_cons.get()
            print(f"A: {to_show} ")


    # Another function that displays the same data
    async def task_show_B(b_cons):
        global begin_ram
        while True:
            to_show = await b_cons.get()
            print(f"B: {to_show}   ", end='')
            print(f"RAM: {begin_ram - gc.mem_free()}")


    # The function which creates and runs each of the task functions
    async def main():
        global begin_ram
        gc.collect()
        begin_ram = gc.mem_free()
        print(f"Begin: {begin_ram}")

        batch = DataBatch(5, maxsize=10)
        consumer_A = batch.register()
        consumer_B = batch.register()

        asyncio.create_task(task_data(batch))
        asyncio.create_task(task_show_A(consumer_A))
        asyncio.create_task(task_show_B(consumer_B))

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

