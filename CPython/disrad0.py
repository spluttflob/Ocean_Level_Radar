## @file disrad0.py
#  Display wave radar data from an SD card or file saved from MQTT connection.
#  
#  @author Spluttflob
#  @date   2025-Nov-29  Original file
#  @copyright (c) 2025 by Spluttflob, released under the GPL V3

import time
from matplotlib import pyplot
import argparse

# Get the name of the file whose data is to be plotted from the command
parser = argparse.ArgumentParser(description='Wave Radar Data Plot Parameters')
parser.add_argument("input_file", help="Name of radar data file to read")
args = parser.parse_args()

times = []
maxhits = 0

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
distances = [[] for _ in range(maxhits)]
strengths = [[] for _ in range(maxhits)]

# For each distance data line, get data unless "NR" shows no radar return
for line in lines:
    if line[0] == 'D' and not "NR" in line:
        # The line should hold time; dist, strength; dist, strength; ...
        # so parts[0] is time and parts[1], ... are (dist, strength) pairs
        parts = line.lstrip('D').split(';')

        try:
            time_parts = [float(x) for x in parts[0].split(':')]
            when = time_parts[0] + time_parts[1] / 60 + time_parts[2] / 3600
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
                    times[index].append(when)
                    distances[index].append(dist)
                    strengths[index].append(strn)

# Plot the data in a handy Matplotlib window for viewing, saving, etc.
# This simple program assumes all the data to be shown was taken on the same day
figs, axes = pyplot.subplots(2)
for time_series, dist_series, strn_series in zip(times, distances, strengths):
    print(f"Plot: {len(time_series)} x {len(dist_series)} points")
    axes[0].plot(time_series, dist_series, '.')
    axes[1].plot(time_series, strn_series, '.')
for ax in axes: ax.grid(True, linestyle='--')
axes[0].set_title("Radar Distance Measurements")
axes[1].set_xlabel("Time of Day (hrs)")
axes[0].set_ylabel("Distance (m)")
axes[1].set_ylabel("Signal Strength (dB?)")
pyplot.show()

