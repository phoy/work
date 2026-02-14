#!/bin/bash
#
# Script to find the latest numbered model file and create the next version
#

# Check if exactly one argument is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <model>" >&2
    exit 1
fi

model="$1"

# Convert model to uppercase for the output filename
model_upper=$(echo "$model" | tr '[:lower:]' '[:upper:]')

# Convert model to lowercase for case-insensitive searching
model_lower=$(echo "$model" | tr '[:upper:]' '[:lower:]')

# Search for files containing the model name in current directory (case-insensitive)
found_file=false
for file in *; do
    file_lower=$(echo "$file" | tr '[:upper:]' '[:lower:]')
    if [[ "$file_lower" == *"$model_lower"* ]]; then
        found_file=true
        break
    fi
done

if [ "$found_file" = false ]; then
    echo "No files found containing '$model' - will create ${model_upper}-001"
    highest_num=0
else
    # Find the highest numbered file matching pattern model-NNN (001-999) case-insensitively
    highest_num=0

    for file in *; do
        file_lower=$(echo "$file" | tr '[:upper:]' '[:lower:]')

        # Check if file matches pattern model-NNN (case-insensitive)
        if [[ "$file_lower" =~ $model_lower-([0-9]{3}) ]]; then
            num="${BASH_REMATCH[1]}"
            # Remove leading zeros for numeric comparison
            num_int=$((10#$num))

            if [ $num_int -gt $highest_num ]; then
                highest_num=$num_int
            fi
        fi
    done
fi

# Calculate next number
next_num=$((highest_num + 1))

# Check if we've exceeded 999
if [ $next_num -gt 999 ]; then
    echo "Error: Maximum number (999) reached for model '$model'" >&2
    exit 1
fi

# Format as 3-digit number with leading zeros
next_num_formatted=$(printf "%03d" $next_num)

# Create new filename with uppercase model name
new_filename="${model_upper}-${next_num_formatted}"

# Create the new file
touch "$new_filename"

BAT=$(upower -e | grep battery_BAT)

sudo -E hw-probe -probe

sudo hw-probe --show --verbose >> $new_filename

echo -e "\n\n" >> $new_filename
echo "-----------------------------------------------------------------------------------" >> $new_filename
echo -e "\n\n" >> $new_filename

upower -i $BAT >> $new_filename

exec snapshot &

exec /usr/bin/gnome-control-center &

cat $new_filename

echo "Created: $new_filename"