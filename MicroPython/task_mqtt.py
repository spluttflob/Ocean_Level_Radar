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
from esp32 import NVS
from utime import ticks_ms, ticks_diff
import uasyncio as asyncio
from mqtt_as import MQTTClient, config


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

## The number of times the network or MQTT broker has gone down
outages = 0


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


async def down(client):
    global outages
    while True:
        await client.down.wait()             # Pause until connectivity changes
        client.down.clear()
        outages += 1
        print("WiFi or MQTT broker is down")


async def up(client):
    while True:
        await client.up.wait()
        client.up.clear()
        print("Connected to MQTT broker")


## Task that sends MQTT messages about radar distance measurements.
#  The messages are delivered in queue mqtt_queue; messages are kept in the
#  queue until a specified number have arrived, at which time the messages are
#  published to the subscribed MQTT broker.
#  @param data_batch A data batch holder that keeps sets of data to be sent
async def mqtt_task(data_batch):

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
        message = await data_batch.get()
        start_time = ticks_ms()
        await mqtt_client.publish(full_mqtt_topic, message.encode(), qos=1)
        data_batch.done()
        print(f"MQTT pub in {ticks_diff(ticks_ms(), start_time)} ms")


if __name__ == "__main__":

    import databatch

    ## Create some data (just counting numbers) and put it in the queue
    async def test_data_task(d_batch):
        count = 0
        while True:
            count += 1
            d_batch.put(f"#{count} RAM: {gc.mem_free()} ")
            await asyncio.sleep_ms(1000)


    ## Get the task functions running, then twiddle thumbs until Control-C'ed.
    async def main():
        batch = databatch.DataBatch(batch_size=5, n_consumers=1)
#         asyncio.create_task(task_network.check_WiFi_task())
        asyncio.create_task(mqtt_task(batch))
        asyncio.create_task(test_data_task(batch))

        while True:
            await asyncio.sleep_ms(1000)

    print("Testing MQTT node for Bogan Radar")
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Control-C ", end='')

    finally:
        asyncio.new_event_loop()             # Clear retained state
        print("Exiting")


