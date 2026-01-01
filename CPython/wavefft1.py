#!/usr/bin/env python3
# @file wavefft1.py
# Simple program to make a power spectrum from a CSV file written by the wave
# radar analysis program. This file doesn't deal with the *.sacsv files that
# are written by the Bogan Radar device; those files must first be processed 
# with the wave radar program, using the -c option to save heights to a CSV
# file.
#
# NON-UNIFORM SAMPLING VERSION
#
# @author ChatGPT and Spluttflob
# @date   2025-Dec-17

#!/usr/bin/env python3
import sys
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import lombscargle


def load_time_series(csv_path, delimiter=",", skiprows=0):
    """
    Load time (s) and height from a CSV file with two columns.
    Returns:
        t: 1D numpy array of times (seconds)
        x: 1D numpy array of heights
    """
    data = np.loadtxt(csv_path, delimiter=delimiter, skiprows=skiprows)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError("CSV must have at least two columns: time, height")

    t = data[:, 0]
    x = data[:, 1]

    # Ensure sorted by time
    sort_idx = np.argsort(t)
    t = t[sort_idx]
    x = x[sort_idx]

    return t, x


def compute_lomb_scargle_spectrum(t, x, f_min=None, f_max=None, n_freqs=2000):
    """
    Compute a spectrum for non-uniformly sampled data using Lomb–Scargle.

    Args:
        t: 1D array of times (seconds), non-uniform allowed
        x: 1D array of signal values (height)
        f_min: minimum frequency in Hz (if None, choose from total duration)
        f_max: maximum frequency in Hz (if None, based on smallest dt)
        n_freqs: number of frequency points

    Returns:
        freqs: 1D array of frequencies (Hz)
        amp: 1D array of "amplitude" per frequency bin (approx)
        power: 1D array of Lomb–Scargle power
    """
    t = np.asarray(t)
    x = np.asarray(x)

    # Remove mean
    x = x - np.mean(x)

    total_time = t.max() - t.min()
    if total_time <= 0:
        raise ValueError("Time array must span a non-zero interval.")

    # Choose frequency range if not provided
    if f_min is None:
        # Very low, but > 0 to avoid numerical weirdness at exactly 0
        f_min = 1.0 / (10.0 * total_time)

    if f_max is None:
        # Use smallest time step to estimate an effective Nyquist frequency
        dt = np.diff(t)
        dt_min = np.min(dt)
        f_max = 0.5 / dt_min

    freqs = np.linspace(f_min, f_max, n_freqs)
    angular_freqs = 2.0 * np.pi * freqs

    # Lomb–Scargle returns a normalized power for each angular frequency
    power = lombscargle(t, x, angular_freqs, precenter=True, normalize=True)

    # Convert power to a rough amplitude estimate.
    # Scaling is somewhat convention-dependent; this gives a relative amplitude.
    amp = np.sqrt(2 * power)

    return freqs, amp, power


def main():
    if len(sys.argv) < 2:
        print("Usage: python spectrum_nonuniform.py <data.csv>", file=sys.stderr)
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"File not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    # Adjust skiprows if your CSV has a header
    t, x = load_time_series(csv_path, delimiter=",", skiprows=1)

    print(f"Loaded {len(x)} samples.")
    print(f"Time span: {t.min():.6f} s to {t.max():.6f} s "
          f"(duration = {t.max() - t.min():.6f} s)")

    # Compute spectrum for non-uniform sampling
    freqs, amp, power = compute_lomb_scargle_spectrum(t, x)

    # Plot amplitude spectrum
    plt.figure()
    plt.plot(freqs, amp)
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Amplitude (relative)")
    plt.title(f"Lomb–Scargle Amplitude Spectrum of {csv_path.name}")
    plt.grid(True)
    plt.tight_layout()

    ## Optionally: plot power spectrum, too
    #plt.figure()
    #plt.plot(freqs, power)
    #plt.xlabel("Frequency (Hz)")
    #plt.ylabel("Power (normalized)")
    #plt.title(f"Lomb–Scargle Power Spectrum of {csv_path.name}")
    #plt.grid(True)
    #plt.tight_layout()

    plt.show()


if __name__ == "__main__":
    main()
