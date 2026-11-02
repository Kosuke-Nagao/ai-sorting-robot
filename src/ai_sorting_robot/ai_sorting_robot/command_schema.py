from dataclasses import dataclass


CUBE_POSES = {
    "red": (0.29, 0.10),
    "blue": (0.38, 0.00),
    "yellow": (0.29, -0.10),
}


ZONE_POSES = {
    "left": (0.22, 0.25),
    "right": (0.22, -0.25),
}


@dataclass(frozen=True)
class SortCommand:
    color: str
    destination: str

    def validate(self) -> None:
        if self.color not in CUBE_POSES:
            raise ValueError(f"Unsupported color: {self.color}")

        if self.destination not in ZONE_POSES:
            raise ValueError(f"Unsupported destination: {self.destination}")