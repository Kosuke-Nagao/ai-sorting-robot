"""Parameterized pick-and-place demo for the sorting workcell."""

import argparse
from dataclasses import dataclass
import os
import subprocess
import time

import rclpy
from linkattacher_msgs.srv import AttachLink, DetachLink
from rclpy.action import ActionClient
from rclpy.node import Node
from ros2srrc_data.action import Move, Robmove

from .command_schema import CUBE_POSES, ZONE_POSES, SortCommand


@dataclass(frozen=True)
class Target:
    x: float
    y: float
    z: float


# Verified reachable UR3 pose for the supplied MoveIt configuration.
DOWN_QUATERNION = (-0.5, 0.5, 0.5, 0.5)

ROBOT_MODEL = "ur3"
# Use the end-effector's native Gazebo link for the attachment.  Adding a
# tiny auxiliary link into the Robotiq model made the Gazebo constraint solver
# unstable under x86 emulation.  The cube model itself has its geometry offset
# by 14 mm (see spawn_workcell.py), so attaching its *link origin* here still
# places the visible cube at the midpoint of the fingertips.
GRIPPER_LINK = "EE_robotiq_2f85"
OBJECT_LINK = "body"
# This pair is the verified collision-free height for this UR3 workcell.
# Lower targets make the visual fingers look closer to the table but can
# destabilize the simulated gripper and interrupt the lift under emulation.
EE_GRASP_Z = 0.559
EE_PLACE_Z = 0.562

# The simulated cubes are 60 mm wide.  The 40% setting leaves a realistic gap
# around the cube while the deterministic link attachment carries it.
GRASP_CLOSE_PERCENT = 40.0
# Briefly hold after the attachment so the grasp is clear in the recording.
GRASP_HOLD_SECONDS = float(os.environ.get("AI_SORTING_GRASP_HOLD_SECONDS", "3.0"))
# With the inverse geometry rotation, the cube body origin sits 23.5 mm below
# its visible centre and carries the same downward orientation as the EE.
GRASP_BODY_Z = 0.5215
GRASP_BODY_RPY = (-1.57079632679, 1.57079632679, 0.0)
# Measured transform from the native EE link origin to the visible cube
# centre after the fixed link attachment.  Apply only after attachment; the
# cube remains on the table at its normal pose during approach.
ATTACHED_GRASP_OFFSET = (0.008, 0.012, 0.037)

# Placement targets in the Gazebo world frame.  The link-attacher is used for
# deterministic simulation grasping; the pad collision/support geometry keeps
# the released cube on the work surface.
PLACE_TARGETS = {
    "left": (0.22, 0.25),
    "right": (0.22, -0.25),
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
        tilted pose.  Resetting the pose at the grasp instant makes the
        deterministic grasp visibly horizontal and centred.
        """
        cube_x, cube_y = self.grasp_xy
        self.normalize_model_pose(
            # Keep the cube's table position unchanged during approach.  The
            # horizontal/vertical visual correction is applied only after the
            # link attachment, when the native EE link frame is active.
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
        """Set the cube body pose while it is not being physically simulated.

        The link-attacher preserves the link-to-link transform, while the
        visible cube is offset inside its body link.  Explicitly restoring
        the body pose at grasp and release removes the small translational
        and rotational error that otherwise accumulates under emulated ODE.
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

    def execute(self) -> None:
        self.wait_until_ready()
        self.get_logger().info(
            f"Starting: {self.color} cube -> {self.destination} sorting zone"
        )

        self.move_gripper(0.0)
        self.move_intermediate_joint_pose()
        self.move_robot("PTP", self.pick_above, 0.50)
        # The cube is dynamic and can shift while the arm is travelling.
        # Re-read and pin its current pose before the final vertical descent,
        # so the fingertips approach the actual cube centre.
        self.refresh_grasp_target()
        self.move_robot("LIN", self.pick, 0.20)
        # Level the cube before the fingers close so the two fingertips meet
        # opposing, parallel side faces rather than catching a corner after
        # a small physics-induced roll.
        self.normalize_grasp_pose()
        self.move_gripper(GRASP_CLOSE_PERCENT)
        self.set_attachment(True)
        self.normalize_model_pose(
            body_x=self.grasp_xy[0] + ATTACHED_GRASP_OFFSET[0],
            body_y=self.grasp_xy[1] + ATTACHED_GRASP_OFFSET[1],
            body_z=GRASP_BODY_Z + ATTACHED_GRASP_OFFSET[2],
            operation="Attached grasp centered",
        )
        self.get_logger().info(
            "Grasp hold: cube secured between the fingertips"
        )
        time.sleep(GRASP_HOLD_SECONDS)

        self.move_robot("LIN", self.pick_above, 0.20)
        # Keep the end-effector orientation fixed while carrying the cube.
        # A joint-space PTP transfer can visibly rotate the gripper between
        # endpoints even though the final pose is correct.
        self.move_robot("LIN", self.place_above, 0.30)
        self.move_robot("LIN", self.place, 0.20)

        # Open while the tool is still at the pad so the release is visible;
        # then remove the deterministic Gazebo attachment and retreat.  This
        # prevents the retreat motion from looking like a second lift/drop.
        self.move_gripper(0.0)
        time.sleep(0.5)
        self.set_attachment(False)
        target_x, target_y = PLACE_TARGETS[self.destination]
        self.normalize_model_pose(
            body_x=target_x,
            body_y=target_y,
            body_z=GRASP_BODY_Z,
            operation="Placement aligned",
        )
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
