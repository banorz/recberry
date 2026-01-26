#!/usr/bin/env python3

import json
import os
import re
import subprocess
import tkinter as tk
from tkinter import font
import time
import recorder
import random

class RecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Recberry Controller")
        self.root.geometry("480x320")
        self.root.resizable(False, False)

        self.bg_color = "#2c3425"
        self.fg_color = "#FFFFFF"
        self.button_color = "#4A4A4A"
        self.status_font = font.Font(family="Helvetica", size=24, weight="bold")
        self.button_font = font.Font(family="Helvetica", size=20)
        self.log_font = font.Font(family="Helvetica", size=12)
        self.input_font = font.Font(family="Helvetica", size=10, weight="bold")
        self.status = "-"
        self.root.configure(bg=self.bg_color)
        
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
        # Log
        self.log_lines = []
        recorder.set_log_callback(self.append_log)
        self.recording_time = 0
        self.last_time = 0
        # Schermate
        self.frames = {}
        self.create_home_screen()
        self.create_inputs_screen()
        self.create_settings_screen()  # <--- AGGIUNGI QUESTO
        self.show_frame("home")

        self.update_status()

    def get_samplerate(self):
        return recorder._samplerate if hasattr(recorder, "_samplerate") else 48000
    
    def set_samplerate(self, rate):
        recorder._samplerate = rate
        self.samplerate = rate
        self.update_samplerate_buttons()
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

    def update_wifi_buttons(self):
        if self.wifi_enabled:
            self.wifi_enable_btn.config(bg="#008000", fg=self.fg_color)
            self.wifi_disable_btn.config(bg="#4A4A4A", fg=self.fg_color)
        else:
            self.wifi_enable_btn.config(bg="#4A4A4A", fg=self.fg_color)
            self.wifi_disable_btn.config(bg="#008000", fg=self.fg_color)

    def update_wifi_ssid(self):
        print("ciao")
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

        # --- Back Button ---
        back_btn = tk.Button(
            frame, text="Back", command=lambda: self.show_frame("home"),
            font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=50, pady=20
        )
        back_btn.grid(row=0, column=0, sticky="nw", padx=0, pady=0)

        # --- Restart LightDM Button ---
        restart_frame = tk.Frame(frame, bg=self.bg_color)
        restart_frame.grid(row=0, column=0, sticky="ne", padx=100, pady=0)  # Posiziona a destra

        self.restart_lightdm_btn = tk.Button(
            restart_frame, text="Restart", command=self.restart_lightdm,
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0
        )
        self.restart_lightdm_btn.pack(side=tk.TOP, anchor="ne", padx=0, pady=0)  # Usa pack nel frame
        
        # --- Sample Rate Options ---
        samplerate_frame = tk.Frame(frame, bg=self.bg_color)
        samplerate_frame.grid(row=1, column=0, pady=20)

        self.samplerate = self.get_samplerate()
        self.samplerate_44100_btn = tk.Button(
            samplerate_frame, text="44100 Hz", command=lambda: self.set_samplerate(44100),
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0
        )
        self.samplerate_48000_btn = tk.Button(
            samplerate_frame, text="48000 Hz", command=lambda: self.set_samplerate(48000),
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0
        )
        self.update_samplerate_buttons()  # Imposta lo stato iniziale dei bottoni

        self.samplerate_44100_btn.grid(row=0, column=0, padx=10)
        self.samplerate_48000_btn.grid(row=0, column=1, padx=10)

        # --- WiFi Options ---
        wifi_frame = tk.Frame(frame, bg=self.bg_color)
        wifi_frame.grid(row=2, column=0, pady=20)

        self.wifi_enabled = True  # Inizializza con lo stato corrente
        self.wifi_enable_btn = tk.Button(
            wifi_frame, text="WiFi Enable", command=self.enable_wifi,
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0
        )
        self.wifi_disable_btn = tk.Button(
            wifi_frame, text="WiFi Disable", command=self.disable_wifi,
            font=self.button_font, bg="#4A4A4A", fg=self.fg_color, relief=tk.FLAT, borderwidth=0
        )
        self.update_wifi_buttons()  # Imposta lo stato iniziale dei bottoni

        self.wifi_enable_btn.grid(row=0, column=0, padx=10)
        self.wifi_disable_btn.grid(row=0, column=1, padx=10)

        self.wifi_ssid_label = tk.Label(
            wifi_frame, text="SSID: Not Connected", font=self.log_font, bg=self.bg_color, fg="#FFD700"
        )
        self.wifi_ssid_label.grid(row=1, column=0, columnspan=2, pady=10)
        self.update_wifi_ssid()  # Aggiorna l'SSID all'avvio
        
    
    # --- SCHERMATE ---
    def create_home_screen(self):
        frame = tk.Frame(self.root, bg=self.bg_color)
        self.frames["home"] = frame

        top_frame = tk.Frame(frame, bg=self.bg_color)
        top_frame.pack(fill=tk.X, pady=0)

        # Pulsante Settings
        self.settings_button = tk.Button(
            top_frame, text="Settings", command=lambda: self.show_frame("settings"),
            font=self.log_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=50, pady=20
        )
        self.settings_button.pack(side=tk.LEFT, anchor="nw")

        self.inputs_button = tk.Button(
            top_frame, text="Inputs", command=lambda: self.show_frame("inputs"),
            font=self.log_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=50, pady=20
        )
        self.inputs_button.pack(side=tk.RIGHT, anchor="ne")

        self.status_label = tk.Label(
            top_frame, text="-", font=self.status_font, bg=self.bg_color, fg=self.fg_color, pady=10
        )
        self.status_label.pack(anchor="nw", side=tk.TOP, padx=30, pady=10)

        self.info_label = tk.Label(
            frame, text="", font=self.log_font, bg=self.bg_color, fg="#FFD700"
        )
        self.info_label.pack(fill=tk.X)
        
        self.device_warning_label = tk.Label(
            frame, text="USB AUDIO NOT FOUND", font=self.status_font, bg=self.bg_color, fg="#FF4500"
        )
        # We'll pack this only when device is missing

        btn_frame = tk.Frame(frame, bg=self.bg_color)
        btn_frame.pack(fill=tk.X, pady=10)

        # Unico pulsante Start/Stop Recording
        self.record_button = tk.Button(
            btn_frame, text="Start Recording", command=self.toggle_recording,
            font=self.button_font, bg="#008000", fg=self.fg_color,
            activebackground="#006400", activeforeground=self.fg_color,
            relief=tk.FLAT, borderwidth=0, highlightthickness=0, pady=30,
            disabledforeground="#666"
        )
        self.record_button.pack(fill=tk.X, padx=30, pady=5)

        # Label per l'ultimo log (max 2 righe)
        self.last_log_label = tk.Label(
            frame, text="", font=self.log_font, bg=self.bg_color, fg="#FFD700",
            wraplength=440, justify="left"
        )
        self.last_log_label.pack(fill=tk.X, padx=10, pady=(5, 0))

    def create_inputs_screen(self):
        if "inputs" in self.frames:
            self.frames["inputs"].destroy()
        
        frame = tk.Frame(self.root, bg=self.bg_color)
        self.frames["inputs"] = frame

        # Pulsante Back SEMPRE presente
        back_btn = tk.Button(
            frame, text="Back", command=lambda: self.show_frame("home"),
            font=self.button_font, bg="#444", fg="#FFD700", relief=tk.FLAT, borderwidth=0, padx=50, pady=20
        )
        back_btn.pack(side=tk.TOP, anchor="ne", padx=0, pady=0)

        if not recorder.is_device_connected():
            error_label = tk.Label(
                frame, text="NO USB AUDIO DEVICE CONNECTED", 
                font=self.button_font, bg=self.bg_color, fg="#FF4500"
            )
            error_label.pack(expand=True)
            return

        # Scrollbar orizzontale
        canvas = tk.Canvas(frame, bg=self.bg_color, highlightthickness=0, width=480, height=150)
        canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=10)

        h_scroll = tk.Scrollbar(frame, orient=tk.HORIZONTAL, command=canvas.xview, width=40)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        canvas.configure(xscrollcommand=h_scroll.set)

        # Frame interno scrollabile
        inner = tk.Frame(canvas, bg=self.bg_color)
        canvas.create_window((0, 0), window=inner, anchor="nw")

        self.input_circles = []
        self.input_audio_circles = []

        # Layout: max 4 input per colonna, colonne affiancate
        inputs_per_col = 3
        col_width = 160
        row_height = 50
        circle_r = 18

        for idx, name in enumerate(self.inputs):
            col = idx // inputs_per_col
            row = idx % inputs_per_col
            x0 = col * col_width + 10
            y0 = row * row_height + 10

            # Canvas per ogni input (per gestire click e cerchi grandi)
            input_canvas = tk.Canvas(inner, width=col_width-10, height=row_height, bg=self.bg_color, highlightthickness=1)
            input_canvas.grid(row=row, column=col, padx=2, pady=2)

            # Cerchio abilitazione
            circle = input_canvas.create_oval(10, 10, 10+circle_r*2, 10+circle_r*2,
                                              fill="#00FF00", outline="")
            if not self.input_enabled[idx]:
                input_canvas.itemconfig(circle, fill="#006400")
            self.input_circles.append((input_canvas, circle))
            # Cerchio audio detect
            audio_circle = input_canvas.create_oval(10+circle_r*2+10, 18, 10+circle_r*2+10+circle_r, 18+circle_r,
                                                   fill="#222", outline="")
            self.input_audio_circles.append((input_canvas, audio_circle))
            # Nome input
            input_canvas.create_text(10+circle_r*2+10+circle_r+10, 30, text=name, anchor="w", fill="#FFD700", font=self.input_font)
            # Click handler
            input_canvas.tag_bind(circle, "<Button-1>", lambda e, i=idx: self.toggle_input(i))

        # Aggiorna la larghezza del canvas interno per lo scroll
        n_cols = (len(self.inputs) + inputs_per_col - 1) // inputs_per_col
        inner.update_idletasks()
        
        canvas.config(scrollregion=canvas.bbox("all"), width=480, height=150)
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
            self.audio_monitoring = True
            self.create_inputs_screen() # Ricrea sempre per gestire stato disconnesso
            if recorder.is_device_connected():
                self.refresh_card()
                self.refresh_inputs()
                self.update_inputs_screen()
                self.monitor_audio_levels()
        else:
            self.audio_monitoring = False
        if name == "settings":
            self.update_samplerate_buttons()
            self.update_wifi_buttons()
            self.update_wifi_ssid()

    # --- LOG --- 
    # mostro solo gli ultimi 150 caratteri 
    def append_log(self, msg):
        self.log_lines.append(msg)
        if len(self.log_lines) > 100:
            self.log_lines = self.log_lines[-100:]
        # Aggiorna la label con l'ultimo messaggio (max 2 righe) 
        last = "\n".join(self.log_lines[-10:])
        if len(last) > 100:
            last = last[-150:]
        if hasattr(self, "last_log_label"):
            self.last_log_label.config(text=last)

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
        else:
            self.info_label.config(text="")

    def update_status(self):
        # Polling della scheda audio
        if not recorder.is_recording:
            is_connected = recorder.is_device_connected()
            if not is_connected:
                self.status_label.config(text="DISCONNECTED", fg="#FF4500")
                if self.record_button['text'] != "NO USB AUDIO":
                    self.record_button.config(text="NO USB AUDIO", state=tk.DISABLED, bg="#4A4A4A")
                if not self.device_warning_label.winfo_viewable():
                    self.device_warning_label.pack(after=self.info_label, pady=5)
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
        
        # Nascondi/Mostra i pulsanti Settings e Inputs
        if recorder.is_recording:
            self.settings_button.pack_forget()
            self.inputs_button.pack_forget()
        else:
            self.settings_button.pack(side=tk.LEFT, anchor="nw")
            self.inputs_button.pack(side=tk.RIGHT, anchor="ne")

if __name__ == "__main__":
    main_window = tk.Tk()
    main_window.attributes('-fullscreen', True)
    app = RecorderApp(main_window)
    main_window.mainloop()