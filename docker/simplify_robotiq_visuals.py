"""Keep only the two Robotiq fingertip visuals in the Gazebo model.

The physical 2F-85 still has all of its joints and collision geometry.  We
only hide the four intermediate link meshes so the recording clearly shows
the two opposing fingertip pads that grasp the cube.
"""

from pathlib import Path
import re


paths = (
    Path(
        "/opt/robot_ws/src/ros2_SimRealRobotControl/"
        "ros2srrc_endeffectors/robotiq_2f85/urdf/robotiq_2f85_macro.urdf.xacro"
    ),
    Path(
        "/opt/robot_ws/install/ros2srrc_endeffectors/share/"
        "ros2srrc_endeffectors/robotiq_2f85/urdf/robotiq_2f85_macro.urdf.xacro"
    ),
)

# Keep the outer knuckle/finger meshes so each visible fingertip remains
# connected to the gripper body.  Hide only the inner linkage that makes the
# real 2F-85 look like four separate fingertips from this camera view.
hidden_links = (
    "robotiq_85_left_inner_knuckle_link",
    "robotiq_85_right_inner_knuckle_link",
)

for path in paths:
    if not path.exists():
        continue
    text = path.read_text()
    for link_name in hidden_links:
        link_pattern = re.compile(
            rf'(<link name="\${{prefix}}{re.escape(link_name)}">)(.*?)(</link>)',
            re.DOTALL,
        )
        match = link_pattern.search(text)
        if match is None:
            raise SystemExit(f"link not found: {link_name} in {path}")
        body = re.sub(
            r"\s*<visual>.*?</visual>\s*", "\n", match.group(2), flags=re.DOTALL
        )
        text = text[: match.start(2)] + body + text[match.end(2) :]
    path.write_text(text)

print("Robotiq inner linkage visuals hidden; connected fingertip visuals retained.")
