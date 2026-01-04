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
import uasyncio as asyncio
from mqtt_as import MQTTClient, config
import task_network


## The first part of the MQTT topic to which we're sending data.
#  The site name will be added to this to get the full topic name.
MQTT_TOPIC = b"bogan_radar/"

## The second part of the MQTT topic, the site name.
#  Set a default here which can be overridden by the site from the site
#  configuration file on the SD card, if there is one.
mqtt_site = b"test0"

## The MQTT server ("broker") to which messages are sent
MQTT_SERVER = "192.168.2.87"

## The port on the MQTT server to be used
MQTT_PORT = 1883

# ## A queue which holds strings to be sent to the MQTT server
# mqtt_queue = queue.Queue()


## Connection handler? Something like that. Seems not to be used.
async def conn_han(client):
    await client.subscribe('foo_topic', 1)


## MQTT callback, not used (I think).
def callback(topic, msg, retained):
    print(topic, msg, retained)


## Task that sends MQTT messages about radar distance measurements.
#  The messages are delivered in queue mqtt_queue; messages are kept in the
#  queue until a specified number have arrived, at which time the messages are
#  published to the subscribed MQTT broker.
#  @param data_batch A data batch holder that keeps sets of data to be sent
async def mqtt_task(data_batch):

    print('Starting mqtt_task()...', end='')

    # Set up the MQTT client object
    config["ssid"] = "NOSSID"
    config["wifi_pw"] = "NOPASS"
    config["subs_cb"] = callback
    config["connect_coro"] = conn_han
    config["server"] = MQTT_SERVER
    config["port"] = MQTT_PORT
    MQTTClient.DEBUG = True              # Optional: print diagnostic messages
    mqtt_client = MQTTClient(config)

    print(f"Connecting to MQTT server {MQTT_SERVER} port {MQTT_PORT}...")
    await mqtt_client.connect()
    print("connected.")

    # Get the site name from the configuration file and add it to the general
    # topic to get the full topic name for the MQTT broker
    full_mqtt_topic = MQTT_TOPIC + mqtt_site
    print(f"Publishing to MQTT topic {full_mqtt_topic}")

    while True:
        message = await data_batch.get()
        await mqtt_client.publish(full_mqtt_topic, message.encode(), qos=1)
        data_batch.done()


if __name__ == "__main__":

    import databatch

    ## Create some data (just counting numbers) and put it in the queue
    async def test_data_task(d_batch):
        count = 0
        while True:
            count += 1
            await d_batch.put(f"Count: {count} ")
            await asyncio.sleep_ms(1000)


    ## Get the task functions running, then twiddle thumbs until Control-C'ed.
    async def main():
        batch = databatch.DataBatch(batch_size=5, n_consumers=1)

        asyncio.create_task(task_network.check_WiFi_task())
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
        task_network.web_down(None)
        print("Exiting")


