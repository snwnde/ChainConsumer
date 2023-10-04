from collections.abc import Iterable

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import rgb2hex

# Colours drawn from material designs colour pallet at https://material.io/guidelines/style/color.html

ColourInput = str | np.ndarray | list[float]


class Colors:
    def __init__(self):
        self.color_map: dict[str, str] = {
            "blue": "#1976D2",
            "lblue": "#4FC3F7",
            "red": "#E53935",
            "green": "#43A047",
            "lgreen": "#8BC34A",
            "purple": "#673AB7",
            "cyan": "#4DD0E1",
            "magenta": "#E91E63",
            "yellow": "#F2D026",
            "black": "#333333",
            "grey": "#9E9E9E",
            "orange": "#FB8C00",
            "amber": "#FFB300",
            "brown": "#795548",
        }
        self.aliases: dict[str, str] = {
            "b": "blue",
            "r": "red",
            "g": "green",
            "k": "black",
            "m": "magenta",
            "c": "cyan",
            "o": "orange",
            "y": "yellow",
            "a": "amber",
            "p": "purple",
            "e": "grey",
            "lg": "lgreen",
            "lb": "lblue",
        }
        self.default_colors: tuple[str, ...] = (
            "blue",
            "lgreen",
            "red",
            "purple",
            "yellow",
            "grey",
            "lblue",
            "magenta",
            "green",
            "brown",
            "black",
            "orange",
        )

    def format(self, color: ColourInput) -> str:
        if isinstance(color, np.ndarray | list):
            color = rgb2hex(color)  # type: ignore
        if color[0] == "#":
            return color
        elif color in self.color_map:
            return self.color_map[color]
        elif color in self.aliases:
            alias = self.aliases[color]
            return self.color_map[alias]
        else:
            raise ValueError("Color %s is not mapped. Please give a hex code" % color)

    def get_formatted(self, list_colors: Iterable[ColourInput]) -> list[str]:
        return [self.format(c) for c in list_colors]

    def get_default(self) -> list[str]:
        return self.get_formatted(self.default_colors)

    def get_colormap(self, num: int, cmap_name: str, scale: float = 0.7) -> list[str]:  # pragma: no cover
        color_list = self.get_formatted(plt.get_cmap(cmap_name)(np.linspace(0.05, 0.9, num)))
        scales = scale + (1 - scale) * np.abs(1 - np.linspace(0, 2, num))
        scaled = [self.scale_colour(c, s) for c, s in zip(color_list, scales)]
        return scaled

    def scale_colour(self, color: ColourInput, scalefactor: float) -> str:  # pragma: no cover
        hexx = self.format(color).strip("#")
        if scalefactor < 0 or len(hexx) != 6:
            return hexx
        r, g, b = int(hexx[:2], 16), int(hexx[2:4], 16), int(hexx[4:], 16)
        r = self._clamp(int(r * scalefactor))
        g = self._clamp(int(g * scalefactor))
        b = self._clamp(int(b * scalefactor))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _clamp(self, val: float, minimum: int = 0, maximum: int = 255):
        if val < minimum:
            return minimum
        if val > maximum:
            return maximum
        return val


colors = Colors()
