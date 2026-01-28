## @file task_mqtt.py
#  This file contains a client which can publish Bogan Radar data to an MQTT
#  broker. The data is supplied as strings in a queue, and the MQTT task
#  publishes those data as they're received from the queue.
#
#  @author Spluttflob
#  @date   2025-Nov-23  Original file, borrowing from earlier project by author
#  @date   2026-Jan-01  Moved networking to task_network.py; using databatch.py
#  @copyright (c) 2025 by Spluttflob, released under the GPL V3

import gc
import machine
from esp32 import NVS
from utime import ticks_ms, ticks_diff
import uasyncio as asyncio
import databatch
from mqtt_as import MQTTClient, config
import task_watchdog


## The namespace in the ESP32's NVS where network SSID and password are stored
CERTS_NAMESPACE = "mqtt"

## The first part of the MQTT topic to which we're sending data.
#  The site name will be added to this to get the full topic name.
MQTT_TOPIC = b"bogan_radar/"

## The second part of the MQTT topic, the site name.
#  Set a default here which can be overridden by the site from the site
#  configuration file on the SD card, if there is one.
mqtt_site = b"test0"

## The MQTT server ("broker") to which messages are sent "test.mosquitto.org"
MQTT_SERVER = "192.168.2.87"

## The port on the MQTT server to be used
MQTT_PORT = 1883

## The lat number in the IP address of this machine on the LAN to which it is
#  hopefully connected
ip_node = 0

## Whether the network is connected and working (True) or not (False)
net_up = False

## The number of times transmission tried with the network or MQTT broker down
outage_count = 0


## Get the LAN's SSID and password from where they're stored in ESP32 NVS
#  @param namespace The NVS namespace where the LAN information is stored
def get_LAN_certs(namespace):
    nvs = NVS(namespace)
    tempbuf = bytearray(42)                  # Maximum length of a passphrase
    size = nvs.get_blob(b'ssid', tempbuf)
    ssid = tempbuf[:size].decode()
    size = nvs.get_blob(b'pswd', tempbuf)
    passy = tempbuf[:size].decode()
    return ssid, passy


## Task which waits until the network is down, then sets a flag and complains
async def down(client):
    while True:
        await client.down.wait()             # Pause until connectivity changes
        client.down.clear()
        net_up = False
        print("WiFi or MQTT broker is down")


## Task which waits until the network is up, then sets a flag and celebrates
async def up(client):
    while True:
        await client.up.wait()
        client.up.clear()
        net_up = True
        print("Connected to MQTT broker")


## Task that sends MQTT messages about radar distance measurements.
#  The messages are delivered by a DataBatch consumer; messages are kept in the
#  batch until a specified number have arrived, at which time the batch of
#  messages is published to the given MQTT broker.
#  @param consumer A DataBatch consumer object from which we get bytearrays of
#         data to be sent to the MQTT broker
#  @param next_queue A queue that sends the data to another task, or None if
#         the data should be deleted when it has been sent
async def mqtt_task(consumer, next_queue=None):

    global ip_node          # Last number in IP address, global for other tasks

    gc.collect()
    print(f"Starting mqtt_task() with {gc.mem_free()} B free")

    # Get the LAN certifications from the ESP32's nonvolatile memory
    ssid, passwd = get_LAN_certs(CERTS_NAMESPACE)

    # Set up the MQTT client object
    config["ssid"] = ssid
    config["wifi_pw"] = passwd
#     config["subs_cb"] = callback
#     config["connect_coro"] = conn_han
    config["server"] = MQTT_SERVER
    config["port"] = MQTT_PORT
    config["will"] = (MQTT_TOPIC + mqtt_site,
                      f"MQTT client at {mqtt_site.decode()} quitting", False, 0)
    config["keepalive"] = 120
    config["queue_len"] = 1            # Use event interface with default queue
    MQTTClient.DEBUG = True            # Optional: print diagnostic messages
    mqtt_client = MQTTClient(config)

    # Connect to the MQTT server
    try:
        await mqtt_client.connect(quick=True)
    except OSError as rats:
        print(f"MQTT Connection failed: {rats}")
        while True:
            asyncio.sleep_ms(1_000)

    # Start tasks that respond to network connection being lost and regained
    asyncio.create_task(up(mqtt_client))
    asyncio.create_task(down(mqtt_client))

    # Find the IP address and isolate the last number for sharing
    my_ip_addr = mqtt_client._sta_if.ifconfig()[0]
    try:
        ip_node = int(my_ip_addr.split('.')[3])
    except (ValueError, IndexError):
        print(f"Cannot find IP node from '{my_ip_addr}'")
        ip_node = 0
    print(f"Connected to MQTT server {MQTT_SERVER} port {MQTT_PORT} from {my_ip_addr}")

    # Get the site name from the configuration file and add it to the general
    # topic to get the full topic name for the MQTT broker
    full_mqtt_topic = MQTT_TOPIC + mqtt_site
    print(f"Publishing to MQTT topic {full_mqtt_topic}")

    while True:
        message = await consumer.get()
        task_watchdog.mqtt_event.set()   # So watchdog timer doesn't reset ESP32
        start_time = ticks_ms()
        await mqtt_client.publish(full_mqtt_topic, message, qos=1)
        print(f"MQTT pub in {ticks_diff(ticks_ms(), start_time)} ms")
        del message


if __name__ == "__main__":

    ## Create some data (just counting numbers and text) and put it in the queue
    async def test_data_task(a_batch):
        count = 0
        while True:
            send_str = f"#{count}: {gc.mem_free()} bytes. "
            count += 1
            await a_batch.put(send_str.encode())
            await asyncio.sleep_ms(1000)


    ## Another task which prints periodically to verify that the MQTT task
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
        tasks.append(asyncio.create_task(mqtt_task(consumer_A)))
        tasks.append(asyncio.create_task(other_task(consumer_B)))

        # Using asyncio.gather() allows us to catch and deal with exceptions in
        # each task; otherwise one task may quit while others just keep going
        try:
            await asyncio.gather(*tasks)
        except MemoryError as oops:
            print(f"FAIL: {oops}")
            machine.reset()


    print("Testing MQTT node for Bogan Radar")
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Control-C ", end='')

    finally:
        asyncio.new_event_loop()             # Clear retained state
        print("Exiting")


