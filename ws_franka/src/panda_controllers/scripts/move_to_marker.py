#!/usr/bin/env python3


import sys

import rospy

import moveit_commander

import tf

import tf2_ros

from geometry_msgs.msg import Pose

from ar_track_alvar_msgs.msg import AlvarMarkers


#declare global variables

world_frame = "panda_link0"

vel_scaling =  .3

home_position = [.4, .0, .3]

home_orientation = [.1, .0, .0, .0]

marker_pose = None


#convert marker from camera frame to robot's base frame

def transform_pose(pose, target_frame):

    if tf_listener.canTransform(target_frame, pose.header.frame_id, rospy.Time(0)):

        #transform pose

        transform = tf_listener.transformPose(target_frame, pose)


        # try:

        #     tran = tf2_ros.Buffer.lookup_transform("world", "ar_maker_1", rospy.Time(), rospy.Duration(10))


        return transform.pose


#callback function to receive marker messages

def marker_cb(msg):

    global marker_pose

    if len(msg.markers) == 0:

        return

    marker = msg.markers[0]

    marker.pose.header.frame_id = marker.header.frame_id

    marker_pose = transform_pose(marker.pose, "panda_link0")


#set Pose message through lists

def set_pose(xyz = [0, 0, 0], q = [0, 0, 0, 1]):

    pose = Pose()

    pose.position.x = xyz[0]

    pose.position.y = xyz[1]

    pose.position.z = xyz[2]

    pose.orientation.x = q[0]

    pose.orientation.y = q[1]

    pose.orientation.z = q[2]

    pose.orientation.w = q[3]

    return pose


#confirm if plan should be executed

def plan_accepted():

    return input("Do you want to execute the plan [y] or replan [n]? ") == "y"


#plan and execute to given pose; If plan is not confirmed plan again

def plan_and_execute(group, pose):

    group.set_pose_target(pose)

    if plan_accepted():

        group.go(wait=True)

        group.stop()

        group.clear_pose_targets()

    else:

        exit()


#main function of application

def main():

    #initialize moveit

    moveit_commander.roscpp_initialize(sys.argv)


    # Your Code For Task 1 #

    group = moveit_commander.MoveGroupCommander("panda_arm")

    group.set_max_velocity_scaling_factor(vel_scaling)



    #while loop to move the robot to the found AR marker

    while not rospy.is_shutdown():

        plan_and_execute(group, set_pose(home_position, home_orientation))

        if marker_pose:

            marker = [marker_pose.position.x, marker_pose.position.y, home_position[2]]

            plan_and_execute(group, set_pose(marker))

        else:

            rospy.logwarn("No marker detected.")


if __name__ == '__main__':

    rospy.init_node('move_to_marker', anonymous=True)

    tf_listener = tf.TransformListener()


    # Your Code for Task 2 #

    rospy.Subscriber("/ar_pose_marker", AlvarMarkers, marker_cb)


    main()