#!/usr/bin/env python3

import os
import re
import subprocess
import time
import threading
from datetime import datetime

import numpy as np
from evdev import InputDevice, categorize, ecodes
import pwd, getpass


RECORDER_LOG_PATH = os.path.expanduser("~/recorder/recorder.log")
MAX_LOG_SIZE = 16 * 1024 * 1024  # 16 MB
# --- Configuration ---
KEYBOARD_DEVICE_PATH = "/dev/input/by-id/usb-1189_8890-event-kbd"
FALLBACK_STORAGE_PATH = "/home/banorz/recordings"
USB_MOUNT_POINT = "/mnt/usbrecorder"

# --- Stato globale ---
is_recording = False
recording_process = None
recording_thread = None
current_storage = None  # "USB" o "SD"
recording_start_time = None
log_callback = None
available_inputs = 0
status = ''
_samplerate = 48000
_user_name = getpass.getuser()
_user_info = pwd.getpwnam(_user_name)
_uid = _user_info.pw_uid
_gid = _user_info.pw_gid

def set_log_callback(cb):
    global log_callback
    log_callback = cb

def get_input_levels(alsa_device, inputs_count):
    """Restituisce i livelli audio in dBFS per ciascun canale usando arecord (buffer ~50ms)."""
    try:
        duration = 0.05  # secondi
        samplerate = _samplerate
        frames = int(duration * samplerate)
        # Comando arecord: PCM 16bit, little endian, raw, multi-canale
        cmd = [
            "arecord",
            "-q",
            "-f", "S32_LE",
            "-D", alsa_device,
            "-c", str(inputs_count),
            "-r", str(samplerate),
            "-s", str(frames),
            "-t", "raw"
        ]
        # Leggi dati raw
        raw = subprocess.check_output(cmd, timeout=1)
        # Decodifica in numpy array
        data = np.frombuffer(raw, dtype=np.int32)
        if data.size < frames * inputs_count:
            # Non abbastanza dati, ritorna silenzio
            log(f"Warning: Not enough data captured ({data.size} samples) for {frames * inputs_count} expected.")
            return [-48 for _ in range(inputs_count)]
        data = data[:frames * inputs_count].reshape(-1, inputs_count)
        levels = []
        for ch in range(inputs_count):
            rms = np.sqrt(np.mean(np.square(data[:, ch].astype(np.float32))))
            db = 20 * np.log10(rms / 2147483648) if rms > 0 else -48
            levels.append(db)
        log(f"Audio levels for {inputs_count} channels: {levels}")
        return levels
    except Exception as e:
        print(f"Errore lettura livelli audio (arecord): {e}")
        

def rotate_log_file():
    """Ruota il file di log se supera la dimensione massima."""
    if os.path.exists(RECORDER_LOG_PATH) and os.path.getsize(RECORDER_LOG_PATH) > MAX_LOG_SIZE:
        # Trova un nome libero per il log ruotato
        for i in range(1, 100):
            rotated = f"{RECORDER_LOG_PATH}.{i}"
            if not os.path.exists(rotated):
                os.rename(RECORDER_LOG_PATH, rotated)
                break

def log(msg):
    global log_callback
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    # Scrivi su file con rotazione
    try:
        rotate_log_file()
        with open(RECORDER_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        # In caso di errore sul file, mostra comunque in console
        print(f"Log file error: {e}")
    # Callback GUI
    if log_callback:
        log_callback(msg)
    # Console
    print(msg)

def get_available_inputs():
    """Restituisce il numero di canali disponibili sulla scheda audio."""
    global available_inputs
    alsa_device, channel_count = get_alsa_device_and_channels()
    available_inputs = channel_count
    return channel_count

def find_keyboard_device():
    global KEYBOARD_DEVICE_PATH
    if KEYBOARD_DEVICE_PATH and os.path.exists(KEYBOARD_DEVICE_PATH):
        log(f"Using pre-configured keyboard path: {KEYBOARD_DEVICE_PATH}")
        return

    log("Pre-configured keyboard not found or not set. Searching automatically...")
    try:
        base_path = "/dev/input/by-id/"
        for device_file in os.listdir(base_path):
            if device_file.endswith("-kbd"):
                KEYBOARD_DEVICE_PATH = os.path.join(base_path, device_file)
                log(f"Auto-detected keyboard at: {KEYBOARD_DEVICE_PATH}")
                return
    except FileNotFoundError:
        pass

    log("Auto-detection via /dev/input/by-id/ failed. Falling back to /dev/input/eventX.")
    for i in range(10):
        path = f"/dev/input/event{i}"
        try:
            device = InputDevice(path)
            if ecodes.EV_KEY in device.capabilities():
                KEYBOARD_DEVICE_PATH = path
                log(f"Found a keyboard-like device at {path}")
                return
        except (OSError, IOError):
            continue

    log("FATAL: No keyboard device could be found. Exiting.")
    exit(1)

def set_led_state(state):
    led_base_path = ""
    if os.path.exists("/sys/class/leds/ACT"):
        led_base_path = "/sys/class/leds/ACT"
    elif os.path.exists("/sys/class/leds/led0"):
        led_base_path = "/sys/class/leds/led0"
    else:
        log("Warning: Could not find a path for the activity LED (ACT or led0).")
        return

    led_trigger_path = os.path.join(led_base_path, "trigger")
    led_delay_on_path = os.path.join(led_base_path, "delay_on")
    led_delay_off_path = os.path.join(led_base_path, "delay_off")

    try:
        if state == "blink":
            log("Setting LED to fast blink.")
            subprocess.run(["sudo", "sh", "-c", f"echo timer > {led_trigger_path}"], check=True)
            subprocess.run(["sudo", "sh", "-c", f"echo 50 > {led_delay_on_path}"], check=True)
            subprocess.run(["sudo", "sh", "-c", f"echo 50 > {led_delay_off_path}"], check=True)
        elif state == "default":
            log("Resetting LED to default.")
            subprocess.run(["sudo", "sh", "-c", f"echo mmc0 > {led_trigger_path}"], check=True)
    except Exception as e:
        log(f"Error controlling LED: {e}")

def get_last_used_partition():
    return os.environ.get("LAST_USED_PARTITION")

def set_last_used_partition(value):
    if value:
        os.environ["LAST_USED_PARTITION"] = value
    elif "LAST_USED_PARTITION" in os.environ:
        del os.environ["LAST_USED_PARTITION"]

def mount_usb_drive():
    log("Attempting to mount USB drive...")
    null = None
    try:
        lsblk_output = subprocess.check_output(['lsblk', '-J', '-o', 'NAME,MOUNTPOINT,TYPE,TRAN']).decode()
        devices = eval(lsblk_output)['blockdevices']

        target_partition = None
        new_automount_found = False

        for device in devices:
            if device.get('tran') == 'usb' and 'children' in device:
                for part in device['children']:
                    if part.get('type') == 'part' and part.get('mountpoint') is not None:
                        target_partition = f"/dev/{part['name']}"
                        set_last_used_partition(target_partition)
                        new_automount_found = True
                        log(f"Found new auto-mounted partition: {target_partition}. Storing as last used.")
                        break
                if new_automount_found:
                    break

        if not target_partition and get_last_used_partition():
            if os.path.exists(get_last_used_partition()):
                log(f"No new auto-mounted drive found. Re-using last known partition: {get_last_used_partition()}")
                target_partition = get_last_used_partition()
            else:
                log(f"Last used partition {get_last_used_partition()} no longer exists. Clearing memory.")
                set_last_used_partition(None)

        if not target_partition:
            for device in devices:
                if device.get('tran') == 'usb' and 'children' in device:
                    if device['children']:
                        for part_info in device['children']:
                            if part_info.get('type') == 'part':
                                current_part_dev = f"/dev/{part_info['name']}"
                                if part_info.get('mountpoint') != USB_MOUNT_POINT:
                                    target_partition = current_part_dev
                                    set_last_used_partition(target_partition)
                                    log(f"No auto-mounted or valid last-used partition found. Falling back to: {target_partition}")
                                    break
                        if target_partition:
                            break
                if target_partition:
                    break

        if target_partition:
            log(f"Proceeding with partition: {target_partition}.")
            is_already_mounted_correctly = False
            if os.path.ismount(USB_MOUNT_POINT):
                try:
                    df_output = subprocess.check_output(['df', '--output=source', USB_MOUNT_POINT], text=True).splitlines()
                    if len(df_output) > 1 and df_output[1].strip() == target_partition:
                        is_already_mounted_correctly = True
                        log(f"{target_partition} is already mounted at {USB_MOUNT_POINT}.")
                except Exception as e:
                    log(f"Could not verify if {USB_MOUNT_POINT} is correctly mounted: {e}")

            if not is_already_mounted_correctly:
                log(f"Unmounting {target_partition} if mounted elsewhere, or {USB_MOUNT_POINT} if occupied...")
                subprocess.run(['sudo', 'umount', target_partition], stderr=subprocess.DEVNULL, check=False)
                if os.path.ismount(USB_MOUNT_POINT):
                    subprocess.run(['sudo', 'umount', USB_MOUNT_POINT], stderr=subprocess.DEVNULL, check=False)

            if not os.path.exists(USB_MOUNT_POINT):
                log(f"Creating mount point: {USB_MOUNT_POINT}")
                subprocess.run(['sudo', 'mkdir', '-p', USB_MOUNT_POINT], check=True)

            log(f"Mounting {target_partition} to {USB_MOUNT_POINT} with ownership for UID={_uid}, GID={_gid}")
            mount_cmd = ['sudo', 'mount', '-o', f'uid={_uid},gid={_gid},umask=007,noatime,nodiratime', target_partition, USB_MOUNT_POINT]
            mount_result = subprocess.run(mount_cmd, capture_output=True, text=True)

            if mount_result.returncode == 0:
                log("Mount successful.")
                return USB_MOUNT_POINT
            else:
                log(f"Error mounting USB drive: {mount_result.stderr.strip()}")
                if get_last_used_partition() == target_partition:
                    set_last_used_partition(None)
                return None
        else:
            log("No suitable USB partition found to mount.")
            set_last_used_partition(None)
            return None
    except Exception as e:
        log(f"An exception occurred while trying to mount USB drive: {e}")
        set_last_used_partition(None)
        return None

def unmount_usb_drive():
    if os.path.ismount(USB_MOUNT_POINT):
        log(f"Unmounting {USB_MOUNT_POINT}...")
        log("Syncing filesystems to ensure data is written...")
        subprocess.run(['sync'], check=False)
        time.sleep(1)

        unmount_result = subprocess.run(['sudo', 'umount', USB_MOUNT_POINT], capture_output=True, text=True)
        if unmount_result.returncode == 0:
            log("Unmount successful.")
        else:
            log(f"Warning: Could not unmount {USB_MOUNT_POINT}. Error: {unmount_result.stderr.strip()}")
            log("It might be busy. Trying lazy unmount...")
            lazy_unmount_result = subprocess.run(['sudo', 'umount', '-l', USB_MOUNT_POINT], capture_output=True, text=True)
            if lazy_unmount_result.returncode == 0:
                log("Lazy unmount initiated.")
            else:
                log(f"Lazy unmount also failed: {lazy_unmount_result.stderr.strip()}")

        time.sleep(1)
        log("It should now be safe to remove the drive if unmount was successful or initiated.")
    else:
        log(f"{USB_MOUNT_POINT} is not mounted, skipping unmount.")

def get_alsa_device_and_channels():
    log("Searching for a generic USB ALSA device...")
    alsa_device_for_ffmpeg = None
    channel_count = 0
    card_id_for_proc = None

    try:
        arecord_l_output = subprocess.check_output(['arecord', '-l'], text=True, timeout=5)
        usb_cards_found = []
        card_pattern = re.compile(r"card\s+(\d+):\s*([A-Za-z0-9\-_]+)\s+\[(.*USB.*)\].*", re.IGNORECASE)
        card_pattern_alt = re.compile(r"card\s+(\d+):\s*(USB[A-Za-z0-9\-_]*)\s*\[.*", re.IGNORECASE)

        for line in arecord_l_output.splitlines():
            match = card_pattern.match(line)
            if not match:
                match = card_pattern_alt.match(line)
            if match:
                card_num_str = match.group(1)
                card_name_alsa = match.group(2)
                full_desc = line.strip()
                usb_cards_found.append({'id_name': card_name_alsa, 'id_num': card_num_str, 'desc': full_desc})
                log(f"Found USB audio device: {full_desc} (ALSA Name: {card_name_alsa}, Number: {card_num_str})")

        if not usb_cards_found:
            log("Error: No USB audio card found in 'arecord -l' output. Is the device connected and recognized?")
            return None, 0

        selected_card = usb_cards_found[0]
        card_name_for_ffmpeg = selected_card['id_name']
        card_id_for_proc = selected_card['id_num']
        alsa_device_for_ffmpeg = f"plughw:CARD={card_name_for_ffmpeg},DEV=0"

        log(f"Selected USB audio device: {selected_card['desc']}")
        log(f"ALSA device string for ffmpeg: '{alsa_device_for_ffmpeg}'")

        proc_info_found = False
        if card_id_for_proc:
            proc_paths_to_check = [
                f"/proc/asound/card{card_id_for_proc}/stream0",
                f"/proc/asound/card{card_id_for_proc}/pcm0c/info"
            ]
            for proc_path in proc_paths_to_check:
                if os.path.exists(proc_path):
                    log(f"Reading ALSA info from {proc_path}")
                    try:
                        with open(proc_path, 'r') as f_proc:
                            content = f_proc.read()
                        capture_section_match = re.search(r"Capture:(.*?)(Playback:|\Z)", content, re.DOTALL | re.IGNORECASE)
                        if capture_section_match:
                            capture_content = capture_section_match.group(1)
                            match = re.search(r"Channels\s*:\s*(\d+)", capture_content, re.IGNORECASE)
                            if match:
                                channel_count = int(match.group(1))
                                log(f"Channels found via {proc_path}: {channel_count}")
                                proc_info_found = True
                                break
                    except Exception as e:
                        log(f"Error reading or parsing {proc_path}: {e}")
                if proc_info_found:
                    break

        if proc_info_found and channel_count > 0:
            return alsa_device_for_ffmpeg, channel_count
        else:
            log(f"Warning: Could not determine channel count from /proc/asound/ for card {card_id_for_proc}.")
            log("Please ensure the ALSA driver for your USB device correctly reports channel information in /proc.")
            log("You might need to use 'arecord --dump-hw-params -D hw:CARD=USB,DEV=0' (or similar) manually to check capabilities.")
            return None, 0

    except FileNotFoundError:
        log("FATAL: 'arecord' command not found (for initial device listing). Is 'alsa-utils' installed?")
        return None, 0
    except subprocess.TimeoutExpired:
        log(f"Timeout while listing ALSA devices with 'arecord -l'.")
        return None, 0
    except subprocess.CalledProcessError as e:
        log(f"Error listing ALSA devices: {e.stderr if e.stderr else e.stdout}")
        return None, 0
def is_device_connected():
    """Restituisce True se almeno una scheda audio USB è presente in 'arecord -l'."""
    try:
        arecord_l_output = subprocess.check_output(['arecord', '-l'], text=True, timeout=5)
        card_pattern = re.compile(r"card\s+(\d+):\s*([A-Za-z0-9\-_]+)\s+\[(.*USB.*)\].*", re.IGNORECASE)
        card_pattern_alt = re.compile(r"card\s+(\d+):\s*(USB[A-Za-z0-9\-_]*)\s*\[.*", re.IGNORECASE)

        for line in arecord_l_output.splitlines():
            if card_pattern.match(line) or card_pattern_alt.match(line):
                return True
        return False
    except Exception:
        return False

def _record_audio_thread(alsa_device, session_name, selected_inputs, channel_count, status_callback=None):
    global is_recording, recording_process, status, current_storage
    log(f"Starting recording session: {session_name} from ALSA device: {alsa_device}")

    part = 1
    while is_recording:
        # --- Storage Detection Logic for each part ---
        storage_path = mount_usb_drive()
        if storage_path:
            current_storage = "USB"
        else:
            log("Wait: USB not found or mount failed. Using internal storage fallback.")
            storage_path = FALLBACK_STORAGE_PATH
            os.makedirs(storage_path, exist_ok=True)
            current_storage = "SD"

        output_directory_base = os.path.join(storage_path, session_name)
        os.makedirs(output_directory_base, exist_ok=True)

        part_suffix = f"_part{part}" if part > 1 else ""
        part_dir = output_directory_base + part_suffix
        
        # Se la directory parte esiste già (magari perché siamo tornati su USB dopo un fallback), incrementa part
        while os.path.exists(part_dir):
            part += 1
            part_suffix = f"_part{part}" if part > 1 else ""
            part_dir = output_directory_base + part_suffix

        os.makedirs(part_dir, exist_ok=True)
        log(f"Recording to {current_storage}: {part_dir}")

        command = [
            'ffmpeg', '-y', '-nostdin', '-f', 'alsa',
            '-thread_queue_size', '2048',
            '-channels', str(channel_count),
            '-ar', str(_samplerate),
            '-i', alsa_device,
        ]

        for i in selected_inputs:
            command.extend([
                '-map_channel', f'0.0.{i}',
                '-ar', str(_samplerate),
                '-c:a', 'flac',
                os.path.join(part_dir, f'ch{i+1}.flac')
            ])

        if(status!="RESUMING"):
            if status_callback:
                status_callback("RECORDING", "#FF0000")
                status = "RECORDING"
        
        try:
            recording_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            time.sleep(1) # Reduced from 2 to 1 for faster recovery
            if(status=="RESUMING"):
                if status_callback:
                    status_callback("RECORDING", "#FF0000")
                    status = "RECORDING"
            
            if recording_process.poll() is not None:
                stdout, stderr = recording_process.communicate()
                log(f"ffmpeg failed to start on {current_storage} (code {recording_process.returncode}).")
                if stderr:
                    log(f"ffmpeg stderr:\n{stderr.strip()}")
                if not is_recording:
                    break
                log("Waiting 1 second before retrying recording (storage/part failsafe)...")
                if status_callback:
                    status = "RESUMING"
                    status_callback("RESUMING", "#FFD700")
                time.sleep(1)
                continue

            log(f"ffmpeg process started with PID: {recording_process.pid} on {current_storage}")
            
            # --- Monitor Loop ---
            # Invece di communicate() (bloccante), usiamo un loop di polling
            # per reagire ai cambi di storage (disco rimosso o inserito)
            while is_recording and recording_process.poll() is None:
                # 1. Se siamo su USB, controlla che sia ancora montata
                if current_storage == "USB":
                    if not os.path.ismount(USB_MOUNT_POINT):
                        log("USB DISK UNPLUGGED! Terminating ffmpeg to trigger fallback...")
                        recording_process.terminate()
                        break
                
                # 2. Se siamo su SD, controlla se è apparso un disco USB
                elif current_storage == "SD":
                    # Controllo rapido: c'è un device USB in /dev/disk/by-id/ ?
                    usb_found = False
                    try:
                        if os.path.exists("/dev/disk/by-id"):
                            for f in os.listdir("/dev/disk/by-id"):
                                if "usb" in f.lower():
                                    usb_found = True
                                    break
                    except Exception:
                        pass
                    
                    if usb_found:
                        log("USB DISK DETECTED! Terminating SD recording to switch to USB...")
                        recording_process.terminate()
                        break
                
                time.sleep(1) # Polling ogni secondo
            
            stdout, stderr = recording_process.communicate()

            log(f"ffmpeg process finished with return code: {recording_process.returncode}")
            if stderr:
                # Logga solo se c'è un errore reale (non terminazione manuale)
                if recording_process.returncode not in (0, -15, 255):
                    log(f"ffmpeg stderr:\n{stderr.strip()}")

            if is_recording:
                # Ri-verifica lo storage nel prossimo ciclo
                time.sleep(1)
                continue
            else:
                break

        except FileNotFoundError:
            log("FATAL: ffmpeg command not found. Please install ffmpeg.")
            is_recording = False
            break
        except Exception as e:
            log(f"Error during recording thread on {current_storage}: {e}")
            if not is_recording:
                break
            if status_callback:
                status_callback("RESUMING", "#FFD700")
                status = "RESUMING"
            log("Waiting 1 second before retrying recording...")
            time.sleep(1)
            continue

    log("Recording audio thread finished.")
    if status_callback:
        status_callback("-", "#FFD700")
        status = "-"
    if is_recording and (recording_process is None or recording_process.poll() is not None):
        set_led_state('default')
    recording_process = None

def start_recording(selected_inputs=None, status_callback=None):
    """
    selected_inputs: lista di indici (es: [0,2]) dei canali abilitati.
    Se None, registra tutti i canali.
    """
    global is_recording, recording_thread, current_storage, recording_start_time, status
    if is_recording:
        log("Already recording.")
        return False

    log("\n--- INITIATING RECORDING ---")

    alsa_device, channel_count = get_alsa_device_and_channels()
    if not alsa_device or channel_count == 0:
        log("Aborting: Could not find or configure ALSA device.")
        return False

    if selected_inputs is None:
        selected_inputs = list(range(channel_count))
    else:
        # Filtra solo quelli validi
        selected_inputs = [i for i in selected_inputs if 0 <= i < channel_count]
        if not selected_inputs:
            log("No valid inputs selected for recording.")
            return False

    status = "-"
    is_recording = True
    recording_start_time = time.time()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_name = f"recording_{timestamp}"

    log(f"Initiating recording session {session_name} with {len(selected_inputs)} channels.")
    set_led_state('blink')

    recording_thread = threading.Thread(
        target=_record_audio_thread,
        args=(alsa_device, session_name, selected_inputs, channel_count, status_callback)
    )
    recording_thread.daemon = True
    recording_thread.start()
    return True

def stop_recording():
    global is_recording, recording_process, recording_thread, recording_start_time
    if not is_recording:
        log("Not currently recording.")
        unmount_usb_drive()
        set_led_state('default')
        return False

    log("\n--- STOPPING RECORDING ---")

    if recording_process and recording_process.poll() is None:
        log(f"Terminating ffmpeg process (PID: {recording_process.pid})...")
        recording_process.terminate()

    if recording_thread and recording_thread.is_alive():
        log("Waiting for recording thread to complete...")
        recording_thread.join(timeout=10)
        if recording_thread.is_alive():
            log("Warning: Recording thread did not join. Forcing kill on ffmpeg.")
            if recording_process and recording_process.poll() is None:
                recording_process.kill()

    log("Recording stopped.")
    is_recording = False
    recording_process = None
    recording_thread = None
    recording_start_time = None

    set_led_state('default')
    unmount_usb_drive()
    return True