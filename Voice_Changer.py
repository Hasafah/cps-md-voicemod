# pyside6-rcc CPS_resources_from_qt.qrc -o CPS_resources_from_qt.py

# \\Budowanie .exe \\ pyinstaller --name CPSMDVoiceMOD --windowed --noconfirm --onedir Voice_Changer.py 
#                     pyinstaller CPSMDVoiceMod.spec

import pyaudio
import numpy as np
import scipy.signal
import sys
import os 
import wave 
from scipy.signal import lfilter, butter, fftconvolve
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PySide6.QtUiTools import QUiLoader
from app_stylesheet import apply_black_n_green_palette, load_stylesheet
#QRC 
from PySide6.QtGui import QIcon, QGuiApplication
from PySide6.QtCore import QSize, Slot, Signal, QThread, QObject, Qt, QMetaObject, QTimer, QMutex, QMutexLocker
import CPS_resources_from_qt
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
import matplotlib as mpl

try:
    from pydub import AudioSegment
    _HAVE_PYDUB = True
except Exception:
    _HAVE_PYDUB = False

# Matplotlib (QtAgg)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout

def app_resource_path(relative_path):  # Pobiera ścieżkę do zasobu
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class MainWindow(QMainWindow): 
    # Sygnał do zmiany efektu w wątku audio
    change_effect_signal = Signal(str)
    
    mute_changed_signal = Signal(bool) # <--- sygnał do mutowania mikrofonu 
    
    def __init__(self, parent = None): 
        super().__init__(parent)
  
        #Visuals 
        self.setWindowIcon(QIcon(app_resource_path("bandpass_kolko.png")))
        self.setWindowTitle("CPS MD Voice MOD")
        
        
        loader = QUiLoader()
        uiapp_path = app_resource_path("main_app_window_cps.ui")
        self.window = loader.load(uiapp_path, self)


        self.active_button = None
        self.active_style = "background-color: #4CAF50; color: white;"
        
        self.effect_map = {
            "robot_pushButton": "robot", "echo_pushButton": "echo",
            "lp_PushButton": "low_pitch", "hp_effect_PushButton": "high_pitch",
            "radio_PushButton": "radio", "chorus_effect_PushButton": "chorus",
            "flanger_pushButton": "flanger", "ts_pushButton": "time_stretch",
            "reverb_PushButton": "reverb", "bp_pushButton": "bandpass",
            "lekcja_matematyki_PushButton": "lekcja_matematyki",
            "ring_mod_pushButton": "ring_modulation", "stutter_PushButton": "stutter",
        }
        
        for btn_name in self.effect_map.keys(): 
            btn = getattr(self.window, btn_name, None)
            if btn: 
                btn.clicked.connect(self.toggle_effect)
        self.setup_audio_thread()
    
        
        # Show 
        self.window.tabMain.setCurrentIndex(0)
        self.adjustSize() 
        self.setFixedSize(self.size())
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setCentralWidget(self.window)
        # self.showMaximized()
        self.show()
        

    def setup_audio_thread(self): # Tworzy i uruchamia wątek do przetwarzania audio
        self.audio_thread = QThread()
        self.audio_worker = AudioWorker()
        
        self.audio_worker.moveToThread(self.audio_thread)
        
        self.audio_thread.started.connect(self.audio_worker.run)
        self.audio_worker.finished.connect(self.audio_thread.quit)
        self.audio_worker.finished.connect(self.audio_worker.deleteLater)
        self.audio_thread.finished.connect(self.audio_thread.deleteLater)
        
        self.change_effect_signal.connect(self.audio_worker.set_effect)
        
        self.audio_worker.chunk_ready.connect(self._on_chunk_for_viz, Qt.QueuedConnection) # SPEKTROGRAM / WAVEFORM 

        self.audio_thread.start()
        print("Wątek audio uruchomiony.")
        
        ######################################################################################
        # Record toggle
        rec_btn = getattr(self.window, "record_pushButton", None)
        if rec_btn:
            rec_btn.setCheckable(True)
            rec_btn.toggled.connect(self._toggle_record)

        # sygnał z gotowym nagraniem (z workera)
        self.audio_worker.recording_ready.connect(self._on_recording_ready)
        ######################################################################################
        
        
        #\\ Logika mutowania mikrofonu : 
        self._mic_btn = getattr(self.window, "Microphone_toolButton", None)
        if self._mic_btn:
            self._mic_btn.setCheckable(True)
            self._mic_btn.setChecked(False) # Na starcie mikro włączony 
            self._mic_btn.setIcon(QIcon(app_resource_path("MIC_ACTIVATED.svg")))
            self._mic_btn.setToolTip("Kliknij, aby wyciszyć mikrofon")
            self._mic_btn.toggled.connect(self._on_mic_toggled)
        self.mute_changed_signal.connect(self.audio_worker.set_muted, Qt.QueuedConnection)
        #\\ 
        
        # waveform + spectrogram 
        mpl.rcParams.update({"text.color": "white", "axes.labelcolor": "white", "xtick.color": "white","ytick.color": "white" })
 
        ph = getattr(self.window, "signal_visualizer_widget", None)

        # Parametry
        self._sr = 44100
        self._nfft = 1024
        self._freq_bins = self._nfft // 2 + 1
        self._spec_cols = 240              # ok. 8 s przy ~30 FPS
        self._wf_len = int(self._sr * 0.25)  # 250 ms
        self._wf_decim = 2                 # rysowanie co 2 próbkę (dla płynności)

        # Canvas
        self.fig = Figure(figsize=(5, 4), layout="constrained")
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setStyleSheet("background: transparent;")  # tło widgetu
        self.canvas.setAutoFillBackground(False)
        self.canvas.figure.set_facecolor("none")
        self.canvas.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = ph.layout() or QVBoxLayout(ph)
        lay.setContentsMargins(0, 0, 0, 0)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setStyleSheet("""
        QToolBar { background: transparent; border: 0; }
        QToolButton { color: white; }
        QToolButton:checked { background: rgba(255,255,255,0.18); }
        """)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas)
        
        
        interval_ms = int(1000 * self.audio_worker.voice_changer.chunk_size / self._sr)  # około 46 ms przy 2048/44100
        
        frame_dt   = interval_ms / 1000.0
        hist_secs  = self._spec_cols * frame_dt  # ile sekund widać wstecz\
            
        # --- Waveform ---
        self.ax_wf = self.fig.add_subplot(2, 1, 1)
        self.ax_wf.set_title("Waveform")
        self.ax_wf.set_ylabel("Amplitude")
        self.ax_wf.set_xlabel("Time (Age) [s]")
        self.ax_wf.set_ylim(-1.0, 1.0)
        self.ax_wf.grid(alpha=0.2)
        self.ax_wf.set_facecolor("none")

        self._wave_buf = np.zeros(self._wf_len, dtype=np.float32)

        M = (self._wf_len + self._wf_decim - 1) // self._wf_decim # liczba rysowanych punktów po decymacji (ceil)
        # stała oś czasu: od -okno do 0, ostatni punkt = 0 s
        self._x_wf = (np.arange(M, dtype=np.float32) - (M - 1)) * (self._wf_decim / self._sr)

        (self._wf_line,) = self.ax_wf.plot(self._x_wf, self._wave_buf[::self._wf_decim], lw=1)
        self.ax_wf.set_xlim(self._x_wf[0], self._x_wf[-1])

        # --- Spectrogram ---
        self.ax_sp = self.fig.add_subplot(2, 1, 2)
        self.ax_sp.set_title(f"Spectrogram (dBFS)")
        self._spec_img = -100.0 * np.ones((self._freq_bins, self._spec_cols), dtype=np.float32)  # cisza
        extent = [0, self._spec_cols, 0, self   ._sr / 2.0]
        self._im = self.ax_sp.imshow(
                self._spec_img,
                origin="lower", aspect="auto",
                vmin=-90, vmax=0, cmap="inferno",
                extent=[-hist_secs, 0.0, 0.0, self._sr/2.0]   # <-- sekundy na osi X
            )

        self.ax_sp.set_ylabel(f"Frequency [Hz]")
        self.ax_sp.set_facecolor("none")
        self.ax_sp.set_xlabel(f"Time (Age) [s]")
        self.ax_sp.set_ylim(0, self._sr / 2.0)
        self.ax_sp.set_xlim(-hist_secs, 0.0)

        # Precompute do FFT
        self._win = np.hanning(self._nfft).astype(np.float32)

        # Blitting bo potrzebujemy tła (backgrounds)
        self.canvas.draw()  # pierwszy pełny render
        self._bg_wf = self.canvas.copy_from_bbox(self.ax_wf.bbox)
        self._bg_sp = self.canvas.copy_from_bbox(self.ax_sp.bbox)

        # Odświeżanie GUI(blit, bez pełnego redraw)
        self._viz_timer = QTimer(self)
        
        self._viz_timer.setInterval(interval_ms)
        self._viz_timer.timeout.connect(self._update_visuals_fast)
        self._viz_timer.start()

        # Re-cache background po resize (inaczej blit artefakty)
        def _on_resize(event):
            self.canvas.draw()
            self._bg_wf = self.canvas.copy_from_bbox(self.ax_wf.bbox)
            self._bg_sp = self.canvas.copy_from_bbox(self.ax_sp.bbox)
        self.cid_resize = self.canvas.mpl_connect("resize_event", _on_resize)

        self.statusBar()

        ## SPEKTROGRAM / WAVEFORM \\ KONIEC 


    @Slot()
    def toggle_effect(self): # Włącza/wyłącza efekt po kliknięciu przycisku
        sender = self.sender()
        effect_name = self.effect_map.get(sender.objectName())

        if not effect_name:
            return

        if sender == self.active_button:
            self.change_effect_signal.emit("none")
            self.active_button.setStyleSheet("")
            self.active_button = None
            print("Wszystkie efekty wyłączone.")
        else:
            if self.active_button:
                self.active_button.setStyleSheet("")
            
            self.change_effect_signal.emit(effect_name)
            sender.setStyleSheet(self.active_style)
            self.active_button = sender

    
    def closeEvent(self, event): # Obsługuje zdarzenie zamknięcia okna, zapewniając czyste zatrzymanie wątku.
        print("Zamykanie aplikacji...")
        if self.audio_thread.isRunning():
            # Sygnalizujemy workerowi, aby się zatrzymał
            # Używamy QMetaObject.invokeMethod, aby bezpiecznie wywołać slot w innym wątku
            QMetaObject.invokeMethod(self.audio_worker, "stop", Qt.QueuedConnection)
            self.audio_thread.quit()
            if not self.audio_thread.wait(2000): # Czekaj max 2 sekundy
                print("Wątek audio nie zakończył się poprawnie.")
        event.accept()
    

    def _toggle_record(self, on: bool):
        if on:
            QMetaObject.invokeMethod(self.audio_worker, "start_recording", Qt.QueuedConnection)
            self.window.record_pushButton.setText("Stop")
            self.statusBar().showMessage("Recording...")
        else:
            QMetaObject.invokeMethod(self.audio_worker, "stop_recording", Qt.QueuedConnection)
            self.window.record_pushButton.setText("Record")
            self.statusBar().clearMessage()
                
    @Slot(bool)
    def _on_mic_toggled(self, muted: bool): 
        btn = self._mic_btn
        if muted: 
            btn.setIcon(QIcon(app_resource_path("MIC_MUTED.svg")))
            btn.setToolTip("Click to turn on the microphone")
            self.statusBar().showMessage("Microphone muted", 1500)
        else: 
            btn.setIcon(QIcon(app_resource_path("MIC_ACTIVATED.svg")))
            btn.setToolTip("Click to mute the microphone")
            self.statusBar().showMessage("Microphone on", 1500)
        self.mute_changed_signal.emit(muted)
            
    @Slot()
    def _on_recording_ready(self, pcm_bytes: bytes):
        if not pcm_bytes:
            QMessageBox.information(self, "Recording", "No data to save (empty recording).")
            return 
        
        fname,  ffilter = QFileDialog.getSaveFileName(self, "Save recording","recording.wav","WAV (*.wav)")
        if not fname:
            self.statusBar().showMessage("Save cancelled.")
            return
        try: 
            if fname.lower().endswith(".wav") or "WAV" in ffilter:
                self._save_wav(fname, pcm_bytes)
                self.statusBar().showMessage(f"WAV saved: {fname}")
                return 
        except Exception as e: 
            QMessageBox.critical(self, "Save error", f"Failed to save file:\n{e}")
    
    def _save_wav(self, fname: str, pcm_bytes: bytes):
        with wave.open(fname, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.audio_worker.voice_changer.rate)
            wf.writeframes(pcm_bytes)

    ## SLOTY DO WAVEFORM / SPEKTROGRAM \\ POCZĄTEK:
    def _on_chunk_for_viz(self, x_float32: np.ndarray):
        # zaktualizuj ring-buffer waveform
        y = x_float32
        k = min(len(y), self._wf_len)
        if k > 0:
            # przesuwamy oknem: wstawiamy na koniec
            self._wave_buf[:-k] = self._wave_buf[k:]
            self._wave_buf[-k:] = y[-k:]

    def _update_visuals_fast(self):
        if not hasattr(self, "_wave_buf"):
            return

        # === Waveform (blit) ===
        # odtwórz tło osi
        self.canvas.restore_region(self._bg_wf)
        # zaktualizuj dane (z decymacją do rysowania)
        self._wf_line.set_ydata(self._wave_buf[::self._wf_decim])
        # narysuj samą linię i zblituj bbox osi
        self.ax_wf.draw_artist(self._wf_line)
        self.canvas.blit(self.ax_wf.bbox)

        # === Spectrogram (1 kolumna STFT -> scroll) ===
        # policz kolumnę z ostatniego kawałka do NFFT (bardzo tanie)
        x = self._wave_buf[-self._nfft:]
        if len(x) < self._nfft:
            x = np.pad(x, (0, self._nfft - len(x)))
        spec = np.fft.rfft(x[:self._nfft] * self._win)
        mag = np.abs(spec, dtype=np.float32)
        np.maximum(mag, 1e-9, out=mag)
        db = 20.0 * np.log10(mag, dtype=np.float32)
        np.clip(db, -90.0, 0.0, out=db)

        # scroll bez kopii: kolumny lewo, ostatnia = nowa
        self._spec_img[:, :-1] = self._spec_img[:, 1:]
        self._spec_img[:, -1] = db

        # odtwórz tło osi spektrogramu
        self.canvas.restore_region(self._bg_sp)
        # zaktualizuj piksele obrazka (ten sam ndarray!)
        self._im.set_data(self._spec_img)
        # narysuj tylko image i zblituj bbox osi
        self.ax_sp.draw_artist(self._im)
        self.canvas.blit(self.ax_sp.bbox)

        # spłucz zdarzenia GUI (bez pełnego redraw)
        self.canvas.flush_events()
    ## SLOTY DO WAVEFORM / SPEKTROGRAM \\ KONIEC
    
class AudioWorker(QObject): # Worker, który obsługuje strumień audio w osobnym wątku, używając mechanizmu callback, aby nie blokować głównego wątku i pętli zdarzeń GUI.

    finished = Signal()
    recording_ready = Signal(object)
    chunk_ready = Signal(object) # Spektrogram / waveform
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.voice_changer = VoiceChanger()
        self.p = None
        self.stream = None
        
        self._is_recording = False
        self._recorded_frames = []
        
        self._is_muted = False # Flaga do mutowania mikrofonu - bazowo jest odmutowany od początku włączenia aplikacji 
        
        self._viz_every = 2 # Spektrogram / waveform
        self._viz_i = 0 # Spektrogram / waveform

    def _audio_callback(self, in_data, frame_count, time_info, status):
        if self._is_muted:
            # cisza o tej samej długości (2 bajty na próbkę int16)
            silent = np.zeros(len(in_data) // 2, dtype=np.int16)
            processed_bytes = silent.tobytes()
            # nie dopisujemy do nagrania kiedy wyciszone
        else:
            processed_bytes = self.voice_changer.process_audio(in_data)
            if self._is_recording:
                self._recorded_frames.append(processed_bytes)

        # wizualizacja co n-te wywołanie (tak jak było)
        self._viz_i += 1
        if self._viz_i >= self._viz_every:
            self._viz_i = 0
            x = np.frombuffer(processed_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            try:
                self.chunk_ready.emit(x)
            except Exception:
                pass

        return (processed_bytes, pyaudio.paContinue)
    

    @Slot()
    def start_recording(self):
        self._recorded_frames.clear()
        self._is_recording = True
        print("Recording: START")

    @Slot()
    def stop_recording(self):
        self._is_recording = False
        print("Recording: STOP")
        if not self._recorded_frames:
            self.recording_ready.emit(b"")
            return
        pcm = b"".join(self._recorded_frames)
        self._recorded_frames.clear()
        self.recording_ready.emit(pcm)


    @Slot() # Ten slot inicjalizuje PyAudio i otwiera strumień w trybie callback.
    def run(self):  # Metoda kończy działanie, a wątek Qt pozostaje aktywny, aby przetwarzać sygnały.
        try:
            self.p = pyaudio.PyAudio()
            self.stream = self.p.open(format=pyaudio.paInt16,
                                      channels=1,
                                      rate=self.voice_changer.rate,
                                      input=True,
                                      output=True,
                                      frames_per_buffer=self.voice_changer.chunk_size,
                                      stream_callback=self._audio_callback)
            self.stream.start_stream()
            print("Strumień audio (callback) został uruchomiony.")
            
        except Exception as e:
            print(f"Błąd podczas uruchamiania strumienia audio: {e}")
            

    @Slot()
    def stop(self): # Zatrzymuje i zamyka strumień audio
        if self.stream and self.stream.is_active():
            self.stream.stop_stream()
        if self.stream:
            self.stream.close()
        if self.p:
            self.p.terminate()
        print("Strumień audio został zatrzymany")
        self.finished.emit()



        
    @Slot(str) 
    def set_effect(self, effect_name): # Ten slot ustawia wybrany efekt w instancji VoiceChanger
        self.voice_changer.set_effect(effect_name)
        
    @Slot(bool)
    def set_muted(self, muted: bool):
        self._is_muted = muted

        
class VoiceChanger: # Klasa odpowiedzialna za algorytmy przetwarzania sygnału audio
    def __init__(self, rate=44100, chunk_size=2048, effect='none'):
        self.rate = rate
        self.chunk_size = chunk_size
        self.effect = effect
        
        # Bufory dla efektów
        self.prev_echo = np.zeros(0)
        self.reverb_tail = np.zeros(0)

    def set_effect(self, effect): # Ustawia nowy efekt do zastosowania
        self.effect = effect
        print(f"VoiceChanger ustawił efekt: {self.effect}")

    def process_audio(self, data): # Przetwarza porcję danych audio, stosując wybrany efekt
        audio_array = np.frombuffer(data, dtype=np.int16).astype(np.float32)

        if self.effect == "robot":
            audio_array = self.robot_effect(audio_array)
        elif self.effect == "echo":
            audio_array = self.echo_effect(audio_array, delay_ms=250, decay=0.7)
        elif self.effect == "reverb":
            audio_array = self.reverb_effect_convolution(audio_array)
        elif self.effect == "lekcja_matematyki":
            audio_array = self.lekcja_matematyki(audio_array)
        elif self.effect == "low_pitch":
            audio_array = self.pitch_shift_fft(audio_array, 0.8)
        elif self.effect == "high_pitch":
            audio_array = self.pitch_shift_fft(audio_array, 1.3)
        elif self.effect == "radio":
            audio_array = self.radio_effect(audio_array)
        elif self.effect == "stutter":
            audio_array = self.stutter_effect(audio_array)
        elif self.effect == "ring_modulation":
            audio_array = self.ring_modulation_effect(audio_array)
        elif self.effect == "flanger":
            audio_array = self.flanger(audio_array, rate_hz=0.25, base_ms=0.7, depth_ms=2.5, feedback=0.5, mix=0.5)
        elif self.effect == "chorus":
            audio_array = self.chorus(audio_array, voices=3, rate_hz=0.8, depth_ms=12.0, base_ms=18.0, mix=0.5)
        elif self.effect == "bandpass":
            audio_array = self.bandpass_filter(audio_array, f0=1200.0, q=1.0)
        elif self.effect == "time_stretch":
            audio_array = self.time_stretch_granular(audio_array, stretch=1.25, grain_ms=40.0, overlap=0.5)
        # 'none' nie wymaga żadnej operacji, sygnał przechodzi bez zmian

        processed_data = np.clip(audio_array, -32768, 32767).astype(np.int16).tobytes()
        return processed_data 
    
    def stutter_effect(self, samples): # Efekty 'jąkania' się głosu przez powtarzanie krótkiego fragmentu
        segment = samples[:len(samples)//8]
        return np.tile(segment, len(samples) // len(segment) + 1)[:len(samples)]

    
    def robot_effect(self, samples):
        # Efekt robota poprzez modulację amplitudy falą kwadratową
        t = np.arange(len(samples)) / self.rate
        modulator = np.sign(np.sin(2 * np.pi * 30 * t))  # 30 Hz fala kwadratowa
        return samples * modulator

    
    def echo_effect(self, samples, delay_ms=250, decay=0.7): # delay_ms: Czas opóźnienia w milisekundach , decay: Współczynnik tłumienia echa
        delay_samples = int(self.rate * delay_ms / 1000)
        if len(self.prev_echo) < delay_samples:
            self.prev_echo = np.concatenate((np.zeros(delay_samples), self.prev_echo))
        padded = np.concatenate((self.prev_echo[-delay_samples:], samples))
        echo_signal = samples + decay * padded[:len(samples)]
        self.prev_echo = np.concatenate((self.prev_echo, samples))[-delay_samples:]
        return echo_signal
    
    def radio_effect(self, samples): #Symulacja dźwięku z radia poprzez filtr pasmowoprzepustowy
        # Filtr Butterwortha 4-go rzędu (300-3400 Hz)
        b, a = butter(4, [300 / (self.rate/2), 3400 / (self.rate/2)], btype='band')
        return lfilter(b, a, samples) * 0.8


    # Zmiana tonacji głosu przy użyciu transformaty FFT 
    def pitch_shift_fft(self, samples, pitch_factor): # pitch_factor: Współczynnik zmiany tonacji (0.8 = niższy, 1.3 = wyższy)
        N = len(samples) 
        window = np.hanning(N)
        fft_spectrum = np.fft.fft(samples * window) # Transformata FFT
        # Przesunięcie składowych częstotliwościowych
        indices = np.round(np.arange(0, N) * pitch_factor).astype(int)
        indices = indices[indices < N]
        shifted_spectrum = np.zeros(N, dtype=complex)
        shifted_spectrum[indices] = fft_spectrum[:len(indices)]
        # Odwrotna transformata FFT do dziedziny czasu
        shifted_signal = np.fft.ifft(shifted_spectrum).real
        return shifted_signal
    
    def reverb_effect_convolution(self, samples): # Efekt pogłosu poprzez splot z odpowiedzią impulsową
        ir = np.zeros(8000)
        ir[0] = 1.0
        ir[500] = 0.5
        ir[1500] = 0.35
        ir[3000] = 0.25
        ir[5000] = 0.15
        ir[7000] = 0.08
        reverb = fftconvolve(samples, ir, mode='full')[:len(samples)] # Splot w dziedzinie częstotliwości dla efektywności
        return reverb


    def lekcja_matematyki(self, samples): # efekt symulujący problemy z połączeniem w lekcji online
        chunk_len = len(samples)
        
        # Losowe przerwy (cisza)
        if np.random.rand() < 0.05:
            return np.zeros_like(samples)
        
        # Opóźnienie z losowym czasem
        elif np.random.rand() < 0.10:
            delay_ms = np.random.uniform(50, 200)  # 50-200ms
            delay_samples = int(delay_ms * self.rate / 1000)
            delayed = np.concatenate((np.zeros(delay_samples), samples))[:chunk_len]
            return delayed * np.random.uniform(0.7, 0.9)  # Losowe tłumienie
        
        # Zanikanie dźwięku z losowym profilem
        elif np.random.rand() < 0.15:
            fade_type = np.random.choice(['out', 'in_out'])
            if fade_type == 'out':
                fade = np.linspace(1, np.random.uniform(0.1, 0.4), chunk_len)
            else:  # in_out
                mid_point = chunk_len // 2
                fade = np.concatenate((
                    np.linspace(1, 0.3, mid_point),
                    np.linspace(0.3, 1, chunk_len - mid_point)
                ))
            return samples * fade
        
        # Dodanie szumu tła
        elif np.random.rand() < 0.10:
            noise_level = np.random.uniform(0.05, 0.15)
            noise = noise_level * np.random.randn(chunk_len) * np.max(np.abs(samples))
            return samples + noise
        
        # Losowe "trzaski"
        elif np.random.rand() < 0.08:
            out = samples.copy()
            for _ in range(np.random.randint(1, 4)):
                pos = np.random.randint(0, chunk_len)
                duration = int(self.rate * 0.005)  # 5ms
                out[pos:pos+duration] = np.random.uniform(-0.5, 0.5, min(duration, chunk_len-pos))
            return out
        
        # Ograniczenie pasma częstotliwości (efekt "telefonu")
        elif np.random.rand() < 0.12:
            nyquist = self.rate / 2
            low = np.random.uniform(300, 500) / nyquist
            high = np.random.uniform(3000, 4000) / nyquist
            b, a = butter(2, [low, high], btype='band')
            return lfilter(b, a, samples)
        # Brak efektu
        else:
            return samples
    
    
    def ring_modulation_effect(self, samples, mod_freq=300): #Efekt modulacji pierścieniowej - pomnożenie przez ton nośny
        t = np.arange(len(samples)) / self.rate
        modulator = np.sin(2 * np.pi * mod_freq * t)
        return samples * modulator


    # Efekt flangera z modulacją opóźnienia LFO i sprzężeniem zwrotnym
    def flanger(self, samples, rate_hz=0.25, base_ms=0.7, depth_ms=2.5, feedback=0.5, mix=0.5):
        max_delay = int((base_ms+depth_ms) * 1e-3 * self.rate) + 4
        if not hasattr(self, '_flg_buf'):
            self._flg_buf = np.zeros(max(4096, max_delay*4), dtype=np.float32)
            self._flg_w = 0
        buf = self._flg_buf
        w = self._flg_w
        n = len(samples)
        out = np.empty(n, dtype=np.float32)
        lfo = self._lfo(n, rate_hz, '_flg_phase', 'sine')
        delay = (base_ms + depth_ms * 0.5*(lfo+1.0)) * 1e-3 * self.rate
        for i in range(n):
            di = delay[i]
            ri = int(w - di) % buf.size
            r0 = ri
            r1 = (ri+1) % buf.size
            frac = di - np.floor(di)
            delayed = buf[r0]*(1-frac) + buf[r1]*frac
            y = (1-mix)*samples[i] + mix*delayed
            buf[w] = samples[i] + feedback*delayed
            out[i] = y
            w = (w+1) % buf.size
        self._flg_w = int(w)
        return out

    # Efekt chóru poprzez sumowanie wielu opóźnionych kopii sygnału
    def chorus(self, samples, voices=4, rate_hz=0.2, depth_ms=3.0, base_ms=20.0, mix=0.5):
        if not hasattr(self, '_cho_bufs'):
            self._cho_bufs = []
            self._cho_ws = []
            self._cho_lfo_phases = []
            self._cho_lfo_rates = []
            max_delay = int((base_ms + depth_ms) * 1e-3 * self.rate) + 16
            for i in range(voices):
                self._cho_bufs.append(np.zeros(max(8192, max_delay * 2), dtype=np.float32))
                self._cho_ws.append(0)
                self._cho_lfo_phases.append(np.random.uniform(0, 2 * np.pi)) # Losowa faza startowa
                self._cho_lfo_rates.append(rate_hz * (1.0 + np.random.uniform(-0.15, 0.15))) # Lekka wariacja prędkości

        n = len(samples)
        wet_signal = np.zeros(n, dtype=np.float32)

        for v in range(voices):
            buf = self._cho_bufs[v]
            w = self._cho_ws[v]
            lfo = self._lfo(n, self._cho_lfo_rates[v], f'_cho_lfo_phases_v{v}', 'sine')
            
            # Modulacja opóźnienia
            delay = (base_ms + depth_ms * lfo) * 1e-3 * self.rate
            
            for i in range(n):
                buf[w] = samples[i]
                
                # Odczyt z interpolacją liniową
                read_idx = w - delay[i]
                r0 = int(np.floor(read_idx))
                frac = read_idx - r0
                r1 = r0 + 1
                delayed_sample = buf[r0 % len(buf)] * (1 - frac) + buf[r1 % len(buf)] * frac
                
                wet_signal[i] += delayed_sample
                w = (w + 1) % len(buf)
            
            self._cho_ws[v] = w

        wet_signal /= voices # Normalizacja
        output = (1 - mix) * samples + mix * wet_signal
        return output.astype(np.float32)


    # Filtr pasmowoprzepustowy z regulowaną częstotliwością środkową i dobrocią
    def bandpass_filter(self, samples, f0=1200.0, q=1.0): # f0: Częstotliwość środkowa filtru (domyślnie 1200 Hz), q: Dobroć filtru (określa szerokość pasma)
        bw = f0 / max(q, 1e-3)
        # Obliczenie dolnej i górnej granicy pasma (z ograniczeniami)
        low = max(30.0, f0 - bw/2.0) / (self.rate/2) 
        high = min(self.rate/2 - 100.0, f0 + bw/2.0) / (self.rate/2)
        # Projektowanie filtra Butterwortha 4-go rzędu
        b, a = butter(4, [low, high], btype='band', output='ba')
        return lfilter(b, a, samples).astype(np.float32)



    # Time-Stretch (prosty granular, stała długość ramki) ======
        # Parametry funkcji: 
         # stretch: Współczynnik rozciągnięcia (>1 = wolniej, <1 = szybciej)
         # grain_ms: Długość pojedynczego ziarna dźwięku w milisekundach
         # overlap: Nakładanie się ziaren (0-1)
    def time_stretch_granular(self, samples, stretch=1.25, grain_ms=40.0, overlap=0.5):
        # Produkuje dźwięk "rozciągnięty" w obrębie ramki, ale zwraca N próbek (jak wejście)
        x = samples.astype(np.float32)
        N = len(x)  # Długość oryginalnego sygnału
        grain = int(max(16, grain_ms * 1e-3 * self.rate))
        hop_in = max(8, int (grain * (1.0 - overlap) )) # Obliczenie przesunięcia między ziarnami wejściowymi
        hop_out = max(8, int ( hop_in * stretch ) ) # Obliczenie przesunięcia między ziarnami wyjściowymi
        win = np.hanning(grain).astype(np.float32)
        # zebrać z wejścia z krokiem hop_in, a złożyć z krokiem hop_out
        frames = []
        for start in range(0, N - grain + 1, hop_in):
            frames.append((x[start:start+grain] * win))
        # sklejanie z innym krokiem
        est_len = hop_out * (len(frames)-1) + grain
        y = np.zeros(est_len, dtype=np.float32)
        idx = 0
        for fr in frames:
            end = idx + grain
            if end > len(y):  
                y = np.pad(y, (0, end - len(y)))
            y[idx:end] += fr
            idx += hop_out
        # Dopasowanie długości do N przez resampling (mały krok)
        if len(y) != N:
            y = scipy.signal.resample(y, N).astype(np.float32)
        return y.astype(np.float32)
    
    
    # Generator sygnału LFO (Low Frequency Oscillator) do modulacji efektów
    def _lfo(self, n, rate_hz, phase_attr, shape='sine'):
        # Kształt fali ('sine' - sinus, 'tri' - trójkąt)
        # n: Liczba próbek do wygenerowania
        # Pobranie aktualnej fazy z atrybutu klasy
        phase = getattr(self, phase_attr, 0.0)
        t = np.arange(n, dtype=np.float32) / self.rate
        omega = 2.0 * np.pi * rate_hz
        # Generowanie różnych kształtów fal
        if shape == 'sine':
            lfo = np.sin(omega * t + phase).astype(np.float32)
        elif shape == 'tri':    # Fala trójkątna poprzez transformację arcsin
            lfo = 2/np.pi * np.arcsin(np.sin(omega * t + phase)).astype(np.float32)
        else:
            lfo = np.sin(omega * t + phase).astype(np.float32) # Domyślnie sinusoida
        # update phase
        new_phase = (phase + omega * n / self.rate) % (2*np.pi)
        setattr(self, phase_attr, float(new_phase))
        return lfo # Zwracamy sygnał LFO o długości n 


def app_resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

if __name__ == "__main__":

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app = QApplication(sys.argv)
    apply_black_n_green_palette(app)
    stylesheet = load_stylesheet(app_resource_path("darkngreen_palette.qss"))

    app.setStyleSheet(stylesheet)
    
    win = MainWindow() 
    sys.exit(app.exec())
