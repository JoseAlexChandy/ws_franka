# I. Setup GPU machine

We assume `agent-arena` has been installed in the gpu machine.
```
. ./launch.sh

conda install -c conda-forge -c ros-noetic-cv-bridge ros-rospy ros-sensor-msgs

cd papers/franka_sim2real_ws

catkin_create_pkg custom_msgs std_msgs sensor_msgs message_generation message_runtime

catkin_make
```

Then, we need to move `sam_vit_h_4b8939.pth` under `franka_sim2real_ws/src` for creating masks.

# II. Setup Robot Machine

1. Install `libfranka`, `franka_ros` and `moveit` packages for ROS's `neotic` setup.
using following links
* https://panda-ros-workshop.readthedocs.io/en/latest/index.html
* https://moveit.github.io/moveit_tutorials/doc/getting_started/getting_started.html
* https://frankaemika.github.io/docs/index.html

2. Setup moving group using `moveit` setup wizard following https://moveit.github.io/moveit_tutorials/doc/getting_started/getting_started.html

3. Note that install `pip install empy==3.3.4`

4. Fix the force threshold issue by modifying `franka_control_node.yaml` file.

# III. Run `run.py` in GPU machine

Assume we are undert `agent-arena` directory

```
. ./launch.sh

cd papers/franka_sim2real_ws

source devel/setup.bash

cd src

export ROS_MASTER_URI=<master-url> # Currently http://172.22.3.6:11311
export ROS_IP=<ip-of-gpu-machine> # Currently 172.22.3.8

python run.py
```

# IV. Run `quasi_static_pick_and_place.py` in Robot Machine to control the robot.

1. Activate Franka Robot Arm in its FCI.

2. Open a terminal
```


export ROS_IP=<ip-of-robot-machine> # Currently172.22.3.6

```

3. Open four terminals run

```
# In all terminals
cd ~/ws_franka
source ~/ws_franka/devel/setup.sh
# In 1st terminal, run
roslaunch franka_control franka_control.launch robot_ip:=172.22.2.4 load_gripper:=true robot:=panda arm_id:=bob 

# In 2nd terminal, run
roslaunch real_panda_moveit ros_controllers.launch 

# In 3rd terminal, run
roslaunch real_panda_moveit move_group.launch 

# In 4th terminal, run
roscd panda_controllers/scripts 
python3 quasi_static_pick_and_place.py
```

4. If you run into robot reflex error, run following in a new terminal
```
rostopic pub -1 /franka_control/error_recovery/goal franka_msgs/ErrorRecoveryActionGoal "{}"
```

# V. Run `run_human_interface.py` in robot machine to provide human demonstrations.
1. Make sure instruction for IV is done. 
```
which are 
cd ~/ws_franka
source ~/ws_franka/devel/setup.sh
```
2. Open a terminal
```
roscd panda_controllers/scripts 
python3 run_human_interface.py
```


# VI. Experiments

1. Run out transporter agent

```
python run.py --agent transporter --task <task-name> --config <config-name>
```

2. Run `FabricFlowNet` for folding

```
python run.py --agent fabricflownet --task <task-name>
```




# Notes for Halid (please ignore)
4. test simulation

roslaunch franka_gazebo panda.launch
roslaunch franka_gazebo ar.launch
roslaunch movit_setup_panda move_group.launch
rosrun panda_controllers move_to_marker.py





2. It struggels to do corners-edge-inward-foldings:
    a. grasping multiple-layers while adjusting
    b. cannot produce effect policy for side-folding after corner folding.

3. We need to work on the depth image.

4. add fix position camera to record trials.

5. It struggles to do double-side folding:
    a. It produce small folding action, and the fabric flip backs to the initial state due to its stiffness
    b. the script cannot recover from bad folding states.
    c. It cannot tell the difference between flattened and one-side folding state.

6. We have similar issue for rectangular folding:

7. grasping orientation may orthogonal to the dragging direcion.

8. we need a side camera for recording.


TODO:

1. Work on depth image.
2. Work on the garpsing z.
3. Add auto-data collect in run.py. 
4. Train mask-depth planet-clothpick

4. Integrate Foldsformer.
5. Integrate FabricFlowNet.
6. Integrate VCD.



work space 39*39cm


25-06 Issues
1. aciton infernece is too slow
2. when the fabric becoms rectangular, the policy think it is flatten, and produce really samll action.
3. in small dragging motion, the robot jiggers with noises.
4. when the exposure too high, it is hard to the the edge of the fabric on its own surface.
5. the fabric sticks to the gripper at step 9.


27-06 Issues
1. cloth somes times attached to the gripper.
2. at the begginig of today, the gripper close completely. I fix it rebooting the robot and run the libfranka script.


It seems like I need to collect data from the real-world and train the depth version (probably).... cloth version can be imporatnt as well.

28-06 issues

1. Even human policy struggles to flatten large fabric.


