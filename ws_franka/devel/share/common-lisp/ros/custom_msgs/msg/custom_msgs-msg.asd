
(cl:in-package :asdf)

(defsystem "custom_msgs-msg"
  :depends-on (:roslisp-msg-protocol :roslisp-utils :sensor_msgs-msg
               :std_msgs-msg
)
  :components ((:file "_package")
    (:file "Observation" :depends-on ("_package_Observation"))
    (:file "_package_Observation" :depends-on ("_package"))
    (:file "PnP" :depends-on ("_package_PnP"))
    (:file "_package_PnP" :depends-on ("_package"))
    (:file "Reset" :depends-on ("_package_Reset"))
    (:file "_package_Reset" :depends-on ("_package"))
  ))