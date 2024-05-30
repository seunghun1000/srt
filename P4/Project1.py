import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QTextEdit
from PyQt5.uic import loadUi
from PyQt5.QtCore import pyqtSignal, QThread, QTimer
from faster_whisper import WhisperModel
from datetime import timedelta
from googletrans import Translator
import ffmpeg
import deepl

class SrtProcessThread(QThread):
    progress_changed = pyqtSignal(int)  # 진행 상황이 변경될 때 발생하는 시그널
    srt_generated = pyqtSignal(str)  # SRT 파일이 생성될 때 발생하는 시그널

    def __init__(self, audio_file, model, language, model_size):
        super().__init__()
        self.audio_file = audio_file
        self.model = model
        self.language = language
        self.model_size = model_size

    def run(self):
        base_name = os.path.splitext(os.path.basename(self.audio_file))[0]  # 파일 이름에서 확장자를 제거
        srt_file_name = f"{base_name}_{self.model_size}.srt"
        
        # ffmpeg를 사용하여 영상 파일을 WAV 오디오 파일로 변환
        wav_audio_file = f"{base_name}.wav"
        ffmpeg.input(self.audio_file).output(wav_audio_file, ar=16000, ac=1, codec='pcm_s16le').run()
    
        # 오디오 파일 변환
        segments, info = self.model.transcribe(wav_audio_file, beam_size=5)

        segments = list(segments)  # 제너레이터를 리스트로 변환
        total_segments = len(segments)
        
        progress = 0

        i = 0  # 세그먼트 번호
        srt_text = ""
        for segment in segments:
            start_time = self.seconds_to_srt_time(segment.start)
            end_time = self.seconds_to_srt_time(segment.end)
            i += 1  # 세그먼트 번호를 증가
            srt_text += f"{i}\n"
            srt_text += f"{start_time}-->{end_time}\n"
            srt_text += f"{segment.text}\n\n"

            # 프로그레시브 바 업데이트
            progress = (i / total_segments) * 100
            self.progress_changed.emit(int(progress))

        # 변환된 SRT 텍스트를 QTextEdit에 표시
        self.srt_generated.emit(srt_text)

        # SRT 파일을 생성
        with open(srt_file_name, 'w', encoding='utf-8') as srt_file:
            srt_file.write(srt_text)
            
        # ffmpeg로 만들어진 WAV 파일 삭제
        os.remove(wav_audio_file)
        
        self.finished.emit()  # 스레드 종료 시그널 발생
        
    def seconds_to_srt_time(self, seconds):
        """초 단위 시간을 SRT 파일 형식의 시간 문자열로 변환"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02}:{minutes:02}:{int(seconds):02},{milliseconds:03}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        loadUi("SRT_Creator.ui", self) 
        self.pushButton.clicked.connect(self.select_audio_file)
        self.comboBox.currentIndexChanged.connect(self.model_changed)
        self.comboBox_2.currentIndexChanged.connect(self.translate_to_selected_language)
        self.model_size = "base"  # 초기 모델 설정
        self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        self.srt_folder = ""  # SRT 파일이 저장될 폴더 경로를 초기화합니다.
        self.pushButton_1.clicked.connect(self.adjust_srt_time_faster)
        self.pushButton_2.clicked.connect(self.adjust_srt_time_slower)
        self.pushButton_7.clicked.connect(self.adjust_srt_time_faster1)
        self.pushButton_8.clicked.connect(self.adjust_srt_time_slower1)
        # 언어 선택 버튼에 대한 클릭 이벤트 연결
        self.pushButton_3.clicked.connect(lambda: self.translate_and_save('ko'))  # 한국어 버튼
        self.pushButton_4.clicked.connect(lambda: self.translate_and_save('en'))  # 영어 버튼
        self.pushButton_5.clicked.connect(lambda: self.translate_and_save('ja'))  # 일본어 버튼
        self.pushButton_6.clicked.connect(lambda: self.translate_and_save('zh-CN'))  # 중국어 버튼
        
        self.pushButton_10.clicked.connect(lambda: self.translate_and_save_deepl('KO'))  # 한국어 버튼
        self.pushButton_11.clicked.connect(lambda: self.translate_and_save_deepl('EN-US'))  # 영어 버튼
        self.pushButton_12.clicked.connect(lambda: self.translate_and_save_deepl('JA'))  # 일본어 버튼
        self.pushButton_13.clicked.connect(lambda: self.translate_and_save_deepl('ZN'))  # 중국어 버튼
        
        self.pushButton_9.clicked.connect(self.save_textedit_content)

        self.language = "None"
        # 드래그 앤 드롭 이벤트를 처리하기 위해 필요한 설정
        self.setAcceptDrops(True)
        self.textEdit.dragEnterEvent = self.dragEnterEvent
        self.textEdit.dropEvent = self.dropEvent
        self.textEdit = self.findChild(QTextEdit, "textEdit")  # QTextEdit 위젯 찾아서 할당
    
        # delta_seconds 초기화
        self.delta_seconds = 0
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_label)
        
        # QLabel에 QTimer 연결
        self.label_8.setText("      00:00")  # 초기 텍스트 설정
        
    def start_timer(self):
        self.elapsed_seconds = 0
        self.timer.start(1000)  # 1초마다 timeout 이벤트 발생

    def stop_timer(self):
        self.timer.stop()

    def update_label(self):
        # 타이머가 갱신될 때마다 라벨을 업데이트
        self.elapsed_seconds += 1
        minutes = self.elapsed_seconds // 60
        seconds = self.elapsed_seconds % 60
        self.label_8.setText(f"        {minutes:02d}:{seconds:02d}")

    def select_audio_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "파일 선택", "", "Audio Files (*.wav *.mp3 *.mp4)")
        if filename:
            self.process_audio_to_srt(filename)  # 선택한 파일을 처리하는 메서드 호출
            
    def model_changed(self, index):
        models = {"base": "base", "large-v2": "large-v2"}
        model_size = models[self.comboBox.currentText()]
        self.model_size = model_size  # 모델 크기 업데이트
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        # 모델 크기가 변경될 때마다 srt_process_thread 다시 시작
        if hasattr(self, 'srt_process_thread') and self.srt_process_thread.isRunning():
            self.srt_process_thread.terminate()  # 이전 스레드 중지
            self.process_audio_to_srt(self.lineEdit.text())  # 새로운 스레드 시작

    def translate_to_selected_language(self):
        audio_file = self.lineEdit.text()
        if not audio_file:
            self.statusbar.showMessage("오디오 파일을 선택하세요.", 3000)
            return
        
        self.language = "None"

        self.process_audio_to_srt(audio_file)

    def process_audio_to_srt(self, audio_file):
        # 기존 코드를 그대로 사용하면서 백그라운드에서 실행되도록 수정
        self.srt_process_thread = SrtProcessThread(audio_file, self.model, self.language, self.model_size)
        self.start_timer()  # 타이머 시작
        self.srt_process_thread.progress_changed.connect(self.progressBar.setValue)
        self.srt_process_thread.srt_generated.connect(self.textEdit.setPlainText)
        self.srt_process_thread.start()
        self.srt_process_thread.finished.connect(self.stop_timer)  # 스레드 종료 시 타이머 정지 연결

    def adjust_srt_time_faster(self):
        self.adjust_srt_time(-0.1)  # 0.1초 빠르게 조정

    def adjust_srt_time_slower(self):
        self.adjust_srt_time(0.1)  # 0.1초 느리게 조정
        
    def adjust_srt_time_faster1(self):
        self.adjust_srt_time(-1)  # 1초 빠르게 조정

    def adjust_srt_time_slower1(self):
        self.adjust_srt_time(1)  # 1초 느리게 조정

    def adjust_srt_time(self, delta_seconds):
        # 현재 선택된 텍스트의 시작 및 끝 위치를 가져오기
        cursor = self.textEdit.textCursor()
        selection_start = cursor.selectionStart()
        selection_end = cursor.selectionEnd()

        if selection_start == selection_end:
            # 선택된 텍스트가 없는 경우에는 전체 텍스트에 대해 싱크 조절을 수행
            text = self.textEdit.toPlainText()
        else:
            # 선택된 텍스트가 있는 경우에는 해당 영역에 대해서만 싱크 조절을 수행
            text = self.textEdit.toPlainText()[selection_start:selection_end]

        # 선택된 텍스트를 각 줄로 분할하여 처리
        lines = text.split('\n')
        adjusted_lines = []

        for line in lines:
            if '-->' in line:  # 시간 형식인 경우
                # 시간 부분을 파싱
                start_time_str, end_time_str = line.split('-->')
                start_time = self.parse_srt_time(start_time_str)
                end_time = self.parse_srt_time(end_time_str)

                # 시간 조정
                start_time += timedelta(seconds=delta_seconds)
                end_time += timedelta(seconds=delta_seconds)

                # 새로운 시간 형식으로 변환하여 줄 추가
                adjusted_line = f"{self.format_srt_time(start_time)}-->{self.format_srt_time(end_time)}"
                adjusted_lines.append(adjusted_line)
            else:
                adjusted_lines.append(line)

        # 새로운 SRT 텍스트 설정
        adjusted_text = '\n'.join(adjusted_lines)

        if selection_start == selection_end:
            # 선택된 텍스트가 없는 경우에는 전체 텍스트에 대해 싱크 조절을 적용
            self.textEdit.setPlainText(adjusted_text)
        else:
            # 선택된 텍스트가 있는 경우에는 해당 영역에 대해서만 싱크 조절을 적용
            cursor.insertText(adjusted_text)

    def parse_srt_time(self, time_str):
        # SRT 시간 형식을 파싱하여 timedelta 객체로 반환
        time_parts = time_str.split(',')
        hours, minutes, seconds = map(float, time_parts[0].split(':'))
        milliseconds = float(time_parts[1])
        return timedelta(hours=hours, minutes=minutes, seconds=seconds, milliseconds=milliseconds)
    
    def format_srt_time(self, time):
        # timedelta 객체를 SRT 시간 형식으로 변환하여 반환
        hours, remainder = divmod(time.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = time.microseconds // 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
    
    def save_subtitle_to_file(self, subtitle_text, language):
        # 저장될 파일명 설정
        base_name = "translated_subtitle"
        srt_file_name = f"{base_name}_{language}.srt"

        # srt 파일로 자막 저장
        with open(srt_file_name, 'w', encoding='utf-8') as srt_file:
            srt_file.write(subtitle_text)
         
    def translate_and_save(self, language):
        # textEdit에서 자막 텍스트 가져오기
        subtitle_text = self.textEdit.toPlainText()

        # 번역된 전체 자막을 저장할 리스트 생성
        translated_parts = []

        # 5000자씩 분할하여 번역하고 저장
        parts = [subtitle_text[i:i+5000] for i in range(0, len(subtitle_text), 5000)]
        for current_part in parts:
            # 언어에 따라 자막 텍스트를 해당 언어로 번역
            if language == 'ko':
                dest_language = '한국어'
            elif language == 'en':
                dest_language = '영어'
            elif language == 'ja':
                dest_language = '일본어'
            elif language == 'zh-CN':
                dest_language = '중국어'
            else:
                dest_language = language

            # 번역기를 사용하여 자막을 해당 언어로 번역
            translator = Translator()
            translated_part = translator.translate(current_part.strip(), dest=language)
            if translated_part:
                translated_parts.append(translated_part.text)
            else:
                # 번역된 부분이 없는 경우에 대한 처리
                translated_parts.append("")  # 또는 다른 처리 방법을 선택

        # 전체 번역된 자막을 하나의 문자열로 결합
        translated_subtitle = "\n".join(translated_parts)

        # 전각 클론을 반각 클론으로 변경
        translated_subtitle = translated_subtitle.replace('：', ':')
        
        translated_subtitle = translated_subtitle.replace('->', '-->')

        # 수정된 자막을 텍스트 편집기에 표시
        self.textEdit.setPlainText(translated_subtitle)

        # 번역된 자막을 파일로 저장
        self.save_subtitle_to_file(translated_subtitle, language)
    
    def translate_and_save_deepl(self, language):
        # textEdit에서 자막 텍스트 가져오기
        subtitle_text = self.textEdit.toPlainText()

        # 번역된 전체 자막을 저장할 리스트 생성
        translated_parts = []

        # 5000자씩 분할하여 번역하고 저장
        parts = [subtitle_text[i:i+5000] for i in range(0, len(subtitle_text), 5000)]
        for current_part in parts:
            # 언어에 따라 자막 텍스트를 해당 언어로 번역
            if language == 'KO':
                target_language = '한국어'
            elif language == 'EN-US':
                target_language = '영어'
            elif language == 'JA':
                target_language = '일본어'
            elif language == 'ZN':
                target_language = '중국어'
            else:
                target_language = language

            # 번역기를 사용하여 자막을 해당 언어로 번역
            auth_key = "DeepL API 키 입력"
            translator = deepl.Translator(auth_key)
                
            translated_part = translator.translate_text(current_part.strip(), target_lang=language)
            if translated_part:
                translated_parts.append(translated_part.text)
            else:
                # 번역된 부분이 없는 경우에 대한 처리
                translated_parts.append("")

        # 전체 번역된 자막을 하나의 문자열로 결합
        translated_subtitle = "\n".join(translated_parts)

        # 수정된 자막을 텍스트 편집기에 표시
        self.textEdit.setPlainText(translated_subtitle)

        # 번역된 자막을 파일로 저장
        self.save_subtitle_to_file(translated_subtitle, language)
    
    
    def save_textedit_content(self):
        # QTextEdit의 내용을 파일로 저장
        srt_text = self.textEdit.toPlainText()
        
        # 파일 이름을 직접 지정
        base_name = "saved_subtitle"
        srt_file_name = f"{base_name}.srt"
        with open(srt_file_name, 'w', encoding='utf-8') as srt_file:
            srt_file.write(srt_text)
                
    def adjust_translated_srt_time(self, translated_subtitle):
        # 번역된 자막을 줄 단위로 분할
        lines = translated_subtitle.split('\n')
        adjusted_lines = []

        for line in lines:
            if '-->' in line:  # 시간 형식인 경우
                # 시간 부분을 분리
                start_time_str, arrow, end_time_str = line.partition('-->')
                # 시간 형식을 그대로 유지하고 연결 부분을 '-->'으로 변경
                adjusted_line = f"{start_time_str.strip()}-->{end_time_str.strip()}"
                adjusted_lines.append(adjusted_line)
            else:
                adjusted_lines.append(line)

        # 조정된 자막 텍스트로 변환
        adjusted_subtitle = '\n'.join(adjusted_lines)
        return adjusted_subtitle
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):  # 파일인 경우에만 처리
                self.load_srt_file(file_path)

    def load_srt_file(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            srt_text = file.read()

        # 텍스트 편집기에 로드된 SRT 텍스트 표시
        self.textEdit.setPlainText(srt_text)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())