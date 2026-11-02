FROM osrf/ros:humble-desktop-full-jammy

SHELL ["/bin/bash", "-lc"]

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=humble
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV DISPLAY=:1
ENV QT_X11_NO_MITSHM=1
ENV LIBGL_ALWAYS_SOFTWARE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    curl \
    wget \
    nano \
    python3-pip \
    python3-colcon-common-extensions \
    python3-vcstool \
    python3-rosdep \
    ros-humble-moveit \
    ros-humble-xacro \
    ros-humble-gripper-controllers \
    ros-humble-gazebo-ros-pkgs \
    ros-humble-ros2-control \
    ros-humble-ros2-controllers \
    ros-humble-rmw-cyclonedds-cpp \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    openbox \
    x11-utils \
    mesa-utils \
    dbus-x11 \
    && rm -rf /var/lib/apt/lists/*

COPY dependencies.repos /tmp/dependencies.repos

RUN mkdir -p /opt/robot_ws/src \
    && vcs import /opt/robot_ws/src < /tmp/dependencies.repos

RUN cp \
    /opt/robot_ws/src/ros2_SimRealRobotControl/include/move_group_interface_improved.h \
    /opt/ros/humble/include/moveit/move_group_interface/

# This project uses UR3 only, so remove the unused ABB dependency.
RUN sed -i \
      -e '/find_package(abb_robot_msgs REQUIRED)/d' \
      -e '/^[[:space:]]*abb_robot_msgs[[:space:]]*$/d' \
      /opt/robot_ws/src/ros2_SimRealRobotControl/ros2srrc_execution/CMakeLists.txt \
    && sed -i \
      '/<depend>abb_robot_msgs<\/depend>/d' \
      /opt/robot_ws/src/ros2_SimRealRobotControl/ros2srrc_execution/package.xml

# The upstream link-attacher creates a zero-limit revolute joint.  Under
# Gazebo/ODE this can still rotate slightly, which makes an attached cube
# appear to twist or slide out of the fingertips.  Build it as a fixed joint
# so the grasp orientation remains rigid during lift and transfer.
RUN sed -i 's/CreateJoint(JointName, "revolute"/CreateJoint(JointName, "fixed"/' \
    /opt/robot_ws/src/IFRA_LinkAttacher/ros2_LinkAttacher/src/gazebo_link_attacher.cpp

RUN source /opt/ros/humble/setup.bash \
    && rosdep update \
    && apt-get update \
    && rosdep install \
       --from-paths /opt/robot_ws/src \
       --ignore-src \
       --rosdistro humble \
       -r \
       -y \
    && rm -rf /var/lib/apt/lists/*

RUN source /opt/ros/humble/setup.bash \
    && cd /opt/robot_ws \
    && colcon build \
       --symlink-install \
       --parallel-workers 2 \
       --packages-up-to \
         ros2srrc_execution \
         ros2srrc_ur3 \
         ros2srrc_launch \
         ros2srrc_endeffectors \
         ros2srrc_gazebo \
         ros2srrc_moveit \
       --cmake-args -DCMAKE_BUILD_TYPE=Release

RUN source /opt/ros/humble/setup.bash \
    && source /opt/robot_ws/install/setup.bash \
    && cd /opt/robot_ws \
    && colcon build \
       --symlink-install \
       --parallel-workers 2 \
       --packages-select \
         ros2srrc_robots \
         gazebo_ros2_control \
       --cmake-args -DCMAKE_BUILD_TYPE=Release

# Keep the full Robotiq mechanics and collision geometry, but hide only the
# inner linkage visuals in both source and install spaces.  This preserves a
# continuous pair of visible fingers without changing the controllers.
COPY docker/simplify_robotiq_visuals.py /tmp/simplify_robotiq_visuals.py
RUN python3 /tmp/simplify_robotiq_visuals.py \
    && rm -f /tmp/simplify_robotiq_visuals.py

# Resolve gripper configuration through the ROS package index in Docker.
RUN sed -i \
    "s#PATH = os.path.join(os.path.expanduser('~'), 'dev_ws', 'src', 'ros2_SimRealRobotControl', 'ros2srrc_endeffectors', EEName, 'config')#PATH = os.path.join(get_package_share_directory('ros2srrc_endeffectors'), EEName, 'config')#g" \
    /opt/robot_ws/src/ros2_SimRealRobotControl/ros2srrc_launch/moveit2/moveit2.launch.py \
    && ! grep -F "'dev_ws'" /opt/robot_ws/src/ros2_SimRealRobotControl/ros2srrc_launch/moveit2/moveit2.launch.py

# Allow the small joint-state lag caused by attaching a simulated object.
# Large discrepancies indicate a physical collision and must not be hidden.
RUN sed -i 's/trajectory_execution.allowed_start_tolerance": 0.01/trajectory_execution.allowed_start_tolerance": 0.05/' \
    /opt/robot_ws/src/ros2_SimRealRobotControl/ros2srrc_launch/moveit2/moveit2.launch.py

# RViz duplicates the 3D rendering already provided by Gazebo and is very slow
# under x86_64 emulation on an ARM64 Windows host.  MoveIt continues to run.
RUN sed -i '/^[[:space:]]*rviz_node_full,$/d' \
    /opt/robot_ws/src/ros2_SimRealRobotControl/ros2srrc_launch/moveit2/moveit2.launch.py

# The supplied controllers update at 250 Hz.  Matching Gazebo's physics rate
# avoids spending CPU on the default 1000 physics steps per simulated second.
RUN sed -i '/<gravity>0 0 -9.8<\/gravity>/a\    <physics name="fast_physics" type="ode"><max_step_size>0.004</max_step_size><real_time_update_rate>250</real_time_update_rate><real_time_factor>1.0</real_time_factor></physics>' \
    /opt/robot_ws/src/ros2_SimRealRobotControl/ros2srrc_gazebo/worlds/ros2srrc_gazebo.world

# Start Gazebo with the original, wider diagonal view of the workcell.
RUN sed -i '/<physics name="fast_physics"/a\    <gui fullscreen="false"><camera name="user_camera"><pose>1.45 -1.45 1.45 0 0.35 2.12</pose></camera></gui>' \
    /opt/robot_ws/src/ros2_SimRealRobotControl/ros2srrc_gazebo/worlds/ros2srrc_gazebo.world

# KDL needs a little more search time on the emulated ARM64 environment.
RUN sed -i 's/kinematics_solver_timeout: 0.005/kinematics_solver_timeout: 0.100/' \
    /opt/robot_ws/src/ros2_SimRealRobotControl/ros2srrc_robots/ur3/config/kinematics.yaml

WORKDIR /workspace

COPY docker/entrypoint.sh /usr/local/bin/start-simulator.sh

RUN sed -i 's/\r$//' /usr/local/bin/start-simulator.sh \
    && chmod +x /usr/local/bin/start-simulator.sh

EXPOSE 6080

CMD ["/usr/local/bin/start-simulator.sh"]
