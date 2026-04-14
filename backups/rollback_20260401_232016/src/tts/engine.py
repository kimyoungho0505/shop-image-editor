"""TTS (Text-to-Speech) 엔진 — Windows TTS + OpenAI TTS 지원."""
import io
import threading
from typing import Optional, Callable
from loguru import logger


# ── Windows TTS 음성 매핑 ──
# provider → voice index or partial name match
_WIN_VOICE_MAP = {
    "claude": 0,     # 첫 번째 음성
    "chatgpt": 1,    # 두 번째 음성
    "gemini": 2,     # 세 번째 음성 (없으면 첫 번째로 폴백)
    "mc": 0,         # 사회자
}

# ── OpenAI TTS 음성 매핑 ──
_OPENAI_VOICE_MAP = {
    "claude": "alloy",     # 중성적, 차분한 목소리
    "chatgpt": "nova",     # 여성적, 밝은 목소리
    "gemini": "echo",      # 남성적, 깊은 목소리
    "mc": "shimmer",       # 부드러운 사회자 목소리
}

# OpenAI TTS 모델 옵션
OPENAI_TTS_MODELS = ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"]
OPENAI_TTS_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


class TTSEngine:
    """TTS 엔진 — Windows pyttsx3 또는 OpenAI API 방식."""

    def __init__(self, provider: str = "off",
                 openai_model: str = "tts-1",
                 openai_api_key: str = "",
                 voice_map: dict = None,
                 speed: float = 1.0,
                 on_log: Callable = None):
        """
        Args:
            provider: "off" | "windows" | "openai"
            openai_model: "tts-1" | "tts-1-hd" | "gpt-4o-mini-tts"
            openai_api_key: OpenAI API 키
            voice_map: {evaluator: voice_name} 오버라이드
            speed: 음성 속도 배율 (0.5~2.0)
            on_log: 로그 콜백
        """
        self._provider = provider
        self._openai_model = openai_model
        self._openai_api_key = openai_api_key
        self._voice_map = voice_map or {}
        self._speed = max(0.5, min(2.0, speed))
        self._log = on_log or (lambda msg: logger.info(msg))
        self._lock = threading.Lock()
        self._speaking = False
        self._stop_flag = False

    @property
    def is_enabled(self) -> bool:
        return self._provider in ("windows", "openai")

    def update_config(self, provider: str = None, openai_model: str = None,
                      openai_api_key: str = None, voice_map: dict = None,
                      speed: float = None):
        """설정 업데이트 (런타임 변경 가능)."""
        if provider is not None:
            self._provider = provider
        if openai_model is not None:
            self._openai_model = openai_model
        if openai_api_key is not None:
            self._openai_api_key = openai_api_key
        if voice_map is not None:
            self._voice_map.update(voice_map)
        if speed is not None:
            self._speed = max(0.5, min(2.0, speed))

    def stop(self):
        """현재 재생 중지."""
        self._stop_flag = True

    def speak(self, text: str, evaluator: str = "mc"):
        """텍스트를 음성으로 재생 (비동기, 별도 스레드).

        Args:
            text: 읽을 텍스트
            evaluator: 발언자 ("claude", "chatgpt", "gemini", "mc")
        """
        if not self.is_enabled or not text or not text.strip():
            return

        self._stop_flag = False
        thread = threading.Thread(
            target=self._speak_sync, args=(text.strip(), evaluator),
            daemon=True
        )
        thread.start()

    def speak_sync(self, text: str, evaluator: str = "mc"):
        """텍스트를 음성으로 재생 (동기, 완료될 때까지 블로킹)."""
        if not self.is_enabled or not text or not text.strip():
            return
        self._speak_sync(text.strip(), evaluator)

    def _speak_sync(self, text: str, evaluator: str):
        """내부 동기 재생."""
        with self._lock:
            self._speaking = True
            try:
                if self._provider == "windows":
                    self._speak_windows(text, evaluator)
                elif self._provider == "openai":
                    self._speak_openai(text, evaluator)
            except Exception as e:
                self._log(f"[TTS] 음성 재생 오류: {e}")
                logger.error(f"TTS error: {e}")
            finally:
                self._speaking = False

    # ── Windows TTS (pyttsx3) ──
    # pyttsx3는 Windows COM(SAPI5) 기반으로 스레드 간 엔진 공유 불가.
    # 매 호출마다 현재 스레드에서 새 엔진을 생성·사용·해제한다.

    def _speak_windows(self, text: str, evaluator: str):
        """Windows SAPI5 TTS로 재생 — 호출 스레드에서 엔진 생성."""
        try:
            import pyttsx3
        except ImportError:
            self._log("[TTS] pyttsx3 미설치. pip install pyttsx3")
            return

        engine = None
        try:
            engine = pyttsx3.init()
        except Exception as e:
            self._log(f"[TTS] Windows TTS 초기화 실패: {e}")
            return

        try:
            voices = engine.getProperty('voices')

            # 음성 선택: 사용자 지정 > 기본 매핑 > 첫 번째 음성
            voice_id = None
            custom = self._voice_map.get(evaluator)
            if custom and isinstance(custom, str):
                # 이름으로 검색
                for v in voices:
                    if custom.lower() in v.name.lower():
                        voice_id = v.id
                        break
            if not voice_id:
                idx = _WIN_VOICE_MAP.get(evaluator, 0)
                if idx < len(voices):
                    voice_id = voices[idx].id
                elif voices:
                    voice_id = voices[0].id

            if voice_id:
                engine.setProperty('voice', voice_id)

            # 속도 설정 (기본 200, speed=1.0 → 180)
            rate = int(180 * self._speed)
            engine.setProperty('rate', rate)

            if self._stop_flag:
                return
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            self._log(f"[TTS] Windows TTS 재생 오류: {e}")
            logger.error(f"pyttsx3 error: {e}")
        finally:
            try:
                engine.stop()
            except Exception:
                pass

    # ── OpenAI TTS ──

    def _speak_openai(self, text: str, evaluator: str):
        """OpenAI TTS API로 재생."""
        if not self._openai_api_key:
            self._log("[TTS] OpenAI API 키가 설정되지 않았습니다.")
            return

        # 음성 선택
        voice = self._voice_map.get(evaluator) or _OPENAI_VOICE_MAP.get(evaluator, "alloy")

        try:
            import openai
            client = openai.OpenAI(api_key=self._openai_api_key)

            if self._stop_flag:
                return

            response = client.audio.speech.create(
                model=self._openai_model,
                voice=voice,
                input=text,
                speed=self._speed,
                response_format="mp3",
            )

            # MP3 바이트를 임시 파일로 저장 후 재생
            audio_bytes = response.content

            if self._stop_flag:
                return

            self._play_audio_bytes(audio_bytes)

        except ImportError:
            self._log("[TTS] openai 패키지 미설치. pip install openai")
        except Exception as e:
            self._log(f"[TTS] OpenAI TTS 오류: {e}")
            logger.error(f"OpenAI TTS error: {e}")

    def _play_audio_bytes(self, audio_bytes: bytes):
        """MP3 오디오 바이트를 재생."""
        import tempfile
        import os

        # 방법 1: pygame (설치되어 있으면)
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            buf = io.BytesIO(audio_bytes)
            pygame.mixer.music.load(buf)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if self._stop_flag:
                    pygame.mixer.music.stop()
                    return
                pygame.time.wait(100)
            return
        except ImportError:
            pass

        # 방법 2: 임시 파일 + playsound
        try:
            from playsound import playsound as _playsound
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name
            try:
                _playsound(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            return
        except ImportError:
            pass

        # 방법 3: Windows 기본 — winsound (WAV만 지원) → 임시파일 + os.startfile
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False,
                                              dir=tempfile.gettempdir()) as f:
                f.write(audio_bytes)
                tmp_path = f.name
            os.startfile(tmp_path)
            # os.startfile은 비동기이므로 재생 완료를 기다림
            import time
            # 대략적 오디오 길이 추정: 1초당 ~16KB (MP3 128kbps)
            estimated_seconds = max(2, len(audio_bytes) / 16000)
            wait_time = 0
            while wait_time < estimated_seconds + 2:
                if self._stop_flag:
                    break
                time.sleep(0.5)
                wait_time += 0.5
            # 임시 파일 정리 시도
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        except Exception as e:
            self._log(f"[TTS] 오디오 재생 실패 (pygame/playsound 미설치): {e}")
            self._log("[TTS] pip install pygame 또는 pip install playsound 설치 권장")

    # ── 유틸리티 ──

    @staticmethod
    def get_windows_voices() -> list:
        """Windows에 설치된 음성 목록 반환."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            result = []
            for i, v in enumerate(voices):
                lang = ""
                if hasattr(v, 'languages') and v.languages:
                    lang = str(v.languages[0])
                result.append({
                    "index": i,
                    "id": v.id,
                    "name": v.name,
                    "lang": lang,
                })
            engine.stop()
            return result
        except Exception:
            return []

    @staticmethod
    def test_windows_voice(index: int = 0, text: str = "테스트 음성입니다."):
        """Windows 음성 테스트."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            if index < len(voices):
                engine.setProperty('voice', voices[index].id)
            engine.setProperty('rate', 180)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            logger.error(f"Windows TTS 테스트 실패: {e}")
