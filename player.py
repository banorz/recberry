#!/usr/bin/env python3

import os
import threading
import time
import numpy as np
import pyaudio
import soundfile as sf

class MultiTrackPlayer:
    def __init__(self, samplerate=48000, chunk_size=1024):
        self.samplerate = samplerate
        self.chunk_size = chunk_size
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.tracks = [] # List of { 'file': sf.SoundFile, 'volume': 1.0, 'pan': 0.0, 'name': str }
        self.master_volume = 1.0
        self.output_device_index = None # Default
        self.output_channels = [0, 1] # Default L/R
        self.is_playing = False
        self.current_frame = 0
        self.total_frames = 0
        self.lock = threading.Lock()

    def get_output_devices(self):
        devices = []
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            if info.get('maxOutputChannels') > 0:
                devices.append({
                    'index': i,
                    'name': info.get('name'),
                    'channels': info.get('maxOutputChannels')
                })
        return devices

    def set_output_routing(self, device_index, channels):
        with self.lock:
            self.output_device_index = device_index
            self.output_channels = channels # e.g. [0, 1]

    def load_folder(self, folder_path):
        """Prepares tracks for streaming from .flac files in the folder."""
        self.stop()
        with self.lock:
            # Close previous files
            for t in self.tracks:
                try:
                    t['file'].close()
                except:
                    pass
            
            self.tracks = []
            if not os.path.exists(folder_path):
                print(f"DEBUG: Folder {folder_path} does not exist.")
                return

            files = sorted([f for f in os.listdir(folder_path) if f.endswith('.flac')])
            print(f"DEBUG: Found files: {files}")
            max_len = 0
            for f in files:
                path = os.path.join(folder_path, f)
                try:
                    # Open file for streaming
                    snd_file = sf.SoundFile(path)
                    
                    self.tracks.append({
                        'file': snd_file,
                        'volume': 0.8,
                        'pan': 0.0,
                        'name': f
                    })
                    max_len = max(max_len, snd_file.frames)
                    print(f"DEBUG: Loaded {f}, frames: {snd_file.frames}")
                except Exception as e:
                    print(f"DEBUG: Error opening {f}: {e}")
            
            self.total_frames = max_len
            self.current_frame = 0
            print(f"DEBUG: Total frames: {self.total_frames}")

    def set_master_volume(self, volume):
        with self.lock:
            self.master_volume = max(0.0, min(2.0, volume))

    def seek(self, seconds):
        with self.lock:
            target_frame = int(seconds * self.samplerate)
            self.current_frame = max(0, min(target_frame, self.total_frames))

    def get_current_time(self):
        return self.current_frame / self.samplerate

    def get_total_time(self):
        return self.total_frames / self.samplerate

    def set_track_volume(self, index, volume):
        if 0 <= index < len(self.tracks):
            with self.lock:
                self.tracks[index]['volume'] = max(0.0, min(1.0, volume))

    def set_track_pan(self, index, pan):
        if 0 <= index < len(self.tracks):
            with self.lock:
                self.tracks[index]['pan'] = max(-1.0, min(1.0, pan))

    def _callback(self, in_data, frame_count, time_info, status):
        try:
            with self.lock:
                if not self.is_playing:
                    return (None, pyaudio.paAbort)

                if self.current_frame >= self.total_frames:
                    print("DEBUG: Reached end of playback.")
                    self.is_playing = False
                    return (None, pyaudio.paComplete)

                # Initialize stereo mix buffer
                mix = np.zeros((frame_count, 2), dtype='float32')

                for track in self.tracks:
                    f = track['file']
                    vol = track['volume']
                    pan = track['pan']
                    
                    if self.current_frame < f.frames:
                        f.seek(self.current_frame)
                        data = f.read(frame_count, dtype='float32')
                        
                        if len(data) > 0:
                            # Convert to mono if stereo
                            if len(data.shape) > 1:
                                mono_data = np.mean(data, axis=1)
                            else:
                                mono_data = data
                                
                            # Padding if read is short
                            if len(mono_data) < frame_count:
                                temp = np.zeros(frame_count, dtype='float32')
                                temp[:len(mono_data)] = mono_data
                                mono_data = temp
                            
                            # Apply Pan & Volume & Master Volume
                            l_vol = vol * self.master_volume * min(1.0, 1.0 - pan)
                            r_vol = vol * self.master_volume * min(1.0, 1.0 + pan)
                            
                            mix[:, 0] += mono_data * l_vol
                            mix[:, 1] += mono_data * r_vol

                self.current_frame += frame_count
                
                # Output Routing: Map stereo mix to selected hardware channels
                # Find max channel index needed
                needed_channels = max(self.output_channels) + 1
                # Use at least 2 channels for the output buffer
                out_channels = max(2, needed_channels)
                
                final_out = np.zeros((frame_count, out_channels), dtype='float32')
                
                l_idx = self.output_channels[0]
                r_idx = self.output_channels[1]
                
                # Use += to allow summing if l_idx and r_idx are the same
                if l_idx < out_channels:
                    final_out[:, l_idx] += mix[:, 0]
                if r_idx < out_channels:
                    final_out[:, r_idx] += mix[:, 1]
                
                final_out = np.clip(final_out, -1.0, 1.0)
                return (final_out.tobytes(), pyaudio.paContinue)
        except Exception as e:
            print(f"DEBUG: Exception in _callback: {e}")
            self.is_playing = False
            return (None, pyaudio.paAbort)

    def play(self):
        if not self.tracks or self.is_playing:
            print(f"DEBUG: Cannot play. tracks: {len(self.tracks)}, is_playing: {self.is_playing}")
            return
        
        # Ensure any old stream is properly closed before opening a new one
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except:
                pass
            self.stream = None

        self.is_playing = True
        try:
            # Determine how many channels to open
            with self.lock:
                idx = self.output_device_index
                needed_channels = max(self.output_channels) + 1
                
                # Get device info to find max channels
                dev_info = self.p.get_device_info_by_index(idx) if idx is not None else self.p.get_default_output_device_info()
                max_dev_channels = dev_info.get('maxOutputChannels')
                
                stream_channels = max(2, min(needed_channels, max_dev_channels))
                
            self.stream = self.p.open(
                format=pyaudio.paFloat32,
                channels=stream_channels,
                rate=self.samplerate,
                output=True,
                output_device_index=idx,
                frames_per_buffer=self.chunk_size,
                stream_callback=self._callback
            )
            self.stream.start_stream()
            print(f"DEBUG: Playback stream started on device {idx} with {stream_channels} channels.")
        except Exception as e:
            print(f"DEBUG: Error opening playback stream: {e}")
            self.is_playing = False
            if self.stream:
                try: self.stream.close()
                except: pass
                self.stream = None

    def pause(self):
        self.is_playing = False
        if self.stream:
            self.stream.stop_stream()

    def stop(self):
        self.is_playing = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        self.current_frame = 0

    def close(self):
        self.stop()
        with self.lock:
            for t in self.tracks:
                try:
                    t['file'].close()
                except:
                    pass
        self.p.terminate()

if __name__ == "__main__":
    # Test stub
    pass
