#!/usr/bin/env python

import sys
import os
import numpy as np
import cv2
from scipy.spatial.transform import Rotation as R
import pyrealsense2 as rs
import rospy

from moveit_commander import MoveGroupCommander, RobotCommander, PlanningSceneInterface
from moveit_commander.robot_trajectory import RobotTrajectory
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Header
from geometry_msgs.msg import PoseStamped
from cv_bridge import CvBridge

from rcc_msgs.msg import NormPixelPnP, Observation, Reset, WorldPnP
from utils import *

from active_gripper_control import ActiveGripperControl
from camera_image_retriever import CameraImageRetriever
from panda_robot_moveit import PandaRobotMoveit  # Adapted for Panda robot

class QuasiStaticPickAndPlace:

    def __init__(self, config, mock=False, estimate_pick_depth=False):
        rospy.init_node('quasi_static_pick_and_place', anonymous=True)
        
        self.config = config
        self.is_mock = mock
        self.estimate_pick_depth = estimate_pick_depth
        self.bridge = CvBridge()

        self._initialize_communication()
        self._initialize_robot()
        self._initialize_camera()

        rospy.loginfo('Finished Initialization, ready for experiments')

    def _initialize_communication(self):
        self.pub = rospy.Publisher('/observation', Observation, queue_size=10)
        if self.is_mock:
            self.mock_pnp_pub = rospy.Publisher('/pnp', NormPixelPnP, queue_size=10)

        rospy.Subscriber('/norm_pixel_pnp', NormPixelPnP, self.pnp_callback if not self.is_mock else self.mock_pnp_callback)
        rospy.Subscriber('/world_pnp', WorldPnP, self.world_pnp_callback)
        rospy.Subscriber('/reset', Reset, self.reset_callback)
        self.rate = rospy.Rate(10)

    def pnp_callback(self, pnp):
        rospy.loginfo("Received pnp: %s", pnp.data)
        orien_degree = pnp.degree
        pnp = np.asarray(pnp.data)

        # Post Process, Convert form pixel space to base space
        pixel_pnp = self.norm2pixel_pnp(pnp)
        self.pixel_pick_and_place(pixel_pnp[:2], pixel_pnp[2:], pick_orien=orien_degree)
        self.go_home()
        self.publish_observation()

    def world_pnp_callback(self, pnp):
        rospy.loginfo("Received pnp: %s", pnp.data)
        pnp = np.asarray(pnp.data)

        base_pick = MyPos(pose=pnp[:3], orien=self.eff_default_orien)
        base_place = MyPos(pose=pnp[3:], orien=self.eff_default_orien)
        base_pick.pose[2] += self.g2e_offset
        base_place.pose[2] += self.g2e_offset
        self.execute_pick_and_place(base_pick, base_place)

    def reset_callback(self, reset):
        rospy.loginfo("Received reset msg")
        self.go_home()
        self.publish_observation()

    def pixel_pick_and_place(self, pick_pixel, place_pixel, pick_orien=0.0):
        estimated_depth = self.camera_height
        orien = self.fix_orien

        cur_orien_degree = quaternion_to_euler(self.fix_orien)
        cur_orien_degree[2] += pick_orien
        orien = euler_to_quaternion(cur_orien_degree)

        if self.estimate_pick_depth:
            depth_images = [self.camera.take_rgbd()[1] for _ in range(5)]
            for d in depth_images:
                if np.isnan(d).any():
                    rospy.logerr("There is nan input in depth images.")
            
            region_size = 5  # 5x5 pixel region
            x, y = int(pick_pixel[0]), int(pick_pixel[1])
            rospy.loginfo(f'pick point x {x} y {y}')
            
            depth_values = []
            for depth_image in depth_images:
                region = depth_image[y-region_size//2:y+region_size//2+1, x-region_size//2:x+region_size//2+1]
                rospy.loginfo(f"Regions to estimate {region}")
                depth_values.append(np.median(region))
            
            estimated_depth = min(np.median(depth_values) + 0.02, self.camera_height)
            rospy.loginfo(f"Estimated pick depth {estimated_depth}")
        
        rospy.loginfo(f"pixel2base pixel {pick_pixel} depth {estimated_depth} intrinsic {self.camera_intrinstic} camera pose {self.camera_pos}")
        base_pick = pixel2base([pick_pixel], self.camera_intrinstic, self.camera_pos, [estimated_depth])[0]
        base_pick = MyPos(pose=base_pick, orien=orien)
        
        base_place = pixel2base([place_pixel], self.camera_intrinstic, self.camera_pos, self.camera_height)[0]
        base_place = MyPos(pose=base_place, orien=orien)
        rospy.loginfo(f"Calculated base pick {base_pick}, base place {base_place}")

        base_pick.pose[2] = max(0, base_pick.pose[2]) + self.g2e_offset
        base_place.pose[2] += self.g2e_offset

        self.execute_pick_and_place(base_pick, base_place)

    def _initialize_gripper(self):
        self.gripper = ActiveGripperControl()
        self.g2e_offset = self.config.g2e_offset

    def _initialize_robot(self):
        self.robot_arm = PandaRobotMoveit()

        self.ready_joint_states = self.config.ready_joint_states.toDict()
        self.ready_pos = MyPos(
            pose=self.config.eff_ready_pose,
            orien=normalise_quaterion(self.config.eff_ready_orien)
        )
        self.home_joint_states = self.config.home_joint_states.toDict()
        self.fix_orien = normalise_quaterion(self.config.eff_ready_orien)

        self._initialize_gripper()

        self.pick_raise_offset = self.config.pick_raise_offset
        self.place_raise_offset = self.config.place_raise_offset

    def _initialize_camera(self):
        camera_orien = euler_to_quaternion(self.config.camera_orien)
        self.camera_pos = MyPos(
            pose=self.config.camera_pose,
            orien=normalise_quaterion(camera_orien)
        )
        self.camera_height = self.config.camera_pose[2]
        self.camera = CameraImageRetriever(self.camera_height)
        self.camera_intrinstic = self.camera.get_intrinsic()
        color, depth = self.take_cropped_rgbd()

    def go_home(self):
        rospy.loginfo('Going Home')
        self.gripper.open()
        self.robot_arm.go(joint_states=self.home_joint_states)
        rospy.loginfo('Home position reached !!!')

    def go_ready(self):
        rospy.loginfo('Going ready')
        self.robot_arm.go(joint_states=self.ready_joint_states)
        rospy.loginfo('Ready position reached !!!')

    def go_pose(self, pose, straight=False):
        self.robot_arm.go(pose=pose)
        
    def execute_pick_and_place(self, pick, place):
        rospy.loginfo('Starting Pick {} and Place {}'.format(pick.pose, place.pose))

        self.gripper.open()
        self.go_ready()

        rospy.loginfo('Going to Pick Position')
        pick_raise_pos = pick.pose + np.asarray([0, 0, self.pick_raise_offset])
        self.go_pose(MyPos(pose=pick_raise_pos, orien=pick.orien), straight=True)

        pick_pos = pick.pose.copy()
        self.go_pose(MyPos(pose=pick_pos, orien=pick.orien))
        self.gripper.grasp()

        self.go_pose(MyPos(pose=pick_raise_pos, orien=pick.orien))

        rospy.loginfo('Going to Place Position')
        current_pos = pick_raise_pos
        place_raise_pos = place.pose + np.asarray([0, 0, self.place_raise_offset])
        direction = place_raise_pos - current_pos
        distance = np.linalg.norm(direction)
        direction = direction / distance

        step_size = 0.2
        num_steps = int(distance / step_size)
        
        for step in range(num_steps):
            intermediate_pos = current_pos + direction * step_size * (step + 1)
            self.go_pose(MyPos(pose=intermediate_pos, orien=place.orien), straight=True)

        self.go_pose(MyPos(pose=place_raise_pos, orien=place.orien), straight=True)
        self.gripper.open()
        self.gripper.grasp()
        self.gripper.open()

    def take_cropped_rgbd(self):
        color_image, depth_image = self.camera.take_rgbd()
        save_color(color_image, filename='raw_color.png', directory="./tmp")
        save_depth(depth_image, filename='preprocessed_depth.png', directory="./tmp")

        cropped_color, annot_color = self._crop_image(color_image, annotation=True)
        cropped_depth = self._crop_image(depth_image)
        save_color(cropped_color, filename='cropped_color.png', directory="./tmp")
        save_color(annot_color, filename='annotated_color.png', directory="./tmp")
        save_depth(cropped_depth, filename='cropped_depth.png', directory="./tmp")
        return cropped_color, cropped_depth

    def publish_observation(self):
        obs = self.get_observation()
        self.publish(obs)

    def run(self):
        self.go_home()
        self.take_cropped_rgbd()
        if self.is_mock:
            self.mock_publish_pnp([0, 0, 0, 0])

        rospy.spin()

    def norm2pixel_pnp(self, pnp):
        pix_pnp = (pnp+1)/2 * self.resol
        pix_pnp[0] += self.start_x
        pix_pnp[2] += self.start_x
        pix_pnp[1] += self.start_y
        pix_pnp[3] += self.start_y
        rospy.loginfo('Pixel Pnp: %s', pix_pnp)
        return pix_pnp


if __name__ == '__main__':
    config_name = "panda_active_realsense_config"  # Replace with actual config for Panda
    config = load_config(config_name)

    qspnp = QuasiStaticPickAndPlace(config=config, mock=False)
    qspnp.run()

