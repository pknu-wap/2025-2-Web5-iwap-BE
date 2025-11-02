# ----------------------------------------------------------
# p!ano
# Mac OS에서 GarageBand나 Logic을 이용해서 test 가능
# ----------------------------------------------------------
import os
from pathlib import Path

import numpy as np
import librosa
import pretty_midi

from services.piano.constants import (
    DEFAULT_MP3_PATH,
    DEFAULT_MIDI_PATH,
    N_FFT,
    HOP_LENGTH,
    VELOCITY,
    THRESHOLD_RATIO,
    NOTE_DURATION,
    ENV_MP3_PATH,
    ENV_MIDI_PATH
)

_env_mp3_path = os.getenv(ENV_MP3_PATH)
_env_midi_path = os.getenv(ENV_MIDI_PATH)

MP3_PATH = Path(_env_mp3_path) if _env_mp3_path else DEFAULT_MP3_PATH
OUTPUT_MIDI_PATH = Path(_env_midi_path) if _env_midi_path else DEFAULT_MIDI_PATH

def freq_to_midi(frequency: int) -> int:
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
    return int(np.round(69 + 12 * np.log2(frequency / 440.0)))


def talking_piano():
    # ----------------------------------------------------------
    # 1. MP3 로드
    # ----------------------------------------------------------
    audio_samples, sample_rate = librosa.load(MP3_PATH, sr=44100, mono=True)

    # ----------------------------------------------------------
    # 2. STFT(Short-time Fourier transform) 계산
    # ----------------------------------------------------------
    spectrogram = np.abs(librosa.stft(audio_samples, n_fft=N_FFT, hop_length=HOP_LENGTH))
    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=N_FFT)
    times = librosa.frames_to_time(np.arange(spectrogram.shape[1]), sr=sample_rate, hop_length=HOP_LENGTH)

    # ----------------------------------------------------------
    # 3. MIDI 생성 및 frequency 매핑
    # ----------------------------------------------------------
    midi_file = pretty_midi.PrettyMIDI()
    piano_instrument = pretty_midi.Instrument(program=0)

    # thrashold는 특정 값 이하면 무시함 너무 많은 건반이 눌리는 것을 방지함
    threshold_value = THRESHOLD_RATIO * np.max(spectrogram)

    for time_index, time_value in enumerate(times):
        for frequency_index, frequency_value in enumerate(frequencies):
            if spectrogram[frequency_index, time_index] > threshold_value:
                note_number = freq_to_midi(frequency_value)
                # MIDI 범위 0~127 제한
                # MIDI에서는 음 높이(pitch) 가 0부터 127까지만 허용됨
                if 0 <= note_number <= 127:
                    note_object = pretty_midi.Note(
                        velocity=VELOCITY,
                        pitch=note_number,
                        start=time_value,
                        end=time_value + NOTE_DURATION
                    )
                    piano_instrument.notes.append(note_object)

    midi_file.instruments.append(piano_instrument)
    midi_file.write(str(OUTPUT_MIDI_PATH))

    print(f"MIDI 생성 완료: {OUTPUT_MIDI_PATH}")

if __name__ == "__main__":
    talking_piano()
