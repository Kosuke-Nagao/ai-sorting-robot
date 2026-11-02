"""Create the reproducible sorting workcell in Gazebo Classic."""

from dataclasses import dataclass
import math
from typing import Iterable

import rclpy
from gazebo_msgs.srv import DeleteEntity, SpawnEntity
from geometry_msgs.msg import Pose
from rclpy.node import Node


@dataclass(frozen=True)
class Model:
    name: str
    sdf: str
    xyz: tuple[float, float, float]
    orientation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)


def box_sdf(
    name: str,
    size: tuple[float, float, float],
    color: tuple[float, float, float, float],
    *,
    static: bool,
    mass: float = 0.08,
    geometry_offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    geometry_rpy: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> str:
    sx, sy, sz = size
    r, g, b, a = color
    ox, oy, oz = geometry_offset
    rr, rp, ry = geometry_rpy
    er, eg, eb = r * 0.35, g * 0.35, b * 0.35
    static_text = "true" if static else "false"
    inertia = mass * (sx * sx + sy * sy + sz * sz) / 6.0
    return f"""<?xml version="1.0"?>
<sdf version="1.7">
  <model name="{name}">
    <static>{static_text}</static>
    <link name="body">
      <inertial>
        <pose>{ox} {oy} {oz} {rr} {rp} {ry}</pose>
        <mass>{mass}</mass>
        <inertia>
          <ixx>{inertia}</ixx><iyy>{inertia}</iyy><izz>{inertia}</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz>
        </inertia>
      </inertial>
      <collision name="collision">
        <pose>{ox} {oy} {oz} {rr} {rp} {ry}</pose>
        <geometry><box><size>{sx} {sy} {sz}</size></box></geometry>
        <surface>
          <friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction>
        </surface>
      </collision>
      <visual name="visual">
        <pose>{ox} {oy} {oz} {rr} {rp} {ry}</pose>
        <geometry><box><size>{sx} {sy} {sz}</size></box></geometry>
        <material>
          <ambient>{r} {g} {b} {a}</ambient>
          <diffuse>{r} {g} {b} {a}</diffuse>
          <emissive>{er} {eg} {eb} {a}</emissive>
        </material>
      </visual>
    </link>
  </model>
</sdf>"""


def workcell_models() -> Iterable[Model]:
    # The UR3 base is at z=0.505 m.  The table top is aligned to that height.
    yield Model(
        "sorting_table",
        box_sdf("sorting_table", (0.60, 0.72, 0.06), (0.38, 0.29, 0.20, 1.0), static=True),
        (0.41, 0.0, 0.475),
    )

    # A thin static contact surface prevents small dynamic cubes from
    # tunneling through the table under the emulated Gazebo physics loop.
    yield Model(
        "cube_support_surface",
        # Cover the full tabletop so dynamically simulated cubes do not
        # tunnel through the table or fall off when released near a zone edge.
        box_sdf("cube_support_surface", (0.58, 0.68, 0.016), (0.38, 0.29, 0.20, 1.0), static=True),
        (0.41, 0.0, 0.507),
    )

    # Colored destination pads: blue is LEFT (+y), green is RIGHT (-y).
    yield Model(
        "left_sorting_zone",
        box_sdf("left_sorting_zone", (0.24, 0.24, 0.012), (0.10, 0.35, 0.95, 1.0), static=True),
        (0.22, 0.25, 0.511),
    )
    yield Model(
        "right_sorting_zone",
        box_sdf("right_sorting_zone", (0.24, 0.24, 0.012), (0.10, 0.35, 0.95, 1.0), static=True),
        (0.22, -0.25, 0.511),
    )

    # 60 mm cubes leave a small clearance inside the Robotiq opening at the
    # calibrated 40% grasp command (about 70 mm fingertip spacing). Gazebo's
    # link-attacher aligns *link origins*, rather than visual geometry.  We
    # measured the midpoint of the two Robotiq fingertip-link frames at this
    # command: it is 23.5 mm along local -X from the EE link.  Offset each cube
    # geometry by that amount inside its body link, so after attachment its
    # visible centre lies between the two fingertips.  The EE has a downward
    # orientation, so apply its inverse to the cube geometry.  The cube model
    # itself starts with the same downward orientation; the two rotations
    # cancel, keeping the cube level before and after attachment.
    cube_z = 0.545
    cube_size = (0.06, 0.06, 0.06)
    grasp_offset = (-0.0235, 0.0, 0.0)
    grasp_geometry_rpy = (math.pi / 2.0, 0.0, -math.pi / 2.0)
    cube_orientation = (-0.5, 0.5, 0.5, 0.5)
    yield Model(
        "red_cube",
        box_sdf(
            "red_cube", cube_size, (0.90, 0.08, 0.08, 1.0), static=False,
            geometry_offset=grasp_offset,
            geometry_rpy=grasp_geometry_rpy,
        ),
        (0.29, 0.10, cube_z - 0.0235),
        cube_orientation,
    )
    yield Model(
        "blue_cube",
        box_sdf(
            "blue_cube", cube_size, (0.05, 0.20, 0.95, 1.0), static=False,
            geometry_offset=grasp_offset,
            geometry_rpy=grasp_geometry_rpy,
        ),
        (0.38, 0.00, cube_z - 0.0235),
        cube_orientation,
    )
    yield Model(
        "yellow_cube",
        box_sdf(
            "yellow_cube", cube_size, (0.95, 0.78, 0.05, 1.0), static=False,
            geometry_offset=grasp_offset,
            geometry_rpy=grasp_geometry_rpy,
        ),
        (0.29, -0.10, cube_z - 0.0235),
        cube_orientation,
    )


class WorkcellSpawner(Node):
    def __init__(self) -> None:
        super().__init__("workcell_spawner")
        self.spawn_client = self.create_client(SpawnEntity, "/spawn_entity")
        self.delete_client = self.create_client(DeleteEntity, "/delete_entity")

    def wait_for_gazebo(self) -> None:
        self.get_logger().info("Waiting for Gazebo spawn service...")
        while rclpy.ok() and not self.spawn_client.wait_for_service(timeout_sec=2.0):
            self.get_logger().info("Gazebo is still starting...")

    def delete_if_present(self, name: str) -> None:
        if not self.delete_client.wait_for_service(timeout_sec=1.0):
            return
        request = DeleteEntity.Request()
        request.name = name
        future = self.delete_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=3.0)

    def spawn(self, model: Model) -> None:
        self.delete_if_present(model.name)
        request = SpawnEntity.Request()
        request.name = model.name
        request.xml = model.sdf
        request.robot_namespace = ""
        request.reference_frame = "world"
        request.initial_pose = Pose()
        request.initial_pose.position.x = model.xyz[0]
        request.initial_pose.position.y = model.xyz[1]
        request.initial_pose.position.z = model.xyz[2]
        request.initial_pose.orientation.x = model.orientation[0]
        request.initial_pose.orientation.y = model.orientation[1]
        request.initial_pose.orientation.z = model.orientation[2]
        request.initial_pose.orientation.w = model.orientation[3]

        future = self.spawn_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        if future.result() is None:
            raise RuntimeError(f"Timed out while spawning {model.name}")
        if not future.result().success:
            raise RuntimeError(f"Failed to spawn {model.name}: {future.result().status_message}")
        x, y, z = model.xyz
        self.get_logger().info(
            f"Spawned {model.name} at ({x:.3f}, {y:.3f}, {z:.3f})"
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WorkcellSpawner()
    try:
        node.wait_for_gazebo()
        for model in workcell_models():
            node.spawn(model)
        node.get_logger().info("Sorting workcell is ready.")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
