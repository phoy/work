#!/usr/bin/env python3
"""
Script to find the latest numbered model file and create the next version
"""

import sys
import os
import subprocess
import re
from pathlib import Path


def main():
    # Check if exactly one argument is provided
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <model>", file=sys.stderr)
        sys.exit(1)

    model = sys.argv[1]

    # Convert model to uppercase for the output filename
    model_upper = model.upper()

    # Convert model to lowercase for case-insensitive searching
    model_lower = model.lower()

    # Search for files containing the model name in current directory (case-insensitive)
    found_file = False
    for file in os.listdir('.'):
        file_lower = file.lower()
        if model_lower in file_lower:
            found_file = True
            break

    if not found_file:
        print(f"No files found containing '{model}' - will create {model_upper}-001")
        highest_num = 0
    else:
        # Find the highest numbered file matching pattern model-NNN (001-999) case-insensitively
        highest_num = 0

        for file in os.listdir('.'):
            file_lower = file.lower()

            # Check if file matches pattern model-NNN (case-insensitive)
            match = re.search(rf'{re.escape(model_lower)}-(\d{{3}})', file_lower)
            if match:
                num = match.group(1)
                # Convert to integer (automatically removes leading zeros)
                num_int = int(num)

                if num_int > highest_num:
                    highest_num = num_int

    # Calculate next number
    next_num = highest_num + 1

    # Check if we've exceeded 999
    if next_num > 999:
        print(f"Error: Maximum number (999) reached for model '{model}'", file=sys.stderr)
        sys.exit(1)

    # Format as 3-digit number with leading zeros
    next_num_formatted = f"{next_num:03d}"

    # Create new filename with uppercase model name
    new_filename = f"{model_upper}-{next_num_formatted}"

    # Create the new file
    Path(new_filename).touch()

    # Get battery device
    try:
        bat_result = subprocess.run(['upower', '-e'], capture_output=True, text=True, check=True)
        bat_lines = [line for line in bat_result.stdout.split('\n') if 'battery_BAT' in line]
        BAT = bat_lines[0] if bat_lines else None
    except (subprocess.CalledProcessError, IndexError):
        BAT = None

    # Run hw-probe
    try:
        subprocess.run(['sudo', '-E', 'hw-probe', '-probe'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Warning: hw-probe -probe failed: {e}", file=sys.stderr)

    # Append hw-probe output to file
    try:
        with open(new_filename, 'a') as f:
            result = subprocess.run(['sudo', 'hw-probe', '--show', '--verbose'],
                                    capture_output=True, text=True, check=True)
            f.write(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Warning: hw-probe --show failed: {e}", file=sys.stderr)

    # Add separator
    with open(new_filename, 'a') as f:
        f.write("\n\n")
        f.write("-" * 83 + "\n")
        f.write("\n\n")

    # Append battery information
    if BAT:
        try:
            with open(new_filename, 'a') as f:
                result = subprocess.run(['upower', '-i', BAT],
                                        capture_output=True, text=True, check=True)
                f.write(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Warning: upower failed: {e}", file=sys.stderr)

    # Launch snapshot in background
    try:
        subprocess.Popen(['snapshot'])
    except FileNotFoundError:
        print("Warning: 'snapshot' command not found", file=sys.stderr)

    # Launch gnome-control-center in background
    try:
        subprocess.Popen(['/usr/bin/gnome-control-center'])
    except FileNotFoundError:
        print("Warning: 'gnome-control-center' not found", file=sys.stderr)

    # Display file contents
    with open(new_filename, 'r') as f:
        print(f.read())

    print(f"Created: {new_filename}")


if __name__ == "__main__":
    main()
