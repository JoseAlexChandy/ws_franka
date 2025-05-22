import os

import rospy
import numpy as np
import cv2


from custom_msgs.msg import Observation, PnP, Reset
from std_msgs.msg import Header
import argparse
from cv_bridge import CvBridge, CvBridgeError

def draw_pick_and_place(image, start, end, color=(143, 201, 58)):
    ## adjust thickness regarding to the image size
    thickness = max(1, int(image.shape[0] / 100))
    print('start', start, 'end', end)
    print('image shape', image.shape)
    
    image = cv2.arrowedLine(
        cv2.UMat(image), 
        start, 
        end,
        color, 
        thickness)
    return image.get().astype(int).clip(0, 255)

class HumanPickAndPlace:
    def __init__(self, task, steps=20):
        print('Max steps {}'.format(steps))
         ### Initialise Ros
        rospy.init_node('franka_human_interface', anonymous=True)
        self.img_sub = rospy.Subscriber('/observation', Observation, self.img_callback)
        self.pnp_pub = rospy.Publisher('/pnp', PnP, queue_size=10)
        self.reset_pub = rospy.Publisher('/reset', Reset, queue_size=10)

        self.rate = rospy.Rate(10)
        self.bridge = CvBridge()
        self.resolution = (256, 256)
        self.fix_steps = steps

        self.save_dir = './human_data/{}'.\
            format(task)

        os.makedirs(self.save_dir, exist_ok=True)

        print('Finish Init')

    def publish_action(self, pnp):
        print('Publish Action')
        pnp_msg = PnP()
        pnp_msg.header = Header()
        pnp_msg.header.stamp = rospy.Time.now()
        
        
        pnp_msg.data = (pnp[1], -pnp[0], pnp[3], -pnp[2])
        #pnp_msg.data = (-1, -1, 1, 1)
        self.pnp_pub.publish(pnp_msg)
        self.rate.sleep()

    def publish_reset(self):
        print('Publish Reset')
        reset_msg = Reset()
        reset_msg.header = Header()
        reset_msg.header.stamp = rospy.Time.now()
        self.reset_pub.publish(reset_msg)
        self.rate.sleep()

    def save_step(self, state):
        rgb = state['observation']['rgb']
        depth = state['observation']['depth']
        #mask = state['observation']['mask']

        depth = (depth - np.min(depth))/(np.max(depth) - np.min(depth))
        depth = cv2.applyColorMap(np.uint8(255 * depth), cv2.COLORMAP_AUTUMN)
        
        save_dir = os.path.join(self.save_dir, self.trj_name, 'step_{}'.format(str(self.step)))
        os.makedirs(save_dir, exist_ok=True)

        cv2.imwrite('{}/rgb.png'.format(save_dir, self.step), rgb)
        cv2.imwrite('{}/depth.png'.format(save_dir, self.step), depth)
        #cv2.imwrite('{}/mask.png'.format(save_dir, self.step), mask.astype(np.uint8)*255)


        os.makedirs('tmp', exist_ok=True)
        cv2.imwrite('tmp/rgb.png', rgb)
        cv2.imwrite('tmp/depth.png', depth)
        #cv2.imwrite('tmp/mask.png', mask.astype(np.uint8)*255)
        

        if 'action' in state:
            action = state['action']
            action_image = state['action_image'] 
            cv2.imwrite('{}/action_image.png'.format(save_dir,self.step), action_image)
            cv2.imwrite('tmp/action_image.png', action_image)
            np.save('{}/action.npy'.format(save_dir, self.step), action)

    def img_callback(self, data):

        rgb_image = self.bridge.imgmsg_to_cv2(data.rgb_image, "bgr8")
        depth_image = self.bridge.imgmsg_to_cv2(data.depth_image, "64FC1")
        depth_image = depth_image.astype(np.float32)


        input_state = self.post_process(rgb_image, depth_image)

        if self.step == -1:
            self.step += 1
        elif self.step >= self.fix_steps-1:
            self.step += 1
            self.save_step(input_state)#
            self.reset()
            return
        else:
            #self.agent.update(input_state, self.last_action)#
            self.step += 1
        print('Step {}'.format(self.step))
              
        action = self.act(input_state)
        self.last_action = action

        ### save action image ###
        pixel_actions = ((action + 1)/2*self.resolution[0]).astype(int).reshape(4)
        action_image = draw_pick_and_place(
            input_state['observation']['rgb'], 
            tuple(pixel_actions[:2]), 
            tuple(pixel_actions[2:]),
            color=(0, 255, 0))
        
        input_state['action'] = action.reshape(4)#
        input_state['action_image'] = action_image
        self.save_step(input_state)

        ## publish action
        self.publish_action(action.reshape(4))

    def act(self, state):
        """
        Pop up a window shows the RGB image, and user can click on the image to
        produce normalised pick-and-place action ranges from [-1, 1]
        """
        rgb = state['observation']['rgb']
        
        # Create a copy of the image to draw on
        img = rgb.copy()
        
        # Store click coordinates
        clicks = []
        
        def mouse_callback(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                clicks.append((x, y))
                cv2.circle(img, (x, y),2, (0, 255, 0), -1)
                cv2.imshow('Click Pick and Place Points', img)
        
        cv2.imshow('Click Pick and Place Points', img)
        cv2.setMouseCallback('Click Pick and Place Points', mouse_callback)
        
        while len(clicks) < 2:
            cv2.waitKey(1)
        
        cv2.destroyAllWindows()
        
        # Normalize the coordinates to [-1, 1]
        height, width = rgb.shape[:2]
        pick_x, pick_y = clicks[0]
        place_x, place_y = clicks[1]
        
        normalized_action = [
            (pick_x / width) * 2 - 1,
            (pick_y / height) * 2 - 1,
            (place_x / width) * 2 - 1,
            (place_y / height) * 2 - 1
        ]
        
        return np.array(normalized_action)

    def reset(self):
        self.step = -1
        self.last_action = None

        ### ask if continue for new experiment
        
        while True:
            is_continue = input('Continue for a new trial? (y/n): ')
            if is_continue == 'n':
                rospy.signal_shutdown('Finish Trial')
                exit()
            elif is_continue == 'y':
                self.trj_name = input('Enter Trial Name: ')
                break
            else:
                print('Invalid input')
                continue


        self.publish_reset()

    def run(self):
        print('Start running ....')
        self.reset()
        rospy.spin()



    def post_process(self, rgb, depth):

        	
        #print(rgb.shape) 
        #print(depth.shape) 
        rgb = cv2.resize(rgb, self.resolution)
        depth = cv2.resize(depth, self.resolution) 
      

        state = {
            'observation': {
                'rgb': rgb.copy(),
                'depth': depth.copy(),
                #'mask': mask.copy()
            }
        }

        return state


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', default='flattening')
    parser.add_argument('--log_dir', default='./human_data')

    return parser.parse_args()

if __name__ == "__main__":
        
    args = parse_arguments()

    ### Initialise Agent ####
    
    if args.task == 'all-corner-inward-folding':
        max_steps = 4
    elif args.task == 'corners-edge-inward-folding':
        max_steps = 6
    elif args.task == 'diagonal-cross-folding':
        max_steps = 2
    elif args.task == 'double-side-folding':
        max_steps = 8
    elif args.task == 'rectangular-folding':
        max_steps = 4
    elif args.task == 'flattening':
        max_steps = 20
 


    ### Run Sim2Real ###
    try:
        sim2real = HumanPickAndPlace(args.task, max_steps)
        sim2real.run()
    except rospy.ROSInterruptException:
        pass   
