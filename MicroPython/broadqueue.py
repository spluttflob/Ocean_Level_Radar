## @file broadqueue.py
#  This file contains a queue class which takes input from one data producer and
#  makes that data available to multiple consumers. Each data item is considered
#  'gotten' from the queue only when all the consumers have gotten it.
#
#  @author ChatGPT 5.2 with some help from Spluttflob
#  @date   2026-Jan-25
#  @copyright (c) 2026 by Spluttflob, released under GPL V3

import gc
import uasyncio as asyncio


## A sort of queue with one producer and many consumers.
#  Each consumer sees every item exactly once, in order.
#  Items buffer up to the limit 'maxlen' if a consumer falls behind.
class BroadcastQueue:

    ## Initialize the multi-consumer queue object.
    #  maxlen=None => unbounded (dangerous on small RAM)
    #  drop_oldest=False: If maxlen reached, producer waits (backpressure)
    #  drop_oldest=True:  If maxlen reached, drop data (slow consumers may miss)
    def __init__(self, maxlen=10, drop_oldest=False):
        self._lock = asyncio.Lock()
        self._buf = []
        self._base = 0              # absolute index of _buf[0]
        self._maxlen = maxlen
        self._drop_oldest = drop_oldest
        self._consumers = []


    ## Register a consumer with the queue.
    #  The queue won't pop an item until all consumers have gotten it.
    #  @param keep_old_items Do we give old data to newly registered consumer:
    #    - False: start at next put (ignore backlog)
    #    - True:  start from oldest currently buffered
    def register(self, keep_old_items=False):
        st = _ConsumerState()
        if keep_old_items:
            st.next = self._base
        else:
            st.next = self._base + len(self._buf)
        self._consumers.append(st)
        return _BQConsumer(self, st)


    ## Put an item into the queue.
    #  If queue is full, follow 'drop_oldest' policy set in __init__().
    #  @param item The item to be added to the queue
    async def put(self, item):
        while True:
            async with self._lock:
                if self._maxlen is None or len(self._buf) < self._maxlen:
                    self._buf.append(item)
                    # Wake every consumer: a new item exists (even if some are
                    # behind)
                    for st in self._consumers:
                        st.ev.set()
                    return

                # Buffer full
                if self._drop_oldest:
                    self._drop_oldest_locked()
                    # loop back and append
                    continue

                # Backpressure: wait until someone consumes and frees space
                # We'll wait on a one-shot event that gets set when trimming
                # happens.
                self._space_ev.clear()

            await self._space_ev.wait()


    ## Get an item from the queue, when one is ready.
    async def get(self, st):
        while True:
            do_gc = False
            async with self._lock:
                avail = self._base + len(self._buf)
                if st.next < avail:
                    item = self._buf[st.next - self._base]
                    st.next += 1

                    trimmed = self._trim_locked()
                    if trimmed:
                        do_gc = True

                    if trimmed and self._maxlen is not None \
                            and not self._drop_oldest:
                        self._space_ev.set()

                    # leave lock before GC
                    break

                st.ev.clear()

            await st.ev.wait()

        if do_gc:
            gc.collect()

        return item


    ## Drop items from left that all consumers have consumed.
    #  Must be called with _lock held.
    #  @returns True if anything was trimmed.
    def _trim_locked(self):
        if not self._consumers:
            if self._buf:
                self._buf.clear()
                return True
            return False

        min_next = min(st.next for st in self._consumers)
        drop = min_next - self._base
        if drop > 0:
            # drop left prefix
            self._buf = self._buf[drop:]
            self._base = min_next
            return True
        return False


    ## Drop one oldest item. Slow consumers skip missed data.
    #  Must be called with _lock held.
    def _drop_oldest_locked(self):
        if not self._buf:
            return
        self._buf.pop(0)
        self._base += 1
        for st in self._consumers:
            if st.next < self._base:
                st.next = self._base


    ## For backpressure mode we need a shared "space available" event.
    #  It's created lazily to keep compatibility with minimal uasyncio builds.
    @property
    def _space_ev(self):
        if not hasattr(self, "__space_ev"):
            self.__space_ev = asyncio.Event()
            self.__space_ev.set()
        return self.__space_ev


class _ConsumerState:
    __slots__ = ("next", "ev")
    def __init__(self):
        self.next = 0
        self.ev = asyncio.Event()


class _BQConsumer:
    def __init__(self, q, st):
        self._q = q
        self._st = st

    async def get(self):
        return await self._q.get(self._st)


#-------------------------------------------------------------------------------

if __name__ == "__main__":

    q = BroadcastQueue(maxlen=10)                # or None for unbounded
    c1 = q.register(keep_old_items=True)
    c2 = q.register()

    async def consumer(name, c, delay_ms=0):
        while True:
            x = await c.get()
            print(name, x)
            if delay_ms:
                await asyncio.sleep_ms(delay_ms)

    async def producer():
        i = 0
        for count in range(10):
            await q.put(i)
            i += 1
            await asyncio.sleep_ms(500)

    async def main():
        asyncio.create_task(consumer("fast", c1, 0))
        asyncio.create_task(consumer("slow", c2, 1000))  # falls behind sometimes
        asyncio.create_task(producer())
        while True:
            await asyncio.sleep(10)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        asyncio.new_event_loop()
        print("Done.")


