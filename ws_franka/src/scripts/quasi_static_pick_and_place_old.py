from grasp_benchmark.utils.ros_utils import *
from grasp_benchmark.utils.ros_utils_real import *
from alr_sim.sims.SimFactory import SimRepository

import numpy as np
from collections import namedtuple
import pyrealsense2 as rs
if (not hasattr(rs, 'intrinsics')):
    import pyrealsense2.pyrealsense2 as rs
from scipy.spatial.transform import Rotation as R

NUMBER_OF_CANDIDATES = 1
global_scene = None

Pose = namedtuple('Pose', ['pos', 'orien'])

def camera2base(camera_pos, camera_orientation_quat, object_pos_cam):
    # Convert the quaternion to a rotation matrix
    r = R.from_quat(camera_orientation_quat)
    rotation_matrix = r.as_matrix()

    # Convert the object position from camera frame to robot base frame
    object_pos_cam = np.array(object_pos_cam)
    object_pos_base = rotation_matrix @ object_pos_cam + np.array(camera_pos)

    return object_pos_base

def interpolate_positions(start_pos, target_pos, num_points=100):
    """
    Generate interpolated positions between start and target positions.
    """
    return np.linspace(start_pos, target_pos, num_points)

class QausiStaticPickAndPlace:

    def __init__(self):
        sim_factory = SimRepository.get_factory("sl")
        s = sim_factory.create_scene()
        self.robot = sim_factory.create_robot(s, robot_name="bob")
        s.start()
        self.robot.use_inv_dyn = False
        self.wait_time = 0.5
        self.velocity = 0.08
        
        self.camera_height = 0.8
        self.e2c_offz = 0.1 ## TODO: tune
        self.home_pos = [0.35, 0, self.camera_height-self.e2c_offz]
        self.home_or = [0.0, 1.0, 0.0, 0.0]
        
        self.camera_offset = np.asarray([-0.05, -0.05, self.e2c_offz]) ### TODO: tune
        self.camera_pos = self.home_pos + self.camera_offset

        self.camera_or = [0.0, 1.0, 0.0, 0.0]

        self.robot.robot_logger.max_time_steps = 100000000
        self.robot.receiveState()
        self.long_duration = 20
        self.short_duration = 2
        # self.medium_dration = 6
        self.wait_time = 1
        self.gripper_open = 0.06
        self.gripper_close = 0
        self.close_duration = 5
        self.pick_raise_offset = 0.05
        self.place_raise_offset = 0.05
        self.fix_z = 0.02
        self.fix_or = [0.0, 1.0, 0.0, 0.0]

        self._initialise_camera()
    
    def _initialise_camera(self):

        self.camera_pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        self.camera_pipeline.start(config)

        profile = self.camera_pipeline.get_active_profile()
        depth_sensor = profile.get_device().first_depth_sensor()
        depth_scale = depth_sensor.get_depth_scale()

        align_to = rs.stream.color
        self.camera_align = rs.align(align_to)

    def go_home(self):
        print('Going Home')
        self.robot.receiveState()
        self.robot.wait(self.wait_time)
        self.robot.gotoCartPositionAndQuat(self.home_pos, self.home_or, duration=self.long_duration)
        
        self.robot.wait(self.wait_time)
        self.robot.receiveState()
        print('Home again')
        self.robot.gotoCartPositionAndQuat(self.home_pos, self.home_or, duration=self.short_duration)
        self.robot.receiveState()
        self.robot.wait(self.wait_time)
        print('Finished home')

    

    def move_in_straight_line(self, start_pos, target_pos, num_points=500):
        """
        Move the end-effector from start_pos to target_pos in a straight line.
        """
        interpolated_positions = interpolate_positions(start_pos, target_pos, num_points)
        for pos, pos1 in zip(interpolated_positions, interpolated_positions[1:]):
            self.robot.receiveState()
            dur = np.linalg.norm(pos1-pos)/self.velocity
            self.robot.gotoCartPositionAndQuat(pos1, self.fix_or, duration=dur)
        
    def execute_pick_and_place(self, pick, place):
        
        
        ### Go to Pick
        print('Open Gripper')
        self.robot.receiveState()
        self.robot.set_gripper_width = self.gripper_open
        self.robot.wait(self.wait_time)

        print('Go to Pick')
        self.robot.receiveState()
        pick_raise_pos = pick.pos.copy()
        pick_raise_pos[2] += self.pick_raise_offset
        self.robot.gotoCartPositionAndQuat(pick_raise_pos, pick.orien, duration=self.long_duration)
        self.robot.wait(self.wait_time)

        self.robot.receiveState()
        self.robot.gotoCartPositionAndQuat(pick.pos, pick.orien, duration=self.short_duration)
        self.robot.wait(self.wait_time)
        
        print('Close Gripper')
        self.robot.receiveState()
        self.robot.close_fingers(duration=self.close_duration)
        self.robot.wait(1)
        

        pick_raise_pos = pick.pos.copy()
        pick_raise_pos[2] += self.pick_raise_offset
        self.robot.receiveState()
        self.robot.gotoCartPositionAndQuat(pick_raise_pos, pick.orien, duration=self.short_duration)
        self.robot.wait(self.wait_time)


        ### Go to Place
        print('Go to Place')
        place_raise_pos = place.pos.copy()
        place_raise_pos[2] += self.place_raise_offset
        self.robot.receiveState()
        # distance = np.linalg.norm(place_raise_pos-pick_raise_pos)
        # dur_pick2place = distance/self.velocity
        # print('duration', dur_pick2place)
        # self.robot.gotoCartPositionAndQuat(place_raise_pos, place.orien, duration=dur_pick2place)
        self.move_in_straight_line(pick_raise_pos, place_raise_pos)
        self.robot.wait(self.wait_time)

        self.robot.receiveState()
        self.robot.gotoCartPositionAndQuat(place.pos, place.orien, duration=self.short_duration)
        self.robot.wait(self.wait_time)

        print('Open Gripper')
        self.robot.receiveState()
        self.robot.set_gripper_width = self.gripper_open
        self.robot.wait(1)

        self.robot.receiveState()
        self.robot.gotoCartPositionAndQuat(place_raise_pos, place.orien, duration=self.short_duration)
        self.robot.wait(self.wait_time)
        #self.robot.receiveState()
    
    def _crop_image(self, image):
        H, W = image.shape[:2]
        min_val = min(H, W)
        self.px_off = (W - min_val)//2
        self.py_off = (H - min_val)//2
        self.resol = min_val
        mid_x =  W//2
        mid_y = H//2
        image = image[mid_y-min_val//2:mid_y+min_val//2, mid_x-min_val//2:mid_x+min_val//2]
        return image

    def take_picture(self):
        print('Taking Image')
        frame = self.camera_pipeline.wait_for_frames()
        aligned_frame = self.camera_align.process(frame)
        depth_frame = aligned_frame.get_depth_frame()
        color_frame = aligned_frame.get_color_frame()
        depth_intrinsic = depth_frame.profile.as_video_stream_profile().intrinsics

        # Show images
        depth_image = np.asanyarray(depth_frame.get_data())

        color_image = np.asanyarray(color_frame.get_data())

        print('depth_image shape:', depth_image.shape)
        print('color_image shape:', color_image.shape)
        print('intrinsics', depth_intrinsic)

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

        ## TODO: subscribe for 4 pixel values [-1, 1]
        re_pnp = np.asarray([-1, -1, 1, 1])
        pix_pnp = (re_pnp+1)/2 * self.resol
        pix_pnp[0] += self.py_off
        pix_pnp[2] += self.py_off
        pix_pnp[1] += self.px_off
        pix_pnp[3] += self.px_off


        print('pix_pnp', pix_pnp)

        pick_depth = self.camera_height # depth_frame.get_distance(pixel_pick_and_place[0], pixel_pick_and_place[1])
        place_depth = self.camera_height # depth_frame.get_distance(pixel_pick_and_place[2], pixel_pick_and_place[3])

        # Convert form pixel space to base space
        camera_pick = rs.rs2_deproject_pixel_to_point(depth_intrinsic,
            pix_pnp[:2],pick_depth)
        
        camera_place = rs.rs2_deproject_pixel_to_point(depth_intrinsic,
            pix_pnp[2:],place_depth)

        base_pick = camera2base(self.camera_pos, self.camera_or, camera_pick)
        base_pick[2] += 0.02
        print('base pick', base_pick)

        base_place = camera2base(self.camera_pos, self.camera_or, camera_place)
        base_place[2] += 0.02
        print('base_place', base_place)

        return base_pick, base_place
    
    def run(self):
        step = -1
        while True:
            user_input = input('Press [y/n] to continue for step {}: '.format(step+1))
            if user_input == 'n':
                break
            elif user_input != 'y':
                continue
            else:
                step += 1

            # Go home 
            self.go_home()

            # Take pictures
            
            base_pick, base_place = self.take_picture()


            ## Execture
            self.execute_pick_and_place(
                Pose(pos=base_pick, orien=self.fix_or),
                Pose(pos=base_place, orien=self.fix_or))
            


#////////////////////////////////////////////////////////////////////////////////

def main():
    manipilation = QausiStaticPickAndPlace()
    manipilation.run()
   

if __name__ == "__main__":
    main()
