![Project logo](Bogan_Radar_Logo_1_inv.png)

This project aims to create simple and inexpensive designs for measuring 
ocean level from piers, pilings, trees, or other relatively fixed
locations above the water.  THe measurements are to be taken quickly enough
that ocean waves and perhaps wind chop can be resolved. 
Ocean Science Hippies will use these measurements to better understand the 
effects of tides, waves, tsunamis, sea level rise, and other ocean phenomena 
on the coastal environment. 


## Hardware

The custom circuit board design currently used is in `hardware`. 

Mechanical part designs, including radar antennas and lenses, are currently 
being developed and will be added to this repository if and when we figure out
what on Earth we're doing. 


## Firmware

The software currently being developed uses a MicroPython program running on an
ESP32 as the overall controller, data logging, and network interface computer.
There is an STM32 microcontroller in the XM125 radar module which runs it own
software which is written in C. 

### ESP32 Firmware

There are two versions of the software which have been developed. The first
version is written in C++, and the second (and currently being worked on) 
version is in MicroPython.

#### C++

The C++ ESP32 firmware is in the `WaterSense_Radar_JJH` directory. 
After cloning this repository, open the `WaterSense_Radar_JJH` directory in a
VSCode/PlatformIO workspace and you should be able to compile and run the
ESP32 firmware. It requires custom firmware to be running on the STM32 in
the XM125 module.

#### MicroPython

For rapid development and testing, MicroPython firmware is provided in the
`MicroPython` folder.  MicroPython for the ESP32 can be downloaded from:  
<https://micropython.org/download/ESP32_GENERIC/>  
The latest release of the `ESP32_GENERIC` software is recommended for our
Feather circuit boards. 

With MicroPython installed on the ESP32, all the Python source files should 
be copied to the root directory of the ESP32's MicroPython filesystem, and 
`radar.cfg` should be copied to the root directory of the SD card which will 
be used for data logging. Configuration of the system for use at specific 
sites should require editing of `main.py` and `radar.cfg` only. The 
main Python file is edited to disable unneeded tasks; for example, the MQTT 
task should be turned off (just comment out the `asyncio.create_task()` line)
at sites where WiFi access and AC power are not available. The radar's range, 
frequency of data collection, and similar configurations are set in `radar.cfg`
which can be edited on the SD card. 

##### MicroPython File List

The following files need to be uploaded to the root directory of the ESP32's
MicroPython filesystem:

* `as_GPS.py` -- The asyncio GPS file from 
  <https://github.com/peterhinch/micropython-async/tree/master>
  or use the older, unmaintained copy here.
  
* `as_xm125_distance.py` -- From this repository.

* `main.py` -- From this repository.

* `mqtt_as.py` -- The asyncio MQTT client from
  <https://github.com/peterhinch/micropython-mqtt>
  or use the older, unmaintained copy here

* `pcf8523.py` -- Driver for the PCF8523 real-time clock on the Adalogger.
  Modified from others' work; use the copy here.
  
* `queue.py` -- From the standard MicroPython queues at 
  <https://github.com/peterhinch/micropython-async/tree/master>
  again, with an old local copy here for convenience.

* `task_gps.py` -- GPS task file from this repository.

* `task_mqtt.py` -- MQTT task (used if you have AC and WiFi) from this repository.

* `task_sd_card.py` -- SD card task from this repository.

* `radar.cfg` -- The configuration file for each site, put on the SD card.


#### Configuration with `radar.cfg`

The configuration file is a regular text file saved on the data logging SD card.
A typical configuration file might look as follows (for 2025-Dec version of the 
software; configurations are expected to change as the software is improved):
```txt
# Configuration file for Bogan Radar

Site Name:           My_Bench   # Name of site; should be one word (no spaces)
Beginning Distance:  2.0        # Beginning distance (m)
Ending Distance:     8.0        # Ending distance (m)
Sensitivity:         500        # Peak threshold sensitivity
Time Per Point:      5.0        # Time between data points (seconds)
Awake Time:          0.0        # Time taking data, sec., or 0.0 for always awake
Cycle Time:          0.0        # Total on-off cycle time, or 0.0 for always awake
```

_With changes to the value of `SD_DIR` in `task_sd_card.py`, the configuration
file could be saved in the ESP32's built-in flash; this would make reconfiguration 
a little harder but protect the configuration from SD card corruption due to power 
loss, somebody hot swapping the card (bad idea), etc._

If data is sent through MQTT, the MQTT topic is made by appending the site name
from the configuration file to `bogan_radar/`. 


### STM32 on XM125 Firmware

The STM32 microcontroller on the XM125 radar can be given a custom program to
optimize the radar module for our use. We have two setups available:

* When using the MicroPython firmware on the ESP32, the XM125's STM32 must be
  flashed with Acconeer's standard distance measurement application.
  The Acconeer software is available from:  
  <https://developer.acconeer.com/home/a121-docs-software/xm125-xe125/>  
  (You have to enroll with a developer account, but at least it's free to do 
  so.)

* When using the C++ firmware from directory `WaterSense_Radar_JJH` for the 
  ESP32, the source code for the STM32 microcontroller in the XM125 radar 
  module from subdirectory `xm125` must be compiled and flashed to the XM125.
  Compiling the XM125 STM32 code is a bit of a hassle, so we can use a binary 
  copy of the last working code.
  
* It's convenient to use an ST-Link2 programmer to flash the STM32 code to the 
  radar module. There is an ST-Link2 compatible 6-pin programming header near
  the screw terminal on the main circuit board, and there are two pushbuttons
  on the board to reset the STM32 and to put the STM32 in bootloader mode if 
  needed. 


## PC Software

### The _Acconeer Exploration Tool_

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
  If you're a civil, environmental, or mechanical engineer: Don't forget the 
  ground wire!  `:)`
  The Exploration Tool should now be able to connect to the XM125 as if the
  XM125 were on the official evaluation board. 

<!-- 
* Use ST-Link to load firmware
* Connect USB-Serial to ST's UART
* Set up Exploration Tool on PC
--> 

### Plotting MicroPython Data

If MicroPython is used, data will be saved in a Semicolon And Comma Separated
Variable (`.sacsv`) format. Some simple programs to plot data in this form are
being developed and can be found in the `CPython` directory. 

### Plotting C++ Firmware Data

Some more fully Python developed programs to analyze data from the C++ firmware 
are in the `ESP32_to_Python_GUI` directory. 

It is our intention to merge the capabilities of the CPython programs from
the `CPython` and `ESP32_to_Python_GUI` directories to create especially 
convenient and flexible data analysis and plotting applications. 


## References

* A Masters thesis utilizing ultrasonic rather than radar sensors which gives
  some perspective to the project:  
  <https://digitalcommons.calpoly.edu/theses/2745/>

