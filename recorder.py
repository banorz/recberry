#!/usr/bin/env python3

import os
import re
import subprocess
import time
import threading
from datetime import datetime
from evdev import InputDevice, categorize, ecodes
import pwd

# --- Configuration ---
# The path to the keyboard device.
# To make the script robust, specify the exact path to your macro keyboard.
# 1. Connect your keyboard.
# 2. Run this command in your SSH terminal: ls -l /dev/input/by-id/
# 3. Find the entry for your keyboard (it will likely contain its name and end in '-kbd').
# 4. Copy the full path and paste it between the quotes below.
# Example: KEYBOARD_DEVICE_PATH = "/dev/input/by-id/usb-Logitech_USB_Receiver-event-kbd"
KEYBOARD_DEVICE_PATH = "/dev/input/by-id/usb-1189_8890-event-kbd"

# Fallback directory on the SD card if no USB drive is found
FALLBACK_STORAGE_PATH = "/home/banorz/recordings"

# Mount point for the USB drive
USB_MOUNT_POINT = "/mnt/usbrecorder"

# --- Globals for state management ---
recording_process = None
is_recording = False
recording_thread = None
# Add a global variable to remember the last used partition
LAST_USED_PARTITION = None

def find_keyboard_device():
    """
    Finds the event file for the keyboard.
    Prioritizes user-configured path, then attempts auto-detection.
    """
    global KEYBOARD_DEVICE_PATH
    if KEYBOARD_DEVICE_PATH and os.path.exists(KEYBOARD_DEVICE_PATH):
        print(f"Using pre-configured keyboard path: {KEYBOARD_DEVICE_PATH}")
        return

    print("Pre-configured keyboard not found or not set. Searching automatically...")
    try:
        base_path = "/dev/input/by-id/"
        for device_file in os.listdir(base_path):
            if device_file.endswith("-kbd"):
                KEYBOARD_DEVICE_PATH = os.path.join(base_path, device_file)
                print(f"Auto-detected keyboard at: {KEYBOARD_DEVICE_PATH}")
                return
    except FileNotFoundError:
        pass # Fallback to next method

    print("Auto-detection via /dev/input/by-id/ failed. Falling back to /dev/input/eventX.")
    for i in range(10):
        path = f"/dev/input/event{i}"
        try:
            device = InputDevice(path)
            if ecodes.EV_KEY in device.capabilities():
                KEYBOARD_DEVICE_PATH = path
                print(f"Found a keyboard-like device at {path}")
                return
        except (OSError, IOError):
            continue

    print("FATAL: No keyboard device could be found. Exiting.")
    exit(1)

def set_led_state(state):
    """
    Controls the state of the activity LED.
    It automatically detects if the LED is named 'ACT' or 'led0'.
    """
    # Find the correct path for the activity LED, preferring 'ACT'
    led_base_path = ""
    if os.path.exists("/sys/class/leds/ACT"):
        led_base_path = "/sys/class/leds/ACT"
    elif os.path.exists("/sys/class/leds/led0"):
        led_base_path = "/sys/class/leds/led0"
    else:
        print("Warning: Could not find a path for the activity LED (ACT or led0).")
        return

    led_trigger_path = os.path.join(led_base_path, "trigger")
    led_delay_on_path = os.path.join(led_base_path, "delay_on")
    led_delay_off_path = os.path.join(led_base_path, "delay_off")

    try:
        if state == "blink":
            print("Setting LED to fast blink.")
            subprocess.run(["sudo", "sh", "-c", f"echo timer > {led_trigger_path}"], check=True)
            subprocess.run(["sudo", "sh", "-c", f"echo 50 > {led_delay_on_path}"], check=True)
            subprocess.run(["sudo", "sh", "-c", f"echo 50 > {led_delay_off_path}"], check=True)
        elif state == "default":
            print("Resetting LED to default.")
            subprocess.run(["sudo", "sh", "-c", f"echo mmc0 > {led_trigger_path}"], check=True)
    except Exception as e:
        print(f"Error controlling LED: {e}")

def get_last_used_partition():
    return os.environ.get("LAST_USED_PARTITION")

def set_last_used_partition(value):
    if value:
        os.environ["LAST_USED_PARTITION"] = value
    elif "LAST_USED_PARTITION" in os.environ:
        del os.environ["LAST_USED_PARTITION"]


def mount_usb_drive():
    """
    Finds the correct USB partition, unmounts it, and remounts it with correct permissions.
    It now remembers the last used partition to handle repeated recordings without unplugging.
    """

    print("Attempting to mount USB drive...")
    null = None # This handles the 'null' value from JSON output of lsblk
    try:
        lsblk_output = subprocess.check_output(['lsblk', '-J', '-o', 'NAME,MOUNTPOINT,TYPE,TRAN']).decode()
        devices = eval(lsblk_output)['blockdevices']
        
        target_partition = None
        new_automount_found = False
        
        for device in devices:
            if device.get('tran') == 'usb' and 'children' in device:
                # First pass: look for an already-mounted partition (indicates a new drive)
                for part in device['children']:
                    if part.get('type') == 'part' and part.get('mountpoint') is not None:
                        target_partition = f"/dev/{part['name']}"
                        set_last_used_partition(target_partition)  # Store this as the last used partition
                       
                        new_automount_found = True
                        print(f"Found new auto-mounted partition: {target_partition}. Storing as last used.")
                        break
                if new_automount_found:
                    break

        # If no *new* auto-mounted drive was found, check if we remember a previously used one
        if not target_partition and get_last_used_partition():
            # Verify the last used partition still exists
            if os.path.exists(get_last_used_partition()):
                print(f"No new auto-mounted drive found. Re-using last known partition: {get_last_used_partition()}")
                target_partition = get_last_used_partition()
            else:
                print(f"Last used partition {get_last_used_partition()} no longer exists. Clearing memory.")
                set_last_used_partition(None)
                


        # Final fallback if we have no memory and nothing is auto-mounted
        if not target_partition:
             for device in devices:
                if device.get('tran') == 'usb' and 'children' in device:
                    if device['children']:
                        # Iterate through partitions to find one that is not already our mount point
                        for part_info in device['children']:
                            if part_info.get('type') == 'part':
                                current_part_dev = f"/dev/{part_info['name']}"
                                if part_info.get('mountpoint') != USB_MOUNT_POINT: # Avoid re-selecting if already mounted by us
                                    target_partition = current_part_dev
                                    set_last_used_partition(target_partition)  # Store for next time
                                    print(f"No auto-mounted or valid last-used partition found. Falling back to: {target_partition}")
                                    break # Found a suitable partition
                        if target_partition: # If we found one in the inner loop
                            break 
                if target_partition: # If we found one in the outer loop
                    break
        
        # Now, mount the selected partition
        if target_partition:
            print(f"Proceeding with partition: {target_partition}.")
            
            # Check if it's already mounted at our desired location
            is_already_mounted_correctly = False
            if os.path.ismount(USB_MOUNT_POINT):
                try:
                    df_output = subprocess.check_output(['df', '--output=source', USB_MOUNT_POINT], text=True).splitlines()
                    if len(df_output) > 1 and df_output[1].strip() == target_partition:
                        is_already_mounted_correctly = True
                        print(f"{target_partition} is already mounted at {USB_MOUNT_POINT}.")
                except Exception as e:
                    print(f"Could not verify if {USB_MOUNT_POINT} is correctly mounted: {e}")

            if not is_already_mounted_correctly:
                print(f"Unmounting {target_partition} if mounted elsewhere, or {USB_MOUNT_POINT} if occupied...")
                subprocess.run(['sudo', 'umount', target_partition], stderr=subprocess.DEVNULL, check=False)
                if os.path.ismount(USB_MOUNT_POINT): # If our mount point is still mounted by something else
                     subprocess.run(['sudo', 'umount', USB_MOUNT_POINT], stderr=subprocess.DEVNULL, check=False)

            if not os.path.exists(USB_MOUNT_POINT):
                print(f"Creating mount point: {USB_MOUNT_POINT}")
                subprocess.run(['sudo', 'mkdir', '-p', USB_MOUNT_POINT], check=True)
            
            user_info = pwd.getpwuid(os.geteuid()) # Get current user's info
            uid, gid = user_info.pw_uid, user_info.pw_gid
            
            print(f"Mounting {target_partition} to {USB_MOUNT_POINT} with ownership for UID={uid}, GID={gid}")
            mount_cmd = ['sudo', 'mount', '-o', f'uid={uid},gid={gid},umask=007,noatime,nodiratime', target_partition, USB_MOUNT_POINT]
            mount_result = subprocess.run(mount_cmd, capture_output=True, text=True)

            if mount_result.returncode == 0:
                print("Mount successful.")
                return USB_MOUNT_POINT
            else:
                print(f"Error mounting USB drive: {mount_result.stderr.strip()}")
                # If mount fails, ensure LAST_USED_PARTITION is cleared so we don't retry a bad one
                if get_last_used_partition() == target_partition:
                    set_last_used_partition(None)
                return None
        else:
            print("No suitable USB partition found to mount.")
            set_last_used_partition(None) # Clear memory if no partition found
            return None
    except Exception as e:
        print(f"An exception occurred while trying to mount USB drive: {e}")
        set_last_used_partition(None) # Clear memory on any exception
        return None

def unmount_usb_drive():
    """
    Safely unmounts the USB drive from our designated mount point.
    """
    if os.path.ismount(USB_MOUNT_POINT):
        print(f"Unmounting {USB_MOUNT_POINT}...")
        print("Syncing filesystems to ensure data is written...")
        subprocess.run(['sync'], check=False) # Best effort sync
        time.sleep(1) 
        
        unmount_result = subprocess.run(['sudo', 'umount', USB_MOUNT_POINT], capture_output=True, text=True)
        if unmount_result.returncode == 0:
            print("Unmount successful.")
        else:
            print(f"Warning: Could not unmount {USB_MOUNT_POINT}. Error: {unmount_result.stderr.strip()}")
            print("It might be busy. Trying lazy unmount...")
            lazy_unmount_result = subprocess.run(['sudo', 'umount', '-l', USB_MOUNT_POINT], capture_output=True, text=True)
            if lazy_unmount_result.returncode == 0:
                print("Lazy unmount initiated.")
            else:
                print(f"Lazy unmount also failed: {lazy_unmount_result.stderr.strip()}")
        
        time.sleep(1)
        print("It should now be safe to remove the drive if unmount was successful or initiated.")
    else:
        print(f"{USB_MOUNT_POINT} is not mounted, skipping unmount.")


def get_alsa_device_and_channels():
    """
    Determines the ALSA device string for the first available USB audio card
    and its maximum input channel count using /proc/asound.
    """
    print("Searching for a generic USB ALSA device...")
    alsa_device_for_ffmpeg = None
    channel_count = 0
    card_id_for_proc = None

    try:
        # 1. Find the USB card identifier (name or number) using 'arecord -l'
        arecord_l_output = subprocess.check_output(['arecord', '-l'], text=True, timeout=5)
        
        usb_cards_found = []
        # Regex to capture card number, card name, and check for "USB" in description or name
        card_pattern = re.compile(r"card\s+(\d+):\s*([A-Za-z0-9\-_]+)\s+\[(.*USB.*)\].*", re.IGNORECASE)
        card_pattern_alt = re.compile(r"card\s+(\d+):\s*(USB[A-Za-z0-9\-_]*)\s*\[.*", re.IGNORECASE) # For cards named "USB..."

        for line in arecord_l_output.splitlines():
            match = card_pattern.match(line)
            if not match:
                match = card_pattern_alt.match(line)
            
            if match:
                card_num_str = match.group(1)
                card_name_alsa = match.group(2) 
                full_desc = line.strip()
                usb_cards_found.append({'id_name': card_name_alsa, 'id_num': card_num_str, 'desc': full_desc})
                print(f"Found USB audio device: {full_desc} (ALSA Name: {card_name_alsa}, Number: {card_num_str})")

        if not usb_cards_found:
            print("Error: No USB audio card found in 'arecord -l' output. Is the device connected and recognized?")
            return None, 0

        # Select the first USB device found.
        selected_card = usb_cards_found[0] 
        card_name_for_ffmpeg = selected_card['id_name'] 
        card_id_for_proc = selected_card['id_num'] 

        # Use plughw with the ALSA card name (e.g., "USB", "Device", or the specific name)
        # This is generally preferred for ffmpeg as it handles format conversions.
        alsa_device_for_ffmpeg = f"plughw:CARD={card_name_for_ffmpeg},DEV=0"
        
        print(f"Selected USB audio device: {selected_card['desc']}")
        print(f"ALSA device string for ffmpeg: '{alsa_device_for_ffmpeg}'")

        # 2. Try to get channel count from /proc/asound/cardX/stream0 (capture stream)
        proc_info_found = False
        if card_id_for_proc:
            # Try common stream file names for capture capabilities
            proc_paths_to_check = [
                f"/proc/asound/card{card_id_for_proc}/stream0",
                f"/proc/asound/card{card_id_for_proc}/pcm0c/info" # 'c' for capture
            ]
            
            for proc_path in proc_paths_to_check:
                if os.path.exists(proc_path):
                    print(f"Reading ALSA info from {proc_path}")
                    try:
                        with open(proc_path, 'r') as f_proc:
                            content = f_proc.read()
                        
                        # Look for "Capture:" block and then "Channels:" within it
                        capture_section_match = re.search(r"Capture:(.*?)(Playback:|\Z)", content, re.DOTALL | re.IGNORECASE)
                        if capture_section_match:
                            capture_content = capture_section_match.group(1)
                            # More specific regex for channels within the capture section
                            match = re.search(r"Channels\s*:\s*(\d+)", capture_content, re.IGNORECASE)
                            if match:
                                channel_count = int(match.group(1))
                                print(f"Channels found via {proc_path}: {channel_count}")
                                proc_info_found = True
                                break # Found channels, no need to check other proc paths
                    except Exception as e:
                        print(f"Error reading or parsing {proc_path}: {e}")
                if proc_info_found:
                    break
        
        if proc_info_found and channel_count > 0:
            return alsa_device_for_ffmpeg, channel_count
        else:
            print(f"Warning: Could not determine channel count from /proc/asound/ for card {card_id_for_proc}.")
            print("Please ensure the ALSA driver for your USB device correctly reports channel information in /proc.")
            print("You might need to use 'arecord --dump-hw-params -D hw:CARD=USB,DEV=0' (or similar) manually to check capabilities.")
            return None, 0

    except FileNotFoundError:
        print("FATAL: 'arecord' command not found (for initial device listing). Is 'alsa-utils' installed?")
        return None, 0
    except subprocess.TimeoutExpired:
        print(f"Timeout while listing ALSA devices with 'arecord -l'.")
        return None, 0
    except subprocess.CalledProcessError as e:
        print(f"Error listing ALSA devices: {e.stderr if e.stderr else e.stdout}")
        return None, 0
    except Exception as e:
        print(f"An unexpected error occurred while getting ALSA device info: {e}")
        return None, 0

def record_audio(alsa_device, output_directory_path, channel_count):
    """
    Records each channel from the ALSA source into a separate mono FLAC file.
    """
    global recording_process, is_recording # Ensure is_recording is accessible
    print(f"Starting recording from ALSA device: {alsa_device}, saving FLAC files to directory: {output_directory_path}")
    
    command = [
        'ffmpeg',
        '-y', # Overwrite output files if they exist
        '-nostdin', # Prevent ffmpeg from trying to read from stdin
        '-f', 'alsa',
        '-thread_queue_size', '2048', # Increased for more stability
        '-channels', str(channel_count), # Total channels ALSA device provides
        '-ar', str(44100),      # Sample rate for ALSA input
        '-i', alsa_device,      # ALSA device string (e.g., "plughw:CARD=USB,DEV=0")
    ]
    
    # Add channel mapping and output files
    for i in range(channel_count):
        command.extend([
            '-map_channel', f'0.0.{i}', # Map input 0, stream 0, channel i
            # FLAC will inherit sample rate and format from the mapped input stream
            # Explicitly set sample rate for output stream just in case
            '-ar', str(44100), 
            '-c:a', 'flac',             # Codec for FLAC
            # Consider adding compression level for FLAC if needed, e.g. '-compression_level', '5'
            os.path.join(output_directory_path, f'ch{i+1}.flac') # Output filename
        ])

    print("Executing ffmpeg command...")
    print(f"Command: {' '.join(command)}") 
    
    try:
        # Start ffmpeg process
        recording_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Monitor for immediate errors
        time.sleep(2) # Give ffmpeg a moment to start
        if recording_process.poll() is not None: # Process has terminated
             stdout_output, stderr_output = recording_process.communicate()
             print(f"ffmpeg failed to start or exited unexpectedly (return code {recording_process.returncode}).")
             if stdout_output: print(f"ffmpeg stdout:\n{stdout_output.strip()}")
             if stderr_output: print(f"ffmpeg stderr:\n{stderr_output.strip()}")
             set_led_state('default')
             is_recording = False # Reset recording state
             recording_process = None # Clear the process variable
             return 

        # If no immediate error, the process is running.
        # We will wait for it in the main thread logic or stop_recording
        print(f"ffmpeg process started with PID: {recording_process.pid}")

        # The thread will now wait for the process to complete or be terminated.
        # stderr can be read continuously if needed for live error/status, but for now, we get it at the end.
        stdout_output, stderr_output = recording_process.communicate() # This blocks until process terminates

        # After process finishes (either by stop_recording or error)
        print(f"ffmpeg process finished with return code: {recording_process.returncode}")
        if stdout_output:
            print(f"ffmpeg stdout:\n{stdout_output.strip()}")
        if stderr_output:
            # Print stderr output regardless of return code for more info,
            # as ffmpeg sometimes prints useful info to stderr even on success.
            print(f"ffmpeg stderr:\n{stderr_output.strip()}")

        if recording_process.returncode != 0:
            if not (recording_process.returncode in [0, -2, -9, -15, 241, 247, 254]): # Common "normal" termination signals
                print(f"ffmpeg may have exited with an unexpected error code.")
        else:
            print("ffmpeg recording process completed successfully.")
        
    except FileNotFoundError:
        print("FATAL: ffmpeg command not found. Please install ffmpeg.")
        is_recording = False
        set_led_state('default')
    except Exception as e:
        print(f"Error during recording thread: {e}")
        is_recording = False
        set_led_state('default')
    finally:
        # This block runs whether the try block succeeded or failed.
        # Ensure recording_process is cleared if it's no longer valid.
        if recording_process and recording_process.poll() is not None:
            recording_process = None 
        
        # If the recording was stopped by an error in this thread, ensure is_recording is false
        # This check is important if stop_recording() wasn't the one to set is_recording to False
        if is_recording and (recording_process is None or recording_process.poll() is not None):
            print("Recording thread detected unexpected termination. Resetting state.")
            is_recording = False
            set_led_state('default')
        
        print("Recording audio function finished.")


def start_recording():
    global is_recording, recording_thread, recording_process
    if is_recording:
        print("Already recording.")
        return

    print("\n--- 'R' KEY PRESSED: INITIATING RECORDING ---")

    alsa_device, channel_count = get_alsa_device_and_channels()
    if not alsa_device or channel_count == 0:
        print("Aborting: Could not find or configure ALSA device.")
        set_led_state('default') # Reset LED if we abort early
        return

    storage_path = mount_usb_drive()
    if not storage_path:
        print("USB mount failed. Falling back to internal storage.")
        storage_path = FALLBACK_STORAGE_PATH
        if not os.path.exists(storage_path):
            try:
                os.makedirs(storage_path, exist_ok=True)
            except OSError as e:
                print(f"Error creating fallback directory {storage_path}: {e}")
                set_led_state('default')
                return


    is_recording = True # Set before starting thread
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_name = f"recording_{timestamp}"
    output_directory_path = os.path.join(storage_path, session_name)
    
    try:
        os.makedirs(output_directory_path, exist_ok=True)
    except OSError as e:
        print(f"Error creating output directory {output_directory_path}: {e}")
        is_recording = False # Reset state
        set_led_state('default')
        return

    print(f"Recording {channel_count} channels from ALSA device '{alsa_device}'. FLAC files will be saved in directory: {output_directory_path}")
    
    set_led_state('blink')

    # Ensure recording_process is None before starting a new one
    recording_process = None 
    recording_thread = threading.Thread(target=record_audio, args=(alsa_device, output_directory_path, channel_count))
    recording_thread.daemon = True 
    recording_thread.start()

def stop_recording():
    global is_recording, recording_process, recording_thread
    if not is_recording:
        # This can happen if recording failed to start properly but stop was called
        if recording_process and recording_process.poll() is None:
            print("Recording flag is false, but process exists. Attempting to stop rogue process...")
        elif recording_thread and recording_thread.is_alive():
            print("Recording flag is false, but thread exists. Attempting to join rogue thread...")
        else:
            print("Not currently recording.")
            unmount_usb_drive() # Attempt unmount even if not recording, in case it was left mounted
            set_led_state('default')
            return

    print("\n--- 'S' KEY PRESSED: STOPPING RECORDING ---")
    
    # Signal ffmpeg to terminate
    if recording_process and recording_process.poll() is None:
        print(f"Terminating ffmpeg process (PID: {recording_process.pid})...")
        recording_process.terminate() # Send SIGTERM
        # The communicate() in record_audio will now unblock and handle stderr
    
    # Wait for the recording thread to finish
    # The thread itself waits for ffmpeg to exit via communicate()
    if recording_thread and recording_thread.is_alive():
        print("Waiting for recording thread to complete...")
        recording_thread.join(timeout=10) # Increased timeout
        if recording_thread.is_alive():
            print("Warning: Recording thread did not join in time. ffmpeg might be stuck.")
            # If thread is stuck, and process still exists, try a kill
            if recording_process and recording_process.poll() is None:
                print("Forcing kill on ffmpeg process as thread is unresponsive.")
                recording_process.kill()

    print("Recording stopped.")

    is_recording = False # Set state after thread/process are handled
    recording_process = None # Clear process
    recording_thread = None  # Clear thread
    
    set_led_state('default')
    
    unmount_usb_drive()

def main():
    find_keyboard_device() # Sets global KEYBOARD_DEVICE_PATH
    if not KEYBOARD_DEVICE_PATH:
        # find_keyboard_device now calls exit(1) if no device is found
        return 
        
    try:
        device = InputDevice(KEYBOARD_DEVICE_PATH)
        print(f"Successfully opened device. Listening for R and S keys on {device.name} ({KEYBOARD_DEVICE_PATH})...")
    except Exception as e:
        print(f"FATAL: Could not open keyboard device {KEYBOARD_DEVICE_PATH}. Error: {e}")
        print("Please ensure the script has read permissions for input devices (e.g., /dev/input/event*).")
        print("Try running with 'sudo' or adding your user to the 'input' group (e.g., 'sudo usermod -aG input your_username').")
        return

    for event in device.read_loop():
        if event.type == ecodes.EV_KEY and event.value == 1: # Key press event (value 1 is key down)
            key = categorize(event)
            # print(f"Key pressed: {key.keycode}") # For debugging key presses
            if key.keycode == 'KEY_R':
                if not is_recording: # Prevent multiple start calls if key is held
                    start_recording()
                else:
                    print("Recording is already in progress. Press 'S' to stop.")
            elif key.keycode == 'KEY_S':
                if is_recording: # Prevent multiple stop calls
                    stop_recording()
                else:
                    print("Recording is not in progress. Press 'R' to start.")

if __name__ == "__main__":
    print("Audio Recorder Script Started (ALSA Direct Mode).")
    # A small delay on startup can be helpful on some systems
    time.sleep(1) 
    set_led_state('default') # Initial LED state
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting by user request (Ctrl+C).")
    except Exception as e:
        print(f"\nAn unexpected error occurred in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Initiating cleanup routine...")
        if is_recording: # Ensure recording is stopped if active
            print("Performing emergency stop of recording due to script exit...")
            stop_recording()
        else:
            # If not recording, still attempt unmount in case it was left from a previous run
            unmount_usb_drive() 
        set_led_state('default') # Ensure LED is reset
        print("Cleanup complete. Exiting script.")