## @file task_mqtt.py
#  This file contains a client which can publish Bogan Radar data to an MQTT
#  broker. The data is supplied as strings in a queue, and the MQTT task
#  publishes those data as they're received from the queue.
#
#  @author Spluttflob
#  @date   2025-Nov-23  Original file, borrowing from earlier project by author
#  @copyright (c) 2025 by Spluttflob, released under the GPL V3

import queue
import esp32
import socket
from network import WLAN, STA_IF
import uasyncio as asyncio
from mqtt_as import MQTTClient, config
import task_sd_card                           # The site name is in config here
import task_watchdog


## The first part of the MQTT topic to which we're sending data.
#  The site name will be added to this to get the full topic name.
MQTT_TOPIC = b"bogan_radar/"

## The MQTT server ("broker") to which messages are sent
MQTT_SERVER = "test.mosquitto.org"

## The port on the MQTT server to be used
MQTT_PORT = 1883

## The namespace in the ESP32's NVS where network SSID and password are stored
CERTS_NAMESPACE = "mqtt"

## A queue which holds strings to be sent to the MQTT server
mqtt_queue = queue.Queue()

## The network station, our node on the LAN
net_station = None


## Connect to the given LAN using the given SSID and password.
#  @param ssid The network SSID
#  @param password The password used to get on that network
#  @returns The network station, hopefully up and running
async def web_up(ssid, password):
    global net_station
    if not net_station:
        net_station = WLAN(STA_IF)

    if net_station.isconnected():
        print(f"Already connected as {net_station.ifconfig()[0]}")

    else:
        while True:
            try:
                print(f"Connecting to LAN {ssid}.", end='')
                net_station.active(True)
                net_station.connect(ssid, password)
                for count in range(60):
                    if not net_station.isconnected():
                        print('.', end='')
                        await asyncio.sleep_ms(1000)
                        count += 1
                    else:
                        print(f"connected as {net_station.ifconfig()[0]}")
                        return

                # If we get here, we've timed out, so start over
                print("timeout; retry.")
                net_station.disconnect()
                net_station.active(False)
                await asyncio.sleep_ms(1000)

            except KeyboardInterrupt:
                net_station.disconnect()
                net_station.active(False)
                print("canceled.")


## Shut down the web connection.
def web_down():
    global net_station
    if net_station:
        net_station.disconnect()
        net_station.active(False)
    else:
        print("web_down(): No active WiFi station")


## MQTT callback, not used (I think).
def callback(topic, msg, retained):
    print(topic, msg, retained)


## Connection handler? Something like that. Seems not to be used.
async def conn_han(client):
    await client.subscribe('foo_topic', 1)


## Get the LAN's SSID and password from where they're stored in ESP32 NVS
#  @param namespace The NVS namespace where the LAN information is stored
def get_LAN_certs(namespace):
    nvs = esp32.NVS(namespace)
    tempbuf = bytearray(42)                  # Maximum length of a passphrase
    size = nvs.get_blob(b'ssid', tempbuf)
    ssid = tempbuf[:size].decode()
    size = nvs.get_blob(b'pswd', tempbuf)
    passy = tempbuf[:size].decode()
    return ssid, passy


## Task that sends MQTT messages about radar distance measurements.
#  The messages are delivered in queue mqtt_queue; messages are kept in the
#  queue until a specified number have arrived, at which time the messages are
#  published to the subscribed MQTT broker.
async def mqtt_task():

    print('Starting mqtt_task()...', end='')
    ssid, password = get_LAN_certs('mqtt')
    net_station = await web_up(ssid, password)

    # Set up the MQTT client object to be passed to the MQTT task
    config['ssid'] = ssid
    config['wifi_pw'] = password
    config['subs_cb'] = callback
    config['connect_coro'] = conn_han
    config['server'] = MQTT_SERVER
    config['port'] = MQTT_PORT
    MQTTClient.DEBUG = True             # Optional: print diagnostic messages
    mqtt_client = MQTTClient(config)

    print(f"Connecting to MQTT server {MQTT_SERVER} port {MQTT_PORT}...")
    await mqtt_client.connect()
    print("connected.")

    # Get the site name from the configuration file and add it to the general
    # topic to get the full topic name for the MQTT broker
    while not task_sd_card.the_SD_card.config:
        await asyncio.sleep_ms(100)
    full_mqtt_topic = MQTT_TOPIC + task_sd_card.the_SD_card.config["Site Name"]
    print(f"Publishing to MQTT topic {full_mqtt_topic}")

    while True:
        message = await mqtt_queue.get()
        await mqtt_client.publish(full_mqtt_topic, message.encode(), qos=1)


## Check if the WiFi is still connected. If not, try to reconnect using the
#  @c web_up() and @c web_down() functions in @c boot.py.
async def check_WiFi_task():
    global net_station

    while True:
        await asyncio.sleep_ms(60000)          # Check every minute

        if net_station and not net_station.isconnected():
            web_down()
            await asyncio.sleep_ms(1000)
            ssid, password = get_LAN_certs('mqtt')
            net_station = await web_up(ssid, password)
        elif not net_station:
            ssid, password = get_LAN_certs('mqtt')
            net_station = await web_up(ssid, password)
        else:
            print("WiFi OK")


if __name__ == "__main__":

    ## Create some data (just counting numbers) and put it in the queue
    async def test_data_task():
        global mqtt_queue

        count = 0
        mqtt_string = ""
        mqtt_count = 0
        while True:
            astr = f"Count: {count}\r\n"
            print(astr, end='')
            count += 1
            mqtt_count += 1
            mqtt_string += astr
            if mqtt_count >= 5:
                await mqtt_queue.put(mqtt_string)
                mqtt_count = 0
                mqtt_string = ""
            await asyncio.sleep_ms(1000)


    print("Testing MQTT node for Bogan Radar")

    ## Get the task functions running, then twiddle thumbs until Control-C'ed.
    async def main():
        asyncio.create_task(mqtt_task())
        asyncio.create_task(check_WiFi_task())
        asyncio.create_task(test_data_task())

        while True:
            await asyncio.sleep_ms(1000)

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Control-C ", end='')

    finally:
        asyncio.new_event_loop()             # Clear retained state
        web_down()
        print("Exiting")


