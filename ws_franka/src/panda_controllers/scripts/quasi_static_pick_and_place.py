#!/usr/bin/env python
import sys

import moveit_commander.move_group
import rospy
import moveit_commander
from collections import namedtuple
import pyrealsense2 as rs
import numpy as np
from scipy.spatial.transform import Rotation as R
from geometry_msgs.msg import Pose, PoseStamped
import cv2
from cv_bridge import CvBridge
from custom_msgs.msg import Observation, PnP, Reset
from std_msgs.msg import Header
from math import pi

import actionlib
import franka_gripper.msg

import rospy
import moveit_commander

MyPos = namedtuple('Pos', ['pose', 'orien'])


def camera2base(camera_pos, camera_orientation_quat, object_pos_cam):
    r = R.from_quat(camera_orientation_quat)
    rotation_matrix = r.as_matrix()
    object_pos_cam = np.array(object_pos_cam)
    object_pos_base = np.matmul(rotation_matrix, object_pos_cam) + np.array(camera_pos)
    return object_pos_base

def interpolate_positions(start_pos, target_pos, num_points=100):
    return np.linspace(start_pos, target_pos, num_points)

def bilinear_interpolation(x, y, x1, y1, x2, y2, q11, q21, q12, q22):
    """
    Perform bilinear interpolation.
    
    Parameters:
        x, y: Coordinates of the target point.
        x1, y1, x2, y2: Coordinates of the four corners.
        q11, q21, q12, q22: Values at the four corners.
        
    Returns:
        Interpolated value at the target point.
    """
    denom = (x2 - x1) * (y2 - y1)
    w11 = (x2 - x) * (y2 - y) / denom
    w21 = (x - x1) * (y2 - y) / denom
    w12 = (x2 - x) * (y - y1) / denom
    w22 = (x - x1) * (y - y1) / denom
    
    interpolated_value = q11 * w11 + q21 * w21 + q12 * w12 + q22 * w22
    return interpolated_value


def interpolate_image(height, width, corner_values):
    interpolated_image = np.zeros((height, width))
    for i in range(height):
        for j in range(width):
            x = i/height
            y = j/width
            x1 = int(x)
            y1 = int(y)
            x2 = x1 + 1
            y2 = y1 + 1
            q11 = corner_values[(x1, y1)]
            q21 = corner_values[(x2, y1)]
            q12 = corner_values[(x1, y2)]
            q22 = corner_values[(x2, y2)]
            interpolated_image[i, j] = \
                bilinear_interpolation(x, y, x1, y1, x2, y2, q11, q21, q12, q22)
    return interpolated_image

class QuasiStaticPickAndPlace:

    def __init__(self, mock=False):
        #rospy.init_node('quasi_static_pick_and_place', anonymous=True)
        rospy.init_node('panda_pnp', anonymous=True)
        # Initialize MoveIt commander

        

        self._initialize_robot()
       

        # Camera setup
        self._initialize_camera()

        # Set up Publisher
        self._intialize_communication(mock)

        # Parameters
        self.is_mock = mock
       
    

    def _intialize_communication(self, mock=False):
        
        self.pub = rospy.Publisher('/observation', Observation, queue_size=10)
        if mock:
            self.mock_pnp_pub = rospy.Publisher('/pnp', PnP, queue_size=10)
        
        self.bridge = CvBridge()
        rospy.Subscriber('/pnp', PnP, (self.mock_pnp_callback if mock else self.pnp_callback))
        rospy.Subscriber('/reset', Reset, self.reset_callback)
        #rospy.spin()
        self.rate = rospy.Rate(10)  # 10 Hz

    def pixel2base(self, p, depth=None):
        
        
        
        #depth = self.camera_height # depth_frame.get_distance(pixel_pick_and_place[0], pixel_pick_and_place[1])
        if depth is None:
            depth = self.camera_height

        camera_p = self.pixel2camera(p, depth)
        
       
        base_p = camera2base(self.camera_pos, self.camera_or, camera_p)

        return  MyPos(pose=base_p, orien=self.fix_or)
    
    def camera2pixel(self, point_3d):
        pixel = rs.rs2_project_point_to_pixel(self.intrinsic, point_3d)
        return pixel
    
    def pixel2camera(self, pixel_point, depth):
        pixel_point = [int(pixel_point[0]), int(pixel_point[1])]
        return rs.rs2_deproject_pixel_to_point(self.intrinsic, pixel_point, depth)



    def pnp_callback(self, pnp):
        print("Received pnp: %s", pnp.data)
        pnp = np.asarray(pnp.data)


        ### Post Process, Convert form pixel space to base space
        pixel_pnp = self.norm2pixel_pnp(pnp)
        self.pixel_pick_and_place(pixel_pnp[:2], pixel_pnp[2:], pick_depth_estimate=True)
        self.go_home()
        self.publish_observation()

    def reset_callback(self, reset):
        print("Received reset")
        self.go_home()
        self.publish_observation()
    
    def estimate_depth(self, depths, pixels):
        """
            Input: N depth images and N pixel positions on corresponding depth image.

            Return: an estimated depth value

            Process: get the median depth value of lowest 20% depth value around the target pixel in each depth image, 
            then get the median of these N values

        """

        # List to store median depths from each image
        median_depths = []
        
        # Process each depth image and pixel pair
        for depth, pixel in zip(depths, pixels):
            # Extract a window around the target pixel (e.g., 5x5 window)
            x, y = int(pixel[0]), int(pixel[1])
            y = depth.shape[1] - y
            window_size = 5
            half_window = window_size // 2
            window = depth[max(0, x-half_window):min(depth.shape[0], x+half_window+1),
                           max(0, y-half_window):min(depth.shape[1], y+half_window+1)]
            
            # Flatten the window and remove any invalid depths (e.g., 0 or negative values)
            valid_depths = window[window > 0].flatten()

            if len(valid_depths) > 0:
                # Sort the valid depths
                sorted_depths = np.sort(valid_depths)
                
                # Calculate the index for 20% of the sorted depths
                index_20_percent = max(1, int(0.2 * len(sorted_depths)))
                
                # Get the median of the lowest 20% depths
                lowest_20_percent = sorted_depths[:index_20_percent]
                median_depth = np.median(lowest_20_percent)
                
                median_depths.append(median_depth)
        
        # Calculate the final estimated depth as the median of all median depths
        if median_depths:
            estimated_depth = np.median(median_depths)
        else:
            estimated_depth = None  # or some default value
        
        return estimated_depth


    def estimate_depth_routine(self, pick_pixel):

        pick_camera_3d = self.pixel2camera(pick_pixel, self.camera_height)

        sample_y_offsets = [-0.1, -0.05, 0, 0.05, 0.1]
        depths = []
        rgbs = []
        target_pixels = []

        #print('pick_pixel', pick_pixel)

        for y_off in sample_y_offsets:
            tarpos = self.home_pos.copy()
            tarpos[1] += y_off
            self.go_pose(MyPos(pose=tarpos, orien=self.home_or), straight=False)
            rgb, depth = self.take_rgbd()
            depths.append(depth.copy())
            rgbs.append(rgb.copy())

            tmp_pick_camera_3d = pick_camera_3d.copy()
            tmp_pick_camera_3d[1] -= y_off

            target_pixel = self.camera2pixel(tmp_pick_camera_3d)
            target_pixels.append(target_pixel)

        #print('taget pixels', target_pixels)

        self.go_pose(MyPos(pose=self.home_pos, orien=self.home_or), straight=False)


        # Annotate RGBs with target pixels for debugging
        # annotated_rgbs = []
        # for rgb, pixel in zip(rgbs, target_pixels):
        #     annotated_rgb = rgb.copy()
        #     H, W = rgb.shape[:2]
        #     x, y = map(int, pixel)  # Ensure pixel coordinates are integers
        #     annotated_rgb[x, W-y] = [255, 255, 255]
        #     annotated_rgbs.append(annotated_rgb)

        # # Optionally, you can save or display these annotated images
        # for i, img in enumerate(annotated_rgbs):
        #     cv2.imwrite(f'annotated_rgb_{i}.png', img)

        return self.estimate_depth(depths, target_pixels)

    def pixel_pick_and_place(self, pick_pixel, place_pixel, pick_depth_estimate=False):
        
        estimated_depth = None
        if pick_depth_estimate:
            estimated_depth = self.estimate_depth_routine(pick_pixel)
            print('estimated_depth', estimated_depth)
            print('camera height', self.camera_height)
        
        if estimated_depth is None:
            estimated_depth = self.camera_height
        
        base_pick = self.pixel2base(pick_pixel, depth=estimated_depth)
        print('Coverted pick z', base_pick.pose[2])       
        base_place = self.pixel2base(place_pixel)



        base_pick.pose[2] = max(0, base_pick.pose[2]) + self.g2e_offset
        base_place.pose[2] += self.g2e_offset

        self.execute_pick_and_place(base_pick, base_place)
    
    def test_pick_and_place(self):
        self.go_home()
        self.take_cropped_rgbd()
        
        
        
        pixel_pnp_norm = np.asarray([-1, -1, 1, 1])
        #pixel_pnp_norm = np.asarray([-1, -1, -1, -1])
        #pixel_pnp_norm = np.asarray([0, 0, 0, 0])

        pixel_pnp = self.norm2pixel_pnp(pixel_pnp_norm)
        self.pixel_pick_and_place(pixel_pnp[:2], pixel_pnp[2:], 
                                  pick_depth_estimate=True)

        


    ######## MOCK PnP  #######
    def mock_publish_pnp(self, pnp):
        pnp_msg = PnP()
        pnp_msg.header = Header()
        pnp_msg.header.stamp = rospy.Time.now()
        pnp_msg.data = pnp
        self.mock_pnp_pub.publish(pnp_msg)
        self.rate.sleep()

    def mock_pnp_callback(self, pnp):
        pnp = np.asarray(pnp.data)
        print("Mock Received pnp: %s", pnp)


        ### Post Process, Convert form pixel space to base space
        pixel_pnp = self.norm2pixel_pnp(pnp)

        print('post pnp', pixel_pnp)
        
        # ###  Pixel2Base
        # base_pick = self.pixel2base(pixel_pnp[:2])
        # base_place = self.pixel2base(pixel_pnp[2:])

        # ## Execute
        #self.execute_pick_and_place(base_pick, base_place)

        self.go_home()
        self.publish_observation()


        ### Publish PnP
        self.mock_publish_pnp(np.random.rand(4))
        
    ######## End #######
    
    def post_process_depth(self, depth_frame):
        H, W = np.asanyarray(depth_frame.get_data()).shape[:2]
        #print('raw depth', H, W)
        depth_frame = self.decimation.process(depth_frame)
        depth_frame = self.depth_to_disparity.process(depth_frame)
        depth_frame = self.spatial.process(depth_frame)
        depth_frame = self.temporal.process(depth_frame)
        depth_frame = self.disparity_to_depth.process(depth_frame)
        depth_frame = self.hole_filling.process(depth_frame)

        depth_data = np.asarray(depth_frame.get_data()).astype(float)/1000
        depth_data = cv2.resize(depth_data, (W, H))

        
        

        ## Align depth to color, to fine tune.
        OW = -14
        OH = -10
        CH = int(H*0.72)
        CW = int(W*0.72)
        MH = int(H//2)
        MW = int(W//2)
        depth_data = depth_data[MH-CH//2+OH:MH+CH//2+OH, MW-CW//2+OW:MW+CW//2+OW]
        depth_data = cv2.resize(depth_data, (W, H))

        ## get the blak ones
        blank_mask = (depth_data == 0)


        ## substrat the ground truth
        # top_left = [0, 0, depth_data[0, 0]]
        # top_right = [1, 0, depth_data[-1, 0]]
        # bottom_left = [0, 1, depth_data[0, -1]]
        # bottom_right = [1, 1, depth_data[-1, -1]]
        # average_depth = (top_left[2] + top_right[2] + bottom_left[2] + bottom_right[2])/4.0
        # #print('avearge_depth', average_depth)
        # corner_values = {(0, 0): top_left[2], (1, 0): top_right[2], (0, 1): bottom_left[2], (1, 1): bottom_right[2]}
        # ground_depth = interpolate_image(H, W, corner_values)


        average_depth = self.cur_z + self.e2c_offz
        depth_data += blank_mask * (average_depth+0.005)
        
        #depth_data = (depth_data + 0.005) - ground_depth + average_depth
        
        
        depth_data = depth_data.clip(0, average_depth+0.02)
        self.depth_img = depth_data.copy()

        return depth_data
    
    def _initialize_robot(self):
        self.home_z = 0.6
        self.home_pos = [0.5, 0, self.home_z]

        moveit_commander.roscpp_initialize(sys.argv)
        self.robot = moveit_commander.RobotCommander()
        self.scene = moveit_commander.PlanningSceneInterface()
        
        self.arm_group = moveit_commander.MoveGroupCommander("bob_arm")
        self.arm_group.set_max_velocity_scaling_factor(0.3)
        self.arm_group.set_max_acceleration_scaling_factor(0.1)
        self.arm_group.set_planning_pipeline_id('pilz_industrial_motion_planner')
        self.arm_group.set_planner_id('PTP')
        # self.arm_group.set_planning_pipeline_id('ompl')
        # self.arm_group.set_planner_id('RRTstar')
        self.arm_group.set_pose_reference_frame("bob_link0")
        self.arm_group.set_end_effector_link("bob_link8")

        #self.gripper_group = moveit_commander.MoveGroupCommander("hand")
        self.default_joints = [0, -pi/4, 0, -3*pi/4, 0, pi/2, pi/4]

        self.gripper_client = actionlib.SimpleActionClient('/franka_gripper/move', franka_gripper.msg.MoveAction)
        self.gripper_client.wait_for_server()

        self.grasp_client = actionlib.SimpleActionClient('/franka_gripper/grasp', franka_gripper.msg.GraspAction)
        self.grasp_client.wait_for_server()

        cur_pos = self.arm_group.get_current_pose(end_effector_link="bob_link8")
        cur_pose = [cur_pos.pose.position.x,  cur_pos.pose.position.y, cur_pos.pose.position.z]
        self.cur_z = cur_pose[2]


        self.ros_sleep_time = 0.2

        self.open_width = 0.02
        self.close_width = 0.0001
        self.pick_raise_offset = 0.05
        self.place_raise_offset = 0.03
        self.g2e_offset = 0.112#halid gripper offset = 0.032 #pink short(0.021)#Tweezer,0.074, 0.0759#0.0448(Metal) #SHort pink with Metal = 0.0478#0.133# 0.115(original gripper) #0.135 # 0.113 orignal gripper ## to fine tune.# Tweezer final  0.112+0.0759
        self.fix_or = [0.9237820580963242, -0.38291837679374485, 
                       7.93796317786616e-05, 0.0004685635894043005] # [0, 0, 0, 0]

        self.home_or = self.fix_or
        #self.velocity = 0.08

    def _initialize_camera(self):
        
        self.e2c_offz = -0.04#-0.035 ## TODO: fine tune
        self.camera_offset = np.asarray([-0.125, -0.127, self.e2c_offz])#np.asarray([-0.12, -0.125, self.e2c_offz]) ### TODO: tune
        self.camera_pos = self.home_pos + self.camera_offset
        self.camera_or = [0, 1.0, 0.0, 0.0]
        self.camera_height = self.home_z + self.e2c_offz
        
        self.pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 30)
        config.enable_stream(rs.stream.color, 848, 480, rs.format.bgr8, 30)
        self.pipeline.start(config)
        align_to = rs.stream.color
        self.align = rs.align(align_to)


        ### Depth Camera Macros ###
        self.colorizer = rs.colorizer()
        self.decimation = rs.decimation_filter()
        self.decimation.set_option(rs.option.filter_magnitude, 2) #4
        self.depth_to_disparity = rs.disparity_transform(True)
        self.disparity_to_depth = rs.disparity_transform(False)
        self.spatial = rs.spatial_filter()
        self.spatial.set_option(rs.option.holes_fill, 2) #3
        self.spatial.set_option(rs.option.filter_magnitude, 5) #5
        self.spatial.set_option(rs.option.filter_smooth_alpha, 1) #1
        self.spatial.set_option(rs.option.filter_smooth_delta, 50) #50
        self.hole_filling = rs.hole_filling_filter()
        self.temporal = rs.temporal_filter()



        self.take_rgbd()

    def go_home(self):
        print('Going Home')
        self.open_gripper()
        self.arm_group.go(self.default_joints, wait=True)
        self.arm_group.stop()
        cur_pos = self.arm_group.get_current_pose(end_effector_link="bob_link8")
        # print('cur pose', cur_pos)
        # exit(1)
        self.go_pose(MyPos(pose=self.home_pos, orien=self.home_or), straight=False)
        self.grasp()
        self.open_gripper()

        print('Home position reached !!!')

    def go_pose(self, pose, straight=False):

            
        ros_pos = PoseStamped()
        target_pos = pose.pose
        target_orien = pose.orien
        ros_pos.pose.position.x = target_pos[0]
        ros_pos.pose.position.y = target_pos[1]
        ros_pos.pose.position.z = target_pos[2]
        ros_pos.pose.orientation.x = target_orien[0]
        ros_pos.pose.orientation.y = target_orien[1]
        ros_pos.pose.orientation.z = target_orien[2]
        ros_pos.pose.orientation.w = target_orien[3]
        
        
        if not straight:
            self.arm_group.set_pose_target(ros_pos, end_effector_link="bob_link8")
            go_success = self.arm_group.go(wait=True)
            print('Going success? {}'.format(go_success))
        else:
            (plan, fraction) = self.arm_group.compute_cartesian_path(
                                    [ros_pos.pose],   # waypoints to follow
                                    0.01,        # eef_step
                                    0.0)
            success = self.arm_group.execute(plan, wait=True)
            print('Execution success? ', success)
            
        self.arm_group.stop()
        self.arm_group.clear_pose_targets()
        cur_pos = self.arm_group.get_current_pose(end_effector_link="bob_link8")
        cur_pose = [cur_pos.pose.position.x,  cur_pos.pose.position.y, cur_pos.pose.position.z]

        self.cur_z = cur_pos.pose.position.z
        # print('\n################################')
        # print('cur pos {}, tar pos {}'.format(cur_pose, pose.pos))
        # d = np.linalg.norm(np.asarray(pose.pos) - np.asarray(cur_pose)) 
        # print('error distance', d)
        # print('################################\n')
        rospy.sleep(self.ros_sleep_time)
            


        


    def move_gripper(self, target_width):

         # Creates a goal to send to the action server.
        goal = franka_gripper.msg.MoveGoal()
        goal.width = target_width
        goal.speed = 0.1

        self.gripper_client.send_goal(goal)
        self.gripper_client.wait_for_result()
        result = self.gripper_client.get_result()
        print("Gripper result received: success=%s", result.success)
        return result


    def grasp(self):
        print('Grasp !!')
         
        # Creates a goal to send to the action server.
        goal = franka_gripper.msg.GraspGoal()
        goal.width = self.close_width
        goal.epsilon = franka_gripper.msg.GraspEpsilon(inner=0.001, outer=0.001)  # Correctly initialize epsilon
        goal.speed = 0.1
        goal.force = 20


        # rospy.loginfo("Sending goal: width=%s, epsilon.inner=%s, epsilon.outer=%s, speed=%s, force=%s",
        #             goal.width, goal.epsilon.inner, goal.epsilon.outer, goal.speed, goal.force)
        
        
        self.grasp_client.wait_for_server()

        # Sends the goal to the action server.
        self.grasp_client.send_goal(goal)

        #rospy.loginfo("Goal sent, waiting for result...")
        # Waits for the server to finish performing the action.
        self.grasp_client.wait_for_result()

        # Get the result
        result = self.grasp_client.get_result()
        
        #   rospy.loginfo("Result received: success=%s, error message=%s", result.success, result.error)

        # Prints out the result of executing the action
        return result 
    

    def open_gripper(self):
        print('Close Gripper')
        self.move_gripper(self.open_width)
        
        
    def get_pick_depth(self):
        _, depth_img = self.take_rgbd()
        
        depth = (depth_img - np.min(depth_img))/(np.max(depth_img) - np.min(depth_img))
        crop_depth_colormap = cv2.applyColorMap(np.uint8(255 * depth), cv2.COLORMAP_JET)
        
        cv2.imwrite('pick_depth_img.png', crop_depth_colormap)
        H = int(depth_img.shape[0]//2)
        sh = int(3.0/4*H)
        
        sw = int(1.0/4*H)
        w = 20
        #mid = int(depth_img.shape[0]//2)
        ret_depth = np.mean(depth_img[sh:sh+w, sw:sw+w])
        print('ret mean', np.mean(depth_img[sh:sh+w, sw:sw+w]))
        print('ret max', np.max(depth_img[sh:sh+w, sw:sw+w]))
        print('ret min', np.min(depth_img[sh:sh+w, sw:sw+w]))
        return ret_depth
        


    def execute_pick_and_place(self, pick, place):
        print('Starting Pick {} and Place {}'.format(pick.pose, place.pose))

        # Open Gripper
        self.open_gripper()

        # Go to Pick Position
        print('Going to Pick Position')
        pick_raise_pos = pick.pose + np.asarray([0, 0, self.pick_raise_offset])
        self.go_pose(
            MyPos(pose=pick_raise_pos, orien=pick.orien), straight=True)

        ### Get pick depth
        pick_pos = pick.pose.copy()
        
        self.go_pose(MyPos(pose=pick_pos, orien=pick.orien))


        # Close Gripper
        self.grasp()
        

        # Raise after Pick
        self.go_pose(
            MyPos(pose=pick_raise_pos, orien=pick.orien)
        )

        # Move to Place Position
        print('Going to Place Position')
        place_raise_pos = place.pose + np.asarray([0, 0, self.place_raise_offset])
        self.go_pose(
            MyPos(pose=place_raise_pos, orien=place.orien), straight=True
        )

        # Open Gripper
        self.open_gripper()

    def _crop_image(self, image):
        H, W = image.shape[:2]
        min_val = int(min(H*0.9, W*0.9))
        self.px_off = (W - min_val)//2
        self.py_off = (H - min_val)//2
        self.resol = min_val
        mid_x =  W//2
        mid_y = H//2
        image = image[mid_y-min_val//2:mid_y+min_val//2, mid_x-min_val//2:mid_x+min_val//2]
        return image
    
    def take_rgbd(self):

        for _ in range(10):
            frames = self.pipeline.wait_for_frames()
        
            aligned_frames = self.align.process(frames)
            depth_frame = aligned_frames.get_depth_frame()
            color_frame = aligned_frames.get_color_frame()
            self.intrinsic = color_frame.profile.as_video_stream_profile().intrinsics
            depth_image = np.asanyarray(depth_frame.get_data())
            color_image = np.asanyarray(color_frame.get_data())

            # Convert images to numpy arrays
            depth_frame = frames.get_depth_frame()
            # raw_depth = np.asanyarray(depth_frame.get_data())

            

            depth_image = self.post_process_depth(depth_frame)
        
        return color_image, depth_image

    def take_cropped_rgbd(self):

        color_image, depth_image = self.take_rgbd()

         # Apply colormap on depth image (image must be converted to 8-bit per pixel first)
        depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET)
        # Stack both images horizontally
        images = np.hstack((color_image, depth_colormap))
        cv2.imwrite('raw_rgbd.jpg', images)

        cropped_color = self._crop_image(color_image)
        cropped_depth = self._crop_image(depth_image)
        ## TODO: publish cropped color and cropped depth
        crop_depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(cropped_depth, alpha=0.03), cv2.COLORMAP_JET)
        cropped_images = np.hstack((cropped_color, crop_depth_colormap))
        cv2.imwrite('cropped_rgb.jpg', cropped_images)


        return cropped_color, cropped_depth

    def get_observation(self):
        
        color_image, depth_image = self.take_cropped_rgbd()

        return {
            'depth': depth_image,
            'color': color_image
        }


    def publish(self, observation):
        
        if not rospy.is_shutdown():
            # Simulate an RGB image
            rgb_image = observation['color']
            depth_image = observation['depth']

            # Convert OpenCV images to ROS messages
            rgb_msg = self.bridge.cv2_to_imgmsg(rgb_image, encoding="bgr8")
            depth_msg = self.bridge.cv2_to_imgmsg(depth_image, encoding="64FC1")

            # Create the custom RGBD message
            rgbd_msg = Observation()
            rgbd_msg.header = Header()
            rgbd_msg.header.stamp = rospy.Time.now()
            rgbd_msg.rgb_image = rgb_msg
            rgbd_msg.depth_image = depth_msg

            # Publish the message
            print("Publishing RGBD image")
            self.pub.publish(rgbd_msg)
            self.rate.sleep()
            return True
        else:
            print('Cannot pubslih. Please run roscore !!!!')
            return False

    def publish_observation(self):
        obs = self.get_observation()
        #self.depth_img = obs['depth']
        self.publish(obs)

    def run(self):
        
        self.go_home()
        self.take_rgbd()
        #self.publish_observation()
        if self.is_mock:
            self.mock_publish_pnp([0, 0, 0, 0])

        rospy.spin()

    def norm2pixel_pnp(self, pnp):
        print('resol', self.resol)
        print('py off', self.py_off)
        print('px off', self.py_off)
        pix_pnp = (pnp+1)/2 * self.resol
        pix_pnp[0] += self.py_off
        pix_pnp[2] += self.py_off
        pix_pnp[1] += self.px_off
        pix_pnp[3] += self.px_off
        print('!!!Pixel Pnp', pix_pnp)
        return pix_pnp


    

    def test_camera(self, crop=False):
        qspnp.go_home()
        while True:
            if crop:
                color, depth = self.take_cropped_rgbd()
            else:
                color, depth = self.take_rgbd()

            
            
            depth = (depth - np.min(depth))/(np.max(depth) - np.min(depth))
            depth = np.uint8(255 * depth)
            crop_depth_colormap = cv2.applyColorMap(depth, cv2.COLORMAP_JET)

            # Interpolation factor (adjust to control the blend)
            alpha = 0.5  # Example: 0.5 means equal contribution from both images

            # Interpolate between color and depth images
            interpolated_image = cv2.addWeighted(color, alpha, crop_depth_colormap, 1 - alpha, 0)



            cropped_images = np.hstack((color, crop_depth_colormap, interpolated_image))
            #cv2.imwrite('cropped_rgb.jpg', cropped_images)

            # Show images
            cv2.namedWindow('RealSense', cv2.WINDOW_AUTOSIZE)
            cv2.imshow('RealSense', cropped_images)
            key = cv2.waitKey(1)
            # Press esc or 'q' to close the image window
            if key & 0xFF == ord('q') or key == 27:
                cv2.destroyAllWindows()
                break

    # def mock(self):
    #     self.go_home()
    #     self.publish_observation()



if __name__ == '__main__':
    try:
        qspnp = QuasiStaticPickAndPlace(mock=False)
        qspnp.run()
        #qspnp.test_pick_and_place()
        #qspnp.test()
        #qspnp.test()
        #qspnp.test_communication()
        #qspnp.go_home()
        # qspnp.go_home()
        # qspnp.go_home()
        #qspnp.test_camera(crop=True)
    except rospy.ROSInterruptException:
        pass
