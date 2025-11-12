import os
from pathlib import Path
import io

import numpy as np
import librosa
import pretty_midi
import soundfile as sf
from pydub import AudioSegment


try:
    from services.piano.constants import (
        DEFAULT_MP3_DIR,
        DEFAULT_MIDI_DIR,
        DEFAULT_FINAL_MP3_DIR,
        SOUNDFONT_PATH,
        N_FFT,
        HOP_LENGTH,
        VELOCITY,
        THRESHOLD_RATIO,
        NOTE_DURATION,
        MAX_MELODY_FREQ,
        MAX_NOTE_JUMP
    )
except ImportError:
    print("Warning: constants.py not found. Using fallback values.")
    BASE_DIR = Path(__file__).parents[2]
    DEFAULT_MP3_DIR = BASE_DIR / "public" / "mp3"
    DEFAULT_MIDI_DIR = BASE_DIR / "public" / "midi"
    DEFAULT_FINAL_MP3_DIR = BASE_DIR / "public" / "piano_mp3"
    SOUNDFONT_PATH = BASE_DIR / "public" / "soundfont.sf2"
    N_FFT, HOP_LENGTH, VELOCITY, THRESHOLD_RATIO, NOTE_DURATION = 2048, 512, 100, 0.1, 0.1
    MAX_MELODY_FREQ, MAX_NOTE_JUMP = 3000, 24

def freq_to_midi(frequency: float) -> int:
    if frequency <= 0:
        return -1
    return int(np.round(69 + 12 * np.log2(frequency / 440.0)))

def talking_piano(input_mp3_path: Path, midi_output_path: Path) -> (pretty_midi.PrettyMIDI, int):
    if not input_mp3_path.exists():
        print(f"오류: MP3 파일을 찾을 수 없습니다. {input_mp3_path}")
        return None, 0
    
    try:
        audio_samples, sample_rate = librosa.load(str(input_mp3_path), sr=44100, mono=True)
    except Exception as e:
        print(f"MP3 파일 로드 오류: {e}")
        return None, 0

    spectrogram = np.abs(librosa.stft(audio_samples, n_fft=N_FFT, hop_length=HOP_LENGTH))
    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=N_FFT)
    times = librosa.frames_to_time(np.arange(spectrogram.shape[1]), sr=sample_rate, hop_length=HOP_LENGTH)

    max_freq_index = np.searchsorted(frequencies, MAX_MELODY_FREQ)
    if max_freq_index == 0:
        max_freq_index = len(frequencies)

    midi_file = pretty_midi.PrettyMIDI()
    piano_instrument = pretty_midi.Instrument(program=0)
    threshold_value = THRESHOLD_RATIO * np.max(spectrogram)
    
    current_note = None
    last_note_pitch = None
    
    for time_index, time_value in enumerate(times):
        spectrum_slice = spectrogram[:max_freq_index, time_index]
        peak_index = np.argmax(spectrum_slice)
        peak_magnitude = spectrum_slice[peak_index]
        
        note_number = -1
        
        if peak_magnitude > threshold_value:
            frequency_value = frequencies[peak_index]
            note_number = freq_to_midi(frequency_value)
            if not (0 <= note_number <= 127):
                note_number = -1
        
        if note_number != -1:
            if last_note_pitch is not None and abs(note_number - last_note_pitch) > MAX_NOTE_JUMP:
                note_number = -1
            else:
                last_note_pitch = note_number
        else:
            last_note_pitch = None

        if note_number != -1:
            if current_note is None:
                current_note = pretty_midi.Note(
                    velocity=VELOCITY, pitch=note_number, start=time_value, end=time_value + NOTE_DURATION
                )
                piano_instrument.notes.append(current_note)
            elif current_note.pitch == note_number:
                current_note.end = time_value + NOTE_DURATION
            else:
                current_note = pretty_midi.Note(
                    velocity=VELOCITY, pitch=note_number, start=time_value, end=time_value + NOTE_DURATION
                )
                piano_instrument.notes.append(current_note)
        else:
            current_note = None

    midi_file.instruments.append(piano_instrument)
    
    midi_output_path.parent.mkdir(parents=True, exist_ok=True)
    midi_file.write(str(midi_output_path))
    print(f"MIDI 생성 완료 (파일 저장): {midi_output_path}")
    
    return midi_file, sample_rate


def midi_to_mp3_bytes(
    midi_data: pretty_midi.PrettyMIDI, 
    sf2_path: Path, 
    sample_rate: int = 44100
) -> bytes:
    if not sf2_path.exists():
        raise ValueError(f"SoundFont 파일을 찾을 수 없습니다: {sf2_path}")

    try:
        audio_data = midi_data.fluidsynth(fs=sample_rate, sf2_path=str(sf2_path))
    except Exception as e:
        print(f"MIDI 합성(fluidsynth) 오류: {e}")
        raise
        
    if audio_data.size == 0:
        raise ValueError("MIDI 파일에 음표가 없거나 합성에 실패하여 빈 오디오가 생성되었습니다.")

    wav_buffer = io.BytesIO()
    sf.write(wav_buffer, audio_data, sample_rate, format="WAV", subtype='PCM_16')
    wav_buffer.seek(0)

    mp3_buffer = io.BytesIO()
    try:
        AudioSegment.from_file(wav_buffer, format="wav").export(mp3_buffer, format="mp3")
    except FileNotFoundError:
        raise
    except Exception as e:
        print(f"pydub MP3 export 오류: {e}")
        raise

    return mp3_buffer.getvalue()


if __name__ == "__main__":
    DEFAULT_MP3_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_MIDI_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_FINAL_MP3_DIR.mkdir(parents=True, exist_ok=True)

    sample_mp3_path = DEFAULT_MP3_DIR / "input.mp3"
    sample_midi_path = DEFAULT_MIDI_DIR / "output.mid"
    sample_final_mp3_path = DEFAULT_FINAL_MP3_DIR / "output_piano.mp3"

    midi_obj, sr = talking_piano(sample_mp3_path, sample_midi_path)
    
    if midi_obj and sr > 0:
        try:
            mp3_bytes = midi_to_mp3_bytes(midi_obj, SOUNDFONT_PATH, sample_rate=sr)
            
            with open(sample_final_mp3_path, "wb") as f:
                f.write(mp3_bytes)
                
            print(f"\n성공! 최종 MP3 파일이 저장되었습니다: {sample_final_mp3_path}")
            print(f"파일 크기: {len(mp3_bytes) / 1024:.2f} KB")

        except FileNotFoundError:
            print("변환에 실패했습니다. (필수 프로그램 설치 확인)")
        except ValueError as e:
            print(f"변환 중 값 오류 발생: {e}")
        except Exception as e:
            print(f"알 수 없는 오류 발생: {e}")
            
    else:
        print("MP3 -> MIDI 변환에 실패하여 MP3를 생성할 수 없습니다.")