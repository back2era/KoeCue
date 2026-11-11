"""Color palettes for the desktop themes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    label: str
    backdrop: str
    glows: tuple[str, ...]
    text: str
    muted: str
    disabled: str
    surface_tint: str
    border_tint: str
    table: str
    alternate_row: str
    table_header: str
    selection: str
    focus: str
    action_top: str
    action_bottom: str
    action_text: str
    light: bool = False


DEFAULT_THEME = "black"

THEMES = {
    "graphite": Theme(
        label="石墨银", backdrop="#111215", glows=("#41464e", "#303237", "#24282d"),
        text="#edeef1", muted="#bbc0c8", disabled="#969ba3",
        surface_tint="#e1e4ec", border_tint="#d5d9e3",
        table="#1e1f23", alternate_row="#292b30", table_header="#393b41",
        selection="#454b54", focus="#b9c2cf",
        action_top="#e7e9ed", action_bottom="#b8bec8", action_text="#1d2229",
    ),
    "ocean": Theme(
        label="深海青", backdrop="#0b191b", glows=("#28484c", "#1f3439", "#173736"),
        text="#e3f0ee", muted="#aac3bf", disabled="#859e9b",
        surface_tint="#a6d1c7", border_tint="#afd1ca",
        table="#142527", alternate_row="#1e3133", table_header="#304546",
        selection="#315653", focus="#a9d5c8",
        action_top="#c8ebe1", action_bottom="#95c6b8", action_text="#17312f",
    ),
    "glacier": Theme(
        label="冰川白", backdrop="#e4edf5", glows=("#f7fbff", "#c5d9ee", "#d3e8ed"),
        text="#213549", muted="#4a657b", disabled="#5e7487",
        surface_tint="#ffffff", border_tint="#6487a7",
        table="#edf4f9", alternate_row="#e3edf6", table_header="#dce7f0",
        selection="#c4dcef", focus="#4e789b",
        action_top="#e5f1fb", action_bottom="#c3dbee", action_text="#203649",
        light=True,
    ),
    "sand": Theme(
        label="暖雾米", backdrop="#ece1d3", glows=("#fff9ee", "#e1c7b0", "#f5ebd9"),
        text="#3b2e25", muted="#695548", disabled="#746557",
        surface_tint="#fffdf8", border_tint="#9c7861",
        table="#f5ede5", alternate_row="#eee5db", table_header="#ebe0d5",
        selection="#edd5bb", focus="#8c6749",
        action_top="#f8eee0", action_bottom="#e5cfb6", action_text="#3b2e25",
        light=True,
    ),
    "black": Theme(
        label="纯黑", backdrop="#000000", glows=(),
        text="#f5f5f7", muted="#b3b3bb", disabled="#919199",
        surface_tint="#e2e2ec", border_tint="#dedee5",
        table="#101012", alternate_row="#1a1a1e", table_header="#262629",
        selection="#3d3e46", focus="#c8c9d1",
        action_top="#f3f3f6", action_bottom="#b6b7c0", action_text="#16161a",
    ),
}
