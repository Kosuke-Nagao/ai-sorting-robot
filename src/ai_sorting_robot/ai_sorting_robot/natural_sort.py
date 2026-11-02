"""Natural-language entry point: LLM parsing followed by robot execution."""

import argparse

import rclpy

from .llm_parser import parse_instruction
from .pick_place import PickPlace


def main(args=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "instruction",
        nargs="?",
        help="Natural-language sorting instruction. If omitted, read from stdin.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the instruction without moving the robot.",
    )
    parsed = parser.parse_args(args)
    instruction = parsed.instruction or input("Sorting instruction> ")

    command = parse_instruction(instruction)
    print(
        f"LLM decision: color={command.color}, "
        f"destination={command.destination}"
    )

    if parsed.dry_run:
        return

    rclpy.init(args=args)
    node = PickPlace(command.color, command.destination)
    try:
        node.execute()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
