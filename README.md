# 🍰 Recberry (Recpie)
**Recberry** is a standalone multi-channel audio recording system based on Raspberry Pi. Designed to be reliable and easy to use on the go, it features a graphical interface optimized for 3.5" touchscreens (480x320) and intelligent storage management.

<p align="center">
  <img src="logo.png" alt="Recberry Logo" width="200">
</p>

## 🚀 Project Purpose
The goal of Recberry is to transform a Raspberry Pi into a professional "plug-and-play" audio recorder. The system automatically detects connected USB audio interfaces, allows for real-time level monitoring, and ensures recording continuity by automatically switching from a USB drive to the internal SD card in case of disconnection or lack of space.

## ✨ Main Features
- **Multi-channel Recording**: Supports audio interfaces with multiple inputs, recording each channel into a separate lossless FLAC file.
- **Touch Interface**: GUI developed in Tkinter, optimized for 480x320 resolution in fullscreen mode.
- **Failsafe Storage**: Priority saving to USB with automatic fallback to internal SD. Intelligent handling of paths and disk mounting.
- **Audio Monitoring**: Visual feedback of peak levels for each input channel.
- **LED Control**: Visual feedback via the Raspberry Pi's "ACT" LED (fast blinking during recording).
- **Flexible Settings**: Sample rate selection (44.1kHz / 48kHz) and WiFi management directly from the interface.
- **System Logging**: Automatic log file rotation to facilitate debugging without saturating disk space.

## 🛠 Required Hardware
To run Recberry correctly, the following hardware is required:
1. **Raspberry Pi**: (Recommended: Pi 4 or Pi 3B+ for better performance with multiple channels).
2. **USB Audio Interface**: Any ALSA-compatible interface (e.g., Behringer UMC1820, Scarlett 18i20, or simple multi-channel adapters).
3. **Touchscreen**: 3.5" display with 480x320 resolution (connected via GPIO or HDMI).
4. **External Storage**: USB flash drive or SSD for saving recordings (recommended).
5. **Power Supply**: A stable power supply of at least 3A (especially if powering audio interfaces via USB).

## 📥 Installation
Ensure you have `ffmpeg`, `alsa-utils`, and the necessary Python libraries installed on your Raspberry Pi:

```bash
sudo apt update
sudo apt install ffmpeg alsa-utils python3-tk python3-numpy python3-evdev
```

Clone the repository and start the interface:
```bash
git clone https://github.com/your-username/recberry.git
cd recberry
python3 gui.py
```

*Note: For LED control and disk mounting, the user requires `sudo` privileges (configuring the sudoers file for specific commands is recommended).*

## 📂 Project Structure
- `recorder.py`: The core of the system. Manages `ffmpeg` processes, ALSA monitoring, and storage logic.
- `gui.py`: The touch-friendly graphical interface.
- `bg.png`/`logo.png`: Graphical assets for the interface.
- `recorder.log`: Log file (automatically generated in `~/recorder/recorder.log`).

## ⚙️ Technical Details
The system utilizes **FFmpeg** for the audio capture process, mapping each hardware channel to a `.flac` file. Audio device detection is performed via dynamic scanning of `arecord -l`, while USB disk management monitors mount points in real-time to ensure data persistence.

---
Developed with ❤️ for Raspberry Pi.
