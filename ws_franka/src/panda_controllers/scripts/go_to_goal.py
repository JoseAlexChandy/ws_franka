#!/usr/bin/env python3


import sys

from tokenize import group

import rospy

import moveit_commander

import tf

import tf2_ros

from geometry_msgs.msg import Pose



def main():

    moveit_commander.roscpp_initialize(sys.argv)


    group = moveit_commander.MoveGroupCommander("bob_arm")

    group.set_max_velocity_scaling_factor(1.0)

    group.set_max_acceleration_scaling_factor(1.0)

    group.set_planning_pipeline_id('pilz_industrial_motion_planner')

    group.set_planner_id('PTP')



    target = Pose()

    target.position.x = 0.4

    target.position.y = 0.2

    target.position.z = 0.5

    target.orientation.x = 1

    target.orientation.y = 0

    target.orientation.z = 0

    target.orientation.w = 0


    target1 = Pose()

    target1.position.x = 0.4

    target1.position.y = - 0.2

    target1.position.z = 0.5

    target1.orientation.x = 1

    target1.orientation.y = 0

    target1.orientation.z = 0

    target1.orientation.w = 0


    while not rospy.is_shutdown():

        group.set_pose_target(target, end_effector_link="bob_link8")

        group.go()

        group.stop()

        group.clear_pose_targets()


        group.set_pose_target(target1, end_effector_link="bob_link8")

        group.go()

        group.stop()

        group.clear_pose_targets()



if __name__ == '__main__':

    rospy.init_node('go_to_goal', anonymous=True)


    main()