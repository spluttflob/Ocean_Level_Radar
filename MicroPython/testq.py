#
#  Written by ChatGPT -- not really a queue but a mailbox.  I'll be trying a
#  real queue after this, but since this might come in handy, let's push it.
#
#
#


import uasyncio as asyncio

## A type of queue with a single producer and many consumers.
#  Each consumer sees every published value exactly once.
#  Next publish waits until all consumers have consumed current value.
#  Works with uasyncio using only Lock + Event.
class BroadcastQueue:

    def __init__(self):
        self._lock = asyncio.Lock()

        self._value = None
        self._gen = 0
        self._remaining = 0
        self._consumers = []  # list of _ConsumerState

        self._all_consumed = asyncio.Event()
        self._all_consumed.set()  # initially no outstanding item


    def register(self):
        st = _ConsumerState()
        # Start each consumer "caught up" to current generation
        st.gen = self._gen
        self._consumers.append(st)
        return _BQConsumer(self, st)


    async def put(self, value):
        # Wait until previous value is fully consumed
        await self._all_consumed.wait()

        async with self._lock:
            # Re-check under lock in case of races
            if self._remaining != 0:
                # Someone started consuming but not finished; wait again
                # outside lock
                pass
            else:
                # Publish new value
                self._value = value
                self._gen += 1
                self._remaining = len(self._consumers)

                # If there are no consumers, mark consumed immediately
                if self._remaining == 0:
                    self._all_consumed.set()
                    return

                # New item outstanding
                self._all_consumed.clear()

                # Wake all consumers by setting their event
                for st in self._consumers:
                    st.ev.set()


    async def _get(self, st):
        # Wait until a new generation is available for this consumer
        while True:
            # Fast path: check under lock
            async with self._lock:
                if st.gen != self._gen:
                    # Consume current value
                    st.gen = self._gen
                    val = self._value

                    self._remaining -= 1
                    if self._remaining == 0:
                        # Last consumer finished -> allow next publish
                        self._all_consumed.set()

                    return val

                # No new value yet: clear our event before waiting
                st.ev.clear()

            # Wait to be notified of a new publish
            await st.ev.wait()


class _ConsumerState:
    __slots__ = ("gen", "ev")
    def __init__(self):
        self.gen = 0
        self.ev = asyncio.Event()


class _BQConsumer:
    def __init__(self, bq, st):
        self._bq = bq
        self._st = st

    async def get(self):
        return await self._bq._get(self._st)


#-------------------------------------------------------------------------------

if __name__ == "__main__":

    bq = BroadcastQueue()
    c1 = bq.register()
    c2 = bq.register()


    async def consumer_A(c):
        while True:
            x = await c.get()
            print("A:", x)


    async def consumer_B(c):
        count = 0
        while True:
            count += 1
            if count % 5 == 0:
                await asyncio.sleep(5)
            x = await c.get()
            print("B:", x)


    async def producer():
        i = 0
        while True:
            await bq.put(i)
            i += 1
            await asyncio.sleep(1)


    async def main():
        asyncio.create_task(consumer_A(c1))
        asyncio.create_task(consumer_B(c2))
        await producer()


    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Ctrl-C.")


