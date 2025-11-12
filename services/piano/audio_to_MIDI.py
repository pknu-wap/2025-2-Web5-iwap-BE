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
        DEFAULT_MP3_PATH,
        DEFAULT_MIDI_PATH,
        FINAL_MP3_PATH,
        SOUNDFONT_PATH,
        N_FFT,
        HOP_LENGTH,
        VELOCITY,
        THRESHOLD_RATIO,
        NOTE_DURATION
    )
except ImportError:
    print("Warning: constants.py not found. Using fallback values.")
    BASE_DIR = Path(__file__).parents[2]
    DEFAULT_MP3_PATH = BASE_DIR / "public" / "input.mp3"
    DEFAULT_MIDI_PATH = BASE_DIR / "public" / "output.mid"
    FINAL_MP3_PATH = BASE_DIR / "public" / "output_piano.mp3"
    SOUNDFONT_PATH = BASE_DIR / "public" / "soundfont.sf2"
    N_FFT, HOP_LENGTH, VELOCITY, THRESHOLD_RATIO, NOTE_DURATION = 2048, 512, 100, 0.1, 0.1

def freq_to_midi(frequency: float) -> int:
    if frequency <= 0:
        return -1
    return int(np.round(69 + 12 * np.log2(frequency / 440.0)))

def talking_piano() -> (pretty_midi.PrettyMIDI, int):
    if not DEFAULT_MP3_PATH.exists():
        print(f"오류: MP3 파일을 찾을 수 없습니다. {DEFAULT_MP3_PATH}")
        return None, 0
    
    try:
        audio_samples, sample_rate = librosa.load(str(DEFAULT_MP3_PATH), sr=44100, mono=True)
    except Exception as e:
        print(f"MP3 파일 로드 오류: {e}")
        return None, 0

    spectrogram = np.abs(librosa.stft(audio_samples, n_fft=N_FFT, hop_length=HOP_LENGTH))
    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=N_FFT)
    times = librosa.frames_to_time(np.arange(spectrogram.shape[1]), sr=sample_rate, hop_length=HOP_LENGTH)

    midi_file = pretty_midi.PrettyMIDI()
    piano_instrument = pretty_midi.Instrument(program=0)
    threshold_value = THRESHOLD_RATIO * np.max(spectrogram)
    
    current_note = None
    
    for time_index, time_value in enumerate(times):
        spectrum_slice = spectrogram[:, time_index]
        peak_index = np.argmax(spectrum_slice)
        peak_magnitude = spectrum_slice[peak_index]
        
        note_number = -1
        
        if peak_magnitude > threshold_value:
            frequency_value = frequencies[peak_index]
            note_number = freq_to_midi(frequency_value)
            if not (0 <= note_number <= 127):
                note_number = -1
        
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
    
    DEFAULT_MIDI_PATH.parent.mkdir(parents=True, exist_ok=True)
    midi_file.write(str(DEFAULT_MIDI_PATH))
    print(f"MIDI 생성 완료 (파일 저장): {DEFAULT_MIDI_PATH}")
    
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
    midi_obj, sr = talking_piano()
    
    if midi_obj and sr > 0:
        try:
            mp3_bytes = midi_to_mp3_bytes(midi_obj, SOUNDFONT_PATH, sample_rate=sr)
            
            FINAL_MP3_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(FINAL_MP3_PATH, "wb") as f:
                f.write(mp3_bytes)
                
            print(f"\n성공! 최종 MP3 파일이 저장되었습니다: {FINAL_MP3_PATH}")
            print(f"파일 크기: {len(mp3_bytes) / 1024:.2f} KB")

        except FileNotFoundError:
            print("변환에 실패했습니다. (필수 프로그램 설치 확인)")
        except ValueError as e:
            print(f"변환 중 값 오류 발생: {e}")
        except Exception as e:
            print(f"알 수 없는 오류 발생: {e}")
            
    else:
        print("MP3 -> MIDI 변환에 실패하여 MP3를 생성할 수 없습니다.")