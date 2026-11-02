"""Parameterized pick-and-place demo for the sorting workcell."""

import argparse
from dataclasses import dataclass
import math
import os
import subprocess
import time

import rclpy
from linkattacher_msgs.srv import AttachLink, DetachLink
from gazebo_msgs.srv import DeleteEntity, SpawnEntity
from geometry_msgs.msg import Pose
from rclpy.action import ActionClient
from rclpy.node import Node
from ros2srrc_data.action import Move, Robmove
from ros2srrc_data.msg import Robpose

from .command_schema import CUBE_POSES, ZONE_POSES, SortCommand
from .spawn_workcell import box_sdf


@dataclass(frozen=True)
class Target:
    x: float
    y: float
    z: float


# Verified reachable UR3 pose for the supplied MoveIt configuration.
DOWN_QUATERNION = (-0.5, 0.5, 0.5, 0.5)

ROBOT_MODEL = "ur3"
# Use the native end-effector link, but attach it to the cube's non-rendered
# grasp_center link.  Attaching directly to the cube body makes the fixed
# link-attacher joint fight the visual/body offset and can tilt the cube.
GRIPPER_LINK = "EE_robotiq_2f85"
OBJECT_LINK = "grasp_center"
# This pair is the verified collision-free height for this UR3 workcell.
# Lower targets make the visual fingers look closer to the table but can
# destabilize the simulated gripper and interrupt the lift under emulation.
EE_GRASP_Z = 0.559
EE_PLACE_Z = 0.562
# The sorting pad top is about z=0.517 m. Keep the 60 mm cube's bottom
# slightly above that surface after release instead of embedding it in the
# pad by a few millimetres.
# The static placed cube has no grasp-center link, so its 60 mm body is
# centred just above the sorting pad at this height.
PLACE_BODY_Z = 0.548

# The simulated cubes are 60 mm wide.  The 40% setting leaves a realistic gap
# around the cube while the deterministic link attachment carries it.
GRASP_CLOSE_PERCENT = 40.0
# Briefly hold after the attachment so the grasp is clear in the recording.
GRASP_HOLD_SECONDS = float(os.environ.get("AI_SORTING_GRASP_HOLD_SECONDS", "3.0"))
# The cube body is world-aligned and its visible centre is at this height.
# The grasp_center child link is 14 mm above this centre, at EE_GRASP_Z.
GRASP_BODY_Z = 0.545
GRASP_BODY_RPY = (0.0, 0.0, 0.0)
GRASP_POSITION_TOLERANCE = 0.015
GRASP_LEVEL_TOLERANCE = 0.12

# Placement targets in the Gazebo world frame.  The link-attacher is used for
# deterministic simulation grasping; the pad collision/support geometry keeps
# the released cube on the work surface.
PLACE_TARGETS = {
    "left": (0.22, 0.25),
    "right": (0.22, -0.25),
}

CUBE_COLORS = {
    "red": (0.90, 0.08, 0.08, 1.0),
    "blue": (0.05, 0.20, 0.95, 1.0),
    "yellow": (0.95, 0.78, 0.05, 1.0),
}


class PickPlace(Node):
    def __init__(self, color: str, destination: str) -> None:
        super().__init__("fixed_pick_place")

        command = SortCommand(color=color, destination=destination)
        command.validate()

        cube_x, cube_y = CUBE_POSES[color]
        target_x, target_y = PLACE_TARGETS[destination]

        self.color = color
        self.destination = destination
        self.object_model = f"{color}_cube"
        self.pick_above = Target(cube_x, cube_y, 0.72)
        self.pick = Target(cube_x, cube_y, EE_GRASP_Z)
        self.place_above = Target(target_x, target_y, 0.72)
        self.place = Target(target_x, target_y, EE_PLACE_Z)
        self.grasp_xy = (cube_x, cube_y)

        self.robot_client = ActionClient(self, Robmove, "/Robmove")
        self.gripper_client = ActionClient(self, Move, "/Move")
        self.attach_client = self.create_client(AttachLink, "/ATTACHLINK")
        self.detach_client = self.create_client(DetachLink, "/DETACHLINK")
        self.spawn_client = self.create_client(SpawnEntity, "/spawn_entity")
        self.delete_client = self.create_client(DeleteEntity, "/delete_entity")
        self._ee_pose: Robpose | None = None
        self._ee_pose_subscription = self.create_subscription(
            Robpose, "/Robpose", self._on_ee_pose, 10
        )

    def _on_ee_pose(self, message: Robpose) -> None:
        self._ee_pose = message

    def wait_until_ready(self) -> None:
        self.get_logger().info("Waiting for robot and gripper action servers...")
        startup_timeout = 120.0
        if not self.robot_client.wait_for_server(timeout_sec=startup_timeout):
            raise RuntimeError("/Robmove action server is not available")
        if not self.gripper_client.wait_for_server(timeout_sec=startup_timeout):
            raise RuntimeError("/Move action server is not available")
        if not self.attach_client.wait_for_service(timeout_sec=startup_timeout):
            raise RuntimeError("/ATTACHLINK service is not available")
        if not self.detach_client.wait_for_service(timeout_sec=startup_timeout):
            raise RuntimeError("/DETACHLINK service is not available")

    def _wait(self, future, operation: str, timeout: float = 60.0):
        rclpy.spin_until_future_complete(self, future, timeout_sec=timeout)
        if not future.done() or future.result() is None:
            raise RuntimeError(f"{operation} timed out")
        return future.result()

    def move_robot(self, movement: str, target: Target, speed: float) -> None:
        qx, qy, qz, qw = DOWN_QUATERNION
        goal = Robmove.Goal()
        goal.type = movement
        goal.speed = speed
        goal.x = target.x
        goal.y = target.y
        goal.z = target.z
        goal.qx = qx
        goal.qy = qy
        goal.qz = qz
        goal.qw = qw

        self.get_logger().info(
            f"{movement}: moving to ({target.x:.2f}, {target.y:.2f}, {target.z:.2f})"
        )
        handle = self._wait(
            self.robot_client.send_goal_async(goal), f"send {movement} goal"
        )
        if not handle.accepted:
            raise RuntimeError(f"{movement} goal was rejected")
        wrapped_result = self._wait(
            handle.get_result_async(), f"execute {movement}", timeout=90.0
        )
        result = wrapped_result.result
        if not result.success:
            raise RuntimeError(f"{movement} failed: {result.message}")
        self.get_logger().info(result.message)

    def move_gripper(self, percentage: float) -> None:
        state = "opening" if percentage == 0.0 else "closing"
        self.get_logger().info(f"Gripper: {state} ({percentage:.0f}%)")
        last_error = None
        for attempt in range(1, 4):
            try:
                goal = Move.Goal()
                goal.action = "MoveG"
                goal.speed = 0.8
                goal.moveg = percentage
                handle = self._wait(
                    self.gripper_client.send_goal_async(goal), "send gripper goal"
                )
                if not handle.accepted:
                    raise RuntimeError("Gripper goal was rejected")
                wrapped_result = self._wait(
                    handle.get_result_async(), "move gripper", timeout=30.0
                )
                message = wrapped_result.result.result
                if "SUCCESS" in message:
                    self.get_logger().info(message)
                    return
                raise RuntimeError(f"Gripper failed: {message}")
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    self.get_logger().warning(
                        f"Gripper attempt {attempt} failed; retrying after settling"
                    )
                    time.sleep(1.0)
        raise last_error

    def move_intermediate_joint_pose(self) -> None:
        """Move to the IFRA-tested pose used as a reliable IK seed."""
        goal = Move.Goal()
        goal.action = "MoveJ"
        goal.speed = 0.50
        goal.movej.joint1 = 90.0
        goal.movej.joint2 = -90.0
        goal.movej.joint3 = 90.0
        goal.movej.joint4 = -90.0
        goal.movej.joint5 = -90.0
        goal.movej.joint6 = 0.0
        self.get_logger().info("MoveJ: moving to the verified intermediate pose")
        handle = self._wait(
            self.gripper_client.send_goal_async(goal), "send MoveJ goal"
        )
        if not handle.accepted:
            raise RuntimeError("MoveJ goal was rejected")
        wrapped_result = self._wait(
            handle.get_result_async(), "execute MoveJ", timeout=60.0
        )
        message = wrapped_result.result.result
        if "SUCCESS" not in message:
            raise RuntimeError(f"MoveJ failed: {message}")
        self.get_logger().info(message)

    def set_attachment(self, attach: bool) -> None:
        service_type = AttachLink if attach else DetachLink
        request = service_type.Request()
        request.model1_name = ROBOT_MODEL
        request.link1_name = GRIPPER_LINK
        request.model2_name = self.object_model
        request.link2_name = OBJECT_LINK
        client = self.attach_client if attach else self.detach_client
        operation = "attach" if attach else "detach"
        # Gazebo runs under x86 emulation on this Windows setup and can take
        # longer to process DETACHLINK while the arm is settling at the pad.
        # Allow that service call to complete instead of reporting a false
        # failure after the cube has already been released visually.
        timeout = 30.0 if not attach else 15.0
        response = self._wait(client.call_async(request), operation, timeout=timeout)
        if not response.success:
            raise RuntimeError(f"Could not {operation} cube: {response.message}")
        self.get_logger().info(response.message)

    def normalize_grasp_pose(self) -> None:
        """Level and centre the cube immediately before attaching it.

        Gazebo's emulated physics can give a light cube a small roll/pitch
        impulse when the fingers close.  The link-attacher then preserves that
        tilted pose.  Resetting the body pose at the grasp instant makes the
        deterministic grasp visibly horizontal and centred; the separate
        grasp_center link provides the tool-facing attachment frame.
        """
        cube_x, cube_y = self.grasp_xy
        self.normalize_model_pose(
            # Keep the cube's table position unchanged during approach.  The
            # body is already world-aligned; only the dynamic pose is reset.
            body_x=cube_x,
            body_y=cube_y,
            body_z=GRASP_BODY_Z,
            operation="Grasp aligned",
        )

    def read_model_pose(self) -> tuple[float, float, float, float, float, float]:
        """Read the current Gazebo model pose.

        The cubes are dynamic bodies. Under the Windows/qemu Gazebo setup a
        light cube can move while the robot is approaching, so the original
        spawn coordinate is not always the actual grasp coordinate.
        """
        try:
            result = subprocess.run(
                ["gz", "model", "-m", self.object_model, "-p"],
                check=True,
                capture_output=True,
                text=True,
                timeout=8.0,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not read {self.object_model} pose: {exc}"
            ) from exc

        values: list[float] = []
        for token in result.stdout.split():
            try:
                values.append(float(token))
            except ValueError:
                continue
        if len(values) < 6:
            raise RuntimeError(
                f"Could not parse {self.object_model} pose: {result.stdout!r}"
            )
        return tuple(values[:6])  # type: ignore[return-value]

    @staticmethod
    def quaternion_to_rpy(
        qx: float, qy: float, qz: float, qw: float
    ) -> tuple[float, float, float]:
        """Convert a unit quaternion to XYZ roll/pitch/yaw for diagnostics."""
        sinr_cosp = 2.0 * (qw * qx + qy * qz)
        cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
        roll = math.atan2(sinr_cosp, cosr_cosp)

        sinp = 2.0 * (qw * qy - qz * qx)
        sinp = max(-1.0, min(1.0, sinp))
        pitch = math.asin(sinp)

        siny_cosp = 2.0 * (qw * qz + qx * qy)
        cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        return roll, pitch, yaw

    def read_ee_pose(self, timeout: float = 1.5) -> Robpose | None:
        """Return the latest complete /Robpose message, if it is available."""
        deadline = time.monotonic() + timeout
        while self._ee_pose is None and time.monotonic() < deadline and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.05)
        if self._ee_pose is None:
            self.get_logger().warning(
                "/Robpose is not available; using the configured Cartesian target"
            )
            return None
        return self._ee_pose

    def compensate_ee_xy_offset(self) -> None:
        """Correct Robmove targets for the configured end-effector frame.

        The Robmove action reports a pose in the MoveIt end-effector frame,
        while LinkAttacher uses the Gazebo ``EE_robotiq_2f85`` link.  Their
        fixed transform is significant in this workcell.  Measuring the
        actual pose after the overhead PTP move lets the approach, lift and
        place targets use the same physical fingertip centre.
        """
        ee_pose = self.read_ee_pose()
        if ee_pose is None:
            return
        dx = self.grasp_xy[0] - ee_pose.x
        dy = self.grasp_xy[1] - ee_pose.y
        ee_roll, ee_pitch, ee_yaw = self.quaternion_to_rpy(
            ee_pose.qx, ee_pose.qy, ee_pose.qz, ee_pose.qw
        )
        self.get_logger().info(
            "EE pose after PTP: "
            f"xyz=({ee_pose.x:.3f}, {ee_pose.y:.3f}, {ee_pose.z:.3f}), "
            f"rpy=({ee_roll:.3f}, {ee_pitch:.3f}, {ee_yaw:.3f})"
        )
        if max(abs(dx), abs(dy)) < 0.005:
            self.get_logger().info(
                f"EE frame aligned: ({ee_pose.x:.3f}, {ee_pose.y:.3f})"
            )
            return

        self.get_logger().warning(
            "Applying EE frame correction: "
            f"reported=({ee_pose.x:.3f}, {ee_pose.y:.3f}), "
            f"cube=({self.grasp_xy[0]:.3f}, {self.grasp_xy[1]:.3f}), "
            f"offset=({dx:+.3f}, {dy:+.3f})"
        )
        self.pick_above = Target(
            self.pick_above.x + dx, self.pick_above.y + dy, self.pick_above.z
        )
        self.pick = Target(self.pick.x + dx, self.pick.y + dy, self.pick.z)
        self.place_above = Target(
            self.place_above.x + dx, self.place_above.y + dy, self.place_above.z
        )
        self.place = Target(self.place.x + dx, self.place.y + dy, self.place.z)

    def refresh_grasp_target(self) -> None:
        """Align the grasp target to the cube's actual current position."""
        cube_x, cube_y, *_ = self.read_model_pose()
        self.grasp_xy = (cube_x, cube_y)
        self.pick_above = Target(cube_x, cube_y, 0.72)
        self.pick = Target(cube_x, cube_y, EE_GRASP_Z)
        self.normalize_model_pose(
            body_x=cube_x,
            body_y=cube_y,
            body_z=GRASP_BODY_Z,
            operation="Approach aligned",
        )
        self.get_logger().info(
            f"Approach target refreshed: {self.object_model} -> "
            f"({cube_x:.3f}, {cube_y:.3f})"
        )

    def normalize_model_pose(
        self,
        *,
        body_x: float,
        body_y: float,
        body_z: float,
        operation: str,
    ) -> None:
        """Set the level cube body pose before grasp or after release.

        Explicitly restoring the body pose at grasp and release removes the
        small translational and rotational error that otherwise accumulates
        under emulated ODE.  While attached, the body is not teleported: the
        fixed joint follows the non-rendered grasp_center link instead.
        """
        try:
            subprocess.run(
                [
                    "gz", "model", "-m", self.object_model,
                    "-x", f"{body_x:.4f}",
                    "-y", f"{body_y:.4f}",
                    "-z", f"{body_z:.4f}",
                    "-R", f"{GRASP_BODY_RPY[0]:.6f}",
                    "-P", f"{GRASP_BODY_RPY[1]:.6f}",
                    "-Y", f"{GRASP_BODY_RPY[2]:.6f}",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=8.0,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not normalize {self.object_model}: {exc}"
            )
        self.get_logger().info(
            f"{operation}: {self.color}_cube level and centered"
        )

    def verify_grasp_pose(self) -> None:
        """Refuse to lift unless the attached cube is level and centered."""
        x, y, z, roll, pitch, yaw = self.read_model_pose()
        expected_x, expected_y = self.grasp_xy
        position_error = max(
            abs(x - expected_x),
            abs(y - expected_y),
            abs(z - GRASP_BODY_Z),
        )
        level_error = max(abs(roll), abs(pitch))
        if (
            position_error > GRASP_POSITION_TOLERANCE
            or level_error > GRASP_LEVEL_TOLERANCE
        ):
            self.get_logger().error(
                "Grasp verification failed: "
                f"pose=({x:.3f}, {y:.3f}, {z:.3f}, "
                f"roll={roll:.3f}, pitch={pitch:.3f}, yaw={yaw:.3f}), "
                f"position_error={position_error:.3f}, "
                f"level_error={level_error:.3f}"
            )
            try:
                self.set_attachment(False)
            finally:
                self.move_gripper(0.0)
            raise RuntimeError(
                "Grasp verification failed; cube was not lifted because it "
                "was not level and centered between the fingertips"
            )
        self.get_logger().info(
            "Grasp verified: cube level and centered before lift "
            f"(roll={roll:.3f}, pitch={pitch:.3f}, yaw={yaw:.3f})"
        )

    def replace_with_placed_cube(self, body_x: float, body_y: float) -> None:
        """Leave a stable, full-size static visual after the dynamic release.

        The moving cube uses a non-rendered grasp anchor and is intentionally
        collisionless for the approach.  After detaching, Gazebo can continue
        integrating that multi-link dynamic model and make it sink or vanish.
        Spawn an identical static cube at the verified pad pose, then remove
        the released dynamic instance.  This keeps the recorded result stable
        without changing the grasp/lift sequence.
        """
        placed_name = f"{self.object_model}_placed"
        if not self.spawn_client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError("/spawn_entity is not available for placement")
        if not self.delete_client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError("/delete_entity is not available for placement")

        delete_request = DeleteEntity.Request()
        delete_request.name = placed_name
        delete_future = self.delete_client.call_async(delete_request)
        rclpy.spin_until_future_complete(self, delete_future, timeout_sec=3.0)

        sdf = box_sdf(
            placed_name,
            (0.06, 0.06, 0.06),
            CUBE_COLORS[self.color],
            static=True,
            gravity=False,
            collision_enabled=False,
        )
        spawn_request = SpawnEntity.Request()
        spawn_request.name = placed_name
        spawn_request.xml = sdf
        spawn_request.robot_namespace = ""
        spawn_request.reference_frame = "world"
        spawn_request.initial_pose = Pose()
        spawn_request.initial_pose.position.x = body_x
        spawn_request.initial_pose.position.y = body_y
        spawn_request.initial_pose.position.z = PLACE_BODY_Z
        spawn_request.initial_pose.orientation.w = 1.0
        spawn_future = self.spawn_client.call_async(spawn_request)
        rclpy.spin_until_future_complete(self, spawn_future, timeout_sec=10.0)
        result = spawn_future.result()
        if result is None or not result.success:
            message = "timed out" if result is None else result.status_message
            raise RuntimeError(f"Could not spawn placed cube: {message}")

        delete_original = DeleteEntity.Request()
        delete_original.name = self.object_model
        delete_original_future = self.delete_client.call_async(delete_original)
        rclpy.spin_until_future_complete(
            self, delete_original_future, timeout_sec=5.0
        )
        self.get_logger().info(
            f"Placed static cube: {placed_name} -> "
            f"({body_x:.3f}, {body_y:.3f}, {PLACE_BODY_Z:.3f})"
        )

    def align_attached_cube_at_place(self) -> None:
        """Center the still-attached cube before opening the gripper."""
        target_x, target_y = PLACE_TARGETS[self.destination]
        x, y, z, roll, pitch, yaw = self.read_model_pose()
        dx = target_x - x
        dy = target_y - y
        self.get_logger().info(
            "Pre-release cube pose: "
            f"({x:.3f}, {y:.3f}, {z:.3f}, rpy=({roll:.3f}, "
            f"{pitch:.3f}, {yaw:.3f}), "
            f"target_error=({dx:+.3f}, {dy:+.3f})"
        )
        if max(abs(dx), abs(dy)) <= 0.005:
            return
        self.get_logger().warning(
            "Correcting attached cube placement by "
            f"({dx:+.3f}, {dy:+.3f}) m before release"
        )
        self.move_robot(
            "LIN",
            Target(self.place.x + dx, self.place.y + dy, self.place.z),
            0.10,
        )

    def execute(self) -> None:
        self.wait_until_ready()
        self.get_logger().info(
            f"Starting: {self.color} cube -> {self.destination} sorting zone"
        )

        self.move_gripper(0.0)
        self.move_intermediate_joint_pose()
        # Force the next correction to use a pose published after the PTP
        # move, rather than a stale pose from the intermediate joint move.
        self._ee_pose = None
        self.move_robot("PTP", self.pick_above, 0.50)
        # The cube is dynamic and can shift while the arm is travelling.
        # Re-read and pin its current pose before the final vertical descent,
        # so the fingertips approach the actual cube centre.
        self.refresh_grasp_target()
        # The motion action and Gazebo attachment use different end-effector
        # frames in this workcell.  Correct all Cartesian targets before the
        # final descent so the attachment does not pull the cube sideways.
        self.compensate_ee_xy_offset()
        self.move_robot("LIN", self.pick, 0.20)
        # Level the cube before the fingers close so the two fingertips meet
        # opposing, parallel side faces rather than catching a corner after
        # a small physics-induced roll.
        self.normalize_grasp_pose()
        self.move_gripper(GRASP_CLOSE_PERCENT)
        before_attach = self.read_model_pose()
        self.get_logger().info(
            "Pre-attach cube pose: "
            f"({before_attach[0]:.3f}, {before_attach[1]:.3f}, "
            f"{before_attach[2]:.3f}, rpy=({before_attach[3]:.3f}, "
            f"{before_attach[4]:.3f}, {before_attach[5]:.3f})"
        )
        self.set_attachment(True)
        self.verify_grasp_pose()
        self.get_logger().info(
            "Grasp hold: cube secured between the fingertips; body remains level"
        )
        time.sleep(GRASP_HOLD_SECONDS)

        self.move_robot("LIN", self.pick_above, 0.20)
        # Keep the end-effector orientation fixed while carrying the cube.
        # A joint-space PTP transfer can visibly rotate the gripper between
        # endpoints even though the final pose is correct.
        self.move_robot("LIN", self.place_above, 0.30)
        self.move_robot("LIN", self.place, 0.20)
        self.align_attached_cube_at_place()

        # Open while the tool is still at the pad so the release is visible;
        # then remove the deterministic Gazebo attachment and retreat.  This
        # prevents the retreat motion from looking like a second lift/drop.
        self.move_gripper(0.0)
        time.sleep(0.5)
        self.set_attachment(False)
        target_x, target_y = PLACE_TARGETS[self.destination]
        self.replace_with_placed_cube(target_x, target_y)
        self.get_logger().info("RELEASED: gripper opened at the destination pad")
        self.move_robot("LIN", self.place_above, 0.20)
        time.sleep(0.5)

        self.get_logger().info(
            f"SUCCESS: {self.color} cube was moved to the {self.destination} zone."
        )


def main(args=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--color", required=True, choices=sorted(CUBE_POSES))
    parser.add_argument("--destination", required=True, choices=sorted(ZONE_POSES))
    parsed = parser.parse_args(args)

    rclpy.init(args=args)
    node = PickPlace(parsed.color, parsed.destination)
    try:
        node.execute()
    except Exception as exc:
        node.get_logger().error(str(exc))
        raise
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
