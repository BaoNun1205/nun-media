from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppTheme:
    app_bg: str = "#0D0E12"
    sidebar_bg: str = "#121319"
    surface: str = "#18191F"
    surface_low: str = "#14151B"
    surface_elevated: str = "#1D1E25"
    surface_hover: str = "#23242C"
    border: str = "#2B2D36"
    border_soft: str = "#242630"
    border_focus: str = "#6E68E8"
    primary: str = "#6C63E8"
    primary_hover: str = "#7A72EF"
    primary_pressed: str = "#5C54D7"
    primary_soft: str = "#D7D4FF"
    text_primary: str = "#F4F4F6"
    text_secondary: str = "#A5A6AF"
    text_muted: str = "#737580"
    success: str = "#32C774"
    warning: str = "#F2A93B"
    error: str = "#EF5B64"

    radius_small: int = 6
    radius_control: int = 8
    radius_medium: int = 12
    radius_card: int = 14
    radius_dialog: int = 16

    space_1: int = 4
    space_2: int = 8
    space_3: int = 12
    space_4: int = 16
    space_5: int = 20
    space_6: int = 24
    space_8: int = 32
    space_10: int = 40
    space_12: int = 48

    font_family: str = '"Segoe UI", "Inter", "Noto Sans"'


APP_THEME = AppTheme()


def build_stylesheet(theme: AppTheme = APP_THEME) -> str:
    return f"""
        QMainWindow, QWidget {{
            background: {theme.app_bg};
            color: {theme.text_primary};
            font-family: {theme.font_family};
            font-size: 13px;
            letter-spacing: 0px;
            selection-background-color: {theme.primary};
            selection-color: white;
        }}

        #Sidebar {{
            background: {theme.sidebar_bg};
            border-right: 1px solid {theme.border};
        }}

        #Topbar {{
            background: {theme.surface};
            border-bottom: 1px solid {theme.border};
        }}

        #Brand {{
            color: {theme.text_primary};
            font-size: 22px;
            font-weight: 700;
        }}

        #HeaderTitle {{
            color: {theme.text_primary};
            font-size: 20px;
            font-weight: 700;
        }}

        #PageTitle {{
            color: {theme.text_primary};
            font-size: 24px;
            font-weight: 700;
        }}

        #Panel {{
            background: {theme.surface};
            border: 1px solid {theme.border};
            border-radius: {theme.radius_card}px;
        }}

        #PanelHeader {{
            background: {theme.surface_elevated};
            border-bottom: 1px solid {theme.border};
            min-height: 44px;
            max-height: 48px;
            border-top-left-radius: {theme.radius_card}px;
            border-top-right-radius: {theme.radius_card}px;
        }}

        #PanelHeaderText {{
            color: {theme.text_primary};
            font-size: 14px;
            font-weight: 700;
        }}

        #ControlBar {{
            background: {theme.surface_elevated};
            border: 1px solid {theme.border};
            border-radius: {theme.radius_medium}px;
        }}

        #VideoSurface {{
            background: #050506;
            border: 1px solid {theme.border};
            border-radius: {theme.radius_medium}px;
        }}

        #Muted, #Status {{
            color: {theme.text_secondary};
        }}

        #Status {{
            background: {theme.surface_low};
            border-top: 1px solid {theme.border};
            font-size: 12px;
        }}

        #FieldLabel {{
            color: {theme.text_secondary};
            font-size: 12px;
            font-weight: 700;
            margin-top: 8px;
        }}

        #Hint {{
            color: {theme.text_muted};
            font-size: 12px;
        }}

        #BigNumber {{
            color: {theme.text_primary};
            font-size: 30px;
            font-weight: 700;
        }}

        QPushButton {{
            background: {theme.surface_elevated};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {theme.radius_control}px;
            padding: 8px 14px;
            min-height: 18px;
            font-weight: 600;
        }}

        QPushButton:hover {{
            background: {theme.surface_hover};
            border-color: {theme.border_focus};
        }}

        QPushButton:pressed {{
            background: {theme.surface_low};
            border-color: {theme.primary_pressed};
        }}

        QPushButton:disabled {{
            background: {theme.surface_low};
            color: {theme.text_muted};
            border-color: {theme.border_soft};
        }}

        QPushButton#PrimaryButton {{
            background: {theme.primary};
            color: white;
            border-color: {theme.primary};
            font-weight: 700;
        }}

        QPushButton#PrimaryButton:hover {{
            background: {theme.primary_hover};
            border-color: {theme.primary_hover};
        }}

        QPushButton#PrimaryButton:pressed {{
            background: {theme.primary_pressed};
            border-color: {theme.primary_pressed};
        }}

        QPushButton#PrimarySoftButton {{
            background: {theme.primary_soft};
            color: #121319;
            border-color: {theme.primary_soft};
            font-weight: 700;
        }}

        QPushButton#TransportButton {{
            min-width: 64px;
            padding: 7px 12px;
        }}

        QPushButton#TopLink {{
            background: transparent;
            border: 0;
            color: {theme.text_secondary};
            padding: 6px 10px;
            font-weight: 700;
        }}

        QPushButton#TopLink:hover {{
            color: {theme.text_primary};
            background: {theme.surface_hover};
        }}

        QPushButton#NavButton {{
            text-align: left;
            background: transparent;
            border: 1px solid transparent;
            border-radius: {theme.radius_control}px;
            padding: 9px 12px;
            font-weight: 700;
            color: {theme.text_secondary};
        }}

        QPushButton#NavButton:hover {{
            background: {theme.surface_hover};
            color: {theme.text_primary};
        }}

        QPushButton#NavButton[selected="true"] {{
            background: {theme.surface_elevated};
            color: {theme.text_primary};
            border-color: {theme.border_focus};
        }}

        QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{
            background: {theme.surface_low};
            border: 1px solid {theme.border};
            border-radius: {theme.radius_control}px;
            padding: 8px 10px;
            color: {theme.text_primary};
        }}

        QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover, QTextEdit:hover {{
            border-color: {theme.surface_hover};
        }}

        QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
            border-color: {theme.border_focus};
            background: {theme.surface};
        }}

        QLineEdit:disabled, QComboBox:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
            color: {theme.text_muted};
            background: {theme.surface_low};
            border-color: {theme.border_soft};
        }}

        QComboBox::drop-down {{
            border: 0;
            width: 28px;
        }}

        QComboBox QAbstractItemView {{
            background: {theme.surface_elevated};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {theme.radius_control}px;
            selection-background-color: {theme.surface_hover};
            selection-color: {theme.text_primary};
            outline: 0;
        }}

        QListWidget, QTableWidget {{
            background: {theme.surface_low};
            border: 1px solid {theme.border};
            border-radius: {theme.radius_medium}px;
            gridline-color: {theme.border_soft};
            selection-background-color: {theme.surface_hover};
            selection-color: {theme.text_primary};
            alternate-background-color: {theme.surface};
            outline: 0;
        }}

        QListWidget::item {{
            padding: 10px 12px;
            border-bottom: 1px solid {theme.border_soft};
        }}

        QListWidget::item:hover {{
            background: {theme.surface_hover};
        }}

        QListWidget::item:selected {{
            background: {theme.surface_hover};
            color: {theme.text_primary};
            border-left: 3px solid {theme.primary};
        }}

        QHeaderView::section {{
            background: {theme.surface_elevated};
            color: {theme.text_secondary};
            border: 0;
            border-bottom: 1px solid {theme.border};
            padding: 10px;
            font-weight: 700;
        }}

        QTableWidget::item {{
            padding: 8px;
            border-bottom: 1px solid {theme.border_soft};
        }}

        QTableWidget::item:selected {{
            background: {theme.surface_hover};
            color: {theme.text_primary};
        }}

        QSlider::groove:horizontal {{
            height: 6px;
            background: {theme.border};
            border-radius: 3px;
        }}

        QSlider::sub-page:horizontal {{
            background: {theme.primary};
            border-radius: 3px;
        }}

        QSlider::handle:horizontal {{
            background: {theme.text_primary};
            border: 2px solid {theme.primary};
            width: 16px;
            height: 16px;
            margin: -6px 0;
            border-radius: 8px;
        }}

        QProgressBar {{
            background: {theme.surface_low};
            border: 1px solid {theme.border};
            border-radius: {theme.radius_small}px;
            text-align: center;
            color: {theme.text_secondary};
        }}

        QProgressBar::chunk {{
            background: {theme.primary};
            border-radius: {theme.radius_small}px;
        }}

        QTabWidget::pane {{
            border: 1px solid {theme.border};
            border-top: 0;
            background: {theme.surface};
            border-bottom-left-radius: {theme.radius_medium}px;
            border-bottom-right-radius: {theme.radius_medium}px;
        }}

        QTabBar::tab {{
            background: {theme.surface_elevated};
            color: {theme.text_secondary};
            padding: 12px 18px;
            min-width: 120px;
            border-right: 1px solid {theme.border};
            font-weight: 700;
        }}

        QTabBar::tab:hover {{
            background: {theme.surface_hover};
            color: {theme.text_primary};
        }}

        QTabBar::tab:selected {{
            background: {theme.surface};
            color: {theme.text_primary};
            border-bottom: 2px solid {theme.primary};
        }}

        QScrollBar:vertical {{
            background: {theme.surface_low};
            width: 10px;
            margin: 2px;
        }}

        QScrollBar::handle:vertical {{
            background: {theme.border_focus};
            min-height: 40px;
            border-radius: 5px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: {theme.primary_hover};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}

        QScrollBar:horizontal {{
            background: {theme.surface_low};
            height: 10px;
            margin: 2px;
        }}

        QScrollBar::handle:horizontal {{
            background: {theme.border_focus};
            min-width: 40px;
            border-radius: 5px;
        }}

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
        }}

        QSplitter::handle {{
            background: {theme.app_bg};
        }}

        QMessageBox {{
            background: {theme.surface};
        }}
    """
