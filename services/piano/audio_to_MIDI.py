# ----------------------------------------------------------
# p!ano
# Mac OS에서 GarageBand나 Logic을 이용해서 test 가능
# ----------------------------------------------------------
import os
from pathlib import Path

NUMBA_CACHE_DIR = Path(__file__).resolve().parent / ".numba_cache"
NUMBA_CACHE_DIR.mkdir(exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", str(NUMBA_CACHE_DIR))

import numba  # noqa: E402
numba.config.DISABLE_CACHE = True
import numpy as np
import librosa
import pretty_midi

N_FFT = 2048
HOP_LENGTH = 512
VELOCITY = 100
THRESHOLD_RATIO = 0.1
NOTE_DURATION = 0.5

MP3_PATH = Path(os.getenv("PIANO_MP3_PATH", "public/input.mp3"))
OUTPUT_MIDI_PATH = Path(os.getenv("PIANO_OUTPUT_MIDI_PATH", "public/output.mid"))

def freq_to_midi(FREQUENCY: int) -> int:
    """
        주파수를 MIDI 노트로 변환하는 함수

    Args:
        FREQUENCY (int): frequency value

    Returns:
        int: MIDI
        
    Example:
        -----------------------------
        Frequency → MIDI Note 변환 공식
        -----------------------------
        MIDI = 69 + 12 x log2(f / 440)
        f = 440 Hz → MIDI = 69
        f = 880 Hz → MIDI = 81
        f = 220 Hz → MIDI = 57
        -----------------------------
    """
    return int(np.round(69 + 12 * np.log2(FREQUENCY / 440.0)))


def talking_piano():
    # ----------------------------------------------------------
    # 1. MP3 로드
    # ----------------------------------------------------------
    AUDIO_SAMPLES, SAMPLE_RATE = librosa.load(MP3_PATH, sr=44100, mono=True)

    # ----------------------------------------------------------
    # 2. STFT(Short-time Fourier transform) 계산
    # ----------------------------------------------------------
    SPECTROGRAM = np.abs(librosa.stft(AUDIO_SAMPLES, n_fft=N_FFT, hop_length=HOP_LENGTH))
    FREQUENCIES = librosa.fft_frequencies(sr=SAMPLE_RATE, n_fft=N_FFT)
    TIMES = librosa.frames_to_time(np.arange(SPECTROGRAM.shape[1]), sr=SAMPLE_RATE, hop_length=HOP_LENGTH)

    # ----------------------------------------------------------
    # 3. MIDI 생성 및 frequency 매핑
    # ----------------------------------------------------------
    MIDI_FILE = pretty_midi.PrettyMIDI()
    PIANO_INSTRUMENT = pretty_midi.Instrument(program=0)

    # thrashold는 특정 값 이하면 무시함 너무 많은 건반이 눌리는 것을 방지함
    THRESHOLD_VALUE = THRESHOLD_RATIO * np.max(SPECTROGRAM)

    for TIME_INDEX, TIME_VALUE in enumerate(TIMES):
        for FREQUENCY_INDEX, FREQUENCY_VALUE in enumerate(FREQUENCIES):
            if SPECTROGRAM[FREQUENCY_INDEX, TIME_INDEX] > THRESHOLD_VALUE:
                NOTE_NUMBER = freq_to_midi(FREQUENCY_VALUE)
                # MIDI 범위 0~127 제한
                # MIDI에서는 음 높이(pitch) 가 0부터 127까지만 허용됨
                if 0 <= NOTE_NUMBER <= 127:
                    NOTE_OBJECT = pretty_midi.Note(
                        velocity=VELOCITY,
                        pitch=NOTE_NUMBER,
                        start=TIME_VALUE,
                        end=TIME_VALUE + NOTE_DURATION
                    )
                    PIANO_INSTRUMENT.notes.append(NOTE_OBJECT)

    MIDI_FILE.instruments.append(PIANO_INSTRUMENT)
    MIDI_FILE.write(str(OUTPUT_MIDI_PATH))

    print(f"MIDI 생성 완료: {OUTPUT_MIDI_PATH}")

if __name__ == "__main__":
    talking_piano()
