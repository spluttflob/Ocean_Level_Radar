## @file disrad0.py
#  Display wave radar data from an SD card or file saved from MQTT connection.
#  This version attempts to convert radar readings to actual water levels,
#  involving highly complex mathematics...subtraction from a constant.
#  
#  @author Spluttflob
#  @date   2025-Nov-29  Original file
#  @copyright (c) 2025 by Spluttflob, released under the GPL V3

import time
import datetime
import argparse
from matplotlib import pyplot
import matplotlib.dates as mdates


# Approximately how high the sensor is above the water, in meters
SENSOR_HEIGHT = 4.4

# Minimum and maximum extents of Y axis of tide plot, in feet
PLOT_Y_MIN = -2.0
PLOT_Y_MAX = 8.0

# Feet per meter conversion factor
FEET_PER_METER = 3.28084

# Get the name of the file whose data is to be plotted from the command
parser = argparse.ArgumentParser(description='Wave Radar Data Plot Parameters')
parser.add_argument("input_file", help="Name of radar data file to read")
args = parser.parse_args()

times = []
maxhits = 0


## Read a line of data from the GPS and get date, time, and location therefrom
#  @param line One line of text in a string
#  @returns A list of date, time, time structure, latitude, longitude, altitude
#           or a list of Nones if parsing the line doesn't work
def read_GPS_line(line: str) -> list:
    try:
        parts = line.lstrip('G').split(',')
        datestr = parts[0]
        timestr = parts[1]
        structime = time.strptime(f"{datestr},{timestr}", "%Y-%m-%d,%H:%M:%S")
        latitude = float(parts[3])
        if parts[2] == 'S':
            latitude = -latitude
        longitude = float(parts[5])
        if parts[4] == 'W':
            longitude = -longitude
        altitude = float(parts[6].strip())
    except (ValueError, IndexError) as rats:
        print(f"Bad line '{line}', error {rats}")
        return [None, None, None, None, None, None]
    else:
        return [datestr, timestr, structime, latitude, longitude, altitude]


#-------------------------------------------------------------------------------

# Read the file into a list of lines with which we'll work
with open(args.input_file, 'r') as dfile:
    lines = dfile.readlines()

# First find the maximum number of radar hits on any line
for line in lines:
    if line[0] == 'D':
        # Break line into time, then (dist, sig_strength) pairs
        parts = line.lstrip('D').split(';')
        n_hits = len(parts) - 1
        if n_hits > maxhits:
            maxhits = n_hits

    # TODO: Deal with GPS lines here

print(f"Longest line: {maxhits} hits")

# Set up arrays for plot lines
times = [[] for _ in range(maxhits)]
datetimes = [[] for _ in range(maxhits)]
distances = [[] for _ in range(maxhits)]
strengths = [[] for _ in range(maxhits)]

# [Year, Month, Day] to get date from G*** lines and use it on D*** lines
latest_gps_datetime = [None, None, None, None, None, None]

# For each distance data line, get data unless "NR" shows no radar return
for line in lines:
    # Ignore empty lines
    if not line:
        pass

    elif line[0] == 'G':
        # These lines hold date, time, and location from the GPS
        try_datetime = read_GPS_line(line)
        if try_datetime[0] is not None:
            latest_gps_datetime = try_datetime

    elif line[0] == 'D' and not "NR" in line and latest_gps_datetime[0] is not None: #############
        # The line should hold time; dist, strength; dist, strength; ...
        # so parts[0] is time and parts[1], ... are (dist, strength) pairs
        parts = line.lstrip('D').split(';')

        try:
            # Get the time of day as hours after midnight
            time_parts = [float(x) for x in parts[0].split(':')]
            when = time_parts[0] + time_parts[1] / 60 + time_parts[2] / 3600
            # Also get time of day as a time.struct_time object
            when_struct = time.strptime(f"{latest_gps_datetime[0]},{parts[0]}",
                                        "%Y-%m-%d,%H:%M:%S")
            dt = datetime.datetime(when_struct.tm_year, when_struct.tm_mon, when_struct.tm_mday, when_struct.tm_hour, when_struct.tm_min, when_struct.tm_sec)
            #dt = datetime.fromtimestamp(calendar.timegm(when_struct))
        except ValueError as ohnoes:
            print(f"Bad time: {parts[0]}")
        else:
            for index, part in enumerate(parts[1:]):
                try:
                    dist_s, strn_s = part.strip().split(',')
                    dist = float(dist_s)
                    strn = float(strn_s)
                except ValueError as oops:
                    print(f"Bad data: {parts}")
                else:
                    if when_struct.tm_year > 2024:
                        times[index].append(when)                      # For now, ignore lines before GPS lock
                        datetimes[index].append(dt)
                        distances[index].append(dist)
                        strengths[index].append(strn)
                        #print(when_struct)                                    ############################




#exit()

# A formatter for dates on a horizontal axis
myFmt = mdates.DateFormatter('%m-%d\n%H:%M')

# Plot the data in a handy Matplotlib window for viewing, saving, etc.
figs, axes = pyplot.subplots(2)

heights_meters = [SENSOR_HEIGHT - dist for dist in distances[0]]
heights_feet = [dist * FEET_PER_METER for dist in heights_meters]

axes[0].plot(datetimes[0], heights_feet, '.')
axes_m = axes[0].twinx()
axes[1].plot(datetimes[0], strengths[0], '.')

for ax in axes: ax.grid(True, linestyle='--')
axes[0].set_title("Radar Distance Measurements")
axes[0].xaxis.set_major_formatter(myFmt)
axes[0].set_ylabel("Height Above Mean Low (ft)")
axes_m.set_ylabel("Height Above Mean Low (m)")
axes[0].set_ylim(PLOT_Y_MIN, PLOT_Y_MAX)
axes_m.set_ylim(PLOT_Y_MIN / FEET_PER_METER, PLOT_Y_MAX / FEET_PER_METER)
axes[1].set_xlabel("Time of Day (hrs)")
axes[1].xaxis.set_major_formatter(myFmt)
axes[1].set_ylabel("Signal Strength (dB?)")
pyplot.show()

