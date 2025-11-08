# Inexpensive Millimeter-wave Radar for Ocean Level Measurement

This project aims to create relatively simple and inexpensive designs for
measuring ocean level from piers, pilings, trees, or other relatively fixed
locations above the water.  The Ocean Science Hippies will use these
measurements to better understand the effects of tides, waves, tsunamis, and
other ocean phenomena on the coastal environment. 


## Hardware

The custom circuit board design currently used is in `hardware`. 

Mechanical part designs, including radar antennas and lenses, are currently 
being developed and will be added to this repository if and when we figure out
what on Earth we're doing. 


## Firmware

### ESP32

The design uses an ESP32 processor, chosen primarily for its WiFi and Bluetooth
capability, as the main controller.

The current ESP32 firmware is in the `WaterSense_Radar_JJH` directory. 
After cloning this repository, open the `WaterSense_Radar_JJH` directory in a
VSCode/PlatformIO workspace and you should be able to compile and run the
ESP32 firmware. 

### STM32 on XM125

The STM32 microcontroller on the XM125 radar can be given a custom program to
enable measurements at longer range (for tall piers and the like) or otherwise
optimized for our use. 

A temporary hack, used until we get the STM32 files set up as we prefer them and
decide how best to configure the radar, is to use a binary copy of the last 
working code, using an ST-Link2 programmer to flash it to the radar module. 

More details to be added soon. 


## Software

### Acconeer Tools

The radar modules can be tested with tools supplied by the manufacturer; this
is _really_ helpful for evaluating the effects of design changes.

#### The _Acconeer Exploration Tool_

This handy application consists of a firmware package and a PC application.
Although it's designed to be run on an official Acconeer development board, the
Exploration Tool can also be run on our boards.

Instructions for setting up the STM32 firmware and Python PC software are at
<https://github.com/acconeer/acconeer-python-exploration>.  Follow Acconeer's 
instructions **with the following exceptions:**

* We usually use leftover ST-Link2 programmers (from old STM32 Nucleo&trade; boards) 
  instead of fussing with DFU programming.  The 6-pin ST-Link2 header next to 
  the power and battery connectors is connected directly to the 6-pin `SWD` (CN4) 
  connector on the ST-Link2, matching the ends marked with dots or triangles. 
  The STM32 Cube Programmer&trade; is a convenient way to flash the binary file
  for the firmware to the STM32. 

* To use our boards with the Exploration Tool, first remove the ESP32 Feather 
  board, any FeatherWing accsesory boards, and the GPS module from the main radar 
  circuit board. Leaving the GPS antenna in place, if present, is OK. 
  Then attach a connector (header pins or sockets) to the three-pin header pad
  marked `STM32 UART0` in the area where the GPS board sits.  Connect a USB to
  RS-232 serial adapter to STM32 UART0 pins, remembering the annoying RS-232 
  standard where RXD of one device must connect to TXD of the other. 
  The Exploration Tool should now be able to connect to the XM125 as if the
  XM125 were on the official evaluation board. 

<!-- 
* Use ST-Link to load firmware
* Connect USB-Serial to ST's UART
* Set up Exploration Tool on PC
--> 
