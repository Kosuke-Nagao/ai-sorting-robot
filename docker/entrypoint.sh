#!/usr/bin/env bash
set -e

source /opt/ros/humble/setup.bash

if [ -f /opt/robot_ws/install/setup.bash ]; then
    source /opt/robot_ws/install/setup.bash
fi

# Build the small course project from the bind-mounted source tree.  This keeps
# source edits visible without rebuilding the large simulator image.
cd /workspace
colcon build \
    --packages-select ai_sorting_robot \
    --symlink-install \
    >/tmp/app_build.log 2>&1
source /workspace/install/setup.bash

# The native end-effector link is used for Gazebo attachments.  The workcell
# adds a lightweight grasp_center link to each cube; keeping that helper on the
# cube (rather than injecting a link into the robot model) avoids disturbing
# the controller's Robotiq joint tree.

export DISPLAY="${DISPLAY:-:1}"
export QT_X11_NO_MITSHM=1
export LIBGL_ALWAYS_SOFTWARE=1

mkdir -p /tmp/.X11-unix
rm -f /tmp/.X1-lock
rm -f /tmp/.X11-unix/X1

Xvfb "${DISPLAY}" \
    -screen 0 1280x720x24 \
    -ac \
    +extension GLX \
    +render \
    -noreset \
    >/tmp/xvfb.log 2>&1 &

for attempt in $(seq 1 30); do
    if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
    echo "Xvfb failed to start."
    cat /tmp/xvfb.log
    exit 1
fi

dbus-launch openbox-session >/tmp/openbox.log 2>&1 &

x11vnc \
    -display "${DISPLAY}" \
    -forever \
    -shared \
    -nopw \
    -xkb \
    -rfbport 5900 \
    >/tmp/x11vnc.log 2>&1 &

websockify \
    --web=/usr/share/novnc/ \
    6080 \
    localhost:5900 \
    >/tmp/novnc.log 2>&1 &

sleep 2

ros2 launch ros2srrc_launch moveit2.launch.py \
    package:=ros2srrc_ur3 \
    config:=ur3_2 \
    >/tmp/robot_launch.log 2>&1 &

# The node waits for Gazebo's spawn service, then creates the complete scene.
ros2 run ai_sorting_robot spawn_workcell \
    >/tmp/workcell.log 2>&1 &

echo "=============================================="
echo "UR3 + Robotiq 2F-85 simulation is starting."
echo "Open: http://localhost:6080/vnc.html"
echo "=============================================="

exec tail -f /dev/null
