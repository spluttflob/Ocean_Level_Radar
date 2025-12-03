## @file radgps0.py
#  Display GPS data from an SD card or file saved from MQTT connection with the
#  wave radar.
#  
#  @author Spluttflob
#  @date   2025-Nov-29  Original file
#  @copyright (c) 2025 by Spluttflob, released under the GPL V3

import time
import argparse
from matplotlib import pyplot
from matplotlib.ticker import FormatStrFormatter

# Get the name of the file whose data is to be plotted from the command
parser = argparse.ArgumentParser(description='Wave Radar GPS Parameters')
parser.add_argument("input_file", help="Name of radar data file to read")
args = parser.parse_args()

# Read the file into a list of lines with which we'll work
with open(args.input_file, 'r') as dfile:
    lines = dfile.readlines()

# Arrays in which to store coordinates
times = []
latitudes = []
longitudes = []
altitudes = []

# Get data from only those lines which begin with a letter G
for line in lines:
    if line[0] == 'G':
        parts = line.strip('G').split(',')

        try:
            # Get the date and make sure it's recent enough to be valid. When
            # some GPS modules start, they'll give what as_GPS claims to be
            # valid data, but it's not, and the year is 1999 or some silliness
            year = int(parts[0].split('-')[0])

            # Get the time of day in hours for plotting altitude vs. day time
            time_parts = [float(x) for x in parts[1].split(':')]
            when = time_parts[0] + time_parts[1] / 60 + time_parts[2] / 3600

            # Get the coordinates
            lati = float(parts[3])
            longi = -float(parts[5])        # More negative, more West for USA
            alti = float(parts[6])
        except ValueError as oops:
            print(f"Bad line '{line}': {oops}")
        else:
            if year > 2024:
                times.append(when)
                latitudes.append(lati)
                longitudes.append(longi)
                altitudes.append(alti)

# Just wondering...
avg_string = f"N{sum(latitudes) / len(latitudes):.6f}," \
             f"W{-sum(longitudes)/len(longitudes):.6f}," \
             f"{sum(altitudes) / len(altitudes):.1f} m"

# Plot the data in a handy Matplotlib window for viewing, saving, etc.
figs, axes = pyplot.subplots(2)

# Set the format for tick labels (not clunky scientific notation)
axes[0].xaxis.set_major_formatter(FormatStrFormatter('%.6f'))
axes[0].yaxis.set_major_formatter(FormatStrFormatter('%.6f'))

# Plot the data
axes[0].plot(longitudes, latitudes, '.')
axes[1].plot(times, altitudes, '.')
axes[1].set_xlim(0.0, 24.0)

# Set grids on
for ax in axes:
    ax.grid(True, linestyle='--')

# Label things to prevent the problem shown in https://xkcd.com/833/
axes[0].set_title("Bogan Radar GPS Coordinates, Averages " + avg_string)
axes[0].set_xlabel("Longitude (deg)")
axes[0].set_ylabel("Latitude (deg)")
axes[1].set_xlabel("Time of Day (hrs)")
axes[1].set_ylabel("Altitude (m)")
pyplot.show()
