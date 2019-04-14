#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#  Copyright (c) 2019, CNRS-LAAS
#  All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice, this
#  list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above copyright notice,
#  this list of conditions and the following disclaimer in the documentation
#  and/or other materials provided with the distribution.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
#  FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
#  DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#  SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
#  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
#  OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import rospy

import zmq
import threading
import time
import binascii
import numpy as np
import datetime
import fire_rs.neptus_interface
import fire_rs.firemodel.propagation
import fire_rs.simulation.wildfire
import fire_rs.libwden as libwden
import serialization
from supersaop.msg import Plan, Timed2DPointStamped, WildfireMap, MeanWindStamped
from std_msgs.msg import Header
from geometry_msgs.msg import Point

# WDEN will listen on this address and ports
URI = "tcp://192.168.255.1"
# URI = "tcp://localhost"
SUB_PORT = 4000
PUB_PORT = 5000

# Define incoming messages filters
# Options are:
#       - Message type filter
#       - Message type filter + destination filter
#       - Message type filter + destination filter + source filter
MESSAGE_TYPE_FILTER = b'\x00\x03'
DESTINATION_FILTER = b'\x33\x33\x33\x33'
SOURCE_FILTER = b'\x22\x22\x22\x22'

# Define message to publish
MESSAGE_TYPE = b'\x00\x03'
DESTINATION = b'\x33\x33\x33\x33'
SOURCE = b'\x22\x22\x22\x22'
NOTIFICATION = "Example message".encode('utf-8')


def main():
    def pub_alarm(posx, posy):
        start_wind = (5.0, 1 * np.pi / 4)
        environment = fire_rs.firemodel.propagation.Environment(
            area, start_wind[0], start_wind[1], fire_rs.geodata.environment.World(
                **world_paths,
                landcover_to_fuel_remap=fire_rs.geodata.environment.EVERYTHING_FUELMODEL_REMAP))
        rw = fire_rs.simulation.wildfire.RealWildfire(
            datetime.datetime.fromtimestamp(
                (rospy.Time.now() - rospy.Duration.from_sec(60 * 30)).to_sec()),
            environment)

        ignitions = [(posx, posy), ]

        ignitions_cell = [rw.fire_map.array_index(p) for p in ignitions]

        rw.ignite((posx, posy))
        rospy.loginfo("ignite %s", str((posx, posy)))
        rw.propagate(datetime.timedelta(minutes=60.))
        rospy.loginfo("propagate 60 min")
        wind = MeanWindStamped(header=Header(stamp=rospy.Time.now()), speed=start_wind[0],
                               direction=start_wind[1])
        wind_pub.publish(wind)
        rospy.loginfo("Notify wind")
        rospy.loginfo(wind)

        firemap = rw.perimeter(rospy.Time.now().to_sec()).geodata
        wildfire_message = WildfireMap(header=rospy.Header(stamp=rospy.Time.now()),
                                       raster=serialization.raster_msg_from_geodata(
                                           firemap,
                                           layer="ignition"))

        map_pub.publish(wildfire_message)
        rospy.loginfo("Notify alarm map at 30 min")
        rospy.loginfo(wildfire_message)

        firemap.data["ignition"][firemap.data["ignition"] == np.inf] = 0
        firemap.data["ignition"][firemap.data["ignition"].nonzero()] = 65535
        firemap.write_to_image_file("/home/rbailonr/fire.png", "ignition")

        fire_pos = Timed2DPointStamped(header=Header(stamp=rospy.Time.now()),
                                       x=posx, y=posy,
                                       t=rospy.Time.now() - rospy.Duration.from_sec(60 * 30))

        alarm_pub.publish(fire_pos)
        rospy.loginfo("Notify alarm point")
        rospy.loginfo(fire_pos)

    def wden_receive_task():
        # Generate subscriber
        subscriber = libwden.gen_subscriber_wfilter(
            context,
            URI,
            PUB_PORT,
            libwden.generate_topic_filter(
                message_filter=MESSAGE_TYPE_FILTER,
                destination_filter=DESTINATION_FILTER,
                source_filter=SOURCE_FILTER,
            )
        )
        # Without filtering, you'll receive your own messages too.
        subscriber = libwden.gen_subscriber(
            context,
            URI,
            PUB_PORT
        )

        while not rospy.is_shutdown():
            # Wait for messages
            message = libwden.receive_message(subscriber)

            # Print message data
            print("Incoming message (filtered): " + str(binascii.hexlify(message)))
            print("Incoming message (utf8): " + str(message[11:].decode("utf-8")))
            if message[11:13] == b"T\xfe":
                print("ACK")
            else:
                print("This is a position")
            # TODO: decode alarm and PlanControl ACK

    def on_sub_plan(msg):
        t = serialization.saop_trajectories_from_plan_msg(msg)
        for traj in t:
            if traj.length() > 0.:
                pass
                # Convert to plan_spec and serialize respecting 192byte limit
                # self.ccu.start_trajectory(traj, traj.conf.uav.name)
                msg = "PlanControl".encode("utf-8")
                msg = fire_rs.neptus_interface.demo1_serialize_plan(traj, 0x0c10, 3035)
                print(msg)
                print(len(msg))
                libwden.send_message(
                    publisher,
                    MESSAGE_TYPE,
                    SOURCE,
                    DESTINATION,
                    msg)

    # Generate 0MQ context
    context = libwden.init_wden()

    recv_th = threading.Thread(target=wden_receive_task, daemon=True)
    recv_th.start()

    publisher = libwden.gen_publisher(context, URI, SUB_PORT)

    rospy.init_node("wden_client")
    rospy.loginfo("Starting {}".format("wden_client"))

    area = rospy.get_param("area")

    world_paths = None
    has_dem_dir = rospy.has_param("dem_dir")
    has_landcover_dir = rospy.has_param("landcover_dir")
    has_wind_dir = rospy.has_param("wind_dir")

    if has_dem_dir and has_landcover_dir and has_wind_dir:
        # Either all are defined ...
        world_paths = {}
        world_paths["elevation_path"] = rospy.get_param("dem_dir")
        world_paths["landcover_path"] = rospy.get_param("landcover_dir")
        world_paths["wind_path"] = rospy.get_param("wind_dir")
    else:
        # ... or none of them
        if has_dem_dir or has_landcover_dir or has_wind_dir:
            # This is an error
            rospy.logerr("dem_dir, landcover_dir and wind_dir have to be defined all toghether "
                         "or not be defined at all.")
            rospy.signal_shutdown("Geographic data directories are not well defined")
        else:
            # data folders are implicitely defined
            pass

    plan_sub = rospy.Subscriber("plan", Plan, on_sub_plan, queue_size=1)
    map_pub = rospy.Publisher("wildfire_observed", WildfireMap, queue_size=1)
    alarm_pub = rospy.Publisher("wildfire_point", Timed2DPointStamped, queue_size=1)
    wind_pub = rospy.Publisher("mean_wind", MeanWindStamped, queue_size=1,
                               tcp_nodelay=True)
    pub_alarm(2786284.0 + 1500, 2306526.0 + 1500)
    rospy.sleep(1.)

    # Publish product notification
    r = rospy.Rate(10.)
    while not rospy.is_shutdown():
        # Publish notification
        # libwden.send_message(
        #     publisher,
        #     MESSAGE_TYPE,
        #     SOURCE,
        #     DESTINATION,
        #     NOTIFICATION)

        r.sleep()


if __name__ == "__main__":
    input()
    main()