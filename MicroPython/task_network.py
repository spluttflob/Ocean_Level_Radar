## @file task_network.py
#  This file contains a task which gets networking up and running, then checks
#  periodically to make sure the network is still connected, taking steps to
#  reconnect if not.
#
#  @author Spluttflob
#  @date   2026-Jan-01  Original file, borrowing from earlier project by author
#  @copyright (c) 2026 by Spluttflob, released under the GPL V3

import gc
import esp32
import uasyncio as asyncio
from network import WLAN, STA_IF, AP_IF


## The namespace in the ESP32's NVS where network SSID and password are stored
CERTS_NAMESPACE = "mqtt"

## The last number in the IP address, sent to help user find this thing on LAN
ip_node = None

# ## A flag to wait for the web task to start before MQTT task does. This flag is
# #  set by the web server task. If not using the web server task, set this flag
# #  to True here and it won't get in the way.
# web_start_done = False


## Connect to the given LAN using the given SSID and password.
#  @param net_station The network station handle, or None if not set up yet
#  @param ssid The network SSID
#  @param password The password used to get on that network
#  @param access_point Set up access point ('hotspot'), not LAN node
#  @returns The network station, hopefully up and running
async def web_up(net_station, ssid, password, access_point=False):

    global ip_node

    gc.collect()
    print(f"Memory prior to WLAN: {gc.mem_free()}")

    # Make sure there's a LAN station, and get it connected
    if net_station is None:
        if access_point:
            net_station = WLAN(AP_IF)
        else:
            net_station = WLAN(STA_IF)

    gc.collect()
    print(f"Memory after creating station: {gc.mem_free()}")

    if net_station.isconnected():
        print(f"Already connected as {net_station.ifconfig()[0]}")
        return net_station
    else:
        net_station.active(False)       # Turn it off and on again
        await asyncio.sleep_ms(100)
        while True:
            if not access_point:
                print(f"Connecting to LAN {ssid}...")
                net_station.active(True)
                net_station.connect(ssid, password)
                for count in range(60):
                    if not net_station.isconnected():
                        print('.', end='')
                        await asyncio.sleep_ms(1000)
                        count += 1
                    else:
                        ip_node = int(net_station.ifconfig()[0].split('.')[-1])
                        print(f"Connected as {net_station.ifconfig()[0]} Node {ip_node}")
                        return net_station

            # If we get here, we've timed out, so start over
            print("LAN timeout; retry.")
            net_station.disconnect()
            net_station.active(False)
            net_station = None
            await asyncio.sleep_ms(1000)

#             except KeyboardInterrupt:
#                 net_station.disconnect()
#                 net_station.active(False)
#                 print("canceled.")


## Shut down the web connection.
def web_down(net_station):
    global ip_node

    if net_station:
        net_station.disconnect()
        net_station.active(False)
    else:
        print("web_down(): No active WiFi station")
    ip_node = None


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


## Check if the WiFi is still connected. If not, try to reconnect using the
#  @c web_up() and @c web_down() functions in @c boot.py.
async def check_WiFi_task():

    ssid, password = get_LAN_certs(CERTS_NAMESPACE)
    net_station = await web_up(None, ssid, password)

    while True:
        await asyncio.sleep_ms(10_000)

        if not net_station:
            ssid, password = get_LAN_certs(CERTS_NAMESPACE)
            net_station = await web_up(net_station, ssid, password)
            print("WiFi restarted")

        elif net_station and not net_station.isconnected():
            web_down()
            await asyncio.sleep_ms(1000)
            ssid, password = get_LAN_certs(CERTS_NAMESPACE)
            net_station = await web_up(net_station, ssid, password)
            print("WiFi reactivated")

        else:
            gc.collect()
            print(f"WiFi OK, RAM: {gc.mem_free()}")


if __name__ == "__main__":

    print("Testing web task for Bogan Radar")

    ## Get the task functions running, then twiddle thumbs until Control-C'ed.
    async def main():
        asyncio.create_task(check_WiFi_task())

        while True:
            await asyncio.sleep_ms(1000)


    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Ctrl-C ", end='')

    finally:
        asyncio.new_event_loop()             # Clear retained state
        web_down(None)
        print("Exiting")


