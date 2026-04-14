from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal, QMutex

from gui_pyside.utils import CONFIG_DIR


class ProcessWorker(QThread):
    """단일/다중 파일 처리 및 배치 처리 워커."""

    log = Signal(str, str)                    # message, tag
    progress = Signal(float)                  # 0.0 ~ 1.0
    stage_image = Signal(str, str, bytes)     # filename, stage_name, image_bytes
    file_started = Signal(str)                # filename
    file_completed = Signal(str, dict)        # filename, result
    finished = Signal(int, int)               # success_count, fail_count
    error = Signal(str)                       # error message

    def __init__(
        self,
        mode: str = "single",
        files: list[str] | None = None,
        input_dir: str = "",
        output_dir: str = "",
        category: str = "",
        skip_analysis: bool = False,
        skip_photoroom: bool = False,
        pre_cropped: bool = False,
        num_workers: int = 1,
        auto_refine: bool = False,
        max_iterations: int = 3,
        parent=None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.files = files or []
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.category = category
        self.skip_analysis = skip_analysis
        self.skip_photoroom = skip_photoroom
        self.pre_cropped = pre_cropped
        self.num_workers = num_workers
        self.auto_refine = auto_refine
        self.max_iterations = max_iterations

        self._cancelled = False
        self._mutex = QMutex()

    def stop(self):
        self._mutex.lock()
        self._cancelled = True
        self._mutex.unlock()

    def is_cancelled(self) -> bool:
        self._mutex.lock()
        val = self._cancelled
        self._mutex.unlock()
        return val

    def _emit_log(self, msg: str, tag: str = "info"):
        self.log.emit(msg, tag)

    def _make_file_log(self, filename: str):
        def _log(msg: str, tag: str = "info"):
            self.log.emit(f"[{filename}] {msg}", tag)
        return _log

    def _make_stage_cb(self, filename: str):
        def _cb(stage: str, data: bytes):
            self.stage_image.emit(filename, stage, data)
        return _cb

    def run(self):
        try:
            if self.mode == "analyze":
                self._run_analyze()
            elif self.mode == "single":
                self._run_single()
            elif self.mode == "batch":
                self._run_batch()
            else:
                self.error.emit(f"Unknown mode: {self.mode}")
        except Exception as e:
            self.error.emit(str(e))

    def _run_analyze(self):
        from src.pipeline import ImageEditPipeline

        pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))

        target = self._resolve_single_target()
        if not target:
            return

        self.progress.emit(0.0)
        instruction = pipeline.analyze_only(
            target, self.category, on_log=self._emit_log,
        )
        self.progress.emit(1.0)
        self.file_completed.emit(Path(target).name, {"instruction": instruction})
        self.finished.emit(1, 0)

    def _run_single(self):
        files = [f for f in self.files if Path(f).is_file()]
        if not files:
            self.error.emit("처리할 이미지 파일이 없습니다.")
            return

        total = len(files)
        success_count = 0
        fail_count = 0

        if total == 1 and self.auto_refine:
            self._run_single_with_refinement(files[0])
            return

        if total == 1 or self.num_workers <= 1:
            for idx, fpath in enumerate(files):
                if self.is_cancelled():
                    self._emit_log("사용자에 의해 중지됨.", "warn")
                    break
                result = self._process_one_file(fpath, idx, total)
                if result and result.get("files"):
                    success_count += 1
                else:
                    fail_count += 1
        else:
            success_count, fail_count = self._run_parallel(files, total)

        self.finished.emit(success_count, fail_count)

    def _run_single_with_refinement(self, filepath: str):
        from src.pipeline import ImageEditPipeline

        pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))
        fname = Path(filepath).name
        self.file_started.emit(fname)

        result = pipeline.process_with_refinement(
            image_path=filepath,
            category=self.category,
            output_dir=self.output_dir,
            max_iterations=self.max_iterations,
            skip_analysis=self.skip_analysis,
            skip_photoroom=self.skip_photoroom,
            pre_cropped=self.pre_cropped,
            on_log=self._make_file_log(fname),
            on_iteration=lambda i, t: self.progress.emit(i / t),
            is_cancelled=self.is_cancelled,
        )

        self.file_completed.emit(fname, result)
        ok = 1 if result.get("final_result", {}).get("files") else 0
        self.finished.emit(ok, 1 - ok)

    def _run_batch(self):
        from src.pipeline import ImageEditPipeline
        from src.utils.image_io import get_image_files

        files = get_image_files(self.input_dir)
        if not files:
            self.error.emit("처리할 이미지가 없습니다.")
            return

        total = len(files)

        if self.num_workers <= 1:
            pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))
            results = pipeline.process_batch(
                input_dir=self.input_dir,
                category=self.category,
                output_dir=self.output_dir,
                skip_analysis=self.skip_analysis,
                skip_photoroom=self.skip_photoroom,
                pre_cropped=self.pre_cropped,
                on_log=self._emit_log,
                on_progress=lambda idx, t: self.progress.emit(idx / t),
                is_cancelled=self.is_cancelled,
            )
            sc = sum(1 for r in results if r.get("success"))
            fc = len(results) - sc
            self.finished.emit(sc, fc)
        else:
            sc, fc = self._run_parallel(files, total)
            self.finished.emit(sc, fc)

    def _run_parallel(self, files: list[str], total: int) -> tuple[int, int]:
        success_count = 0
        fail_count = 0
        completed = 0
        lock = threading.Lock()

        def _process(fpath: str):
            nonlocal success_count, fail_count, completed
            if self.is_cancelled():
                return
            fname = Path(fpath).name
            self.file_started.emit(fname)
            try:
                from src.pipeline import ImageEditPipeline
                thread_pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))

                file_log = self._make_file_log(fname)
                stage_cb = self._make_stage_cb(fname)

                result = thread_pipeline.process_single(
                    image_path=fpath,
                    category=self.category,
                    output_dir=self.output_dir,
                    skip_analysis=self.skip_analysis,
                    skip_photoroom=self.skip_photoroom,
                    pre_cropped=self.pre_cropped,
                    on_log=file_log,
                    on_stage_image=stage_cb,
                )

                with lock:
                    completed += 1
                    if result.get("files"):
                        success_count += 1
                    else:
                        fail_count += 1
                    self.progress.emit(completed / total)

                self.file_completed.emit(fname, result)

            except Exception as e:
                with lock:
                    completed += 1
                    fail_count += 1
                    self.progress.emit(completed / total)
                self._emit_log(f"[{fname}] 오류: {e}", "error")

        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = {executor.submit(_process, f): f for f in files}
            for future in as_completed(futures):
                if self.is_cancelled():
                    self._emit_log("사용자에 의해 중지됨. 진행 중인 작업 완료 대기...", "warn")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    future.result()
                except Exception:
                    pass

        return success_count, fail_count

    def _process_one_file(self, fpath: str, idx: int, total: int) -> dict | None:
        from src.pipeline import ImageEditPipeline

        pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))
        fname = Path(fpath).name
        self.file_started.emit(fname)

        try:
            file_log = self._make_file_log(fname)
            stage_cb = self._make_stage_cb(fname)

            result = pipeline.process_single(
                image_path=fpath,
                category=self.category,
                output_dir=self.output_dir,
                skip_analysis=self.skip_analysis,
                skip_photoroom=self.skip_photoroom,
                pre_cropped=self.pre_cropped,
                on_log=file_log,
                on_stage_image=stage_cb,
            )

            self.progress.emit((idx + 1) / total)
            self.file_completed.emit(fname, result)
            return result

        except Exception as e:
            self.progress.emit((idx + 1) / total)
            self._emit_log(f"[{fname}] 오류: {e}", "error")
            self.file_completed.emit(fname, {"error": str(e)})
            return None

    def _resolve_single_target(self) -> str | None:
        if self.files:
            p = Path(self.files[0])
        elif self.input_dir:
            p = Path(self.input_dir)
        else:
            self.error.emit("입력 경로가 지정되지 않았습니다.")
            return None

        if p.is_dir():
            from src.utils.image_io import get_image_files
            found = get_image_files(str(p))
            if not found:
                self.error.emit("이미지를 찾을 수 없습니다.")
                return None
            return found[0]
        return str(p)


class RefinementWorker(QThread):
    """process_with_refinement 전용 워커.

    get_user_input은 QThread에서 직접 받을 수 없으므로
    user_input_requested Signal로 메인스레드에 요청하고,
    provide_user_input()으로 응답을 받는 패턴을 사용한다.
    """

    log = Signal(str, str)                   # message, tag
    deliberation = Signal(dict)              # deliberation data
    iteration_progress = Signal(int, int)    # current, total
    finished = Signal(dict)                  # full result
    error = Signal(str)
    user_input_requested = Signal()          # 사용자 입력 요청

    def __init__(
        self,
        image_path: str,
        category: str = "",
        output_dir: str = "",
        max_iterations: int = 3,
        skip_analysis: bool = False,
        skip_photoroom: bool = False,
        pre_cropped: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.image_path = image_path
        self.category = category
        self.output_dir = output_dir
        self.max_iterations = max_iterations
        self.skip_analysis = skip_analysis
        self.skip_photoroom = skip_photoroom
        self.pre_cropped = pre_cropped

        self._cancelled = False
        self._mutex = QMutex()
        self._user_input: list[str] = []
        self._input_event = threading.Event()

    def stop(self):
        self._mutex.lock()
        self._cancelled = True
        self._mutex.unlock()
        self._input_event.set()

    def is_cancelled(self) -> bool:
        self._mutex.lock()
        val = self._cancelled
        self._mutex.unlock()
        return val

    def provide_user_input(self, messages: list[str]):
        self._mutex.lock()
        self._user_input = list(messages)
        self._mutex.unlock()
        self._input_event.set()

    def _get_user_input(self) -> list[str]:
        self.user_input_requested.emit()
        self._input_event.wait()
        self._input_event.clear()
        if self.is_cancelled():
            return []
        self._mutex.lock()
        msgs = list(self._user_input)
        self._user_input.clear()
        self._mutex.unlock()
        return msgs

    def run(self):
        try:
            from src.pipeline import ImageEditPipeline

            pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))

            result = pipeline.process_with_refinement(
                image_path=self.image_path,
                category=self.category,
                output_dir=self.output_dir,
                max_iterations=self.max_iterations,
                skip_analysis=self.skip_analysis,
                skip_photoroom=self.skip_photoroom,
                pre_cropped=self.pre_cropped,
                on_log=lambda msg, tag="info": self.log.emit(msg, tag),
                on_iteration=lambda i, t: self.iteration_progress.emit(i, t),
                on_deliberation=lambda data: self.deliberation.emit(data),
                is_cancelled=self.is_cancelled,
                get_user_input=self._get_user_input,
            )

            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ShadowPreviewWorker(QThread):
    """preview_shadow_only 호출 워커 (뷰파인더에서 사용)."""

    finished = Signal(bytes)
    error = Signal(str)

    def __init__(
        self,
        pre_shadow_bytes: bytes,
        original_bytes: bytes,
        nukki_png_bytes: bytes | None,
        temp_hint: str,
        image_type: str = "full",
        category: str = "",
        shooting_angle: str = "front",
        has_mannequin: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.pre_shadow_bytes = pre_shadow_bytes
        self.original_bytes = original_bytes
        self.nukki_png_bytes = nukki_png_bytes
        self.temp_hint = temp_hint
        self.image_type = image_type
        self.category = category
        self.shooting_angle = shooting_angle
        self.has_mannequin = has_mannequin

        self._cancelled = False

    def stop(self):
        self._cancelled = True

    def run(self):
        try:
            from src.pipeline import ImageEditPipeline

            pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))

            result = pipeline.preview_shadow_only(
                pre_shadow_bytes=self.pre_shadow_bytes,
                original_bytes=self.original_bytes,
                nukki_png_bytes=self.nukki_png_bytes,
                temp_hint=self.temp_hint,
                image_type=self.image_type,
                category=self.category,
                shooting_angle=self.shooting_angle,
                has_mannequin=self.has_mannequin,
            )

            if result:
                self.finished.emit(result)
            else:
                self.error.emit("그림자 미리보기 생성 실패")
        except Exception as e:
            self.error.emit(str(e))


class AutoFixWorker(QThread):
    """preview_prompt_fix + apply_prompt_and_regenerate 워커."""

    prompt_ready = Signal(dict)              # preview_prompt_fix 결과
    regenerated = Signal(bytes, dict)        # result_bytes, new_eval
    error = Signal(str)

    def __init__(
        self,
        mode: str = "preview",
        evaluation: dict | None = None,
        user_feedback: str = "",
        image_type: str = "full",
        category: str = "",
        shooting_angle: str = "front",
        pre_shadow_bytes: bytes | None = None,
        original_bytes: bytes | None = None,
        nukki_png_bytes: bytes | None = None,
        suggested_hint: str = "",
        hint_key: str = "",
        has_mannequin: bool = False,
        needs_shadow: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.evaluation = evaluation or {}
        self.user_feedback = user_feedback
        self.image_type = image_type
        self.category = category
        self.shooting_angle = shooting_angle
        self.pre_shadow_bytes = pre_shadow_bytes
        self.original_bytes = original_bytes
        self.nukki_png_bytes = nukki_png_bytes
        self.suggested_hint = suggested_hint
        self.hint_key = hint_key
        self.has_mannequin = has_mannequin
        self.needs_shadow = needs_shadow

        self._cancelled = False

    def stop(self):
        self._cancelled = True

    def run(self):
        try:
            from src.pipeline import ImageEditPipeline

            pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))

            if self.mode == "preview":
                self._run_preview(pipeline)
            elif self.mode == "regenerate":
                self._run_regenerate(pipeline)
            else:
                self.error.emit(f"Unknown AutoFix mode: {self.mode}")
        except Exception as e:
            self.error.emit(str(e))

    def _run_preview(self, pipeline: Any):
        result = pipeline.preview_prompt_fix(
            evaluation=self.evaluation,
            user_feedback=self.user_feedback,
            image_type=self.image_type,
            category=self.category,
            shooting_angle=self.shooting_angle,
        )
        self.prompt_ready.emit(result)

    def _run_regenerate(self, pipeline: Any):
        result = pipeline.apply_prompt_and_regenerate(
            pre_shadow_bytes=self.pre_shadow_bytes,
            original_bytes=self.original_bytes,
            nukki_png_bytes=self.nukki_png_bytes,
            suggested_hint=self.suggested_hint,
            hint_key=self.hint_key,
            evaluation=self.evaluation,
            image_type=self.image_type,
            category=self.category,
            shooting_angle=self.shooting_angle,
            has_mannequin=self.has_mannequin,
            needs_shadow=self.needs_shadow,
        )

        if result.get("success") and result.get("result_bytes"):
            self.regenerated.emit(result["result_bytes"], result.get("new_eval", {}))
        else:
            self.error.emit("재생성 실패")


class ValidationFixWorker(QThread):
    """검증 프롬프트 수정 요청 워커."""

    suggestion_ready = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        evaluation: dict | None = None,
        user_feedback: str = "",
        image_type: str = "full",
        category: str = "",
        shooting_angle: str = "front",
        parent=None,
    ):
        super().__init__(parent)
        self.evaluation = evaluation or {}
        self.user_feedback = user_feedback
        self.image_type = image_type
        self.category = category
        self.shooting_angle = shooting_angle

        self._cancelled = False

    def stop(self):
        self._cancelled = True

    def run(self):
        try:
            from src.pipeline import ImageEditPipeline

            pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))

            result = pipeline.preview_prompt_fix(
                evaluation=self.evaluation,
                user_feedback=self.user_feedback,
                image_type=self.image_type,
                category=self.category,
                shooting_angle=self.shooting_angle,
            )

            self.suggestion_ready.emit(result)
        except Exception as e:
            self.error.emit(str(e))
