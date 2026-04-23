#!/usr/bin/env python3

import json
import os
import re
import subprocess
import tkinter as tk
from tkinter import font
import time
import recorder
import player
import random
import threading
import numpy as np
import datetime
import shutil

class RecorderApp:
    def __init__(self, root):
        self.root = root
        self.version = self.get_version()
        self.root.title(f"Recberry Controller {self.version}")
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_w}x{screen_h}")
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))

        self.scale = min(screen_w / 480.0, screen_h / 320.0)
        if self.scale < 1.0:
            self.scale = 1.0

        self.bg_color = "#2c3425"
        self.fg_color = "#FFFFFF"
        self.button_color = "#4A4A4A"
        self.status_font = font.Font(family="Helvetica", size=int(24 * self.scale), weight="bold")
        self.button_font = font.Font(family="Helvetica", size=int(20 * self.scale))
        self.medium_font = font.Font(family="Helvetica", size=int(15 * self.scale))
        self.log_font = font.Font(family="Helvetica", size=int(12 * self.scale))
        self.input_font = font.Font(family="Helvetica", size=int(10 * self.scale), weight="bold")
        self.status = "-"
        self.root.configure(bg=self.bg_color)
        
        # Rimuove solo i bordini di focus che sono antiestetici su touchscreen
        self.root.option_add("*Button.highlightThickness", 0)
        self.root.option_add("*Button.takeFocus", 0)
        
        # Inizializzazioni per evitare AttributeError prima della creazione screen
        self.samplerate = self.get_samplerate()
        self.wifi_enabled = True 
        
        # Stato per inputs
        self.inputs = self.get_inputs()
        self.alsa_device = ""
        self.input_enabled = [True for _ in self.inputs]
        self.input_audio_detected = [False for _ in self.inputs]
        self.refresh_card()
        self.refresh_inputs()
        self.load_input_enabled()  # <-- Prima carica lo stato
        
        # Inizializza Player
        self.player = player.MultiTrackPlayer(samplerate=self.samplerate)
        self.current_playback_folder = None
        self.playback_storage = "USB"
        self.master_vol = 1.0
        self.seek_timer = None
        self.seek_direction = 0
        self.seek_start_time = 0
        
        # Output Routing State
        self.output_settings_path = "output_settings.json"
        self.output_device_index = None # Default
        self.output_channels = [0, 1] # Stereo L/R
        self.current_out_name = "Default"
        self.out_devices = self.player.get_output_devices()

        # Log
        self.log_lines = []
        recorder.set_log_callback(self.append_log)
        self.recording_time = 0
        self.last_time = 0
        # Schermate
        self.frames = {}
        self.load_output_settings()
        self.create_home_screen()
        self.create_inputs_screen()
        self.create_settings_screen()
        self.create_wifi_config_screen()
        self.create_output_screen()
        self.create_playback_browser_screen()
        self.create_mixer_screen()
        self.show_frame("home")

        self.update_status()
        
        # Operazioni lente spostate dopo l'avvio
        self.root.after(500, self.deferred_init)
        self.update_temp()

    def deferred_init(self):
        self.update_samplerate_buttons()
        self.update_wifi_buttons()
        self.update_wifi_ssid()
        self.refresh_card()
        self.refresh_inputs()

    def get_version(self):
        try:
            with open(os.path.join(os.path.dirname(__file__), "version.txt"), "r") as f:
                return f.read().strip()
        except Exception:
            return "vUnknown"

    def get_samplerate(self):
        return recorder._samplerate if hasattr(recorder, "_samplerate") else 48000
    
    def set_samplerate(self, rate):
        recorder._samplerate = rate
        self.samplerate = rate
        self.root.after(0, self.update_samplerate_buttons)
        recorder.log(f"Sample rate set to {rate} Hz")

    def update_samplerate_buttons(self):
        if self.samplerate == 44100:
            self.samplerate_44100_btn.config(bg="#008000", fg=self.fg_color)
            self.samplerate_48000_btn.config(bg="#4A4A4A", fg=self.fg_color)
        else:
            self.samplerate_44100_btn.config(bg="#4A4A4A", fg=self.fg_color)
            self.samplerate_48000_btn.config(bg="#008000", fg=self.fg_color)
    def restart_lightdm(self):
        try:
            result = subprocess.run(["sudo", "service", "lightdm", "restart"], capture_output=True, text=True, check=True)
            recorder.log("Restart")
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            recorder.log(f"Error restarting LightDM: {e.stderr}")

    def disable_wifi(self):
        try:
            result = subprocess.run(["nmcli", "radio", "wifi", "off"], capture_output=True, text=True, check=True)
            recorder.log("WiFi Disabled")
            self.wifi_enabled = False
            self.update_wifi_buttons()
            self.wifi_ssid_label.config(text=f"SSID: Not Connected")
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            recorder.log(f"Error disabling WiFi: {e.stderr}")
            self.wifi_ssid_label.config(text=f"{e.stderr.strip()}")

    def enable_wifi(self):
        try:
            result = subprocess.run(["nmcli", "radio", "wifi", "on"], capture_output=True, text=True, check=True)
            recorder.log("WiFi Enabled")
            self.wifi_enabled = True
            self.update_wifi_buttons()
            self.wifi_ssid_label.config(text=f"SSID: searching...")
            # add timer to update SSID after 5 seconds
            self.root.after(5000, self.update_wifi_ssid)
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            recorder.log(f"Error enabling WiFi: {e.stderr}")
            self.wifi_ssid_label.config(text=f"{e.stderr.strip()}")

    def power_off(self):
        if recorder.is_recording:
            recorder.log("Cannot power off while recording!")
            return
        try:
            recorder.log("Powering off...")
            subprocess.run(["sudo", "poweroff"], check=True)
        except Exception as e:
            recorder.log(f"Error during power off: {e}")

    def reboot(self):
        if recorder.is_recording:
            recorder.log("Cannot reboot while recording!")
            return
        try:
            recorder.log("Rebooting...")
            subprocess.run(["sudo", "reboot"], check=True)
        except Exception as e:
            recorder.log(f"Error during reboot: {e}")

    def update_wifi_buttons(self):
        if self.wifi_enabled:
            self.wifi_enable_btn.config(bg="#008000", fg=self.fg_color)
            self.wifi_disable_btn.config(bg="#4A4A4A", fg=self.fg_color)
        else:
            self.wifi_enable_btn.config(bg="#4A4A4A", fg=self.fg_color)
            self.wifi_disable_btn.config(bg="#008000", fg=self.fg_color)

    def update_wifi_ssid(self):
        try:
            result = subprocess.run(["nmcli", "dev", "show", "wlan0"], capture_output=True, text=True, check=True)
            output = result.stdout
            ssid = re.search(r'GENERAL.CONNECTION:\s(.*?)\n', output)
            
            if ssid:
                ssid = ssid.group(1).strip()
            else:
                ssid = "Not Connected"
        except subprocess.CalledProcessError as e:
            ssid = "Not Connected"
     
        self.wifi_ssid_label.config(text=f"SSID: {ssid}")

    def get_inputs(self):
        try:
            n = recorder.get_available_inputs()
        except Exception:
            n = 4
        return [f"INPUT {i+1}" for i in range(n if n > 0 else 4)]

    def refresh_card(self):
        alsa_device, channel_count = recorder.get_alsa_device_and_channels()
        if not alsa_device:
            self.alsa_device = ""
            return
  
        if alsa_device != self.alsa_device:
            self.alsa_device = alsa_device

    def load_input_enabled(self):
        path = os.path.join(os.path.expanduser("~/recorder"), "inputs.json")
        enabled = []
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    enabled = json.load(f)
            except Exception as e:
                print(f"Errore caricamento inputs.json: {e}")
        # Riempie input_enabled con i primi N valori, il resto True
        self.input_enabled = []
        for i in range(len(self.inputs)):
            if i < len(enabled):
                self.input_enabled.append(bool(enabled[i]))
            else:
                self.input_enabled.append(True)
        recorder.log(f"Loaded input_enabled: {self.input_enabled}")
        # NON chiamare qui self.update_inputs_screen()

    def save_input_enabled(self):
        path = os.path.join(os.path.expanduser("~/recorder"), "inputs.json")
        try:
            with open(path, "w") as f:
                json.dump(self.input_enabled, f)
        except Exception as e:
            print(f"Errore salvataggio inputs.json: {e}")

    def refresh_inputs(self):
        new_inputs = self.get_inputs()
        if len(new_inputs) != len(self.inputs):
            self.inputs = new_inputs
            self.load_input_enabled()  # <-- Prima carica lo stato
            self.input_audio_detected = [False for _ in self.inputs]
            self.create_inputs_screen()  # <-- Poi crea la schermata
           
    def create_settings_screen(self):
        frame = tk.Frame(self.root, bg=self.bg_color)
        self.frames["settings"] = frame

        # --- Back Button (Top Left) ---
        back_btn = tk.Button(
            frame, text="Back", command=lambda: self.show_frame("home"),
            font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=50, pady=20,
            takefocus=0
        )
        back_btn.grid(row=0, column=0, sticky="nw", padx=10, pady=10)

        # --- Sample Rate Options (Row 1) ---
        samplerate_frame = tk.Frame(frame, bg=self.bg_color)
        samplerate_frame.grid(row=1, column=0, pady=10, sticky="ew")

        self.samplerate_44100_btn = tk.Button(
            samplerate_frame, text="44100 Hz", command=lambda: self.set_samplerate(44100),
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0,
            takefocus=0
        )
        self.samplerate_48000_btn = tk.Button(
            samplerate_frame, text="48000 Hz", command=lambda: self.set_samplerate(48000),
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0,
            takefocus=0
        )
        self.samplerate_44100_btn.pack(side=tk.LEFT, padx=10)
        self.samplerate_48000_btn.pack(side=tk.LEFT, padx=10)

        # --- WiFi Options (Row 2) ---
        wifi_frame = tk.Frame(frame, bg=self.bg_color)
        wifi_frame.grid(row=2, column=0, pady=10, sticky="ew")

        # Label WiFi:
        tk.Label(wifi_frame, text="WiFi:", font=self.button_font, bg=self.bg_color, fg="#FFD700").pack(side=tk.LEFT, padx=(10, 5))

        self.wifi_enable_btn = tk.Button(
            wifi_frame, text="ON", command=self.enable_wifi,
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0,
            takefocus=0, padx=10
        )
        self.wifi_disable_btn = tk.Button(
            wifi_frame, text="OFF", command=self.disable_wifi,
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0,
            takefocus=0, padx=10
        )
        self.wifi_config_btn = tk.Button(
            wifi_frame, text="CONFIG", command=lambda: self.show_frame("wifi_config"),
            font=self.button_font, bg="#0055AA", fg=self.fg_color, relief=tk.FLAT, borderwidth=0,
            takefocus=0, padx=10
        )
        self.wifi_enable_btn.pack(side=tk.LEFT, padx=5)
        self.wifi_disable_btn.pack(side=tk.LEFT, padx=5)
        self.wifi_config_btn.pack(side=tk.LEFT, padx=5)

        self.wifi_ssid_label = tk.Label(
            frame, text="SSID: Not Connected", font=self.log_font, bg=self.bg_color, fg="#FFD700"
        )
        self.wifi_ssid_label.grid(row=3, column=0, pady=5)

        # --- Date/Time Options (Row 4) ---
        datetime_frame = tk.Frame(frame, bg=self.bg_color)
        datetime_frame.grid(row=4, column=0, pady=10, sticky="ew")

        self.time_display_label = tk.Label(
            datetime_frame, text="Time: 00/00/00 00:00", 
            font=self.log_font, bg=self.bg_color, fg="#FFD700"
        )
        self.time_display_label.pack(side=tk.LEFT, padx=(10, 10))

        tk.Button(
            datetime_frame, text="SET TIME", command=self.show_time_picker,
            font=self.log_font, bg="#0055AA", fg=self.fg_color, relief=tk.FLAT, borderwidth=0,
            takefocus=0, padx=15
        ).pack(side=tk.LEFT)

        # --- System Options (Row 5: Reboot, Power Off, Restart GUI) ---
        system_frame = tk.Frame(frame, bg=self.bg_color)
        system_frame.grid(row=5, column=0, pady=10, sticky="ew")

        self.reboot_btn = tk.Button(
            system_frame, text="Reboot", command=self.reboot,
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0,
            takefocus=0, padx=10
        )
        self.poweroff_btn = tk.Button(
            system_frame, text="Power Off", command=self.power_off,
            font=self.button_font, bg="#B22222", fg=self.fg_color, relief=tk.FLAT, borderwidth=0,
            takefocus=0, padx=10
        )
        self.restart_lightdm_btn = tk.Button(
            system_frame, text="Restart GUI", command=self.restart_lightdm,
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0,
            takefocus=0, padx=10
        )
        
        self.reboot_btn.pack(side=tk.LEFT, padx=5)
        self.poweroff_btn.pack(side=tk.LEFT, padx=5)
        self.restart_lightdm_btn.pack(side=tk.LEFT, padx=5)

        # --- Version Label at the bottom ---
        version_label = tk.Label(frame, text=f"Recberry {self.version}", font=self.log_font, bg=self.bg_color, fg="#888")
        version_label.grid(row=6, column=0, pady=(15, 0), sticky="s")

        self.update_samplerate_buttons()
        self.update_wifi_buttons()
        self.update_clock_label()

        # self.update_wifi_ssid() # Spostato in deferred_init
        
    
    def update_clock_label(self):
        # Update clock label if it exists
        try:
            if hasattr(self, "time_display_label") and self.time_display_label.winfo_exists():
                now = datetime.datetime.now()
                self.time_display_label.config(text=now.strftime("Time: %d/%m/%Y %H:%M:%S"))
        except Exception:
            pass
        
        # Keep the loop running as long as the app is alive
        self.root.after(1000, self.update_clock_label)

    def update_temp(self):
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_raw = int(f.read())
                temp_c = temp_raw / 1000.0
                if hasattr(self, "temp_label") and self.temp_label.winfo_exists():
                    self.temp_label.config(text=f"CPU: {temp_c:.1f}°C")
        except Exception:
            pass
        # Polling ogni 3 secondi
        self.root.after(3000, self.update_temp)

    def get_free_time_string(self, path=None):
        try:
            if path is None:
                # Logica per Standby: USB se montata, altrimenti SD
                usb_path = recorder.USB_MOUNT_POINT
                if os.path.ismount(usb_path):
                    path = usb_path
                else:
                    path = os.path.expanduser("~/")
            
            usage = shutil.disk_usage(path)
            free_bytes = usage.free
            
            # Calcolo bitrate stimato FLAC
            n_ch = sum(self.input_enabled)
            if n_ch == 0:
                n_ch = len(self.inputs) if self.inputs else 1
            
            bytes_per_second = n_ch * self.samplerate * 3 * 0.7
            
            if bytes_per_second <= 0:
                return ""
            
            seconds_left = free_bytes / bytes_per_second
            
            hours = int(seconds_left // 3600)
            minutes = int((seconds_left % 3600) // 60)
            
            if hours > 999:
                return "FREE: >999h"
            
            if hours > 0:
                return f"FREE: {hours}h {minutes}m"
            else:
                return f"FREE: {minutes}m"
        except Exception:
            return ""
        except Exception:
            return ""

    def show_time_picker(self):
        picker = tk.Toplevel(self.root)
        picker.overrideredirect(True)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        picker.geometry(f"{screen_w}x{screen_h}+0+0")
        picker.configure(bg=self.bg_color)
        picker.grab_set()

        now = datetime.datetime.now()
        year = tk.IntVar(value=now.year)
        month = tk.IntVar(value=now.month)
        day = tk.IntVar(value=now.day)
        hour = tk.IntVar(value=now.hour)
        minute = tk.IntVar(value=now.minute)

        tk.Label(picker, text="SET DATE AND TIME", font=self.medium_font, bg=self.bg_color, fg="#FFD700").pack(pady=10)

        main_frame = tk.Frame(picker, bg=self.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True)

        def create_selector(parent, label, var, v_min, v_max):
            f = tk.Frame(parent, bg=self.bg_color)
            f.pack(side=tk.LEFT, expand=True)
            tk.Label(f, text=label, font=self.log_font, bg=self.bg_color, fg="#AAA").pack()
            tk.Button(f, text="+", font=self.button_font, command=lambda: var.set(var.get()+1 if var.get()<v_max else v_min), bg="#444", fg="#FFF").pack(pady=5)
            tk.Label(f, textvariable=var, font=self.button_font, bg=self.bg_color, fg="#FFF").pack()
            tk.Button(f, text="-", font=self.button_font, command=lambda: var.set(var.get()-1 if var.get()>v_min else v_max), bg="#444", fg="#FFF").pack(pady=5)

        create_selector(main_frame, "Year", year, 2024, 2099)
        create_selector(main_frame, "Month", month, 1, 12)
        create_selector(main_frame, "Day", day, 1, 31)
        create_selector(main_frame, "Hour", hour, 0, 23)
        create_selector(main_frame, "Min", minute, 0, 59)

        def save_time():
            new_time = f"{year.get():04d}-{month.get():02d}-{day.get():02d} {hour.get():02d}:{minute.get():02d}:00"
            try:
                # Imposta ora di sistema
                subprocess.run(["sudo", "date", "-s", new_time], check=True)
                # Sincronizza su RTC hardware
                subprocess.run(["sudo", "hwclock", "-w"], check=True)
                recorder.log(f"System time updated to: {new_time}")
            except Exception as e:
                recorder.log(f"Error setting time: {e}")
            picker.destroy()
            self.update_clock_label()

        btn_frame = tk.Frame(picker, bg=self.bg_color)
        btn_frame.pack(fill=tk.X, pady=20)

        tk.Button(btn_frame, text="CANCEL", command=picker.destroy, font=self.button_font, bg="#B22222", fg="#FFF", padx=40, pady=20).pack(side=tk.LEFT, expand=True)
        
        def sync_internet():
            if sync_btn['state'] == tk.DISABLED: return
            sync_btn.config(text="...", state=tk.DISABLED)
            picker.update_idletasks()
            
            def do_sync():
                success = False
                try:
                    # 1. Rileva timezone via IP (opzionale ma utile)
                    tz_res = subprocess.run(["curl", "-s", "http://worldtimeapi.org/api/ip"], capture_output=True, text=True, timeout=5)
                    if tz_res.returncode == 0:
                        import json
                        tz_data = json.loads(tz_res.stdout)
                        new_tz = tz_data.get("timezone")
                        if new_tz:
                            subprocess.run(["sudo", "timedatectl", "set-timezone", new_tz])
                            recorder.log(f"Timezone updated to {new_tz}")

                    # 2. Abilita temporaneamente NTP
                    subprocess.run(["sudo", "timedatectl", "set-ntp", "true"], check=True)
                    # Poll for sync for max 8 seconds
                    for _ in range(16):
                        time.sleep(0.5)
                        res = subprocess.run(["timedatectl", "status"], capture_output=True, text=True)
                        if "System clock synchronized: yes" in res.stdout:
                            success = True
                            break
                    # Sincronizza su RTC
                    if success:
                        subprocess.run(["sudo", "hwclock", "-w"], check=True)
                        # Aggiorna variabili UI
                        now = datetime.datetime.now()
                        year.set(now.year); month.set(now.month); day.set(now.day)
                        hour.set(now.hour); minute.set(now.minute)
                except Exception as e:
                    recorder.log(f"Sync error: {e}")
                finally:
                    subprocess.run(["sudo", "timedatectl", "set-ntp", "false"])
                    
                self.root.after(0, lambda: self.finish_sync(sync_btn))

            threading.Thread(target=do_sync, daemon=True).start()

        # Verifica stato WiFi per abilitare tasto
        is_wifi_connected = False
        try:
            wifi_status = subprocess.run(["nmcli", "-t", "-f", "ACTIVE", "dev", "wifi"], capture_output=True, text=True).stdout
            if "yes" in wifi_status.lower():
                is_wifi_connected = True
        except: pass

        sync_btn = tk.Button(btn_frame, text="SYNC", command=sync_internet, font=self.button_font, bg="#0055AA", fg="#FFF", padx=40, pady=20)
        if not is_wifi_connected:
            sync_btn.config(state=tk.DISABLED, bg="#444")
        sync_btn.pack(side=tk.LEFT, expand=True)

        tk.Button(btn_frame, text="SAVE", command=save_time, font=self.button_font, bg="#008000", fg="#FFF", padx=40, pady=20).pack(side=tk.LEFT, expand=True)

    def finish_sync(self, btn):
        if btn.winfo_exists():
            btn.config(text="SYNC", state=tk.NORMAL)
        self.update_clock_label()

    # --- SCHERMATE ---
    def create_home_screen(self):
        frame = tk.Frame(self.root, bg=self.bg_color)
        self.frames["home"] = frame

        # --- Top Button Bar (Settings, Input, Output, Browse) ---
        top_bar = tk.Frame(frame, bg="#333")
        top_bar.pack(fill=tk.X)

        nav_btns = [
            ("Settings", "settings"),
            ("Input", "inputs"),
            ("Output", "output"),
            ("Browse", "playback_browser")
        ]
        
        for text, frame_name in nav_btns:
            btn = tk.Button(
                top_bar, text=text, command=lambda n=frame_name: self.show_frame(n),
                font=self.log_font, bg="#444", fg="#FFD700", relief=tk.FLAT, 
                borderwidth=1, highlightthickness=0, width=10, pady=10
            )
            btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)
            if text == "Settings":
                self.settings_button = btn
            elif text == "Input":
                self.inputs_button = btn
            elif text == "Browse":
                self.playback_button = btn
            elif text == "Output":
                self.output_button = btn

        self.status_label = tk.Label(
            frame, text="", font=self.status_font, bg=self.bg_color, fg=self.fg_color
        )
        self.status_label.pack(pady=(12, 0))

        self.device_warning_label = tk.Label(
            frame, text="USB AUDIO NOT FOUND", font=self.log_font, bg=self.bg_color, fg="#FF4500"
        )
        # We'll pack this only when device is missing

        self.info_label = tk.Label(
            frame, text="", font=self.log_font, bg=self.bg_color, fg="#FFD700"
        )
        # We'll pack this only when needed (recording/playback)

        # Pulsante RECORD (Centrato e più piccolo)
        self.record_button = tk.Button(
            frame, text="Start Recording", command=self.toggle_recording,
            font=self.button_font, bg="#008000", fg=self.fg_color,
            activebackground="#006400", activeforeground=self.fg_color,
            relief=tk.FLAT, borderwidth=0, highlightthickness=0,
            disabledforeground="#666", takefocus=0,
            pady=15, anchor="center"
        )
        self.record_button.pack(fill=tk.X, padx=100, pady=(6, 0))

        # Area LOG (più spazio e scorrevole)
        log_frame = tk.Frame(frame, bg="#1a1a1a", borderwidth=0, highlightthickness=0)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(20, 10))
        
        self.log_listbox = tk.Listbox(
            log_frame, font=("Courier", 10), bg="#1a1a1a", fg="#00FF00",
            relief=tk.FLAT, borderwidth=0, highlightthickness=0,
            selectborderwidth=0, exportselection=False
        )
        self.log_listbox.pack(fill=tk.BOTH, expand=True)

        # Label Temperatura (in basso)
        self.temp_label = tk.Label(
            frame, text="CPU: --°C", font=("Courier", 10), bg=self.bg_color, fg="#888"
        )
        self.temp_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-5)

        # Inizializza con i log esistenti
        for line in self.log_lines:
            self.log_listbox.insert(tk.END, line)
        self.log_listbox.yview_moveto(1.0)

    def create_wifi_config_screen(self):
        frame = tk.Frame(self.root, bg=self.bg_color)
        self.frames["wifi_config"] = frame
        
        # --- Header ---
        header = tk.Frame(frame, bg="#333")
        header.pack(fill=tk.X)
        
        tk.Button(
            header, text="Back", command=lambda: self.show_frame("settings"),
            font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=20, pady=10
        ).pack(side=tk.LEFT)
        
        tk.Label(header, text="WiFi Networks", font=self.button_font, bg="#333", fg=self.fg_color).pack(side=tk.LEFT, padx=10)
        
        tk.Button(
            header, text="Scan", command=self.scan_wifi_networks,
            font=self.button_font, bg="#008000", fg=self.fg_color, relief=tk.FLAT, borderwidth=0, padx=20, pady=10
        ).pack(side=tk.RIGHT)
        
        # --- Listbox ---
        list_frame = tk.Frame(frame, bg=self.bg_color)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.wifi_listbox = tk.Listbox(
            list_frame, font=self.medium_font, bg="#222", fg="#FFF",
            selectbackground="#FFD700", selectforeground="#000", borderwidth=0, highlightthickness=0
        )
        self.wifi_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.wifi_listbox.yview, width=40)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.wifi_listbox.config(yscrollcommand=scrollbar.set)
        
        # --- Action Button ---
        self.wifi_connect_btn = tk.Button(
            frame, text="Connect", command=self.on_wifi_select,
            font=self.button_font, bg="#0055AA", fg=self.fg_color, relief=tk.FLAT, pady=10
        )
        self.wifi_connect_btn.pack(fill=tk.X, padx=30, pady=(0, 10))

    def scan_wifi_networks(self):
        self.wifi_listbox.delete(0, tk.END)
        self.wifi_listbox.insert(tk.END, "Scanning networks...")
        self.root.update_idletasks()
        
        try:
            result = subprocess.run(["nmcli", "-t", "-f", "SSID,SECURITY,SIGNAL", "dev", "wifi"], capture_output=True, text=True, check=True)
            self.wifi_listbox.delete(0, tk.END)
            self.wifi_networks = []
            
            for line in result.stdout.splitlines():
                if line:
                    parts = line.split(':')
                    if len(parts) >= 3:
                        ssid = parts[0].strip()
                        security = parts[1].strip()
                        signal = parts[2].strip()
                        
                        if ssid: # Ignora reti nascoste senza SSID
                            # Non aggiungere duplicati con segnale minore
                            if not any(n['ssid'] == ssid for n in self.wifi_networks):
                                self.wifi_networks.append({'ssid': ssid, 'sec': security, 'sig': signal})
            
            for net in self.wifi_networks:
                sec_str = "Open" if not net['sec'] else "Secured"
                self.wifi_listbox.insert(tk.END, f"{net['ssid']} ({sec_str}) - {net['sig']}%")
                
        except subprocess.CalledProcessError as e:
            self.wifi_listbox.delete(0, tk.END)
            self.wifi_listbox.insert(tk.END, "Failed to scan networks.")
            recorder.log(f"WiFi scan error: {e.stderr}")

    def on_wifi_select(self):
        selection = self.wifi_listbox.curselection()
        if not selection:
            return
            
        selected_index = selection[0]
        # Salta se è un messaggio di sistema
        if selected_index >= len(getattr(self, 'wifi_networks', [])):
            return
            
        selected_network = self.wifi_networks[selected_index]
        ssid = selected_network['ssid']
        security = selected_network['sec']
        
        if security:
            self.show_osk(ssid)
        else:
            self.connect_to_wifi(ssid, "")

    def show_osk(self, ssid):
        osk = tk.Toplevel(self.root)
        osk.overrideredirect(True)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        osk.geometry(f"{screen_w}x{screen_h}+0+0")
        osk.configure(bg="#222")
        osk.grab_set()

        password_var = tk.StringVar()
        layout_var = tk.StringVar(value="lower")  # "lower", "upper", "sym"

        LAYOUTS = {
            "lower": [
                ['q','w','e','r','t','y','u','i','o'],
                ['a','s','d','f','g','h','j','k','l'],
                ['z','x','c','v','b','n','m','.','@'],
            ],
            "upper": [
                ['Q','W','E','R','T','Y','U','I','O'],
                ['A','S','D','F','G','H','J','K','L'],
                ['Z','X','C','V','B','N','M','.','@'],
            ],
            "sym": [
                ['1','2','3','4','5','6','7','8','9'],
                ['0','!','#','$','%','&','*','(',')'],
                ['_','-','+','=','[',']','{','}','@'],
            ],
        }

        # --- Header / Display ---
        header = tk.Frame(osk, bg="#333")
        header.pack(fill=tk.X)
        tk.Label(header, text=f"{ssid}:", font=self.log_font, bg="#333", fg="#AAA").pack(side=tk.LEFT, padx=6)
        entry = tk.Entry(header, textvariable=password_var, font=self.medium_font)  # password in chiaro
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=4)

        # --- Keys area ---
        keys_frame = tk.Frame(osk, bg="#222")
        keys_frame.pack(fill=tk.BOTH, expand=True)

        # Configure 9 columns + 3 rows (no DEL in grid)
        for col in range(9):
            keys_frame.columnconfigure(col, weight=1)
        for row in range(3):
            keys_frame.rowconfigure(row, weight=1)

        def press(key):
            if key == 'DEL':
                password_var.set(password_var.get()[:-1])
            else:
                password_var.set(password_var.get() + key)

        def draw_layout(layout_name):
            for widget in keys_frame.winfo_children():
                widget.destroy()
            for r, row in enumerate(LAYOUTS[layout_name]):
                for c, key in enumerate(row):
                    tk.Button(
                        keys_frame, text=key, command=lambda k=key: press(k),
                        font=self.medium_font, bg="#3A3A3A", fg="#FFF",
                        relief=tk.FLAT, borderwidth=1
                    ).grid(row=r, column=c, sticky="nsew", padx=1, pady=1)

        draw_layout("lower")

        def switch_layout(name):
            layout_var.set(name)
            draw_layout(name)
            # Aggiorna colori tasti switch
            lower_btn.config(bg="#0055AA" if name == "lower" else "#444")
            upper_btn.config(bg="#0055AA" if name == "upper" else "#444")
            sym_btn.config(bg="#0055AA" if name == "sym" else "#444")

        # --- Bottom bar: tasti grandi, facili da toccare ---
        bottom = tk.Frame(osk, bg="#111")
        bottom.pack(fill=tk.X)
        for col in range(10):
            bottom.columnconfigure(col, weight=1)

        bs = {"font": self.button_font, "fg": "#FFF", "relief": tk.FLAT}

        lower_btn = tk.Button(bottom, text="abc", command=lambda: switch_layout("lower"), bg="#0055AA", **bs)
        lower_btn.grid(row=0, column=0, sticky="nsew", padx=1, pady=5)

        upper_btn = tk.Button(bottom, text="ABC", command=lambda: switch_layout("upper"), bg="#444", **bs)
        upper_btn.grid(row=0, column=1, sticky="nsew", padx=1, pady=5)

        sym_btn = tk.Button(bottom, text="123?", command=lambda: switch_layout("sym"), bg="#444", **bs)
        sym_btn.grid(row=0, column=2, sticky="nsew", padx=1, pady=5)

        tk.Button(bottom, text="DEL", command=lambda: press("DEL"),
                  bg="#555", fg="#FF8888", font=self.button_font, relief=tk.FLAT).grid(
            row=0, column=3, columnspan=2, sticky="nsew", padx=1, pady=5)

        tk.Button(bottom, text="Annulla", command=osk.destroy, bg="#8B0000", **bs).grid(
            row=0, column=5, columnspan=2, sticky="nsew", padx=1, pady=5)

        tk.Button(bottom, text="Connetti",
                  command=lambda: [osk.destroy(), self.connect_to_wifi(ssid, password_var.get())],
                  bg="#005500", **bs).grid(row=0, column=7, columnspan=3, sticky="nsew", padx=1, pady=5)

    def connect_to_wifi(self, ssid, password):
        self.wifi_connect_btn.config(text="Connecting...", state=tk.DISABLED)
        self.root.update_idletasks()
        
        def _connect():
            try:
                if password:
                    cmd = ["nmcli", "dev", "wifi", "connect", ssid, "password", password]
                else:
                    cmd = ["nmcli", "dev", "wifi", "connect", ssid]
                
                # Run connection (Auto-saves the profile by default)
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    recorder.log(f"Successfully connected to {ssid}")
                    self.root.after(0, lambda: self.finish_wifi_connect(True, "Connected"))
                else:
                    recorder.log(f"Failed to connect to {ssid}: {result.stderr}")
                    self.root.after(0, lambda: self.finish_wifi_connect(False, "Failed"))
            except subprocess.TimeoutExpired:
                 recorder.log(f"Connection to {ssid} timed out.")
                 self.root.after(0, lambda: self.finish_wifi_connect(False, "Timeout"))
            except Exception as e:
                recorder.log(f"Connection error: {str(e)}")
                self.root.after(0, lambda: self.finish_wifi_connect(False, "Error"))

        threading.Thread(target=_connect, daemon=True).start()

    def finish_wifi_connect(self, success, msg):
        self.wifi_connect_btn.config(text="Connect", state=tk.NORMAL)
        if success:
            self.show_frame("settings")
            # Update SSID on settings screen
            self.update_wifi_ssid()
        else:
            self.wifi_listbox.insert(tk.END, f"Connection {msg}!")
            self.wifi_listbox.yview_moveto(1.0)

    def create_output_screen(self):
        frame = self.frames.get("output")
        if frame:
            for widget in frame.winfo_children():
                widget.destroy()
        else:
            frame = tk.Frame(self.root, bg=self.bg_color)
            self.frames["output"] = frame
        
        # Top Bar for Back Button
        top_bar = tk.Frame(frame, bg="#333")
        top_bar.pack(fill=tk.X)
        
        back_btn = tk.Button(
            top_bar, text="Back", command=lambda: self.show_frame("home"),
            font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=20, pady=10
        )
        back_btn.pack(side=tk.LEFT)
        
        main_content = tk.Frame(frame, bg=self.bg_color)
        main_content.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Spacer to ensure visibility
        tk.Label(main_content, bg=self.bg_color).pack(pady=5)

        self.out_device_info_label = tk.Label(
            main_content, text=f"Output: {self.current_out_name}", 
            font=self.medium_font, bg=self.bg_color, fg="#FFD700"
        )
        self.out_device_info_label.pack(pady=2)

        self.out_channels_info_label = tk.Label(
            main_content, text=f"Channels: {self.output_channels[0]+1}, {self.output_channels[1]+1}", 
            font=self.medium_font, bg=self.bg_color, fg="#FFD700"
        )
        self.out_channels_info_label.pack(pady=2)

        btn_style = {"font": self.button_font, "bg": "#4A4A4A", "fg": self.fg_color, "relief": tk.FLAT, "pady": 15}

        tk.Button(
            main_content, text="Select Output Device", command=self.show_device_picker,
            **btn_style
        ).pack(fill=tk.X, padx=50, pady=10)

        tk.Button(
            main_content, text="Select Output Channels", command=self.show_channel_picker,
            **btn_style
        ).pack(fill=tk.X, padx=50, pady=10)

    def show_device_picker(self):
        self.out_devices = self.player.get_output_devices()
        picker = tk.Toplevel(self.root)
        picker.overrideredirect(True)
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        picker.geometry(f"{screen_w}x{screen_h}+0+0")
        picker.configure(bg=self.bg_color, highlightthickness=0, bd=0)
        picker.grab_set()
        
        tk.Label(picker, text="AVAILABLE DEVICES", font=self.medium_font, bg=self.bg_color, fg="#FFD700", highlightthickness=0, bd=0).pack(pady=5)
        
        list_frame = tk.Frame(picker, bg=self.bg_color, highlightthickness=0, bd=0)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(list_frame, width=45, bg="#444", troughcolor=self.bg_color, highlightthickness=0, borderwidth=0)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        lb = tk.Listbox(
            list_frame, font=self.medium_font, bg="#333", fg="#FFF", 
            yscrollcommand=scrollbar.set, relief=tk.FLAT, borderwidth=0,
            highlightthickness=0, selectbackground="#FFD700", selectforeground="#000"
        )
        for d in self.out_devices:
            lb.insert(tk.END, f"{d['index']}: {d['name']}")
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=lb.yview)

        def on_select():
            sel = lb.curselection()
            if sel:
                d = self.out_devices[sel[0]]
                self.output_device_index = d['index']
                self.player.set_output_routing(self.output_device_index, self.output_channels)
                self.out_device_info_label.config(text=f"Output: {d['name']}")
                self.save_output_settings()
                picker.destroy()
        
        tk.Button(picker, text="SELECT DEVICE", command=on_select, font=self.button_font, bg="#008000", fg="#FFF", pady=50).pack(fill=tk.X, padx=2, pady=2)

    def show_channel_picker(self):
        picker = tk.Toplevel(self.root)
        picker.overrideredirect(True)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        picker.geometry(f"{screen_w}x{screen_h}+0+0")
        picker.configure(bg=self.bg_color, highlightthickness=0, bd=0)
        picker.grab_set()
        
        # Get max channels for current device
        max_ch = 2
        active_idx = self.output_device_index
        for d in self.out_devices:
            if d['index'] == active_idx:
                max_ch = d['channels']
                break

        # Variables for touch adjustment
        l_var = tk.IntVar(value=self.output_channels[0])
        r_var = tk.IntVar(value=self.output_channels[1])

        def step_ch(var, delta, limit):
            val = var.get() + delta
            if 0 <= val < limit:
                var.set(val)

        tk.Label(picker, text=f"SELECT CHANNELS (0-{max_ch-1})", font=self.medium_font, bg=self.bg_color, fg="#FFD700").pack(pady=10)

        # Container for both selectors
        selectors_frame = tk.Frame(picker, bg=self.bg_color, highlightthickness=0)
        selectors_frame.pack(fill=tk.BOTH, expand=True)

        # Style for +/- buttons
        step_btn_style = {"font": self.button_font, "bg": "#444", "fg": "#FFD700", "width": 3, "relief": tk.FLAT}

        # LEFT Channel Selector
        l_frame = tk.Frame(selectors_frame, bg=self.bg_color, highlightthickness=0)
        l_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=10)
        tk.Label(l_frame, text="LEFT", font=self.log_font, bg=self.bg_color, fg="#FFF").pack()
        
        tk.Button(l_frame, text="+", command=lambda: step_ch(l_var, 1, max_ch), **step_btn_style).pack(pady=2)
        tk.Label(l_frame, textvariable=l_var, font=self.button_font, bg=self.bg_color, fg="#FFD700").pack(pady=2)
        tk.Button(l_frame, text="-", command=lambda: step_ch(l_var, -1, max_ch), **step_btn_style).pack(pady=2)

        # RIGHT Channel Selector
        r_frame = tk.Frame(selectors_frame, bg=self.bg_color, highlightthickness=0)
        r_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=10)
        tk.Label(r_frame, text="RIGHT", font=self.log_font, bg=self.bg_color, fg="#FFF").pack()
        
        tk.Button(r_frame, text="+", command=lambda: step_ch(r_var, 1, max_ch), **step_btn_style).pack(pady=2)
        tk.Label(r_frame, textvariable=r_var, font=self.button_font, bg=self.bg_color, fg="#FFD700").pack(pady=2)
        tk.Button(r_frame, text="-", command=lambda: step_ch(r_var, -1, max_ch), **step_btn_style).pack(pady=2)

        def on_save():
            l = l_var.get()
            r = r_var.get()
            self.output_channels = [l, r]
            self.player.set_output_routing(active_idx, self.output_channels)
            self.out_channels_info_label.config(text=f"Channels: {l+1}, {r+1}")
            self.save_output_settings()
            picker.destroy()
        
        tk.Button(picker, text="SAVE CHANNELS", command=on_save, font=self.button_font, bg="#008000", fg="#FFF", pady=30).pack(fill=tk.X, padx=5, pady=5)

    def create_playback_browser_screen(self):
        frame = tk.Frame(self.root, bg=self.bg_color)
        self.frames["playback_browser"] = frame
        
        # Header
        header = tk.Frame(frame, bg=self.bg_color)
        header.pack(fill=tk.X)
        
        self.browser_back_btn = tk.Button(
            header, text="Back", command=self.back_from_browser,
            font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=30, pady=10
        )
        self.browser_back_btn.pack(side=tk.LEFT)
        
        tk.Label(header, text="Sessions", font=self.medium_font, bg=self.bg_color, fg=self.fg_color).pack(side=tk.LEFT, padx=10)
        
        self.browser_free_label = tk.Label(header, text="", font=self.log_font, bg=self.bg_color, fg="#FFD700")
        self.browser_free_label.pack(side=tk.LEFT, expand=True)
        
        # Storage Toggle
        self.storage_toggle_btn = tk.Button(
            header, text="Source: USB", command=self.toggle_playback_storage,
            font=self.log_font, bg="#4A4A4A", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=20
        )
        self.storage_toggle_btn.pack(side=tk.RIGHT, padx=10)
        
        # Listbox with Scrollbar
        list_frame = tk.Frame(frame, bg=self.bg_color)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.session_listbox = tk.Listbox(
            list_frame, font=self.log_font, bg="#1e2419", fg=self.fg_color, 
            selectbackground="#FFD700", selectforeground="#000", borderwidth=0, highlightthickness=0
        )
        self.session_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.session_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.session_listbox.config(yscrollcommand=scrollbar.set)
        
        # Open Button
        self.open_mixer_btn = tk.Button(
            frame, text="Open Mixer", command=self.open_mixer,
            font=self.button_font, bg="#008000", fg=self.fg_color, relief=tk.FLAT, pady=10
        )
        self.open_mixer_btn.pack(fill=tk.X, padx=30, pady=10)

    def back_from_browser(self):
        if self.playback_storage == "USB":
            # Blocca l'interfaccia e mostra status mentre smonta
            self.browser_back_btn.config(state=tk.DISABLED)
            self.storage_toggle_btn.config(state=tk.DISABLED)
            self.browser_free_label.config(text="UNMOUNTING...", fg="#FF4500")
            
            def work():
                recorder.unmount_usb_drive()
                # Torna alla home solo a operazione completata
                def finish():
                    self.playback_storage = "SD"
                    self.browser_back_btn.config(state=tk.NORMAL)
                    self.storage_toggle_btn.config(state=tk.NORMAL)
                    self.browser_free_label.config(text="")
                    self.update_storage_button_text()
                    self.show_frame("home")
                
                self.root.after(0, finish)
            
            threading.Thread(target=work, daemon=True).start()
        else:
            self.show_frame("home")

    def toggle_playback_storage(self):
        self.storage_toggle_btn.config(state=tk.DISABLED)
        self.browser_back_btn.config(state=tk.DISABLED)
        if self.playback_storage == "USB":
            self.browser_free_label.config(text="UNMOUNTING...", fg="#FF4500")
            def work():
                recorder.unmount_usb_drive()
                self.root.after(0, lambda: self.finish_storage_toggle("SD"))
        else:
            self.browser_free_label.config(text="MOUNTING...", fg="#FFD700")
            def work():
                success = recorder.mount_usb_drive()
                self.root.after(0, lambda: self.finish_storage_toggle("USB" if success else "SD"))
        
        threading.Thread(target=work, daemon=True).start()

    def finish_storage_toggle(self, result_storage):
        self.playback_storage = result_storage
        self.storage_toggle_btn.config(state=tk.NORMAL)
        self.browser_back_btn.config(state=tk.NORMAL)
        # Resettiamo il testo così refresh_session_list può scrivere il FREE:
        self.browser_free_label.config(text="")
        self.update_storage_button_text()
        self.refresh_session_list()

    def update_storage_button_text(self):
        self.storage_toggle_btn.config(text=f"Source: {self.playback_storage}")

    def refresh_session_list(self):
        self.session_listbox.delete(0, tk.END)
        
        # If USB selected but not mounted, fallback to SD
        if self.playback_storage == "USB" and not os.path.ismount(recorder.USB_MOUNT_POINT):
            self.playback_storage = "SD"
            self.update_storage_button_text()
            recorder.log("USB not mounted, falling back to SD for playback.")

        base = recorder.USB_MOUNT_POINT if self.playback_storage == "USB" else recorder.FALLBACK_STORAGE_PATH
        
        # Aggiorna indicatore spazio libero nel browser
        if hasattr(self, "browser_free_label"):
            # Se la label è vuota o contiene già FREE, aggiorniamo.
            # Se contiene MOUNTING/UNMOUNTING e siamo ancora occupati, non sovrascriviamo.
            current_txt = self.browser_free_label.cget("text")
            if "MOUNTING" not in current_txt:
                free_str = self.get_free_time_string(path=base)
                self.browser_free_label.config(text=free_str, fg="#FFD700")
        
        if os.path.exists(base):
            for folder in sorted(os.listdir(base), reverse=True):
                if folder.startswith("recording_"):
                    self.session_listbox.insert(tk.END, folder)

    def open_mixer(self):
        selection = self.session_listbox.curselection()
        if not selection:
            return
        
        folder_name = self.session_listbox.get(selection[0])
        # Find path
        folder_path = None
        for base in [recorder.USB_MOUNT_POINT, recorder.FALLBACK_STORAGE_PATH]:
            p = os.path.join(base, folder_name)
            if os.path.exists(p):
                folder_path = p
                break
        
        if folder_path:
            self.current_playback_folder = folder_path
            self.open_mixer_btn.config(text="Loading...", state=tk.DISABLED)
            
            # Use a thread to avoid freezing the GUI
            def load_task():
                try:
                    self.player.load_folder(folder_path)
                except Exception as e:
                    recorder.log(f"Error loading session: {e}")
                
                # Update UI in main thread
                self.root.after(0, self.finish_open_mixer)
            
            threading.Thread(target=load_task, daemon=True).start()

    def finish_open_mixer(self):
        self.open_mixer_btn.config(text="Open Mixer", state=tk.NORMAL)
        # Load mixer settings if mixer.json exists
        settings_path = os.path.join(self.current_playback_folder, "mixer.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    data = json.load(f)
                master_vol = data.get("master_volume", 1.0)
                self.adjust_master_vol(master_vol - self.master_vol)
                track_settings = data.get("tracks", [])
                for i, t_data in enumerate(track_settings):
                    if i < len(self.player.tracks):
                        self.player.set_track_volume(i, t_data.get("volume", 0.8))
                        self.player.set_track_pan(i, t_data.get("pan", 0.0))
            except Exception as e:
                print(f"Error loading mixer.json: {e}")
        
        self.show_frame("mixer")
        self.refresh_mixer_ui()

    def create_mixer_screen(self):
        frame = tk.Frame(self.root, bg=self.bg_color)
        self.frames["mixer"] = frame
        
        # --- TOP BAR ---
        top_bar = tk.Frame(frame, bg=self.bg_color)
        top_bar.pack(fill=tk.X)
        
        tk.Button(
            top_bar, text="Back", command=self.stop_and_back,
            font=self.log_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=15, pady=8
        ).pack(side=tk.LEFT)
        
        self.play_btn = tk.Button(
            top_bar, text="Play", command=self.toggle_playback,
            font=self.log_font, bg="#008000", fg=self.fg_color, relief=tk.FLAT, borderwidth=0, padx=15, pady=8
        )
        self.play_btn.pack(side=tk.LEFT, padx=5)

        # Track Scroll (Top Center)
        track_scroll_frame = tk.Frame(top_bar, bg=self.bg_color)
        track_scroll_frame.pack(side=tk.LEFT, expand=True)
        
        tk.Button(
            track_scroll_frame, text="<<", command=lambda: self.mixer_canvas.xview_scroll(-1, 'pages'),
            font=self.log_font, bg="#333", fg="#FFD700", relief=tk.FLAT, borderwidth=1, padx=10
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Button(
            track_scroll_frame, text=">>", command=lambda: self.mixer_canvas.xview_scroll(1, 'pages'),
            font=self.log_font, bg="#333", fg="#FFD700", relief=tk.FLAT, borderwidth=1, padx=10
        ).pack(side=tk.LEFT, padx=2)

        # Master Volume (Top Right)
        master_vol_frame = tk.Frame(top_bar, bg=self.bg_color)
        master_vol_frame.pack(side=tk.RIGHT, padx=5)
        
        tk.Button(
            master_vol_frame, text="-", command=lambda: self.adjust_master_vol(-0.05),
            font=self.log_font, bg="#444", fg="#FFD700", relief=tk.FLAT, width=3
        ).pack(side=tk.LEFT)
        
        self.master_vol_label = tk.Label(master_vol_frame, text="0dB", font=self.log_font, bg=self.bg_color, fg="#FFD700", width=6)
        self.master_vol_label.pack(side=tk.LEFT)
        
        tk.Button(
            master_vol_frame, text="+", command=lambda: self.adjust_master_vol(0.05),
            font=self.log_font, bg="#444", fg="#FFD700", relief=tk.FLAT, width=3
        ).pack(side=tk.LEFT)
        
        # --- BOTTOM BAR ---
        bottom_bar = tk.Frame(frame, bg=self.bg_color, height=60)
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
        bottom_bar.pack_propagate(False)

        # Seek Left (Backward)
        self.seek_back_btn = tk.Button(
            bottom_bar, text="<<", font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, width=6
        )
        self.seek_back_btn.pack(side=tk.LEFT, padx=15, fill=tk.Y, pady=5)
        self.seek_back_btn.bind("<ButtonPress-1>", lambda e: self.start_seek(-1))
        self.seek_back_btn.bind("<ButtonRelease-1>", lambda e: self.stop_seek())

        # Time Display (Center)
        self.time_label = tk.Label(bottom_bar, text="00:00:00 / 00:00:00", font=self.log_font, bg=self.bg_color, fg="#FFD700")
        self.time_label.pack(side=tk.LEFT, expand=True)

        # Seek Right (Forward)
        self.seek_fwd_btn = tk.Button(
            bottom_bar, text=">>", font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, width=6
        )
        self.seek_fwd_btn.pack(side=tk.RIGHT, padx=15, fill=tk.Y, pady=5)
        self.seek_fwd_btn.bind("<ButtonPress-1>", lambda e: self.start_seek(1))
        self.seek_fwd_btn.bind("<ButtonRelease-1>", lambda e: self.stop_seek())
        
        # --- MIXER AREA ---
        mixer_container = tk.Frame(frame, bg=self.bg_color)
        mixer_container.pack(fill=tk.BOTH, expand=True)
        
        self.mixer_canvas = tk.Canvas(mixer_container, bg=self.bg_color, highlightthickness=0)
        self.mixer_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.mixer_inner = tk.Frame(self.mixer_canvas, bg=self.bg_color)
        self.mixer_canvas.create_window((0, 0), window=self.mixer_inner, anchor="nw")

    def adjust_master_vol(self, delta):
        self.master_vol = max(0.0, min(2.0, self.master_vol + delta))
        self.player.set_master_volume(self.master_vol)
        # dB = 20 * log10(lin)
        if self.master_vol > 0:
            db = 20 * np.log10(self.master_vol)
            self.master_vol_label.config(text=f"{db:+.1f}dB")
        else:
            self.master_vol_label.config(text="-inf dB")

    def start_seek(self, direction):
        self.seek_direction = direction
        self.seek_start_time = time.time()
        # Initial jump (15s)
        self.player.seek(self.player.get_current_time() + (direction * 15))
        self.update_playback_time()
        # Start repeat
        self.seek_timer = self.root.after(500, self.do_seek)

    def do_seek(self):
        if self.seek_direction == 0:
            return
        
        elapsed = time.time() - self.seek_start_time
        # Accelerated seek: 30s (<5s), 60s (<10s), 300s/5min (>=10s)
        if elapsed < 5:
            step = 30
        elif elapsed < 10:
            step = 60
        else:
            step = 300
        
        self.player.seek(self.player.get_current_time() + (self.seek_direction * step))
        self.update_playback_time()
        self.seek_timer = self.root.after(500, self.do_seek)

    def stop_seek(self):
        self.seek_direction = 0
        if self.seek_timer:
            self.root.after_cancel(self.seek_timer)
            self.seek_timer = None

    def update_playback_time(self):
        curr = self.player.get_current_time()
        total = self.player.get_total_time()
        self.time_label.config(text=f"{self.format_time(curr)} / {self.format_time(total)}")
        if self.player.is_playing:
            self.root.after(500, self.update_playback_time)

    def format_time(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
        
    def refresh_mixer_ui(self):
        for widget in self.mixer_inner.winfo_children():
            widget.destroy()
            
        for i, track in enumerate(self.player.tracks):
            track_frame = tk.Frame(self.mixer_inner, bg="#3d4735", highlightthickness=1, highlightbackground="#555", padx=5, pady=5)
            track_frame.pack(side=tk.LEFT, fill=tk.Y, padx=2)
            
            tk.Label(track_frame, text=f"CH {i+1}", font=self.input_font, bg="#3d4735", fg="#FFD700").pack()
            
            # Volume Slider (Vertical)
            vol_scale = tk.Scale(
                track_frame, from_=1.0, to=0.0, resolution=0.05, 
                orient=tk.VERTICAL, length=120, bg="#3d4735", fg=self.fg_color,
                highlightthickness=0, borderwidth=0, command=lambda v, idx=i: self.set_mixer_param(idx, 'volume', float(v))
            )
            vol_scale.set(track['volume'])
            vol_scale.pack(pady=5)
            
            # Pan Slider (Horizontal)
            pan_scale = tk.Scale(
                track_frame, from_=-1.0, to=1.0, resolution=0.1,
                orient=tk.HORIZONTAL, label="Pan", length=60, bg="#3d4735", fg=self.fg_color,
                highlightthickness=0, borderwidth=0, command=lambda v, idx=i: self.set_mixer_param(idx, 'pan', float(v))
            )
            pan_scale.set(track['pan'])
            pan_scale.pack()
            
        self.mixer_inner.update_idletasks()
        self.mixer_canvas.config(scrollregion=self.mixer_canvas.bbox("all"))

    def set_mixer_param(self, index, key, value):
        if key == 'volume':
            self.player.set_track_volume(index, value)
        elif key == 'pan':
            self.player.set_track_pan(index, value)
        self.save_mixer_settings()

    def save_output_settings(self):
        try:
            settings = {
                "device_index": self.output_device_index,
                "channels": self.output_channels
            }
            with open(self.output_settings_path, "w") as f:
                json.dump(settings, f)
            recorder.log("Output settings saved.")
        except Exception as e:
            recorder.log(f"Error saving output settings: {e}")

    def load_output_settings(self):
        try:
            if os.path.exists(self.output_settings_path):
                with open(self.output_settings_path, "r") as f:
                    settings = json.load(f)
                self.output_device_index = settings.get("device_index")
                self.output_channels = settings.get("channels", [0, 1])
                
                # Apply to player
                self.player.set_output_routing(self.output_device_index, self.output_channels)
                
                # Update current device name for UI display
                devices = self.player.get_output_devices()
                self.out_devices = devices
                for d in devices:
                    if d['index'] == self.output_device_index:
                        self.current_out_name = d['name']
                        break
                recorder.log(f"Output settings loaded: Device {self.output_device_index}, Ch {self.output_channels}")
        except Exception as e:
            recorder.log(f"Error loading output settings: {e}")

    def save_mixer_settings(self):
        if not self.current_playback_folder:
            return
        settings_path = os.path.join(self.current_playback_folder, "mixer.json")
        try:
            data = {
                "master_volume": self.master_vol,
                "tracks": [{"volume": t["volume"], "pan": t["pan"]} for t in self.player.tracks]
            }
            with open(settings_path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving mixer.json: {e}")

    def toggle_playback(self):
        if self.player.is_playing:
            self.player.pause()
            self.play_btn.config(text="Play", bg="#008000")
        else:
            self.player.play()
            self.play_btn.config(text="Pause", bg="#B22222")
            self.update_playback_time() # Restart the time update loop

    def stop_and_back(self):
        self.player.stop()
        if hasattr(self, "play_btn"):
            self.play_btn.config(text="Play", bg="#008000")
        if hasattr(self, "time_label"):
            self.update_playback_time() # Final update to 0:00:00
        self.show_frame("playback_browser")


    def create_inputs_screen(self):
        # Invece di distruggere l'intero frame (che causa problemi di visualizzazione), 
        # lo svuotiamo se esiste già.
        if "inputs" in self.frames:
            for widget in self.frames["inputs"].winfo_children():
                widget.destroy()
            frame = self.frames["inputs"]
        else:
            frame = tk.Frame(self.root, bg=self.bg_color)
            self.frames["inputs"] = frame
        
        recorder.log(f"Refreshing inputs screen. Count: {len(self.inputs)}")

        # Pulsante Back SEMPRE presente
        back_btn = tk.Button(
            frame, text="Back", command=lambda: self.show_frame("home"),
            font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=50, pady=20,
            takefocus=0
        )
        back_btn.pack(side=tk.TOP, anchor="ne", padx=0, pady=0)

        if not recorder.is_device_connected():
            error_label = tk.Label(
                frame, text="NO USB AUDIO DEVICE CONNECTED", 
                font=self.button_font, bg=self.bg_color, fg="#FF4500"
            )
            error_label.pack(expand=True)
            return

        # Contenitore principale per navigation + canvas
        main_container = tk.Frame(frame, bg=self.bg_color)
        main_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Pulsanti di navigazione orizzontale ai lati (Fixed character width)
        left_btn = tk.Button(
            main_container, text="<<", command=lambda: canvas.xview_scroll(-1, 'pages'),
            font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=1, width=4, takefocus=0
        )
        left_btn.pack(side=tk.LEFT, fill=tk.Y)

        right_btn = tk.Button(
            main_container, text=">>", command=lambda: canvas.xview_scroll(1, 'pages'),
            font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=1, width=4, takefocus=0
        )
        right_btn.pack(side=tk.RIGHT, fill=tk.Y)

        # Canvas centrale (360px per mostrare esattamente 2 colonne da 180px)
        canvas = tk.Canvas(main_container, bg=self.bg_color, highlightthickness=0, width=360)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbar sottile in fondo
        h_scroll = tk.Scrollbar(frame, orient=tk.HORIZONTAL, command=canvas.xview, width=20)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        canvas.configure(xscrollcommand=h_scroll.set)

        # Frame interno scrollabile
        inner = tk.Frame(canvas, bg=self.bg_color)
        canvas.create_window((0, 0), window=inner, anchor="nw")

        self.input_circles = []
        self.input_audio_circles = []

        # Layout: 3 righe per colonna, 2 colonne visibili (360px / 180px = 2)
        inputs_per_col = 3
        col_width = 138
        row_height = 80 
        circle_r = 22  

        for idx, name in enumerate(self.inputs):
            col = idx // inputs_per_col
            row = idx % inputs_per_col
            
            # Estraggo solo il numero dal nome (es: "INPUT 1" -> "1")
            short_name = name.split()[-1]

            # Canvas per ogni input
            input_canvas = tk.Canvas(inner, width=col_width-10, height=row_height-5, bg=self.bg_color, highlightthickness=1)
            input_canvas.grid(row=row, column=col, padx=5, pady=2)

            # Cerchio abilitazione (Più grande)
            circle = input_canvas.create_oval(10, 15, 10+circle_r*2, 15+circle_r*2,
                                              fill="#00FF00", outline="")
            if not self.input_enabled[idx]:
                input_canvas.itemconfig(circle, fill="#006400")
            self.input_circles.append((input_canvas, circle))
            
            # Cerchio audio detect
            audio_circle = input_canvas.create_oval(10+circle_r*2+12, 28, 10+circle_r*2+12+15, 24+15,
                                                   fill="#222", outline="")
            self.input_audio_circles.append((input_canvas, audio_circle))
            
            # Numero input (Fonte più piccolo e spostato di 4px a dx rispetto a prima)
            input_canvas.create_text(10+circle_r*2+12+24, 38, text=short_name, anchor="w", fill="#FFD700", font=self.button_font)
            
            # Click handler
            input_canvas.bind("<Button-1>", lambda e, i=idx: self.toggle_input(i))
            input_canvas.tag_bind(circle, "<Button-1>", lambda e, i=idx: self.toggle_input(i))

        inner.update_idletasks()
        canvas.config(scrollregion=canvas.bbox("all"))
        canvas.xview_moveto(0)
        self.update_inputs_screen()

    def format_duration(self, seconds):
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h:02}:{m:02}:{s:02}"
        elif m > 0:
            return f"{m:02}:{s:02}"
        else:
            return f"{s:02}"
    
    def monitor_audio_levels(self):
        if not self.audio_monitoring:
            return
        
        # Don't monitor levels via arecord if we are currently recording (avoids hardware conflict)
        if recorder.is_recording:
            self.root.after(1000, self.monitor_audio_levels)
            return

        try:
            recorder.log("alsa device: " + self.alsa_device+ " inputs: " + str(len(self.inputs)))
        
            levels = recorder.get_input_levels(self.alsa_device,len(self.inputs))
        except Exception:
            self.refresh_card()
            self.refresh_inputs()
            levels = [random.uniform(-48, 0) for _ in self.inputs]
        for i, level in enumerate(levels):
            self.input_audio_detected[i] = (level > -24)
        self.update_inputs_screen()
        self.root.after(200, self.monitor_audio_levels)

    def show_frame(self, name):
        for f in self.frames.values():
            f.pack_forget()
        self.frames[name].pack(fill=tk.BOTH, expand=True)

        if name == "inputs":
            if not self.audio_monitoring:
                self.audio_monitoring = True
                self.create_inputs_screen() # Ricrea sempre per gestire stato disconnesso
                if recorder.is_device_connected():
                    self.refresh_card()
                    self.refresh_inputs()
                    self.update_inputs_screen()
                    self.monitor_audio_levels()
            else:
                # Se è già attivo, aggiorna solo la vista per gestire disconnessioni
                self.create_inputs_screen()
        elif name == "output":
            self.create_output_screen()
        elif name == "wifi_config":
            self.scan_wifi_networks()
        elif name == "playback_browser":
            # Assicuriamoci che i tasti siano abilitati (nel caso fossimo usciti male)
            if hasattr(self, "browser_back_btn"): self.browser_back_btn.config(state=tk.NORMAL)
            if hasattr(self, "storage_toggle_btn"): self.storage_toggle_btn.config(state=tk.NORMAL)
            self.refresh_session_list()
        elif name == "mixer":
            self.update_playback_time()
        else:
            self.audio_monitoring = False
            # Se usciamo dai frame di playback (galleria o mixer), smontiamo USB
            if self.player.is_playing:
                self.player.stop()
                if hasattr(self, "play_btn"):
                    self.play_btn.config(text="Play", bg="#008000")
            
            if name == "home" and self.playback_storage == "USB":
                # Lo smontaggio è ora gestito esplicitamente da back_from_browser
                pass
        
        if name == "settings":
            self.update_samplerate_buttons()
            self.update_wifi_buttons()
            self.update_wifi_ssid()
            self.update_clock_label()

    # --- LOG --- 
    def append_log(self, msg):
        # Thread-safe log append
        self.root.after(0, self._append_log_main, msg)

    def _append_log_main(self, msg):
        self.log_lines.append(msg)
        if len(self.log_lines) > 50:
            self.log_lines = self.log_lines[-50:]
            
        if hasattr(self, "log_listbox"):
            self.log_listbox.insert(tk.END, msg)
            if self.log_listbox.size() > 50:
                self.log_listbox.delete(0)
            self.log_listbox.yview_moveto(1.0)

    # --- INPUTS ---
    def toggle_input(self, idx):
        if recorder.is_recording:
            return
        self.input_enabled[idx] = not self.input_enabled[idx]
        self.save_input_enabled()  # <--- salva lo stato ogni volta che cambi
        self.update_inputs_screen()
        
    def update_inputs_screen(self):
        for idx, (input_canvas, circle) in enumerate(self.input_circles):
            color = "#00FF00" if self.input_enabled[idx] else "#006400"
            input_canvas.itemconfig(circle, fill=color)
        for idx, (input_canvas, audio_circle) in enumerate(self.input_audio_circles):
            detected = self.input_audio_detected[idx]
            color = "#FF0000" if detected else "#222"
            input_canvas.itemconfig(audio_circle, fill=color)
        if recorder.is_recording:
            self.inputs_button.config(state=tk.DISABLED)
        else:
            self.inputs_button.config(state=tk.NORMAL)

    # --- RECORDING ---
    def toggle_recording(self):
        # Disabilita subito il pulsante e mostra "..."
        self.record_button.config(state=tk.DISABLED, text="...")
        self.root.update_idletasks()
        if not recorder.is_recording:
            self.root.after(100, self.start_recording)
        else:
            self.root.after(100, self.stop_recording)


    def status_callback(self, text, color):
        # Thread-safe status update
        self.root.after(0, self._status_callback_main, text, color)

    def _status_callback_main(self, text, color):
        recorder.log(f"Status update: {text} (color: {color})")
        self.status_label.config(text=text, fg=color)
        self.status = text

    def start_recording(self):
        self.append_log("GUI: Start button pressed.")
        selected_inputs = [i for i, enabled in enumerate(self.input_enabled) if enabled]
        # Mostra spinner/disabilitato finché non termina
        self.record_button.config(state=tk.DISABLED, text="Starting...")
        self.root.update_idletasks()
        self.last_time = 0
        self.recording_time = 0
        self.status = "-"
        success = recorder.start_recording(selected_inputs=selected_inputs, status_callback=self.status_callback)
        if success:
          
            self.record_button.config(
                text="Stop Recording",
                bg="#B22222",
                activebackground="#8B0000",
                state=tk.NORMAL
            )
            self.update_info_label()
            self.inputs_button.config(state=tk.DISABLED)
        else:
            self.record_button.config(
                text="Start Recording",
                bg="#008000",
                activebackground="#006400",
                state=tk.NORMAL
            )

    def stop_recording(self):
        self.append_log("GUI: Stop button pressed.")
        # Mostra spinner/disabilitato finché non termina
        self.record_button.config(state=tk.DISABLED, text="Stopping...")
        self.root.update_idletasks()
        success = recorder.stop_recording()
        if success:
            self.status_label.config(text="-", fg=self.fg_color)
            self.record_button.config(
                text="Start Recording",
                bg="#008000",
                activebackground="#006400",
                state=tk.NORMAL
            )
            self.info_label.config(text="")
            self.inputs_button.config(state=tk.NORMAL)
        else:
            self.record_button.config(
                text="Stop Recording",
                bg="#B22222",
                activebackground="#8B0000",
                state=tk.NORMAL
            )

    def update_info_label(self):
        if recorder.is_recording and recorder.recording_start_time:
            current_time = time.time()
            if(self.last_time == 0):
                self.last_time = recorder.recording_start_time
            if(self.status=="RESUMING"):
                elapsed = 0
            else:
                elapsed = current_time - self.last_time
            self.last_time = current_time
            self.recording_time = self.recording_time + elapsed
            drive = "USB" if getattr(recorder, "current_storage", None) == "USB" else "SD"
            formatted_elapsed = self.format_duration(self.recording_time)
            self.info_label.config(text=f"Rec on {drive} | {formatted_elapsed}")
            if not self.info_label.winfo_viewable():
                # Try to pack it after warning, or status
                target = self.device_warning_label if self.device_warning_label.winfo_viewable() else self.status_label
                self.info_label.pack(after=target, pady=(6, 0))
        else:
            if self.info_label.winfo_viewable():
                self.info_label.pack_forget()
            self.info_label.config(text="")

    def update_status(self):
        # Polling dello stato registrazione per pulsanti Home
        if recorder.is_recording:
            if self.playback_button.winfo_viewable():
                self.playback_button.config(state=tk.DISABLED)
        else:
            if self.playback_button.winfo_viewable():
                self.playback_button.config(state=tk.NORMAL)

        # Polling della scheda audio
        if not recorder.is_recording:
            # Auto-fallback to SD if USB is disconnected in browser
            if self.frames["playback_browser"].winfo_viewable() and self.playback_storage == "USB":
                if not os.path.ismount(recorder.USB_MOUNT_POINT):
                    recorder.log("USB disconnected, switching playback view to SD.")
                    self.playback_storage = "SD"
                    self.update_storage_button_text()
                    self.refresh_session_list()

            is_connected = recorder.is_device_connected()
            if not is_connected:
                self.status_label.config(text="DISCONNECTED", fg="#FF4500")
                if self.record_button['text'] != "NO USB AUDIO":
                    self.record_button.config(text="NO USB AUDIO", state=tk.DISABLED, bg="#4A4A4A")
                if not self.device_warning_label.winfo_viewable():
                    self.device_warning_label.pack(after=self.status_label, pady=(6, 0))
            else:
                if self.status == "-" and self.status_label['text'] == "DISCONNECTED":
                    self.status_label.config(text="-", fg=self.fg_color)
                
                if self.record_button['text'] == "NO USB AUDIO":
                    self.record_button.config(text="Start Recording", state=tk.NORMAL, bg="#008000")
                    self.refresh_card()
                    self.refresh_inputs()
                
                if self.device_warning_label.winfo_viewable():
                    self.device_warning_label.pack_forget()

        # self.refresh_inputs()
        if not getattr(recorder, "is_recording", False) and self.record_button['text'] == "Stop Recording":
            self.append_log("GUI: Detected recording has stopped unexpectedly.")
            self.stop_recording()
        self.update_info_label()
        self.root.after(1000, self.update_status)
        
        # Nascondi/Mostra i pulsanti Settings, Inputs, Playback, Output
        is_rec = getattr(recorder, "is_recording", False)
        # Solo se siamo nel frame home
        if self.frames["home"].winfo_viewable():
            if is_rec:
                if self.settings_button.winfo_viewable():
                    self.settings_button.pack_forget()
                    self.inputs_button.pack_forget()
                    self.playback_button.pack_forget()
                    self.output_button.pack_forget()
            else:
                if not self.settings_button.winfo_viewable():
                    # Ripristina con i parametri originali di create_home_screen
                    self.settings_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)
                    self.inputs_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)
                    self.output_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)
                    self.playback_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)

if __name__ == "__main__":
    main_window = tk.Tk()
    main_window.attributes('-fullscreen', True)
    app = RecorderApp(main_window)
    main_window.mainloop()