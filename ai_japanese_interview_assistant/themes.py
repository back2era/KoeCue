"""Saved theme IDs and the desktop application's color and spacing tokens."""
from dataclasses import dataclass


GAP = 8
INSET = 16
GUTTER = 24
CONTROL_RADIUS = 7
PANEL_RADIUS = 12

TEXT_SMALL = 12
TEXT_BODY = 14
TEXT_CAPTION = 16
TEXT_ANSWER = 20
TEXT_TITLE = 24

UI_FONTS = ("Inter", "Segoe UI", "Microsoft YaHei UI", "Yu Gothic UI")
JAPANESE_FONTS = ("Yu Gothic UI", "Noto Sans JP", "Meiryo", "Microsoft YaHei UI")


@dataclass(frozen=True)
class Theme:
    label: str
    backdrop: str
    surface: str
    elevated: str
    border: str
    text: str
    secondary: str
    muted: str
    disabled: str
    accent: str
    action: str
    action_text: str
    selection: str
    success: str
    warning: str
    danger: str
    light: bool = False


DEFAULT_THEME = "graphite"

THEMES = {
    "graphite": Theme(
        label="石墨银", backdrop="#111216", surface="#1b1c22", elevated="#25262d", border="#34363e",
        text="#f1f1f4", secondary="#a4a6b1", muted="#8a8c9a", disabled="#777a87",
        accent="#a4a5f0", action="#a1a2ee", action_text="#1c1d31", selection="#2d2e45",
        success="#75c5a5", warning="#e1b780", danger="#f4a3a9",
    ),
    "ocean": Theme(
        label="深海青", backdrop="#121a1c", surface="#1a2628", elevated="#233336", border="#35484a",
        text="#eaf5f3", secondary="#acc4bf", muted="#90aaa4", disabled="#758e8a",
        accent="#a9dacd", action="#b1dfd2", action_text="#172f2c", selection="#2b4341",
        success="#8bdbb9", warning="#edc390", danger="#f4a6aa",
    ),
    "glacier": Theme(
        label="冰川白", backdrop="#edf2f7", surface="#f7f9fc", elevated="#e4ebf4", border="#cbd6e4",
        text="#243344", secondary="#465d73", muted="#556d83", disabled="#697d91",
        accent="#304f89", action="#405e96", action_text="#f4f7ff", selection="#dce7f5",
        success="#25614f", warning="#755023", danger="#983a50", light=True,
    ),
    "sand": Theme(
        label="暖雾米", backdrop="#f0e8dd", surface="#f8f1e8", elevated="#eae0d4", border="#d6c6b5",
        text="#382c25", secondary="#614e42", muted="#6b5749", disabled="#756557",
        accent="#764d37", action="#754e3a", action_text="#fcf6ed", selection="#eadbca",
        success="#35614c", warning="#78501e", danger="#963d49", light=True,
    ),
    "black": Theme(
        label="深黑", backdrop="#131316", surface="#19191d", elevated="#24242a", border="#35353d",
        text="#f2f2f5", secondary="#b2b2bc", muted="#93939e", disabled="#7d7d87",
        accent="#bfc0e5", action="#c5c6e6", action_text="#212136", selection="#30313e",
        success="#85c9ad", warning="#e6bd8b", danger="#f2a4ab",
    ),
}
