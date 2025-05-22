#!/usr/bin/env python3

import rospy
import actionlib
import franka_gripper.msg
import sys

def move_client(target_width):
    # Creates the SimpleActionClient, passing the type of the action
    # (MoveAction) to the constructor.
    client = actionlib.SimpleActionClient('/franka_gripper/move', franka_gripper.msg.MoveAction)

    rospy.loginfo("Waiting for action server to start...")
    # Waits until the action server has started up and started listening for goals.
    client.wait_for_server()
    rospy.loginfo("Action server started.")

    # Creates a goal to send to the action server.
    goal = franka_gripper.msg.MoveGoal()
    goal.width = target_width
    goal.speed = 0.1

    rospy.loginfo("Sending goal: width=%s, speed=%s",
                  goal.width, goal.speed)
    
    # Sends the goal to the action server.
    client.send_goal(goal)

    rospy.loginfo("Goal sent, waiting for result...")
    # Waits for the server to finish performing the action.
    client.wait_for_result()

    # Get the result
    result = client.get_result()
    
    rospy.loginfo("Result received: success=%s", result.success)

    # Prints out the result of executing the action
    return result  # A MoveResult

if __name__ == '__main__':
    try:
        # Check if the target width argument is provided
        if len(sys.argv) < 2:
            print("Usage: move_client.py <target_width>")
            sys.exit(1)

        # Parse the target width argument
        target_width = float(sys.argv[1])
        
        # Initializes a rospy node so that the SimpleActionClient can publish and subscribe over ROS.
        rospy.init_node('move_client_py')
        result = move_client(target_width)
        if result:
            print("Success: ", result.success)
        else:
            print("No result returned from the action server.")
    except rospy.ROSInterruptException:
        print("Program interrupted before completion", file=sys.stderr)
    except AttributeError:
        print("An error occurred with the result, possibly an incorrect field name.", file=sys.stderr)
    except ValueError:
        print("Invalid target width. Please provide a numeric value.", file=sys.stderr)
