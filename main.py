import sys
import os
import json
import base64
import gitlab
from gitlab.exceptions import GitlabCreateError
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, QLineEdit,
                             QProgressBar, QTextEdit, QSystemTrayIcon, QMenu, QAction, QComboBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QIcon

CONFIG_DIR = os.path.expanduser("~/.gitlabuploader")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

def get_logo_path():
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'logo.png')
    else:
        return os.path.join(os.path.dirname(__file__), 'logo.png')

def ensure_config_directory():
    """确保配置目录存在，如果不存在则创建它"""
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

def load_config():
    """从配置文件中加载配置"""
    ensure_config_directory()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as file:
            return json.load(file)
    return {}

def save_config(config):
    """保存配置到配置文件"""
    ensure_config_directory()
    with open(CONFIG_FILE, 'w') as file:
        json.dump(config, file)

def clear_config():
    """清除配置文件"""
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)

class UploadWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)

    def __init__(self, gitlab_url, token, project_id, file_path):
        super().__init__()
        self.gitlab_url = gitlab_url
        self.token = token
        self.project_id = project_id
        self.file_path = file_path

    def run(self):
        try:
            gl = gitlab.Gitlab(url=self.gitlab_url, private_token=self.token)

            try:
                project = gl.projects.get(self.project_id)
            except gitlab.exceptions.GitlabGetError:
                self.log_signal.emit("<b style='color:red;'>项目 ID 无效或无法访问！</b>")
                return

            files_to_upload = []
            self.log_signal.emit("获取文件数量...")
            for root, _, files in os.walk(self.file_path):
                for file in files:
                    file_full_path = os.path.join(root, file)
                    files_to_upload.append(file_full_path)

            total_files = len(files_to_upload)
            if total_files == 0:
                self.log_signal.emit("<b style='color:red;'>没有找到文件可以上传！</b>")
                return

            self.log_signal.emit(f"共有{total_files}个文件")

            for index, file_full_path in enumerate(files_to_upload):
                with open(file_full_path, 'rb') as f:
                    content = f.read()
                    b64_content = base64.b64encode(content).decode('utf-8')

                parsed_file_path = file_full_path[len(self.file_path) + 1:].replace("\\", "/")
                self.log_signal.emit(f"上传 {parsed_file_path}...")

                try:
                    project.files.create({
                        'file_path': parsed_file_path,
                        'branch': 'main',
                        'content': b64_content,
                        'commit_message': 'Upload file',
                        'encoding': 'base64'
                    })
                except GitlabCreateError as e:
                    self.log_signal.emit(f"<b style='color:red;'>上传错误: {str(e)}</b>")

                # 更新进度条
                progress = int((index + 1) / total_files * 100)
                self.progress_signal.emit(progress)

            self.log_signal.emit("<b style='color:green;'>所有文件上传完成！</b>")

        except Exception as e:
            self.log_signal.emit(f"<b style='color:red;'>发生异常: {str(e)}</b>")

class UploadApp(QWidget):
    def __init__(self):
        super().__init__()

        self.token = ''
        self.project_id = ''
        self.file_path = ''
        self.gitlab_url = ''

        self.initUI()
        self.load_settings()
        self.init_tray_icon()

    def initUI(self):
        self.setWindowTitle('GitLab File Uploader')
        self.setGeometry(100, 100, 400, 500)  # 设置较大的窗口大小
        self.setWindowIcon(QIcon(get_logo_path()))

        layout = QVBoxLayout()

        self.title_label = QLabel("GitLab Uploader")
        self.title_label.setStyleSheet("font-size: 24px; font-weight: bold;")  # 设置字体大小与风格
        self.title_label.setAlignment(Qt.AlignCenter)  # 居中对齐
        layout.addWidget(self.title_label)

        self.copywrite_label = QLabel("By XzyStudio")
        self.copywrite_label.setStyleSheet("font-size: 14px;")  # 设置字体大小与风格
        self.copywrite_label.setAlignment(Qt.AlignCenter)  # 居中对齐
        layout.addWidget(self.copywrite_label)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.gitlab_url_label = QLabel("GitLab URL:")
        layout.addWidget(self.gitlab_url_label)

        # 使用下拉框实现 GitLab URL 选择，允许用户自定义
        self.gitlab_url_input = QComboBox(self)
        self.gitlab_url_input.addItems(["https://gitlab.com", "https://gitlab.hk"])  # 添加默认选项
        self.gitlab_url_input.setEditable(True)  # 允许用户自定义
        layout.addWidget(self.gitlab_url_input)

        self.token_label = QLabel("GitLab Token:")
        layout.addWidget(self.token_label)

        self.token_input = QLineEdit(self)
        layout.addWidget(self.token_input)

        self.project_id_label = QLabel("GitLab Project ID:")
        layout.addWidget(self.project_id_label)

        self.project_id_input = QLineEdit(self)
        layout.addWidget(self.project_id_input)

        self.label = QLabel("选择要上传的目录:")
        layout.addWidget(self.label)

        self.select_button = QPushButton("选择目录")
        self.select_button.clicked.connect(self.select_directory)
        layout.addWidget(self.select_button)

        self.upload_button = QPushButton("上传文件")
        self.upload_button.clicked.connect(self.upload_files)
        layout.addWidget(self.upload_button)

        self.clear_config_button = QPushButton("清除配置文件")
        self.clear_config_button.clicked.connect(self.clear_config)
        layout.addWidget(self.clear_config_button)

        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_area = QTextEdit(self)
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

        self.setLayout(layout)

        # Connect upload worker signals
        self.worker = None

    def init_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(get_logo_path()))
        self.tray_icon.setVisible(True)

        # 创建托盘菜单
        tray_menu = QMenu(self)

        restore_action = QAction("恢复", self)
        restore_action.triggered.connect(self.show)
        tray_menu.addAction(restore_action)

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.exit_app)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)

    def select_directory(self):
        self.file_path = QFileDialog.getExistingDirectory(self, "选择目录")
        if self.file_path:
            self.label.setText(f"选择的目录: {self.file_path}")

    def upload_files(self):
        self.log_area.clear()
        self.gitlab_url = self.gitlab_url_input.currentText()  # 获取当前选中的 GitLab URL
        self.token = self.token_input.text()
        self.project_id = self.project_id_input.text()

        if not self.gitlab_url or not self.token or not self.project_id:
            self.log("请填写 GitLab URL、Token 和 Project ID！")
            return

        if not self.file_path:
            self.log("请先选择目录！")
            return

        self.log("开始上传文件...")
        self.progress_bar.setValue(0)

        # 保存配置到文件
        self.save_settings()

        # Stop any existing worker
        if self.worker is not None:
            self.worker.terminate()

        self.worker = UploadWorker(self.gitlab_url, self.token, self.project_id, self.file_path)
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.start()

    def log(self, message):
        self.log_area.append(message)

    def save_settings(self):
        config = {
            'token': self.token,
            'project_id': self.project_id
        }
        save_config(config)

    def load_settings(self):
        config = load_config()
        self.token_input.setText(config.get('token', ''))
        self.project_id_input.setText(config.get('project_id', ''))

    def clear_config(self):
        clear_config()
        self.log("配置文件已清除。")

    def exit_app(self):
        self.tray_icon.hide()
        sys.exit()

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # 检查系统托盘是否可用
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("系统托盘不可用！")
        sys.exit(1)

    QApplication.setQuitOnLastWindowClosed(False)

    uploader = UploadApp()
    uploader.show()

    sys.exit(app.exec_())
